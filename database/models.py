"""
Database Models - SQLAlchemy ORM Models
数据库模型定义
"""
from datetime import datetime, timedelta
from sqlalchemy import (
    BigInteger,
    Column,
    String,
    Integer,
    DateTime,
    Date,
    Time,
    Boolean,
    Numeric,
    Float,
    ForeignKey,
    Index,
    Text,
    JSON,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship, backref
import uuid

Base = declarative_base()


def _model_to_dict(self):
    """Return persisted columns without leaking SQLAlchemy internals."""
    return {column.name: getattr(self, column.key) for column in self.__table__.columns}


Base.to_dict = _model_to_dict


def generate_uuid():
    """生成 UUID"""
    return str(uuid.uuid4())


# ============================================================
# 权限与角色模型（新增）
# ============================================================

class Role(Base):
    """角色表 - 存储 MES 系统预定义角色"""

    __tablename__ = "roles"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    role_code = Column(String(50), unique=True, nullable=False, index=True)  # factory_manager, operator...
    role_name = Column(String(100), nullable=False)  # 厂长、操作员...
    position = Column(String(30), nullable=False, index=True)  # 职位层级
    department = Column(String(50), default="all")  # 所属部门
    description = Column(Text)
    is_system = Column(Boolean, default=False, index=True)  # 系统内置角色不可删除
    level = Column(Integer, default=999)  # 层级数字，越小越高
    permissions = Column(JSON().with_variant(JSONB, "postgresql"), default=list)
    # 数据范围: {"type": "own"|"department"|"factory"|"all"}
    data_scope = Column(JSON().with_variant(JSONB, "postgresql"), default={"type": "own"})
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关系
    users = relationship("User", back_populates="role_obj", foreign_keys="User.role_id")

    __table_args__ = (
        Index("idx_role_position_dept", "position", "department"),
    )


class Permission(Base):
    """权限表 - 细粒度权限定义"""

    __tablename__ = "permissions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    module = Column(String(50), nullable=False, index=True)  # work_order, production_report...
    action = Column(String(30), nullable=False, index=True)  # view, create, edit, delete, approve...
    module_name = Column(String(50))  # 中文模块名
    action_name = Column(String(50))  # 中文动作名
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_perm_module_action", "module", "action", unique=True),
    )


class UserRole(Base):
    """用户-角色关联表 - 支持多角色"""

    __tablename__ = "user_roles"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False, index=True)
    is_primary = Column(Boolean, default=True)  # 是否主角色
    assigned_by = Column(String(50))
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)

    # 关系
    user_obj = relationship("User", back_populates="user_roles", foreign_keys=[user_id])
    role_obj = relationship("Role", foreign_keys=[role_id])

    __table_args__ = (
        Index("idx_user_role_user_role", "user_id", "role_id", unique=True),
    )


class RolePermission(Base):
    """角色-权限关联表"""

    __tablename__ = "role_permissions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False, index=True)
    permission_id = Column(UUID(as_uuid=True), ForeignKey("permissions.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_role_perm_role_perm", "role_id", "permission_id", unique=True),
    )


class User(Base):
    """用户表"""
    
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100))
    factory_id = Column(String(50), index=True)
    role = Column(String(50), default="operator", index=True)  # 兼容字段：快捷角色编码
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=True, index=True)  # 关联角色表
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    work_center = Column(String(20), nullable=True, index=True)  # 工序组编码（WCUT/EDM/CUT...），null=管理岗不绑定
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # 密码重置相关字段（用于忘记密码功能）
    password_reset_token = Column(String(255), index=True, nullable=True, default=None)  # 重置令牌哈希
    password_reset_expires = Column(DateTime, nullable=True)  # 令牌过期时间
    
    # 关系
    role_obj = relationship("Role", back_populates="users", foreign_keys=[role_id])
    user_roles = relationship("UserRole", back_populates="user_obj", foreign_keys="UserRole.user_id")
    
    __table_args__ = (
        Index("idx_user_factory_role", "factory_id", "role"),
        Index("idx_user_password_reset_token", "password_reset_token"),
    )


class WorkOrder(Base):
    """生产工单表"""
    
    __tablename__ = "work_orders"
    
    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    work_order_code = Column(String(50), unique=True, nullable=False, index=True)
    factory_id = Column(String(50), nullable=False, index=True)
    sales_order_id = Column(String(50), index=True)
    product_id = Column(String(50), nullable=False, index=True)
    routing_id = Column(String(50))
    planned_qty = Column(Integer, nullable=False, default=0)
    unit = Column(String(20), default="pcs")
    completed_qty = Column(Integer, default=0)
    good_qty = Column(Integer, default=0)
    defect_qty = Column(Integer, default=0)
    scrap_qty = Column(Integer, default=0)
    status = Column(String(20), nullable=False, default="pending", index=True)
    priority = Column(String(20), default="medium")
    planned_start = Column(DateTime)
    planned_due = Column(DateTime)
    actual_start = Column(DateTime)
    actual_complete = Column(DateTime)
    assigned_station_id = Column(String(50), index=True)
    current_routing_step = Column(Integer, default=0)
    current_stage = Column(String(100), nullable=True)
    next_station = Column(String(100), nullable=True)
    in_progress_status = Column(String(30), nullable=True)
    partial_completion_percentage = Column(Float, default=0)
    bom_version = Column(String(50))
    # ---- 工单体系化编码：层级字段（主工单 <-> 工序工单）----
    parent_work_order_id = Column(UUID(as_uuid=False), ForeignKey("work_orders.id"), nullable=True, index=True)
    wo_type = Column(String(20), nullable=False, default="master", index=True)  # master=主工单 / operation=工序工单
    process_code = Column(String(20), nullable=True, index=True)  # 行业通用工序代码（SMT/INJ/MACH...），主工单为空
    operation_seq = Column(Integer, nullable=True)  # 同一工序内道次序号（01/02...）
    created_by = Column(String(50))
    updated_by = Column(String(50))
    # ---- 状态审核机制（014）：下达人/完工确认人 ----
    released_by = Column(String(50), nullable=True)   # 下达人（管理角色且非创建人）
    completed_by = Column(String(50), nullable=True)  # 完工确认人（品质角色）
    # ---- 工序流转与多角色视角（016）----
    assigned_to = Column(String(36), nullable=True, index=True)  # 指派操作人 user_id
    work_center = Column(String(20), nullable=True, index=True)  # 工序组（operation 工单=process_code）
    routing_template_id = Column(String(36), nullable=True)  # 绑定的工艺路线模板
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # 索引
    __table_args__ = (
        Index("idx_wo_status_factory", "status", "factory_id"),
        Index("idx_wo_created_at", "created_at"),
        Index("idx_wo_parent", "parent_work_order_id"),
    )
    
    # 关系
    production_reports = relationship("ProductionReport", back_populates="work_order")
    # 层级关系：主工单.operations -> 工序工单；工序工单.parent -> 主工单
    operations = relationship(
        "WorkOrder",
        backref=backref("parent", remote_side=[id]),
        cascade="all, delete-orphan",
    )




class QualityInspection(Base):
    """质量检验记录表"""
    __tablename__ = "quality_inspections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    work_order_id = Column(String(36), nullable=False, index=True)
    routing_step_id = Column(String(36), nullable=False, index=True)
    inspect_type = Column(String(20), nullable=False)  # IQC/IPQC/FQC/OQC
    inspection_phase = Column(String(30), nullable=True)
    inspector_id = Column(String(50), nullable=False)
    sample_qty = Column(Integer, nullable=False, default=0)
    sampling_method = Column(String(100), nullable=True)
    check_tool_id = Column(String(50), nullable=True)
    defect_qty = Column(Integer, nullable=False, default=0)
    result = Column(String(20), nullable=False)  # PASS/FAIL/PENDING
    defect_details = Column(JSON, nullable=True)
    remark = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Inspection(Base):
    """Compatibility inspection model used by the complete AQL workflow."""

    __tablename__ = "inspections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    inspection_code = Column(String(50), unique=True, nullable=False, index=True)
    factory_id = Column(String(50), nullable=False, index=True)
    inspection_type = Column(String(20), nullable=False)
    product_id = Column(String(50), nullable=True)
    material_id = Column(String(50), nullable=True)
    batch_id = Column(String(50), nullable=True)
    batch_size = Column(Integer, default=0)
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=True)
    aql_level = Column(Float, default=1.0)
    inspection_level = Column(String(20), default="general_ii")
    sample_size = Column(Integer, nullable=True)
    status = Column(String(20), default="pending", nullable=False)
    inspected_qty = Column(Integer, default=0)
    defective_qty = Column(Integer, default=0)
    inspector_id = Column(String(50))
    inspected_at = Column(DateTime)
    aql_result = Column(JSON)
    remarks = Column(Text)
    created_by = Column(String(50))
    updated_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Defect(Base):
    """Compatibility defect model used by the AQL/OCAP workflow."""

    __tablename__ = "defects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    defect_code = Column(String(50), unique=True, nullable=False, index=True)
    factory_id = Column(String(50), nullable=False, index=True)
    defect_type = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False)
    severity = Column(String(20), nullable=False)
    inspection_id = Column(String(36), ForeignKey("inspections.id"), nullable=True)
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=True)
    material_id = Column(String(50), nullable=True)
    batch_id = Column(String(50), nullable=True)
    station_id = Column(String(50), nullable=True)
    description = Column(Text)
    status = Column(String(20), default="open", nullable=False)
    disposition = Column(String(20))
    disposition_by = Column(String(50))
    disposition_at = Column(DateTime)
    disposition_qty = Column(Integer)
    disposition_remark = Column(Text)
    ocap_status = Column(String(20), default="pending")
    ocap_triggered_at = Column(DateTime)
    ocap_trigger_reason = Column(Text)
    created_by = Column(String(50))
    updated_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class WoStatusLog(Base):
    """工单状态操作日志（审核追溯：谁/什么角色/何时/做了什么）"""
    __tablename__ = "wo_status_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    work_order_id = Column(UUID(as_uuid=False), ForeignKey("work_orders.id"), nullable=False, index=True)
    action = Column(String(30), nullable=False)          # create/release/start/pause/resume/pending_inbound/complete/close/cancel/split
    from_status = Column(String(20), nullable=True)
    to_status = Column(String(20), nullable=False)
    operator = Column(String(50), nullable=False)        # 操作人 username
    operator_role = Column(String(50), nullable=True)    # 操作人角色
    comment = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class FileRecord(Base):
    """文件/附件元数据（chatbot 多模态收发 + 系统表单/报告导出）。

    实体落盘到容器 /app/uploads；按 factory_id 多工厂隔离，
    related_type/related_id 关联业务对象（work_order/inspection/report/chat...）。"""
    __tablename__ = "files"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    filename = Column(String(255), nullable=False)        # 原始文件名
    content_type = Column(String(100), nullable=True)     # MIME 类型
    size = Column(Integer, default=0)                     # 字节数
    storage_path = Column(String(500), nullable=False)    # 容器内落盘路径
    uploaded_by = Column(String(50), nullable=True)       # 上传人 username
    factory_id = Column(String(50), nullable=True, index=True)  # 所属工厂
    related_type = Column(String(50), nullable=True)      # 关联业务对象类型
    related_id = Column(String(50), nullable=True)        # 关联业务对象 ID
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_files_related", "related_type", "related_id"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "content_type": self.content_type,
            "size": self.size,
            "uploaded_by": self.uploaded_by,
            "factory_id": self.factory_id,
            "related_type": self.related_type,
            "related_id": self.related_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
        }


class Plan(Base):
    """生产计划表 (MPS)"""
    
    __tablename__ = "pp_plans"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    plan_code = Column(String(50), unique=True, nullable=False, index=True)
    plan_type = Column(String(20), nullable=False, default='mps')
    product_id = Column(String(50), nullable=False, index=True)
    sales_order_id = Column(String(50))
    quantity = Column(Integer, nullable=False)
    required_date = Column(Date, nullable=False)
    due_date = Column(Date)
    customer_level = Column(String(10), default='b')
    priority = Column(Integer, default=50)
    priority_score = Column(Numeric(10, 2))
    status = Column(String(20), nullable=False, default='draft')
    planning_cycle = Column(String(30), nullable=True)
    release_status = Column(String(20), default="unreleased")
    planner_id = Column(String(50), nullable=True)
    
    station_id = Column(String(50))
    scheduled_start_date = Column(Date)
    scheduled_end_date = Column(Date)
    
    mrp_status = Column(String(20), default='pending')
    
    created_by = Column(String(50))
    updated_by = Column(String(50))
    confirmed_by = Column(String(50))
    released_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    confirmed_at = Column(DateTime)
    released_at = Column(DateTime)
    
    __table_args__ = (
        Index("idx_plan_factory", "factory_id"),
        Index("idx_plan_status", "status"),
        Index("idx_plan_product", "product_id"),
        Index("idx_plan_required_date", "required_date"),
    )


class ProductionReport(Base):
    """生产报工表"""
    
    __tablename__ = "production_reports"
    
    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    report_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    work_order_id = Column(UUID(as_uuid=False), ForeignKey("work_orders.id"), nullable=False, index=True)
    station_id = Column(String(50), nullable=False, index=True)
    good_qty = Column(Integer, nullable=False, default=0)
    defect_qty = Column(Integer, default=0)
    scrap_qty = Column(Integer, default=0)
    report_type = Column(String(20), default="normal")
    shift = Column(String(20), default="day")
    operator_id = Column(String(50))
    assistant_operator_ids = Column(JSON().with_variant(JSONB, "postgresql"), default=list)
    quality_check_passed = Column(Boolean, nullable=True)
    remark = Column(Text)
    # ---- 023: 岗位替代 Phase 1 扩展 ----
    operation_seq = Column(Integer, nullable=True)
    operation_name = Column(String(100), nullable=True)
    machine_id = Column(String(50), nullable=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    cycle_time_sec = Column(Float, nullable=True)
    is_undone = Column(Boolean, default=False)
    undone_at = Column(DateTime, nullable=True)
    undone_by = Column(String(50), nullable=True)
    # ----
    is_modified = Column(Boolean, default=False)
    modified_at = Column(DateTime)
    modified_by = Column(String(50))
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # 关系
    work_order = relationship("WorkOrder", back_populates="production_reports")
    comments = relationship("ProductionReportComment", back_populates="report")
    
    # 索引
    __table_args__ = (
        Index("idx_pr_work_order_created", "work_order_id", "created_at"),
    )


class ProductionReportComment(Base):
    """生产报工评论表"""
    
    __tablename__ = "production_report_comments"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    report_id = Column(UUID(as_uuid=False), ForeignKey("production_reports.id"), nullable=False, index=True)
    comment = Column(Text, nullable=False)
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # 关系
    report = relationship("ProductionReport", back_populates="comments")


class Product(Base):
    """产品主数据表"""

    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_code = Column(String(50), unique=True, nullable=False, index=True)
    product_name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False, default="default")
    unit = Column(String(20), nullable=False, default="pcs")
    description = Column(String(500))
    status = Column(String(20), nullable=False, default="active")
    standard_cost = Column(Float)
    selling_price = Column(Float)
    current_bom_version = Column(String(20))
    current_routing_id = Column(String(50), nullable=True)
    engineering_lead_time_days = Column(Float, nullable=True)
    manufacturing_lead_time_days = Column(Float, nullable=True)
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Station(Base):
    """工位/产线表"""
    
    __tablename__ = "stations"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    station_code = Column(String(50), nullable=False, index=True)
    station_name = Column(String(100), nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    station_type = Column(String(50), nullable=False)
    workshop_id = Column(String(50))
    capacity_per_hour = Column(Integer, default=0)
    status = Column(String(20), default="active")
    equipment_ids = Column(JSONB, default=list)
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_station_factory_type", "factory_id", "station_type"),
    )


class Routing(Base):
    """工艺路线表"""
    
    __tablename__ = "routings"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    routing_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    version = Column(String(20), default="v1")
    steps = Column(JSONB, nullable=False, default=list)
    is_active = Column(Boolean, default=True)
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_routing_product_version", "product_id", "version"),
    )


class RoutingTemplate(Base):
    """工艺路线模板表（016）"""

    __tablename__ = "routing_templates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    template_code = Column(String(50), unique=True, nullable=False)
    template_name = Column(String(100), nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关系
    steps = relationship("RoutingTemplateStep", back_populates="template", order_by="RoutingTemplateStep.seq", cascade="all, delete-orphan")


class RoutingTemplateStep(Base):
    """工艺路线模板工序步骤（016）"""

    __tablename__ = "routing_template_steps"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    template_id = Column(String(36), ForeignKey("routing_templates.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    process_code = Column(String(20), nullable=False)
    operation_name = Column(String(100), nullable=False)
    work_center = Column(String(20), nullable=True)
    standard_hours = Column(Numeric(8, 2), default=0)
    is_parallel = Column(Boolean, default=False)
    is_qc_gate = Column(Boolean, default=False)
    quality_requirement = Column(Text, nullable=True)
    sop_document_url = Column(String(500), nullable=True)
    tooling_requirement = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 关系
    template = relationship("RoutingTemplate", back_populates="steps")

    __table_args__ = (
        Index("idx_rts_template_seq", "template_id", "seq"),
    )


class AlertIntelligenceReview(Base):
    """AI 预警审查记录（017）—— 每条被动预警触发一条 AI 审查"""

    __tablename__ = "alert_intelligence_reviews"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    alert_source = Column(String(30), nullable=False)      # andon/defect/equipment/wo_timeout/inventory
    alert_ref_id = Column(String(36), nullable=False)      # 关联源记录 ID
    alert_ref_code = Column(String(100), nullable=True)    # 源记录编码
    alert_summary = Column(Text, nullable=False)           # 预警摘要
    severity_assessment = Column(String(20), nullable=True)  # critical/high/medium/low
    root_cause_hypothesis = Column(Text, nullable=True)
    recommended_actions = Column(Text, nullable=True)      # JSON array
    dispatch_recommendation = Column(String(100), nullable=True)
    raw_ai_response = Column(Text, nullable=True)
    status = Column(String(20), default="pending")         # pending/acknowledged/dismissed/acted
    acknowledged_by = Column(String(50), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class TimeStudyRecord(Base):
    """时间研究记录"""
    
    __tablename__ = "time_study_records"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    station_id = Column(String(50), nullable=False, index=True)
    operation_name = Column(String(100), nullable=False)
    operator_id = Column(String(50))
    observer_id = Column(String(50))
    observation_date = Column(DateTime, nullable=False)
    observed_cycles = Column(JSON, default=list)  # 观测周期数据 (JSON)
    cycle_count = Column(Integer)
    average_time = Column(Float)  # 平均时间
    rating_factor = Column(Float)  # 评定系数
    normal_time = Column(Float)  # 正常时间
    allowed_time = Column(Float)  # 允许时间
    allowance_rate = Column(Float)  # 宽放率
    method = Column(String(50))  # 研究方法
    status = Column(String(20))  # 状态 (pending/approved/rejected)
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_factory_product_station", "factory_id", "product_id", "station_id"),
    )


class StandardOperationTime(Base):
    """标准工时记录"""
    
    __tablename__ = "standard_operation_times"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    routing_step = Column(String(50))  # 工艺路线步骤编号
    operation_seq = Column(Integer, nullable=True)
    operation_name = Column(String(100), nullable=False)  # 工序名称
    station_id = Column(String(50))  # 工位编码
    work_center = Column(String(50))  # 加工中心
    standard_time_min = Column(Float)  # 标准工时（分钟）
    unit_time_type = Column(String(20))  # 时间类型（单件/批量等）
    setup_time_min = Column(Float)  # 准备时间（分钟）
    setup_before_start_time_min = Column(Float, nullable=True)
    post_operation_time_min = Column(Float, nullable=True)
    batch_size = Column(Integer)  # 批量数
    rating_factor = Column(Float)  # 速度系数
    allowance_rate = Column(Float)  # 宽放率
    effective_standard_time = Column(Float)  # 有效标准工时
    version = Column(String(20))  # 版本号
    is_active = Column(Boolean, default=True)  # 是否生效
    validity_start = Column(DateTime)  # 生效开始时间
    validity_end = Column(DateTime)  # 失效结束时间
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_factory_product", "factory_id", "product_id"),
        Index("idx_station_factory", "station_id", "factory_id"),
    )


class LineBalanceAnalysis(Base):
    """产线平衡分析记录"""
    
    __tablename__ = "line_balance_analyses"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    line_id = Column(String(50), nullable=False, index=True)
    analysis_date = Column(DateTime, nullable=False)
    takt_time_min = Column(Float)
    cycle_time_max = Column(Float)
    cycle_time_avg = Column(Float)
    balance_rate = Column(Float)
    idle_time_total = Column(Float)
    workstation_count = Column(Integer)
    is_balanced = Column(Boolean, default=False)
    workstation_details = Column(JSON, default=dict)
    bottleneck_station = Column(String(50))
    bottleneck_time = Column(Float)
    recommendations = Column(JSON, default=list)
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProcessAnalysis(Base):
    """工序分析记录"""
    
    __tablename__ = "process_analyses"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    operation_code = Column(String(50), nullable=False, index=True)
    analysis_date = Column(DateTime, nullable=False)
    total_process_time_min = Column(Float)
    va_time_min = Column(Float)
    nva_time_min = Column(Float)
    wait_time_min = Column(Float)
    move_time_min = Column(Float)
    inspect_time_min = Column(Float)
    va_ratio = Column(Float)
    lead_time = Column(Float)
    efficiency_score = Column(Float)
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ActionStudy(Base):
    """动作研究记录"""
    
    __tablename__ = "action_studies"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    operation_name = Column(String(100))
    station_id = Column(String(50))
    operator_id = Column(String(50))
    study_date = Column(DateTime, nullable=False)
    method_type = Column(String(50))
    recorded_by = Column(String(50), nullable=True)
    motions = Column(JSON().with_variant(JSONB, "postgresql"), default=list)
    total_time_cycles = Column(Float, nullable=True)
    analysis_result = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    duration_min = Column(Float)
    energy_consumption = Column(Float)
    fatigue_level = Column(Integer)
    improvement_suggestion = Column(Text)
    motion_analysis_result = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    ergonomic_score = Column(Float, nullable=True)
    recommended_improvement_suggestion = Column(Text, nullable=True)
    is_optimized = Column(Boolean, default=False)
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MethodStudy(Base):
    """方法研究记录"""
    
    __tablename__ = "method_studies"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    original_operation = Column(String(255))
    version = Column(String(20))
    is_basement_method = Column(Boolean, default=False)
    is_optimal_method = Column(Boolean, default=False)
    description = Column(Text)
    old_method_description = Column(Text, nullable=True)
    improved_method_diagram_url = Column(String(500), nullable=True)
    expected_time_saving_calculation_detail = Column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    improved_operation = Column(Text)
    action_sequence = Column(JSON().with_variant(JSONB, "postgresql"), default=list)
    required_resources = Column(JSON().with_variant(JSONB, "postgresql"), default=list)
    setup_time_min = Column(Float, nullable=True)
    cycle_time_min = Column(Float, nullable=True)
    total_standard_time_min = Column(Float, nullable=True)
    validity_start = Column(DateTime, nullable=True)
    validity_end = Column(DateTime, nullable=True)
    approved_by = Column(String(50), nullable=True)
    status = Column(String(20), default="draft")
    expected_time_saving_min = Column(Float)
    cost_impact = Column(Float)
    implementation_status = Column(String(50))
    implementer_id = Column(String(50))
    implementation_date = Column(DateTime)
    verification_result = Column(String(100))
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkCellLayout(Base):
    """工作单元布局"""
    
    __tablename__ = "work_cell_layouts"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    work_cell_id = Column(String(50), nullable=False, index=True)
    product_family_id = Column(String(50))
    layout_diagram_url = Column(String(255))
    material_flow_path = Column(JSON, default=dict)
    operator_movement_path = Column(JSON, default=dict)
    takt_time_alignment = Column(String(50))
    storage_location_type = Column(String(50), nullable=True)
    description = Column(Text)
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KanbanSystem(Base):
    """看板系统"""
    
    __tablename__ = "kanban_systems"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    kanban_id = Column(String(50), nullable=False, index=True)
    kanban_type = Column(String(50))
    upstream_station = Column(String(50))
    downstream_station = Column(String(50))
    product_id = Column(String(50))
    part_number = Column(String(100))
    min_stock_level = Column(Integer)
    max_stock_level = Column(Integer)
    max_card_count = Column(Integer, nullable=True)
    current_card_count = Column(Integer, nullable=True)
    safety_stock_level = Column(Integer, nullable=True)
    card_status = Column(String(20), nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    reorder_quantity = Column(Integer)
    lead_time_days = Column(Integer)
    kanban_card_image_url = Column(String(500), nullable=True)
    trigger_rule_type = Column(String(50), nullable=True)
    min_max_stock_levels_detail = Column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    holder_id = Column(String(50))
    status = Column(String(20), default="active")
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FiveSAudit(Base):
    """5S 审核记录"""
    
    __tablename__ = "five_s_audits"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    work_center_id = Column(String(50), nullable=False, index=True)
    audit_date = Column(DateTime, nullable=False)
    auditor_id = Column(String(50))
    seiri_score = Column(Integer)  # 整理评分
    seiton_score = Column(Integer)  # 整顿评分
    seiso_score = Column(Integer)  # 清扫评分
    seiketsu_score = Column(Integer, nullable=True)
    shitsuke_score = Column(Integer, nullable=True)
    improvement_items = Column(JSON().with_variant(JSONB, "postgresql"), default=list)
    next_audit_date = Column(Date, nullable=True)
    seiketsu_score = Column(Integer)  # 清洁评分
    shitsuke_score = Column(Integer)  # 素养评分
    total_score = Column(Integer)
    improvement_items = Column(JSON, default=list)
    next_audit_date = Column(DateTime)
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ShiftSummary(Base):
    """班次汇总记录"""
    
    __tablename__ = "shift_summaries"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    shift_date = Column(Date, nullable=False)
    shift_type = Column(String(20))  # 白班/夜班/晚班等
    station_id = Column(String(50))
    work_order_id = Column(String(50))
    product_id = Column(String(50))
    total_output = Column(Integer)
    good_qty = Column(Integer)
    defect_qty = Column(Integer)
    scrap_qty = Column(Integer)
    yield_rate = Column(Float)
    target_output = Column(Integer)
    achievement_rate = Column(Float)
    report_count = Column(Integer)
    total_cycle_time = Column(Float)
    operator_count = Column(Integer)
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CodeTable(Base):
    """代码表（字典表）"""
    
    __tablename__ = "code_tables"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    category = Column(String(50), nullable=False, index=True)  # 类别（如 status, type, level 等）
    code = Column(String(50), nullable=False, index=True)  # 代码值
    name = Column(String(100), nullable=False)  # 中文名称
    name_en = Column(String(100))  # 英文名称
    description = Column(Text)  # 描述
    keywords = Column(JSON, default=dict)  # 关键词
    extra = Column(JSON, default=dict)  # 扩展字段
    sort_order = Column(Integer, default=0)  # 排序
    is_active = Column(Boolean, default=True)  # 是否启用
    is_system = Column(Boolean, default=False)  # 是否为系统内置
    factory_id = Column(String(50), index=True)  # 所属工厂（空表示全局）
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Equipment(Base):
    """设备表"""
    
    __tablename__ = "equipment"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    equipment_code = Column(String(50), unique=True, nullable=False)
    equipment_name = Column(String(100), nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    station_id = Column(String(50), index=True)
    equipment_type = Column(String(50))
    manufacturer_model = Column(String(100), nullable=True)
    serial_number = Column(String(100), nullable=True)
    purchase_date = Column(Date, nullable=True)
    warranty_expiry = Column(Date, nullable=True)
    maintenance_interval_days = Column(Integer, nullable=True)
    status = Column(String(20), default="available")
    last_maintenance_date = Column(DateTime)
    next_maintenance_date = Column(DateTime)
    spec = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ============== WMS Models ==============

class Warehouse(Base):
    """仓库表"""
    
    __tablename__ = "warehouses"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    warehouse_code = Column(String(50), unique=True, nullable=False, index=True)
    warehouse_name = Column(String(100), nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    warehouse_type = Column(String(20), nullable=False)  # raw_material, finished_goods, in_transit
    address = Column(String(255))
    status = Column(String(20), default="active")
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_wh_factory_type", "factory_id", "warehouse_type"),
    )


class Location(Base):
    """库位表"""
    
    __tablename__ = "locations"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    location_code = Column(String(50), nullable=False, index=True)
    location_name = Column(String(100))
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    location_type = Column(String(20), default="rack")
    zone = Column(String(50))
    aisle = Column(String(30), nullable=True)
    rack = Column(String(30), nullable=True)
    level = Column(String(30), nullable=True)
    bin_code = Column(String(30), nullable=True)
    capacity = Column(Integer)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_loc_warehouse_zone", "warehouse_id", "zone"),
    )


class Inventory(Base):
    """库存表"""
    
    __tablename__ = "inventory"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    material_id = Column(String(50), nullable=False, index=True)
    material_code = Column(String(50), nullable=False)
    material_name = Column(String(100), nullable=True)
    factory_id = Column(String(50), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False, index=True)
    location_id = Column(String(36), ForeignKey("locations.id"))
    batch_code = Column(String(50), index=True)
    expiry_date = Column(Date, nullable=True)
    storage_location = Column(String(100), nullable=True)
    qualified_status = Column(String(20), default="qualified")
    total_qty = Column(Integer, default=0, nullable=False)
    available_qty = Column(Integer, default=0, nullable=False)
    reserved_qty = Column(Integer, default=0)
    unit_cost = Column(Numeric(10, 2))
    unit = Column(String(20), default="pcs")
    status = Column(String(20), default="available")
    last_movement_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_inv_mat_wh_batch", "material_id", "warehouse_id", "batch_code"),
    )


class InboundOrder(Base):
    """入库单表"""
    
    __tablename__ = "inbound_orders"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    inbound_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False)
    material_id = Column(String(50), nullable=False)
    material_code = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False)
    batch_code = Column(String(50))
    supplier_id = Column(String(50))
    purchase_order_id = Column(String(50))
    unit_cost = Column(Numeric(10, 2))
    location_id = Column(String(36), ForeignKey("locations.id"))
    inbound_type = Column(String(20), default="purchase")
    status = Column(String(20), default="pending")
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime)


class OutboundOrder(Base):
    """出库单表"""
    
    __tablename__ = "outbound_orders"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    outbound_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False)
    material_id = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False)
    work_order_id = Column(String(50), index=True)
    batch_code = Column(String(50))
    outbound_type = Column(String(20), default="production")
    status = Column(String(20), default="pending")
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime)


class InventoryTransaction(Base):
    """库存交易流水表（出入库记录）"""
    
    __tablename__ = "inventory_transactions"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    inventory_id = Column(String(36), ForeignKey("inventory.id"), nullable=False)
    material_id = Column(String(50), nullable=False, index=True)
    batch_code = Column(String(50))
    transaction_type = Column(String(20), nullable=False)  # INBOUND/OUTBOUND/ADJUSTMENT/PRODUCTION_OUT/WIP_TRANSFER etc.
    quantity = Column(Integer, nullable=False)
    before_qty = Column(Integer)
    after_qty = Column(Integer)
    reference_type = Column(String(30))  # e.g., work_order, inbound_order, production_order
    reference_id = Column(String(36))  # reference to related entity
    reference_doc_no = Column(String(100), nullable=True)
    reason_code = Column(String(50), nullable=True)
    operator = Column(String(50))
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationship to WorkOrder (if transaction is linked to a production order)
    work_order_id = Column(String(50), index=True)
    
    __table_args__ = (
        Index("idx_inv_txn_factory", "factory_id"),
        Index("idx_inv_txn_mat", "material_id"),
        Index("idx_inv_txn_batch", "batch_code"),
        Index("idx_inv_txn_date", "created_at"),
        Index("idx_inv_txn_work_order", work_order_id, transaction_type),  # 针对成本核算JOIN的复合索引
    )


# ==================== 员工技能模型 ====================

class Skill(Base):
    """技能库定义"""
    
    __tablename__ = "skills"
    
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50), index=True)
    description = Column(Text)
    is_active = Column(Boolean, default=True)


class EmployeeSkill(Base):
    """员工技能关联表"""
    
    __tablename__ = "employee_skills"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False, index=True)
    level = Column(String(10), nullable=False)  # L1-L5
    certified_date = Column(DateTime)
    expiry_date = Column(DateTime)
    score = Column(Numeric(5, 2))
    training_record_link = Column(String(500), nullable=True)
    competency_assessment_score = Column(Numeric(5, 2), nullable=True)
    skill_level_date = Column(Date, nullable=True)
    remarks = Column(Text)
    evaluated_by = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="skills")
    evaluator = relationship("User", foreign_keys=[evaluated_by])
    skill = relationship("Skill")


class TrainingRecord(Base):
    """培训记录"""
    
    __tablename__ = "training_records"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=False)
    training_type = Column(String(50))
    trainer = Column(String(100))
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime)
    hours = Column(Numeric(5, 2))
    result = Column(String(20))
    certificate_no = Column(String(50))
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    user = relationship("User", backref="training_records")
    skill = relationship("Skill")


class SimERPAuditLog(Base):
    """Sim-ERP 审计日志表"""

    __tablename__ = "sim_erp_audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    simulation_id = Column(String(36), unique=True, nullable=False, index=True)
    worker_ref = Column(String(50), nullable=False, index=True)
    shift_id = Column(String(50), nullable=False, index=True)
    task_type = Column(String(100), nullable=False, index=True)
    zone_id = Column(String(50), nullable=False, index=True)
    final_status = Column(String(20), nullable=False, index=True)
    legal_blocked = Column(Boolean, default=False, nullable=False, index=True)
    total_cost_delta = Column(Numeric(12, 2), default=0)
    max_required_break_minutes = Column(Integer, default=0)
    total_penalty_score = Column(Integer, default=0)
    simulation_input_hash = Column(String(64), nullable=False, index=True)
    physics_core_version = Column(String(20), nullable=False)
    plugin_manifest_hash = Column(String(256), nullable=False)
    legislation_pack_hash = Column(String(256), nullable=False)
    arbiter_version = Column(String(20), nullable=False)
    optimizer_version = Column(String(50), default="manual")
    snapshot_payload = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    plugin_records_payload = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    arbiter_result_payload = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_sim_erp_status_created", "final_status", "created_at"),
        Index("idx_sim_erp_worker_shift", "worker_ref", "shift_id"),
    )


# ============== TMS (Task Management System) Models ==============

class TMSTask(Base):
    """TMS 任务表 - 任务分发核心"""

    __tablename__ = "tms_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_code = Column(String(50), unique=True, nullable=False, index=True)  # TASK-2026-00001
    title = Column(String(200), nullable=False)
    description = Column(Text)
    task_type = Column(String(50), nullable=False, index=True)  # ecn_release, ecr_approval, inspection, custom
    source = Column(String(50), default="manual")  # manual, system, agent, api
    priority = Column(String(20), default="medium", index=True)  # low, medium, high, urgent
    points = Column(Integer, default=0)  # 积分激励

    # 分发相关（核心字段）
    status = Column(String(30), default="pending_distribution", index=True)
    # pending_distribution -> distributed -> claimed -> in_progress -> pending_approval -> completed / rejected
    distribution_strategy = Column(String(50))  # skill_match, load_balance, round_robin, manual, agent_decide
    assigned_to = Column(String(36), nullable=True, index=True)
    assigned_by = Column(String(100))  # user_id 或 "agent:xxx"
    candidate_pool = Column(JSON().with_variant(JSONB, "postgresql"), default=list)  # 候选人列表
    required_skills = Column(JSON().with_variant(JSONB, "postgresql"), default=list)  # 所需技能标签
    required_roles = Column(JSON().with_variant(JSONB, "postgresql"), default=list)  # 所需角色
    deadline = Column(DateTime)

    # 审批关联
    approval_flow_id = Column(String(36), nullable=True)

    # Agent 元数据
    agent_context = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)  # Agent 可读写上下文
    metadata_ = Column("metadata", JSON().with_variant(JSONB, "postgresql"), default=dict)  # 扩展字段

    # 关联
    related_work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=True)

    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关系
    distribution_logs = relationship("TMSDistributionLog", back_populates="task")
    approval_flow = relationship("TMSApprovalFlow", back_populates="task", uselist=False)

    __table_args__ = (
        Index("idx_tms_task_status_priority", "status", "priority"),
        Index("idx_tms_task_type_status", "task_type", "status"),
        Index("idx_tms_task_assigned", "assigned_to", "status"),
    )


class TMSApprovalFlow(Base):
    """TMS 审批流表"""

    __tablename__ = "tms_approval_flows"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    flow_code = Column(String(50), unique=True, nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("tms_tasks.id"), nullable=False, index=True)
    flow_type = Column(String(50), nullable=False, default="sequential")  # sequential, parallel, conditional
    steps = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)  # 审批步骤定义
    current_step = Column(Integer, default=0)
    status = Column(String(30), default="active", index=True)  # active, approved, rejected, cancelled
    initiated_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # 关系
    task = relationship("TMSTask", back_populates="approval_flow")
    records = relationship("TMSApprovalRecord", back_populates="flow", order_by="TMSApprovalRecord.created_at")


class TMSApprovalRecord(Base):
    """TMS 审批记录表"""

    __tablename__ = "tms_approval_records"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    flow_id = Column(String(36), ForeignKey("tms_approval_flows.id"), nullable=False, index=True)
    step_index = Column(Integer, nullable=False)
    approver_id = Column(String(36), nullable=True)
    action = Column(String(20), nullable=False)  # approve, reject, delegate, escalate
    comment = Column(Text)
    acted_by = Column(String(100), nullable=False)  # "user:xxx" 或 "agent:chatbot-01"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 关系
    flow = relationship("TMSApprovalFlow", back_populates="records")

    __table_args__ = (
        Index("idx_tms_approval_flow_step", "flow_id", "step_index"),
    )


class TMSDistributionLog(Base):
    """TMS 分发日志表 - 可审计"""

    __tablename__ = "tms_distribution_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("tms_tasks.id"), nullable=False, index=True)
    strategy = Column(String(50), nullable=False)
    candidate_scores = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)  # 各候选人评分
    selected_user_id = Column(String(36), nullable=True)
    reason = Column(Text)  # 分发决策理由
    triggered_by = Column(String(100), nullable=False)  # "system" / "agent:xxx" / "user:xxx"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # 关系
    task = relationship("TMSTask", back_populates="distribution_logs")


class TMSAgentAction(Base):
    """TMS Agent 操作日志 - 全量审计"""

    __tablename__ = "tms_agent_actions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    agent_id = Column(String(100), nullable=False, index=True)  # chatbot/agent 标识
    action_type = Column(String(50), nullable=False, index=True)  # assign, approve, escalate, reassign, query, create_task
    target_task_id = Column(String(36), ForeignKey("tms_tasks.id"), nullable=True)
    payload = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)  # 命令参数
    result = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)  # 执行结果
    status = Column(String(20), default="success", index=True)  # success, failed, pending_confirmation
    requires_confirmation = Column(Boolean, default=False)  # 高危操作需人工确认
    idempotency_key = Column(String(100), unique=True, nullable=True, index=True)  # 幂等键
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_tms_agent_action_type", "agent_id", "action_type"),
    )

class TMSWebhookSubscription(Base):
    """TMS Webhook 订阅表 - Agent 事件推送"""

    __tablename__ = "tms_webhook_subscriptions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    agent_id = Column(String(100), nullable=False, index=True)
    event_types = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)  # 订阅事件类型
    webhook_url = Column(String(500), nullable=False)
    secret = Column(String(100))  # 签名密钥
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ==================== v2.5 Data Consistency Models ====================

class DefectRecord(Base):
    """缺陷记录表 — 与报工原子关联，支持不良品闭环"""

    __tablename__ = "defect_records"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    record_code = Column(String(50), unique=True, nullable=False, index=True)
    factory_id = Column(String(50), nullable=False, index=True)
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=True, index=True)
    production_report_id = Column(String(36), ForeignKey("production_reports.id"), nullable=True, index=True)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True, index=True)
    material_id = Column(String(50), nullable=True, index=True)
    batch_code = Column(String(50), nullable=True, index=True)
    station_id = Column(String(50), nullable=True, index=True)
    equipment_id = Column(String(36), ForeignKey("equipment.id"), nullable=True, index=True)
    defect_type = Column(String(50), nullable=False)      # appearance/dimension/function/performance/material/process/other
    defect_classification = Column(String(50), nullable=True)
    failure_mode = Column(String(100), nullable=True)
    rpn_value = Column(Integer, nullable=True)
    corrective_action_link = Column(String(500), nullable=True)
    severity = Column(String(20), nullable=False, default="minor")  # critical/major/minor/observation
    quantity = Column(Integer, nullable=False, default=0)
    disposition = Column(String(20), nullable=True)        # rework/repair/scrap/concession/return
    disposition_by = Column(String(50), nullable=True)
    disposition_at = Column(DateTime, nullable=True)
    disposition_remark = Column(Text, nullable=True)
    ocap_status = Column(String(20), default="pending", index=True)  # pending/triggered/in_progress/completed
    description = Column(Text, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    is_finalized = Column(Boolean, default=False, index=True)

    # 品质追溯字段
    defect_source = Column(String(30), nullable=True)          # incoming/process/design/operation/environment/customer
    root_cause_category = Column(String(30), nullable=True)    # 5M1E: material/method/machine/man/environment/measurement
    root_cause = Column(Text, nullable=True)                   # 根因描述
    responsible_dept = Column(String(30), nullable=True)       # QA/production/purchasing/engineering/vendor
    discovery_stage = Column(String(20), nullable=True)        # IQC/IPQC/FQC/OQC/customer
    discovery_time = Column(DateTime, nullable=True)           # 发现时间
    defect_location = Column(String(200), nullable=True)       # 缺陷位置
    inspection_id = Column(String(36), nullable=True)          # 关联检验单
    corrective_action = Column(Text, nullable=True)            # 纠正措施
    preventive_action = Column(Text, nullable=True)            # 预防措施
    process_step = Column(String(50), nullable=True)           # 工序名称
    review_status = Column(String(20), default="pending")      # pending/under_review/reviewed/closed
    reviewed_by = Column(String(50), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_dr_factory_batch", "factory_id", "batch_code"),
        Index("idx_dr_disposition_severity", "disposition", "severity"),
    )

    # 关系
    work_order = relationship("WorkOrder")
    production_report = relationship("ProductionReport")
    product = relationship("Product")
    station_obj = relationship("Station", primaryjoin="foreign(DefectRecord.station_id) == Station.station_code", viewonly=True)
    equipment_obj = relationship("Equipment")


class ItemTraceability(Base):
    """一物一码追溯链 — 正反向全链路追溯"""

    __tablename__ = "item_traceability"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    item_code = Column(String(50), unique=True, nullable=False)
    item_type = Column(String(20), default="finished", index=True)  # raw_material/semi_finished/finished
    factory_id = Column(String(50), nullable=False, index=True)
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=True, index=True)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True, index=True)
    material_batch_id = Column(String(50), nullable=True, index=True)
    material_supplier_id = Column(String(50), nullable=True)
    station_id = Column(String(50), nullable=True, index=True)
    equipment_id = Column(String(36), ForeignKey("equipment.id"), nullable=True)
    operator_id = Column(String(50), nullable=True, index=True)
    quality_check_result = Column(String(20), nullable=True)  # pass/fail/rework_pass
    serial_number = Column(String(50), nullable=True, index=True)
    next_item_code = Column(String(36), ForeignKey("item_traceability.item_code"), nullable=True)
    inspection_record_id = Column(String(36), nullable=True)
    metadata_ = Column("metadata", JSON().with_variant(JSONB, "postgresql"), default=dict)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_it_work_order", "work_order_id"),
        Index("idx_it_factory_product", "factory_id", "product_id"),
    )


class ReconciliationLog(Base):
    """自动对账日志 — 生产报工 vs 工单进度 vs 库存增量"""

    __tablename__ = "reconciliation_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    reconcile_code = Column(String(50), unique=True, nullable=False, index=True)
    factory_id = Column(String(50), nullable=False, index=True)
    work_order_id = Column(UUID(as_uuid=False), ForeignKey("work_orders.id"), nullable=True, index=True)
    planned_qty = Column(Integer, nullable=False, default=0)
    good_qty = Column(Integer, nullable=False, default=0)
    defect_qty = Column(Integer, nullable=False, default=0)
    scrap_qty = Column(Integer, nullable=False, default=0)
    net_change = Column(Integer, nullable=False, default=0)
    expected_delta = Column(Integer, nullable=False, default=0)
    delta = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="ok", index=True)  # ok/mismatch/investigating
    discrepancy_detail = Column(Text, nullable=True)
    checked_by = Column(String(50), default="auto_reconciler")
    checked_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_rl_factory_date", "factory_id", "checked_at"),
        Index("idx_rl_work_order", "work_order_id", "status"),
    )


class ReplenishmentThreshold(Base):
    """Min-Max 线边仓水位模型"""

    __tablename__ = "replenishment_thresholds"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=True)
    location_id = Column(String(36), ForeignKey("locations.id"), nullable=True)
    material_id = Column(String(50), nullable=False, index=True)
    min_level = Column(Integer, nullable=False, default=0)
    max_level = Column(Integer, nullable=False, default=0)
    safety_stock = Column(Integer, nullable=False, default=0)
    reorder_lot_size = Column(Integer, nullable=False, default=1)
    reorder_lead_time_hours = Column(Float, default=24.0)
    line_side_location = Column(String(50), nullable=True)
    active = Column(Boolean, default=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("factory_id", "material_id", "line_side_location", name="uq_rt_factory_mat_loc"),
    )


class PullReplenishmentTask(Base):
    """拉动式补货任务"""

    __tablename__ = "pull_replenishment_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_code = Column(String(50), unique=True, nullable=False, index=True)
    factory_id = Column(String(50), nullable=False, index=True)
    source_warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=True)
    target_location_id = Column(String(36), ForeignKey("locations.id"), nullable=True)
    material_id = Column(String(50), nullable=False, index=True)
    requested_qty = Column(Integer, nullable=False, default=0)
    fulfilled_qty = Column(Integer, nullable=False, default=0)
    status = Column(String(20), default="pending", index=True)  # pending/approved/picking/delivering/completed/cancelled
    trigger_type = Column(String(20), default="min_reached")
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=True)
    threshold_id = Column(String(36), ForeignKey("replenishment_thresholds.id"), nullable=True)
    assigned_to = Column(String(50), nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_prt_factory_status", "factory_id", "status"),
    )


# ============================================================
# QMS 检验模型
# ============================================================


class QualityDefect(Base):
    """质量缺陷记录 - 记录每次检验中发现的具体缺陷"""
    
    __tablename__ = "quality_defects"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    inspection_id = Column(UUID(as_uuid=True), ForeignKey("quality_inspections.id"), nullable=False)  # 关联的检验记录
    
    # 缺陷信息
    defect_code = Column(String(50))  # 缺陷编码（如 CRITICAL, MAJOR, MINOR）
    defect_category = Column(String(50))  # 缺陷类别（尺寸、外观、功能等）
    defect_description = Column(Text)  # 缺陷描述
    
    # 涉及的工序（如果是生产过程中的缺陷）
    operation_seq = Column(Integer)  # 工序序号
    station_id = Column(String(50))  # 工站ID
    
    quantity = Column(Integer, default=1)  # 涉及数量
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_inspection_id", "inspection_id"),
    )


class CAPACase(Base):
    """CAPA纠正预防行动计划"""
    
    __tablename__ = "capa_cases"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_number = Column(String(50), unique=True, nullable=False)  # CAPA编号（如 CAPA-2026-001）
    
    # 问题来源：可以关联到具体的质量检验记录
    
    # 问题描述
    problem_description = Column(Text, nullable=True)  # 问题描述
    discovery_date = Column(DateTime, default=datetime.utcnow)  # 发现日期
    
    # 分类
    defect_severity = Column(String(20))  # "critical", "major", "minor"
    root_cause = Column(Text)  # 根本原因分析
    
    # 行动计划（纠正措施 + 预防措施）
    corrective_action = Column(Text)  # 纠正措施（消除已发生的问题）
    preventive_action = Column(Text)  # 预防措施（防止再次发生）
    
    # 责任人
    assigned_to = Column(String(50))  # 负责人
    deadline = Column(DateTime)  # 截止日期
    
    # 状态流转
    status = Column(String(20), default="open")  # "open", "in_progress", "verified", "closed"
    effectiveness_check_date = Column(DateTime, nullable=True)
    verification_result = Column(Text, nullable=True)
    preventive_scope = Column(Text, nullable=True)
    
    # 执行记录
    action_logs = Column(JSONB, default=list)  # [{"status": "...", "at": "...", "by": "...", "notes": "..."}]
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    

    # ==================== CAPA 增强字段（5Why分析 + 鱼骨图 + 效果验证）====================

    # 5Why层层追问记录（最多5层）
    why_analysis = Column(JSONB, default={})  # {"why1": "...", "why2": "...", ..., "root_cause": "..."}
    
    # 鱼骨图（石川图）- 维度分类
    fishbone_dimensions = Column(JSONB, default={"man": [], "machine": [], "material": [], "method": [], "measurement": [], "environment": []})
    
    # 临时遏制措施（D3）详细说明
    interim_actions_detailed = Column(JSONB, default={})  # {"description": "...", "owner": "...", "deadline": "...", "status": "..."}
    
    # D5永久纠正措施的详细行动计划列表
    corrective_action_plans = Column(JSONB, default=[])  # [{"action": "", "owner": "", "deadline": "", "status": "", "completion_pct": 0}]
    
    # D6效果验证结果
    verification_results = Column(JSONB, default={})  # {"before": {...}, "after": {...}, "improved": bool, "verified_by": ""}
    
    # D7预防措施文档更新
    preventive_updates = Column(JSONB, default={})   # {"sop_updated": bool, "documents_changed": [], "training_conducted": bool}
    
    # D8经验教训及标准化建议
    lessons_learned_doc = Column(Text)  # 更长的文本字段用于存储经验总结
    __table_args__ = (
        Index("idx_case_number", "case_number", unique=True),
        Index("idx_status", "status"),
    )


class QualityCost(Base):
    """质量成本（COQ）核算记录"""
    
    __tablename__ = "quality_costs"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    
    # 成本类别
    
    # 关联的检验或CAPA事件
    related_capa_id = Column(UUID(as_uuid=True), ForeignKey("capa_cases.id"))
    
    # 金额
    amount = Column(Numeric(15, 2), nullable=False)  # 金额
    currency = Column(String(3), default="CNY")  # 货币单位
    
    # 日期
    cost_date = Column(DateTime, default=datetime.utcnow)  # 成本发生日期
    
    # 描述
    description = Column(Text)  # 成本说明（如返工成本、退货损失等）
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_cost_date", "cost_date"),
    )


# ==================== APS 排程模型 ====================

class ApsSchedule(Base):
    """排程计划"""
    __tablename__ = "aps_schedules"
    __table_args__ = {"extend_existing": True}

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50))
    status = Column(String(20))
    schedule_code = Column(String(50))
    mode = Column(String(20), default="hybrid")
    optimize_for = Column(String(20), default="delivery")
    priority_level = Column(String(20), nullable=True)
    constraint_type = Column(String(50), nullable=True)
    feasibility_status = Column(String(20), nullable=True)
    horizon_start = Column(DateTime)
    horizon_end = Column(DateTime)
    on_time_rate = Column(Float)
    avg_utilization = Column(Float)
    total_setup_minutes = Column(Float)
    avg_cycle_hours = Column(Float)
    total_tasks = Column(Integer, default=0)
    unscheduled_count = Column(Integer, default=0)
    created_by = Column(String(50))
    confirmed_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)


class ApsScheduleTask(Base):
    """排程任务明细"""
    __tablename__ = "aps_schedule_tasks"
    __table_args__ = {"extend_existing": True}

    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    schedule_id = Column(UUID(as_uuid=False))
    station_id = Column(String(50))
    planned_start = Column(DateTime)
    planned_end = Column(DateTime)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)
    deviation_reason = Column(Text, nullable=True)
    status = Column(String(20))
    setup_minutes = Column(Float, default=0)
    material_ready = Column(Boolean, default=True)
    sequence_in_station = Column(Integer)
    work_order_id = Column(String(36))
    order_code = Column(String(50))
    product_code = Column(String(50))
    operation_seq = Column(Integer, default=0)
    operation_name = Column(String(100))
    setup_seconds = Column(Float, default=0)
    run_seconds = Column(Float, default=0)
    quantity = Column(Integer, default=0)
    is_locked = Column(Boolean, default=False)
    priority = Column(Integer, default=5)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApsWorkCalendar(Base):
    """工作日历"""
    __tablename__ = "aps_work_calendars"
    __table_args__ = {"extend_existing": True}

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False)
    resource_id = Column(String(50), nullable=False)
    resource_type = Column(String(20), default="station")
    shift_name = Column(String(50), default="标准班")
    day_of_week = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_active = Column(Boolean, default=True)
    effective_from = Column(Date)
    effective_to = Column(Date)


# ==================== EngHub BOM 同步表 ====================

class BomItem(Base):
    """映射 EngFlow bom_items 源表（只读查询用）"""
    __tablename__ = "bom_items"
    __table_args__ = {"extend_existing": True}

    row_id = Column(BigInteger, primary_key=True)
    company_id = Column(String(50))
    product_sap_code = Column(String(100))
    level = Column(Integer)
    part_number = Column(String(100))
    description = Column(Text)
    quantity = Column(Float)
    unit = Column(String(20))
    unit_price = Column(Float)
    total_cost = Column(Float)
    vendor_code = Column(String(50))
    vendor_name = Column(String(255))
    parent_sap = Column(String(100))
    model_name = Column(String(100))
    # EngHub 扩展字段
    id = Column(String(36))
    factory_id = Column(String(50))
    product_id = Column(String(50))
    bom_version = Column(String(50))
    material_code = Column(String(50))
    material_name = Column(String(100))
    qty_per_unit = Column(Float, default=1)
    remark = Column(String(255))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

class EngHubBomItem(Base):
    """EngHub 本地 BOM 缓存（从 EngFlow bom_items 同步）"""
    __tablename__ = "enghub_bom_items"

    id = Column(Integer, primary_key=True, index=True)
    source_row_id = Column(BigInteger, unique=True, index=True)  # 对应 bom_items.row_id
    product_model = Column(String(100), index=True)              # model_name
    part_number = Column(String(100), index=True)
    description = Column(Text)
    level = Column(Integer)
    quantity = Column(Float)
    unit = Column(String(20))
    unit_price = Column(Float)
    total_cost = Column(Float)
    vendor_code = Column(String(50))
    vendor_name = Column(String(255))
    parent_part = Column(String(100), index=True)                # parent_sap
    category_l1 = Column(String(100))
    category_l2 = Column(String(100))
    material_family = Column(String(100))                        # from part_master
    component_type = Column(String(100))
    synced_at = Column(DateTime, default=datetime.utcnow)
    source_updated_at = Column(DateTime)                         # 源表 updated_at 快照

    __table_args__ = (
        Index("idx_enghub_bom_model_part", "product_model", "part_number"),
    )


class QmsInspectionItem(Base):
    """QMS检验项记录"""
    
    __tablename__ = "qms_inspection_items"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    inspection_id = Column(String(50), nullable=False, index=True)  # 检验单ID
    item_name = Column(String(100))  # 检验项目名称
    item_code = Column(String(50))  # 检验项目编码
    spec_lower = Column(Float)  # 规格下限
    spec_upper = Column(Float)  # 规格上限
    target_value = Column(Float)  # 目标值
    measured_value = Column(Float)  # 实测值
    result = Column(String(20))  # 检验结果（合格/不合格等）
    measurement_method = Column(String(100))  # 测量方法
    remark = Column(Text)  # 备注
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class QualityGoal(Base):
    """质量目标"""
    
    __tablename__ = "quality_goals"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50))
    metric_type = Column(String(50))  # 不良率、一次合格率等
    target_value = Column(Float)
    actual_value = Column(Float)
    period = Column(String(20))  # 日/周/月
    status = Column(String(20), default="active")  # active/archived
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class QualityGoalReview(Base):
    """质量目标评审记录"""
    
    __tablename__ = "quality_goal_reviews"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    goal_id = Column(String(36), nullable=False)
    review_date = Column(DateTime, nullable=False)
    reviewer = Column(String(50))
    comments = Column(Text)
    approved = Column(Boolean, default=False)
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class QmsSpcPoint(Base):
    """SPC控制图数据点"""
    
    __tablename__ = "qms_spc_points"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    characteristic_code = Column(String(50), nullable=False, index=True)  # 特征码
    characteristic_name = Column(String(100))  # 特征名称
    control_chart_type = Column(String(30), nullable=True)
    calculation_method = Column(String(50), nullable=True)
    subgroup_count = Column(Integer, nullable=True)
    work_order_id = Column(String(50))  # 关联工单
    station_id = Column(String(50))  # 工位
    measured_value = Column(Float)  # 测量值
    sample_group = Column(Integer)  # 样本组号
    ucl = Column(Float)  # 上控制限
    lcl = Column(Float)  # 下控制限
    cl = Column(Float)  # 中心线
    is_out_of_control = Column(Boolean, default=False)  # 是否失控
    measured_at = Column(DateTime, nullable=False)  # 测量时间
    measured_by = Column(String(50))  # 测量人
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProcessCapability(Base):
    """工序能力分析"""
    
    __tablename__ = "process_capability"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    station_id = Column(String(50), nullable=False, index=True)
    operation_name = Column(String(100))  # 工序名称
    characteristic = Column(String(100))  # 特性名称
    specification_min = Column(Float)  # 规格下限
    specification_max = Column(Float)  # 规格上限
    mean_value = Column(Float)  # 均值
    standard_deviation = Column(Float)  # 标准差
    cp = Column(Float)  # 工序能力指数
    cpk = Column(Float)  # 工序能力潜力指数
    sampling_size = Column(Integer)  # 抽样数量
    sample_date = Column(DateTime, nullable=False)
    status = Column(String(20), default="analyzed")  # analyzed/pending
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InventoryCountItem(Base):
    """库存盘点明细记录"""
    
    __tablename__ = "inventory_count_items"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    count_id = Column(String(50), nullable=False)  # 盘点单ID
    inventory_id = Column(String(36))  # 关联库存物料ID（Inventory.id）
    material_id = Column(String(50))  # 物料ID
    batch_code = Column(String(50))  # 批次号
    system_qty = Column(Integer)  # 系统数量
    counted_qty = Column(Integer)  # 实际盘点数量
    diff_qty = Column(Integer)  # 差异数量（counted - system）
    adjusted = Column(Boolean, default=False)  # 是否已调整
    remark = Column(String(255))  # 备注
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProductionAlert(Base):
    """生产告警记录"""
    
    __tablename__ = "production_alerts"
    
    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)  # 工厂
    alert_type = Column(String(50))  # 告警类型（缺料/设备故障/质量异常等）
    severity = Column(String(20))  # 严重程度（critical/high/medium/low）
    title = Column(String(255))  # 标题
    message = Column(Text)  # 详细信息
    source_type = Column(String(50))  # 来源类型（equipment/work_order/quality等）
    source_id = Column(String(36))  # 来源ID
    metric_value = Column(Float)  # 指标值
    threshold_value = Column(Float)  # 阈值
    is_read = Column(Boolean, default=False)  # 是否已读
    is_resolved = Column(Boolean, default=False)  # 是否已解决
    resolved_by = Column(String(50))  # 解决人
    resolved_at = Column(DateTime)  # 解决时间
    triggered_at = Column(DateTime, nullable=False)  # 触发时间
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EquipmentDowntime(Base):
    """设备停机记录"""
    
    __tablename__ = "equipment_downtime"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    equipment_id = Column(String(50))  # 设备ID
    factory_id = Column(String(50), nullable=False, index=True)  # 工厂
    start_time = Column(DateTime, nullable=False)  # 开始时间
    end_time = Column(DateTime)  # 结束时间
    duration_minutes = Column(Float)  # 停机分钟数
    downtime_category = Column(String(50))  # 停机类别（故障/维护/缺料等）
    reason_code = Column(String(50))  # 原因代码
    description = Column(Text)  # 描述
    reported_by = Column(String(50))  # 报告人
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MaintenanceOrder(Base):
    """维修工单"""
    
    __tablename__ = "maintenance_orders"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_code = Column(String(50), unique=True, nullable=False)  # 工单编号
    equipment_id = Column(String(50), nullable=False)  # 设备ID
    factory_id = Column(String(50), nullable=False, index=True)  # 工厂
    order_type = Column(String(50))  # 工单类型（预防性/ corrective/紧急）
    priority = Column(String(20), default="normal")  # 优先级
    status = Column(String(20), default="pending")  # 状态（pending/in progress/completed/canceled）
    scheduled_start = Column(DateTime)  # 计划开始时间
    scheduled_end = Column(DateTime)  # 计划结束时间
    actual_start = Column(DateTime)  # 实际开始时间
    actual_end = Column(DateTime)  # 实际结束时间
    description = Column(Text)  # 描述
    assigned_to = Column(String(50))  # 负责人
    parts_used = Column(JSON().with_variant(JSONB, "postgresql"), default=list)
    labor_hours = Column(Float, nullable=True)
    cost_analysis = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    failure_root_cause_code = Column(String(50), nullable=True)
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MaintenancePlan(Base):
    """维修计划"""
    
    __tablename__ = "maintenance_plans"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    plan_code = Column(String(50), unique=True, nullable=False)  # 计划编号
    equipment_id = Column(String(50), nullable=False)  # 设备ID
    factory_id = Column(String(50), nullable=False, index=True)  # 工厂
    plan_type = Column(String(50))  # 计划类型（daily/weekly/monthly/yearly）
    frequency = Column(String(50))  # 频率
    next_run_date = Column(Date)  # 下次运行日期
    last_run_date = Column(Date)  # 上次运行日期
    description = Column(Text)  # 描述
    is_active = Column(Boolean, default=True)  # 是否启用
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Notification(Base):
    """通知记录"""
    
    __tablename__ = "notifications"
    
    id = Column(UUID(as_uuid=False), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)  # 工厂
    title = Column(String(255), nullable=False)  # 标题
    content = Column(Text)  # 内容
    severity = Column(String(20))  # 严重程度
    category = Column(String(50))  # 类别
    recipient = Column(String(50))  # 接收人
    is_read = Column(Boolean, default=False)  # 是否已读
    source_type = Column(String(50), nullable=True)
    source_id = Column(String(100), nullable=True)
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HourlyOutputSnapshot(Base):
    """小时产出快照"""
    
    __tablename__ = "hourly_output_snapshots"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)  # 工厂
    snapshot_date = Column(Date, nullable=False)  # 日期
    snapshot_hour = Column(Integer, nullable=False)  # 小时
    station_id = Column(String(50), nullable=False, index=True)  # 工位
    output_qty = Column(Integer)  # 总产出
    good_qty = Column(Integer)  # 良品数
    defect_qty = Column(Integer)  # 不良品数
    target_qty = Column(Integer)  # 目标产量
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InventoryCount(Base):
    """库存盘点记录"""
    
    __tablename__ = "inventory_counts"
    """库存盘点记录"""
    
    __tablename__ = "inventory_counts"
    """库存盘点记录"""
    
    __tablename__ = "inventory_counts"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    count_code = Column(String(50), nullable=False, unique=True)  # 盘点单号
    factory_id = Column(String(50), nullable=False, index=True)  # 工厂
    warehouse_id = Column(String(50))  # 仓库
    count_type = Column(String(20))  # 盘点类型（日常/月度/年度等）
    status = Column(String(20), default="planned")  # 计划/执行中/已完成/待审核
    planned_date = Column(Date)  # 计划盘点日期
    counted_by = Column(String(50))  # 盘点人
    approved_by = Column(String(50))  # 审核人
    total_items = Column(Integer)  # 总物品数
    diff_items = Column(Integer)  # 差异物品数
    total_diff_qty = Column(Integer)  # 差异总数量
    remark = Column(Text)  # 备注
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SpcConfig(Base):
    """SPC配置"""
    """SPC配置"""
    
    __tablename__ = "spc_configs"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50))
    station_id = Column(String(50))
    characteristic_code = Column(String(50), nullable=False, index=True)
    sample_size = Column(Integer, default=5)  # 子组大小
    sample_interval = Column(Integer, nullable=False)  # 采样间隔（分钟）
    control_rule = Column(String(50), default="westgard")  # 判异规则
    is_active = Column(Boolean, default=True)
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Qms8dReport(Base):
    
    __tablename__ = "qms_8d_reports"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    report_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    defect_record_id = Column(String(36))  # 关联缺陷记录ID
    title = Column(String(255), nullable=False)  # 标题
    severity = Column(String(20))  # 严重程度
    status = Column(String(20), default="open")  # 状态
    d1_team = Column(Text)  # D1团队描述
    d2_problem_description = Column(Text)  # D2问题描述
    d3_containment_action = Column(Text)  # D3遏制措施
    d4_root_cause = Column(Text)  # D4根本原因
    d5_corrective_action = Column(Text)  # D5纠正措施
    d6_implementation = Column(Text)  # D6实施情况
    d7_preventive_action = Column(Text)  # D7预防措施
    d8_congratulations = Column(Text)  # D8表彰/总结经验
    opened_by = Column(String(50))
    closed_by = Column(String(50))
    due_date = Column(DateTime)
    
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(50))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EngHubBomSyncLog(Base):
    """BOM 同步日志"""
    __tablename__ = "enghub_bom_sync_log"

    id = Column(Integer, primary_key=True, index=True)
    sync_type = Column(String(20))       # full / incremental
    status = Column(String(20))          # running / success / failed
    records_synced = Column(Integer, default=0)
    watermark = Column(DateTime)         # 同步水位线（源表最大 updated_at）
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    error_message = Column(Text)
