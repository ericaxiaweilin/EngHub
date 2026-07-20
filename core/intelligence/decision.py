"""
Decision-oriented facade over EngHub intelligence capabilities.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from core.sim_erp.models import AuditRecord, PhysicalInput

from .hub import ManufacturingIntelligenceHub, get_intelligence_hub


class DecisionStudio:
    def __init__(self, hub: ManufacturingIntelligenceHub):
        self.hub = hub

    async def optimize_schedule(
        self,
        *,
        work_orders: List[Dict[str, Any]],
        constraints: Dict[str, Any],
    ) -> Dict[str, Any] | None:
        return await self.hub.get_ai_service().optimize_schedule(work_orders=work_orders, constraints=constraints)

    async def predict_defects(self, *, process_params: Dict[str, Any]) -> Dict[str, Any] | None:
        return await self.hub.get_ai_service().predict_defects(process_params=process_params)

    async def analyze_quality(self, *, inspection_data: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        return await self.hub.get_ai_service().analyze_quality_trend(inspection_data=inspection_data)

    async def chat(self, *, user_id: str, message: str, context: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
        return await self.hub.get_ai_service().get_chat_response(
            user_id=user_id,
            message=message,
            context=context,
        )

    def simulate_compliance(
        self,
        *,
        physical_input: PhysicalInput,
        plugin_names: Iterable[str],
    ) -> AuditRecord:
        plugins = self.hub.get_sim_erp_plugin_registry().create_many(plugin_names)
        return self.hub.get_sim_erp_engine().evaluate(physical_input, plugins)

    def list_simulation_plugins(self) -> List[dict]:
        return self.hub.get_sim_erp_plugin_registry().list_manifests()

    def default_plugin_names(self) -> List[str]:
        return [manifest["plugin_name"] for manifest in self.list_simulation_plugins()]


_decision_studio: DecisionStudio | None = None


def get_decision_studio() -> DecisionStudio:
    global _decision_studio
    if _decision_studio is None:
        _decision_studio = DecisionStudio(get_intelligence_hub())
    return _decision_studio
