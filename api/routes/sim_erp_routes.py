"""
Sim-ERP compliance simulation routes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.sim_erp_audit_service import SimERPAuditService
from core.sim_erp.engine import SimERPEngine
from core.sim_erp.models import (
    ActionType,
    AuditRecord,
    EnvironmentSnapshot,
    PhysicalInput,
    TerrainType,
    WorkContext,
)
from core.sim_erp.plugins.registry import build_default_registry
from core.sim_erp.serializers import (
    entity_to_detail_payload,
    entity_to_summary_payload,
    record_to_summary_payload,
)
from database.db_config import get_db
from database.models import SimERPAuditLog

router = APIRouter(prefix="/api/v1/sim-erp", tags=["sim-erp"])
engine = SimERPEngine()
plugin_registry = build_default_registry()


class SimERPScenarioRequest(BaseModel):
    worker_ref: str = "worker-001"
    shift_id: str = "shift-day"
    task_type: str = "assembly"
    zone_id: str = "line-a"
    step_count: int = Field(..., ge=0)
    load_weight_kg: float = Field(default=0.0, ge=0.0)
    posture_angle_deg: float = Field(default=0.0, ge=0.0, le=180.0)
    continuous_work_minutes: int = Field(..., ge=0, le=1440)
    temperature_c: float = Field(..., ge=-20.0, le=80.0)
    humidity_percent: float = Field(default=60.0, ge=0.0, le=100.0)
    distance_meters: float = Field(default=0.0, ge=0.0)


class SimERPEnvironmentRequest(BaseModel):
    temperature_c: float = Field(default=30.0, ge=-20.0, le=80.0)
    humidity_percent: float = Field(default=60.0, ge=0.0, le=100.0)
    noise_db: Optional[float] = Field(default=None, ge=0.0, le=150.0)
    dust_mg_m3: Optional[float] = Field(default=None, ge=0.0)
    terrain: TerrainType = TerrainType.FLAT
    floor_incline_percent: float = Field(default=0.0, ge=0.0, le=100.0)


class SimERPWorkContextRequest(BaseModel):
    worker_ref: str
    shift_id: str
    task_type: str
    zone_id: str
    skill_level: Optional[str] = None
    ppe_status: Optional[str] = None
    machine_risk_level: Optional[str] = None
    action_type: ActionType = ActionType.WALK


class SimERPSimulationRequest(BaseModel):
    time_step_minutes: float = Field(..., gt=0.0, le=480.0)
    step_count: int = Field(..., ge=0)
    load_weight_kg: float = Field(default=0.0, ge=0.0)
    posture_angle_deg: float = Field(default=0.0, ge=0.0, le=180.0)
    continuous_work_minutes: int = Field(default=0, ge=0, le=1440)
    distance_meters: float = Field(default=0.0, ge=0.0)
    x_position_m: float = 0.0
    y_position_m: float = 0.0
    timestamp: Optional[datetime] = None
    environment: SimERPEnvironmentRequest
    work_context: SimERPWorkContextRequest
    plugin_names: List[str] = Field(
        default_factory=lambda: [
            "VN_Legal_2024",
            "Johnson_Global_Standard",
            "Factory_Policy_Default",
        ]
    )


class SimERPRuleEvidenceResponse(BaseModel):
    field: str
    observed_value: Any = None
    expected: Optional[str] = None
    source: Optional[str] = None


class SimERPRequiredActionResponse(BaseModel):
    action_code: str
    description: str
    break_minutes: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SimERPRuleDecisionResponse(BaseModel):
    plugin_name: str
    plugin_version: str
    rule_code: str
    rule_version: str
    decision_type: str
    priority: str
    message: str
    blocking: bool = False
    required_break_minutes: int = 0
    cost_delta: float = 0.0
    penalty_score: int = 0
    evidence: List[SimERPRuleEvidenceResponse] = Field(default_factory=list)
    required_actions: List[SimERPRequiredActionResponse] = Field(default_factory=list)


class SimERPPluginRecordResponse(BaseModel):
    plugin_name: str
    plugin_version: str
    rule_version: str
    priority: str
    legislation_pack: Optional[str] = None
    timeout_ms: int
    duration_ms: float
    status: str
    error: Optional[str] = None
    decisions: List[SimERPRuleDecisionResponse] = Field(default_factory=list)


class SimERPSnapshotResponse(BaseModel):
    timestamp: str
    worker_ref: str
    shift_id: str
    task_type: str
    zone_id: str
    action_type: str
    distance_meters: float
    step_count: int
    load_weight_kg: float
    posture_angle_deg: float
    continuous_work_minutes: int
    fatigue_score: float
    energy_kcal: float
    temperature_c: float
    humidity_percent: float
    noise_db: Optional[float] = None
    terrain: str
    floor_incline_percent: float
    skill_level: Optional[str] = None
    ppe_status: Optional[str] = None
    machine_risk_level: Optional[str] = None


class SimERPSimulationResponse(BaseModel):
    simulation_id: str
    final_status: str
    legal_blocked: bool
    fatigue_score: float
    energy_kcal: float
    total_cost_delta: float
    max_required_break_minutes: int
    blocking_rules: List[str]
    warnings: List[str]
    # --- 扩展工程字段 ---
    total_penalty_score: int = 0
    winning_priority: Optional[str] = None
    physics_core_version: str = ""
    arbiter_version: str = ""
    snapshot: Optional[SimERPSnapshotResponse] = None
    plugin_records: List[SimERPPluginRecordResponse] = Field(default_factory=list)
    applied_actions: List[SimERPRequiredActionResponse] = Field(default_factory=list)
    all_decisions: List[SimERPRuleDecisionResponse] = Field(default_factory=list)


class SimERPPluginManifestResponse(BaseModel):
    plugin_name: str
    plugin_version: str
    rule_version: str
    priority: str
    legislation_pack: Optional[str] = None
    timeout_ms: int


class SimERPAuditSummaryResponse(BaseModel):
    simulation_id: str
    final_status: str
    legal_blocked: bool
    created_at: datetime
    total_cost_delta: float
    max_required_break_minutes: int
    blocking_rules: List[str]
    warnings: List[str]


class SimERPAuditListResponse(BaseModel):
    items: List[SimERPAuditSummaryResponse]
    total: int
    page: int
    page_size: int


class SimERPAuditDetailResponse(SimERPAuditSummaryResponse):
    worker_ref: str
    shift_id: str
    task_type: str
    zone_id: str
    total_penalty_score: int
    snapshot_payload: dict
    plugin_records_payload: List[dict]
    arbiter_result_payload: dict


def _record_to_summary(record: AuditRecord) -> SimERPAuditSummaryResponse:
    return SimERPAuditSummaryResponse(**record_to_summary_payload(record))


def _entity_to_summary(entity: SimERPAuditLog) -> SimERPAuditSummaryResponse:
    return SimERPAuditSummaryResponse(**entity_to_summary_payload(entity))


def _entity_to_detail(entity: SimERPAuditLog) -> SimERPAuditDetailResponse:
    return SimERPAuditDetailResponse(**entity_to_detail_payload(entity))


def _decision_to_response(d) -> SimERPRuleDecisionResponse:
    return SimERPRuleDecisionResponse(
        plugin_name=d.plugin_name,
        plugin_version=d.plugin_version,
        rule_code=d.rule_code,
        rule_version=d.rule_version,
        decision_type=d.decision_type if isinstance(d.decision_type, str) else d.decision_type.value,
        priority=d.priority if isinstance(d.priority, str) else d.priority.value,
        message=d.message,
        blocking=d.blocking,
        required_break_minutes=d.required_break_minutes,
        cost_delta=d.cost_delta,
        penalty_score=d.penalty_score,
        evidence=[
            SimERPRuleEvidenceResponse(
                field=e.field, observed_value=e.observed_value,
                expected=e.expected, source=e.source,
            )
            for e in d.evidence
        ],
        required_actions=[
            SimERPRequiredActionResponse(
                action_code=a.action_code, description=a.description,
                break_minutes=a.break_minutes, metadata=a.metadata,
            )
            for a in d.required_actions
        ],
    )


def _build_response(record: AuditRecord) -> SimERPSimulationResponse:
    snap = record.snapshot
    env = snap.environment
    wc = snap
    return SimERPSimulationResponse(
        simulation_id=record.simulation_id,
        final_status=record.arbiter_result.final_status,
        legal_blocked=record.arbiter_result.legal_blocked,
        fatigue_score=snap.fatigue_score,
        energy_kcal=snap.energy_kcal,
        total_cost_delta=record.arbiter_result.total_cost_delta,
        max_required_break_minutes=record.arbiter_result.max_required_break_minutes,
        blocking_rules=[decision.rule_code for decision in record.arbiter_result.blocking_decisions],
        warnings=[decision.rule_code for decision in record.arbiter_result.warnings],
        # --- 扩展工程字段 ---
        total_penalty_score=record.arbiter_result.total_penalty_score,
        winning_priority=(
            record.arbiter_result.winning_priority.value
            if record.arbiter_result.winning_priority else None
        ),
        physics_core_version=record.physics_core_version,
        arbiter_version=record.arbiter_version,
        snapshot=SimERPSnapshotResponse(
            timestamp=snap.timestamp.isoformat(),
            worker_ref=snap.worker_ref,
            shift_id=snap.shift_id,
            task_type=snap.task_type,
            zone_id=snap.zone_id,
            action_type=snap.action_type if isinstance(snap.action_type, str) else snap.action_type.value,
            distance_meters=snap.distance_meters,
            step_count=snap.step_count,
            load_weight_kg=snap.load_weight_kg,
            posture_angle_deg=snap.posture_angle_deg,
            continuous_work_minutes=snap.continuous_work_minutes,
            fatigue_score=snap.fatigue_score,
            energy_kcal=snap.energy_kcal,
            temperature_c=env.temperature_c,
            humidity_percent=env.humidity_percent,
            noise_db=env.noise_db,
            terrain=env.terrain if isinstance(env.terrain, str) else env.terrain.value,
            floor_incline_percent=env.floor_incline_percent,
            skill_level=snap.skill_level,
            ppe_status=snap.ppe_status,
            machine_risk_level=snap.machine_risk_level,
        ),
        plugin_records=[
            SimERPPluginRecordResponse(
                plugin_name=pr.manifest.plugin_name,
                plugin_version=pr.manifest.plugin_version,
                rule_version=pr.manifest.rule_version,
                priority=pr.manifest.priority if isinstance(pr.manifest.priority, str) else pr.manifest.priority.value,
                legislation_pack=pr.manifest.legislation_pack,
                timeout_ms=pr.manifest.timeout_ms,
                duration_ms=pr.duration_ms,
                status=pr.status,
                error=pr.error,
                decisions=[_decision_to_response(d) for d in pr.decisions],
            )
            for pr in record.plugin_records
        ],
        applied_actions=[
            SimERPRequiredActionResponse(
                action_code=a.action_code, description=a.description,
                break_minutes=a.break_minutes, metadata=a.metadata,
            )
            for a in record.arbiter_result.applied_actions
        ],
        all_decisions=[
            _decision_to_response(d) for d in record.arbiter_result.decisions
        ],
    )


@router.get("/status")
async def sim_erp_status():
    return {
        "status": "running",
        "engine": "Sim-ERP v2.0",
        "physics_model": "step_based_fatigue",
    }


@router.get("/plugins", response_model=List[SimERPPluginManifestResponse])
async def list_plugins():
    return plugin_registry.list_manifests()


@router.get("/audits", response_model=SimERPAuditListResponse)
async def list_audits(
    page: int = 1,
    page_size: int = 20,
    worker_ref: Optional[str] = None,
    final_status: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db),
):
    if page < 1:
        raise HTTPException(status_code=400, detail="page must be at least 1")
    if page_size < 1 or page_size > 200:
        raise HTTPException(status_code=400, detail="page_size must be between 1 and 200")
    if created_from and created_to and created_from > created_to:
        raise HTTPException(status_code=400, detail="created_from must be before created_to")

    entities, total = await SimERPAuditService(db).list_audit_logs(
        page=page,
        page_size=page_size,
        worker_ref=worker_ref,
        final_status=final_status,
        created_from=created_from,
        created_to=created_to,
    )
    return SimERPAuditListResponse(
        items=[_entity_to_summary(entity) for entity in entities],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/audits/latest", response_model=SimERPAuditSummaryResponse)
async def latest_audit(db: AsyncSession = Depends(get_db)):
    service = SimERPAuditService(db)
    entity = await service.get_latest_audit_log()
    if entity is not None:
        return _entity_to_summary(entity)

    record = engine.audit_trail.latest()
    if record is None:
        raise HTTPException(status_code=404, detail="No audit records found.")
    return _record_to_summary(record)


@router.get("/audits/{simulation_id}", response_model=SimERPAuditDetailResponse)
async def get_audit(simulation_id: str, db: AsyncSession = Depends(get_db)):
    entity = await SimERPAuditService(db).get_audit_log_by_simulation_id(simulation_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Audit record not found.")
    return _entity_to_detail(entity)


@router.post("/simulate", response_model=SimERPSimulationResponse)
async def simulate(request: SimERPSimulationRequest, db: AsyncSession = Depends(get_db)):
    try:
        plugins = plugin_registry.create_many(request.plugin_names)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown plugin: {exc.args[0]}") from exc

    physical_input = PhysicalInput(
        time_step_minutes=request.time_step_minutes,
        step_count=request.step_count,
        load_weight_kg=request.load_weight_kg,
        posture_angle_deg=request.posture_angle_deg,
        continuous_work_minutes=request.continuous_work_minutes,
        distance_meters=request.distance_meters,
        x_position_m=request.x_position_m,
        y_position_m=request.y_position_m,
        timestamp=request.timestamp or datetime.now(timezone.utc),
        environment=EnvironmentSnapshot(**request.environment.model_dump()),
        work_context=WorkContext(**request.work_context.model_dump()),
    )
    record = engine.evaluate(physical_input, plugins)
    await _persist_audit_record(db, record)
    return _build_response(record)


@router.post("/scenarios/high-heat-overtime", response_model=SimERPSimulationResponse)
async def simulate_high_heat_overtime(
    request: SimERPScenarioRequest,
    db: AsyncSession = Depends(get_db),
):
    physical_input = PhysicalInput(
        time_step_minutes=30,
        step_count=request.step_count,
        load_weight_kg=request.load_weight_kg,
        posture_angle_deg=request.posture_angle_deg,
        continuous_work_minutes=request.continuous_work_minutes,
        distance_meters=request.distance_meters,
        x_position_m=0.0,
        y_position_m=0.0,
        timestamp=datetime.now(timezone.utc),
        environment=EnvironmentSnapshot(
            temperature_c=request.temperature_c,
            humidity_percent=request.humidity_percent,
        ),
        work_context=WorkContext(
            task_type=request.task_type,
            zone_id=request.zone_id,
            shift_id=request.shift_id,
            worker_ref=request.worker_ref,
            action_type=ActionType.WALK,
        ),
    )
    record = engine.evaluate(
        physical_input,
        plugin_registry.create_many(
            ["VN_Legal_2024", "Johnson_Global_Standard", "Factory_Policy_Default"]
        ),
    )
    await _persist_audit_record(db, record)
    return _build_response(record)


async def _persist_audit_record(db: AsyncSession, record: AuditRecord) -> None:
    try:
        await SimERPAuditService(db).create_audit_log(record)
    except Exception:
        await db.rollback()
