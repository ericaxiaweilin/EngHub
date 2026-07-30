"""
v2.5 - Andon 2.0 Smart Work Order Models

安灯小工单核心模型：
- AndonTicket: 基础工单实体（5大类别）
- AndonCategory: 工单类型定义
- EscalationLog: 超时升级日志
"""

from sqlalchemy import Column, String, Integer, DateTime, Boolean, Float, ForeignKey, Text, JSON, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime

from database.models import Base


class AndonCategory(Base):
    """安灯工单类别定义"""

    __tablename__ = "andon_categories"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(50), unique=True, nullable=False)        # equipment_repair, material_call, quality_issue, tech_support, admin
    name = Column(String(100), nullable=False)                    # 设备维修/物料呼叫/质量异常/技术支持/行政事务
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    priority_hint = Column(String(20), default="medium")          # low/medium/high/urgent
    requires_leader_approval = Column(Boolean, default=False)
    auto_route_to_tms = Column(Boolean, default=False)            # 是否自动转TMS任务
    tms_task_type = Column(String(50))                            # 转化后的TMS任务类型
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AndonTicket(Base):
    """安灯小工单 - 全员协作平台核心实体"""

    __tablename__ = "andon_tickets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_code = Column(String(50), unique=True, nullable=False, index=True)
    factory_id = Column(String(50), nullable=False, index=True)
    category_id = Column(String(36), ForeignKey("andon_categories.id"), nullable=True)
    category_code = Column(String(50), nullable=False, index=True)  # 冗余便于查询
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # 位置和关联
    location_id = Column(String(50), nullable=True)                 # 工位/区域ID
    location_name = Column(String(100), nullable=True)              # 位置名称（冗余）
    equipment_id = Column(String(36), nullable=True, index=True)    # 关联设备
    work_order_id = Column(UUID(as_uuid=False), nullable=True, index=True)   # 关联生产工单

    # 状态机
    status = Column(String(30), default="open", index=True)         # open/assigned/picking/upgrading/in_progress/resolved/closed/cancelled
    priority = Column(String(20), default="medium", index=True)     # low/medium/high/urgent

    # 派单
    assigned_to = Column(String(50), nullable=True, index=True)     # 指派人员ID/工号
    assigned_by = Column(String(50), nullable=True)
    claimed_at = Column(DateTime, nullable=True)                    # 抢单时间

    # 升级
    escalation_level = Column(Integer, default=0)                   # 0=初始, 1=组长, 2=厂长
    escalator_note = Column(Text, nullable=True)
    escalated_to = Column(String(50), nullable=True)                # 升级到谁
    escalated_at = Column(DateTime, nullable=True)

    # 时限与提醒
    reminder_interval_minutes = Column(Integer, default=5)          # 可配置提醒间隔
    last_reminder_at = Column(DateTime, nullable=True)
    timeout_minutes_no_response = Column(Integer, default=15)       # 无响应升级阈值
    timeout_minutes_resolve = Column(Integer, default=30)           # 未解决升级阈值
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    # 元数据扩展
    metadata_ = Column("metadata_", JSON().with_variant(JSONB, "postgresql"), default=dict)

    # 关系
    category = relationship("AndonCategory")


class AndonEscalationLog(Base):
    """安灯升级日志 - 记录每次提醒和升级"""

    __tablename__ = "andon_escalation_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(UUID(as_uuid=False), ForeignKey("andon_tickets.id"), nullable=False, index=True)
    event_type = Column(String(30), nullable=False, index=True)     # reminder/escalated/resolved_closed
    from_role = Column(String(50), nullable=True)                   # 当前处理人
    to_role = Column(String(50), nullable=True)                     # 升级对象
    message = Column(Text, nullable=True)
    triggered_by = Column(String(50), default="system")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_aes_ticket_created", "ticket_id", "created_at"),
    )


# 导出
__all__ = ["AndonCategory", "AndonTicket", "AndonEscalationLog"]
