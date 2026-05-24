"""
Unified entrypoint for EngHub intelligence capabilities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, TYPE_CHECKING

from core.ai_service import AIService, ai_service
from core.search_engine.v2 import BusinessDataLoader, UnifiedSearchEngine, get_data_loader, get_search_engine
from core.sim_erp.engine import SimERPEngine
from core.sim_erp.plugins.registry import PluginRegistry, build_default_registry

from .models import DecisionSurface, IntelligenceHealth, IntelligenceOverview, IntelligenceSubsystem

if TYPE_CHECKING:
    from core.expert_system import ExpertEngine


class UnavailableExpertEngine:
    def __init__(self, reason: str):
        self.reason = reason
        self.is_initialized = False
        self.knowledge_base = None
        self.tool_registry = None

    async def initialize(self) -> None:
        raise RuntimeError(self.reason)

    async def chat(self, query: str, context: dict | None = None) -> dict:
        raise RuntimeError(self.reason)


class ManufacturingIntelligenceHub:
    """
    Concentrates simulation, AI, search, expert reasoning, and decision surfaces
    behind one stable module boundary.
    """

    VERSION = "1.0.0"

    def __init__(
        self,
        *,
        ai_service_instance: AIService | None = None,
        expert_engine_factory: Callable[[], Any] | None = None,
        search_engine_getter: Callable[[], UnifiedSearchEngine] | None = None,
        search_loader_getter: Callable[[], BusinessDataLoader] | None = None,
        sim_erp_engine: SimERPEngine | None = None,
        plugin_registry: PluginRegistry | None = None,
    ):
        self._ai_service = ai_service_instance or ai_service
        self._expert_engine_factory = expert_engine_factory
        self._search_engine_getter = search_engine_getter or get_search_engine
        self._search_loader_getter = search_loader_getter or get_data_loader
        self._sim_erp_engine = sim_erp_engine or SimERPEngine()
        self._plugin_registry = plugin_registry or build_default_registry()
        self._expert_engine: Any | None = None
        self._search_engine: UnifiedSearchEngine | None = None
        self._search_loader: BusinessDataLoader | None = None

    def get_ai_service(self) -> AIService:
        return self._ai_service

    def get_expert_engine(self) -> Any:
        if self._expert_engine is None:
            try:
                factory = self._expert_engine_factory or self._load_default_expert_engine
                self._expert_engine = factory()
            except ModuleNotFoundError as exc:
                self._expert_engine = UnavailableExpertEngine(
                    f"Expert system dependency is unavailable: {exc}"
                )
        return self._expert_engine

    def get_search_engine(self) -> UnifiedSearchEngine:
        if self._search_engine is None:
            self._search_engine = self._search_engine_getter()
        return self._search_engine

    def get_search_loader(self) -> BusinessDataLoader:
        if self._search_loader is None:
            self._search_loader = self._search_loader_getter()
        return self._search_loader

    def get_sim_erp_engine(self) -> SimERPEngine:
        return self._sim_erp_engine

    def get_sim_erp_plugin_registry(self) -> PluginRegistry:
        return self._plugin_registry

    def _load_default_expert_engine(self) -> Any:
        from core.expert_system import ExpertEngine

        return ExpertEngine()

    def build_overview(self) -> IntelligenceOverview:
        search_stats = self.get_search_engine().get_stats()
        expert_engine = self.get_expert_engine()
        plugin_manifests = self.get_sim_erp_plugin_registry().list_manifests()

        return IntelligenceOverview(
            system_name="EngHub Intelligence Core",
            system_type="manufacturing_intelligence_platform",
            focus=["simulation", "ai", "scenario_reasoning", "decisioning"],
            orchestration_flow=[
                "physical_input",
                "simulation",
                "search_and_context",
                "expert_reasoning",
                "ai_prediction",
                "decision_arbitration",
                "audit_trail",
            ],
            decision_surfaces=[
                DecisionSurface(
                    name="compliance_simulation",
                    role="physics + legal/customer/factory arbitration",
                    entrypoint="core.sim_erp.engine.SimERPEngine.evaluate",
                    capabilities=["fatigue simulation", "plugin evaluation", "audit record generation"],
                ),
                DecisionSurface(
                    name="ai_prediction",
                    role="gateway-backed forecasting and optimization",
                    entrypoint="core.ai_service.AIService",
                    capabilities=["schedule optimization", "defect prediction", "quality trend analysis"],
                ),
                DecisionSurface(
                    name="expert_reasoning",
                    role="RAG + tool-calling manufacturing advisory",
                    entrypoint="core.expert_system.ExpertEngine.chat",
                    capabilities=["knowledge retrieval", "tool execution", "operational guidance"],
                ),
                DecisionSurface(
                    name="unified_search",
                    role="cross-module context retrieval",
                    entrypoint="core.search_engine.v2.UnifiedSearchEngine.search",
                    capabilities=["multi-entity search", "context links", "action-oriented results"],
                ),
            ],
            subsystems=[
                IntelligenceSubsystem(
                    name="simulation",
                    role="step-based physical and compliance simulation",
                    module="core.sim_erp",
                    status="ready",
                    capabilities=["physics core", "plugin sandbox contract", "arbiter", "audit"],
                    details={"plugins": [manifest["plugin_name"] for manifest in plugin_manifests]},
                ),
                IntelligenceSubsystem(
                    name="ai",
                    role="external prediction and optimization gateway",
                    module="core.ai_service",
                    status="ready",
                    capabilities=["schedule optimization", "defect prediction", "quality analysis", "chat"],
                    details={
                        "gateway_url": self.get_ai_service().model_gateway_url,
                        "chatbot_url": self.get_ai_service().chatbot_url,
                    },
                ),
                IntelligenceSubsystem(
                    name="expert",
                    role="production expert copilot",
                    module="core.expert_system",
                    status="initialized" if expert_engine.is_initialized else "standby",
                    capabilities=["RAG retrieval", "tool calling", "expert chat"],
                    details={"initialized": expert_engine.is_initialized},
                ),
                IntelligenceSubsystem(
                    name="search",
                    role="enterprise retrieval fabric",
                    module="core.search_engine.v2",
                    status="ready",
                    capabilities=["full-text search", "related context", "result actions"],
                    details={"indexed_documents": search_stats["total_documents"]},
                ),
                IntelligenceSubsystem(
                    name="decision",
                    role="orchestration layer over all intelligence surfaces",
                    module="core.intelligence",
                    status="ready",
                    capabilities=["shared entrypoint", "capability routing", "decision facade"],
                    details={"hub_version": self.VERSION},
                ),
            ],
        )

    async def build_health_snapshot(self) -> IntelligenceHealth:
        ai_gateway_ok = await self.get_ai_service().health_check()
        expert_engine = self.get_expert_engine()
        search_stats = self.get_search_engine().get_stats()
        plugin_count = len(self.get_sim_erp_plugin_registry().list_manifests())

        subsystems = [
            IntelligenceSubsystem(
                name="simulation",
                role="step-based physical and compliance simulation",
                module="core.sim_erp",
                status="healthy",
                capabilities=["simulation", "arbiter", "audit"],
                details={"plugin_count": plugin_count},
            ),
            IntelligenceSubsystem(
                name="ai",
                role="external prediction and optimization gateway",
                module="core.ai_service",
                status="healthy" if ai_gateway_ok else "degraded",
                capabilities=["prediction", "optimization", "chat"],
                details={"gateway_available": ai_gateway_ok},
            ),
            IntelligenceSubsystem(
                name="expert",
                role="production expert copilot",
                module="core.expert_system",
                status="healthy" if expert_engine.is_initialized else "standby",
                capabilities=["knowledge retrieval", "tool calling"],
                details={"initialized": expert_engine.is_initialized},
            ),
            IntelligenceSubsystem(
                name="search",
                role="enterprise retrieval fabric",
                module="core.search_engine.v2",
                status="healthy",
                capabilities=["search", "suggestions", "indexing"],
                details=search_stats,
            ),
        ]
        overall = "healthy" if ai_gateway_ok else "degraded"
        return IntelligenceHealth(
            status=overall,
            checked_at=datetime.now(timezone.utc),
            subsystems=subsystems,
        )


_intelligence_hub: ManufacturingIntelligenceHub | None = None


def get_intelligence_hub() -> ManufacturingIntelligenceHub:
    global _intelligence_hub
    if _intelligence_hub is None:
        _intelligence_hub = ManufacturingIntelligenceHub()
    return _intelligence_hub
