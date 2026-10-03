"""
订单拆分服务 - 岗位替代 Phase 2: 替代计划员
销售订单 → 工单拆分 / 物料齐套检查 / 交期评估
"""
import uuid
import json
import math
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database.models import (
    WorkOrder, BomItem, Inventory, Product, Routing, Station,
)


def _gen_id() -> str:
    return str(uuid.uuid4())


def _gen_so_code(factory_id: str) -> str:
    prefix = factory_id[:3].upper() if factory_id else "FAC"
    ts = datetime.now().strftime("%y%m%d")
    suffix = uuid.uuid4().hex[:4].upper()
    return f"SO-{prefix}-{ts}-{suffix}"


def _gen_wo_code(factory_id: str, product_id: str) -> str:
    prefix = factory_id[:3].upper() if factory_id else "FAC"
    ts = datetime.now().strftime("%m%d")
    suffix = uuid.uuid4().hex[:5].upper()
    return f"WO-{prefix}-{ts}-{suffix}"


class OrderDecompositionService:
    """订单拆分 + 齐套检查服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== 销售订单 CRUD ====================

    async def create_sales_order(
        self,
        factory_id: str,
        product_id: str,
        quantity: int,
        customer_name: Optional[str] = None,
        customer_code: Optional[str] = None,
        product_name: Optional[str] = None,
        delivery_date: Optional[str] = None,
        priority: str = "medium",
        unit_price: Optional[float] = None,
        remark: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建销售订单"""
        so = {
            "id": _gen_id(),
            "order_code": _gen_so_code(factory_id),
            "factory_id": factory_id,
            "customer_name": customer_name,
            "customer_code": customer_code,
            "product_id": product_id,
            "product_name": product_name or product_id,
            "quantity": quantity,
            "delivery_date": date.fromisoformat(delivery_date) if delivery_date else None,
            "priority": priority,
            "status": "pending",
            "decomposed": False,
            "material_ready": False,
            "unit_price": unit_price,
            "total_amount": (unit_price or 0) * quantity,
            "remark": remark,
            "created_by": created_by,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        from database.models import Base
        from sqlalchemy import text
        # 使用 raw insert 因为 SalesOrder 模型可能尚未在 models.py 中
        await self.db.execute(text("""
            INSERT INTO sales_orders (id, order_code, factory_id, customer_name, customer_code,
                product_id, product_name, quantity, delivery_date, priority, status,
                decomposed, material_ready, unit_price, total_amount, remark, created_by, created_at, updated_at)
            VALUES (:id, :order_code, :factory_id, :customer_name, :customer_code,
                :product_id, :product_name, :quantity, :delivery_date, :priority, :status,
                :decomposed, :material_ready, :unit_price, :total_amount, :remark, :created_by, :created_at, :updated_at)
        """), so)
        await self.db.commit()

        return {"id": so["id"], "order_code": so["order_code"], "status": "pending"}

    async def list_sales_orders(
        self, factory_id: str, status: Optional[str] = None, limit: int = 50
    ) -> Dict[str, Any]:
        """销售订单列表"""
        from sqlalchemy import text
        query = "SELECT * FROM sales_orders WHERE factory_id = :fid"
        params: Dict[str, Any] = {"fid": factory_id}
        if status:
            query += " AND status = :status"
            params["status"] = status
        query += " ORDER BY created_at DESC LIMIT :lim"
        params["lim"] = limit

        result = await self.db.execute(text(query), params)
        rows = result.mappings().all()
        return {"items": [dict(r) for r in rows], "total": len(rows)}

    # ==================== 订单 → 工单拆分 ====================

    async def decompose_order(self, sales_order_id: str, operator: str = "system") -> Dict[str, Any]:
        """
        订单拆分为工单
        逻辑：销售订单 → 创建主工单（master）→ 按工艺路线创建工序工单（operation）
        """
        from sqlalchemy import text

        # 获取销售订单
        result = await self.db.execute(
            text("SELECT * FROM sales_orders WHERE id = :id"), {"id": sales_order_id}
        )
        so = result.mappings().first()
        if not so:
            return {"error": "订单不存在"}
        if so["decomposed"]:
            return {"error": "订单已拆分", "work_order_ids": json.loads(so["work_order_ids"] or "[]")}

        factory_id = so["factory_id"]
        product_id = so["product_id"]
        quantity = so["quantity"]

        # 查找工艺路线
        routing_stmt = select(Routing).where(
            and_(Routing.factory_id == factory_id, Routing.product_id == product_id)
        )
        routing_result = await self.db.execute(routing_stmt)
        routing = routing_result.scalar_one_or_none()

        # 创建主工单
        master_wo_id = _gen_id()
        master_wo = WorkOrder(
            id=master_wo_id,
            work_order_code=_gen_wo_code(factory_id, product_id),
            factory_id=factory_id,
            sales_order_id=so["order_code"],
            product_id=product_id,
            routing_id=routing.id if routing else None,
            planned_qty=quantity,
            status="pending",
            priority=so["priority"],
            planned_due=datetime.combine(so["delivery_date"], datetime.max.time()) if so["delivery_date"] else None,
            wo_type="master",
            created_by=operator,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.db.add(master_wo)

        # 如果有工艺路线，创建工序工单
        op_wo_ids = []
        if routing:
            # 获取工序步骤（从 routing 的 steps JSON 或关联表）
            steps = json.loads(routing.steps) if hasattr(routing, "steps") and routing.steps else []
            for i, step in enumerate(steps):
                op_wo_id = _gen_id()
                op_wo = WorkOrder(
                    id=op_wo_id,
                    work_order_code=f"{master_wo.work_order_code}-OP{i+1:02d}",
                    factory_id=factory_id,
                    sales_order_id=so["order_code"],
                    product_id=product_id,
                    routing_id=routing.id,
                    planned_qty=quantity,
                    status="pending",
                    priority=so["priority"],
                    planned_due=master_wo.planned_due,
                    assigned_station_id=step.get("station_id"),
                    current_routing_step=i + 1,
                    wo_type="operation",
                    parent_work_order_id=master_wo_id,
                    process_code=step.get("process_code", f"OP{i+1:02d}"),
                    operation_seq=i + 1,
                    created_by=operator,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                self.db.add(op_wo)
                op_wo_ids.append(op_wo_id)

        # 更新销售订单状态
        all_wo_ids = [master_wo_id] + op_wo_ids
        await self.db.execute(text("""
            UPDATE sales_orders SET decomposed = TRUE, decomposed_at = :now,
                work_order_ids = :wo_ids, status = 'planning', updated_at = :now
            WHERE id = :id
        """), {
            "now": datetime.utcnow(),
            "wo_ids": json.dumps(all_wo_ids),
            "id": sales_order_id,
        })

        # 记录拆分日志
        await self.db.execute(text("""
            INSERT INTO order_decomposition_logs (id, factory_id, sales_order_id, action, result, work_orders_created, operator, created_at)
            VALUES (:id, :fid, :so_id, 'decompose', :result, :count, :op, :now)
        """), {
            "id": _gen_id(),
            "fid": factory_id,
            "so_id": sales_order_id,
            "result": json.dumps({"master_wo": master_wo.work_order_code, "operation_wos": len(op_wo_ids)}),
            "count": len(all_wo_ids),
            "op": operator,
            "now": datetime.utcnow(),
        })

        await self.db.commit()

        return {
            "success": True,
            "master_work_order": {"id": master_wo_id, "code": master_wo.work_order_code},
            "operation_work_orders": len(op_wo_ids),
            "total_work_orders": len(all_wo_ids),
        }

    # ==================== 物料齐套检查 ====================

    async def material_check(self, sales_order_id: str) -> Dict[str, Any]:
        """
        物料齐套检查
        逻辑：BOM 展开 × 订单量 → 对比库存 → 返回缺料清单
        """
        from sqlalchemy import text

        result = await self.db.execute(
            text("SELECT * FROM sales_orders WHERE id = :id"), {"id": sales_order_id}
        )
        so = result.mappings().first()
        if not so:
            return {"error": "订单不存在"}

        factory_id = so["factory_id"]
        product_id = so["product_id"]
        quantity = so["quantity"]

        # BOM 展开
        bom_stmt = select(BomItem).where(
            and_(BomItem.factory_id == factory_id, BomItem.product_id == product_id)
        )
        bom_result = await self.db.execute(bom_stmt)
        bom_items = bom_result.scalars().all()

        if not bom_items:
            return {"error": f"产品 {product_id} 无 BOM 数据", "ready": False}

        # 逐项检查库存
        materials = []
        shortage_count = 0
        for item in bom_items:
            required = item.qty_per_unit * quantity
            # 查库存
            inv_stmt = select(func.coalesce(func.sum(Inventory.total_qty), 0)).where(
                and_(
                    Inventory.factory_id == factory_id,
                    Inventory.material_code == item.material_code,
                )
            )
            inv_result = await self.db.execute(inv_stmt)
            available = inv_result.scalar() or 0

            shortage = max(0, required - available)
            is_ready = shortage == 0
            if not is_ready:
                shortage_count += 1

            materials.append({
                "material_code": item.material_code,
                "material_name": item.material_name or item.material_code,
                "required": round(required, 2),
                "available": available,
                "shortage": round(shortage, 2),
                "unit": item.unit,
                "ready": is_ready,
            })

        all_ready = shortage_count == 0

        # 更新订单齐套状态
        await self.db.execute(text("""
            UPDATE sales_orders SET material_ready = :ready, material_check_at = :now, updated_at = :now
            WHERE id = :id
        """), {"ready": all_ready, "now": datetime.utcnow(), "id": sales_order_id})
        await self.db.commit()

        return {
            "order_code": so["order_code"],
            "product_id": product_id,
            "quantity": quantity,
            "ready": all_ready,
            "total_materials": len(materials),
            "shortage_count": shortage_count,
            "materials": materials,
            "checked_at": datetime.utcnow().isoformat(),
        }

    # ==================== 交期评估 ====================

    async def estimate_delivery(self, factory_id: str, product_id: str, quantity: int) -> Dict[str, Any]:
        """
        交期评估：根据产能估算最早完成日期
        """
        # 获取工艺路线工序数
        routing_stmt = select(Routing).where(
            and_(Routing.factory_id == factory_id, Routing.product_id == product_id)
        )
        routing_result = await self.db.execute(routing_stmt)
        routing = routing_result.scalars().first()

        # 产能：`station_capacity.available_hours_per_day` 这一列维护的是"一天可完成几件产品"
        # （用户确认的口径），不是小时。原来这里把它当小时、再乘一个平均 OEE、并按
        # "每件 0.5 小时"编一个需求工时，得到的日数是三层假设的乘积。
        # 现在按件算：瓶颈工位一天的可完成件数决定产出节拍，天数只数工厂日历上真正排了班的日子。
        from sqlalchemy import text
        from core.mes.capacity_math import load_station_models

        cap_rows = (await self.db.execute(text(
            "SELECT station_id, available_hours_per_day FROM station_capacity"
            " WHERE factory_id = :fid AND is_active = TRUE"
        ), {"fid": factory_id})).mappings().all()
        piece_capacity = {
            str(r["station_id"]): float(r["available_hours_per_day"] or 0)
            for r in cap_rows if float(r["available_hours_per_day"] or 0) > 0
        }
        if not piece_capacity:
            return {
                "estimated_days": None,
                "earliest_delivery": None,
                "confidence": "unavailable",
                "note": "该工厂没有任何按件计的日产能配置（station_capacity），无法给出交期承诺",
            }

        # 路线工位与排程同一口径（core.mes.route_resolution）：排程排得出几道，这里就能算几道。
        # 解析不出工位时**拒绝给日期** —— 以前这里退回"全厂最慢工位"，那个 0.07 件/天
        # 的工位跟本产品毫无关系，却把交期算成 286 天，数字看着精确其实是错的。
        from core.mes.route_resolution import route_stations_for_product

        route_stations = await route_stations_for_product(self.db, factory_id, product_id)
        usable = [c for c in route_stations if c in piece_capacity]
        if not usable:
            return {
                "estimated_days": None,
                "earliest_delivery": None,
                "confidence": "unavailable",
                "route_stations": route_stations,
                "note": (
                    f"产品 {product_id} 解析不出带产能配置的工艺路线工位"
                    + ("（路线工位 " + "、".join(route_stations) + " 都没有日产能记录）" if route_stations else "（没有可用的工艺路线）")
                    + "，不给按假设拼出来的交期"
                ),
            }
        throughput = min(piece_capacity[c] for c in usable)
        basis = f"工艺路线 {len(usable)} 个工位里的瓶颈 {min(usable, key=lambda c: piece_capacity[c])} 日产能 {throughput:g} 件/天"
        confidence = "medium"

        start_day = date.today()
        horizon = start_day + timedelta(days=365)
        start_dt = datetime.now()
        models = await load_station_models(
            self.db, factory_id, sorted(usable or piece_capacity), start_dt, start_dt + timedelta(days=365)
        )
        working_days = [
            (start_day + timedelta(days=offset))
            for offset in range((horizon - start_day).days + 1)
            if any(m.is_working_day(start_day + timedelta(days=offset)) for m in models.values())
        ]
        if not working_days:
            return {
                "estimated_days": None,
                "earliest_delivery": None,
                "confidence": "unavailable",
                "note": "工厂日历在未来一年内没有任何排班日，无法排产",
            }

        # 只数排了班的日子；超出评估窗口就明说，不钳成窗口最后一天冒充"能交"
        days_needed = max(1, math.ceil(float(quantity) / float(throughput)))
        if days_needed > len(working_days):
            return {
                "estimated_days": days_needed,
                "earliest_delivery": None,
                "confidence": "low",
                "daily_capacity_pieces": throughput,
                "capacity_basis": basis,
                "note": f"按 {throughput:g} 件/天需要 {days_needed} 个排班日，超出 365 天评估窗口",
            }
        earliest = working_days[days_needed - 1]

        return {
            "estimated_days": days_needed,
            "earliest_delivery": earliest.isoformat(),
            "confidence": confidence,
            "capacity_utilization": round(quantity / (throughput * days_needed) * 100, 1),
            "stations_available": len(piece_capacity),
            "daily_capacity_pieces": throughput,
            "capacity_basis": basis,
            "capacity_note": "日产能取自 station_capacity 的『一天可完成几件产品』口径；天数为工厂日历排班日",
        }
