

"""
v2.6 - RCC (Resource Control Center) Models
资源控制中心 — 三位一体调度系统核心
"""

from sqlalchemy import Column, String, Text, Boolean, Float, Integer, DateTime, JSON, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
import uuid

from database.models import Base


class RCCOrganization(Base):
    """RCC 组织单元"""
    __tablename__ = "rcc_organizations"
    
    id = Column(String(36), ForeignKey("org_units.id", ondelete="CASCADE"), primary_key=True)
    org_type = Column(String(20), nullable=False, default="rcc")
    resource_pool = Column(JSON, default=dict)
    capacity_model = Column(JSON, default=dict)
    dispatch_rules = Column(JSON, default=list)
    auto_dispatch_enabled = Column(Boolean, default=False)
    human_approval_required = Column(Boolean, default=True)
    approval_threshold_pct = Column(Float, default=80.0)
    last_sync_at = Column(DateTime)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # relationships
    org_unit = None  # 继承 org_units
    
    def __repr__(self):
        return f"<RCCOrganization(id={self.id}, type={self.org_type})>"


class RCCTask(Base):
    """RCC 调度任务"""
    __tablename__ = "rcc_tasks"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_code = Column(String(50), unique=True, nullable=False)
    org_unit_id = Column(String(36), ForeignKey("org_units.id", ondelete="SET NULL"))
    task_type = Column(String(30), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    
    affected_params = Column(JSON, default=list)
    affected_entities = Column(JSON, default=list)
    expected_impact_summary = Column(Text)
    
    status = Column(String(20), nullable=False, default="pending")
    # pending/approved/rejected/executing/completed/failed/escalated
    
    approved_by = Column(String(50))
    approved_at = Column(DateTime)
    rejected_by = Column(String(50))
    rejection_reason = Column(Text)
    executed_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    requested_by = Column(String(50))
    request_context = Column(JSON, default=dict)
    source_ticket_id = Column(String(36))
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class RccApprovalRecord(Base):
    """RCC 审批记录"""
    __tablename__ = "rcc_approval_records"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rcc_task_id = Column(String(36), ForeignKey("rcc_tasks.id", ondelete="CASCADE"))
    approver_role = Column(String(50), nullable=False)
    approver_name = Column(String(100))
    decision = Column(String(20), nullable=False)
    decision_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    comment = Column(Text)
    escalation_level = Column(Integer, default=0)


class GlobalAdjustableParam(Base):
    """全局可调参数"""
    __tablename__ = "global_adjustable_params"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    param_code = Column(String(100), unique=True, nullable=False)
    param_name = Column(String(100), nullable=False)
    
    org_unit_id = Column(String(36), ForeignKey("org_units.id", ondelete="SET NULL"))
    position_cap_id = Column(String(36), ForeignKey("position_capabilities.id", ondelete="SET NULL"))
    
    category = Column(String(20), nullable=False)
    param_type = Column(String(20), nullable=False)
    default_value = Column(String)
    current_value = Column(String)
    effective_from = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    target_value = Column(String)
    
    min_value = Column(Float)
    max_value = Column(Float)
    step_value = Column(Float)
    unit = Column(String(50))
    options = Column(JSON, default=list)
    sensitivity = Column(String(20), nullable=False, default="normal")
    
    affects_logic_chains = Column(JSON, default=list)
    rollback_allowed = Column(Boolean, default=True)
    rollback_window_minutes = Column(Integer, default=60)
    
    changed_by = Column(String(50))
    change_reason = Column(Text)
    previous_value = Column(String)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class ParameterChangeAudit(Base):
    """参数变更审计"""
    __tablename__ = "parameter_change_audit"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    param_id = Column(String(36), ForeignKey("global_adjustable_params.id", ondelete="CASCADE"))
    from_value = Column(String)
    to_value = Column(String)
    changed_by = Column(String(50))
    changed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    reason = Column(Text)
    approval_required = Column(Boolean, default=False)
    approval_status = Column(String(20), default="auto_approved")
    approval_record_id = Column(String(36))
    source = Column(String(20), default="panel")
    impact_summary = Column(Text)


class ChatbotTicket(Base):
    """Chatbot 工单"""
    __tablename__ = "chatbot_tickets"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_code = Column(String(50), unique=True, nullable=False)
    
    requester_id = Column(String(50), nullable=False)
    requester_org_unit = Column(String(36), ForeignKey("org_units.id", ondelete="SET NULL"))
    
    ticket_type = Column(String(30), nullable=False)
    
    raw_message = Column(Text, nullable=False)
    parsed_intents = Column(JSON, default=dict)
    parsed_slots = Column(JSON, default=dict)
    
    requested_resource = Column(JSON, default=dict)
    requested_time_window = Column(JSON, default=dict)
    
    related_param_id = Column(String(36), ForeignKey("global_adjustable_params.id", ondelete="SET NULL"))
    related_rcc_task_id = Column(String(36), ForeignKey("rcc_tasks.id", ondelete="SET NULL"))
    related_andon_id = Column(String(36))
    related_work_order_id = Column(String(36), ForeignKey("work_orders.id", ondelete="SET NULL"))
    
    status = Column(String(20), default="open")
    priority = Column(String(20), default="medium")
    
    routed_to_org_unit = Column(String(36))
    routed_to_position = Column(String(50))
    
    resolved_by = Column(String(50))
    resolution = Column(Text)
    resolved_at = Column(DateTime)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class ChatbotTicketApprovalFlow(Base):
    """Chatbot 工单审批流"""
    __tablename__ = "chatbot_ticket_approval_flow"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(String(36), ForeignKey("chatbot_tickets.id", ondelete="CASCADE"))
    step = Column(Integer, nullable=False)
    role_required = Column(String(50), nullable=False)
    approver_id = Column(String(50))
    decision = Column(String(20))
    decision_at = Column(DateTime)
    comment = Column(Text)


class DeterministicLogicChain(Base):
    """确定性逻辑链"""
    __tablename__ = "deterministic_logic_chains"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chain_code = Column(String(50), unique=True, nullable=False)
    chain_name = Column(String(100), nullable=False)
    
    org_unit_id = Column(String(36), ForeignKey("org_units.id", ondelete="SET NULL"))
    position_cap_id = Column(String(36), ForeignKey("position_capabilities.id", ondelete="SET NULL"))
    
    trigger_event = Column(String(100), nullable=False)
    conditions = Column(JSON, nullable=False, default=list)
    action_sequence = Column(JSON, nullable=False, default=list)
    
    enabled = Column(Boolean, default=True)
    execution_order = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class LogicChainExecutionLog(Base):
    """逻辑链执行日志"""
    __tablename__ = "logic_chain_execution_log"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    chain_id = Column(String(36), ForeignKey("deterministic_logic_chains.id", ondelete="CASCADE"))
    triggered_by = Column(String(50))
    trigger_payload = Column(JSON, default=dict)
    conditions_matched = Column(Boolean, default=True)
    actions_executed = Column(JSON, default=list)
    action_results = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
