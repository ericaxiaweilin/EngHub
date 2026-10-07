"""PMC 工作矩阵：把订单/工单评审所需的证据汇总成可追溯数据。

这里不替 PMC 做承诺，也不猜测企业自定义指标的口径；每个参数都返回
value、unit、source、status，缺数据时明确标记为 unknown，而不是补一个假值。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from math import ceil
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    ApsSchedule,
    ApsScheduleTask,
    BomItem,
    Inventory,
    InventoryTransaction,
    Product,
    Routing,
    Station,
    WorkOrder,
)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_number(value: Any, default: float = 0.0) -> float:
    """Normalize Decimal/SQLite string values returned by raw procurement queries."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _age_days(value: Any, now: Optional[datetime] = None) -> Optional[int]:
    """Return calendar age in days for a date/datetime/string value."""
    if value is None:
        return None
    now = now or datetime.utcnow()
    if isinstance(value, datetime):
        return max(0, (now - value).days)
    parsed_date = _as_date(value)
    return max(0, (now.date() - parsed_date).days) if parsed_date else None


def _working_days(start: date, end: date) -> int:
    return _working_days_with_options(start, end, skip_vietnam_holidays=False)


def _working_days_with_options(
    start: date,
    end: date,
    *,
    skip_vietnam_holidays: bool,
    holiday_dates: Optional[Set[date]] = None,
    working_dates: Optional[Set[date]] = None,
) -> int:
    if end < start:
        return 0
    holiday_dates = holiday_dates or set()
    working_dates = working_dates or set()
    return sum(
        1
        for offset in range((end - start).days + 1)
        if (
            (start + timedelta(days=offset)) in working_dates
            or (
                (start + timedelta(days=offset)).weekday() < 5
                and not (skip_vietnam_holidays and (start + timedelta(days=offset)) in holiday_dates)
            )
        )
    )


def _next_working_day(
    day: date,
    *,
    skip_vietnam_holidays: bool,
    holiday_dates: Optional[Set[date]] = None,
    working_dates: Optional[Set[date]] = None,
) -> date:
    holiday_dates = holiday_dates or set()
    working_dates = working_dates or set()
    candidate = day
    while candidate not in working_dates and (
        candidate.weekday() >= 5 or (skip_vietnam_holidays and candidate in holiday_dates)
    ):
        candidate += timedelta(days=1)
    return candidate


def _add_working_hours(
    start: datetime,
    hours: float,
    *,
    daily_hours: float,
    skip_vietnam_holidays: bool,
    holiday_dates: Optional[Set[date]] = None,
    working_dates: Optional[Set[date]] = None,
) -> datetime:
    """用工作日和班次容量估算完成时刻；不伪装成精确 APS 排程。"""
    remaining = max(0.0, float(hours or 0))
    cursor = _next_working_day(
        start.date(),
        skip_vietnam_holidays=skip_vietnam_holidays,
        holiday_dates=holiday_dates,
        working_dates=working_dates,
    )
    while remaining > 0:
        remaining -= daily_hours
        if remaining <= 0:
            return datetime.combine(cursor, time(hour=8)) + timedelta(hours=max(0.0, daily_hours + remaining))
        cursor = _next_working_day(
            cursor + timedelta(days=1),
            skip_vietnam_holidays=skip_vietnam_holidays,
            holiday_dates=holiday_dates,
            working_dates=working_dates,
        )
    return datetime.combine(cursor, time(hour=8))


def _normalize_options(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    iqc_mode = str(raw.get("iqc_mode") or "exempt")
    if iqc_mode not in {"exempt", "sampling", "full"}:
        iqc_mode = "exempt"
    shift_mode = str(raw.get("shift_mode") or "single")
    if shift_mode not in {"single", "double"}:
        shift_mode = "single"
    line_occupancy = str(raw.get("line_occupancy") or "exclusive")
    if line_occupancy not in {"exclusive", "shared_50"}:
        line_occupancy = "exclusive"
    customs_mode = str(raw.get("customs_mode") or "none")
    if customs_mode not in {"none", "random"}:
        customs_mode = "none"
    try:
        yield_rate = float(raw.get("yield_rate", 0.97))
    except (TypeError, ValueError):
        yield_rate = 0.97
    yield_rate = max(0.5, min(1.0, yield_rate))
    try:
        container_hours = float(raw.get("container_hours", 2))
    except (TypeError, ValueError):
        container_hours = 2.0
    try:
        dead_stock_days = int(raw.get("dead_stock_days", 180))
    except (TypeError, ValueError):
        dead_stock_days = 180
    try:
        material_eta_delay_days = float(raw.get("material_eta_delay_days", 0))
    except (TypeError, ValueError):
        material_eta_delay_days = 0.0
    return {
        # 是否使用工厂通过 APS 日历接口配置的日期级假期；没有配置时不会猜测。
        "skip_vietnam_holidays": bool(raw.get("skip_vietnam_holidays", True)),
        "shift_mode": shift_mode,
        "shift_hours_per_day": 20.0 if shift_mode == "double" else 10.0,
        "iqc_mode": iqc_mode,
        "iqc_delay_hours": {"exempt": 0.0, "sampling": 4.0, "full": 8.0}[iqc_mode],
        "substitute_material_available": bool(raw.get("substitute_material_available", False)),
        "yield_rate": yield_rate,
        "line_occupancy": line_occupancy,
        "line_share": 0.5 if line_occupancy == "shared_50" else 1.0,
        "container_hours": max(0.0, container_hours),
        "customs_mode": customs_mode,
        "customs_delay_hours": 24.0 if customs_mode == "random" else 0.0,
        "dead_stock_days": max(0, dead_stock_days),
        "material_eta_delay_days": max(0.0, material_eta_delay_days),
        "enable_air_freight": bool(raw.get("enable_air_freight", False)),
        "transport_days": 1 if bool(raw.get("enable_air_freight", False)) else 5,
        "accept_subcontracting": bool(raw.get("accept_subcontracting", False)),
        "subcontract_capacity_factor": 2.0 if bool(raw.get("accept_subcontracting", False)) else 1.0,
    }


def _option_schema() -> List[Dict[str, Any]]:
    return [
        {"group": "时间锤", "key": "skip_vietnam_holidays", "label": "跳过接口配置的越南法定假期", "type": "boolean", "description": "读取 APS 日期级工作日历接口中当前工厂/年度的法定休息日和补休；没有配置时不会自动猜测日期。", "business_talk": "仓库不上班时，ETA 自动顺延，避免误算。"},
        {"group": "时间锤", "key": "shift_mode", "label": "班次", "type": "select", "options": [{"value": "single", "label": "单班（10h）"}, {"value": "double", "label": "双班（20h）"}], "description": "影响每天理论可加工工时。"},
        {"group": "物料锤", "key": "iqc_mode", "label": "IQC 来料检", "type": "select", "options": [{"value": "exempt", "label": "免检（+0h）"}, {"value": "sampling", "label": "抽检（+4h）"}, {"value": "full", "label": "全检（+8h）"}], "description": "作为物料进入生产前的时间缓冲。"},
        {"group": "物料锤", "key": "dead_stock_days", "label": "呆滞料阈值", "type": "number", "min": 0, "max": 3650, "step": 1, "unit": "天", "description": "按最后库存流动时间识别呆滞料，默认180天。"},
        {"group": "物料锤", "key": "material_eta_delay_days", "label": "物料 ETA 延迟", "type": "number", "min": 0, "max": 365, "step": 1, "unit": "天", "description": "模拟在途/采购物料比原 ETA 晚到几天。"},
        {"group": "物料锤", "key": "substitute_material_available", "label": "有可用替代料", "type": "boolean", "description": "仅当缺料时把结论转为“条件放行”，不会伪造库存。"},
        {"group": "生产锤", "key": "yield_rate", "label": "预期直通率", "type": "number", "min": 0.95, "max": 0.99, "step": 0.01, "unit": "%", "description": "按需求量 ÷ 直通率倒推投入量。"},
        {"group": "生产锤", "key": "line_occupancy", "label": "线体占用", "type": "select", "options": [{"value": "exclusive", "label": "独占（100%）"}, {"value": "shared_50", "label": "共享（50%）"}], "description": "共享50%会把本工单可用产能折半。"},
        {"group": "出货锤", "key": "container_hours", "label": "装柜耗时", "type": "number", "min": 2, "max": 4, "step": 2, "unit": "h", "description": "旺季排队可从2h切换到4h。"},
        {"group": "出货锤", "key": "customs_mode", "label": "海关查验", "type": "select", "options": [{"value": "none", "label": "免查验（+0h）"}, {"value": "random", "label": "抽查（+24h）"}], "description": "影响 FG Ready 后的出货 ETA。"},
        {"group": "紧急锤", "key": "enable_air_freight", "label": "启用空运", "type": "boolean", "description": "运输假设从海运5天切换为空运1天，并提示成本增幅。"},
        {"group": "紧急锤", "key": "accept_subcontracting", "label": "接受外协加工", "type": "boolean", "description": "将可用产能按2倍沙盘估算，并提示外协成本/质量确认。"},
    ]


def _route_steps(routing: Optional[Routing]) -> List[Dict[str, Any]]:
    if not routing or not routing.steps:
        return []
    steps = routing.steps
    if isinstance(steps, str):
        import json
        try:
            steps = json.loads(steps)
        except (TypeError, ValueError):
            return []
    return [step for step in steps if isinstance(step, dict)] if isinstance(steps, list) else []


def _step_unit_hours(step: Dict[str, Any]) -> Optional[float]:
    """Read an explicit per-unit process time without inventing a UHN value."""
    for key in ("UHN", "uhn", "unit_hours_needed", "unit_hour_need"):
        if step.get(key) is not None:
            value = _as_number(step.get(key), default=-1)
            if value >= 0:
                return value
    if step.get("duration_min") is not None:
        value = _as_number(step.get("duration_min"), default=-1)
        return value / 60.0 if value >= 0 else None
    # routing_steps.standard_time is traditionally seconds in the legacy data.
    if step.get("standard_time") is not None:
        value = _as_number(step.get("standard_time"), default=-1)
        return value / 3600.0 if value >= 0 else None
    return None


class PmcWorkMatrixService:
    """面向 PMC 当前评审节点的工单证据矩阵。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _purchase_order_rows(
        self,
        factory_id: str,
        material_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """读取采购订单供应证据，并兼容尚未执行采购迁移的环境。"""
        sql = """
            SELECT po_code, supplier_name, material_code, qty, expected_date,
                   actual_date, status, order_date
            FROM purchase_orders
            WHERE factory_id = :fid
              AND status NOT IN ('received', 'closed', 'cancelled')
        """
        params: Dict[str, Any] = {"fid": factory_id}
        if material_code:
            sql += " AND material_code = :material_code"
            params["material_code"] = material_code
        # Keep the query valid for both PostgreSQL and the local SQLite demo DB.
        sql += " ORDER BY expected_date ASC, order_date ASC"
        try:
            # Procurement is optional during phased rollout.  A missing table
            # must roll back only this evidence lookup, not abort the whole
            # PMC matrix transaction and hide the otherwise valid BOM/inventory.
            async with self.db.begin_nested():
                result = await self.db.execute(text(sql), params)
                rows = [dict(row) for row in result.mappings().all()]
            return {"available": True, "rows": rows}
        except SQLAlchemyError as exc:
            # The main MES schema can be booted before procurement migration 031.
            # PMC must expose the missing evidence instead of failing the whole matrix.
            return {
                "available": False,
                "rows": [],
                "error": f"purchase_orders unavailable: {type(exc).__name__}",
            }

    async def _supplier_lead_time_rows(
        self,
        factory_id: str,
        material_code: str,
    ) -> Dict[str, Any]:
        """Read supplier quoted lead time for the PMC LT answer.

        优先读供应商报价表 supplier_prices（报价含 LT/MOQ/价格）；
        报价表无数据时降级读 supplier_materials（供应商物料绑定表，含 lead_time_days），
        避免供应商主数据存在但报价未维护时 LT 恒为 unknown。
        """
        try:
            async with self.db.begin_nested():
                result = await self.db.execute(text("""
                    SELECT s.supplier_code, s.supplier_name, sp.lead_days,
                           sp.moq, sp.currency, sp.unit_price
                    FROM supplier_prices sp
                    JOIN suppliers s ON s.id = sp.supplier_id
                    WHERE s.factory_id = :fid
                      AND sp.material_code = :material_code
                      AND sp.is_active = TRUE
                      AND s.is_approved = TRUE
                    ORDER BY sp.lead_days ASC, sp.unit_price ASC
                """), {"fid": factory_id, "material_code": material_code})
                rows = [dict(row) for row in result.mappings().all()]
            if rows:
                return {"available": True, "rows": rows, "source": "supplier_prices"}

            # 降级源：supplier_materials 供应商物料绑定（含 lead_time_days）
            async with self.db.begin_nested():
                result = await self.db.execute(text("""
                    SELECT s.supplier_code, s.supplier_name,
                           sm.lead_time_days AS lead_days,
                           sm.min_order_qty AS moq,
                           NULL AS currency,
                           sm.unit_cost AS unit_price
                    FROM supplier_materials sm
                    JOIN suppliers s ON s.id = sm.supplier_id
                    WHERE s.factory_id = :fid
                      AND sm.material_code = :material_code
                      AND sm.is_active = TRUE
                    ORDER BY sm.lead_time_days ASC, sm.unit_cost ASC
                """), {"fid": factory_id, "material_code": material_code})
                rows = [dict(row) for row in result.mappings().all()]
            # 降级源也是空的 → 就是没有数据，不能报 available=True：
            # 原来这里恒为 True，于是 supplier_lead_time_data_status 显示 "ready"、
            # 而 supplier_lead_days 是 None，界面上一格"有依据"的空数字。
            return {
                "available": bool(rows),
                "rows": rows,
                "source": "supplier_materials" if rows else "missing",
            }
        except SQLAlchemyError as exc:
            return {
                "available": False,
                "rows": [],
                "error": f"supplier_prices unavailable: {type(exc).__name__}",
            }

    async def _bom_reuse_candidates(
        self,
        factory_id: str,
        material_code: str,
    ) -> List[Dict[str, Any]]:
        """Find active products whose BOM can consume a material."""
        bom_result = await self.db.execute(
            select(BomItem).where(
                BomItem.factory_id == factory_id,
                BomItem.material_code == material_code,
            ).order_by(BomItem.product_id, BomItem.bom_version)
        )
        bom_items = list(bom_result.scalars().all())
        if not bom_items:
            return []

        refs = {str(item.product_id) for item in bom_items if item.product_id}
        products: Dict[str, Product] = {}
        if refs:
            product_result = await self.db.execute(
                select(Product).where(
                    Product.factory_id == factory_id,
                    or_(Product.id.in_(refs), Product.product_code.in_(refs)),
                )
            )
            for product in product_result.scalars().all():
                products[str(product.id)] = product
                products[str(product.product_code)] = product

        candidates: List[Dict[str, Any]] = []
        seen = set()
        for item in bom_items:
            ref = str(item.product_id or "")
            product = products.get(ref)
            key = (ref, item.bom_version, item.qty_per_unit or item.quantity or 0)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "product_id": product.id if product else item.product_id,
                "product_code": product.product_code if product else item.product_id,
                "product_name": product.product_name if product else None,
                "product_status": product.status if product else "unknown",
                "bom_version": item.bom_version,
                "qty_per_unit": _as_number(item.qty_per_unit or item.quantity or 0),
                "can_consume": bool(product is None or product.status == "active"),
            })
        return candidates

    async def _holiday_calendar_snapshot(
        self,
        factory_id: str,
        start: date,
        end: date,
    ) -> Dict[str, Any]:
        """读取 APS 日期级日历；日历缺失时返回证据缺失，不回退到代码内日期。"""
        try:
            # Keep this interface deployable when the host's consolidated ORM
            # has not yet caught up with the calendar migration.
            async with self.db.begin_nested():
                result = await self.db.execute(text("""
                    SELECT calendar_code, year, holiday_date, holiday_name,
                           holiday_type, is_working_day, source_name, source_url
                    FROM aps_holidays
                    WHERE factory_id = :factory_id
                      AND is_active = TRUE
                      AND year BETWEEN :start_year AND :end_year
                    ORDER BY holiday_date
                """), {
                    "factory_id": factory_id,
                    "start_year": start.year,
                    "end_year": end.year,
                })
                items = [SimpleNamespace(**dict(row)) for row in result.mappings().all()]
        except SQLAlchemyError as exc:
            return {
                "configured": False,
                "status": "missing",
                "code": None,
                "items": [],
                "holiday_dates": set(),
                "working_dates": set(),
                "error": f"aps_holidays unavailable: {type(exc).__name__}",
            }

        return {
            "configured": bool(items),
            "status": "ready" if items else "missing",
            "code": items[0].calendar_code if items else None,
            "items": items,
            "holiday_dates": {item.holiday_date for item in items if not item.is_working_day},
            "working_dates": {item.holiday_date for item in items if item.is_working_day},
            "source_name": next((item.source_name for item in items if item.source_name), None),
            "source_url": next((item.source_url for item in items if item.source_url), None),
            "error": None,
        }

    async def _material_snapshot(
        self,
        factory_id: str,
        material_code: str,
        dead_stock_days: int = 180,
    ) -> Dict[str, Any]:
        """Build one shared inventory + PO + BOM evidence snapshot."""
        inventory_result = await self.db.execute(
            select(Inventory).where(
                Inventory.factory_id == factory_id,
                Inventory.material_code == material_code,
            )
        )
        inventories = list(inventory_result.scalars().all())

        available_qty = sum(_as_number(item.available_qty) for item in inventories)
        total_qty = sum(_as_number(item.total_qty) for item in inventories)
        reserved_qty = sum(_as_number(item.reserved_qty) for item in inventories)
        qualified_qty = sum(
            _as_number(item.available_qty)
            for item in inventories
            if (item.status or "available") == "available"
            and (item.qualified_status or "qualified") == "qualified"
        )

        material_ids = {str(item.material_id) for item in inventories if item.material_id}
        transaction_times: List[Any] = []
        if material_ids:
            txn_result = await self.db.execute(
                select(InventoryTransaction.created_at).where(
                    InventoryTransaction.factory_id == factory_id,
                    InventoryTransaction.material_id.in_(material_ids),
                ).order_by(InventoryTransaction.created_at.desc())
            )
            transaction_times = list(txn_result.scalars().all())

        movement_times = [item.last_movement_at for item in inventories if item.last_movement_at]
        if transaction_times:
            movement_times.append(transaction_times[0])
        if not movement_times:
            movement_times = [item.created_at for item in inventories if item.created_at]
        last_movement = max(movement_times) if movement_times else None
        aging_days = _age_days(last_movement)
        dead_stock = bool(
            available_qty > 0
            and aging_days is not None
            and aging_days >= dead_stock_days
        )

        po_snapshot = await self._purchase_order_rows(factory_id, material_code)
        po_rows = po_snapshot["rows"]
        on_order_qty = 0.0
        in_transit_qty = 0.0
        po_details: List[Dict[str, Any]] = []
        for row in po_rows:
            qty = _as_number(row.get("qty"))
            status = str(row.get("status") or "").lower()
            if status == "shipped":
                in_transit_qty += qty
            else:
                on_order_qty += qty
            expected = row.get("expected_date")
            po_details.append({
                "po_code": row.get("po_code"),
                "supplier_name": row.get("supplier_name"),
                "qty": qty,
                "status": status,
                "expected_date": _iso(expected),
                "actual_date": _iso(row.get("actual_date")),
                "days_to_eta": (_as_date(expected) - date.today()).days if _as_date(expected) else None,
            })

        lead_time_snapshot = await self._supplier_lead_time_rows(factory_id, material_code)
        supplier_lead_times = [
            {
                "supplier_code": row.get("supplier_code"),
                "supplier_name": row.get("supplier_name"),
                "lead_days": _as_number(row.get("lead_days")),
                "moq": _as_number(row.get("moq")),
                "currency": row.get("currency"),
                "unit_price": _as_number(row.get("unit_price")),
            }
            for row in lead_time_snapshot["rows"]
        ]

        reuse_candidates = await self._bom_reuse_candidates(factory_id, material_code)
        return {
            "material_code": material_code,
            "material_name": next((item.material_name for item in inventories if item.material_name), material_code),
            "unit": next((item.unit for item in inventories if item.unit), "pcs"),
            "total_qty": round(total_qty, 2),
            "available_qty": round(available_qty, 2),
            "reserved_qty": round(reserved_qty, 2),
            "qualified_available_qty": round(qualified_qty, 2),
            "last_movement_at": _iso(last_movement),
            "aging_days": aging_days,
            "dead_stock_days": dead_stock_days,
            "dead_stock": dead_stock,
            "on_order_qty": round(on_order_qty, 2),
            "in_transit_qty": round(in_transit_qty, 2),
            "open_supply_qty": round(on_order_qty + in_transit_qty, 2),
            "po_codes": [row.get("po_code") for row in po_details if row.get("po_code")],
            "purchase_orders": po_details,
            "purchase_order_data_status": "ready" if po_snapshot["available"] else "missing",
            "purchase_order_source_error": po_snapshot.get("error"),
            "supplier_lead_days": min((row["lead_days"] for row in supplier_lead_times), default=None),
            "supplier_lead_times": supplier_lead_times,
            "supplier_lead_time_data_status": "ready" if lead_time_snapshot["available"] else "missing",
            "supplier_lead_time_source_error": lead_time_snapshot.get("error"),
            "bom_reuse_candidates": reuse_candidates,
        }

    async def query_material_supply(
        self,
        factory_id: str,
        material_keyword: Optional[str] = None,
        days_threshold: int = 180,
        limit: int = 50,
        only_stagnant: bool = False,
    ) -> Dict[str, Any]:
        """Chatbot/PMC shared query for inventory aging, BOM reuse and PO supply."""
        days_threshold = max(0, int(days_threshold or 180))
        limit = max(1, min(int(limit or 50), 200))
        keyword = (material_keyword or "").strip()

        # Do not materialize every SKU and then execute five evidence queries
        # per item.  A production factory can have tens of thousands of SKUs;
        # the previous implementation applied ``limit`` only after that N+1
        # fan-out and made the PMC supply panel unusable.
        inventory_stmt = select(Inventory.material_code).where(Inventory.factory_id == factory_id)
        if keyword:
            inventory_stmt = inventory_stmt.where(
                or_(
                    Inventory.material_code.ilike(f"%{keyword}%"),
                    Inventory.material_name.ilike(f"%{keyword}%"),
                )
            )
        candidate_limit = limit
        if only_stagnant:
            candidate_limit = min(max(limit * 3, limit), 200)
            cutoff = datetime.utcnow() - timedelta(days=days_threshold)
            inventory_stmt = inventory_stmt.where(
                Inventory.available_qty > 0,
                Inventory.last_movement_at.is_not(None),
                Inventory.last_movement_at <= cutoff,
            ).order_by(Inventory.last_movement_at.asc())
        else:
            inventory_stmt = inventory_stmt.order_by(Inventory.material_code.asc())

        material_result = await self.db.execute(inventory_stmt.distinct().limit(candidate_limit))
        material_codes = {str(code) for code in material_result.scalars().all() if code}

        # Include PO-only materials so the PMC can see a purchase that has not arrived yet.
        po_snapshot = await self._purchase_order_rows(factory_id)
        for row in po_snapshot["rows"]:
            code = str(row.get("material_code") or "")
            if (
                code
                and (not keyword or keyword.lower() in code.lower())
                and (code in material_codes or len(material_codes) < candidate_limit)
            ):
                material_codes.add(code)

        snapshots = []
        for code in sorted(material_codes):
            snapshot = await self._material_snapshot(factory_id, code, days_threshold)
            if only_stagnant and not snapshot["dead_stock"]:
                continue
            snapshots.append(snapshot)

        snapshots.sort(
            key=lambda item: (
                not item["dead_stock"],
                -(item["aging_days"] or 0),
                item["material_code"],
            )
        )
        snapshots = snapshots[:limit]
        return {
            "type": "pmc_material_supply",
            "factory_id": factory_id,
            "threshold_days": days_threshold,
            "material_keyword": keyword or None,
            "count": len(snapshots),
            "stagnant_count": sum(1 for item in snapshots if item["dead_stock"]),
            "items": snapshots,
            "candidate_count": len(material_codes),
            "query_scope": "candidate page; refine material_keyword for a specific material",
            "purchase_order_data_status": "ready" if po_snapshot["available"] else "missing",
            "note": "available_qty 是现有可用库存；open_supply_qty 是未收货PO供应，in_transit_qty 是已出货未收货PO；supplier_lead_days 来自有效供应商报价。BOM候选只表示主数据关联，是否可用仍需确认批次质量与版本。",
        }

    async def build(
        self,
        factory_id: str,
        work_order_code: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        options = _normalize_options(options)
        work_order_result = await self.db.execute(
            select(WorkOrder).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.work_order_code == work_order_code,
            )
        )
        work_order = work_order_result.scalar_one_or_none()
        if not work_order:
            return {
                "type": "pmc_work_matrix",
                "error": f"未找到工单 {work_order_code}",
                "hint": "请提供当前工厂下的主工单号；矩阵不会用虚拟字段补齐不存在的数据。",
            }

        product_result = await self.db.execute(
            select(Product).where(
                Product.factory_id == factory_id,
                or_(Product.id == work_order.product_id, Product.product_code == work_order.product_id),
            )
        )
        product = product_result.scalar_one_or_none()
        product_refs = {str(work_order.product_id)}
        if product:
            product_refs.update({str(product.id), str(product.product_code)})

        routing_result = await self.db.execute(
            select(Routing).where(
                Routing.factory_id == factory_id,
                or_(Routing.id == work_order.routing_id, Routing.product_id.in_(product_refs)),
                Routing.is_active.is_(True),
            ).order_by(Routing.updated_at.desc())
        )
        routing = routing_result.scalars().first()
        route_steps = _route_steps(routing)

        demand_qty = int(work_order.planned_qty or 0)
        rdd = _as_date(work_order.planned_due)
        today = date.today()
        horizon_end = rdd or (today + timedelta(days=7))
        holiday_calendar = await self._holiday_calendar_snapshot(factory_id, today, horizon_end)
        holiday_dates = holiday_calendar["holiday_dates"]
        working_dates = holiday_calendar["working_dates"]
        workdays = _working_days_with_options(
            today,
            horizon_end,
            skip_vietnam_holidays=options["skip_vietnam_holidays"],
            holiday_dates=holiday_dates,
            working_dates=working_dates,
        )
        skipped_holidays = sum(
            1
            for offset in range(max(0, (horizon_end - today).days + 1))
            if (today + timedelta(days=offset)) in holiday_dates
            and (today + timedelta(days=offset)) not in working_dates
        ) if options["skip_vietnam_holidays"] else 0

        # 物料证据：BOM 毛需求 vs 库存可用量。
        bom_result = await self.db.execute(
            select(BomItem).where(
                BomItem.factory_id == factory_id,
                or_(
                    BomItem.product_id.in_(product_refs),
                    BomItem.product_sap_code.in_(product_refs),
                    BomItem.model_name.in_(product_refs),
                ),
            ).order_by(BomItem.level, BomItem.material_code)
        )
        bom_items = list(bom_result.scalars().all())
        material_rows: List[Dict[str, Any]] = []
        for bom in bom_items:
            required_qty = float(bom.qty_per_unit or bom.quantity or 0) * demand_qty
            snapshot = await self._material_snapshot(
                factory_id,
                bom.material_code,
                options["dead_stock_days"],
            )
            available_qty = snapshot["available_qty"]
            reserved_qty = snapshot["reserved_qty"]
            shortage_qty = max(0.0, required_qty - available_qty)
            projected_shortage_qty = max(
                0.0,
                required_qty - available_qty - snapshot["open_supply_qty"],
            )
            qualified_shortage_qty = max(
                0.0,
                required_qty - snapshot["qualified_available_qty"],
            )
            if shortage_qty <= 0:
                kit_status = "ready"
            elif projected_shortage_qty <= 0:
                kit_status = "conditional_on_po"
            else:
                kit_status = "shortage"
            material_rows.append({
                "material_code": bom.material_code,
                "material_name": bom.material_name or snapshot["material_name"] or bom.material_code,
                "unit": bom.unit or snapshot["unit"] or "pcs",
                "required_qty": round(required_qty, 2),
                "available_qty": round(available_qty, 2),
                "reserved_qty": round(reserved_qty, 2),
                "shortage_qty": round(shortage_qty, 2),
                "projected_shortage_qty": round(projected_shortage_qty, 2),
                "qualified_shortage_qty": round(qualified_shortage_qty, 2),
                "on_order_qty": snapshot["on_order_qty"],
                "in_transit_qty": snapshot["in_transit_qty"],
                "open_supply_qty": snapshot["open_supply_qty"],
                "po_codes": snapshot["po_codes"],
                "purchase_orders": snapshot["purchase_orders"],
                "purchase_order_data_status": snapshot["purchase_order_data_status"],
                "supplier_lead_days": snapshot["supplier_lead_days"],
                "supplier_lead_times": snapshot["supplier_lead_times"],
                "supplier_lead_time_data_status": snapshot["supplier_lead_time_data_status"],
                "last_movement_at": snapshot["last_movement_at"],
                "aging_days": snapshot["aging_days"],
                "dead_stock": snapshot["dead_stock"],
                "dead_stock_reusable_for_order": bool(
                    snapshot["dead_stock"]
                    and snapshot["qualified_available_qty"] >= required_qty
                ),
                "bom_reuse_candidates": snapshot["bom_reuse_candidates"],
                "kit_status": kit_status,
                "source": "bom_items + inventory + inventory_transactions + purchase_orders",
            })

        # 提前期的出处必须跟着数字走：`supplier_lead_days` 可能来自台账铺的默认值
        # （本厂 31,452 个外购料号只有 10 个不同取值），也可能真有采购/仓收实测。
        # 判据只写在 core/mes/data_evidence 一处，这里一次性批量取，不按料号循环查库。
        lead_unverified = 0
        lead_no_row = 0
        lead_measured = 0
        lead_evidence_error: Optional[str] = None
        lead_census_basis = ""
        if material_rows:
            try:
                from core.mes.data_evidence import lead_time_evidence

                codes = sorted({str(r["material_code"]) for r in material_rows if r.get("material_code")})
                census = await lead_time_evidence(self.db, factory_id, codes=codes, limit=max(1, len(codes)))
                lead_census_basis = str(census.get("basis") or "")
                by_code = {str(r["material_code"]): r for r in census.get("rows") or []}
                for row in material_rows:
                    e = by_code.get(str(row.get("material_code"))) or {}
                    measured = e.get("measured") or {}
                    row["ledger_lead_time_days"] = e.get("ledger_days")
                    row["lead_evidence"] = e.get("verdict") or "no_ledger_row"
                    row["lead_measured_median_days"] = measured.get("median_days")
                    row["lead_measured_n"] = measured.get("n")
                    row["lead_suggested_days"] = e.get("suggested_days")
                    if row["lead_evidence"] == "unverified_default":
                        lead_unverified += 1
                    elif row["lead_evidence"] == "no_ledger_row":
                        lead_no_row += 1
                    if measured.get("n"):
                        lead_measured += 1
            except Exception as exc:  # noqa: BLE001  出处查不到要说出来，不能当成"没问题"
                lead_evidence_error = f"{type(exc).__name__}: {exc}"[:200]
                for row in material_rows:
                    row["lead_evidence"] = "evidence_query_failed"
        lead_no_evidence = len(material_rows) - lead_measured

        # 产能证据：工位理论可用工时 - 已排程工时。生产锤会改变“有效产能”和倒推投入量。
        capacity_rows: List[Dict[str, Any]] = []
        required_production_qty = int(ceil(demand_qty / max(options["yield_rate"], 0.01)))
        capacity_factor = options["line_share"] * options["subcontract_capacity_factor"]
        route_station_refs = [
            step.get("station_id") or step.get("station") or step.get("work_center")
            for step in route_steps
        ]
        if work_order.assigned_station_id:
            route_station_refs.insert(0, work_order.assigned_station_id)
        seen_station_refs = set()
        seen_station_ids = set()
        for station_ref in route_station_refs:
            if not station_ref or station_ref in seen_station_refs:
                continue
            seen_station_refs.add(station_ref)
            station_result = await self.db.execute(
                select(Station).where(
                    Station.factory_id == factory_id,
                    or_(Station.id == station_ref, Station.station_code == station_ref),
                )
            )
            station = station_result.scalar_one_or_none()
            if not station:
                capacity_rows.append({
                    "station_id": station_ref,
                    "station_name": station_ref,
                    "status": "unknown",
                    "source": "未找到 stations 主数据",
                })
                continue
            # A work order often carries the first station by ID while routing
            # carries it by station code.  They are one resource, not two
            # capacity buckets.
            if station.id in seen_station_ids:
                continue
            seen_station_ids.add(station.id)

            station_identifiers = {str(station_ref), str(station.id), str(station.station_code)}
            station_steps = [
                step for step in route_steps
                if str(step.get("station_id") or step.get("station") or step.get("work_center")) in station_identifiers
            ]
            station_unit_hours = [
                value for value in (_step_unit_hours(step) for step in station_steps)
                if value is not None
            ]
            daily_hours = options["shift_hours_per_day"]
            nominal_capacity = float(station.capacity_per_hour or 0)
            # availability is time, not units: capacity_per_hour is used only to
            # convert demand into hours when no explicit UHN exists in routing.
            theoretical_hours = daily_hours * workdays * options["line_share"]
            tasks_result = await self.db.execute(
                select(ApsScheduleTask).join(
                    ApsSchedule, ApsScheduleTask.schedule_id == ApsSchedule.id
                ).where(
                    ApsSchedule.factory_id == factory_id,
                    ApsSchedule.status.in_(["draft", "confirmed", "released", "active"]),
                    ApsScheduleTask.station_id == station.id,
                    ApsScheduleTask.planned_start < datetime.combine(horizon_end, datetime.max.time()),
                    ApsScheduleTask.planned_end > datetime.combine(today, datetime.min.time()),
                )
            )
            loaded_hours = 0.0
            for task in tasks_result.scalars().all():
                if task.planned_start and task.planned_end:
                    loaded_hours += max(0.0, (task.planned_end - task.planned_start).total_seconds() / 3600)
            available_hours = max(0.0, theoretical_hours - loaded_hours)
            utilization = (loaded_hours / theoretical_hours * 100) if theoretical_hours else None
            effective_capacity_per_hour = nominal_capacity * options["subcontract_capacity_factor"]
            required_hours = (
                required_production_qty * sum(station_unit_hours) / options["subcontract_capacity_factor"]
                if station_unit_hours
                else required_production_qty / effective_capacity_per_hour
                if effective_capacity_per_hour
                else None
            )
            capacity_rows.append({
                "station_id": station.station_code,
                "station_name": station.station_name,
                "capacity_per_hour": station.capacity_per_hour or 0,
                "effective_capacity_per_hour": round(effective_capacity_per_hour, 2),
                "working_days": workdays,
                "shift_hours_per_day": daily_hours,
                "theoretical_hours": round(theoretical_hours, 2),
                "loaded_hours": round(loaded_hours, 2),
                "available_machining_hours": round(available_hours, 2),
                "required_production_qty": required_production_qty,
                "required_hours": round(required_hours, 2) if required_hours is not None else None,
                "unit_hours_needed": round(sum(station_unit_hours), 4) if station_unit_hours else None,
                "utilization_pct": round(utilization, 1) if utilization is not None else None,
                "status": "overloaded" if required_hours is not None and required_hours > available_hours else "available" if theoretical_hours else "unknown",
                "source": "stations.capacity_per_hour + aps_schedule_tasks + PMC生产锤",
            })

        # UHN 是企业自定义口径：只有流程/工艺定义显式提供时才填值。
        uhn_values = [value for value in (_step_unit_hours(step) for step in route_steps) if value is not None]
        uhn = round(sum(uhn_values), 4) if uhn_values else None
        shortage_count = sum(1 for row in material_rows if row["shortage_qty"] > 0)
        projected_shortage_count = sum(1 for row in material_rows if row["projected_shortage_qty"] > 0)
        dead_stock_count = sum(1 for row in material_rows if row["dead_stock"])
        capacity_unknown = any(row.get("status") == "unknown" for row in capacity_rows)
        capacity_overloaded = any(row.get("status") == "overloaded" for row in capacity_rows)
        purchase_order_data_available = bool(material_rows) and all(
            row.get("purchase_order_data_status") == "ready" for row in material_rows
        )
        material_ready = shortage_count == 0 if material_rows else None
        projected_material_ready = projected_shortage_count == 0 if material_rows else None
        material_decision = (
            "ready"
            if material_ready is True
            else "conditional_substitute"
            if shortage_count and options["substitute_material_available"]
            else "conditional_on_po"
            if shortage_count and projected_material_ready is True
            else "shortage"
            if projected_shortage_count
            else "unknown"
        )

        capacity_ready = bool(capacity_rows) and not capacity_unknown and all(
            row.get("required_hours") is not None for row in capacity_rows
        )
        production_hours = sum(row.get("required_hours") or 0 for row in capacity_rows) if capacity_ready else None
        iqc_delay_hours = options["iqc_delay_hours"]
        material_eta_delay_hours = options["material_eta_delay_days"] * 24.0
        fg_ready_hours = (
            production_hours
            + iqc_delay_hours
            + material_eta_delay_hours
            + options["container_hours"]
            + options["customs_delay_hours"]
            if production_hours is not None
            else None
        )
        start_at = work_order.planned_start or datetime.combine(today, time(hour=8))
        production_complete_at = (
            _add_working_hours(
                start_at,
                production_hours + iqc_delay_hours + material_eta_delay_hours,
                daily_hours=options["shift_hours_per_day"],
                skip_vietnam_holidays=options["skip_vietnam_holidays"],
                holiday_dates=holiday_dates,
                working_dates=working_dates,
            )
            if production_hours is not None
            else None
        )
        fg_ready_at = (
            _add_working_hours(
                start_at,
                fg_ready_hours,
                daily_hours=options["shift_hours_per_day"],
                skip_vietnam_holidays=options["skip_vietnam_holidays"],
                holiday_dates=holiday_dates,
                working_dates=working_dates,
            )
            if fg_ready_hours is not None
            else None
        )
        estimated_eta = fg_ready_at + timedelta(days=options["transport_days"]) if fg_ready_at else None
        # A valid RDD alone is not enough to calculate an ETA.  Legacy work
        # orders can legitimately lack routings/station capacity; keep that
        # as an evidence gap instead of crashing the whole PMC workbench.
        rdd_feasible = estimated_eta.date() <= rdd if rdd and estimated_eta else None
        yield_warning = not (0.95 <= options["yield_rate"] <= 0.99)

        calendar_missing = options["skip_vietnam_holidays"] and not holiday_calendar["configured"]
        if calendar_missing:
            next_focus = ["先通过 APS 日期级工作日历接口导入当前工厂的 VN 2026 法定日历", "日历未配置前，ETA 不能宣称已按越南法律排除假期"]
        elif not rdd:
            next_focus = ["补齐 RDD/交付节点", "确认客户需求版本后再做倒排"]
        elif not material_rows:
            # 缺 BOM：主数据缺口，齐套率/ETA 无法计算。区分产品是否已有工艺路线，
            # 已有路由时产能证据仍可用，问题明确收敛到 BOM。
            if not route_steps:
                next_focus = ["产品缺工艺路线与已生效 BOM（双缺）", "先由工艺/工程绑定路由与 BOM 版本，再算齐套率与交期"]
            else:
                next_focus = ["补齐该成品的已生效 BOM 版本", "BOM 未生效前不能给出库存齐套率或 MRP 结论"]
        elif not capacity_rows or capacity_unknown:
            next_focus = ["补齐工艺路线和瓶颈工位主数据", "执行 CRP/APS 后再承诺交期"]
        elif projected_shortage_count and not options["substitute_material_available"]:
            next_focus = ["锁定缺料物料和 PO/在途 ETA", "确认采购交期或替代料，再决定 MPS 是否释放"]
        elif shortage_count and projected_material_ready is True:
            next_focus = ["确认 PO/在途按期到货", "到货后完成 IQC 放行，当前只能条件齐套"]
        elif shortage_count:
            next_focus = ["拿替代料料号和 IQC 放行条件", "替代料未完成验证前只能条件放行，不能视为完全齐套"]
        elif capacity_overloaded:
            next_focus = ["确认瓶颈工位可加工时间", "执行 CRP/APS 后再承诺交期"]
        elif rdd is not None and rdd_feasible is False:
            next_focus = ["当前 ETA 晚于 RDD，先选择空运/外协/加班", "向客户或销售确认新的承诺节点"]
        else:
            next_focus = ["核对需求量、RDD、物料和产能证据", "形成 MPS 草案并进入计划确认"]

        parameters = [
            {"key": "work_order_code", "label": "工单", "value": work_order.work_order_code, "status": "ready", "source": "work_orders"},
            {"key": "demand_qty", "label": "需求量", "value": demand_qty, "unit": work_order.unit or "pcs", "status": "ready", "source": "work_orders.planned_qty"},
            {"key": "rdd", "label": "RDD/需求交期", "value": _iso(work_order.planned_due), "status": "ready" if rdd else "missing", "source": "work_orders.planned_due"},
            {"key": "holiday_calendar", "label": "法定工作日历", "value": holiday_calendar["code"], "status": "ready" if holiday_calendar["configured"] else "missing", "source": "GET /api/v1/aps/holiday-calendars"},
            {"key": "UHN", "label": "UHN（企业口径）", "value": uhn, "unit": "h", "status": "ready" if uhn is not None else "unknown", "source": "routing.steps.UHN；当前模型未强制定义"},
            {"key": "available_machining_hours", "label": "可加工时间（瓶颈工位）", "value": round(min((row.get("available_machining_hours", 0) for row in capacity_rows), default=0), 2) if capacity_rows and not capacity_unknown else None, "unit": "h", "status": "blocked" if capacity_overloaded else "ready" if capacity_ready else "unknown", "source": "瓶颈工位：APS排程占用后的班次可用时长"},
            {"key": "inventory_kit_rate", "label": "库存齐套率", "value": round(sum(row["required_qty"] - row["shortage_qty"] for row in material_rows) / max(sum(row["required_qty"] for row in material_rows), 1) * 100, 1) if material_rows else None, "unit": "%", "status": "blocked" if shortage_count and not options["substitute_material_available"] else "conditional" if shortage_count else "ready" if material_rows else "unknown", "source": "BOM × Inventory.available_qty"},
            {"key": "projected_kit_rate", "label": "含 PO/在途预计齐套率", "value": round(sum(row["required_qty"] - row["projected_shortage_qty"] for row in material_rows) / max(sum(row["required_qty"] for row in material_rows), 1) * 100, 1) if material_rows else None, "unit": "%", "status": "blocked" if projected_shortage_count else "conditional" if shortage_count else "ready" if material_rows else "unknown", "source": "BOM × Inventory × purchase_orders"},
            {"key": "in_transit_qty", "label": "在途数量", "value": round(sum(row["in_transit_qty"] for row in material_rows), 2) if material_rows else None, "unit": work_order.unit or "pcs", "status": "ready" if purchase_order_data_available else "missing", "source": "purchase_orders.status=shipped"},
            {"key": "on_order_qty", "label": "未收货 PO 数量", "value": round(sum(row["on_order_qty"] for row in material_rows), 2) if material_rows else None, "unit": work_order.unit or "pcs", "status": "ready" if purchase_order_data_available else "missing", "source": "purchase_orders 未收货状态"},
            {"key": "po_count", "label": "关联 PO 数", "value": len({po for row in material_rows for po in row["po_codes"]}), "unit": "单", "status": "ready" if purchase_order_data_available else "missing", "source": "purchase_orders.po_code"},
            {"key": "supplier_lead_days", "label": "供应商最短 LT", "value": min((row["supplier_lead_days"] for row in material_rows if row["supplier_lead_days"] is not None), default=None), "unit": "天", "status": "ready" if any(row["supplier_lead_days"] is not None for row in material_rows) else "unknown", "source": "supplier_prices.lead_days"},
            {"key": "lead_evidence", "label": "提前期出处",
             "value": (f"{lead_no_evidence}/{len(material_rows)} 项没有实测证据"
                       if (material_rows and not lead_evidence_error)
                       else ("查询失败" if lead_evidence_error else None))
                      + (f"（铺值 {lead_unverified}、无台账行 {lead_no_row}、"
                         f"其余 {lead_no_evidence - lead_unverified - lead_no_row} 个只有台账声明）"
                         if material_rows and not lead_evidence_error else ""),
             "unit": "项", "status": "warning" if lead_unverified else "ready" if material_rows else "unknown",
             "source": lead_census_basis or "core/mes/data_evidence（台账 vs 采购实测 vs 仓收 vs 供应商声明）"},
            {"key": "dead_stock_material_count", "label": "BOM涉及呆滞料数", "value": dead_stock_count, "unit": "种", "status": "warning" if dead_stock_count else "ready", "source": f"库存最后流动时间 ≥ {options['dead_stock_days']}天"},
            {"key": "required_production_qty", "label": "按直通率倒推投入量", "value": required_production_qty, "unit": work_order.unit or "pcs", "status": "warning" if yield_warning else "ready", "source": "需求量 ÷ 预期直通率"},
            {"key": "required_production_hours", "label": "需求生产工时", "value": round(production_hours, 2) if production_hours is not None else None, "unit": "h", "status": "blocked" if capacity_overloaded else "ready" if capacity_ready else "unknown", "source": "工艺 UHN；未定义时以产能速度倒推"},
            {"key": "production_complete_at", "label": "预计生产完成", "value": _iso(production_complete_at), "status": "ready" if production_complete_at else "unknown", "source": "生产工时 + IQC缓冲 + 工作日历"},
            {"key": "fg_ready_at", "label": "FG Ready", "value": _iso(fg_ready_at), "status": "ready" if fg_ready_at else "unknown", "source": "生产完成 + 装柜 + 海关"},
            {"key": "estimated_eta", "label": "预计 ETA", "value": _iso(estimated_eta), "status": "blocked" if rdd_feasible is False else "ready" if estimated_eta else "unknown", "source": "FG Ready + 海运/空运"},
        ]

        risk_flags: List[str] = []
        if calendar_missing:
            risk_flags.append("APS 日期级法定工作日历未配置；系统没有使用代码内假期兜底，ETA 仅为未排除法定假期的沙盘值")
        if options["skip_vietnam_holidays"] and skipped_holidays:
            risk_flags.append(f"已按 APS 接口日历跳过 {skipped_holidays} 个法定/补休日期")
        if shortage_count and options["substitute_material_available"]:
            risk_flags.append("缺料仅因替代料开关暂时转为条件放行，需验证替代料")
        if shortage_count and projected_material_ready is True:
            risk_flags.append("当前库存未齐套，但关联 PO/在途数量覆盖缺口，需确认按 ETA 到货并完成 IQC")
        if lead_evidence_error:
            risk_flags.append(f"提前期出处普查本次失败（{lead_evidence_error}）：这一轮的 LT 出处未知，"
                              "不能按「都量过」或「都没问题」理解")
        elif lead_no_evidence and material_rows:
            risk_flags.append(f"BOM 涉及 {len(material_rows)} 个料号，其中 {lead_no_evidence} 个没有任何实测到货依据"
                              f"（{lead_unverified} 个的提前期是按类别铺的默认值 —— 同组几十~几千个料号共用一个取值；"
                              f"{lead_no_row} 个连台账行都没有）；本厂 65 单采购实测到货中位 54 天，"
                              "而台账均值只有 9.9 天 —— ETA/齐套按这个数算会系统性偏乐观。"
                              f"有实测的 {lead_measured} 个可在物料行看实测中位天数与建议值")
        if dead_stock_count:
            reusable_count = sum(1 for row in material_rows if row["dead_stock_reusable_for_order"])
            risk_flags.append(f"BOM涉及 {dead_stock_count} 种呆滞料，其中 {reusable_count} 种满足当前工单需求且库存状态合格")
        if options["material_eta_delay_days"]:
            risk_flags.append(f"物料 ETA 沙盘延迟 {options['material_eta_delay_days']:g} 天")
        if options["line_occupancy"] == "shared_50":
            risk_flags.append("线体共享50%，有效产能已折半")
        if options["enable_air_freight"]:
            risk_flags.append("空运将运输假设从5天缩短至1天，但会增加运输成本")
        if options["accept_subcontracting"]:
            risk_flags.append("外协按产能翻倍沙盘估算，需补充供应商、质量和成本确认")
        if yield_warning:
            risk_flags.append("直通率超出建议的95%~99%沙盘区间，请确认口径")
        if rdd_feasible is False:
            risk_flags.append(f"预计 ETA {_iso(estimated_eta)} 晚于 RDD {_iso(rdd)}")

        overall = (
            "blocked"
            if not rdd or (projected_shortage_count and not options["substitute_material_available"]) or capacity_overloaded or rdd_feasible is False
            else "needs_evidence"
            if calendar_missing
            else "conditional"
            if shortage_count or options["enable_air_freight"] or options["accept_subcontracting"]
            else "ready_for_mps"
            if capacity_ready
            else "needs_evidence"
        )

        return {
            "type": "pmc_work_matrix",
            "title": f"PMC 工作矩阵 · {work_order.work_order_code}",
            "factory_id": factory_id,
            "calendar": {
                "code": holiday_calendar["code"],
                "status": holiday_calendar["status"],
                "configured": holiday_calendar["configured"],
                "year": sorted({item.year for item in holiday_calendar["items"]}),
                "applies_to_factory": factory_id,
                "holiday_count": len(holiday_calendar["items"]),
                "dates": [
                    {"date": item.holiday_date.isoformat(), "name": item.holiday_name, "type": item.holiday_type, "is_working_day": item.is_working_day}
                    for item in holiday_calendar["items"]
                ],
                "source_name": holiday_calendar["source_name"],
                "source_url": holiday_calendar["source_url"],
                "error": holiday_calendar["error"],
                "endpoint": "/api/v1/aps/holiday-calendars",
            },
            "work_order": {
                "id": work_order.id,
                "code": work_order.work_order_code,
                "product_id": work_order.product_id,
                "product_name": product.product_name if product else None,
                "status": work_order.status,
                "planned_qty": demand_qty,
                "planned_due": _iso(work_order.planned_due),
                "current_stage": work_order.current_stage,
                "next_station": work_order.next_station,
            },
            "parameters": parameters,
            "options": options,
            "option_schema": _option_schema(),
            "materials": material_rows,
            "capacity": capacity_rows,
                "judgement": {
                    "material_ready": material_ready,
                    "material_decision": material_decision,
                    "projected_material_ready": projected_material_ready,
                "capacity_feasible": False if capacity_overloaded else True if capacity_ready else None,
                "rdd_present": bool(rdd),
                "rdd_feasible": rdd_feasible,
                "overall": overall,
            },
            "computed": {
                "required_production_qty": required_production_qty,
                "production_hours": round(production_hours, 2) if production_hours is not None else None,
                "iqc_delay_hours": iqc_delay_hours,
                "material_eta_delay_hours": material_eta_delay_hours,
                "dead_stock_days": options["dead_stock_days"],
                "container_hours": options["container_hours"],
                "customs_delay_hours": options["customs_delay_hours"],
                "transport_days": options["transport_days"],
                "production_complete_at": _iso(production_complete_at),
                "fg_ready_at": _iso(fg_ready_at),
                "estimated_eta": _iso(estimated_eta),
            },
            "risk_flags": risk_flags,
            "next_focus": next_focus,
            "deliverables": [
                "PMC 工作矩阵",
                "物料齐套/缺料清单",
                "产能可加工时间证据",
                "MPS 可行性结论（待 PMC 确认）",
            ],
            "matrix_columns": [
                {"key": "key", "label": "参数"},
                {"key": "value", "label": "当前值"},
                {"key": "unit", "label": "单位"},
                {"key": "status", "label": "状态"},
                {"key": "source", "label": "数据来源"},
            ],
            "matrix_rows": parameters,
            "note": "法定假期由 APS 日期级工作日历接口维护，PMC 不在代码内内置假期日期。两个工厂可通过同一批量接口写入同一日历编码；这些开关是 PMC 预排程假设，不会覆盖工单主数据。UHN 未在当前数据模型中定义，系统不会擅自猜测其含义。",
        }


__all__ = ["PmcWorkMatrixService"]
