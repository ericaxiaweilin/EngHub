"""库存专业健康度汇总。

这个服务只做一件事：把 wms_architecture 里已有但没人调用的分析执行器编排成
一次可审计的读数，并把"算不出来"的原因显式说出来。业务口径仍然只有一份 ——
不在这里重复实现 ABC、呆滞、效期或补货判定。
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wms_architecture.executors.abc_analysis_executor import AbcAnalysisExecutor
from api.services.wms_architecture.executors.batch_expiry_executor import BatchExpiryExecutor
from api.services.wms_architecture.executors.dead_stock_executor import DeadStockExecutor
from api.services.wms_architecture.executors.inventory_alert_executor import InventoryAlertExecutor
from api.services.wms_architecture.executors.replenish_executor import ReplenishExecutor
from api.services.wms_architecture.movements import INBOUND_TYPES, OUTBOUND_TYPES


def _json_safe(value: Any) -> Any:
    """把 date/datetime/Decimal 等在落库前统一成 JSON 可序列化的标量。

    工具结果会原样写入 chat_events 的 JSONB 列；执行器返回的行字典里带着
    date 对象，直接落库会抛 TypeError 并连带把整轮事务打回滚（500）。
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((str(k), _json_safe(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


class WmsInventoryHealthService:
    """只读：不写库存、不改阈值、不生成建议之外的动作。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _coverage(self, factory_id: str) -> Dict[str, Any]:
        inv = (await self.db.execute(text("""
            SELECT COUNT(*) AS inventory_rows,
                   COUNT(DISTINCT material_id) AS sku_count,
                   COUNT(*) FILTER (WHERE COALESCE(available_qty, 0) > 0) AS rows_with_stock,
                   COUNT(*) FILTER (WHERE COALESCE(unit_cost, 0) > 0) AS rows_with_cost,
                   COUNT(*) FILTER (WHERE COALESCE(safety_stock, 0) > 0) AS rows_with_safety_stock,
                   COUNT(*) FILTER (WHERE COALESCE(reorder_point, 0) > 0) AS rows_with_reorder_point,
                   COUNT(*) FILTER (WHERE expiry_date IS NOT NULL) AS rows_with_expiry,
                   COUNT(*) FILTER (WHERE location_id IS NOT NULL) AS rows_with_location_id,
                   COUNT(*) FILTER (WHERE last_movement_at IS NOT NULL) AS rows_with_last_movement
            FROM inventory WHERE factory_id = :fid
        """), {"fid": factory_id})).mappings().first()

        txn = (await self.db.execute(text("""
            SELECT COUNT(*) AS total_rows,
                   COUNT(DISTINCT material_id) AS touched_materials,
                   MIN(created_at)::date AS first_day,
                   MAX(created_at)::date AS last_day,
                   COUNT(*) FILTER (WHERE transaction_type = ANY(:out_types)) AS outbound_rows,
                   COUNT(*) FILTER (WHERE transaction_type = ANY(:in_types)) AS inbound_rows
            FROM inventory_transactions WHERE factory_id = :fid
        """), {
            "fid": factory_id,
            "out_types": list(OUTBOUND_TYPES),
            "in_types": list(INBOUND_TYPES),
        })).mappings().first()

        loc = (await self.db.execute(text("""
            SELECT COUNT(*) AS location_rows,
                   COUNT(*) FILTER (WHERE l.status = 'active') AS active_location_rows,
                   COUNT(*) FILTER (WHERE COALESCE(l.capacity, 0) > 0) AS rows_with_capacity
            FROM locations l
            JOIN warehouses w ON w.id = l.warehouse_id
            WHERE w.factory_id = :fid
        """), {"fid": factory_id})).mappings().first()

        threshold_rows = (await self.db.execute(text("""
            SELECT COUNT(*) AS rows FROM replenishment_thresholds WHERE factory_id = :fid
        """), {"fid": factory_id})).mappings().first()

        return {
            "inventory": dict(inv or {}),
            "movements": dict(txn or {}),
            "locations": dict(loc or {}),
            "replenishment_threshold_rows": (threshold_rows or {}).get("rows", 0),
            "movement_vocabulary": {
                "counted_as_consumption": list(OUTBOUND_TYPES),
                "counted_as_receipt": list(INBOUND_TYPES),
                "note": "流水写入方历史上用了多套词汇（服务写 outbound/inbound，虚拟工厂写 production_out/scenario_hold），读取侧按词表匹配，否则消耗会被静默算成 0。",
            },
        }

    async def _run(self, label: str, executor, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            result = await executor.execute(self.db, self.factory_id, context)
        except Exception as exc:  # noqa: BLE001
            await self.db.rollback()
            return {"ok": False, "error_type": type(exc).__name__,
                    "error": str(exc)[:200]}
        if isinstance(result, dict) and result.get("error"):
            return {"ok": False, "error": result.get("message") or result}
        return {"ok": True, "result": result}

    async def collect(
        self,
        factory_id: str,
        *,
        dead_stock_days: int = 60,
        expiry_warn_days: int = 30,
        turnover_days: int = 90,
    ) -> Dict[str, Any]:
        self.factory_id = factory_id
        coverage = await self._coverage(factory_id)

        abc = AbcAnalysisExecutor()
        alerts = InventoryAlertExecutor()
        analyses = {
            "abc_classification": await self._run("abc", abc, {"operation": "analyze"}),
            "turnover": await self._run("turnover", abc, {"operation": "get_turnover",
                                                          "period_days": turnover_days}),
            "valuation": await self._run("cost", abc, {"operation": "get_cost"}),
            "location_utilization": await self._run("util", abc, {"operation": "get_utilization"}),
            "dead_stock": await self._run("dead", DeadStockExecutor(),
                                          {"operation": "check", "days_threshold": dead_stock_days}),
            "batch_expiry": await self._run("expiry", BatchExpiryExecutor(),
                                            {"operation": "check_expiry",
                                             "days_threshold": expiry_warn_days}),
            "low_stock": await self._run("low", alerts, {"operation": "get_low_stock"}),
            "overstock": await self._run("over", alerts, {"operation": "get_overstock"}),
            "stagnant": await self._run("stagnant", alerts, {"operation": "get_stagnant"}),
            "replenishment": await self._run("replenish", ReplenishExecutor(),
                                             {"operation": "suggestions"}),
        }

        inv = coverage["inventory"]
        txn = coverage["movements"]
        loc = coverage["locations"]
        gaps: List[Dict[str, Any]] = []
        if not txn.get("inbound_rows"):
            gaps.append({
                "item": "入库侧流水",
                "reason": "inventory_transactions 里没有收货/入库类型记录，因此周转率只反映领料出库，不等于完整进销存周转。",
                "needed": "收货单/入库回执落到 inventory_transactions（当前只有领料与调拨）。",
            })
        if not inv.get("rows_with_expiry"):
            gaps.append({
                "item": "效期与先进先出",
                "reason": f"inventory.expiry_date 有值 {inv.get('rows_with_expiry') or 0}/{inv.get('inventory_rows')} 行，效期分析没有可判定的批次。",
                "needed": "收货时落 expiry_date（或 production_date + shelf_life_days）。",
            })
        if not loc.get("location_rows") or not inv.get("rows_with_location_id"):
            gaps.append({
                "item": "库位容量与满载率",
                "reason": (
                    f"本厂 locations {loc.get('location_rows') or 0} 行、"
                    f"inventory.location_id 有值 {inv.get('rows_with_location_id') or 0}/{inv.get('inventory_rows')} 行 —— 库存没有挂到库位，容量利用率不可计算。"
                ),
                "needed": "库位主数据入库并把库存行关联到 location_id。",
            })
        if not inv.get("rows_with_cost"):
            gaps.append({
                "item": "库存金额",
                "reason": f"inventory.unit_cost>0 仅 {inv.get('rows_with_cost') or 0}/{inv.get('inventory_rows')} 行，金额口径只覆盖这一部分，其余只报数量。",
                "needed": "采购/入库单价落库。",
            })
        if not coverage["replenishment_threshold_rows"]:
            gaps.append({
                "item": "过量(max_level)阈值",
                "reason": "replenishment_thresholds 为 0 行，过量判定退回使用 inventory 行上的再订货点+一次补货量。",
                "needed": "为物料维护 min/max 水位，或确认以行级 reorder 字段为唯一口径。",
            })

        def _items(key: str) -> int:
            entry = analyses.get(key) or {}
            res = entry.get("result") or {}
            for name in ("total_items", "total", "count"):
                if isinstance(res.get(name), int):
                    return res[name]
            for name in ("items", "suggestions", "locations", "zones"):
                if isinstance(res.get(name), list):
                    return len(res[name])
            return 0

        return _json_safe({
            "type": "wms_inventory_health",
            "factory_id": factory_id,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "thresholds": {
                "dead_stock_days": dead_stock_days,
                "expiry_warn_days": expiry_warn_days,
                "turnover_days": turnover_days,
            },
            "headline": {
                "sku_count": inv.get("sku_count"),
                "inventory_rows": inv.get("inventory_rows"),
                "movements_total": txn.get("total_rows"),
                "movements_first_day": txn.get("first_day"),
                "movements_last_day": txn.get("last_day"),
                "low_stock_items": _items("low_stock"),
                "dead_stock_items": _items("dead_stock"),
                "overstock_items": _items("overstock"),
                "stagnant_items": _items("stagnant"),
                "replenishment_suggestions": _items("replenishment"),
                "expiry_warning_items": _items("batch_expiry"),
            },
            "coverage": coverage,
            "analyses": analyses,
            "not_computable": gaps,
            "policy": "只读汇总；不修改库存、阈值或工单。任一分析器口径以 wms_architecture/executors 为唯一实现。",
        })


__all__ = ["WmsInventoryHealthService"]
