"""
Core contracts for the Sim-ERP compliance engine.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PolicyPriority(str, Enum):
    LEGAL = "P0"
    CUSTOMER_CODE = "P1"
    FACTORY_POLICY = "P2"
    OPTIMIZATION_GOAL = "P3"


class DecisionType(str, Enum):
    VIOLATION = "VIOLATION"
    WARNING = "WARNING"
    REQUIRED_ACTION = "REQUIRED_ACTION"
    COST_MODIFIER = "COST_MODIFIER"
    ADVISORY = "ADVISORY"


class TerrainType(str, Enum):
    FLAT = "flat"
    SLOPE = "slope"
    STAIRS = "stairs"
    UNEVEN = "uneven"


class ActionType(str, Enum):
    WALK = "walk"
    LIFT = "lift"
    PUSH = "push"
    PULL = "pull"
    ASSEMBLE = "assemble"
    INSPECT = "inspect"
    IDLE = "idle"


class EnvironmentSnapshot(BaseModel):
    temperature_c: float = Field(default=30.0, ge=-20.0, le=80.0)
    humidity_percent: float = Field(default=60.0, ge=0.0, le=100.0)
    noise_db: Optional[float] = Field(default=None, ge=0.0, le=150.0)
    dust_mg_m3: Optional[float] = Field(default=None, ge=0.0)
    terrain: TerrainType = TerrainType.FLAT
    floor_incline_percent: float = Field(default=0.0, ge=0.0, le=100.0)


class WorkContext(BaseModel):
    task_type: str
    zone_id: str
    shift_id: str
    worker_ref: str
    skill_level: Optional[str] = None
    ppe_status: Optional[str] = None
    machine_risk_level: Optional[str] = None
    action_type: ActionType = ActionType.WALK


class PhysicalInput(BaseModel):
    time_step_minutes: float = Field(..., gt=0.0, le=480.0)
    step_count: int = Field(..., ge=0)
    load_weight_kg: float = Field(default=0.0, ge=0.0, le=500.0)
    posture_angle_deg: float = Field(default=0.0, ge=0.0, le=180.0)
    continuous_work_minutes: int = Field(default=0, ge=0, le=1440)
    distance_meters: float = Field(default=0.0, ge=0.0)
    x_position_m: float = Field(default=0.0)
    y_position_m: float = Field(default=0.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    environment: EnvironmentSnapshot
    work_context: WorkContext


class PhysicalSnapshot(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    timestamp: datetime
    worker_ref: str
    shift_id: str
    task_type: str
    zone_id: str
    action_type: ActionType
    x_position_m: float
    y_position_m: float
    distance_meters: float
    step_count: int
    load_weight_kg: float
    posture_angle_deg: float
    continuous_work_minutes: int
    fatigue_score: float = Field(..., ge=0.0)
    energy_kcal: float = Field(..., ge=0.0)
    environment: EnvironmentSnapshot
    skill_level: Optional[str] = None
    ppe_status: Optional[str] = None
    machine_risk_level: Optional[str] = None


class RuleEvidence(BaseModel):
    field: str
    observed_value: Any
    expected: Optional[str] = None
    source: Optional[str] = None


class RequiredAction(BaseModel):
    action_code: str
    description: str
    break_minutes: int = Field(default=0, ge=0, le=480)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RuleDecision(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    plugin_name: str
    plugin_version: str
    rule_code: str
    rule_version: str
    decision_type: DecisionType
    priority: PolicyPriority
    message: str
    blocking: bool = False
    required_break_minutes: int = Field(default=0, ge=0, le=480)
    cost_delta: float = 0.0
    penalty_score: int = 0
    evidence: List[RuleEvidence] = Field(default_factory=list)
    required_actions: List[RequiredAction] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PluginManifest(BaseModel):
    plugin_name: str
    plugin_version: str
    rule_version: str
    priority: PolicyPriority
    legislation_pack: Optional[str] = None
    timeout_ms: int = Field(default=50, ge=1, le=5_000)
    allow_database: bool = False
    allow_network: bool = False
    allow_state_mutation: bool = False


class PluginExecutionRecord(BaseModel):
    manifest: PluginManifest
    duration_ms: float = Field(..., ge=0.0)
    decisions: List[RuleDecision] = Field(default_factory=list)
    status: str
    error: Optional[str] = None


class ArbiterResult(BaseModel):
    legal_blocked: bool
    accepted: bool
    final_status: str
    max_required_break_minutes: int = 0
    total_cost_delta: float = 0.0
    total_penalty_score: int = 0
    winning_priority: Optional[PolicyPriority] = None
    decisions: List[RuleDecision] = Field(default_factory=list)
    applied_actions: List[RequiredAction] = Field(default_factory=list)
    blocking_decisions: List[RuleDecision] = Field(default_factory=list)
    warnings: List[RuleDecision] = Field(default_factory=list)


class AuditRecord(BaseModel):
    simulation_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    simulation_input_hash: str
    physics_core_version: str
    plugin_manifest_hash: str
    legislation_pack_hash: str
    arbiter_version: str
    optimizer_version: str = "manual"
    random_seed: Optional[int] = None
    snapshot: PhysicalSnapshot
    plugin_records: List[PluginExecutionRecord]
    arbiter_result: ArbiterResult

    @staticmethod
    def stable_hash(payload: Dict[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return sha256(body.encode("utf-8")).hexdigest()
