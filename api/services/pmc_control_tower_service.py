"""PMC control-tower facts for the chatbot.

This service is deliberately read-only.  It provides one stable, auditable
contract for the questions a PMC manager asks repeatedly: orders, materials,
shortage, inventory, OTD, capacity, rush orders, engineering changes and
supplier delays.

The running database has been deployed in phases, so every optional source is
checked before it is queried.  A missing source is returned as ``missing``;
zero rows are returned as ``ready`` with an explicit zero.  The chatbot can
therefore distinguish "there are no records" from "the source is not
available" without inventing a business conclusion.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import json
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


SCOPES = {
    "all",
    "orders",
    "materials",
    "shortage",
    "inventory",
    "otd",
    "capacity",
    "rush",
    "engineering_change",
    "supplier_delay",
}


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value is not None else None)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _status(key: str, status: str, source: str, note: str = "") -> Dict[str, Any]:
    return {"key": key, "status": status, "source": source, "note": note}


def _steps(route: Any) -> List[Dict[str, Any]]:
    value = _json(route)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _step_hours(step: Dict[str, Any]) -> Optional[float]:
    for key in ("UHN", "uhn", "unit_hours_needed", "unit_hour_need"):
        if step.get(key) is not None:
            number = _number(step.get(key), -1)
            return number if number >= 0 else None
    if step.get("duration_min") is not None:
        number = _number(step.get("duration_min"), -1)
        return number / 60 if number >= 0 else None
    if step.get("standard_time") is not None:
        number = _number(step.get("standard_time"), -1)
        return number / 3600 if number >= 0 else None
    return None


class PmcControlTowerService:
    """Read-only cross-module PMC facts with explicit evidence status."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.tables: Set[str] = set()
        self.columns: Dict[str, Set[str]] = {}

    async def _load_tables(self) -> None:
        try:
            rows = await self.db.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """))
            self.tables = {str(row[0]) for row in rows.all()}
            column_rows = await self.db.execute(text("""
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
            """))
            for table_name, column_name in column_rows.all():
                self.columns.setdefault(str(table_name), set()).add(str(column_name))
        except SQLAlchemyError:
            # Unit tests and local SQLite demos do not expose information_schema.
            try:
                rows = await self.db.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
                self.tables = {str(row[0]) for row in rows.all()}
                for table in self.tables:
                    column_rows = await self.db.execute(text(f"PRAGMA table_info({table})"))
                    self.columns[table] = {str(row[1]) for row in column_rows.all()}
            except SQLAlchemyError:
                self.tables = set()
                self.columns = {}

    def _has(self, table: str) -> bool:
        return table in self.tables

    def _has_column(self, table: str, column: str) -> bool:
        return column in self.columns.get(table, set())

    async def _rows(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        try:
            result = await self.db.execute(text(sql), params or {})
            return [dict(row) for row in result.mappings().all()]
        except SQLAlchemyError:
            # Optional sources must never abort the chatbot's whole answer.
            return []

    async def _count(self, table: str, where: str = "", params: Optional[Dict[str, Any]] = None) -> int:
        if not self._has(table):
            return 0
        rows = await self._rows(f"SELECT COUNT(*) AS n FROM {table} {where}", params)
        return int(rows[0].get("n") or 0) if rows else 0

    def _scope_list(self, scope: str) -> List[str]:
        scope = scope if scope in SCOPES else "all"
        return ["orders", "materials", "shortage", "inventory", "otd", "capacity", "rush", "engineering_change", "supplier_delay"] if scope == "all" else [scope]

    async def collect(
        self,
        factory_id: str,
        scope: str = "all",
        *,
        material_keyword: Optional[str] = None,
        work_order_code: Optional[str] = None,
        days: int = 180,
        rush_quantity: Optional[int] = None,
        rush_due_date: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        await self._load_tables()
        scope = scope if scope in SCOPES else "all"
        days = max(0, min(int(days or 180), 3650))
        limit = max(1, min(int(limit or 20), 100))
        result: Dict[str, Any] = {
            "type": "pmc_control_tower",
            "factory_id": factory_id,
            "scope": scope,
            "generated_at": datetime.utcnow().isoformat(),
            "facts": {},
            "data_quality": [],
            "method": {
                "orders": "APS任务的去重工单数为实际排程订单数；MPS/工单数仅作为计划记录，不冒充APS排程历史。",
                "materials": "BOM、工单物料和库存SKU分别计数；库存流水物料数用于判断历史控制证据。",
                "shortage": "优先使用工单物料齐套记录的 shortage_qty；在途和PO只有供应表存在时才计入预计齐套。",
                "otd": "已完工且 actual_complete 不晚于 planned_due 的订单 / 已完工订单；无销售订单时明确标记为工单口径。",
                "capacity": "优先使用APS任务负荷；没有APS任务时使用工艺路线UHN与工位CPH估算，并标记partial。",
                "rush": "插单先做只读影响评估，再走审批，审批执行后生成新的APS版本；本查询不修改排程。",
                "engineering_change": "ECN记录、受影响工单标记和BOM版本分别核对；没有变更历史不推断已完成传播。",
                "supplier_delay": "以PO expected_date与actual_date/status判断逾期；没有PO表或记录时明确为missing/zero。",
            },
        }
        for key in self._scope_list(scope):
            handler = getattr(self, f"_{key}")
            result["facts"][key] = await handler(
                factory_id,
                material_keyword=material_keyword,
                work_order_code=work_order_code,
                days=days,
                rush_quantity=rush_quantity,
                rush_due_date=rush_due_date,
                limit=limit,
            )
        result["data_quality"] = self._quality(result["facts"])
        result["actions"] = self._actions(result["facts"])
        return result

    def _quality(self, facts: Dict[str, Any]) -> List[Dict[str, Any]]:
        quality: List[Dict[str, Any]] = []
        for key, value in facts.items():
            quality.append({
                "key": key,
                "status": value.get("data_status", "unknown"),
                "source": value.get("source"),
                "missing_sources": value.get("missing_sources", []),
                "note": value.get("data_note", ""),
            })
        return quality

    def _actions(self, facts: Dict[str, Any]) -> List[str]:
        actions: List[str] = []
        shortage = facts.get("shortage", {})
        if shortage.get("total_shortage_qty", 0) > 0:
            actions.append("Shortage：先锁定缺口物料与受影响工单；补齐PO/供应商ETA或完成替代料验证后再放行。")
        inventory = facts.get("inventory", {})
        if inventory.get("stagnant_count", 0) > 0:
            actions.append("库存：优先把呆滞料与当前BOM复用需求匹配，停止无需求补货，再处理调拨/退供应商/报废审批。")
        capacity = facts.get("capacity", {})
        if capacity.get("bottlenecks"):
            actions.append("产能：按瓶颈工位负荷排序，先调整未开工工单，再评估加班、换线、外协或分批交付。")
        rush = facts.get("rush", {})
        if rush.get("approval_count", 0) == 0:
            actions.append("插单：当前没有插单审批执行记录；正式插单应先做影响评估并取得审批，再生成APS新版本。")
        supplier = facts.get("supplier_delay", {})
        if supplier.get("overdue_count", 0) > 0:
            actions.append("供应商延迟：按逾期天数升级跟催，同时把受影响工单纳入重新评审。")
        engineering = facts.get("engineering_change", {})
        if engineering.get("ecn_count", 0) > 0:
            actions.append("EC/BOM：先确认ECN批准状态与生效BOM版本，再对受影响工单重算MRP并触发APS重排。")
        return actions

    async def _orders(self, factory_id: str, **_: Any) -> Dict[str, Any]:
        missing: List[str] = []
        if not self._has("pp_plans"):
            missing.append("pp_plans")
        if not self._has("work_orders"):
            missing.append("work_orders")
        aps_schedule_count = await self._count("aps_schedules", "WHERE factory_id = :fid", {"fid": factory_id})
        task_rows = await self._rows("""
            SELECT DISTINCT work_order_id, order_code
            FROM aps_schedule_tasks t
            JOIN aps_schedules s ON s.id = t.schedule_id
            WHERE s.factory_id = :fid AND t.work_order_id IS NOT NULL
        """, {"fid": factory_id}) if self._has("aps_schedule_tasks") and self._has("aps_schedules") else []
        plan_count = await self._count("pp_plans", "WHERE factory_id = :fid", {"fid": factory_id})
        wo_rows = await self._rows("""
            SELECT work_order_code, status, planned_qty, completed_qty, planned_due, actual_complete,
                   wo_type, source_plan_id
            FROM work_orders
            WHERE factory_id = :fid
            ORDER BY created_at DESC
        """, {"fid": factory_id}) if self._has("work_orders") else []
        master_rows = [row for row in wo_rows if (row.get("wo_type") or "master") == "master"]
        status_counts = dict(Counter(str(row.get("status") or "unknown") for row in wo_rows))
        return {
            "data_status": "missing" if missing else "partial" if not self._has("aps_schedule_tasks") or not self._has("aps_schedules") else "ready",
            "source": "pp_plans + work_orders + aps_schedules + aps_schedule_tasks",
            "missing_sources": missing + (["aps_schedules/aps_schedule_tasks"] if not task_rows and (not self._has("aps_schedules") or not self._has("aps_schedule_tasks")) else []),
            "data_note": "当前APS排程历史为空时，scheduled_order_count=0；不能用MPS或工单数替代APS排程数。",
            "scheduled_order_count": len(task_rows),
            "aps_schedule_count": aps_schedule_count,
            "aps_task_count": await self._count("aps_schedule_tasks", "WHERE schedule_id IN (SELECT id FROM aps_schedules WHERE factory_id = :fid)", {"fid": factory_id}) if self._has("aps_schedule_tasks") and self._has("aps_schedules") else 0,
            "mps_plan_count": plan_count,
            "mps_planned_qty": await self._sum("pp_plans", "quantity", "factory_id = :fid", {"fid": factory_id}),
            "work_order_count": len(wo_rows),
            "master_work_order_count": len(master_rows),
            "work_order_status": status_counts,
            "recent_work_orders": [
                {"work_order_code": row.get("work_order_code"), "status": row.get("status"), "planned_qty": row.get("planned_qty"), "planned_due": _iso(row.get("planned_due"))}
                for row in master_rows[:10]
            ],
        }

    async def _sum(self, table: str, column: str, where: str, params: Dict[str, Any]) -> float:
        if not self._has(table):
            return 0
        rows = await self._rows(f"SELECT COALESCE(SUM({column}), 0) AS total FROM {table} WHERE {where}", params)
        return _number(rows[0].get("total")) if rows else 0

    async def _materials(self, factory_id: str, **_: Any) -> Dict[str, Any]:
        bom_codes = {str(row.get("material_code")) for row in await self._rows(
            "SELECT material_code FROM bom_items WHERE factory_id = :fid AND material_code IS NOT NULL",
            {"fid": factory_id},
        )} if self._has("bom_items") else set()
        wo_codes = {str(row.get("material_code")) for row in await self._rows(
            """
            SELECT DISTINCT wom.material_code
            FROM work_order_materials wom
            JOIN work_orders wo ON wo.id = wom.work_order_id
            WHERE wo.factory_id = :fid AND wom.material_code IS NOT NULL
            """, {"fid": factory_id},
        )} if self._has("work_order_materials") and self._has("work_orders") else set()
        inv_codes = {str(row.get("material_code")) for row in await self._rows(
            "SELECT DISTINCT material_code FROM inventory WHERE factory_id = :fid AND material_code IS NOT NULL",
            {"fid": factory_id},
        )} if self._has("inventory") else set()
        txn_codes = {str(row.get("material_id")) for row in await self._rows(
            "SELECT DISTINCT material_id FROM inventory_transactions WHERE factory_id = :fid AND material_id IS NOT NULL",
            {"fid": factory_id},
        )} if self._has("inventory_transactions") else set()
        missing = [table for table in ("bom_items", "work_order_materials", "inventory", "inventory_transactions") if not self._has(table)]
        return {
            "data_status": "partial" if missing else "ready",
            "source": "bom_items + work_order_materials + inventory + inventory_transactions",
            "missing_sources": missing,
            "data_note": "controlled_material_count 是当前主数据/工单控制范围，不等于历史累计控制过的物料数。",
            "controlled_material_count": len(bom_codes | wo_codes | inv_codes),
            "bom_material_count": len(bom_codes),
            "work_order_material_count": len(wo_codes),
            "inventory_sku_count": len(inv_codes),
            "historical_transaction_material_count": len(txn_codes),
            "inventory_transaction_count": await self._count("inventory_transactions", "WHERE factory_id = :fid", {"fid": factory_id}),
        }

    async def _shortage(self, factory_id: str, *, work_order_code: Optional[str] = None, **_: Any) -> Dict[str, Any]:
        if not self._has("work_order_materials") or not self._has("work_orders"):
            return {
                "data_status": "missing",
                "source": "work_order_materials + work_orders",
                "missing_sources": [t for t in ("work_order_materials", "work_orders") if not self._has(t)],
                "data_note": "没有工单物料齐套来源，不能给出Shortage数量。",
                "affected_work_order_count": 0, "shortage_material_count": 0, "total_shortage_qty": 0, "items": [],
            }
        where = "wo.factory_id = :fid AND wo.status NOT IN ('completed', 'cancelled') AND COALESCE(wom.shortage_qty, 0) > 0"
        params: Dict[str, Any] = {"fid": factory_id}
        if work_order_code:
            where += " AND wo.work_order_code = :work_order_code"
            params["work_order_code"] = work_order_code
        rows = await self._rows(f"""
            SELECT wom.work_order_id, wo.work_order_code, wo.status, wom.material_code,
                   wom.material_name, wom.required_qty, wom.available_qty, wom.received_qty, wom.shortage_qty
            FROM work_order_materials wom
            JOIN work_orders wo ON wo.id = wom.work_order_id
            WHERE {where}
            ORDER BY wom.shortage_qty DESC, wo.planned_due
        """, params)
        grouped: Dict[str, Dict[str, Any]] = {}
        affected: Set[str] = set()
        for row in rows:
            code = str(row.get("material_code") or "unknown")
            item = grouped.setdefault(code, {
                "material_code": code,
                "material_name": row.get("material_name") or code,
                "shortage_qty": 0,
                "required_qty": 0,
                "available_qty": 0,
                "affected_work_orders": [],
            })
            item["shortage_qty"] += _number(row.get("shortage_qty"))
            item["required_qty"] += _number(row.get("required_qty"))
            item["available_qty"] += _number(row.get("available_qty"))
            if row.get("work_order_code") not in item["affected_work_orders"]:
                item["affected_work_orders"].append(row.get("work_order_code"))
            if row.get("work_order_code"):
                affected.add(str(row.get("work_order_code")))
        for item in grouped.values():
            for key in ("shortage_qty", "required_qty", "available_qty"):
                item[key] = round(item[key], 2)
        return {
            "data_status": "ready",
            "source": "work_order_materials.shortage_qty + work_orders",
            "missing_sources": [],
            "data_note": "当前结果是已落库的工单物料缺口；PO/在途覆盖量需看供应商数据。",
            "affected_work_order_count": len(affected),
            "shortage_material_count": len(grouped),
            "total_shortage_qty": round(sum(item["shortage_qty"] for item in grouped.values()), 2),
            "items": list(grouped.values()),
        }

    async def _inventory(self, factory_id: str, *, days: int = 180, material_keyword: Optional[str] = None, **_: Any) -> Dict[str, Any]:
        if not self._has("inventory"):
            return {"data_status": "missing", "source": "inventory", "missing_sources": ["inventory"], "data_note": "没有库存主表，不能回答库存现状或降库存。", "sku_count": 0, "items": []}
        where = "factory_id = :fid"
        params: Dict[str, Any] = {"fid": factory_id}
        if material_keyword:
            where += " AND (material_code ILIKE :kw OR COALESCE(material_name, '') ILIKE :kw)"
            params["kw"] = f"%{material_keyword}%"
        rows = await self._rows(f"""
            SELECT material_code, material_name, total_qty, available_qty, reserved_qty,
                   unit_cost, status, qualified_status, last_movement_at, created_at
            FROM inventory WHERE {where} ORDER BY material_code
        """, params)
        today = date.today()
        items: List[Dict[str, Any]] = []
        stagnant = 0
        total_value = 0.0
        for row in rows:
            movement = row.get("last_movement_at") or row.get("created_at")
            age = max(0, (today - _date(movement)).days) if _date(movement) else None
            is_stagnant = bool(_number(row.get("available_qty")) > 0 and age is not None and age >= days)
            stagnant += int(is_stagnant)
            if row.get("unit_cost") is not None:
                total_value += _number(row.get("total_qty")) * _number(row.get("unit_cost"))
            items.append({
                "material_code": row.get("material_code"), "material_name": row.get("material_name"),
                "total_qty": _number(row.get("total_qty")), "available_qty": _number(row.get("available_qty")),
                "reserved_qty": _number(row.get("reserved_qty")), "aging_days": age,
                "dead_stock": is_stagnant, "last_movement_at": _iso(row.get("last_movement_at")),
                "status": row.get("status"), "qualified_status": row.get("qualified_status"),
            })
        return {
            "data_status": "partial" if not self._has("inventory_transactions") else "ready",
            "source": "inventory + inventory_transactions",
            "missing_sources": ["inventory_transactions"] if not self._has("inventory_transactions") else [],
            "data_note": "没有库存流水时，库存数量可查，但无法证明历史消耗趋势和真实降库存效果。",
            "sku_count": len(rows), "total_qty": round(sum(item["total_qty"] for item in items), 2),
            "available_qty": round(sum(item["available_qty"] for item in items), 2),
            "reserved_qty": round(sum(item["reserved_qty"] for item in items), 2),
            "inventory_value": round(total_value, 2) if total_value else None,
            "stagnant_threshold_days": days, "stagnant_count": stagnant, "items": items[:50],
            "reduction_method": [
                "按已确认需求/BOM做净需求与预留，停止无需求补货",
                "优先复用跨产品共用BOM物料，再做仓间调拨/退供应商/报废审批",
                "用库存流水按周验证库存余额、消耗和呆滞变化",
            ],
        }

    DELIVERY_RISK_METHOD = (
        "只看 in_progress 且有 planned_due 的工单：按已完成量算出的实际速度推算剩余工期天数，"
        "预计完成晚于 planned_due 即计为交期风险；距交期不足 3 天记 high。"
        "交期智能体与本方法共用同一实现，口径不分叉。"
    )

    async def delivery_risk(self, factory_id: str, *, limit: int = 20) -> Dict[str, Any]:
        """前瞻交期风险（唯一实现）：控制塔、chatbot、交期智能体都取这里。"""
        await self._load_tables()
        if not self._has("work_orders"):
            return {
                "data_status": "missing",
                "risk_count": 0,
                "high_risk_count": 0,
                "items": [],
                "data_note": "没有 work_orders 表，不能判断交期风险。",
            }
        rows = await self._rows("""
            SELECT wo.work_order_code, wo.planned_qty, wo.completed_qty,
                   wo.planned_due, wo.priority,
                   CASE WHEN wo.completed_qty > 0 AND wo.actual_start IS NOT NULL
                        THEN (wo.planned_qty - wo.completed_qty) *
                             EXTRACT(EPOCH FROM (NOW() - wo.actual_start)) / wo.completed_qty / 86400.0
                        ELSE NULL END as estimated_remaining_days
            FROM work_orders wo
            WHERE wo.factory_id = :fid AND wo.status = 'in_progress'
              AND wo.planned_due IS NOT NULL
            ORDER BY wo.planned_due
        """, {"fid": factory_id})

        items: List[Dict[str, Any]] = []
        for row in rows:
            remaining_days = _number(row.get("estimated_remaining_days"))
            due = _date(row.get("planned_due"))
            if remaining_days <= 0 or due is None:
                continue
            days_to_due = (due - date.today()).total_seconds() / 86400.0
            if remaining_days > days_to_due and days_to_due > 0:
                items.append({
                    "work_order_code": row.get("work_order_code"),
                    "severity": "high" if days_to_due < 3 else "medium",
                    "days_to_due": round(days_to_due, 1),
                    "estimated_remaining_days": round(remaining_days, 1),
                    "planned_due": _iso(due),
                    "priority": row.get("priority"),
                })

        high_count = len([item for item in items if item["severity"] == "high"])
        return {
            "data_status": "ready",
            "risk_count": len(items),
            "high_risk_count": high_count,
            "items": items[:max(1, min(int(limit or 20), 100))],
            "method": self.DELIVERY_RISK_METHOD,
        }

    async def _otd(self, factory_id: str, *, work_order_code: Optional[str] = None, **_: Any) -> Dict[str, Any]:
        if not self._has("work_orders"):
            return {"data_status": "missing", "source": "work_orders", "missing_sources": ["work_orders"], "data_note": "没有交付执行来源，不能计算OTD。", "otd_pct": None}
        where = "factory_id = :fid AND planned_due IS NOT NULL"
        params: Dict[str, Any] = {"fid": factory_id}
        if work_order_code:
            where += " AND work_order_code = :work_order_code"
            params["work_order_code"] = work_order_code
        work_order_rows = await self._rows(f"""
            SELECT work_order_code, status, planned_due, actual_complete, planned_qty, completed_qty
            FROM work_orders WHERE {where}
        """, params)
        sales_order_count = await self._count("sales_orders", "WHERE factory_id = :fid", {"fid": factory_id})
        has_ship_date_source = self._has_column("sales_orders", "actual_ship_date")
        has_sales_order_evidence = self._has("sales_orders") and sales_order_count > 0 and has_ship_date_source

        # Once customer orders exist, OTD must use the customer delivery date
        # and actual shipment date.  Work-order completion remains the explicit
        # fallback for installations that have not loaded sales-order history.
        if has_sales_order_evidence:
            sales_where = "factory_id = :fid AND delivery_date IS NOT NULL AND status <> 'cancelled'"
            sales_params: Dict[str, Any] = {"fid": factory_id}
            if work_order_code:
                sales_where += """
                    AND EXISTS (
                        SELECT 1 FROM work_orders linked_wo
                        WHERE linked_wo.sales_order_id = sales_orders.id
                          AND linked_wo.work_order_code = :work_order_code
                    )
                """
                sales_params["work_order_code"] = work_order_code
            sales_rows = await self._rows(f"""
                SELECT order_code, status, delivery_date, actual_ship_date, quantity, shipped_qty
                FROM sales_orders
                WHERE {sales_where}
                ORDER BY delivery_date
            """, sales_params)
            completed = [
                row for row in sales_rows
                if row.get("actual_ship_date") is not None or row.get("status") == "completed"
            ]
            on_time = [
                row for row in completed
                if _date(row.get("actual_ship_date"))
                and _date(row.get("delivery_date"))
                and _date(row.get("actual_ship_date")) <= _date(row.get("delivery_date"))
            ]
            today = date.today()
            open_overdue = [
                row for row in sales_rows
                if row.get("status") not in ("completed", "cancelled")
                and row.get("delivery_date")
                and _date(row.get("delivery_date")) < today
            ]
            due_order_count = len(sales_rows)
            overdue_orders = [
                {"order_code": row.get("order_code"), "delivery_date": _iso(row.get("delivery_date")), "status": row.get("status")}
                for row in open_overdue[:20]
            ]
        else:
            completed = [row for row in work_order_rows if row.get("actual_complete") is not None or row.get("status") == "completed"]
            on_time = [
                row for row in completed
                if _date(row.get("actual_complete"))
                and _date(row.get("planned_due"))
                and _date(row.get("actual_complete")) <= _date(row.get("planned_due"))
            ]
            today = datetime.utcnow()
            open_overdue = [
                row for row in work_order_rows
                if row.get("status") not in ("completed", "cancelled")
                and row.get("planned_due")
                and row.get("planned_due") < today
            ]
            due_order_count = len(work_order_rows)
            overdue_orders = [
                {"work_order_code": row.get("work_order_code"), "planned_due": _iso(row.get("planned_due")), "status": row.get("status")}
                for row in open_overdue[:20]
            ]
        # 历史达成率之外，给出同一个前瞻口径（与交期智能体共用实现）
        risk = await self.delivery_risk(factory_id)
        result = {
            "data_status": "ready" if has_sales_order_evidence else "partial",
            "source": "sales_orders.actual_ship_date + sales_orders.delivery_date" if has_sales_order_evidence else "work_orders.actual_complete + work_orders.planned_due",
            "missing_sources": (
                ["sales_orders"] if not self._has("sales_orders")
                else ["sales_orders.actual_ship_date"] if not has_ship_date_source
                else ["sales_orders:no_rows"] if sales_order_count == 0 else []
            ),
            "data_note": "有销售订单时按客户交期/实际出货计算；没有销售订单时才采用工单完成口径。无已完工样本时OTD为null，不显示0%。",
            "otd_scope": "sales_order_linked_work_order" if has_sales_order_evidence else "work_order_fallback",
            "sales_order_count": sales_order_count,
            "due_order_count": due_order_count, "completed_order_count": len(completed), "on_time_order_count": len(on_time),
            "otd_pct": round(len(on_time) / len(completed) * 100, 1) if completed else None,
            "open_overdue_count": len(open_overdue),
            "at_risk_in_progress_count": risk["risk_count"],
            "at_risk_high_count": risk["high_risk_count"],
            "at_risk_orders": risk["items"],
            "at_risk_method": risk["method"],
            "overdue_orders": overdue_orders,
            "guarantee_controls": [
                "订单进入MPS前做ATP：物料齐套、产能可行、RDD可行三项同时核对",
                "每日按计划完工/实际完工重算风险，超期订单触发升级",
                "任何插单、缺料、ECN或供应延迟都必须触发影响评估和APS重排",
            ],
        }
        return result

    async def _capacity(self, factory_id: str, *, work_order_code: Optional[str] = None, **_: Any) -> Dict[str, Any]:
        missing = [table for table in ("stations", "work_orders", "routings") if not self._has(table)]
        if missing:
            return {"data_status": "missing", "source": "stations + work_orders + routings + aps_schedule_tasks", "missing_sources": missing, "data_note": "没有工位/工艺/工单完整链路，不能做负荷平衡。", "bottlenecks": [], "stations": []}
        stations = await self._rows("""
            SELECT id, station_code, station_name, capacity_per_hour
            FROM stations WHERE factory_id = :fid AND COALESCE(status, 'active') = 'active'
        """, {"fid": factory_id})
        capacity_rows = await self._rows("""
            SELECT station_id, available_hours_per_day, efficiency_rate,
                   setup_time_minutes, max_concurrent_orders, source
            FROM station_capacity
            WHERE factory_id = :fid AND is_active = TRUE
        """, {"fid": factory_id}) if self._has("station_capacity") else []
        calendar_count = await self._count("aps_work_calendars", "WHERE factory_id = :fid", {"fid": factory_id})
        capacity_map = {str(row.get("station_id")): row for row in capacity_rows}
        route_rows = await self._rows("SELECT product_id, steps FROM routings WHERE factory_id = :fid AND is_active = TRUE", {"fid": factory_id})
        route_map = {str(row.get("product_id")): _steps(row.get("steps")) for row in route_rows}
        wo_where = "factory_id = :fid AND status IN ('pending', 'released', 'in_progress') AND COALESCE(wo_type, 'master') = 'master'"
        wo_params: Dict[str, Any] = {"fid": factory_id}
        if work_order_code:
            wo_where += " AND work_order_code = :work_order_code"
            wo_params["work_order_code"] = work_order_code
        wo_rows = await self._rows(f"""
            SELECT product_id, assigned_station_id, planned_qty, planned_due, status
            FROM work_orders WHERE {wo_where}
        """, wo_params)
        aps_where = "s.factory_id = :fid AND s.status IN ('draft', 'confirmed', 'released', 'active')"
        aps_params: Dict[str, Any] = {"fid": factory_id}
        if work_order_code:
            aps_where += " AND wo.work_order_code = :work_order_code"
            aps_params["work_order_code"] = work_order_code
        aps_rows = await self._rows(f"""
            SELECT t.station_id, t.planned_start, t.planned_end, t.work_order_id
            FROM aps_schedule_tasks t
            JOIN aps_schedules s ON s.id = t.schedule_id
            JOIN work_orders wo ON wo.id = t.work_order_id
            WHERE {aps_where}
        """, aps_params) if self._has("aps_schedule_tasks") and self._has("aps_schedules") else []
        aps_hours = defaultdict(float)
        for row in aps_rows:
            if row.get("planned_start") and row.get("planned_end"):
                aps_hours[str(row.get("station_id"))] += max(0, (row["planned_end"] - row["planned_start"]).total_seconds() / 3600)
        required = defaultdict(float)
        for wo in wo_rows:
            steps = route_map.get(str(wo.get("product_id")), [])
            for step in steps:
                ref = str(step.get("station_id") or step.get("station") or step.get("work_center") or "")
                hours = _step_hours(step)
                if ref and hours is not None:
                    required[ref] += _number(wo.get("planned_qty")) * hours
        station_items = []
        horizon_end = max((_date(row.get("planned_due")) for row in wo_rows if _date(row.get("planned_due"))), default=date.today() + timedelta(days=7))
        workdays = max(1, (horizon_end - date.today()).days + 1)
        for station in stations:
            identifiers = {str(station.get("id")), str(station.get("station_code"))}
            required_hours = sum(required[key] for key in identifiers)
            loaded_hours = aps_hours.get(str(station.get("id")), 0) + aps_hours.get(str(station.get("station_code")), 0)
            configured = capacity_map.get(str(station.get("station_code"))) or capacity_map.get(str(station.get("id"))) or {}
            configured_hours_per_day = _number(configured.get("available_hours_per_day"))
            available_hours = (configured_hours_per_day or _number(station.get("capacity_per_hour")) * 8) * workdays
            load_hours = loaded_hours if aps_rows else required_hours
            utilization = load_hours / available_hours * 100 if available_hours else None
            station_items.append({
                "station_code": station.get("station_code"), "station_name": station.get("station_name"),
                "capacity_per_hour": _number(station.get("capacity_per_hour")), "horizon_workdays": workdays,
                "configured_hours_per_day": round(configured_hours_per_day, 2) if configured_hours_per_day else None,
                "capacity_config_source": configured.get("source") or "station_master_fallback",
                "available_hours": round(available_hours, 2), "required_hours": round(required_hours, 2),
                "aps_loaded_hours": round(loaded_hours, 2), "load_hours_used": round(load_hours, 2),
                "utilization_pct": round(utilization, 1) if utilization is not None else None,
                "status": "overloaded" if utilization is not None and utilization > 100 else "warning" if utilization is not None and utilization >= 90 else "available",
            })
        bottlenecks = sorted(station_items, key=lambda item: item.get("utilization_pct") or 0, reverse=True)[:3]
        return {
            "data_status": "ready" if aps_rows else "partial",
            "source": "stations + station_capacity + routings + work_orders + aps_schedule_tasks",
            "missing_sources": ([] if aps_rows else ["aps_schedule_tasks_or_no_active_APS_tasks"])
            + ([] if capacity_rows else ["station_capacity:no_rows"])
            + ([] if calendar_count else ["aps_work_calendars:no_rows"]),
            "data_note": "有APS任务时使用实际任务负荷；没有APS任务时使用工艺UHN与已配置工位产能做理论评估，不代表已完成实际排程。未配置工作日历时，APS只使用兼容默认班次，不能作为正式承诺依据。",
            "load_source": "aps_schedule_tasks" if aps_rows else "routing_UHN_and_station_capacity" if capacity_rows else "routing_UHN_and_station_CPH",
            "bottlenecks": bottlenecks, "stations": station_items,
            "balance_method": [
                "按瓶颈工位利用率从高到低排序",
                "先重排未开工工单和换型顺序，再考虑班次、外协或分批交付",
                "重排后必须复核物料齐套、交期和工序无重叠",
            ],
        }

    async def _rush(self, factory_id: str, *, rush_quantity: Optional[int] = None, rush_due_date: Optional[str] = None, **_: Any) -> Dict[str, Any]:
        approval_count = await self._count("rush_order_approvals", "WHERE factory_id = :fid", {"fid": factory_id})
        approval_rows = await self._rows("""
            SELECT approval_code, product_id, quantity, due_date, status, affected_orders,
                   max_delay_days, process_hours, target_schedule_id, created_at
            FROM rush_order_approvals WHERE factory_id = :fid ORDER BY created_at DESC LIMIT 20
        """, {"fid": factory_id}) if self._has("rush_order_approvals") else []
        simulation: Dict[str, Any] = {}
        if rush_quantity and rush_quantity > 0:
            process_hours = rush_quantity * 0.5 / 0.85
            due = _date(rush_due_date)
            simulation = {
                "quantity": int(rush_quantity), "estimated_process_hours": round(process_hours, 1),
                "due_date": _iso(due), "due_feasible": (datetime.utcnow() + timedelta(hours=process_hours)).date() <= due if due else None,
                "note": "这是保守沙盘，不会修改APS；正式插单仍需调用影响评估并审批。",
            }
        return {
            "data_status": "ready" if self._has("rush_order_approvals") else "missing",
            "source": "rush_order_approvals + rush_order_approval_logs + APS重排接口",
            "missing_sources": ["rush_order_approvals"] if not self._has("rush_order_approvals") else [],
            "data_note": "插单历史以审批单和执行状态为准；没有记录时不代表没有线下插单，只代表系统无审计记录。",
            "approval_count": approval_count,
            "status_counts": dict(Counter(str(row.get("status") or "unknown") for row in approval_rows)),
            "executed_count": sum(1 for row in approval_rows if row.get("status") == "executed"),
            "recent_approvals": [{"approval_code": row.get("approval_code"), "product_id": row.get("product_id"), "quantity": row.get("quantity"), "status": row.get("status"), "affected_orders": row.get("affected_orders"), "target_schedule_id": row.get("target_schedule_id")} for row in approval_rows],
            "simulation": simulation,
            "process": [
                "1) 先核对急单BOM、库存齐套、产能和交期",
                "2) 用只读影响评估计算受影响订单和最大延迟",
                "3) 生成插单审批单；审批通过后才允许重排",
                "4) APS生成新版本，保留原版本、差异和审批日志",
                "5) 重排后重新核对OTD风险并通知受影响责任人",
            ],
        }

    async def _engineering_change(self, factory_id: str, **_: Any) -> Dict[str, Any]:
        ecn_rows = await self._rows("""
            SELECT ecn_code, title, change_type, affected_product, status,
                   affected_wo_count, propagated_at, created_at
            FROM engineering_changes WHERE factory_id = :fid ORDER BY created_at DESC LIMIT 20
        """, {"fid": factory_id}) if self._has("engineering_changes") else []
        bom_rows = await self._rows("""
            SELECT product_id, bom_version, COUNT(*) AS line_count
            FROM bom_items WHERE factory_id = :fid GROUP BY product_id, bom_version
            ORDER BY product_id, bom_version
        """, {"fid": factory_id}) if self._has("bom_items") else []
        marked_count = 0
        if self._has("work_orders"):
            marked_count = len(await self._rows("""
                SELECT id FROM work_orders WHERE factory_id = :fid AND COALESCE(remark, '') ILIKE '%[ECN:%'
            """, {"fid": factory_id}))
        missing = [table for table in ("engineering_changes", "bom_items") if not self._has(table)]
        return {
            "data_status": "missing" if "engineering_changes" in missing else "partial" if missing else "ready",
            "source": "engineering_changes + bom_items + work_orders.remark",
            "missing_sources": missing,
            "data_note": "BOM表只有当前版本快照时，不能把版本差异或生效传播历史当作已完成。",
            "ecn_count": await self._count("engineering_changes", "WHERE factory_id = :fid", {"fid": factory_id}),
            "ecn_status_counts": dict(Counter(str(row.get("status") or "unknown") for row in ecn_rows)),
            "recent_ecns": [{"ecn_code": row.get("ecn_code"), "title": row.get("title"), "change_type": row.get("change_type"), "affected_product": row.get("affected_product"), "status": row.get("status"), "affected_wo_count": row.get("affected_wo_count"), "propagated_at": _iso(row.get("propagated_at"))} for row in ecn_rows],
            "bom_product_version_count": len({(row.get("product_id"), row.get("bom_version")) for row in bom_rows}),
            "bom_versions": [{"product_id": row.get("product_id"), "bom_version": row.get("bom_version"), "line_count": row.get("line_count")} for row in bom_rows],
            "ecn_marked_work_order_count": marked_count,
            "process": [
                "ECN评审：确认变更类型、受影响产品/BOM/工艺和库存风险",
                "批准并生效新BOM/工艺版本，冻结旧版本的适用范围",
                "重新运行MRP，核对旧料/替代料/在途PO",
                "对未完工工单做影响传播并触发APS重排，保留版本与审计记录",
            ],
        }

    async def _supplier_delay(self, factory_id: str, **_: Any) -> Dict[str, Any]:
        if not self._has("purchase_orders"):
            return {"data_status": "missing", "source": "purchase_orders + suppliers", "missing_sources": ["purchase_orders", "suppliers"], "data_note": "采购订单表不存在，不能判断供应商延迟。", "po_count": 0, "overdue_count": 0, "items": []}
        rows = await self._rows("""
            SELECT po_code, supplier_name, supplier_id, material_code, material_name,
                   qty, expected_date, actual_date, order_date, status
            FROM purchase_orders WHERE factory_id = :fid ORDER BY expected_date NULLS LAST
        """, {"fid": factory_id})
        overdue: List[Dict[str, Any]] = []
        today = date.today()
        for row in rows:
            expected = _date(row.get("expected_date")); actual = _date(row.get("actual_date"))
            status = str(row.get("status") or "").lower()
            delay_days = 0
            if expected and actual:
                delay_days = max(0, (actual - expected).days)
            elif expected and expected < today and status not in ("received", "closed", "cancelled"):
                delay_days = (today - expected).days
            if delay_days > 0:
                overdue.append({"po_code": row.get("po_code"), "supplier_name": row.get("supplier_name"), "material_code": row.get("material_code"), "qty": _number(row.get("qty")), "expected_date": _iso(expected), "actual_date": _iso(actual), "status": row.get("status"), "delay_days": delay_days})
        return {
            "data_status": "ready" if self._has("suppliers") else "partial",
            "source": "purchase_orders + suppliers",
            "missing_sources": ["suppliers"] if not self._has("suppliers") else [],
            "data_note": "以PO expected_date/actual_date/status计算延迟；没有PO不代表供应商没有延迟，只代表系统没有证据。",
            "po_count": len(rows), "open_po_count": sum(1 for row in rows if str(row.get("status") or "").lower() not in ("received", "closed", "cancelled")),
            "overdue_count": len(overdue), "max_delay_days": max((row["delay_days"] for row in overdue), default=0),
            "affected_material_count": len({str(row.get("material_code")) for row in overdue if row.get("material_code")}),
            "items": overdue[:50],
            "process": [
                "按逾期天数和受影响工单优先级升级跟催",
                "确认供应商新ETA并更新PO，不能只在备注里口头承诺",
                "同步PMC重新评审Shortage、ATP/OTD和替代供应源",
                "必要时切换合格替代供应商、空运或调整排产，并保留审批原因",
            ],
        }


__all__ = ["PmcControlTowerService", "SCOPES"]
