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




"""
QualityInspection Model - Original Version (to be reinserted into models.py)

This is the original IQC/FAI/IPC/OQC inspection record model with simple fields:
- inspect_type (IQC/IPQC/FQC/OQC)
- result (PASS/FAIL/PENDING)
- sample_qty, defect_qty, good_qty
- related work order and routing step
"""

from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey, Index
from database.models import Base, generate_uuid, datetime

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


class QualityDefect(Base):
    """质量缺陷记录 - 记录每次检验中发现的具体缺陷"""
    
    __tablename__ = "quality_defects"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
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
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
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
    
    # 执行记录
    action_logs = Column(JSONB, default=list)  # [{"status": "...", "at": "...", "by": "...", "notes": "..."}]
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_case_number", "case_number", unique=True),
        Index("idx_status", "status"),
    )


class QualityCost(Base):
    """质量成本（COQ）核算记录"""
    
    __tablename__ = "quality_costs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    
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

