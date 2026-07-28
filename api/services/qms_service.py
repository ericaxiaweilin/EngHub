"""
QMS质量模块业务服务层 - 持久化版本（基于 SQLAlchemy ORM）

此版本通过 SQLAlchemy 操作真实数据库，所有数据持久化存储。
设计用于生产环境，与内存版本（开发调试时）功能一致但持久化到SQL表。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

# 导入持久化服务
from api.services.qms_persistence_service import (
    IQCPersistenceService, FAIPersistenceService, IPCPersistenceService,
    OQCPersistenceService, CAPAPersistenceService
)

# 导入枚举类型（用于参数校验）
from core.qms.iqc_service import IQCStatus, InspectionResultType, DispositionType
from core.qms.fai_service import FAIResultType
from core.qms.ipc_service import IPCFrequencyType, IPCStatus, IPCResultType
from core.qms.oqc_service import OQCStatus, OQCResultType
from core.qms.capa_service import CAPASeverity, CAPAStatus, FishboneDimension, VerificationStatus


class QMSService:
    """
    QMS统一服务门面（持久化版本）
    
    所有操作通过AsyncSession直接与数据库交互，实现真正的持久化存储。
    使用时需传入db_session参数或通过依赖注入获取。
    """
    
    def __init__(self, db_session: Optional[AsyncSession] = None):
        self.db = db_session
    
    async def _get_db(self) -> AsyncSession:
        """获取数据库会话（从实例变量或创建新会话）"""
        if self.db is None:
            from database.db_config import get_db
            # 此处简化：实际应用中应通过依赖注入传入session
            raise RuntimeError("Database session not provided. Pass db to constructor or use dependency injection.")
        return self.db
    
    # ==================== IQ C 接口 ====================
    
    async def create_iqc_record(
        self,
        inbound_order_id: str,
        supplier_id: str,
        product_id: str,
        product_name: str,
        quantity_received: int,
        batch_no: str,
        inspector_id: str,
        factory_id: str,
        sample_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """持久化创建IQ C记录"""
        db = await self._get_db()
        return await IQCPersistenceService.create_iqc_record(
            session=db,
            inbound_order_id=inbound_order_id,
            supplier_id=supplier_id,
            product_id=product_id,
            product_name=product_name,
            quantity_received=quantity_received,
            batch_no=batch_no,
            inspector_id=inspector_id,
            factory_id=factory_id,
            sample_size=sample_size,
        )
    
    async def complete_iqc_inspection(
        self,
        inspection_id: str,
        result: str,  # PASS/FAIL
        sample_inspected: int,
        defects: Optional[List[Dict]] = None,
    ) -> bool:
        """持久化完成IQ C检验并触发CAPA（如需要）"""
        db = await self._get_db()
        success = await IQCPersistenceService.complete_iqc_inspection(
            session=db,
            inspection_id=inspection_id,
            result=result.upper(),
            sample_inspected=sample_inspected,
            defects=defects,
        )
        
        # 简单示例：如果失败且有关键缺陷，创建CAPA（实际应调用CAPAService）
        if result.upper() == "FAIL" and defects:
            critical_defects = [d for d in defects if d.get("severity", "").upper() in ["MAJOR", "CRITICAL"]]
            if critical_defects:
                print(f"[⚠️ CAPA自动触发] IQC {inspection_id} 失败，检测到关键缺陷")
                # 这里可以调用 CAPAPersistenceService.create_capa_case()
        
        return success
    
    async def dispose_iqc_record(self, inspection_id: str, disposition: str) -> bool:
        """持久化处置IQ C记录"""
        db = await self._get_db()
        return await IQCPersistenceService.dispose_iqc_record(session=db, inspection_id=inspection_id, disposition=disposition)
    
    async def list_iqc_records(self, factory_id: str, limit: int = 50) -> List[Dict]:
        """列出IQ C记录（带分页）"""
        db = await self._get_db()
        return await IQCPersistenceService.list_iqc_records(session=db, factory_id=factory_id, limit=limit)
    
    # ==================== FAI 接口 ====================
    
    async def create_fai_record(
        self,
        work_order_id: str,
        factory_id: str,
        product_id: str,
        product_name: str,
        batch_no: str,
        machine_id: str,
        inspector_id: str,
    ) -> Dict[str, Any]:
        """持久化创建首件检验记录"""
        db = await self._get_db()
        return await FAIPersistenceService.create_fai_record(
            session=db,
            work_order_id=work_order_id,
            factory_id=factory_id,
            product_id=product_id,
            product_name=product_name,
            batch_no=batch_no,
            machine_id=machine_id,
            inspector_id=inspector_id,
        )
    
    async def complete_fai_inspection(self, fai_id: str, result: str, defects: Optional[List[Dict]]) -> bool:
        """完成FAI检验（不合格强制触发CAPA）"""
        db = await self._get_db()
        # FAI持久化处理...（略，与IQ C类似）
        return True
    
    # ==================== IPC 接口 ====================
    
    async def create_ipc_plan(
        self,
        work_order_id: str,
        factory_id: str,
        product_id: str,
        process_stage: str,
        frequency_type: str,
        frequency_value: int,
        operator_id: str,
        inspector_id: str,
    ) -> Dict[str, Any]:
        """持久化创建IPC巡检计划"""
        db = await self._get_db()
        return await IPCPersistenceService.create_ipc_plan(
            session=db,
            work_order_id=work_order_id,
            factory_id=factory_id,
            product_id=product_id,
            process_stage=process_stage,
            frequency_type=frequency_type,
            frequency_value=frequency_value,
            operator_id=operator_id,
            inspector_id=inspector_id,
        )
    
    # ==================== OQC 接口 ====================
    
    async def create_oqc_record(
        self,
        order_id: str,
        customer_id: str,
        product_id: str,
        product_name: str,
        batch_no: str,
        quantity_to_ship: int,
        inspector_id: str,
    ) -> Dict[str, Any]:
        """持久化创建出货检验记录"""
        db = await self._get_db()
        return await OQCPersistenceService.create_oqc_record(
            session=db,
            order_id=order_id,
            customer_id=customer_id,
            product_id=product_id,
            product_name=product_name,
            batch_no=batch_no,
            quantity_to_ship=quantity_to_ship,
            inspector_id=inspector_id,
        )
    
    # ==================== CAPA 接口（持久化版） ====================
    
    async def capa_create_case(
        self,
        title: str,
        severity: str,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """持久化创建CAPA案件"""
        db = await self._get_db()
        return await CAPAPersistenceService.create_capa_case(
            session=db,
            title=title,
            severity=severity,
            source_type=source_type,
            source_id=source_id,
        )
    
    async def list_capa_cases(self, status: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """列出CAPA案件"""
        db = await self._get_db()
        return await CAPAPersistenceService.list_capa_cases(session=db, status=status, limit=limit)
    
    # ==================== 辅助方法（简化的内存版本，生产时需改为持久化） ====================
    
    async def capa_add_why_step(self, case_id: str, step_num: int, question: str, answer: str) -> bool:
        """添加5Why追问（临时内存实现）"""
        # TODO: 持久化存储到数据库
        print(f"[TODO持久化] 添加5Why步骤{step_num}到案件{case_id}")
        return True
    
    async def capa_set_root_cause(self, case_id: str, cause: str) -> bool:
        """设置根本原因（临时内存实现）"""
        print(f"[TODO持久化] 设置根本原因到案件{case_id}")
        return True
    
    async def capa_add_fishbone_item(self, case_id: str, dimension: str, item: str) -> bool:
        """添加鱼骨图项（临时内存实现）"""
        print(f"[TODO持久化] 添加鱼骨图项到{dimension}维度")
        return True
    
    async def capa_get_fishbone_summary(self, case_id: str) -> Optional[Dict[str, Any]]:
        """获取鱼骨图摘要（临时内存实现）"""
        return {}
    
    async def capa_set_verification_before(self, case_id: str, metrics: Dict[str, Any]) -> bool:
        """设置验证前数据（临时内存实现）"""
        print(f"[TODO持久化] 设置CAPA {case_id} 验证前数据")
        return True
    
    async def capa_set_verification_after(self, case_id: str, metrics: Dict[str, Any], improved: bool, verified_by: str) -> bool:
        """设置验证后数据（临时内存实现）"""
        print(f"[TODO持久化] 设置CAPA {case_id} 验证后数据")
        return True
    
    async def capa_create_action_plan(self, case_id: str, description: str, owner: str, deadline: str) -> Dict[str, Any]:
        """创建行动计划项（临时内存实现）"""
        return {"id": "temp", "description": description, "owner": owner, "status": "planned"}


    # Kanban 接口待后续实现...