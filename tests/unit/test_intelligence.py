from datetime import datetime, timezone

import pytest

from core.intelligence import DecisionStudio, ManufacturingIntelligenceHub
from core.sim_erp.audit import AuditTrail
from core.sim_erp.engine import SimERPEngine
from core.sim_erp.models import EnvironmentSnapshot, PhysicalInput, WorkContext
from core.sim_erp.plugins.registry import build_default_registry


class FakeAIService:
    def __init__(self, healthy: bool = True):
        self._healthy = healthy
        self.model_gateway_url = "http://gateway.test"
        self.chatbot_url = "http://chatbot.test"

    async def health_check(self) -> bool:
        return self._healthy

    async def optimize_schedule(self, work_orders, constraints):
        return {"task": "schedule", "work_orders": len(work_orders), "constraints": constraints}

    async def predict_defects(self, process_params):
        return {"task": "predict", "params": process_params}

    async def analyze_quality_trend(self, inspection_data):
        return {"task": "quality", "rows": len(inspection_data)}

    async def get_chat_response(self, user_id, message, context=None):
        return {"user_id": user_id, "message": message, "context": context or {}}


class FakeSearchEngine:
    def get_stats(self):
        return {"total_documents": 12, "total_terms": 48}


class FakeSearchLoader:
    pass


def build_input() -> PhysicalInput:
    return PhysicalInput(
        time_step_minutes=30,
        step_count=12_000,
        load_weight_kg=20.0,
        posture_angle_deg=50.0,
        continuous_work_minutes=300,
        distance_meters=2_500.0,
        x_position_m=0.0,
        y_position_m=0.0,
        timestamp=datetime.now(timezone.utc),
        environment=EnvironmentSnapshot(
            temperature_c=38.0,
            humidity_percent=70.0,
        ),
        work_context=WorkContext(
            worker_ref="worker-001",
            shift_id="shift-day",
            task_type="assembly",
            zone_id="line-a",
            action_type="walk",
        ),
    )


def build_hub(tmp_path, healthy: bool = True) -> ManufacturingIntelligenceHub:
    return ManufacturingIntelligenceHub(
        ai_service_instance=FakeAIService(healthy=healthy),
        search_engine_getter=FakeSearchEngine,
        search_loader_getter=FakeSearchLoader,
        sim_erp_engine=SimERPEngine(audit_trail=AuditTrail(storage_path=tmp_path / "audit.jsonl")),
        plugin_registry=build_default_registry(),
    )


def test_intelligence_overview_concentrates_non_crud_capabilities(tmp_path):
    hub = build_hub(tmp_path)

    overview = hub.build_overview()

    assert overview.system_type == "manufacturing_intelligence_platform"
    assert overview.focus == ["simulation", "ai", "scenario_reasoning", "decisioning"]
    assert [subsystem.name for subsystem in overview.subsystems] == [
        "simulation",
        "ai",
        "expert",
        "search",
        "decision",
    ]


def test_decision_studio_keeps_sim_erp_compliance_chain_working(tmp_path):
    studio = DecisionStudio(build_hub(tmp_path))

    record = studio.simulate_compliance(
        physical_input=build_input(),
        plugin_names=["VN_Legal_2024", "Johnson_Global_Standard", "Factory_Policy_Default"],
    )

    assert record.arbiter_result.legal_blocked is True
    assert record.arbiter_result.final_status == "rejected"


@pytest.mark.asyncio
async def test_intelligence_health_marks_ai_gateway_as_degraded(tmp_path):
    hub = build_hub(tmp_path, healthy=False)

    snapshot = await hub.build_health_snapshot()

    ai_status = next(subsystem for subsystem in snapshot.subsystems if subsystem.name == "ai")
    assert snapshot.status == "degraded"
    assert ai_status.status == "degraded"
