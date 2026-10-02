"""Resilient composition of the production intelligence capabilities.

This module intentionally depends on the current Chatbot, PMC and alerting
contracts instead of restoring the retired AI/Search/Expert modules.  Each
component is probed independently so an optional dependency cannot turn an
otherwise useful health or operations overview into a 500 response.
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, Optional, Tuple

from .models import (
    IntelligenceHealth,
    IntelligenceOverview,
    IntelligenceSignal,
    IntelligenceSubsystem,
)

_logger = logging.getLogger("enghub.intelligence")

_ComponentResult = Tuple[IntelligenceSubsystem, Dict[str, Any]]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


class ManufacturingIntelligenceService:
    """Combines existing runtime services into one read-only factory view."""

    def __init__(
        self,
        *,
        chat_status: Optional[Callable[[], Awaitable[Dict[str, Any]]]] = None,
        pmc_collect: Optional[Callable[[Any, str], Awaitable[Dict[str, Any]]]] = None,
        alert_summary: Optional[Callable[[Any, str], Awaitable[Dict[str, Any]]]] = None,
        plugin_manifests: Optional[Callable[[], Iterable[Dict[str, Any]]]] = None,
        harness_snapshot: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        self._chat_status = chat_status or self._default_chat_status
        self._pmc_collect = pmc_collect or self._default_pmc_collect
        self._alert_summary = alert_summary or self._default_alert_summary
        self._plugin_manifests = plugin_manifests or self._default_plugin_manifests
        self._harness_snapshot = harness_snapshot or self._default_harness_snapshot

    async def build_overview(self, db: Any, factory_id: str) -> IntelligenceOverview:
        """Return an operations view without exposing model-stack internals."""
        chat, _ = await self._probe(
            "chatbot_harness",
            ["model routing", "tool execution", "thread/turn lifecycle", "goal tracking"],
            self._chat_component,
        )
        harness, _ = await self._probe(
            "harness_runtime",
            ["plugin composition", "event replay", "cross-worker turn control"],
            self._harness_component,
        )
        pmc, pmc_payload = await self._probe(
            "pmc_control_tower",
            ["orders", "materials", "shortage", "inventory", "OTD", "capacity", "EC/BOM", "supplier delay"],
            lambda: self._pmc_component(db, factory_id),
        )
        alerts, alert_payload = await self._probe(
            "alert_intelligence",
            ["pending alert aggregation", "AI review", "patrol evidence"],
            lambda: self._alert_component(db, factory_id),
        )
        simulation, _ = await self._probe(
            "sim_erp",
            ["physical simulation", "compliance plugins", "audit trail"],
            self._simulation_component,
        )
        subsystems = [chat, harness, pmc, alerts, simulation]
        status = "degraded" if any(item.status == "degraded" for item in subsystems) else "healthy"
        return IntelligenceOverview(
            factory_id=factory_id,
            status=status,
            generated_at=datetime.now(timezone.utc),
            subsystems=subsystems,
            signals=self._build_signals(pmc_payload, alert_payload),
        )

    async def build_health(self, db: Any, factory_id: str) -> IntelligenceHealth:
        overview = await self.build_overview(db, factory_id)
        return IntelligenceHealth(
            factory_id=overview.factory_id,
            status=overview.status,
            checked_at=overview.generated_at,
            subsystems=overview.subsystems,
        )

    async def _probe(
        self,
        name: str,
        capabilities: list[str],
        operation: Callable[[], Any],
    ) -> _ComponentResult:
        try:
            payload = operation()
            if inspect.isawaitable(payload):
                payload = await payload
            raw_payload = dict(payload or {})
            status = str(raw_payload.get("_status", "healthy"))
            # Underscore keys are internal evidence used to derive signals;
            # never return raw control-tower rows through this summary API.
            details = {
                key: value for key, value in raw_payload.items()
                if not str(key).startswith("_")
            }
            return IntelligenceSubsystem(
                name=name,
                status=status if status in {"healthy", "degraded"} else "degraded",
                capabilities=capabilities,
                details=details,
            ), raw_payload
        except Exception as exc:  # noqa: BLE001 - component isolation is intentional
            _logger.warning("intelligence component degraded: %s", name, exc_info=True)
            return IntelligenceSubsystem(
                name=name,
                status="degraded",
                capabilities=capabilities,
                details={"reason": type(exc).__name__},
            ), {}

    async def _chat_component(self) -> Dict[str, Any]:
        snapshot = await self._chat_status()
        reachable = bool(snapshot.get("reachable"))
        return {
            "_status": "healthy" if reachable else "degraded",
            "configured": bool(snapshot.get("configured")),
            "reachable": reachable,
            "task_id": snapshot.get("model"),
            "detail": snapshot.get("detail"),
            "warmup": dict(snapshot.get("warmup") or {}),
        }

    async def _harness_component(self) -> Dict[str, Any]:
        snapshot = self._harness_snapshot()
        return {
            "version": snapshot.get("version"),
            "plugins": len(snapshot.get("plugins") or []),
            "profiles": len(snapshot.get("profiles") or []),
            "capabilities": len(snapshot.get("capabilities") or []),
        }

    async def _pmc_component(self, db: Any, factory_id: str) -> Dict[str, Any]:
        collected = await self._pmc_collect(db, factory_id)
        facts = dict(collected.get("facts") or {})
        quality = list(collected.get("data_quality") or [])
        status_counts: Dict[str, int] = {}
        for item in quality:
            key = str(item.get("status") or "unknown")
            status_counts[key] = status_counts.get(key, 0) + 1
        return {
            "data_quality": status_counts,
            "available_facts": sorted(facts),
            "recommended_actions": list(collected.get("actions") or [])[:8],
            "_facts": facts,
            "_quality": quality,
        }

    async def _alert_component(self, db: Any, factory_id: str) -> Dict[str, Any]:
        summary = await self._alert_summary(db, factory_id)
        return {
            "total_pending": int(summary.get("total_pending") or 0),
            "by_source": dict(summary.get("by_source") or {}),
            "by_severity": dict(summary.get("by_severity") or {}),
            "_summary": summary,
        }

    async def _simulation_component(self) -> Dict[str, Any]:
        manifests = list(self._plugin_manifests())
        return {
            "plugin_count": len(manifests),
            "plugins": [str(item.get("plugin_name")) for item in manifests],
        }

    def _build_signals(
        self,
        pmc_payload: Dict[str, Any],
        alert_payload: Dict[str, Any],
    ) -> list[IntelligenceSignal]:
        facts = pmc_payload.get("_facts") or {}
        quality = pmc_payload.get("_quality") or []
        signals: list[IntelligenceSignal] = []

        missing = [item.get("key") for item in quality if item.get("status") == "missing"]
        if missing:
            signals.append(IntelligenceSignal(
                code="pmc_data_gap",
                severity="medium",
                message=f"PMC 有 {len(missing)} 个业务域缺少可审计数据。",
                action="补齐缺失来源后重新生成控制塔结论；不要用其他模块记录替代缺失事实。",
                evidence={"missing_domains": missing},
            ))

        shortage = facts.get("shortage") or {}
        shortage_qty = _number(shortage.get("total_shortage_qty"))
        if shortage_qty > 0:
            signals.append(IntelligenceSignal(
                code="shortage_risk",
                severity="high",
                message=f"检测到缺料 {shortage_qty:g}，影响 {int(_number(shortage.get('affected_work_order_count')))} 张工单。",
                action="锁定缺口物料和受影响工单，核实 PO/ETA 或替代料验证后再放行。",
                evidence={
                    "shortage_qty": shortage_qty,
                    "affected_work_order_count": int(_number(shortage.get("affected_work_order_count"))),
                },
            ))

        capacity = facts.get("capacity") or {}
        bottlenecks = [item for item in (capacity.get("bottlenecks") or []) if item.get("status") == "overloaded"]
        if bottlenecks:
            signals.append(IntelligenceSignal(
                code="capacity_bottleneck",
                severity="high",
                message=f"检测到 {len(bottlenecks)} 个超负荷瓶颈工位。",
                action="先调整未开工工单，再评估换线、加班、外协或分批交付。",
                evidence={"stations": [item.get("station_code") or item.get("station_name") for item in bottlenecks[:10]]},
            ))

        otd = facts.get("otd") or {}
        otd_pct = otd.get("otd_pct")
        if otd_pct is not None and _number(otd_pct) < 95:
            signals.append(IntelligenceSignal(
                code="otd_at_risk",
                severity="high",
                message=f"当前 OTD 为 {_number(otd_pct):.1f}%，低于 95% 控制线。",
                action="按交期风险排序复核缺料、瓶颈和异常工单，并将需要重排的订单进入 APS 评审。",
                evidence={"otd_pct": _number(otd_pct)},
            ))

        supplier = facts.get("supplier_delay") or {}
        overdue_count = int(_number(supplier.get("overdue_count")))
        if overdue_count:
            signals.append(IntelligenceSignal(
                code="supplier_delay",
                severity="high",
                message=f"检测到 {overdue_count} 张逾期采购订单。",
                action="按逾期天数升级跟催，并对受影响工单重新进行交期和物料评审。",
                evidence={"overdue_count": overdue_count},
            ))

        inventory = facts.get("inventory") or {}
        stagnant_count = int(_number(inventory.get("stagnant_count")))
        if stagnant_count:
            signals.append(IntelligenceSignal(
                code="inventory_stagnation",
                severity="medium",
                message=f"检测到 {stagnant_count} 个呆滞库存 SKU。",
                action="优先与现行 BOM 复用需求匹配，停止无需求补货后再评估调拨、退供或报废审批。",
                evidence={"stagnant_count": stagnant_count},
            ))

        alert_summary = alert_payload.get("_summary") or {}
        pending = int(_number(alert_summary.get("total_pending")))
        if pending:
            signals.append(IntelligenceSignal(
                code="pending_alerts",
                severity="high",
                message=f"当前有 {pending} 条待确认智能预警。",
                action="优先确认高严重度预警，并将确认后的责任和处置动作回写到业务流程。",
                evidence={"total_pending": pending, "by_severity": alert_summary.get("by_severity") or {}},
            ))
        return signals

    @staticmethod
    async def _default_chat_status() -> Dict[str, Any]:
        # Lazy import avoids a startup-time route/service cycle.
        from api.routes.chat_routes import chat_health

        return await chat_health()

    @staticmethod
    async def _default_pmc_collect(db: Any, factory_id: str) -> Dict[str, Any]:
        from api.services.pmc_control_tower_service import PmcControlTowerService

        return await PmcControlTowerService(db).collect(factory_id, scope="all")

    @staticmethod
    async def _default_alert_summary(db: Any, factory_id: str) -> Dict[str, Any]:
        from api.services.alert_intelligence_service import get_pending_alerts_summary

        return await get_pending_alerts_summary(db, factory_id)

    @staticmethod
    def _default_plugin_manifests() -> Iterable[Dict[str, Any]]:
        from core.sim_erp.plugins.registry import build_default_registry

        return build_default_registry().list_manifests()

    @staticmethod
    def _default_harness_snapshot() -> Dict[str, Any]:
        from core.kernel import __version__
        from core.kernel.plugins import get_harness_plugin_registry

        return {"version": __version__, **get_harness_plugin_registry().snapshot()}


_service: ManufacturingIntelligenceService | None = None


def get_manufacturing_intelligence_service() -> ManufacturingIntelligenceService:
    global _service
    if _service is None:
        _service = ManufacturingIntelligenceService()
    return _service
