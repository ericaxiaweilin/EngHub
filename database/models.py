"""
Database Models - SQLAlchemy ORM Models
数据库模型定义
"""
from datetime import datetime, timedelta
from sqlalchemy import (
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


def generate_uuid():
    """生成 UUID"""
    return str(uuid.uuid4())


# ============================================================
# 权限与角色模型（新增）
# ============================================================

class Role(Base):
    """角色表 - 存储 MES 系统预定义角色"""

    __tablename__ = "roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False, index=True)
    permission_id = Column(UUID(as_uuid=True), ForeignKey("permissions.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_role_perm_role_perm", "role_id", "permission_id", unique=True),
    )


class User(Base):
    """用户表"""
    
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
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
    
    # 关系
    role_obj = relationship("Role", back_populates="users", foreign_keys=[role_id])
    user_roles = relationship("UserRole", back_populates="user_obj", foreign_keys="UserRole.user_id")
    
    __table_args__ = (
        Index("idx_user_factory_role", "factory_id", "role"),
    )


class WorkOrder(Base):
    """生产工单表"""
    
    __tablename__ = "work_orders"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
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
    bom_version = Column(String(50))
    # ---- 工单体系化编码：层级字段（主工单 <-> 工序工单）----
    parent_work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=True, index=True)
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


class WoStatusLog(Base):
    """工单状态操作日志（审核追溯：谁/什么角色/何时/做了什么）"""
    __tablename__ = "wo_status_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=False, index=True)
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


class ProductionReport(Base):
    """生产报工表"""
    
    __tablename__ = "production_reports"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    report_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=False, index=True)
    station_id = Column(String(50), nullable=False, index=True)
    good_qty = Column(Integer, nullable=False, default=0)
    defect_qty = Column(Integer, default=0)
    scrap_qty = Column(Integer, default=0)
    report_type = Column(String(20), default="normal")
    shift = Column(String(20), default="day")
    operator_id = Column(String(50))
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
    report_id = Column(String(36), ForeignKey("production_reports.id"), nullable=False, index=True)
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


class Equipment(Base):
    """设备表"""
    
    __tablename__ = "equipment"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    equipment_code = Column(String(50), unique=True, nullable=False)
    equipment_name = Column(String(100), nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    station_id = Column(String(50), index=True)
    equipment_type = Column(String(50))
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
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=True, index=True)
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


class QualityInspection(Base):
    """质量检验记录表"""
    __tablename__ = "quality_inspections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=False, index=True)
    routing_step_id = Column(String(36), nullable=False, index=True)
    inspect_type = Column(String(20), nullable=False)  # IQC/IPQC/FQC/OQC
    inspector_id = Column(String(50), nullable=False)
    sample_qty = Column(Integer, nullable=False, default=0)
    defect_qty = Column(Integer, nullable=False, default=0)
    result = Column(String(20), nullable=False)  # PASS/FAIL/PENDING
    defect_details = Column(JSON, nullable=True)
    remark = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    work_order = relationship("WorkOrder")


# ============================================================
# PP 生产计划模型
# ============================================================


class Plan(Base):
    """生产计划表"""
    __tablename__ = "plans"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    plan_code = Column(String(50), unique=True, nullable=False, index=True)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    sales_order_id = Column(String(50), nullable=True)
    quantity = Column(Integer, nullable=False)
    required_date = Column(DateTime, nullable=False)
    plan_type = Column(String(20), nullable=False, default="mps")
    customer_level = Column(String(10), nullable=False, default="b")
    priority = Column(Integer, nullable=False, default=50)
    status = Column(String(20), nullable=False, default="draft")
    due_date = Column(DateTime, nullable=True)
    priority_score = Column(Float, nullable=False, default=0.0)
    confirmed_by = Column(String(50), nullable=True)
    confirmed_at = Column(DateTime, nullable=True)
    released_by = Column(String(50), nullable=True)
    released_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(50), nullable=True)


class BomItem(Base):
    """BOM 物料清单表（MRP 计算前置：产品→物料用量）"""
    __tablename__ = "bom_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)   # 对应 products.id
    bom_version = Column(String(50), nullable=False)              # 对应 products.current_bom_version
    material_code = Column(String(50), nullable=False, index=True)  # 对应 inventory.material_code
    material_name = Column(String(100), nullable=True)
    qty_per_unit = Column(Float, nullable=False, default=1.0)     # 单位产品用量
    unit = Column(String(20), nullable=True, default="pcs")
    level = Column(Integer, nullable=False, default=1)            # BOM 层级
    remark = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ============================================================
# 统一码表（基础数据管理）—— 系统设置中集中维护，告别硬编码散落
# ============================================================

class CodeTable(Base):
    """统一码表 / 基础数据管理

    将散落在代码各处的枚举字典（工单类型、工序代码、优先级等）
    集中到数据库，支持在系统设置页面自定义扩展。
    category 为码表分类，code 为编码值，name 为中文显示名。
    """
    __tablename__ = "code_tables"
    __table_args__ = (
        UniqueConstraint("category", "code", name="uq_code_table_category_code"),
        Index("idx_code_table_category", "category"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    category = Column(String(50), nullable=False)       # 码表分类: wo_type / process_code / priority ...
    code = Column(String(30), nullable=False)           # 编码值（如 S / INJ / high）
    name = Column(String(100), nullable=False)          # 中文名称（如 标准量产 / 注塑）
    name_en = Column(String(100), nullable=True)        # 英文名称（如 Standard Production）
    description = Column(String(255), nullable=True)    # 补充说明
    keywords = Column(JSON, nullable=True)              # 关键词列表（用于工序解析匹配）
    extra = Column(JSON, nullable=True)                 # 扩展属性（颜色、图标等）
    sort_order = Column(Integer, default=0)             # 排序
    is_active = Column(Boolean, default=True)           # 是否启用
    is_system = Column(Boolean, default=False)          # 系统内置（不可删除，可改名/停用）
    factory_id = Column(String(50), nullable=True)      # NULL=全局；非空=工厂专属
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "code": self.code,
            "name": self.name,
            "name_en": self.name_en,
            "description": self.description,
            "keywords": self.keywords,
            "extra": self.extra,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "is_system": self.is_system,
            "factory_id": self.factory_id,
        }


# ============== APS 排程模型 (018) ==============

class ApsSchedule(Base):
    """排程方案（一次排程生成一个方案）"""
    __tablename__ = "aps_schedules"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    schedule_code = Column(String(50), unique=True, nullable=False, index=True)
    factory_id = Column(String(50), nullable=False, index=True)
    mode = Column(String(20), nullable=False, default="hybrid")
    optimize_for = Column(String(20), default="delivery")
    status = Column(String(20), default="draft")
    horizon_start = Column(DateTime, nullable=False)
    horizon_end = Column(DateTime, nullable=False)
    on_time_rate = Column(Float, nullable=True)
    avg_utilization = Column(Float, nullable=True)
    total_setup_minutes = Column(Float, nullable=True)
    avg_cycle_hours = Column(Float, nullable=True)
    total_tasks = Column(Integer, default=0)
    unscheduled_count = Column(Integer, default=0)
    created_by = Column(String(50), nullable=True)
    confirmed_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    tasks = relationship("ApsScheduleTask", back_populates="schedule", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_aps_sched_factory", "factory_id", "status"),
    )


class ApsScheduleTask(Base):
    """排程任务明细（每道工序一条）"""
    __tablename__ = "aps_schedule_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    schedule_id = Column(String(36), ForeignKey("aps_schedules.id"), nullable=False, index=True)
    work_order_id = Column(String(36), nullable=True, index=True)
    order_code = Column(String(50), nullable=True)
    product_code = Column(String(50), nullable=True)
    operation_seq = Column(Integer, nullable=False)
    operation_name = Column(String(100), nullable=True)
    station_id = Column(String(50), nullable=False)
    planned_start = Column(DateTime, nullable=False)
    planned_end = Column(DateTime, nullable=False)
    setup_seconds = Column(Float, default=0)
    run_seconds = Column(Float, default=0)
    quantity = Column(Integer, default=0)
    status = Column(String(20), default="planned")
    is_locked = Column(Boolean, default=False)
    priority = Column(Integer, default=5)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    schedule = relationship("ApsSchedule", back_populates="tasks")

    __table_args__ = (
        Index("idx_aps_task_station", "station_id", "planned_start"),
    )


class ApsWorkCalendar(Base):
    """工作日历（工位/产线的可用时间段）"""
    __tablename__ = "aps_work_calendars"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False)
    resource_id = Column(String(50), nullable=False)
    resource_type = Column(String(20), default="station")
    shift_name = Column(String(50), default="标准班")
    day_of_week = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    is_active = Column(Boolean, default=True)
    effective_from = Column(Date, nullable=True)
    effective_to = Column(Date, nullable=True)

    __table_args__ = (
        Index("idx_aps_cal_resource", "resource_id", "day_of_week"),
    )


# ============================================================
# QMS 增强模型（019）
# ============================================================


class QmsInspectionItem(Base):
    """检验项明细"""
    __tablename__ = "qms_inspection_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    inspection_id = Column(String(36), ForeignKey("quality_inspections.id"), nullable=False, index=True)
    item_name = Column(String(100), nullable=False)
    item_code = Column(String(50), nullable=True)
    spec_lower = Column(Float, nullable=True)
    spec_upper = Column(Float, nullable=True)
    target_value = Column(Float, nullable=True)
    measured_value = Column(Float, nullable=True)
    result = Column(String(10), nullable=True)  # OK/NG
    measurement_method = Column(String(50), nullable=True)
    remark = Column(String(200), nullable=True)


class QmsSpcPoint(Base):
    """SPC 控制图数据点"""
    __tablename__ = "qms_spc_points"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    characteristic_code = Column(String(50), nullable=False, index=True)
    characteristic_name = Column(String(100), nullable=True)
    work_order_id = Column(String(36), nullable=True)
    station_id = Column(String(50), nullable=True)
    measured_value = Column(Float, nullable=False)
    sample_group = Column(Integer, nullable=True)
    ucl = Column(Float, nullable=True)
    lcl = Column(Float, nullable=True)
    cl = Column(Float, nullable=True)
    is_out_of_control = Column(Boolean, default=False)
    measured_at = Column(DateTime, default=datetime.utcnow)
    measured_by = Column(String(50), nullable=True)

    __table_args__ = (
        Index("idx_spc_char_time", "factory_id", "characteristic_code", "measured_at"),
    )


class Qms8dReport(Base):
    """8D 报告"""
    __tablename__ = "qms_8d_reports"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    report_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    defect_record_id = Column(String(36), ForeignKey("defect_records.id"), nullable=True)
    title = Column(String(200), nullable=False)
    severity = Column(String(20), default="major")
    status = Column(String(20), default="open")  # open/in_progress/closed/verified
    d1_team = Column(Text, nullable=True)
    d2_problem_description = Column(Text, nullable=True)
    d3_containment_action = Column(Text, nullable=True)
    d4_root_cause = Column(Text, nullable=True)
    d5_corrective_action = Column(Text, nullable=True)
    d6_implementation = Column(Text, nullable=True)
    d7_preventive_action = Column(Text, nullable=True)
    d8_congratulations = Column(Text, nullable=True)
    opened_by = Column(String(50), nullable=True)
    closed_by = Column(String(50), nullable=True)
    due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_8d_factory_status", "factory_id", "status"),
    )


# ============================================================
# 设备 TPM 模型（020）
# ============================================================


class EquipmentDowntime(Base):
    """设备停机记录"""
    __tablename__ = "equipment_downtime"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    equipment_id = Column(String(36), ForeignKey("equipment.id"), nullable=False, index=True)
    factory_id = Column(String(50), nullable=False, index=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration_minutes = Column(Float, nullable=True)
    downtime_category = Column(String(30), nullable=True)  # breakdown/setup/adjustment/waiting/planned_maint
    reason_code = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    reported_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MaintenanceOrder(Base):
    """维护工单"""
    __tablename__ = "maintenance_orders"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    equipment_id = Column(String(36), ForeignKey("equipment.id"), nullable=False, index=True)
    maintenance_type = Column(String(20), nullable=False)  # preventive/corrective/predictive
    priority = Column(String(10), default="medium")
    status = Column(String(20), default="open")  # open/in_progress/completed/cancelled
    description = Column(Text, nullable=True)
    planned_date = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    assigned_to = Column(String(50), nullable=True)
    result_summary = Column(Text, nullable=True)
    downtime_minutes = Column(Float, default=0)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MaintenancePlan(Base):
    """预防性维护计划"""
    __tablename__ = "maintenance_plans"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    equipment_id = Column(String(36), ForeignKey("equipment.id"), nullable=False, index=True)
    plan_name = Column(String(100), nullable=False)
    frequency_days = Column(Integer, nullable=False)
    last_executed_at = Column(DateTime, nullable=True)
    next_due_at = Column(DateTime, nullable=True)
    checklist = Column(Text, nullable=True)  # JSON array
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ============================================================
# WMS 增强模型（021）
# ============================================================


class InventoryTransaction(Base):
    """库存流水"""
    __tablename__ = "inventory_transactions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    inventory_id = Column(String(36), ForeignKey("inventory.id"), nullable=True)
    material_id = Column(String(50), nullable=False, index=True)
    batch_code = Column(String(50), nullable=True)
    transaction_type = Column(String(20), nullable=False)  # inbound/outbound/adjust/transfer/count_diff
    quantity = Column(Integer, nullable=False)  # 正=入, 负=出
    before_qty = Column(Integer, nullable=True)
    after_qty = Column(Integer, nullable=True)
    reference_type = Column(String(30), nullable=True)
    reference_id = Column(String(36), nullable=True)
    operator = Column(String(50), nullable=True)
    remark = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class InventoryCount(Base):
    """盘点单"""
    __tablename__ = "inventory_counts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    count_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    warehouse_id = Column(String(36), ForeignKey("warehouses.id"), nullable=False)
    count_type = Column(String(20), default="periodic")  # periodic/cycle/spot
    status = Column(String(20), default="draft")  # draft/counting/pending_approval/approved/rejected
    planned_date = Column(Date, nullable=True)
    counted_by = Column(String(50), nullable=True)
    approved_by = Column(String(50), nullable=True)
    total_items = Column(Integer, default=0)
    diff_items = Column(Integer, default=0)
    total_diff_qty = Column(Integer, default=0)
    remark = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    items = relationship("InventoryCountItem", back_populates="count_order", cascade="all, delete-orphan")


class InventoryCountItem(Base):
    """盘点明细"""
    __tablename__ = "inventory_count_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    count_id = Column(String(36), ForeignKey("inventory_counts.id"), nullable=False, index=True)
    inventory_id = Column(String(36), ForeignKey("inventory.id"), nullable=True)
    material_id = Column(String(50), nullable=False)
    batch_code = Column(String(50), nullable=True)
    system_qty = Column(Integer, nullable=False)
    counted_qty = Column(Integer, nullable=True)
    diff_qty = Column(Integer, nullable=True)
    adjusted = Column(Boolean, default=False)
    remark = Column(String(200), nullable=True)

    count_order = relationship("InventoryCount", back_populates="items")


# ============== ERPNext 参考增强（022）==============

class JobCardTimeLog(Base):
    """工序计时日志（参考 ERPNext Job Card Time Log）"""
    __tablename__ = "job_card_time_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=True, index=True)
    operation_seq = Column(Integer, nullable=True)
    operation_name = Column(String(100), nullable=True)
    station_id = Column(String(50), nullable=True, index=True)
    operator = Column(String(50), nullable=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=True)
    duration_minutes = Column(Float, nullable=True)
    completed_qty = Column(Integer, default=0)
    status = Column(String(20), default="running")
    remark = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ============== IE Module (Industrial Engineering) ==============

class StandardOperationTime(Base):
    """标准工时（Standard Operation Time, SOT）- 精益生产核心数据
    每个工序在标准条件下的理论作业时间，用于生产计划、绩效评估和线平衡分析"""
    
    __tablename__ = "standard_operation_times"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    routing_step = Column(String(20), nullable=True)  # 工序步骤号（如 A01, B02）
    operation_name = Column(String(100), nullable=False)  # 工序名称
    station_id = Column(String(50), nullable=True, index=True)  # 工位编号
    work_center = Column(String(20), nullable=True, index=True)  # 工序组
    
    standard_time_min = Column(Float, nullable=False)  # 标准工时（分钟）
    unit_time_type = Column(String(20), default="per_piece")  # per_piece/per_batch/setup
    setup_time_min = Column(Float, default=0.0)  # Setup time（分钟）
    batch_size = Column(Integer, default=1)  # 批量大小
    
    rating_factor = Column(Float, default=1.0)  # 评定系数（正常速度为1.0）
    allowance_rate = Column(Float, default=0.15)  # 宽放率（默认15%）
    
    effective_standard_time = Column(Float, nullable=False)  # 有效标准时间（已含宽放）
    
    version = Column(String(10), default="v1")  # 版本号
    is_active = Column(Boolean, default=True)  # 是否生效
    validity_start = Column(DateTime, nullable=False)  # 生效开始时间
    validity_end = Column(DateTime, nullable=True)  # 失效结束时间
    
    created_by = Column(String(50))
    updated_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('factory_id', 'product_id', 'routing_step', 'version', name='idx_unique_sot_factory_product_step'),
        Index('idx_sot_factory_station', 'factory_id', 'station_id'),
        Index('idx_sot_validity', 'validity_start', 'is_active'),
    )
    
    def to_dict(self):
        return {
            "id": self.id,
            "factory_id": self.factory_id,
            "product_id": self.product_id,
            "routing_step": self.routing_step,
            "operation_name": self.operation_name,
            "station_id": self.station_id,
            "work_center": self.work_center,
            "standard_time_min": self.standard_time_min,
            "unit_time_type": self.unit_time_type,
            "setup_time_min": self.setup_time_min,
            "batch_size": self.batch_size,
            "rating_factor": self.rating_factor,
            "allowance_rate": self.allowance_rate,
            "effective_standard_time": self.effective_standard_time,
            "version": self.version,
            "is_active": self.is_active,
            "validity_start": self.validity_start.isoformat() if self.validity_start else None,
            "validity_end": self.validity_end.isoformat() if self.validity_end else None,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.validity_start.isoformat() if self.validity_start else None,
        }


class TimeStudyRecord(Base):
    """时间研究记录 - 实际作业观测数据
    通过秒表或系统采集的实际作业时间数据，用于计算标准工时的依据"""
    
    __tablename__ = "time_study_records"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    station_id = Column(String(50), nullable=False, index=True)
    operation_name = Column(String(100), nullable=False)
    operator_id = Column(String(50), nullable=False)  # 观测操作员
    observer_id = Column(String(50), nullable=False)  # 时间研究员
    
    observation_date = Column(DateTime, nullable=False)  # 观测日期
    observed_cycles = Column(JSON, default=list)  # 多个循环观测时间数组 [minute]
    cycle_count = Column(Integer, default=1)  # 观测循环次数
    
    average_time = Column(Float, nullable=False)  # 平均观测时间
    rating_factor = Column(Float, default=1.0)  # 评定系数
    normal_time = Column(Float, nullable=False)  # 正常时间 = 平均时间 × 评定系数
    allowed_time = Column(Float, nullable=False)  # 允许时间 = 正常时间 × (1 + 宽放率)
    allowance_rate = Column(Float, default=0.15)  # 宽放率
    
    method = Column(String(20), default="stopwatch")  # stopwatch/video/electronic
    status = Column(String(20), default="pending")  # pending/approved/reviewed
    
    created_by = Column(String(50))
    approved_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_ts_factory_operator', 'factory_id', 'operator_id'),
        Index('idx_ts_observation', 'observation_date'),
    )
    
    def to_dict(self):
        return {
            "id": self.id,
            "factory_id": self.factory_id,
            "product_id": self.product_id,
            "station_id": self.station_id,
            "operation_name": self.operation_name,
            "operator_id": self.operator_id,
            "observer_id": self.observer_id,
            "observation_date": self.observation_date.isoformat() if self.observation_date else None,
            "observed_cycles": self.observed_cycles,
            "cycle_count": self.cycle_count,
            "average_time": self.average_time,
            "rating_factor": self.rating_factor,
            "normal_time": self.normal_time,
            "allowed_time": self.allowed_time,
            "allowance_rate": self.allowance_rate,
            "method": self.method,
            "status": self.status,
            "created_by": self.created_by,
            "approved_by": self.approved_by,
        }


class LineBalanceAnalysis(Base):
    """产线平衡分析 - 生产线IE分析核心结果
    计算各工站的节拍、平衡率、瓶颈，并提供改善建议"""
    
    __tablename__ = "line_balance_analyses"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    line_id = Column(String(50), nullable=False)  # 产线ID
    analysis_date = Column(DateTime, nullable=False)  # 分析日期
    
    takt_time_min = Column(Float, nullable=False)  # 客户需求节拍时间（分钟/件）
    cycle_time_max = Column(Float, nullable=False)  # 最大工序耗时（瓶颈工序）
    cycle_time_avg = Column(Float, nullable=False)  # 平均工序耗时
    balance_rate = Column(Float, nullable=False)  # 平衡率（%） = 总有效时间 / (工位数 × 最长工时)
    idle_time_total = Column(Float, nullable=False)  # 总闲置时间
    workstation_count = Column(Integer, default=0)  # 工位数
    
    is_balanced = Column(Boolean, default=False)  # 是否平衡（平衡率 > 90%）
    
    # 各工站详细数据
    station_details = Column(JSON, default=list)  # [{"station_id", "cycle_time", "idle_time", "balance_pct"}]
    
    bottleneck_station = Column(String(50), nullable=True)  # 瓶颈工位
    bottleneck_time = Column(Float, nullable=True)  # 瓶颈工序耗时
    
    recommendations = Column(JSON, default=list)  # 改善建议列表
    
    created_by = Column(String(50))
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_lb_factory_line', 'factory_id', 'line_id'),
        Index('idx_lb_product', 'product_id', 'analysis_date'),
    )
    
    def to_dict(self):
        return {
            "id": self.id,
            "factory_id": self.factory_id,
            "product_id": self.product_id,
            "line_id": self.line_id,
            "analysis_date": self.analysis_date.isoformat() if self.analysis_date else None,
            "takt_time_min": self.takt_time_min,
            "cycle_time_max": self.cycle_time_max,
            "cycle_time_avg": self.cycle_time_avg,
            "balance_rate": self.balance_rate,
            "idle_time_total": self.idle_time_total,
            "workstation_count": self.workstation_count,
            "is_balanced": self.is_balanced,
            "station_details": self.station_details,
            "bottleneck_station": self.bottleneck_station,
            "bottleneck_time": self.bottleneck_time,
            "recommendations": self.recommendations,
            "created_by": self.created_by,
        }


class ProcessAnalysis(Base):
    """工序价值分析 - VA/NVA 时间分解
    区分增值时间和非增值时间，支持精益改善（Lean Improvement）"""
    
    __tablename__ = "process_analyses"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    operation_code = Column(String(20), nullable=False)  # 工序代码
    analysis_date = Column(DateTime, nullable=False)
    
    total_process_time_min = Column(Float, nullable=False)  # 总过程时间
    va_time_min = Column(Float, nullable=False)  # 增值时间（Value Added）
    nva_time_min = Column(Float, nullable=False)  # 非增值时间（Non-Value Added）
    wait_time_min = Column(Float, nullable=False)  # 等待时间
    move_time_min = Column(Float, nullable=False)  # 搬运时间
    inspect_time_min = Column(Float, nullable=False)  # 检验时间
    
    va_ratio = Column(Float, nullable=False)  # 增值比率 = VA / Total Time
    lead_time = Column(Float, nullable=False)  # 交付周期时间
    
    efficiency_score = Column(Float, nullable=False)  # 效率评分（0-100）
    
    created_by = Column(String(50))
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('factory_id', 'product_id', 'operation_code', 'analysis_date', 
                       name='unique_pa_factory_product_op'),
        Index('idx_pa_factory', 'factory_id', 'analysis_date'),
    )
    
    def to_dict(self):
        return {
            "id": self.id,
            "factory_id": self.factory_id,
            "product_id": self.product_id,
            "operation_code": self.operation_code,
            "analysis_date": self.analysis_date.isoformat() if self.analysis_date else None,
            "total_process_time_min": self.total_process_time_min,
            "va_time_min": self.va_time_min,
            "nva_time_min": self.nva_time_min,
            "wait_time_min": self.wait_time_min,
            "move_time_min": self.move_time_min,
            "inspect_time_min": self.inspect_time_min,
            "va_ratio": self.va_ratio,
            "lead_time": self.lead_time,
            "efficiency_score": self.efficiency_score,
            "created_by": self.created_by,
        }


# ============================================================
# END: IE Module Models
# ============================================================





# ============== Extended IE Module Models (Advanced Lean Features) ==============

class ActionStudy(Base):
    """动作研究 - 基于MODAPTS或MTM方法的详细动作时间分析
    用于方法研究和工时测定的基础数据收集"""
    
    __tablename__ = "action_studies"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    operation_name = Column(String(100), nullable=False)
    station_id = Column(String(50), nullable=True, index=True)
    operator_id = Column(String(50), nullable=False)  # 执行动作研究的员工
    
    study_date = Column(DateTime, nullable=False)  # 研究日期
    method_type = Column(String(20), default="mtm")  # mtm / modapt / therbligs / video_analysis
    recorded_by = Column(String(50), nullable=False)  # 记录人
    
    # MODAPTS/MTM 动作列表（JSON数组）
    motions = Column(JSON, default=list)  # [{"motion": "reach", "time_units": 2, ...}]
    total_time_cycles = Column(Float, nullable=False)  # 总循环时间（周期数或分钟）
    
    analysis_result = JSON  # 分析结果，包含时间要素分解
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_factory_product_op', 'factory_id', 'product_id', 'operation_name'),
    )


class MethodStudy(Base):
    """方法研究 - 工序操作方法的记录和对比分析
    支持多个方法版本对比，选择最佳方法作为标准作业方法"""
    
    __tablename__ = "method_studies"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    original_operation = Column(String(100), nullable=False)  # 原始工序名称
    
    version = Column(String(10), default="v1")  # 版本号（v1, v2...）
    is_basement_method = Column(Boolean, default=False)  # 是否为基准方法（原方法）
    is_optimal_method = Column(Boolean, default=False)  # 是否为最优方法
    
    description = Column(Text)  # 方法描述，包含操作步骤、工装夹具、动作要点等
    
    # 动作序列（JSON数组，按执行顺序）
    action_sequence = Column(JSON, default=list)  # [{"step": 1, "action": "move", "from": "...", "to": "...", "time_min": 0.5}, ...]
    
    required_resources = Column(JSON, default=list)  # {"tools": [], "fixtures": [], "materials": []}
    
    # 时间要素
    setup_time_min = Column(Float, default=0.0)  # Setup time
    cycle_time_min = Column(Float, nullable=False)  # Cycle time
    total_standard_time_min = Column(Float, nullable=False)  # Total standard time including allowances
    
    validity_start = Column(DateTime, nullable=False)  # 生效开始
    validity_end = Column(DateTime, nullable=True)   # 失效结束
    
    created_by = Column(String(50))
    approved_by = Column(String(50), nullable=True)  # 批准人
    status = Column(String(20), default="draft")  # draft/approved/reviewed
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('factory_id', 'product_id', 'original_operation', 'version', 
                       name='unique_method_factory_product_op_version'),
        Index('idx_method_validity', 'validity_start', 'is_optimal_method'),
    )


class WorkCellLayout(Base):
    """工站布局分析 - 精益布局设计支持
    记录工站的物理布局和物料流动路径，支持5S和精益布局优化"""
    
    __tablename__ = "work_cell_layouts"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    work_cell_id = Column(String(50), nullable=False)  # 单元格/工作岛编号
    product_family_id = Column(String(50), nullable=False)  # 产品族编码
    
    layout_diagram_url = Column(String(200), nullable=True)  # 布局图路径
    
    material_flow_path = Column(JSON, default=list)  # 物料流动路径 [step1, step2, ...]
    operator_movement_path = Column(JSON, default=list)  # 人员移动路径
    
    takt_time_alignment = Column(String(20), default="aligned")  # aligned / pending / misaligned
    
    storage_location_type = Column(String(20), default="in_process")  # in_process / FIFO_kanban / buffer
    
    last_updated = Column(DateTime, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_cell_product', 'work_cell_id', 'product_family_id'),
        Index('idx_factory_cell', 'factory_id', 'work_cell_id'),
    )


class KanbanSystem(Base):
    """看板系统 - 拉动式生产管理系统
    支持连续看板、Kanban卡片、电子看板等多种看板形式"""
    
    __tablename__ = "kanban_systems"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    kanban_id = Column(String(50), unique=True, nullable=False)  # 看板编号
    kanban_type = Column(String(20), default="continuous")  # continuous / move / production / emergency
    
    upstream_station = Column(String(50))  # 上游工位
    downstream_station = Column(String(50))  # 下游工位
    product_id = Column(String(50), nullable=False)  # 看板对象产品
    part_number = Column(String(50))  # 零件号
    
    max_card_count = Column(Integer, default=5)  # 最大卡片数量
    current_card_count = Column(Integer, default=0)  # 当前卡片数
    safety_stock_level = Column(Integer, default=2)  # 安全库存量
    
    card_status = Column(String(20), default="available")  # available / occupied / lost
    
    last_used_at = Column(DateTime, nullable=True)  # 最后使用时间
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_upstream_downstream', 'upstream_station', 'downstream_station'),
        Index('idx_product_kanban', 'product_id', 'kanban_type'),
    )


class FiveSAudit(Base):
    """5S审计 - 现场整理整顿评估
    支持定期5S检查和持续改善跟踪"""
    
    __tablename__ = "five_s_audits"
    
    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    work_center_id = Column(String(50), nullable=False)  # 工序组/区域
    
    audit_date = Column(DateTime, nullable=False)  # 审计日期
    auditor_id = Column(String(50), nullable=False)  # 审计员
    
    # 5S各项目评分（1-5分）
    seiri_score = Column(Integer, default=0)  # 整理
    seiton_score = Column(Integer, default=0)  # 整顿
    seiso_score = Column(Integer, default=0)  # 清扫
    seiketsu_score = Column(Integer, default=0)  # 清洁
    shitsuke_score = Column(Integer, default=0)  # 素养
    
    total_score = Column(Integer, default=0)  # 总分（各单项之和）
    score_percentage = Column(Float, default=0.0)  # 得分百分比（0-100）
    
    improvement_items = Column(JSON, default=list)  # 改进项列表
    
    next_audit_date = Column(DateTime, nullable=True)  # 下次审计日期
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_work_center_audit', 'work_center_id', 'audit_date'),
        Index('idx_factory_date', 'factory_id', 'audit_date'),
    )
class QualityGoal(Base):
    """质量目标（参考 ERPNext Quality Goal）"""
    __tablename__ = "quality_goals"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    goal_code = Column(String(50), unique=True, nullable=False)
    goal_name = Column(String(200), nullable=False)
    metric_type = Column(String(30), nullable=False)
    target_value = Column(Float, nullable=False)
    current_value = Column(Float, nullable=True)
    unit = Column(String(20), default="%")
    period = Column(String(20), default="monthly")
    responsible = Column(String(50), nullable=True)
    status = Column(String(20), default="active")
    review_frequency_days = Column(Integer, default=30)
    last_reviewed_at = Column(DateTime, nullable=True)
    next_review_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    reviews = relationship("QualityGoalReview", back_populates="goal", cascade="all, delete-orphan")


class QualityGoalReview(Base):
    """质量目标评审记录"""
    __tablename__ = "quality_goal_reviews"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    goal_id = Column(String(36), ForeignKey("quality_goals.id"), nullable=False, index=True)
    review_date = Column(DateTime, default=datetime.utcnow)
    measured_value = Column(Float, nullable=True)
    gap = Column(Float, nullable=True)
    status = Column(String(20), default="on_track")
    action_plan = Column(Text, nullable=True)
    reviewed_by = Column(String(50), nullable=True)
    remark = Column(String(500), nullable=True)

    goal = relationship("QualityGoal", back_populates="reviews")


class PickList(Base):
    """拣货单（参考 ERPNext Pick List）"""
    __tablename__ = "pick_lists"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    pick_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    work_order_id = Column(String(36), ForeignKey("work_orders.id"), nullable=True, index=True)
    work_order_code = Column(String(50), nullable=True)
    status = Column(String(20), default="draft")
    warehouse_id = Column(String(36), nullable=True)
    total_items = Column(Integer, default=0)
    picked_items = Column(Integer, default=0)
    picked_by = Column(String(50), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    items = relationship("PickListItem", back_populates="pick_list", cascade="all, delete-orphan")


class PickListItem(Base):
    """拣货明细"""
    __tablename__ = "pick_list_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    pick_list_id = Column(String(36), ForeignKey("pick_lists.id"), nullable=False, index=True)
    material_id = Column(String(50), nullable=False)
    material_name = Column(String(100), nullable=True)
    required_qty = Column(Integer, nullable=False)
    picked_qty = Column(Integer, default=0)
    batch_code = Column(String(50), nullable=True)
    location = Column(String(50), nullable=True)
    status = Column(String(20), default="pending")
    remark = Column(String(200), nullable=True)

    pick_list = relationship("PickList", back_populates="items")


# ============== 岗位替代 Phase 1（023）==============

class ShiftSummary(Base):
    """班次汇总表（自动聚合，报表数据源）"""
    __tablename__ = "shift_summaries"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    shift_date = Column(Date, nullable=False)
    shift_type = Column(String(20), nullable=False)  # day/middle/night
    station_id = Column(String(50), nullable=True)
    work_order_id = Column(String(36), nullable=True)
    product_id = Column(String(50), nullable=True)
    total_output = Column(Integer, default=0)
    good_qty = Column(Integer, default=0)
    defect_qty = Column(Integer, default=0)
    scrap_qty = Column(Integer, default=0)
    yield_rate = Column(Float, default=0)
    target_output = Column(Integer, default=0)
    achievement_rate = Column(Float, default=0)
    report_count = Column(Integer, default=0)
    total_cycle_time = Column(Float, default=0)
    operator_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_ss_unique", "factory_id", "shift_date", "shift_type", "station_id", "work_order_id", unique=True),
    )


class ProductionAlert(Base):
    """生产异常预警"""
    __tablename__ = "production_alerts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    alert_type = Column(String(30), nullable=False)  # below_target/yield_drop/machine_stop/material_short/order_delay
    severity = Column(String(10), nullable=False, default="warning")  # info/warning/critical
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=True)
    source_type = Column(String(30), nullable=True)
    source_id = Column(String(50), nullable=True)
    metric_value = Column(Float, nullable=True)
    threshold_value = Column(Float, nullable=True)
    is_read = Column(Boolean, default=False)
    is_resolved = Column(Boolean, default=False)
    resolved_by = Column(String(50), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    triggered_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class HourlyOutputSnapshot(Base):
    """小时产出快照（看板趋势图数据源）"""
    __tablename__ = "hourly_output_snapshots"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False)
    snapshot_hour = Column(Integer, nullable=False)  # 0-23
    station_id = Column(String(50), nullable=True)
    output_qty = Column(Integer, default=0)
    good_qty = Column(Integer, default=0)
    defect_qty = Column(Integer, default=0)
    target_qty = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_hos_unique", "factory_id", "snapshot_date", "snapshot_hour", "station_id", unique=True),
    )


class Notification(Base):
    """站内通知（报告就绪/异常预警/系统消息）"""
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    factory_id = Column(String(50), nullable=False, index=True)
    recipient = Column(String(50), nullable=True, index=True)  # 用户名，空=广播
    category = Column(String(30), nullable=False, default="system")  # report/anomaly/system/andon
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=True)
    severity = Column(String(10), default="info")  # info/warning/critical
    source_type = Column(String(30), nullable=True)  # daily_report/alert/andon
    source_id = Column(String(50), nullable=True)
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_notif_unread", "factory_id", "recipient", "is_read"),
    )


# 导出所有模型
__all__ = [
    "Base",
    "User",
    "WorkOrder",
    "ProductionReport",
    "ProductionReportComment",
    "Product",
    "Station",
    "Routing",
    "Equipment",
    "Warehouse",
    "Location",
    "Inventory",
    "InboundOrder",
    "OutboundOrder",
    "Skill",
    "EmployeeSkill",
    "TrainingRecord",
    "SimERPAuditLog",
    # TMS Models
    "TMSTask",
    "TMSApprovalFlow",
    "TMSApprovalRecord",
    "TMSDistributionLog",
    "TMSAgentAction",
    "TMSWebhookSubscription",
    # v2.5 Data Consistency Models
    "DefectRecord",
    "ItemTraceability",
    "ReconciliationLog",
    "ReplenishmentThreshold",
    "PullReplenishmentTask",
    # QMS / PP Models
    "QualityInspection",
    "Plan",
    "BomItem",
    "WoStatusLog",
    # 文件/附件
    "FileRecord",
    # 统一码表
    "CodeTable",
    # 工序流转（016）
    "RoutingTemplate",
    "RoutingTemplateStep",
    # APS 排程（018）
    "ApsSchedule",
    "ApsScheduleTask",
    "ApsWorkCalendar",
    # QMS 增强（019）
    "QmsInspectionItem",
    "QmsSpcPoint",
    "Qms8dReport",
    # 设备 TPM（020）
    "EquipmentDowntime",
    "MaintenanceOrder",
    "MaintenancePlan",
    # WMS 增强（021）
    "InventoryTransaction",
    "InventoryCount",
    "InventoryCountItem",
    # ERPNext 参考增强（022）
    "JobCardTimeLog",
    "ActionStudy",
    "MethodStudy",
    "WorkCellLayout",
    "KanbanSystem",
    "FiveSAudit",
    # IE Module (Industrial Engineering)
    "StandardOperationTime",
    "TimeStudyRecord",
    "LineBalanceAnalysis",
    "ProcessAnalysis",
    "QualityGoal",
    "QualityGoalReview",
    "PickList",
    "PickListItem",
    # 岗位替代 Phase 1（023）
    "ShiftSummary",
    "ProductionAlert",
    "HourlyOutputSnapshot",
    # 通知系统（030）
    "Notification",
]
