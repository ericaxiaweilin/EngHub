"""
QMS 持久化演示服务（SQLite 内存模式）

此模块展示了如何将 IQC/FAI/IPC/OQC/CAPA 数据持久化到关系型数据库。
使用 SQLAlchemy ORM + SQLite 内存数据库（开发/演示用）。
生产环境中请替换为真实的 PostgreSQL 连接配置。
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON, ForeignKey, Text, func
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from uuid import uuid4

# 创建演示引擎（SQLite 内存数据库，无需额外依赖）
engine = create_engine("sqlite:///:memory:", echo=False)
Base = declarative_base()

# ==================== 数据库模型 ====================

class QualityInspection(Base):
    """质量检验记录（支持多种类型：IQC、FAI、IPC、OQC）"""
    
    __tablename__ = "quality_inspections"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    factory_id = Column(String(50), nullable=False)
    work_order_id = Column(String(36))  # 关联工单（用于 FAI/IPC）
    inspect_type = Column(String(20), nullable=False)  # IQC/FAI/IPC/OQC
    inspector_id = Column(String(50), nullable=False)
    sample_qty = Column(Integer, default=0)
    defect_qty = Column(Integer, default=0)
    result = Column(String(20), nullable=False)  # PENDING/PASS/FAIL
    defect_details = Column(JSON, default={})
    remark = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)

class CAPACase(Base):
    """CAPA案件（8D问题跟踪）"""
    
    __tablename__ = "capa_cases"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    case_number = Column(String(30), unique=True, nullable=False)
    title = Column(String(200), nullable=False)
    severity = Column(String(20), nullable=False)  # critical/major/minor
    source_type = Column(String(20))  # iqc/fai/ipc/oqc/internal
    source_id = Column(String(36))
    status = Column(String(20), default="open")
    created_at = Column(DateTime, default=datetime.utcnow)
    root_cause = Column(Text)
    verification_results = Column(JSON, default={})

# 初始化表
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# ==================== 持久化服务类 ====================

class IQCPersistenceService:
    """IQ C 持久化操作封装"""
    
    @staticmethod
    def create_iqc_record(db: Session, **kwargs) -> Dict[str, Any]:
        inspection = QualityInspection(
            id=str(uuid4()),
            factory_id=kwargs.get('factory_id', 'FACT-001'),
            work_order_id=kwargs.get('work_order_id'),
            inspect_type='IQC',
            inspector_id=kwargs['inspector_id'],
            sample_qty=kwargs.get('sample_size', 50),
            defect_qty=0,
            result='PENDING',
            defect_details={'batch_no': kwargs.get('batch_no')},
            remark=f"IQC 检验 - {kwargs.get('product_name')}",
        )
        db.add(inspection)
        db.commit()
        db.refresh(inspection)
        
        return {
            "id": inspection.id,
            "factory_id": inspection.factory_id,
            "status": inspection.result.lower(),
        }
    
    @staticmethod
    def complete_iqc_inspection(db: Session, inspection_id: str, result: str, defects: Optional[List[Dict]]) -> bool:
        inspection = db.query(QualityInspection).filter_by(id=inspection_id).first()
        if not inspection:
            return False
        
        inspection.result = result.upper()
        inspection.defect_qty = len(defects) or 0
        if defects:
            inspection.defect_details['defects'] = defects
        
        db.commit()
        return True
    
    @staticmethod
    def list_iqc_records(db: Session, factory_id: str, limit: int = 100) -> List[Dict]:
        results = db.query(QualityInspection).filter_by(factory_id=factory_id, inspect_type='IQC').order_by(QualityInspection.created_at.desc()).limit(limit)
        return [{
            "id": r.id,
            "product_id": r.defect_details.get('batch_no', ''),
            "status": r.result.lower(),
            "created_at": r.created_at.isoformat()
        } for r in results]


class CAPAPersistenceService:
    """CAPA 持久化操作封装"""
    
    @staticmethod
    def create_capa_case(db: Session, title: str, severity: str, source_type: str = None, source_id: str = None) -> Dict[str, Any]:
        case_number = f"CAPA-{datetime.utcnow().strftime('%Y')}-{CAPAPersistenceService._get_next_number(db)}"
        case = CAPACase(
            id=str(uuid4()),
            case_number=case_number,
            title=title,
            severity=severity,
            source_type=source_type,
            source_id=source_id,
            status='open'
        )
        db.add(case)
        db.commit()
        db.refresh(case)
        
        return {
            "id": case.id,
            "case_number": case.case_number,
            "title": case.title,
            "severity": case.severity,
        }
    
    @staticmethod
    def _get_next_number(db: Session) -> int:
        # 简单实现：从现有案件中获取最大编号并递增（实际生产应使用更健壮的序列）
        result = db.query(CAPACase).order_by(CAPACase.case_number.desc()).first()
        if result and result.case_number.startswith('CAPA-'):
            try:
                num = int(result.case_number.split('-')[-1])
                return num + 1
            except:
                pass
        return 1
    
    @staticmethod
    def list_capa_cases(db: Session, limit: int = 100) -> List[Dict]:
        results = db.query(CAPACase).order_by(CAPACase.created_at.desc()).limit(limit)
        return [{
            "id": r.id,
            "case_number": r.case_number,
            "title": r.title,
            "severity": r.severity,
            "status": r.status
        } for r in results]


# ==================== 测试演示 ====================

if __name__ == "__main__":
    print("=== QMS 持久化演示 ===\n")
    
    db = SessionLocal()
    
    try:
        # 1. 创建 IQC 记录
        iqc = IQCPersistenceService.create_iqc_record(
            db=db,
            supplier_id="SUPP-TEST",
            product_id="PROD-A",
            product_name="Test Product",
            quantity_received=100,
            batch_no="BATCH-001",
            inspector_id="QUAL-001",
            factory_id="FACT-001",
        )
        print(f"[1] ✅ IQC 创建: {iqc['id'][:8]}...")
        
        # 2. 完成检验（失败）
        IQCPersistenceService.complete_iqc_inspection(
            db=db,
            inspection_id=iqc['id'],
            result="FAIL",
            defects=[{"severity": "MAJOR", "description": "Surface scratch"}]
        )
        print("[2] ✅ IQC 检验完成 (FAIL)")
        
        # 3. 自动触发 CAPA（模拟）
        case = CAPAPersistenceService.create_capa_case(
            db=db,
            title=f"IQC Defect - {iqc['id'][:8]}",
            severity="major",
            source_type="iqc",
            source_id=iqc['id'][:8]
        )
        print(f"[3] ✅ CAPA 创建: {case['case_number']}")
        
        # 4. 查询验证
        iqcs = IQCPersistenceService.list_iqc_records(db, factory_id="FACT-001")
        capas = CAPAPersistenceService.list_capa_cases(db)
        print(f"[4] ✅ 查询验证: {len(iqcs)} IQC records, {len(capas)} CAPA cases")
        
        db.commit()
        print("\n✅ 持久化演示成功！数据已保存在内存 SQLite 数据库中。")
        
    finally:
        db.close()
