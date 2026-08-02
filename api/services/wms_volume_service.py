"""WMS 体积/重量管理：物料尺寸参数、库存体积汇总、发货装柜、空间利用率。"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 标准集装箱可用容积（m³，留 10% 装载余量）
CONTAINER_SPECS: Dict[str, Dict[str, float]] = {
    "20GP": {"gross_m3": 33.0, "usable_m3": 29.7},
    "40GP": {"gross_m3": 58.0, "usable_m3": 52.2},
    "40HQ": {"gross_m3": 67.7, "usable_m3": 60.9},
}


def _calc_unit_volume_m3(length_cm: Optional[float], width_cm: Optional[float], height_cm: Optional[float]) -> float:
    if not all(v is not None and v > 0 for v in (length_cm, width_cm, height_cm)):
        return 0.0
    return round(float(length_cm) * float(width_cm) * float(height_cm) / 1_000_000, 6)


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


class WmsVolumeService:
    """WMS 体积数据服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def track_volume(
        self,
        factory_id: str,
        material_code: str,
        *,
        material_id: Optional[str] = None,
        material_name: Optional[str] = None,
        length_cm: Optional[float] = None,
        width_cm: Optional[float] = None,
        height_cm: Optional[float] = None,
        unit_weight_kg: Optional[float] = None,
        quantity: Optional[int] = None,
        warehouse_id: Optional[str] = None,
        batch_code: Optional[str] = None,
        operator: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录/更新物料体积参数，并按库存量计算占用。"""
        mid = material_id or material_code
        unit_vol = _calc_unit_volume_m3(length_cm, width_cm, height_cm)
        weight = _as_float(unit_weight_kg)

        existing = (
            await self.db.execute(
                text("""
                    SELECT id, unit_volume_m3, unit_weight_kg
                    FROM material_volume_specs
                    WHERE factory_id = :fid AND material_code = :code
                """),
                {"fid": factory_id, "code": material_code},
            )
        ).mappings().first()

        if existing:
            await self.db.execute(
                text("""
                    UPDATE material_volume_specs SET
                        material_id = :mid,
                        material_name = COALESCE(:mname, material_name),
                        length_cm = COALESCE(:l, length_cm),
                        width_cm = COALESCE(:w, width_cm),
                        height_cm = COALESCE(:h, height_cm),
                        unit_volume_m3 = CASE WHEN :l IS NOT NULL THEN :uv ELSE unit_volume_m3 END,
                        unit_weight_kg = CASE WHEN :wt IS NOT NULL THEN :wt ELSE unit_weight_kg END,
                        updated_at = NOW()
                    WHERE factory_id = :fid AND material_code = :code
                """),
                {
                    "fid": factory_id,
                    "code": material_code,
                    "mid": mid,
                    "mname": material_name,
                    "l": length_cm,
                    "w": width_cm,
                    "h": height_cm,
                    "uv": unit_vol,
                    "wt": weight if unit_weight_kg is not None else None,
                },
            )
            spec_id = existing["id"]
        else:
            spec_id = str(uuid.uuid4())
            await self.db.execute(
                text("""
                    INSERT INTO material_volume_specs (
                        id, factory_id, material_id, material_code, material_name,
                        length_cm, width_cm, height_cm, unit_volume_m3, unit_weight_kg
                    ) VALUES (
                        :id, :fid, :mid, :code, :mname,
                        :l, :w, :h, :uv, :wt
                    )
                """),
                {
                    "id": spec_id,
                    "fid": factory_id,
                    "mid": mid,
                    "code": material_code,
                    "mname": material_name,
                    "l": length_cm,
                    "w": width_cm,
                    "h": height_cm,
                    "uv": unit_vol,
                    "wt": weight,
                },
            )

        inv_qty = quantity
        if inv_qty is None:
            inv_filter = """
                SELECT COALESCE(SUM(available_qty), 0) AS qty
                FROM inventory
                WHERE factory_id = :fid AND material_code = :code AND status != 'deleted'
            """
            params: Dict[str, Any] = {"fid": factory_id, "code": material_code}
            if warehouse_id:
                inv_filter += " AND warehouse_id = :wh"
                params["wh"] = warehouse_id
            if batch_code:
                inv_filter += " AND batch_code = :batch"
                params["batch"] = batch_code
            row = (await self.db.execute(text(inv_filter), params)).mappings().first()
            inv_qty = int(row["qty"] or 0) if row else 0

        final = (
            await self.db.execute(
                text("""
                    SELECT unit_volume_m3, unit_weight_kg, length_cm, width_cm, height_cm
                    FROM material_volume_specs
                    WHERE id = :id
                """),
                {"id": spec_id},
            )
        ).mappings().first() or {}

        uv = _as_float(final.get("unit_volume_m3"), unit_vol)
        uw = _as_float(final.get("unit_weight_kg"), weight)
        total_vol = round(uv * inv_qty, 4)
        total_wt = round(uw * inv_qty, 4)

        await self.db.commit()
        return {
            "spec_id": spec_id,
            "factory_id": factory_id,
            "material_code": material_code,
            "material_id": mid,
            "dimensions_cm": {
                "length": _as_float(final.get("length_cm"), length_cm or 0),
                "width": _as_float(final.get("width_cm"), width_cm or 0),
                "height": _as_float(final.get("height_cm"), height_cm or 0),
            },
            "unit_volume_m3": uv,
            "unit_weight_kg": uw,
            "inventory_qty": inv_qty,
            "total_volume_m3": total_vol,
            "total_weight_kg": total_wt,
            "warehouse_id": warehouse_id,
            "batch_code": batch_code,
            "tracked_by": operator,
            "tracked_at": datetime.utcnow().isoformat() + "Z",
        }

    async def update_volume(
        self,
        factory_id: str,
        material_code: str,
        *,
        length_cm: Optional[float] = None,
        width_cm: Optional[float] = None,
        height_cm: Optional[float] = None,
        unit_weight_kg: Optional[float] = None,
        material_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """更新物料体积参数（不触发库存量重算）。"""
        return await self.track_volume(
            factory_id,
            material_code,
            material_name=material_name,
            length_cm=length_cm,
            width_cm=width_cm,
            height_cm=height_cm,
            unit_weight_kg=unit_weight_kg,
            quantity=0,
        )

    async def get_volume_summary(
        self,
        factory_id: str,
        warehouse_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """统计工厂/仓库库存总体积与总重量。"""
        where = "i.factory_id = :fid AND i.status != 'deleted' AND i.available_qty > 0"
        params: Dict[str, Any] = {"fid": factory_id}
        if warehouse_id:
            where += " AND i.warehouse_id = :wh"
            params["wh"] = warehouse_id

        rows = (
            await self.db.execute(
                text(f"""
                    SELECT
                        i.material_code,
                        COALESCE(i.material_name, s.material_name, '') AS material_name,
                        SUM(i.available_qty) AS qty,
                        COALESCE(s.unit_volume_m3, 0) AS unit_volume_m3,
                        COALESCE(s.unit_weight_kg, 0) AS unit_weight_kg
                    FROM inventory i
                    LEFT JOIN material_volume_specs s
                      ON s.factory_id = i.factory_id AND s.material_code = i.material_code
                    WHERE {where}
                    GROUP BY i.material_code, i.material_name, s.material_name,
                             s.unit_volume_m3, s.unit_weight_kg
                    ORDER BY SUM(i.available_qty * COALESCE(s.unit_volume_m3, 0)) DESC
                """),
                params,
            )
        ).mappings().all()

        items: List[Dict[str, Any]] = []
        total_vol = 0.0
        total_wt = 0.0
        total_qty = 0
        missing_specs = 0
        for row in rows:
            qty = int(row["qty"] or 0)
            uv = _as_float(row["unit_volume_m3"])
            uw = _as_float(row["unit_weight_kg"])
            line_vol = round(uv * qty, 4)
            line_wt = round(uw * qty, 4)
            if uv <= 0 and uw <= 0:
                missing_specs += 1
            total_vol += line_vol
            total_wt += line_wt
            total_qty += qty
            items.append({
                "material_code": row["material_code"],
                "material_name": row["material_name"],
                "qty": qty,
                "unit_volume_m3": uv,
                "unit_weight_kg": uw,
                "total_volume_m3": line_vol,
                "total_weight_kg": line_wt,
            })

        return {
            "factory_id": factory_id,
            "warehouse_id": warehouse_id,
            "sku_count": len(items),
            "total_qty": total_qty,
            "total_volume_m3": round(total_vol, 4),
            "total_weight_kg": round(total_wt, 4),
            "missing_volume_spec_count": missing_specs,
            "items": items,
        }

    async def calculate_shipping_volume(
        self,
        factory_id: str,
        lines: List[Dict[str, Any]],
        container_type: str = "40HQ",
    ) -> Dict[str, Any]:
        """按发运明细计算总体积/重量及所需集装箱数。"""
        spec = CONTAINER_SPECS.get(container_type.upper(), CONTAINER_SPECS["40HQ"])
        usable = spec["usable_m3"]

        detail: List[Dict[str, Any]] = []
        total_vol = 0.0
        total_wt = 0.0
        total_qty = 0

        for line in lines:
            code = line.get("material_code") or line.get("material_id")
            if not code:
                continue
            qty = int(line.get("quantity") or line.get("qty") or 0)
            if qty <= 0:
                continue

            row = (
                await self.db.execute(
                    text("""
                        SELECT unit_volume_m3, unit_weight_kg, material_name
                        FROM material_volume_specs
                        WHERE factory_id = :fid AND material_code = :code
                    """),
                    {"fid": factory_id, "code": code},
                )
            ).mappings().first()

            uv = _as_float(row["unit_volume_m3"]) if row else 0.0
            uw = _as_float(row["unit_weight_kg"]) if row else 0.0
            if uv <= 0 and all(line.get(k) for k in ("length_cm", "width_cm", "height_cm")):
                uv = _calc_unit_volume_m3(
                    line.get("length_cm"), line.get("width_cm"), line.get("height_cm")
                )
            if uw <= 0 and line.get("unit_weight_kg"):
                uw = _as_float(line["unit_weight_kg"])

            line_vol = round(uv * qty, 4)
            line_wt = round(uw * qty, 4)
            total_vol += line_vol
            total_wt += line_wt
            total_qty += qty
            detail.append({
                "material_code": code,
                "material_name": (row or {}).get("material_name"),
                "quantity": qty,
                "unit_volume_m3": uv,
                "unit_weight_kg": uw,
                "total_volume_m3": line_vol,
                "total_weight_kg": line_wt,
            })

        containers_needed = max(1, int(-(-total_vol / usable // 1))) if total_vol > 0 else 0
        if total_vol <= 0:
            containers_needed = 0

        return {
            "factory_id": factory_id,
            "container_type": container_type.upper(),
            "container_usable_m3": usable,
            "total_quantity": total_qty,
            "total_volume_m3": round(total_vol, 4),
            "total_weight_kg": round(total_wt, 4),
            "containers_needed": containers_needed,
            "volume_utilization_pct": round(total_vol / (containers_needed * usable) * 100, 1)
            if containers_needed else 0.0,
            "lines": detail,
        }

    async def get_space_utilization(
        self,
        factory_id: str,
        warehouse_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """分析仓库空间利用率（库存占用体积 vs 仓库/库位容量）。"""
        wh_filter = "w.factory_id = :fid AND w.status = 'active'"
        params: Dict[str, Any] = {"fid": factory_id}
        if warehouse_id:
            wh_filter += " AND w.id = :wh"
            params["wh"] = warehouse_id

        warehouses = (
            await self.db.execute(
                text(f"""
                    SELECT w.id, w.warehouse_code, w.warehouse_name,
                           COALESCE(w.usable_volume_m3, w.total_volume_m3, 0) AS capacity_m3,
                           COALESCE(SUM(l.capacity), 0) AS location_capacity_units
                    FROM warehouses w
                    LEFT JOIN locations l ON l.warehouse_id = w.id AND l.status = 'active'
                    WHERE {wh_filter}
                    GROUP BY w.id, w.warehouse_code, w.warehouse_name,
                             w.usable_volume_m3, w.total_volume_m3
                """),
                params,
            )
        ).mappings().all()

        summary = await self.get_volume_summary(factory_id, warehouse_id)
        used_by_wh: Dict[str, float] = {}
        if warehouse_id:
            used_by_wh[warehouse_id] = summary["total_volume_m3"]
        else:
            inv_rows = (
                await self.db.execute(
                    text("""
                        SELECT i.warehouse_id,
                               SUM(i.available_qty * COALESCE(s.unit_volume_m3, 0)) AS used_m3
                        FROM inventory i
                        LEFT JOIN material_volume_specs s
                          ON s.factory_id = i.factory_id AND s.material_code = i.material_code
                        WHERE i.factory_id = :fid AND i.status != 'deleted'
                        GROUP BY i.warehouse_id
                    """),
                    {"fid": factory_id},
                )
            ).mappings().all()
            for r in inv_rows:
                used_by_wh[str(r["warehouse_id"])] = round(_as_float(r["used_m3"]), 4)

        items: List[Dict[str, Any]] = []
        for wh in warehouses:
            wid = str(wh["id"])
            capacity = _as_float(wh["capacity_m3"])
            used = used_by_wh.get(wid, 0.0)
            util = round(used / capacity * 100, 1) if capacity > 0 else None
            items.append({
                "warehouse_id": wid,
                "warehouse_code": wh["warehouse_code"],
                "warehouse_name": wh["warehouse_name"],
                "capacity_m3": capacity,
                "used_volume_m3": used,
                "free_volume_m3": round(max(capacity - used, 0), 4) if capacity > 0 else None,
                "utilization_pct": util,
                "location_capacity_units": int(wh["location_capacity_units"] or 0),
            })

        total_cap = sum(i["capacity_m3"] for i in items)
        total_used = sum(i["used_volume_m3"] for i in items)
        return {
            "factory_id": factory_id,
            "warehouse_count": len(items),
            "total_capacity_m3": round(total_cap, 4),
            "total_used_volume_m3": round(total_used, 4),
            "overall_utilization_pct": round(total_used / total_cap * 100, 1) if total_cap > 0 else None,
            "warehouses": items,
        }
