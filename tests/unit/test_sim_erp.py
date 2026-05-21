import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from core.sim_erp.audit import AuditTrail
from core.sim_erp.arbiter import DecisionArbiter
from core.sim_erp.engine import SimERPEngine
from core.sim_erp.models import (
    DecisionType,
    EnvironmentSnapshot,
    PhysicalInput,
    PluginExecutionRecord,
    PluginManifest,
    PolicyPriority,
    RuleDecision,
    WorkContext,
)
from core.sim_erp.physics import PhysicsCore
from core.sim_erp.plugins.builtin import (
    FactoryBreakPolicyPlugin,
    JohnsonGlobalStandardPlugin,
    VNLabor2024Plugin,
)
from core.sim_erp.plugins.registry import build_default_registry
from core.sim_erp.serializers import entity_to_detail_payload, entity_to_summary_payload


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


def test_physics_core_step_based_fatigue_responds_to_heat_and_load():
    snapshot = PhysicsCore().simulate_step(build_input())

    assert snapshot.step_count == 12_000
    assert snapshot.fatigue_score > 20.0
    assert snapshot.energy_kcal > 0.0


def test_arbiter_rejects_when_legal_plugin_violates():
    decision = RuleDecision(
        plugin_name="VN_Legal_2024",
        plugin_version="1.0.0",
        rule_code="VN.CONTINUOUS.WORK",
        rule_version="2024.01",
        decision_type=DecisionType.VIOLATION,
        priority=PolicyPriority.LEGAL,
        message="Continuous work limit exceeded.",
        blocking=True,
    )
    record = PluginExecutionRecord(
        manifest=PluginManifest(
            plugin_name="VN_Legal_2024",
            plugin_version="1.0.0",
            rule_version="2024.01",
            priority=PolicyPriority.LEGAL,
        ),
        duration_ms=1.0,
        decisions=[decision],
        status="ok",
    )

    result = DecisionArbiter().resolve([record])

    assert result.legal_blocked is True
    assert result.accepted is False
    assert result.final_status == "rejected"


def test_engine_records_high_heat_overtime_scenario():
    engine = SimERPEngine()
    record = engine.evaluate(
        build_input(),
        [VNLabor2024Plugin(), JohnsonGlobalStandardPlugin(), FactoryBreakPolicyPlugin()],
    )

    assert record.arbiter_result.legal_blocked is True
    assert record.arbiter_result.total_cost_delta == 30000
    assert "VN.CONTINUOUS.WORK" in {
        decision.rule_code for decision in record.arbiter_result.blocking_decisions
    }


def test_plugin_registry_exposes_default_plugins():
    manifests = build_default_registry().list_manifests()

    assert [manifest["plugin_name"] for manifest in manifests] == [
        "Factory_Policy_Default",
        "Johnson_Global_Standard",
        "VN_Legal_2024",
    ]


def test_audit_trail_persists_records_to_jsonl(tmp_path):
    storage_path = tmp_path / "sim_erp_audit.jsonl"
    engine = SimERPEngine(audit_trail=AuditTrail(storage_path=storage_path))

    record = engine.evaluate(
        build_input(),
        [VNLabor2024Plugin(), JohnsonGlobalStandardPlugin(), FactoryBreakPolicyPlugin()],
    )

    assert storage_path.exists()
    lines = storage_path.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[-1])
    assert payload["simulation_id"] == record.simulation_id
    assert payload["arbiter_result"]["final_status"] == "rejected"


def test_audit_entity_serializers_produce_summary_and_detail():
    entity = SimpleNamespace(
        simulation_id="sim-123",
        final_status="rejected",
        legal_blocked=True,
        created_at=datetime.now(timezone.utc),
        total_cost_delta=Decimal("30000.00"),
        max_required_break_minutes=30,
        total_penalty_score=120,
        worker_ref="worker-001",
        shift_id="shift-day",
        task_type="assembly",
        zone_id="line-a",
        snapshot_payload={"step_count": 12000},
        plugin_records_payload=[{"plugin_name": "VN_Legal_2024"}],
        arbiter_result_payload={
            "blocking_decisions": [{"rule_code": "VN.CONTINUOUS.WORK"}],
            "warnings": [{"rule_code": "JOHNSON.FATIGUE.WARNING"}],
        },
    )

    summary = entity_to_summary_payload(entity)
    detail = entity_to_detail_payload(entity)

    assert summary["simulation_id"] == "sim-123"
    assert summary["blocking_rules"] == ["VN.CONTINUOUS.WORK"]
    assert detail["worker_ref"] == "worker-001"
    assert detail["arbiter_result_payload"]["warnings"][0]["rule_code"] == "JOHNSON.FATIGUE.WARNING"
