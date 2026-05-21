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
    Boolean,
    Numeric,
    ForeignKey,
    Index,
    Text,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
import uuid

Base = declarative_base()


def generate_uuid():
    """生成 UUID"""
    return str(uuid.uuid4())


class User(Base):
    """用户表"""
    
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100))
    factory_id = Column(String(50), index=True)
    role = Column(String(20), default="operator", index=True)  # admin, manager, operator, viewer
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_user_factory_role", "factory_id", "role"),
    )


class WorkOrder(Base):
    """生产工单表"""
    
    __tablename__ = "work_orders"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default="gen_random_uuidid()")
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
    created_by = Column(String(50))
    updated_by = Column(String(50))
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # 索引
    __table_args__ = (
        Index("idx_wo_status_factory", "status", "factory_id"),
        Index("idx_wo_created_at", "created_at"),
    )
    
    # 关系
    production_reports = relationship("ProductionReport", back_populates="work_order")


class ProductionReport(Base):
    """生产报工表"""
    
    __tablename__ = "production_reports"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default="gen_random_uuidid()")
    report_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    work_order_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False, index=True)
    station_id = Column(String(50), nullable=False, index=True)
    good_qty = Column(Integer, nullable=False, default=0)
    defect_qty = Column(Integer, default=0)
    scrap_qty = Column(Integer, default=0)
    report_type = Column(String(20), default="normal")
    shift = Column(String(20), default="day")
    operator_id = Column(String(50))
    remark = Column(Text)
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
    
    id = Column(UUID(as_uuid=True), primary_key=True, default="gen_random_uuidid()")
    report_id = Column(UUID(as_uuid=True), ForeignKey("production_reports.id"), nullable=False, index=True)
    comment = Column(Text, nullable=False)
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # 关系
    report = relationship("ProductionReport", back_populates="comments")


class Station(Base):
    """工位/产线表"""
    
    __tablename__ = "stations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default="gen_random_uuidid()")
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
    
    id = Column(UUID(as_uuid=True), primary_key=True, default="gen_random_uuidid()")
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


class Equipment(Base):
    """设备表"""
    
    __tablename__ = "equipment"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default="gen_random_uuidid()")
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
    
    id = Column(UUID(as_uuid=True), primary_key=True, default="gen_random_uuidid()")
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
    
    id = Column(UUID(as_uuid=True), primary_key=True, default="gen_random_uuidid()")
    location_code = Column(String(50), nullable=False, index=True)
    location_name = Column(String(100))
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False, index=True)
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
    
    id = Column(UUID(as_uuid=True), primary_key=True, default="gen_random_uuidid()")
    material_id = Column(String(50), nullable=False, index=True)
    material_code = Column(String(50), nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False, index=True)
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"))
    batch_code = Column(String(50), index=True)
    total_qty = Column(Integer, default=0, nullable=False)
    available_qty = Column(Integer, default=0, nullable=False)
    reserved_qty = Column(Integer, default=0)
    unit_cost = Column(Numeric(10, 2))
    status = Column(String(20), default="available")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_inv_mat_wh_batch", "material_id", "warehouse_id", "batch_code"),
    )


class InboundOrder(Base):
    """入库单表"""
    
    __tablename__ = "inbound_orders"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default="gen_random_uuidid()")
    inbound_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    material_id = Column(String(50), nullable=False)
    material_code = Column(String(50), nullable=False)
    quantity = Column(Integer, nullable=False)
    batch_code = Column(String(50))
    supplier_id = Column(String(50))
    purchase_order_id = Column(String(50))
    unit_cost = Column(Numeric(10, 2))
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id"))
    inbound_type = Column(String(20), default="purchase")
    status = Column(String(20), default="pending")
    created_by = Column(String(50))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime)


class OutboundOrder(Base):
    """出库单表"""
    
    __tablename__ = "outbound_orders"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default="gen_random_uuidid()")
    outbound_code = Column(String(50), unique=True, nullable=False)
    factory_id = Column(String(50), nullable=False, index=True)
    warehouse_id = Column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
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


# 导出所有模型
__all__ = [
    "Base",
    "User",
    "WorkOrder",
    "ProductionReport",
    "ProductionReportComment",
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
]
