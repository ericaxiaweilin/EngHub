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