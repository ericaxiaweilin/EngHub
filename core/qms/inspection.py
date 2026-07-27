"""
QMS Inspection Service - 检验管理系统（完整ORM实现）

功能:
- IQC 来料检验（独立创建，不关联工单）
- IPQC 过程检验（必须关联工单）
- FQC 最终检验（必须关联工单/出货）
- OQC出货检验（必须关联工单）
- AQL判定逻辑
- 检验结果提交与不良自动触发
- 批次级追溯
- 统计分析

使用 SQLAlchemy ORM 进行数据库操作，支持完整的CRUD和事务管理。
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
from sqlalchemy import select, update, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    WorkOrder, Product, Station, Equipment, User,
    Inspection, Defect, Inventory, InboundOrder, OutboundOrder,
)
from core.qms.defect import (
    DefectService, DefectType, Severity, DispositionType, OcapStatus,
)


class InspectionType(str, Enum):
    """检验类型"""
    IQC = "iqc"         # 来料检验
    IPQC = "ipqc"       # 过程检验
    FQC = "fqc"         # 最终检验
    OQC = "oqc"         # 出货检验


class InspectionStatus(str, Enum):
    """检验状态"""
    PENDING = "pending"       # 待检验
    IN_PROGRESS = "in_progress"  # 检验中
    PASSED = "passed"         # 合格
    FAILED = "failed"         # 不合格
    REJECTED = "rejected"     # 拒收


class AQLLevel(str, Enum):
    """AQL检验水平"""
    GENERAL_I = "general_i"
    GENERAL_II = "general_ii"
    GENERAL_III = "general_iii"
    SPECIAL_S1 = "special_s1"
    SPECIAL_S2 = "special_s2"


class AQLService:
    """AQL查表计算服务 - 提供完整的AQL判定逻辑"""
    
    SAMPLE_SIZE_CODES = {
        (2, 8): "A", (9, 15): "B", (16, 25): "C", (26, 50): "D",
        (51, 90): "E", (91, 150): "F", (151, 280): "G", (281, 500): "H",
        (501, 1200): "J", (1201, 3200): "K", (3201, 10000): "L",
    }
    
    AQL_STANDARDS = {
        "A": {"0.65": (1, 2), "1.0": (2, 3), "1.5": (3, 4)},
        "B": {"0.65": (1, 2), "1.0": (2, 3), "1.5": (3, 4)},
        "C": {"0.65": (1, 2), "1.0": (2, 3), "1.5": (3, 4), "2.5": (5, 6)},
        "D": {"0.65": (1, 2), "1.0": (2, 3), "1.5": (3, 4), "2.5": (5, 6)},
        "E": {"0.65": (1, 2), "1.0": (2, 3), "1.5": (3, 4), "2.5": (5, 6)},
        "F": {"0.40": (1, 2), "0.65": (2, 3), "1.0": (3, 4), "1.5": (5, 6), "2.5": (7, 8)},
        "G": {"0.40": (1, 2), "0.65": (2, 3), "1.0": (3, 4), "1.5": (5, 6), "2.5": (7, 8)},
        "H": {"0.25": (1, 2), "0.40": (2, 3), "0.65": (3, 4), "1.0": (5, 6), "1.5": (7, 8), "2.5": (10, 11)},
        "J": {"0.15": (1, 2), "0.25": (2, 3), "0.40": (3, 4), "0.65": (5, 6), "1.0": (7, 8), "1.5": (10, 11)},
    }
    
    def get_sample_size_code(self, batch_size: int) -> str:
        """根据批量大小获取样本大小代码"""
        for (min_size, max_size), code in self.SAMPLE_SIZE_CODES.items():
            if min_size <= batch_size <= max_size:
                return code
        return "L"
    
    def calculate_sample_size(self, batch_size: int, level: str = AQLLevel.GENERAL_II.value) -> int:
        """计算样本大小"""
        code = self.get_sample_size_code(batch_size)
        sample_sizes = {"A": 2, "B": 3, "C": 5, "D": 8, "E": 13, "F": 20, "G": 32, "H": 50, "J": 80, "K": 125, "L": 200}
        return sample_sizes.get(code, 200)
    
    def evaluate(self, batch_size: int, defective_count: int, aql_level: float = 1.0) -> Dict[str, Any]:
        """AQL判定
        
        Returns:
            dict with keys: result ('pass'/'fail'), sample_size, ac, re, defective_count, aql_level
        """
        code = self.get_sample_size_code(batch_size)
        ac_re = self.AQL_STANDARDS.get(code, {}).get(str(aql_level), (1, 2))
        ac, re = ac_re
        sample_size = self.calculate_sample_size(batch_size)
        result = "pass" if defective_count <= ac else "fail"
        
        return {
            "result": result,
            "sample_size": sample_size,
            "ac": ac,
            "re": re,
            "defective_count": defective_count,
            "aql_level": aql_level,
        }


class InspectionService:
    """检验服务 - 基于SQLAlchemy ORM的完整实现
    
    使用模式:
        async with db_config.session_factory() as session:
            svc = InspectionService(session)
            # 调用服务方法...
    """
    
    def __init__(self, db: AsyncSession):
        """初始化检验服务
        
        Args:
            db: 异步数据库会话对象
        """
        self.db: AsyncSession = db
        self.aql_service: AQLService = AQLService()
        self.defect_service: DefectService = DefectService(db)
    
    def generate_inspection_code(self, factory_id: str, inspection_type: str) -> str:
        """生成唯一检验码
        
        Args:
            factory_id: 工厂ID
            inspection_type: 检验类型（iqc/ipqc/fqc/oqc）
            
        Returns:
            格式为 INS-F1-IQC-20260727-XXXXXX 的检验码
        """
        factory_code = factory_id[:3].upper() if factory_id else "SYS"
        today = datetime.now().strftime("%Y%m%d")
        suffix = str(uuid.uuid4())[:6].upper()
        return f"INS-{factory_code}-{inspection_type.upper()}-{today}-{suffix}"
    
    async def create_inspection(
        self,
        factory_id: str,
        inspection_type: str,
        product_id: Optional[str] = None,
        material_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        batch_size: int = 0,
        work_order_id: Optional[str] = None,
        aql_level: float = 1.0,
        inspection_level: str = AQLLevel.GENERAL_II.value,
        created_by: str = None,
        supplier_id: Optional[str] = None,
        purchase_order_id: Optional[str] = None,
    ) -> Inspection:
        """
        创建检验单 - ORM持久化到数据库
        
        业务规则:
        - IQC: material_id必填，work_order_id可选
        - IPQC/FQC/OQC: work_order_id必填
        
        Args:
            factory_id: 工厂ID
            inspection_type: 检验类型
            product_id: 产品ID（可选）
            material_id: 物料ID（IQC必需）
            batch_id: 批次号（可选）
            batch_size: 批量大小
            work_order_id: 工单ID（非IQC必需）
            aql_level: AQL等级
            inspection_level: AQL检验水平
            created_by: 创建人
            supplier_id: 供应商ID（IQC）
            purchase_order_id: 采购单号（IQC）
            
        Returns:
            已保存到数据库的Inspection对象
            
        Raises:
            ValueError: 必填字段验证失败
        """
        # 验证必填字段
        if inspection_type == InspectionType.IQC.value:
            if not material_id:
                raise ValueError("IQC检验必须指定物料")
        else:
            if not work_order_id:
                raise ValueError(f"{inspection_type}检验必须关联工单")
        
        # 检查工单是否存在（非IQC时）
        if work_order_id and inspection_type != InspectionType.IQC.value:
            wo_result = await self.db.execute(select(WorkOrder).where(WorkOrder.id == work_order_id))
            if not wo_result.scalar_one_or_none():
                raise ValueError(f"工单 {work_order_id} 不存在")
        
        # 计算样本大小
        sample_size = None
        if batch_size > 0:
            sample_size = self.aql_service.calculate_sample_size(batch_size, inspection_level)
        
        # 构建检验记录
        inspection = Inspection(
            id=str(uuid.uuid4()),
            inspection_code=self.generate_inspection_code(factory_id, inspection_type),
            factory_id=factory_id,
            inspection_type=inspection_type,
            product_id=product_id,
            material_id=material_id,
            batch_id=batch_id,
            batch_size=batch_size,
            work_order_id=work_order_id,
            aql_level=aql_level,
            inspection_level=inspection_level,
            sample_size=sample_size,
            status=InspectionStatus.PENDING.value,
            created_by=created_by or "system",
            updated_by=created_by or "system",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
        )
        
        # 添加到会话并提交
        self.db.add(inspection)
        await self.db.commit()
        await self.db.refresh(inspection)
        
        return inspection
    
    async def get_inspection(self, inspection_id: str) -> Optional[Inspection]:
        """获取检验单详情
        
        Args:
            inspection_id: 检验单ID
            
        Returns:
            Inspection对象或None
        """
        result = await self.db.execute(select(Inspection).where(Inspection.id == inspection_id))
        return result.scalar_one_or_none()
    
    async def list_inspections(
        self,
        factory_id: str,
        inspection_type: Optional[str] = None,
        status: Optional[str] = None,
        work_order_id: Optional[str] = None,
        material_id: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """
        获取检验单列表（带分页和过滤）
        
        Returns:
            {items: [], total: int, page: int, page_size: int, total_pages: int}
        """
        # 构建查询
        query = select(Inspection).where(Inspection.factory_id == factory_id)
        
        if inspection_type:
            query = query.where(Inspection.inspection_type == inspection_type)
        if status:
            query = query.where(Inspection.status == status)
        if work_order_id:
            query = query.where(Inspection.work_order_id == work_order_id)
        if material_id:
            query = query.where(Inspection.material_id == material_id)
        if from_date:
            query = query.where(Inspection.created_at >= from_date)
        if to_date:
            query = query.where(Inspection.created_at <= to_date)
        
        # 计算总数
        count_query = select(func.count()).select_from(Inspection).where(Inspection.factory_id == factory_id)
        if inspection_type:
            count_query = count_query.where(Inspection.inspection_type == inspection_type)
        if status:
            count_query = count_query.where(Inspection.status == status)
        if work_order_id:
            count_query = count_query.where(Inspection.work_order_id == work_order_id)
        if material_id:
            count_query = count_query.where(Inspection.material_id == material_id)
        if from_date:
            count_query = count_query.where(Inspection.created_at >= from_date)
        if to_date:
            count_query = count_query.where(Inspection.created_at <= to_date)
        
        total = await (await self.db.execute(count_query)).scalar() or 0
        
        # 分页查询
        query = query.offset((page - 1) * page_size).limit(page_size)
        results = await self.db.execute(query)
        inspections = results.scalars().all()
        
        return {
            "items": [insp.to_dict() for insp in inspections],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }
    
    async def submit_inspection_result(
        self,
        inspection_id: str,
        inspected_qty: int,
        defective_qty: int,
        defect_details: Optional[List[Dict[str, Any]]] = None,
        inspector_id: str = None,
        remarks: str = None,
    ) -> Inspection:
        """
        提交检验结果 - 执行AQL判定并可能触发缺陷单
        
        Args:
            inspection_id: 检验单ID
            inspected_qty: 检验数量
            defective_qty: 不良数量
            defect_details: 缺陷详细信息列表
            inspector_id: 检验员ID
            remarks: 备注
            
        Returns:
            更新后的Inspection对象
            
        Raises:
            ValueError: 检验单不存在或已提交
        """
        # 获取检验单
        inspection = await self.get_inspection(inspection_id)
        if not inspection:
            raise ValueError(f"检验单 {inspection_id} 不存在")
        
        # 检查状态是否可以提交
        if inspection.status in (InspectionStatus.PASSED.value, InspectionStatus.FAILED.value):
            raise ValueError("检验结果已提交，不可重复提交")
        
        # AQL判定
        aql_result = self.aql_service.evaluate(
            batch_size=inspection.batch_size,
            defective_count=defective_qty,
            aql_level=inspection.aql_level,
        )
        
        # 确定新状态
        new_status = InspectionStatus.PASSED.value if aql_result["result"] == "pass" else InspectionStatus.FAILED.value
        
        # 更新检验单
        update_data = {
            "status": new_status,
            "inspected_at": datetime.utcnow(),
            "inspected_qty": inspected_qty,
            "defective_qty": defective_qty,
            "inspector_id": inspector_id,
            "aql_result": aql_result,
            "remarks": remarks,
            "updated_at": datetime.utcnow(),
            "updated_by": inspector_id or "system",
        }
        
        # 添加缺陷详情（如果有）
        if defect_details:
            update_data["defect_details"] = defect_details
        
        # 执行更新
        update_stmt = (
            update(Inspection)
            .where(Inspection.id == inspection_id)
            .values(update_data)
        )
        await self.db.execute(update_stmt)
        await self.db.commit()
        
        # 如果不合格且不良品数>0，自动创建缺陷单
        if new_status == InspectionStatus.FAILED.value and defective_qty > 0:
            await self._create_defect_on_failure(inspection, defective_qty, defect_details, inspector_id, remarks)
        
        # 刷新并返回
        await self.db.refresh(inspection)
        return inspection
    
    async def _create_defect_on_failure(
        self,
        inspection: Inspection,
        defective_qty: int,
        defect_details: Optional[List[Dict]],
        inspector_id: str,
        remarks: str,
    ) -> Defect:
        """检验不合格时自动创建缺陷单"""
        # 确定严重等级
        severity = Severity.MINOR.value
        if defect_details:
            for detail in defect_details or []:
                if detail.get("severity") in ["critical", "major"]:
                    severity = detail["severity"]
                    break
        
        # 创建缺陷单
        defect = await self.defect_service.create_defect(
            db=self.db,
            factory_id=inspection.factory_id,
            defect_type=inspection.material_id or DefectType.OTHER.value,
            quantity=defective_qty,
            severity=severity,
            inspection_id=inspection.id,
            work_order_id=inspection.work_order_id,
            material_id=inspection.material_id,
            batch_id=inspection.batch_id,
            station_id=inspector_id,
            description=f"检验不合格，检验单: {inspection.inspection_code}, {remarks or ''}",
            created_by=inspector_id or "system",
        )
        
        return defect
    
    async def start_inspection(self, inspection_id: str, started_by: str) -> Inspection:
        """开始检验（从 pending 变为 in_progress）"""
        inspection = await self.get_inspection(inspection_id)
        if not inspection:
            raise ValueError(f"检验单 {inspection_id} 不存在")
        
        if inspection.status != InspectionStatus.PENDING.value:
            raise ValueError(f"检验单当前状态为 {inspection.status}，不能开始检验")
        
        update_stmt = (
            update(Inspection)
            .where(Inspection.id == inspection_id)
            .values({
                "status": InspectionStatus.IN_PROGRESS.value,
                "started_at": datetime.utcnow(),
                "started_by": started_by,
                "updated_at": datetime.utcnow(),
                "updated_by": started_by,
            })
        )
        await self.db.execute(update_stmt)
        await self.db.commit()
        await self.db.refresh(inspection)
        return inspection
    
    async def associate_work_order(self, inspection_id: str, work_order_id: str) -> Inspection:
        """将IQC检验单关联到工单"""
        inspection = await self.get_inspection(inspection_id)
        if not inspection:
            raise ValueError(f"检验单 {inspection_id} 不存在")
        
        if inspection.inspection_type != InspectionType.IQC.value:
            raise ValueError("只有IQC检验单可以关联工单")
        
        if inspection.work_order_id:
            raise ValueError("该检验单已关联工单")
        
        # 验证工单存在
        wo_result = await self.db.execute(select(WorkOrder).where(WorkOrder.id == work_order_id))
        if not wo_result.scalar_one_or_none():
            raise ValueError(f"工单 {work_order_id} 不存在")
        
        update_stmt = (
            update(Inspection)
            .where(Inspection.id == inspection_id)
            .values({
                "work_order_id": work_order_id,
                "updated_at": datetime.utcnow(),
                "updated_by": "system",
            })
        )
        await self.db.execute(update_stmt)
        await self.db.commit()
        await self.db.refresh(inspection)
        return inspection
    
    async def trace_by_batch(self, factory_id: str, batch_id: str) -> Dict[str, Any]:
        """
        批次追溯 - 查找与该批次相关的所有检验记录和相关数据
        
        Returns:
            包含批次信息、检验记录、工单关联等的追溯报告
        """
        # 查找该批次的检验记录
        inspection_result = await self.db.execute(
            select(Inspection).where(
                Inspection.factory_id == factory_id,
                Inspection.batch_id == batch_id,
            )
        )
        inspections = inspection_result.scalars().all()
        
        # 查找相关工单
        work_orders = set()
        for insp in inspections:
            if insp.work_order_id:
                work_orders.add(insp.work_order_id)
        
        # 获取工单详情
        work_order_details = []
        for wo_id in work_orders:
            wo_result = await self.db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
            wo = wo_result.scalar_one_or_none()
            if wo:
                work_order_details.append(wo.to_dict())
        
        return {
            "batch_id": batch_id,
            "factory_id": factory_id,
            "inspections": [i.to_dict() for i in inspections],
            "related_work_orders": work_order_details,
            "related_defects": [],  # 需要进一步扩展
        }
    
    async def get_statistics(
        self,
        factory_id: str,
        from_date: datetime,
        to_date: datetime,
        inspection_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取检验统计数据"""
        # 构建基础查询条件
        where_conditions = [
            Inspection.factory_id == factory_id,
            Inspection.created_at >= from_date,
            Inspection.created_at <= to_date,
        ]
        if inspection_type:
            where_conditions.append(Inspection.inspection_type == inspection_type)
        
        # 总计数
        count_query = select(func.count()).select_from(Inspection).where(*where_conditions)
        total = await (await self.db.execute(count_query)).scalar() or 0
        
        # 按状态分布
        status_query = (
            select(Inspection.status, func.count())
            .where(*where_conditions)
            .group_by(Inspection.status)
        )
        status_result = await self.db.execute(status_query)
        status_breakdown = {str(row[0]): row[1] for row in status_result.fetchall()}
        
        # 按类型分布
        type_query = (
            select(Inspection.inspection_type, func.count())
            .where(*where_conditions)
            .group_by(Inspection.inspection_type)
        )
        type_result = await self.db.execute(type_query)
        type_breakdown = {str(row[0]): row[1] for row in type_result.fetchall()}
        
        passed_rate = round(status_breakdown.get(InspectionStatus.PASSED.value, 0) / total * 100, 2) if total > 0 else 0.0
        failed_rate = round(status_breakdown.get(InspectionStatus.FAILED.value, 0) / total * 100, 2) if total > 0 else 0.0
        
        return {
            "period": f"{from_date.date()} - {to_date.date()}",
            "factory_id": factory_id,
            "total_inspections": int(total),
            "by_status": {k: int(v) for k, v in status_breakdown.items()},
            "by_type": {k: int(v) for k, v in type_breakdown.items()},
            "passed_rate": passed_rate,
            "failed_rate": failed_rate,
        }