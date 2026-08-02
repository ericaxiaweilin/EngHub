"""
QMS 持久化服务层 - 基于 SQLAlchemy ORM 的数据库操作封装

此服务提供 IQC、FAI、IPC、OQC 和 CAPA 的数据库 CRUD 操作，
作为对内存服务的生产级替换。
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

# 导入模型
from database.models import (
    QualityInspection, QualityDefect, CAPACase, InboundOrder, WorkOrder,
)


class IQCPersistenceService:
    """IQ C 持久化服务"""
    
    @staticmethod
    async def create_iqc_record(
        session: AsyncSession,
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
        """在数据库中创建 IQ C 记录"""
        # 获取收货单信息验证存在性
        inbound_order = await session.get(InboundOrder, inbound_order_id)
        if not inbound_order:
            raise ValueError(f"收货单 {inbound_order_id} 不存在")
        
        # 计算默认抽样数量
        if sample_size is None:
            sample_size = max(5, int(quantity_received * 0.1))
        
        # 创建 QualityInspection 记录（inspect_type="IQC"）
        inspection_id = str(inbound_order.id)[:8]  # 简化：使用简短ID
        qms_record = QualityInspection(
            id=inspection_id,
            factory_id=factory_id,
            work_order_id=inbound_order.id,  # 关联收货单
            inspect_type="IQC",
            inspector_id=inspector_id,
            sample_qty=sample_size,
            defect_qty=0,
            result="PENDING",  # 待检验状态
            defect_details={
                "sampling_method": "AQL",
                "aql_level": "II",
                "batch_no": batch_no,
                "supplier": supplier_id,
            },
            remark=f"IQC 检验 - 供应商{supplier_id}来料",
            created_at=datetime.utcnow(),
        )
        
        session.add(qms_record)
        await session.commit()
        await session.refresh(qms_record)
        
        return {
            "id": inspection_id,
            "inbound_order_id": inbound_order_id,
            "supplier_id": supplier_id,
            "product_id": product_id,
            "batch_no": batch_no,
            "status": "pending",
            "created_at": qms_record.created_at.isoformat(),
        }
    
    @staticmethod
    async def complete_iqc_inspection(
        session: AsyncSession,
        inspection_id: str,
        result: str,  # PASS/FAIL
        sample_inspected: int,
        defects: Optional[List[Dict]] = None,
    ) -> bool:
        """完成 IQ C 检验并记录结果到数据库"""
        qms_record = await session.get(QualityInspection, inspection_id)
        if not qms_record:
            return False
        
        qms_record.result = result.upper()
        qms_record.sample_qty = sample_inspected
        qms_record.defect_qty = len(defects) or 0
        
        if defects:
            qms_record.defect_details = {
                "defects": defects,
                "total_defects": len(defects),
            }
        
        await session.commit()
        
        # 如果有缺陷，在数据库中创建缺陷记录
        if defects:
            for defect in defects:
                defect_rec = QualityDefect(
                    inspection_id=inspection_id,
                    defect_code=defect.get("code"),
                    defect_category=defect.get("category"),
                    defect_description=defect.get("description"),
                    quantity=defect.get("quantity", 1),
                )
                session.add(defect_rec)
            await session.commit()
        
        return True
    
    @staticmethod
    async def dispose_iqc_record(session: AsyncSession, inspection_id: str, disposition: str) -> bool:
        """处置 IQ C 记录"""
        qms_record = await session.get(QualityInspection, inspection_id)
        if not qms_record:
            return False
        
        qms_record.disposition = disposition
        qms_record.updated_at = datetime.utcnow()
        await session.commit()
        return True
    
    @staticmethod
    async def list_iqc_records(
        session: AsyncSession,
        factory_id: str,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """列出 IQ C 记录"""
        query = select(QualityInspection).where(
            QualityInspection.factory_id == factory_id,
            QualityInspection.inspect_type == "IQC"
        )
        if status:
            query = query.where(QualityInspection.result == status.upper())
        
        query = query.order_by(QualityInspection.created_at.desc()).limit(limit)
        result = await session.execute(query)
        records = result.scalars().all()
        
        return [
            {
                "id": r.id,
                "factory_id": r.factory_id,
                "product_id": r.product_id,
                "batch_no": r.defect_details.get("batch_no", "") if r.defect_details else "",
                "status": r.result.lower(),
                "sample_size": r.sample_qty,
                "defects": r.defect_qty,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]


class CAPAPersistenceService:
    """CAPA 持久化服务"""
    
    @staticmethod
    async def create_capa_case(
        session: AsyncSession,
        title: str,
        severity: str,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """在数据库中创建 CAPA 案件"""
        case_number = f"CAPA-{datetime.utcnow().strftime('%Y')}-{CAPAPersistenceService._get_next_number()}"
        
        capa = CAPACase(
            id=str(hash(title + str(datetime.utcnow())))[:36],  # 简化生成唯一ID
            case_number=case_number,
            title=title,
            severity=severity,
            source_type=source_type,
            source_id=source_id if source_id else "",
            created_at=datetime.utcnow(),
        )
        
        session.add(capa)
        await session.commit()
        await session.refresh(capa)
        
        return {
            "id": capa.id,
            "case_number": capa.case_number,
            "title": capa.title,
            "severity": capa.severity,
            "status": capa.status,
            "created_at": capa.created_at.isoformat(),
        }
    
    @staticmethod
    async def _get_next_number() -> int:
        """获取下一个 CAPA 序号（简化实现）"""
        # 实际应从数据库查询最大值 + 1
        return 1
    
    @staticmethod
    async def list_capa_cases(
        session: AsyncSession,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """列出 CAPA 案件"""
        query = select(CAPACase)
        if status:
            query = query.where(CAPACase.status == status)
        
        query = query.order_by(CAPACase.created_at.desc()).limit(limit)
        result = await session.execute(query)
        cases = result.scalars().all()
        
        return [
            {
                "id": c.id,
                "case_number": c.case_number,
                "title": c.title,
                "severity": c.severity,
                "status": c.status,
                "created_at": c.created_at.isoformat(),
            }
            for c in cases
        ]


class FAIPersistenceService:
    """FAI 持久化服务 - 复用 QualityInspection 表，inspect_type='FAI'"""
    
    @staticmethod
    async def create_fai_record(
        session: AsyncSession,
        work_order_id: str,
        factory_id: str,
        product_id: str,
        product_name: str,
        batch_no: str,
        machine_id: str,
        inspector_id: str,
    ) -> Dict[str, Any]:
        """创建 FAI 记录（使用 QualityInspection 表）"""
        # 简化的实现：直接在 QualityInspection 中记录 FAI
        fai_id = str(hash(f"{work_order_id}_{product_id}"))[:36]
        
        fai = QualityInspection(
            id=fai_id,
            factory_id=factory_id,
            work_order_id=work_order_id,
            inspect_type="FAI",  # 首件检验类型
            inspector_id=inspector_id,
            sample_qty=1,
            defect_qty=0,
            result="PENDING",
            defect_details={
                "machine_id": machine_id,
                "batch_no": batch_no,
            },
            remark=f"FAI 检验 - {product_name}",
            created_at=datetime.utcnow(),
        )
        
        session.add(fai)
        await session.commit()
        await session.refresh(fai)
        
        return {
            "id": fai_id,
            "work_order_id": work_order_id,
            "product_id": product_id,
            "status": "pending",
        }


class IPCPersistenceService:
    """IPC 持久化服务"""
    
    @staticmethod
    async def create_ipc_plan(
        session: AsyncSession,
        work_order_id: str,
        factory_id: str,
        product_id: str,
        process_stage: str,
        frequency_type: str,
        frequency_value: int,
        operator_id: str,
        inspector_id: str,
    ) -> Dict[str, Any]:
        """创建 IPC 巡检计划（存储为 QualityInspection，inspect_type='IPC'）"""
        ipc_id = str(hash(f"{work_order_id}_{process_stage}"))[:36]
        
        ipc = QualityInspection(
            id=ipc_id,
            factory_id=factory_id,
            work_order_id=work_order_id,
            inspect_type="IPC",
            inspector_id=inspector_id,
            sample_qty=frequency_value,  # 复用 sample_qty 字段存储频率值
            defect_qty=0,
            result="PENDING",
            defect_details={
                "process_stage": process_stage,
                "frequency_type": frequency_type,
                "operator_id": operator_id,
            },
            remark=f"IPC 巡检 - {process_stage}",
            created_at=datetime.utcnow(),
        )
        
        session.add(ipc)
        await session.commit()
        await session.refresh(ipc)
        
        return {
            "id": ipc_id,
            "work_order_id": work_order_id,
            "process_stage": process_stage,
            "status": "pending",
        }


class OQCPersistenceService:
    """OQC 持久化服务"""
    
    @staticmethod
    async def create_oqc_record(
        session: AsyncSession,
        order_id: str,
        customer_id: str,
        product_id: str,
        product_name: str,
        batch_no: str,
        quantity_to_ship: int,
        inspector_id: str,
    ) -> Dict[str, Any]:
        """创建出货检验记录（QualityInspection 类型 OQC）"""
        oqc_id = str(hash(order_id))[:36]
        
        oqc = QualityInspection(
            id=oqc_id,
            factory_id="",  # OQC可能不关联特定工厂
            work_order_id="",
            inspect_type="OQC",  # 出货检验
            inspector_id=inspector_id,
            sample_qty=quantity_to_ship,
            defect_qty=0,
            result="PENDING",
            defect_details={
                "customer_id": customer_id,
                "batch_no": batch_no,
            },
            remark=f"OQC 检验 - {product_name}",
            created_at=datetime.utcnow(),
        )
        
        session.add(oqc)
        await session.commit()
        await session.refresh(oqc)
        
        return {
            "id": oqc_id,
            "order_id": order_id,
            "customer_id": customer_id,
            "status": "pending",
        }
