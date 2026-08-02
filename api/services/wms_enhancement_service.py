"""WMS 全量增强服务：批次/库位/报表/条码RFID/自动化/多仓/调拨/冻结/盘点差异。"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Inventory, InventoryTransaction, Location


def _gen_id() -> str:
    return str(uuid.uuid4())


def _code(prefix: str) -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def _as_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    return float(v)


class WmsEnhancementService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== 1. 批次管理 ====================

    async def set_batch_expiry(
        self,
        inventory_id: str,
        *,
        expiry_date: Optional[date] = None,
        production_date: Optional[date] = None,
        shelf_life_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        inv = await self.db.get(Inventory, inventory_id)
        if not inv:
            return {"success": False, "message": "库存记录不存在"}
        if production_date:
            inv.production_date = production_date
        if shelf_life_days is not None:
            inv.shelf_life_days = shelf_life_days
        if expiry_date:
            inv.expiry_date = expiry_date
        elif production_date and shelf_life_days:
            inv.expiry_date = production_date + timedelta(days=shelf_life_days)
        elif inv.production_date and inv.shelf_life_days:
            inv.expiry_date = inv.production_date + timedelta(days=int(inv.shelf_life_days))
        inv.updated_at = datetime.utcnow()
        await self.db.commit()
        return {
            "success": True,
            "inventory_id": inventory_id,
            "expiry_date": inv.expiry_date.isoformat() if inv.expiry_date else None,
            "production_date": inv.production_date.isoformat() if inv.production_date else None,
            "shelf_life_days": inv.shelf_life_days,
        }

    async def lock_batch(
        self,
        inventory_id: str,
        *,
        reason: str,
        operator: str,
    ) -> Dict[str, Any]:
        inv = await self.db.get(Inventory, inventory_id)
        if not inv:
            return {"success": False, "message": "库存记录不存在"}
        inv.status = "locked"
        inv.lock_reason = reason
        inv.locked_at = datetime.utcnow()
        inv.locked_by = operator
        inv.updated_at = datetime.utcnow()
        await self.db.commit()
        return {"success": True, "inventory_id": inventory_id, "status": "locked", "reason": reason}

    async def unlock_batch(
        self,
        inventory_id: str,
        *,
        operator: str,
    ) -> Dict[str, Any]:
        inv = await self.db.get(Inventory, inventory_id)
        if not inv:
            return {"success": False, "message": "库存记录不存在"}
        inv.status = "available"
        inv.lock_reason = None
        inv.locked_at = None
        inv.locked_by = None
        inv.updated_at = datetime.utcnow()
        await self.db.commit()
        return {"success": True, "inventory_id": inventory_id, "status": "available", "unlocked_by": operator}

    async def list_expiring_batches(
        self,
        factory_id: str,
        within_days: int = 30,
    ) -> Dict[str, Any]:
        rows = (
            await self.db.execute(
                text("""
                    SELECT id, material_code, material_name, batch_code, warehouse_id,
                           total_qty, expiry_date,
                           (expiry_date - CURRENT_DATE) AS days_left
                    FROM inventory
                    WHERE factory_id = :fid AND expiry_date IS NOT NULL
                      AND expiry_date <= CURRENT_DATE + :days * INTERVAL '1 day'
                      AND total_qty > 0
                    ORDER BY expiry_date ASC
                """),
                {"fid": factory_id, "days": within_days},
            )
        ).mappings().all()
        items = [dict(r) for r in rows]
        for it in items:
            if it.get("expiry_date"):
                it["expiry_date"] = it["expiry_date"].isoformat()
            if it.get("days_left") is not None:
                it["days_left"] = int(it["days_left"])
        return {"factory_id": factory_id, "within_days": within_days, "items": items, "count": len(items)}

    # ==================== 2. 库位管理 ====================

    async def update_location_3d(
        self,
        location_id: str,
        *,
        row_num: Optional[int] = None,
        col_num: Optional[int] = None,
        level_num: Optional[int] = None,
        capacity: Optional[int] = None,
        occupancy_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        loc = await self.db.get(Location, location_id)
        if not loc:
            return {"success": False, "message": "库位不存在"}
        sets = []
        params: Dict[str, Any] = {"id": location_id}
        if row_num is not None:
            sets += ["row_num = :row", "aisle = :row_s"]
            params["row"] = row_num
            params["row_s"] = str(row_num)
        if col_num is not None:
            sets += ["col_num = :col", "rack = :col_s"]
            params["col"] = col_num
            params["col_s"] = str(col_num)
        if level_num is not None:
            sets += ["level_num = :lvl", "level = :lvl_s"]
            params["lvl"] = level_num
            params["lvl_s"] = str(level_num)
        if capacity is not None:
            sets.append("capacity = :cap")
            params["cap"] = capacity
        if occupancy_status:
            sets.append("occupancy_status = :ost")
            params["ost"] = occupancy_status
        if sets:
            sets.append("updated_at = NOW()")
            await self.db.execute(
                text(f"UPDATE locations SET {', '.join(sets)} WHERE id = :id"),
                params,
            )
        await self.db.commit()
        row = (
            await self.db.execute(text("SELECT * FROM locations WHERE id = :id"), {"id": location_id})
        ).mappings().first()
        return {"success": True, "location": dict(row) if row else {"id": location_id}}

    async def sync_location_occupancy(self, warehouse_id: str) -> Dict[str, Any]:
        """根据库存刷新库位占用状态。"""
        await self.db.execute(
            text("""
                UPDATE locations l SET occupancy_status = CASE
                    WHEN l.status = 'locked' THEN 'locked'
                    WHEN EXISTS (
                        SELECT 1 FROM inventory i
                        WHERE i.location_id = l.id AND i.total_qty > 0
                    ) THEN 'occupied'
                    ELSE 'idle'
                END,
                updated_at = NOW()
                WHERE l.warehouse_id = :wh
            """),
            {"wh": warehouse_id},
        )
        await self.db.commit()
        cnt = (
            await self.db.execute(
                text("SELECT COUNT(*) FROM locations WHERE warehouse_id = :wh"),
                {"wh": warehouse_id},
            )
        ).scalar()
        return {"success": True, "warehouse_id": warehouse_id, "locations_updated": int(cnt or 0)}

    async def list_locations_enhanced(
        self,
        warehouse_id: str,
        occupancy_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        q = """
            SELECT l.*, COALESCE(SUM(i.total_qty), 0) AS used_qty
            FROM locations l
            LEFT JOIN inventory i ON i.location_id = l.id AND i.total_qty > 0
            WHERE l.warehouse_id = :wh
        """
        params: Dict[str, Any] = {"wh": warehouse_id}
        if occupancy_status:
            q += " AND l.occupancy_status = :st"
            params["st"] = occupancy_status
        q += " GROUP BY l.id ORDER BY l.location_code"
        rows = (await self.db.execute(text(q), params)).mappings().all()
        items = []
        for r in rows:
            cap = r.get("capacity") or 0
            used = int(r.get("used_qty") or 0)
            items.append({
                "id": r["id"],
                "location_code": r["location_code"],
                "row_num": r.get("row_num"),
                "col_num": r.get("col_num"),
                "level_num": r.get("level_num"),
                "capacity": cap,
                "used_qty": used,
                "utilization_pct": round(used / cap * 100, 1) if cap > 0 else None,
                "occupancy_status": r.get("occupancy_status") or "idle",
            })
        return {"warehouse_id": warehouse_id, "items": items, "total": len(items)}

    # ==================== 4. 报表分析 ====================

    async def inventory_turnover_report(self, factory_id: str, days: int = 90) -> Dict[str, Any]:
        rows = (
            await self.db.execute(
                text("""
                    SELECT i.material_code, i.material_name,
                           COALESCE(SUM(i.total_qty), 0) AS on_hand,
                           COALESCE(SUM(i.total_qty * COALESCE(i.unit_cost, 0)), 0) AS inventory_value,
                           COALESCE(outflow.out_qty, 0) AS outbound_qty
                    FROM inventory i
                    LEFT JOIN (
                        SELECT material_id, SUM(ABS(quantity)) AS out_qty
                        FROM inventory_transactions
                        WHERE factory_id = :fid AND quantity < 0
                          AND created_at >= NOW() - :days * INTERVAL '1 day'
                        GROUP BY material_id
                    ) outflow ON outflow.material_id = i.material_id
                    WHERE i.factory_id = :fid AND i.total_qty > 0
                    GROUP BY i.material_code, i.material_name, i.material_id, outflow.out_qty
                    ORDER BY outbound_qty DESC
                """),
                {"fid": factory_id, "days": days},
            )
        ).mappings().all()
        items = []
        for r in rows:
            on_hand = int(r["on_hand"] or 0)
            out_qty = int(r["outbound_qty"] or 0)
            avg_inv = max(on_hand, 1)
            turnover = round(out_qty / avg_inv * (365 / max(days, 1)), 2)
            items.append({
                "material_code": r["material_code"],
                "material_name": r["material_name"],
                "on_hand": on_hand,
                "outbound_qty": out_qty,
                "inventory_value": _as_float(r["inventory_value"]),
                "turnover_rate": turnover,
            })
        avg_turnover = round(sum(i["turnover_rate"] for i in items) / len(items), 2) if items else 0
        return {"factory_id": factory_id, "period_days": days, "avg_turnover_rate": avg_turnover, "items": items}

    async def abc_classification_report(self, factory_id: str) -> Dict[str, Any]:
        rows = (
            await self.db.execute(
                text("""
                    SELECT material_code, material_name,
                           SUM(total_qty) AS qty,
                           SUM(total_qty * COALESCE(unit_cost, 10)) AS value
                    FROM inventory
                    WHERE factory_id = :fid AND total_qty > 0
                    GROUP BY material_code, material_name
                    ORDER BY value DESC
                """),
                {"fid": factory_id},
            )
        ).mappings().all()
        if not rows:
            return {"factory_id": factory_id, "items": [], "distribution": {"A": 0, "B": 0, "C": 0}}
        total_value = sum(_as_float(r["value"]) for r in rows)
        cumulative = 0.0
        items = []
        dist = {"A": 0, "B": 0, "C": 0}
        for r in rows:
            val = _as_float(r["value"])
            cumulative += val
            pct = cumulative / total_value if total_value > 0 else 1
            if pct <= 0.8:
                cls = "A"
            elif pct <= 0.95:
                cls = "B"
            else:
                cls = "C"
            dist[cls] += 1
            await self.db.execute(
                text("""
                    UPDATE inventory SET abc_class = :cls
                    WHERE factory_id = :fid AND material_code = :code
                """),
                {"cls": cls, "fid": factory_id, "code": r["material_code"]},
            )
            items.append({
                "material_code": r["material_code"],
                "material_name": r["material_name"],
                "qty": int(r["qty"] or 0),
                "value": val,
                "abc_class": cls,
                "cumulative_pct": round(pct * 100, 1),
            })
        await self.db.commit()
        return {"factory_id": factory_id, "distribution": dist, "items": items}

    async def inventory_cost_report(self, factory_id: str) -> Dict[str, Any]:
        rows = (
            await self.db.execute(
                text("""
                    SELECT w.warehouse_code, w.warehouse_name,
                           SUM(i.total_qty) AS total_qty,
                           SUM(i.total_qty * COALESCE(i.unit_cost, 10)) AS total_cost
                    FROM inventory i
                    JOIN warehouses w ON w.id = i.warehouse_id
                    WHERE i.factory_id = :fid AND i.total_qty > 0
                    GROUP BY w.id, w.warehouse_code, w.warehouse_name
                    ORDER BY total_cost DESC
                """),
                {"fid": factory_id},
            )
        ).mappings().all()
        items = [{
            "warehouse_code": r["warehouse_code"],
            "warehouse_name": r["warehouse_name"],
            "total_qty": int(r["total_qty"] or 0),
            "total_cost": _as_float(r["total_cost"]),
        } for r in rows]
        grand = sum(i["total_cost"] for i in items)
        return {"factory_id": factory_id, "grand_total_cost": round(grand, 2), "warehouses": items}

    # ==================== 5. 条码 / RFID ====================

    async def generate_barcode(
        self,
        factory_id: str,
        material_id: str,
        material_code: str,
        *,
        batch_code: Optional[str] = None,
        barcode_type: str = "CODE128",
    ) -> Dict[str, Any]:
        barcode = f"EH-{material_code}-{uuid.uuid4().hex[:10].upper()}"
        bid = _gen_id()
        await self.db.execute(
            text("""
                INSERT INTO wms_barcodes (id, factory_id, material_id, material_code, barcode, barcode_type, batch_code)
                VALUES (:id, :fid, :mid, :code, :bc, :type, :batch)
            """),
            {
                "id": bid, "fid": factory_id, "mid": material_id, "code": material_code,
                "bc": barcode, "type": barcode_type, "batch": batch_code,
            },
        )
        await self.db.commit()
        return {"success": True, "barcode_id": bid, "barcode": barcode, "material_code": material_code}

    async def scan_barcode_inbound(
        self,
        factory_id: str,
        barcode: str,
        quantity: int,
        warehouse_id: str,
        *,
        location_id: Optional[str] = None,
        operator: str = "system",
    ) -> Dict[str, Any]:
        row = (
            await self.db.execute(
                text("""
                    SELECT * FROM wms_barcodes
                    WHERE factory_id = :fid AND barcode = :bc AND is_active = TRUE
                """),
                {"fid": factory_id, "bc": barcode},
            )
        ).mappings().first()
        if not row:
            return {"success": False, "message": "条码未注册"}
        from api.services.wms_operation_service import WmsOperationService
        op = WmsOperationService(self.db)
        return await op.quick_inbound(
            factory_id=factory_id,
            material_id=row["material_id"],
            material_code=row["material_code"],
            quantity=quantity,
            warehouse_id=warehouse_id,
            location_id=location_id,
            batch_code=row.get("batch_code"),
            operator=operator,
            remark=f"条码扫描入库 {barcode}",
        )

    async def start_rfid_count(
        self,
        factory_id: str,
        warehouse_id: Optional[str],
        *,
        created_by: str = "system",
    ) -> Dict[str, Any]:
        sid = _gen_id()
        code = _code("RFID")
        tags = (
            await self.db.execute(
                text("""
                    SELECT tag_id, material_code FROM wms_rfid_tags
                    WHERE factory_id = :fid AND status = 'active'
                """),
                {"fid": factory_id},
            )
        ).mappings().all()
        await self.db.execute(
            text("""
                INSERT INTO wms_rfid_count_sessions
                (id, factory_id, warehouse_id, session_code, status, total_tags, created_by)
                VALUES (:id, :fid, :wh, :code, 'open', :total, :by)
            """),
            {"id": sid, "fid": factory_id, "wh": warehouse_id, "code": code, "total": len(tags), "by": created_by},
        )
        for t in tags:
            await self.db.execute(
                text("""
                    INSERT INTO wms_rfid_count_items (id, session_id, tag_id, material_code, expected_qty, status)
                    VALUES (:id, :sid, :tag, :code, 1, 'pending')
                """),
                {"id": _gen_id(), "sid": sid, "tag": t["tag_id"], "code": t["material_code"]},
            )
        await self.db.commit()
        return {"success": True, "session_id": sid, "session_code": code, "total_tags": len(tags)}

    async def submit_rfid_scans(
        self,
        session_id: str,
        tag_ids: List[str],
    ) -> Dict[str, Any]:
        matched = 0
        for tag in tag_ids:
            r = await self.db.execute(
                text("""
                    UPDATE wms_rfid_count_items SET scanned_qty = 1, variance_qty = 0, status = 'matched'
                    WHERE session_id = :sid AND tag_id = :tag
                """),
                {"sid": session_id, "tag": tag},
            )
            if r.rowcount:
                matched += 1
        await self.db.execute(
            text("""
                UPDATE wms_rfid_count_items SET variance_qty = expected_qty, status = 'missing'
                WHERE session_id = :sid AND status = 'pending'
            """),
            {"sid": session_id},
        )
        stats = (
            await self.db.execute(
                text("""
                    SELECT COUNT(*) FILTER (WHERE status = 'matched') AS matched,
                           COUNT(*) FILTER (WHERE status = 'missing') AS variance
                    FROM wms_rfid_count_items WHERE session_id = :sid
                """),
                {"sid": session_id},
            )
        ).mappings().first()
        await self.db.execute(
            text("""
                UPDATE wms_rfid_count_sessions SET status = 'completed', matched_tags = :m,
                    variance_tags = :v, completed_at = NOW()
                WHERE id = :sid
            """),
            {"sid": session_id, "m": stats["matched"], "v": stats["variance"]},
        )
        await self.db.commit()
        return {"success": True, "session_id": session_id, "matched": matched, "variance": int(stats["variance"] or 0)}

    async def register_rfid_tag(
        self,
        factory_id: str,
        tag_id: str,
        material_code: str,
        *,
        material_id: Optional[str] = None,
        inventory_id: Optional[str] = None,
        batch_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        await self.db.execute(
            text("""
                INSERT INTO wms_rfid_tags (id, factory_id, tag_id, material_id, material_code, inventory_id, batch_code)
                VALUES (:id, :fid, :tag, :mid, :code, :inv, :batch)
                ON CONFLICT (factory_id, tag_id) DO UPDATE SET
                    material_code = EXCLUDED.material_code,
                    material_id = EXCLUDED.material_id,
                    inventory_id = EXCLUDED.inventory_id
            """),
            {
                "id": _gen_id(), "fid": factory_id, "tag": tag_id,
                "mid": material_id or material_code, "code": material_code,
                "inv": inventory_id, "batch": batch_code,
            },
        )
        await self.db.commit()
        return {"success": True, "tag_id": tag_id, "material_code": material_code}

    # ==================== 6. 自动化设备 ====================

    async def dispatch_automation_job(
        self,
        factory_id: str,
        job_type: str,
        *,
        material_code: Optional[str] = None,
        quantity: Optional[int] = None,
        source_location: Optional[str] = None,
        target_location: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        created_by: str = "system",
    ) -> Dict[str, Any]:
        jid = _gen_id()
        jcode = _code(job_type.upper()[:3])
        await self.db.execute(
            text("""
                INSERT INTO wms_automation_jobs
                (id, factory_id, job_code, job_type, payload, status, source_location, target_location,
                 material_code, quantity, created_by, dispatched_at)
                VALUES (:id, :fid, :code, :type, :payload, 'dispatched', :src, :tgt, :mat, :qty, :by, NOW())
            """),
            {
                "id": jid, "fid": factory_id, "code": jcode, "type": job_type,
                "payload": json.dumps(payload or {}),
                "src": source_location, "tgt": target_location,
                "mat": material_code, "qty": quantity, "by": created_by,
            },
        )
        await self.db.commit()
        return {"success": True, "job_id": jid, "job_code": jcode, "job_type": job_type, "status": "dispatched"}

    async def list_automation_jobs(
        self,
        factory_id: str,
        job_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        q = "SELECT * FROM wms_automation_jobs WHERE factory_id = :fid"
        params: Dict[str, Any] = {"fid": factory_id}
        if job_type:
            q += " AND job_type = :type"
            params["type"] = job_type
        if status:
            q += " AND status = :st"
            params["st"] = status
        q += " ORDER BY created_at DESC LIMIT 50"
        rows = (await self.db.execute(text(q), params)).mappings().all()
        return {"items": [dict(r) for r in rows], "total": len(rows)}

    async def complete_automation_job(self, job_id: str, *, success: bool = True, error: Optional[str] = None) -> Dict[str, Any]:
        st = "completed" if success else "failed"
        await self.db.execute(
            text("""
                UPDATE wms_automation_jobs SET status = :st, error_message = :err, completed_at = NOW()
                WHERE id = :id
            """),
            {"id": job_id, "st": st, "err": error},
        )
        await self.db.commit()
        return {"success": True, "job_id": job_id, "status": st}

    # ==================== 7. 多仓库协同 ====================

    async def create_inventory_pool(
        self,
        factory_id: str,
        pool_code: str,
        pool_name: str,
        material_id: str,
        material_code: str,
        warehouse_ids: List[str],
    ) -> Dict[str, Any]:
        pid = _gen_id()
        total = (
            await self.db.execute(
                text("""
                    SELECT COALESCE(SUM(available_qty), 0) FROM inventory
                    WHERE factory_id = :fid AND material_id = :mid AND warehouse_id = ANY(:whs)
                """),
                {"fid": factory_id, "mid": material_id, "whs": warehouse_ids},
            )
        ).scalar() or 0
        await self.db.execute(
            text("""
                INSERT INTO wms_inventory_pools (id, factory_id, pool_code, pool_name, material_id, material_code, shared_qty)
                VALUES (:id, :fid, :code, :name, :mid, :mcode, :qty)
            """),
            {"id": pid, "fid": factory_id, "code": pool_code, "name": pool_name,
             "mid": material_id, "mcode": material_code, "qty": int(total)},
        )
        for wh in warehouse_ids:
            alloc = (
                await self.db.execute(
                    text("""
                        SELECT COALESCE(SUM(available_qty), 0) FROM inventory
                        WHERE factory_id = :fid AND material_id = :mid AND warehouse_id = :wh
                    """),
                    {"fid": factory_id, "mid": material_id, "wh": wh},
                )
            ).scalar() or 0
            await self.db.execute(
                text("""
                    INSERT INTO wms_inventory_pool_members (id, pool_id, warehouse_id, allocated_qty)
                    VALUES (:id, :pid, :wh, :qty)
                """),
                {"id": _gen_id(), "pid": pid, "wh": wh, "qty": int(alloc)},
            )
        await self.db.commit()
        return {"success": True, "pool_id": pid, "shared_qty": int(total)}

    async def get_shared_inventory(self, factory_id: str, material_code: Optional[str] = None) -> Dict[str, Any]:
        q = """
            SELECT p.*, json_agg(json_build_object('warehouse_id', m.warehouse_id, 'allocated_qty', m.allocated_qty)) AS members
            FROM wms_inventory_pools p
            JOIN wms_inventory_pool_members m ON m.pool_id = p.id
            WHERE p.factory_id = :fid AND p.status = 'active'
        """
        params: Dict[str, Any] = {"fid": factory_id}
        if material_code:
            q += " AND p.material_code = :code"
            params["code"] = material_code
        q += " GROUP BY p.id ORDER BY p.pool_code"
        rows = (await self.db.execute(text(q), params)).mappings().all()
        return {"items": [dict(r) for r in rows], "total": len(rows)}

    async def cross_warehouse_trace(
        self,
        factory_id: str,
        material_code: str,
    ) -> Dict[str, Any]:
        inv_rows = (
            await self.db.execute(
                text("""
                    SELECT i.*, w.warehouse_code, w.warehouse_name
                    FROM inventory i JOIN warehouses w ON w.id = i.warehouse_id
                    WHERE i.factory_id = :fid AND i.material_code = :code AND i.total_qty > 0
                """),
                {"fid": factory_id, "code": material_code},
            )
        ).mappings().all()
        txn_rows = (
            await self.db.execute(
                text("""
                    SELECT t.*, w.warehouse_code
                    FROM inventory_transactions t
                    LEFT JOIN inventory i ON i.id = t.inventory_id
                    LEFT JOIN warehouses w ON w.id = i.warehouse_id
                    WHERE t.factory_id = :fid AND i.material_code = :code
                    ORDER BY t.created_at DESC LIMIT 100
                """),
                {"fid": factory_id, "code": material_code},
            )
        ).mappings().all()
        xfer_rows = (
            await self.db.execute(
                text("""
                    SELECT * FROM wms_transfer_requests
                    WHERE factory_id = :fid AND material_code = :code
                    ORDER BY created_at DESC LIMIT 20
                """),
                {"fid": factory_id, "code": material_code},
            )
        ).mappings().all()
        return {
            "material_code": material_code,
            "warehouses": [dict(r) for r in inv_rows],
            "transactions": [dict(r) for r in txn_rows],
            "transfers": [dict(r) for r in xfer_rows],
        }

    # ==================== 8. 调拨审批 ====================

    async def create_transfer_request(
        self,
        factory_id: str,
        material_id: str,
        material_code: str,
        quantity: int,
        from_warehouse_id: str,
        to_warehouse_id: str,
        *,
        material_name: Optional[str] = None,
        to_location_id: Optional[str] = None,
        requested_by: str = "system",
        remark: Optional[str] = None,
        submit: bool = False,
    ) -> Dict[str, Any]:
        rid = _gen_id()
        rcode = _code("XFR")
        status = "pending" if submit else "draft"
        await self.db.execute(
            text("""
                INSERT INTO wms_transfer_requests
                (id, factory_id, request_code, material_id, material_code, material_name, quantity,
                 from_warehouse_id, to_warehouse_id, to_location_id, status, requested_by, remark)
                VALUES (:id, :fid, :code, :mid, :mcode, :mname, :qty, :from, :to, :tol, :st, :by, :rmk)
            """),
            {
                "id": rid, "fid": factory_id, "code": rcode, "mid": material_id,
                "mcode": material_code, "mname": material_name, "qty": quantity,
                "from": from_warehouse_id, "to": to_warehouse_id, "tol": to_location_id,
                "st": status, "by": requested_by, "rmk": remark,
            },
        )
        await self.db.commit()
        return {"success": True, "request_id": rid, "request_code": rcode, "status": status}

    async def approve_transfer_request(
        self,
        request_id: str,
        *,
        approved_by: str,
        execute: bool = True,
    ) -> Dict[str, Any]:
        row = (
            await self.db.execute(
                text("SELECT * FROM wms_transfer_requests WHERE id = :id"),
                {"id": request_id},
            )
        ).mappings().first()
        if not row:
            return {"success": False, "message": "调拨申请不存在"}
        if row["status"] not in ("pending", "draft"):
            return {"success": False, "message": f"状态 {row['status']} 不可审批"}
        await self.db.execute(
            text("""
                UPDATE wms_transfer_requests SET status = 'approved', approved_by = :by, approved_at = NOW()
                WHERE id = :id
            """),
            {"id": request_id, "by": approved_by},
        )
        result: Dict[str, Any] = {"success": True, "request_id": request_id, "status": "approved"}
        if execute:
            from api.services.wms_operation_service import WmsOperationService
            op = WmsOperationService(self.db)
            xfer = await op.transfer(
                factory_id=row["factory_id"],
                material_id=row["material_id"],
                quantity=row["quantity"],
                from_warehouse_id=row["from_warehouse_id"],
                to_warehouse_id=row["to_warehouse_id"],
                to_location_id=row.get("to_location_id"),
                operator=approved_by,
                remark=f"调拨审批执行 {row['request_code']}",
            )
            if xfer.get("success"):
                await self.db.execute(
                    text("""
                        UPDATE wms_transfer_requests SET status = 'completed', completed_at = NOW()
                        WHERE id = :id
                    """),
                    {"id": request_id},
                )
                result["execution"] = xfer
                result["status"] = "completed"
            else:
                result["execution"] = xfer
        await self.db.commit()
        return result

    async def reject_transfer_request(
        self,
        request_id: str,
        *,
        rejected_by: str,
        reason: str,
    ) -> Dict[str, Any]:
        await self.db.execute(
            text("""
                UPDATE wms_transfer_requests SET status = 'rejected', approved_by = :by,
                    rejected_reason = :reason, approved_at = NOW()
                WHERE id = :id AND status IN ('pending', 'draft')
            """),
            {"id": request_id, "by": rejected_by, "reason": reason},
        )
        await self.db.commit()
        return {"success": True, "request_id": request_id, "status": "rejected"}

    async def list_transfer_requests(
        self,
        factory_id: str,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        q = "SELECT * FROM wms_transfer_requests WHERE factory_id = :fid"
        params: Dict[str, Any] = {"fid": factory_id}
        if status:
            q += " AND status = :st"
            params["st"] = status
        q += " ORDER BY created_at DESC LIMIT 50"
        rows = (await self.db.execute(text(q), params)).mappings().all()
        return {"items": [dict(r) for r in rows], "total": len(rows)}

    # ==================== 9. 冻结/解冻 ====================

    async def freeze_inventory(
        self,
        inventory_id: str,
        *,
        reason_code: str,
        reason_text: Optional[str] = None,
        freeze_until: Optional[datetime] = None,
        auto_unfreeze: bool = False,
        frozen_by: str = "system",
    ) -> Dict[str, Any]:
        inv = await self.db.get(Inventory, inventory_id)
        if not inv:
            return {"success": False, "message": "库存不存在"}
        fid = _gen_id()
        inv.status = "frozen"
        inv.updated_at = datetime.utcnow()
        await self.db.execute(
            text("""
                INSERT INTO inventory_freezes
                (id, factory_id, inventory_id, material_id, material_code, batch_code,
                 reason_code, reason_text, freeze_until, frozen_by, auto_unfreeze)
                VALUES (:id, :fid, :inv, :mid, :code, :batch, :rc, :rt, :until, :by, :auto)
            """),
            {
                "id": fid, "fid": inv.factory_id, "inv": inventory_id,
                "mid": inv.material_id, "code": inv.material_code, "batch": inv.batch_code,
                "rc": reason_code, "rt": reason_text, "until": freeze_until,
                "by": frozen_by, "auto": auto_unfreeze,
            },
        )
        await self.db.commit()
        return {"success": True, "freeze_id": fid, "inventory_id": inventory_id, "status": "frozen"}

    async def unfreeze_inventory(
        self,
        freeze_id: str,
        *,
        unfrozen_by: str = "system",
    ) -> Dict[str, Any]:
        row = (
            await self.db.execute(
                text("SELECT * FROM inventory_freezes WHERE id = :id AND status = 'active'"),
                {"id": freeze_id},
            )
        ).mappings().first()
        if not row:
            return {"success": False, "message": "冻结记录不存在或已解冻"}
        inv = await self.db.get(Inventory, row["inventory_id"])
        if inv:
            inv.status = "available"
            inv.updated_at = datetime.utcnow()
        await self.db.execute(
            text("""
                UPDATE inventory_freezes SET status = 'released', unfrozen_by = :by, unfrozen_at = NOW()
                WHERE id = :id
            """),
            {"id": freeze_id, "by": unfrozen_by},
        )
        await self.db.commit()
        return {"success": True, "freeze_id": freeze_id, "status": "released"}

    async def run_auto_unfreeze(self, factory_id: str) -> Dict[str, Any]:
        rows = (
            await self.db.execute(
                text("""
                    SELECT id, inventory_id FROM inventory_freezes
                    WHERE factory_id = :fid AND status = 'active' AND auto_unfreeze = TRUE
                      AND freeze_until IS NOT NULL AND freeze_until <= NOW()
                """),
                {"fid": factory_id},
            )
        ).mappings().all()
        count = 0
        for r in rows:
            await self.unfreeze_inventory(r["id"], unfrozen_by="system_auto")
            count += 1
        return {"success": True, "unfrozen_count": count}

    async def list_freezes(self, factory_id: str, status: str = "active") -> Dict[str, Any]:
        rows = (
            await self.db.execute(
                text("SELECT * FROM inventory_freezes WHERE factory_id = :fid AND status = :st ORDER BY created_at DESC"),
                {"fid": factory_id, "st": status},
            )
        ).mappings().all()
        return {"items": [dict(r) for r in rows], "total": len(rows)}

    # ==================== 10. 盘点差异 ====================

    async def submit_cycle_count_for_approval(self, task_id: str) -> Dict[str, Any]:
        task = (
            await self.db.execute(
                text("SELECT * FROM cycle_count_tasks WHERE id = :id"),
                {"id": task_id},
            )
        ).mappings().first()
        if not task:
            return {"success": False, "message": "盘点任务不存在"}
        items = (
            await self.db.execute(
                text("SELECT * FROM cycle_count_items WHERE task_id = :tid"),
                {"tid": task_id},
            )
        ).mappings().all()
        diff_items = [dict(i) for i in items if i.get("diff_qty") not in (None, 0)]
        summary = {
            "total_items": len(items),
            "diff_items": len(diff_items),
            "total_diff_qty": sum(abs(int(i.get("diff_qty") or 0)) for i in diff_items),
            "details": diff_items[:50],
        }
        await self.db.execute(
            text("""
                UPDATE cycle_count_tasks SET approval_status = 'pending', status = 'completed'
                WHERE id = :id
            """),
            {"id": task_id},
        )
        await self.db.commit()
        return {"success": True, "task_id": task_id, "approval_status": "pending", "variance_summary": summary}

    async def approve_cycle_count_variance(
        self,
        task_id: str,
        *,
        approved_by: str,
    ) -> Dict[str, Any]:
        items = (
            await self.db.execute(
                text("""
                    SELECT ci.*, i.id AS inv_id, i.factory_id, i.material_id, i.batch_code
                    FROM cycle_count_items ci
                    LEFT JOIN inventory i ON i.material_id = ci.material_id AND i.location_id = ci.location_id
                    JOIN cycle_count_tasks ct ON ct.id = ci.task_id
                    WHERE ci.task_id = :tid AND ci.diff_qty IS NOT NULL AND ci.diff_qty != 0
                """),
                {"tid": task_id},
            )
        ).mappings().all()
        adjusted = 0
        task = (
            await self.db.execute(
                text("SELECT factory_id FROM cycle_count_tasks WHERE id = :id"),
                {"id": task_id},
            )
        ).mappings().first()
        if not task:
            return {"success": False, "message": "任务不存在"}
        factory_id = task["factory_id"]
        for item in items:
            diff = int(item["diff_qty"] or 0)
            inv_id = item.get("inv_id")
            if inv_id:
                inv = await self.db.get(Inventory, inv_id)
                if inv:
                    inv.total_qty = int(item["counted_qty"] or 0)
                    inv.available_qty = max(0, inv.total_qty - (inv.reserved_qty or 0))
                    inv.updated_at = datetime.utcnow()
            txn = InventoryTransaction(
                id=_gen_id(),
                factory_id=factory_id,
                inventory_id=inv_id or _gen_id(),
                material_id=item["material_id"],
                batch_code=inv.batch_code if inv else None,
                transaction_type="count_adjust",
                quantity=diff,
                before_qty=int(item["system_qty"] or 0),
                after_qty=int(item["counted_qty"] or 0),
                operator=approved_by,
                remark="盘点差异调整",
                created_at=datetime.utcnow(),
            )
            self.db.add(txn)
            await self.db.execute(
                text("UPDATE cycle_count_items SET adjusted = TRUE WHERE id = :id"),
                {"id": item["id"]},
            )
            adjusted += 1
        await self.db.execute(
            text("""
                UPDATE cycle_count_tasks SET approval_status = 'approved', approved_by = :by,
                    approved_at = NOW(), variance_adjusted = TRUE
                WHERE id = :id
            """),
            {"id": task_id, "by": approved_by},
        )
        await self.db.commit()
        return {"success": True, "task_id": task_id, "adjusted_items": adjusted}

    async def variance_analysis(self, factory_id: str, task_id: Optional[str] = None) -> Dict[str, Any]:
        if task_id:
            q = """
                SELECT ci.*, ct.task_code FROM cycle_count_items ci
                JOIN cycle_count_tasks ct ON ct.id = ci.task_id
                WHERE ci.task_id = :tid AND ci.diff_qty IS NOT NULL AND ci.diff_qty != 0
            """
            params = {"tid": task_id}
        else:
            q = """
                SELECT ci.*, ct.task_code FROM cycle_count_items ci
                JOIN cycle_count_tasks ct ON ct.id = ci.task_id
                WHERE ct.factory_id = :fid AND ci.diff_qty IS NOT NULL AND ci.diff_qty != 0
                ORDER BY ci.counted_at DESC NULLS LAST LIMIT 100
            """
            params = {"fid": factory_id}
        rows = (await self.db.execute(text(q), params)).mappings().all()
        items = [dict(r) for r in rows]
        gain = sum(i["diff_qty"] for i in items if (i.get("diff_qty") or 0) > 0)
        loss = sum(abs(i["diff_qty"]) for i in items if (i.get("diff_qty") or 0) < 0)
        return {
            "factory_id": factory_id,
            "task_id": task_id,
            "variance_count": len(items),
            "gain_qty": gain,
            "loss_qty": loss,
            "items": items,
        }
