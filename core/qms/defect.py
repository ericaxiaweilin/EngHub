"""
QMS Defect Service - 不良品管理系统（完整ORM实现）

功能:
- 缺陷单创建（批次级追溯，关联检验、工单、物料等）
- 处置方式：返工/返修/报废/特采/退货
- OCAP（纠正预防措施）自动触发
- 批次追溯查询
- 统计分析

使用 SQLAlchemy ORM 进行持久化操作，支持事务和并发控制。
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_

from database.models import WorkOrder, Inventory, User, Inspection, Defect
from core.qms.inspection import AQLLevel, InspectionType, InspectionStatus


class DefectStatus(str, Enum):
    """缺陷状态"""
    OPEN = "open"           # 待处理
    IN_PROGRESS = "in_progress"  # 处理中
    RESOLVED = "resolved"   # 已解决（处置中）
    CLOSED = "closed"       # 已关闭
    CANCELLED = "cancelled"  # 已取消


class DefectType(str, Enum):
    """缺陷类型"""
    APPEARANCE = "appearance"     # 外观缺陷
    DIMENSION = "dimension"        # 尺寸超差
    FUNCTION = "function"          # 功能不良
    PERFORMANCE = "performance"    # 性能不良
    MATERIAL = "material"          # 材料不良
    PROCESS = "process"            # 工艺不良
    OTHER = "other"               # 其他


class Severity(str, Enum):
    """严重等级"""
    CRITICAL = "critical"   # 致命（影响安全、法规）
    MAJOR = "major"         # 重大（影响功能）
    MINOR = "minor"         # 轻微（外观、轻微功能）
    OBSERVATION = "observation"  # 观察项


class DispositionType(str, Enum):
    """处置方式"""
    REWORK = "rework"       # 返工
    REPAIR = "repair"       # 返修
    SCRAP = "scrap"         # 报废
    CONCESSION = "concession"  # 特采（让步使用）
    RETURN = "return"        # 退货


class OcapStatus(str, Enum):
    """OCAP状态"""
    PENDING = "pending"       # 待触发
    TRIGGERED = "triggered"   # 已触发
    IN_PROGRESS = "in_progress"  # 处理中
    COMPLETED = "completed"   # 已完成


class DefectService:
    """不良品服务 - 基于SQLAlchemy ORM的完整实现
    
    Usage:
        async with db_config.session_factory() as session:
            svc = DefectService(session)
            defect = await svc.create_defect(...)
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_defect(
        self,
        factory_id: str,
        defect_type: str,
        quantity: int,
        severity: str = Severity.MINOR.value,
        inspection_id: Optional[str] = None,
        work_order_id: Optional[str] = None,
        material_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        station_id: Optional[str] = None,
        description: str = None,
        created_by: str = None,
        disposition_type: Optional[str] = None,
    ) -> Defect:
        """
        创建缺陷单 - 持久化到数据库
        
        Args:
            factory_id: 工厂ID
            defect_type: 缺陷类型（来自DefectType枚举）
            quantity: 数量
            severity: 严重等级（来自Severity枚举）
            inspection_id: 关联检验单ID（可选）
            work_order_id: 关联工单ID（可选）
            material_id: 物料ID（可选）
            batch_id: 批次ID（可选）
            station_id: 工站ID（可选）
            description: 描述
            created_by: 创建人
            disposition_type: 初始处置方式（可选）
            
        Returns:
            已保存到数据库的Defect对象
        """
        if not factory_id or not defect_type or quantity <= 0:
            raise ValueError("工厂ID、缺陷类型和数量必须有效且大于0")
        
        # 生成唯一缺陷编码
        factory_code = factory_id[:3].upper() if factory_id else "SYS"
        defect_code = f"DEF-{factory_code}-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
        
        # 创建缺陷记录
        defect = Defect(
            id=str(uuid.uuid4()),
            defect_code=defect_code,
            factory_id=factory_id,
            defect_type=defect_type,
            quantity=quantity,
            severity=severity,
            inspection_id=inspection_id,
            work_order_id=work_order_id,
            material_id=material_id,
            batch_id=batch_id,
            station_id=station_id,
            description=description,
            status=DefectStatus.OPEN.value,
            disposition=disposition_type,
            disposition_by=created_by,
            disposition_at=datetime.utcnow() if disposition_type else None,
            ocap_status=OcapStatus.PENDING.value,
            created_by=created_by or "system",
            updated_by=created_by or "system",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        self.db.add(defect)
        await self.db.commit()
        await self.db.refresh(defect)
        
        return defect
    
    async def auto_create_from_inspection(self, inspection_id: str) -> Optional[Defect]:
        """
        从检验结果自动创建缺陷单
        
        当检验结果为FAIL时调用此方法。
        
        Args:
            inspection_id: 检验单ID
            
        Returns:
            创建的Defect对象，或None如果不需要创建（如检验合格）
        """
        # 获取检验单
        inspection = await self._get_inspection_db(inspection_id)
        if not inspection:
            return None
        
        # 只有检验失败时才创建缺陷单
        if inspection.status != InspectionStatus.FAILED.value:
            return None
        
        # 确定缺陷严重等级（根据不良品数量）
        severity = Severity.MAJOR.value if inspection.defective_qty > 10 else Severity.MINOR.value
        
        # 创建缺陷单
        defect = await self.create_defect(
            factory_id=inspection.factory_id,
            defect_type=inspection.material_id or DefectType.OTHER.value,
            quantity=int(inspection.defective_qty) if inspection.defective_qty else 0,
            severity=severity,
            inspection_id=inspection.id,
            work_order_id=inspection.work_order_id,
            material_id=inspection.material_id,
            batch_id=inspection.batch_id,
            station_id=inspector_id or "SYSTEM",
            description=f"检验不合格，检验单: {inspection.inspection_code}",
            created_by=inspector_id,
        )
        
        # 触发OCAP检查
        await self.trigger_ocap(defect.id)
        
        return defect
    
    async def submit_disposition(
        self,
        defect_id: str,
        disposition: str,
        disposition_by: str,
        disposition_qty: Optional[int] = None,
        remark: str = None,
    ) -> Defect:
        """
        提交处置方案 - 更新缺陷单状态和处置信息
        
        Args:
            defect_id: 缺陷ID
            disposition: 处置方式（rework/repair/scrap/concession/return）
            disposition_by: 处置人
            disposition_qty: 处置数量（部分处置时使用）
            remark: 备注
            
        Returns:
            更新后的缺陷单对象
            
        Raises:
            ValueError: 缺陷不存在、处置方式无效或状态不合法
        """
        # 获取缺陷单
        defect = await self._get_defect_db(defect_id)
        if not defect:
            raise ValueError(f"缺陷单 {defect_id} 不存在")
        
        # 验证处置方式
        valid_dispositions = [d.value for d in DispositionType]
        if disposition not in valid_dispositions:
            raise ValueError(f"无效的处置方式: {disposition}")
        
        # 验证状态变更合法性
        allowed_transitions = {
            DefectStatus.OPEN.value: set(valid_dispositions),
            DefectStatus.IN_PROGRESS.value: set(valid_dispositions),
        }
        
        if defect.status not in allowed_transitions or disposition not in allowed_transitions[defect.status]:
            raise ValueError(f"状态变更不允许: {defect.status} -> {disposition}")
        
        # 计算实际处置数量
        actual_qty = disposition_qty if disposition_qty is not None else defect.quantity
        
        # 更新处置信息
        defect.disposition = disposition
        defect.disposition_by = disposition_by
        defect.disposition_at = datetime.utcnow()
        defect.disposition_qty = actual_qty
        defect.disposition_remark = remark
        
        # 根据处置方式更新主状态
        if disposition == DispositionType.SCRAP.value:
            defect.status = DefectStatus.RESOLVED.value
        elif disposition == DispositionType.RETURN.value:
            defect.status = DefectStatus.RESOLVED.value
        else:
            defect.status = DefectStatus.IN_PROGRESS.value
        
        defect.updated_at = datetime.utcnow()
        defect.updated_by = disposition_by
        
        # 提交更改
        await self.db.commit()
        await self.db.refresh(defect)
        
        return defect
    
    async def trigger_ocap(self, defect_id: str) -> Defect:
        """
        触发OCAP（纠正预防措施）
        
        规则:
        1. CRITICAL级别 - 必须触发
        2. MAJOR级别 - 数量>=5时触发
        3. 工艺/材料类缺陷 - 数量>=3时触发
        
        Args:
            defect_id: 缺陷ID
            
        Returns:
            更新后的缺陷单对象
        """
        defect = await self._get_defect_db(defect_id)
        if not defect:
            raise ValueError(f"缺陷单 {defect_id} 不存在")
        
        ocap_triggered = False
        reason = None
        
        # 检查是否需要触发OCAP
        if defect.severity == Severity.CRITICAL.value:
            ocap_triggered = True
            reason = "致命缺陷，强制触发OCAP"
        elif defect.severity == Severity.MAJOR.value and defect.quantity >= 5:
            ocap_triggered = True
            reason = "重大缺陷数量超过阈值（>=5）"
        elif defect.defect_type in [DefectType.PROCESS.value, DefectType.MATERIAL.value] and defect.quantity >= 3:
            ocap_triggered = True
            reason = "工艺/材料问题需要分析（>=3）"
        
        if ocap_triggered:
            defect.ocap_status = OcapStatus.TRIGGERED.value
            defect.ocap_trigger_reason = reason
            defect.ocap_triggered_at = datetime.utcnow()
            defect.updated_at = datetime.utcnow()
            
            # TODO: 这里应该创建OCAP记录并通知相关人员
            # await self._create_ocap_record(defect, reason)
            # await self._notify_stakeholders(defect)
            
            await self.db.commit()
            await self.db.refresh(defect)
        
        return defect
    
    async def get_defect(self, defect_id: str) -> Optional[Dict[str, Any]]:
        """获取缺陷单详情（返回字典格式）"""
        defect = await self._get_defect_db(defect_id)
        if defect:
            return defect.to_dict()
        return None
    
    async def list_defects(
        self,
        factory_id: str,
        status: Optional[str] = None,
        defect_type: Optional[str] = None,
        work_order_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """
        获取缺陷单列表（带分页和过滤）
        
        Returns:
            {items: [], total: int, ...}
        """
        # 构建基础查询
        query = select(Defect).where(Defect.factory_id == factory_id)
        
        if status:
            query = query.where(Defect.status == status)
        if defect_type:
            query = query.where(Defect.defect_type == defect_type)
        if work_order_id:
            query = query.where(Defect.work_order_id == work_order_id)
        if batch_id:
            query = query.where(Defect.batch_id == batch_id)
        if from_date:
            query = query.where(Defect.created_at >= from_date)
        if to_date:
            query = query.where(Defect.created_at <= to_date)
        
        # 计数
        count_query = select(func.count()).select_from(Defect).where(Defect.factory_id == factory_id)
        if status:
            count_query = count_query.where(Defect.status == status)
        if defect_type:
            count_query = count_query.where(Defect.defect_type == defect_type)
        if work_order_id:
            count_query = count_query.where(Defect.work_order_id == work_order_id)
        if batch_id:
            count_query = count_query.where(Defect.batch_id == batch_id)
        if from_date:
            count_query = count_query.where(Defect.created_at >= from_date)
        if to_date:
            count_query = count_query.where(Defect.created_at <= to_date)
        
        total = await (await self.db.execute(count_query)).scalar() or 0
        
        # 分页
        query = query.offset((page - 1) * page_size).limit(page_size)
        results = await self.db.execute(query)
        defects = results.scalars().all()
        
        return {
            "items": [d.to_dict() for d in defects],
            "total": int(total),
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }
    
    async def trace_by_batch(self, batch_id: str) -> Dict[str, Any]:
        """
        批次追溯 - 查找与该批次相关的所有缺陷和相关数据
        
        Returns:
            包含批次信息、缺陷记录等的追溯报告
        """
        # 查找该批次的缺陷
        defect_result = await self.db.execute(
            select(Defect).where(Defect.batch_id == batch_id)
        )
        defects = defect_result.scalars().all()
        
        # 收集相关信息
        related_work_orders = set()
        related_inspections = []
        
        for defect in defects:
            if defect.work_order_id:
                related_work_orders.add(defect.work_order_id)
            if defect.inspection_id:
                related_inspections.append(defect.inspection_id)
        
        # 查询相关工单详情
        work_orders = []
        for wo_id in related_work_orders:
            wo_result = await self.db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
            wo = wo_result.scalar_one_or_none()
            if wo:
                work_orders.append(wo.to_dict())
        
        return {
            "batch_id": batch_id,
            "factory_id": defects[0].factory_id if defects else None,
            "defects_count": len(defects),
            "defects": [d.to_dict() for d in defects],
            "related_work_orders": work_orders,
            "related_inspections": related_inspections,
        }
    
    async def get_statistics(
        self,
        factory_id: str,
        from_date: datetime,
        to_date: datetime,
    ) -> Dict[str, Any]:
        """获取缺陷统计数据"""
        # 总数
        count_stmt = select(func.count()).where(
            Defect.factory_id == factory_id,
            Defect.created_at >= from_date,
            Defect.created_at <= to_date,
        )
        total = await (await self.db.execute(count_stmt)).scalar() or 0
        
        # 按类型分布
        type_stmt = select(Defect.defect_type, func.count()).where(
            Defect.factory_id == factory_id,
            Defect.created_at >= from_date,
            Defect.created_at <= to_date,
        ).group_by(Defect.defect_type)
        type_result = await self.db.execute(type_stmt)
        type_breakdown = {str(row[0]): int(row[1]) for row in type_result.fetchall()}
        
        # 按严重程度分布
        severity_stmt = select(Defect.severity, func.count()).where(
            Defect.factory_id == factory_id,
            Defect.created_at >= from_date,
            Defect.created_at <= to_date,
        ).group_by(Defect.severity)
        severity_result = await self.db.execute(severity_stmt)
        severity_breakdown = {str(row[0]): int(row[1]) for row in severity_result.fetchall()}
        
        # 按处置方式分布
        disposition_stmt = select(Defect.disposition, func.count()).where(
            Defect.factory_id == factory_id,
            Defect.created_at >= from_date,
            Defect.created_at <= to_date,
        ).group_by(Defect.disposition)
        disposition_result = await self.db.execute(disposition_stmt)
        disposition_breakdown = {str(row[0]): int(row[1]) for row in disposition_result.fetchall() if row[0]}
        
        # 按状态分布
        status_stmt = select(Defect.status, func.count()).where(
            Defect.factory_id == factory_id,
            Defect.created_at >= from_date,
            Defect.created_at <= to_date,
        ).group_by(Defect.status)
        status_result = await self.db.execute(status_stmt)
        status_breakdown = {str(row[0]): int(row[1]) for row in status_result.fetchall()}
        
        return {
            "period": f"{from_date.date()} - {to_date.date()}",
            "factory_id": factory_id,
            "total_defects": int(total),
            "by_type": type_breakdown,
            "by_severity": severity_breakdown,
            "by_disposition": disposition_breakdown,
            "by_status": status_breakdown,
            "resolved_rate": round(status_breakdown.get('closed', 0) / total * 100, 2) if total > 0 else 0.0,
        }
    
    async def resolve_defect(self, defect_id: str, resolved_by: str, remarks: str = None) -> Defect:
        """关闭缺陷单（解决后关闭）"""
        defect = await self._get_defect_db(defect_id)
        if not defect:
            raise ValueError(f"缺陷单 {defect_id} 不存在")
        
        if defect.status not in [DefectStatus.OPEN.value, DefectStatus.IN_PROGRESS.value]:
            raise ValueError(f"缺陷单状态为 {defect.status}，无法关闭")
        
        defect.status = DefectStatus.CLOSED.value
        defect.resolved_by = resolved_by
        defect.resolved_at = datetime.utcnow()
        defect.remarks = remarks
        defect.updated_at = datetime.utcnow()
        defect.updated_by = resolved_by
        
        await self.db.commit()
        await self.db.refresh(defect)
        
        return defect
    
    # ===== 内部辅助方法 =====
    
    async def _get_defect_db(self, defect_id: str) -> Optional[Defect]:
        """从数据库获取缺陷记录"""
        result = await self.db.execute(select(Defect).where(Defect.id == defect_id))
        return result.scalar_one_or_none()
    
    async def _get_inspection_db(self, inspection_id: str) -> Optional[Inspection]:
        """从数据库获取检验记录（用于auto_create_from_inspection）"""
        result = await self.db.execute(select(Inspection).where(Inspection.id == inspection_id))
        return result.scalar_one_or_none()