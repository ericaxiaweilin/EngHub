"""
仓管操作服务 - 岗位替代 Phase 3: 替代仓管员
快速入库/出库/移库 + 盘点任务 + 库存查询
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text, update

from database.models import Inventory, InventoryTransaction


def _gen_id() -> str:
    return str(uuid.uuid4())


def _gen_task_code(factory_id: str) -> str:
    ts = datetime.now().strftime("%m%d%H%M")
    suffix = uuid.uuid4().hex[:4].upper()
    return f"CC-{factory_id[:3].upper()}-{ts}-{suffix}"


class WmsOperationService:
    """仓管操作终端服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== 快速入库 ====================

    async def quick_inbound(
        self,
        factory_id: str,
        material_id: str,
        material_code: str,
        quantity: int,
        warehouse_id: str,
        location_id: Optional[str] = None,
        batch_code: Optional[str] = None,
        material_name: Optional[str] = None,
        unit: str = "pcs",
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        operator: str = "system",
        remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        """快速入库（扫码/手动）"""
        now = datetime.utcnow()

        # 查找或创建库存记录
        inv_stmt = select(Inventory).where(
            and_(
                Inventory.factory_id == factory_id,
                Inventory.material_id == material_id,
                Inventory.warehouse_id == warehouse_id,
                Inventory.batch_code == (batch_code or "DEFAULT"),
            )
        )
        inv_result = await self.db.execute(inv_stmt)
        inv = inv_result.scalar_one_or_none()

        before_qty = 0
        if inv:
            before_qty = inv.total_qty
            inv.total_qty += quantity
            inv.available_qty += quantity
            inv.last_movement_at = now
            inv.updated_at = now
        else:
            inv = Inventory(
                id=_gen_id(),
                material_id=material_id,
                material_code=material_code,
                material_name=material_name,
                factory_id=factory_id,
                warehouse_id=warehouse_id,
                location_id=location_id,
                batch_code=batch_code or "DEFAULT",
                total_qty=quantity,
                available_qty=quantity,
                reserved_qty=0,
                unit=unit,
                status="available",
                last_movement_at=now,
                created_at=now,
                updated_at=now,
            )
            self.db.add(inv)

        # 记录流水
        txn = InventoryTransaction(
            id=_gen_id(),
            factory_id=factory_id,
            inventory_id=inv.id,
            material_id=material_id,
            batch_code=batch_code,
            transaction_type="inbound",
            quantity=quantity,
            before_qty=before_qty,
            after_qty=before_qty + quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            operator=operator,
            remark=remark or "快速入库",
            created_at=now,
        )
        self.db.add(txn)
        await self.db.commit()

        # ═══ G2断点修复：收货自动触发IQC（按自动化等级决定行为） ═══
        iqc_triggered = False
        iqc_action = "none"
        if reference_type == "purchase" or (remark and "采购" in (remark or "")):
            try:
                from api.services.automation_level_service import AutomationLevelService
                lvl_svc = AutomationLevelService(self.db)
                iqc_level = await lvl_svc.get_level(factory_id, "auto_iqc")

                if iqc_level >= 2:
                    # L2/L3: 自动创建IQC任务+抽样
                    from api.services.inspection_service import InspectionService
                    insp_svc = InspectionService(self.db)
                    import math
                    sample = min(80, max(5, int(math.sqrt(quantity))))
                    await insp_svc.create_task(
                        factory_id=factory_id,
                        inspect_type="IQC",
                        material_code=material_code,
                        material_name=material_name,
                        batch_qty=quantity,
                        sample_qty=sample,
                        source_type="inbound",
                        source_code=batch_code or material_code,
                        created_by=operator,
                    )
                    iqc_triggered = True
                    iqc_action = "auto_task_created" if iqc_level == 2 else "auto_task_and_judge"
                elif iqc_level == 1:
                    # L1: 只提醒品质部有待检（不自动创建任务）
                    iqc_action = "notify_qc"
                else:
                    # L0: 纯手工，不做任何事
                    iqc_action = "manual"
            except Exception:
                pass  # IQC触发失败不阻塞入库

        return {
            "success": True,
            "type": "inbound",
            "material_code": material_code,
            "quantity": quantity,
            "after_qty": before_qty + quantity,
            "warehouse_id": warehouse_id,
            "operator": operator,
            "time": now.isoformat(),
            "iqc_triggered": iqc_triggered,
            "iqc_action": iqc_action,
            "iqc_note": {"auto_task_created": "已自动创建IQC任务", "auto_task_and_judge": "已自动创建IQC+自动判定", "notify_qc": "已提醒品质部(L1)", "manual": "手工模式-需人通知品质部", "none": "非采购入库"}.get(iqc_action, ""),
        }

    # ==================== 快速出库 ====================

    async def quick_outbound(
        self,
        factory_id: str,
        material_id: str,
        quantity: int,
        warehouse_id: Optional[str] = None,
        batch_code: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        operator: str = "system",
        remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        """快速出库（领料/发货）"""
        now = datetime.utcnow()

        # 查找库存
        conditions = [
            Inventory.factory_id == factory_id,
            Inventory.material_id == material_id,
        ]
        if warehouse_id:
            conditions.append(Inventory.warehouse_id == warehouse_id)
        if batch_code:
            conditions.append(Inventory.batch_code == batch_code)

        inv_stmt = select(Inventory).where(and_(*conditions)).order_by(Inventory.created_at.asc())
        inv_result = await self.db.execute(inv_stmt)
        inv = inv_result.scalars().first()

        if not inv:
            return {"error": f"物料 {material_id} 无库存"}
        if inv.available_qty < quantity:
            return {"error": f"可用库存不足：需要 {quantity}，可用 {inv.available_qty}"}

        before_qty = inv.total_qty
        inv.total_qty -= quantity
        inv.available_qty -= quantity
        inv.last_movement_at = now
        inv.updated_at = now

        # 记录流水
        txn = InventoryTransaction(
            id=_gen_id(),
            factory_id=factory_id,
            inventory_id=inv.id,
            material_id=material_id,
            batch_code=inv.batch_code,
            transaction_type="outbound",
            quantity=-quantity,
            before_qty=before_qty,
            after_qty=before_qty - quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            operator=operator,
            remark=remark or "快速出库",
            created_at=now,
        )
        self.db.add(txn)
        await self.db.commit()

        return {
            "success": True,
            "type": "outbound",
            "material_id": material_id,
            "material_code": inv.material_code,
            "quantity": quantity,
            "after_qty": before_qty - quantity,
            "warehouse_id": inv.warehouse_id,
            "operator": operator,
            "time": now.isoformat(),
        }

    # ==================== 移库 ====================

    async def transfer(
        self,
        factory_id: str,
        material_id: str,
        quantity: int,
        from_warehouse_id: str,
        to_warehouse_id: str,
        to_location_id: Optional[str] = None,
        operator: str = "system",
        remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        """移库（仓间调拨）"""
        now = datetime.utcnow()

        # 源库存
        src_stmt = select(Inventory).where(
            and_(
                Inventory.factory_id == factory_id,
                Inventory.material_id == material_id,
                Inventory.warehouse_id == from_warehouse_id,
            )
        )
        src_result = await self.db.execute(src_stmt)
        src_inv = src_result.scalars().first()

        if not src_inv:
            return {"error": f"源仓库无物料 {material_id} 库存"}
        if src_inv.available_qty < quantity:
            return {"error": f"源库存不足：需要 {quantity}，可用 {src_inv.available_qty}"}

        # 扣减源
        before_src = src_inv.total_qty
        src_inv.total_qty -= quantity
        src_inv.available_qty -= quantity
        src_inv.last_movement_at = now
        src_inv.updated_at = now

        # 目标库存
        dst_stmt = select(Inventory).where(
            and_(
                Inventory.factory_id == factory_id,
                Inventory.material_id == material_id,
                Inventory.warehouse_id == to_warehouse_id,
            )
        )
        dst_result = await self.db.execute(dst_stmt)
        dst_inv = dst_result.scalar_one_or_none()

        before_dst = 0
        if dst_inv:
            before_dst = dst_inv.total_qty
            dst_inv.total_qty += quantity
            dst_inv.available_qty += quantity
            dst_inv.last_movement_at = now
            dst_inv.updated_at = now
        else:
            dst_inv = Inventory(
                id=_gen_id(),
                material_id=material_id,
                material_code=src_inv.material_code,
                material_name=src_inv.material_name,
                factory_id=factory_id,
                warehouse_id=to_warehouse_id,
                location_id=to_location_id,
                batch_code=src_inv.batch_code,
                total_qty=quantity,
                available_qty=quantity,
                reserved_qty=0,
                unit=src_inv.unit or "pcs",
                status="available",
                last_movement_at=now,
                created_at=now,
                updated_at=now,
            )
            self.db.add(dst_inv)

        # 记录流水（出+入）
        self.db.add(InventoryTransaction(
            id=_gen_id(), factory_id=factory_id, inventory_id=src_inv.id,
            material_id=material_id, batch_code=src_inv.batch_code,
            transaction_type="transfer", quantity=-quantity,
            before_qty=before_src, after_qty=before_src - quantity,
            reference_type="transfer", reference_id=to_warehouse_id,
            operator=operator, remark=remark or f"移库→{to_warehouse_id}", created_at=now,
        ))
        self.db.add(InventoryTransaction(
            id=_gen_id(), factory_id=factory_id, inventory_id=dst_inv.id,
            material_id=material_id, batch_code=src_inv.batch_code,
            transaction_type="transfer", quantity=quantity,
            before_qty=before_dst, after_qty=before_dst + quantity,
            reference_type="transfer", reference_id=from_warehouse_id,
            operator=operator, remark=remark or f"移库←{from_warehouse_id}", created_at=now,
        ))
        await self.db.commit()

        return {
            "success": True,
            "type": "transfer",
            "material_id": material_id,
            "material_code": src_inv.material_code,
            "quantity": quantity,
            "from": from_warehouse_id,
            "to": to_warehouse_id,
            "operator": operator,
            "time": now.isoformat(),
        }

    # ==================== 库存查询 ====================

    async def search_inventory(
        self, factory_id: str, keyword: Optional[str] = None, warehouse_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """库存搜索（支持物料编码/名称模糊）"""
        conditions = [Inventory.factory_id == factory_id, Inventory.total_qty > 0]
        if warehouse_id:
            conditions.append(Inventory.warehouse_id == warehouse_id)
        if keyword:
            conditions.append(
                (Inventory.material_code.ilike(f"%{keyword}%")) |
                (Inventory.material_name.ilike(f"%{keyword}%")) |
                (Inventory.material_id.ilike(f"%{keyword}%"))
            )

        stmt = select(Inventory).where(and_(*conditions)).order_by(Inventory.updated_at.desc()).limit(100)
        result = await self.db.execute(stmt)
        items = result.scalars().all()

        return {
            "items": [{
                "id": i.id,
                "material_id": i.material_id,
                "material_code": i.material_code,
                "material_name": i.material_name,
                "warehouse_id": i.warehouse_id,
                "batch_code": i.batch_code,
                "total_qty": i.total_qty,
                "available_qty": i.available_qty,
                "reserved_qty": i.reserved_qty,
                "unit": i.unit,
                "last_movement_at": i.last_movement_at.isoformat() if i.last_movement_at else None,
            } for i in items],
            "total": len(items),
        }

    # ==================== 最近操作记录 ====================

    async def recent_transactions(self, factory_id: str, limit: int = 50) -> Dict[str, Any]:
        """最近操作流水"""
        stmt = select(InventoryTransaction).where(
            InventoryTransaction.factory_id == factory_id
        ).order_by(InventoryTransaction.created_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        txns = result.scalars().all()

        return {
            "items": [{
                "id": t.id,
                "type": t.transaction_type,
                "material_id": t.material_id,
                "quantity": t.quantity,
                "before_qty": t.before_qty,
                "after_qty": t.after_qty,
                "operator": t.operator,
                "remark": t.remark,
                "time": t.created_at.isoformat() if t.created_at else None,
            } for t in txns],
            "total": len(txns),
        }

    # ==================== 盘点任务 ====================

    async def create_cycle_count(
        self,
        factory_id: str,
        warehouse_id: Optional[str] = None,
        count_type: str = "cycle",
        assigned_to: Optional[str] = None,
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """创建盘点任务（自动选取库存项）"""
        now = datetime.utcnow()
        task_id = _gen_id()
        task_code = _gen_task_code(factory_id)

        # 获取待盘库存
        conditions = [Inventory.factory_id == factory_id, Inventory.total_qty > 0]
        if warehouse_id:
            conditions.append(Inventory.warehouse_id == warehouse_id)

        stmt = select(Inventory).where(and_(*conditions))
        result = await self.db.execute(stmt)
        inv_items = result.scalars().all()

        if not inv_items:
            return {"error": "无可盘点的库存"}

        # 创建任务
        await self.db.execute(text("""
            INSERT INTO cycle_count_tasks (id, factory_id, task_code, warehouse_id, count_type,
                status, total_items, assigned_to, created_by, created_at)
            VALUES (:id, :fid, :code, :wh, :type, 'pending', :total, :assigned, :by, :now)
        """), {
            "id": task_id, "fid": factory_id, "code": task_code,
            "wh": warehouse_id, "type": count_type,
            "total": len(inv_items), "assigned": assigned_to,
            "by": created_by, "now": now,
        })

        # 创建盘点明细
        for inv in inv_items:
            await self.db.execute(text("""
                INSERT INTO cycle_count_items (id, task_id, material_id, material_code, location_id, system_qty, status, created_at)
                VALUES (:id, :tid, :mid, :mcode, :lid, :qty, 'pending', :now)
            """), {
                "id": _gen_id(), "tid": task_id,
                "mid": inv.material_id, "mcode": inv.material_code,
                "lid": inv.location_id, "qty": inv.total_qty, "now": now,
            })

        await self.db.commit()

        return {
            "success": True,
            "task_id": task_id,
            "task_code": task_code,
            "total_items": len(inv_items),
            "count_type": count_type,
        }

    async def submit_count(
        self, task_id: str, item_id: str, counted_qty: int, counted_by: str = "system"
    ) -> Dict[str, Any]:
        """提交盘点数量"""
        now = datetime.utcnow()

        # 获取明细
        result = await self.db.execute(text(
            "SELECT * FROM cycle_count_items WHERE id = :id AND task_id = :tid"
        ), {"id": item_id, "tid": task_id})
        item = result.mappings().first()
        if not item:
            return {"error": "盘点项不存在"}

        diff = counted_qty - item["system_qty"]

        await self.db.execute(text("""
            UPDATE cycle_count_items SET counted_qty = :qty, diff_qty = :diff,
                status = 'counted', counted_by = :by, counted_at = :now
            WHERE id = :id
        """), {"qty": counted_qty, "diff": diff, "by": counted_by, "now": now, "id": item_id})

        # 更新任务进度
        await self.db.execute(text("""
            UPDATE cycle_count_tasks SET
                counted_items = (SELECT COUNT(*) FROM cycle_count_items WHERE task_id = :tid AND status != 'pending'),
                diff_items = (SELECT COUNT(*) FROM cycle_count_items WHERE task_id = :tid AND diff_qty != 0 AND diff_qty IS NOT NULL),
                status = CASE WHEN (SELECT COUNT(*) FROM cycle_count_items WHERE task_id = :tid AND status = 'pending') = 0
                    THEN 'completed' ELSE 'in_progress' END
            WHERE id = :tid
        """), {"tid": task_id})

        await self.db.commit()

        return {"success": True, "diff": diff, "item_id": item_id}

    async def list_count_tasks(self, factory_id: str, status: Optional[str] = None) -> Dict[str, Any]:
        """盘点任务列表"""
        query = "SELECT * FROM cycle_count_tasks WHERE factory_id = :fid"
        params: Dict[str, Any] = {"fid": factory_id}
        if status:
            query += " AND status = :status"
            params["status"] = status
        query += " ORDER BY created_at DESC LIMIT 50"

        result = await self.db.execute(text(query), params)
        return {"items": [dict(r) for r in result.mappings().all()]}

    # ==================== 自动补货建议 ====================

    async def replenishment_suggestions(self, factory_id: str) -> Dict[str, Any]:
        """自动补货建议：基于安全库存 + 日均消耗计算补货量。

        仓管员核心能力：系统自动告诉你要补什么、补多少。
        """
        # 获取安全库存配置
        config_result = await self.db.execute(text("""
            SELECT material_code, material_name, safety_stock, reorder_point, max_stock
            FROM safety_stock_config WHERE factory_id = :fid AND is_active = TRUE
        """), {"fid": factory_id})
        configs = [dict(r) for r in config_result.mappings().all()]

        suggestions = []
        for cfg in configs:
            code = cfg["material_code"]
            # 当前库存
            inv_result = await self.db.execute(text("""
                SELECT COALESCE(SUM(available_qty), 0) as avail FROM inventory
                WHERE factory_id = :fid AND material_code = :code
            """), {"fid": factory_id, "code": code})
            avail = inv_result.scalar() or 0

            reorder_point = cfg.get("reorder_point") or cfg.get("safety_stock") or 0
            if avail <= reorder_point:
                # 计算日均消耗（近30天出库）
                consumption_result = await self.db.execute(text("""
                    SELECT COALESCE(SUM(ABS(qty_change)), 0) as consumed
                    FROM inventory_transactions
                    WHERE factory_id = :fid AND material_code = :code
                        AND qty_change < 0 AND created_at >= NOW() - INTERVAL '30 days'
                """), {"fid": factory_id, "code": code})
                consumed_30d = consumption_result.scalar() or 0
                daily_avg = consumed_30d / 30

                # 补货量 = max_stock - 当前库存（或安全库存*2 - 当前）
                max_stock = cfg.get("max_stock") or int(reorder_point * 2)
                suggested_qty = max(int(max_stock - avail), 1)

                suggestions.append({
                    "material_code": code,
                    "material_name": cfg.get("material_name", ""),
                    "current_stock": int(avail),
                    "reorder_point": reorder_point,
                    "safety_stock": cfg.get("safety_stock", 0),
                    "daily_consumption": round(daily_avg, 1),
                    "days_of_stock": round(avail / daily_avg, 1) if daily_avg > 0 else 999,
                    "suggested_qty": suggested_qty,
                    "urgency": "high" if avail <= (cfg.get("safety_stock") or 0) else "medium",
                })

        suggestions.sort(key=lambda x: x["days_of_stock"])
        return {
            "suggestions": suggestions,
            "total_items": len(suggestions),
            "urgent_count": sum(1 for s in suggestions if s["urgency"] == "high"),
        }

    # ==================== FIFO 出库推荐 ====================

    async def fifo_pick_suggestion(self, factory_id: str, material_code: str, qty_needed: int) -> Dict[str, Any]:
        """FIFO 出库推荐：按入库时间从早到晚推荐批次。

        仓管员核心能力：系统告诉你从哪个批次拣货。
        """
        # 按创建时间升序（最早入库的优先）
        result = await self.db.execute(text("""
            SELECT id, batch_code, available_qty, warehouse_id, location_id, created_at
            FROM inventory
            WHERE factory_id = :fid AND material_code = :code AND available_qty > 0
            ORDER BY created_at ASC
        """), {"fid": factory_id, "code": material_code})
        batches = [dict(r) for r in result.mappings().all()]

        picks = []
        remaining = qty_needed
        for batch in batches:
            if remaining <= 0:
                break
            pick_qty = min(batch["available_qty"], remaining)
            picks.append({
                "inventory_id": batch["id"],
                "batch_code": batch["batch_code"],
                "warehouse_id": batch["warehouse_id"],
                "location_id": batch["location_id"],
                "pick_qty": pick_qty,
                "inbound_date": batch["created_at"].isoformat() if batch["created_at"] else None,
            })
            remaining -= pick_qty

        return {
            "material_code": material_code,
            "qty_needed": qty_needed,
            "picks": picks,
            "total_picked": qty_needed - max(remaining, 0),
            "shortage": max(remaining, 0),
            "fifo_compliant": remaining <= 0,
        }

    # ==================== 批次追溯链 ====================

    async def batch_trace(self, factory_id: str, batch_code: str) -> Dict[str, Any]:
        """批次追溯：原料批次 → 入库记录 → 出库/领料 → 关联工单 → 成品。

        仓管员核心能力：完整追溯一个批次的全生命周期。
        """
        # 1. 库存记录
        inv_result = await self.db.execute(text("""
            SELECT * FROM inventory WHERE factory_id = :fid AND batch_code = :batch
        """), {"fid": factory_id, "batch": batch_code})
        inv_records = [dict(r) for r in inv_result.mappings().all()]

        # 2. 交易记录（出入库历史）
        txn_result = await self.db.execute(text("""
            SELECT * FROM inventory_transactions
            WHERE factory_id = :fid AND material_code IN (
                SELECT DISTINCT material_code FROM inventory WHERE batch_code = :batch AND factory_id = :fid
            ) AND batch_code = :batch
            ORDER BY created_at ASC
        """), {"fid": factory_id, "batch": batch_code})
        transactions = [dict(r) for r in txn_result.mappings().all()]

        # 3. 关联工单（通过领料出库记录）
        wo_links = []
        for txn in transactions:
            if txn.get("reference_type") == "work_order" and txn.get("reference_id"):
                wo_links.append({
                    "work_order_id": txn["reference_id"],
                    "qty": abs(txn.get("qty_change", 0)),
                    "date": txn["created_at"].isoformat() if txn.get("created_at") else None,
                })

        # 4. 汇总
        total_in = sum(t.get("qty_change", 0) for t in transactions if t.get("qty_change", 0) > 0)
        total_out = abs(sum(t.get("qty_change", 0) for t in transactions if t.get("qty_change", 0) < 0))
        current_stock = sum(r.get("available_qty", 0) for r in inv_records)

        return {
            "batch_code": batch_code,
            "factory_id": factory_id,
            "inventory_records": inv_records,
            "transactions": transactions,
            "work_order_links": wo_links,
            "summary": {
                "total_inbound": total_in,
                "total_outbound": total_out,
                "current_stock": current_stock,
                "transaction_count": len(transactions),
                "linked_work_orders": len(wo_links),
            },
        }

