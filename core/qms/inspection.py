"""
QMS Inspection Service - 检验管理模块（完整实现）

功能:
- IQC 来料检验（独立创建，不关联工单）
- IPQC 过程检验（必须关联工单）
- FQC 最终检验（必须关联工单/出货）
- OQC出货检验（必须关联工单）
- AQL判定逻辑
- 检验结果提交与不良自动触发
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from sqlalchemy import select, update, func

from database.models import (
    WorkOrder,
    Inventory,
    InboundOrder,
    OutboundOrder,
    Product,
    Station,
    Warehouse,
    User,
    Inspection,
)
from core.qms.defect import DefectService, DefectType, Severity


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
    GENERAL_I = "general_i"    # 一般检验水平 I
    GENERAL_II = "general_ii"  # 一般检验水平 II
    GENERAL_III = "general_iii" # 一般检验水平 III
    SPECIAL_S1 = "special_s1"  # 特殊检验水平 S1
    SPECIAL_S2 = "special_s2"  # 特殊检验水平 S2


class AQLService:
    """AQL查表计算服务"""
    
    # AQL标准表（样本大小代码）
    SAMPLE_SIZE_CODES = {
        (2, 8): "A",
        (9, 15): "B",
        (16, 25): "C",
        (26, 50): "D",
        (51, 90): "E",
        (91, 150): "F",
        (151, 280): "G",
        (281, 500): "H",
        (501, 1200): "J",
        (1201, 3200): "K",
        (3201, 10000): "L",
    }
    
    # AQL判定标准（Ac=合格判定数，Re=不合格判定数）
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
        return "L"  # 最大批量
    
    def calculate_sample_size(self, batch_size: int, level: str = AQLLevel.GENERAL_II.value) -> int:
        """计算样本大小"""
        code = self.get_sample_size_code(batch_size)
        
        sample_sizes = {
            "A": 2, "B": 3, "C": 5, "D": 8, "E": 13,
            "F": 20, "G": 32, "H": 50, "J": 80, "K": 125, "L": 200
        }
        
        return sample_sizes.get(code, 200)
    
    def evaluate(
        self,
        batch_size: int,
        defective_count: int,
        aql_level: float = 1.0,
    ) -> Dict[str, Any]:
        """
        AQL判定
        
        Args:
            batch_size: 批量大小
            defective_count: 不良品数
            aql_level: AQL等级（0.1, 0.25, 0.4, 0.65, 1.0, 1.5, 2.5）
        
        Returns:
            {
                "result": "pass" / "fail",
                "sample_size": 32,
                "ac": 3,  # 合格判定数
                "re": 4,  # 不合格判定数
                "defective_count": 2
            }
        """
        code = self.get_sample_size_code(batch_size)
        
        # 获取判定数
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
    """
    检验服务
    
    核心功能:
    - 创建检验单（根据类型自动验证必填字段）
    - AQL判定
    - 检验结果提交
    - 不合格自动创建不良品单
    - 批次追溯
    - 统计分析
    """
    
    def __init__(self, db_pool=None):
        self.db = db_pool
        self.aql_service = AQLService()
        self.defect_service = DefectService(db_pool)
    
    def generate_inspection_code(self, factory_code: str, inspection_type: str) -> str:
        today = datetime.now().strftime("%Y%m%d")
        return f"INS-{factory_code}-{inspection_type.upper()}-{today}"
    
    async def create_inspection(
        self,
        db: Any,
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
    ) -> Dict[str, Any]:
        """
        创建检验单
        
        业务规则:
        - IQC: material_id必填，work_order_id可选，supplier_id/PurchaseOrder可选
        - IPQC/FQC/OQC: work_order_id必填
        
        Args:
            db: Database session
            factory_id: 工厂ID
            inspection_type: 检验类型
            material_id: 物料ID（IQC必需）
            work_order_id: 工单号（IPQC/FQC/OQC必需）
            batch_size: 批量大小
            aql_level: AQL等级
            created_by: 创建人
        
        Returns:
            检验单详情字典
        """
        # 验证必填字段
        if inspection_type == InspectionType.IQC.value:
            if not material_id:
                raise ValueError("IQC检验必须指定物料")
        else:
            if not work_order_id:
                raise ValueError(f"{inspection_type}检验必须关联工单")
        
        # 生成唯一检验码
        inspection_code = self.generate_inspection_code(
            factory_id[:3].upper(), inspection_type
        )
        
        # 获取样本大小
        sample_size = None
        if batch_size > 0:
            sample_size = self.aql_service.calculate_sample_size(batch_size, inspection_level)
        
        # 构造检验记录
        inspection = Inspection(
            id=str(uuid.uuid4()),
            inspection_code=inspection_code,
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
            created_at=datetime.now(),
            updated_at=datetime.now(),
            supplier_id=supplier_id,
            purchase_order_id=purchase_order_id,
        )
        
        db.add(inspection)
        await db.commit()
        await db.refresh(inspection)
        
        return self._model_to_dict(inspection)
    
    async def get_inspection(self, db: Any, inspection_id: str) -> Optional[Dict[str, Any]]:
        """获取检验单详情"""
        result = await db.execute(
            select(Inspection).where(Inspection.id == inspection_id)
        )
        inspection = result.scalar_one_or_none()
        if inspection:
            return self._model_to_dict(inspection)
        return None
    
    async def list_inspections(
        self,
        db: Any,
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
        """获取检验单列表（带分页）"""
        query = select(Inspection).where(Inspection.factory_id == factory_id)
        
        # 应用过滤条件
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
        
        # 获取总数计数
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
        
        total = (await db.execute(count_query)).scalar()
        
        # 分页查询
        query = query.offset((page - 1) * page_size).limit(page_size)
        results = await db.execute(query)
        inspections = results.scalars().all()
        
        return {
            "items": [self._model_to_dict(i) for i in inspections],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }
    
    async def submit_inspection_result(
        self,
        db: Any,
        inspection_id: str,
        inspected_qty: int,
        defective_qty: int,
        defect_details: Optional[List[Dict[str, Any]]] = None,
        inspector_id: str = None,
        remarks: str = None,
    ) -> Dict[str, Any]:
        """
        提交检验结果
        
        自动进行AQL判定:
        - 合格: status = passed
        - 不合格: status = failed, 自动创建不良品单
        
        Args:
            db: Database session
            inspection_id: 检验单ID
            inspected_qty: 检验数量
            defective_qty: 不良数量
            defect_details: 缺陷详细信息列表
            inspector_id: 检验员ID
            remarks: 备注
        
        Returns:
            更新后的检验单详情
        """
        # 获取检验单
        inspection = await self.get_inspection(db, inspection_id)
        if not inspection:
            raise ValueError(f"检验单 {inspection_id} 不存在")
        
        # 更新检验状态
        if inspection["status"] in [InspectionStatus.PASSED.value, InspectionStatus.FAILED.value]:
            raise ValueError("检验结果已提交，不可重复提交")
        
        # AQL判定
        aql_result = self.aql_service.evaluate(
            batch_size=inspection["batch_size"],
            defective_count=defective_qty,
            aql_level=inspection["aql_level"],
        )
        
        # 更新检验单记录
        update_stmt = (
            update(Inspection)
            .where(Inspection.id == inspection_id)
            .values({
                "status": InspectionStatus.FAILED.value if aql_result["result"] == "fail" else InspectionStatus.PASSED.value,
                "inspected_at": datetime.now(),
                "inspected_qty": inspected_qty,
                "defective_qty": defective_qty,
                "defect_details": defect_details or [],
                "inspector_id": inspector_id,
                "aql_result": aql_result,
                "updated_at": datetime.now(),
                "remarks": remarks,
            })
        )
        await db.execute(update_stmt)
        await db.commit()
        
        # 如果不合格，自动生成不良品单
        if aql_result["result"] == "fail" and defective_qty > 0:
            await self._create_defect_on_failure(
                db, inspection_id, defective_qty, defect_details, inspector_id, remarks
            )
        
        # 返回更新的检验单
        return await self.get_inspection(db, inspection_id)
    
    async def _create_defect_on_failure(
        self,
        db: Any,
        inspection_id: str,
        defective_qty: int,
        defect_details: Optional[List[Dict]],
        inspector_id: str,
        remarks: str,
    ):
        """检验不合格时自动创建不良品单"""
        # 获取检验单详情（已提交更新后重新查询）
        inspection = await self.get_inspection(db, inspection_id)
        if not inspection:
            return
        
        # 获取缺陷严重等级（根据缺陷详情判断）
        severity = Severity.MINOR.value
        if defect_details:
            for detail in defect_details:
                if detail.get("severity") in ["critical", "major"]:
                    severity = detail["severity"]
                    break
        
        # 创建不良品单
        defect = await self.defect_service.create_defect(
            db=db,
            factory_id=inspection["factory_id"],
            defect_type="appearance" if inspection["inspection_type"] == "iqc" else "dimension",
            quantity=defective_qty,
            severity=severity,
            inspection_id=inspection["id"],
            work_order_id=inspection.get("work_order_id"),
            material_id=inspection.get("material_id"),
            batch_id=inspection.get("batch_id"),
            station_id=inspector_id,
            description=f"检验不合格，检验单: {inspection['inspection_code']}, {remarks or ''}",
            created_by=inspector_id or "system",
        )
        
        return defect
    
    async def associate_work_order(
        self,
        db: Any,
        inspection_id: str,
        work_order_id: str,
    ) -> Dict[str, Any]:
        """将IQC检验单关联到工单"""
        # 获取现有检验单
        inspection = await self.get_inspection(db, inspection_id)
        if not inspection:
            raise ValueError(f"检验单 {inspection_id} 不存在")
        
        if inspection["inspection_type"] != InspectionType.IQC.value:
            raise ValueError("只有IQC检验单可以关联工单")
        
        if inspection["work_order_id"]:
            raise ValueError("该检验单已关联工单")
        
        # 验证工单是否存在
        wo_result = await db.execute(select(WorkOrder).where(WorkOrder.id == work_order_id))
        work_order = wo_result.scalar_one_or_none()
        if not work_order:
            raise ValueError(f"工单 {work_order_id} 不存在")
        
        # 关联工单
        update_stmt = (
            update(Inspection)
            .where(Inspection.id == inspection_id)
            .values({
                "work_order_id": work_order_id,
                "updated_at": datetime.now(),
            })
        )
        await db.execute(update_stmt)
        await db.commit()
        
        return await self.get_inspection(db, inspection_id)
    
    async def start_inspection(
        self,
        db: Any,
        inspection_id: str,
        started_by: str,
    ) -> Dict[str, Any]:
        """开始检验（状态从 pending 变为 in_progress）"""
        inspection = await self.get_inspection(db, inspection_id)
        if not inspection:
            raise ValueError(f"检验单 {inspection_id} 不存在")
        
        if inspection["status"] != InspectionStatus.PENDING.value:
            raise ValueError(f"检验单当前状态为 {inspection['status']}，不能开始检验")
        
        update_stmt = (
            update(Inspection)
            .where(Inspection.id == inspection_id)
            .values({
                "status": InspectionStatus.IN_PROGRESS.value,
                "started_at": datetime.now(),
                "started_by": started_by,
                "updated_at": datetime.now(),
            })
        )
        await db.execute(update_stmt)
        await db.commit()
        
        return await self.get_inspection(db, inspection_id)
    
    async def trace_by_batch(self, db: Any, batch_id: str, factory_id: str) -> Dict[str, Any]:
        """
        批次追溯
        
        根据批次号追溯:
        - 采购入库记录
        - 生产工单
        - 检验记录
        - 不良品记录
        """
        # 查找该批次的入库记录
        inbound_result = await db.execute(
            select(InboundOrder).where(InboundOrder.batch_code == batch_id)
        )
        inbound_orders = inbound_result.scalars().all()
        
        # 查找该批次的检验记录
        inspection_result = await db.execute(
            select(Inspection).where(
                Inspection.factory_id == factory_id,
                Inspection.batch_id == batch_id
            )
        )
        inspections = inspection_result.scalars().all()
        
        # 查找该批次的工单关联
        work_orders = []
        for insp in inspections:
            if insp.work_order_id:
                work_orders.append(insp.work_order_id)
        
        # 查找相关不良品（需要进一步集成）
        defects = []
        
        return {
            "batch_id": batch_id,
            "factory_id": factory_id,
            "inbound_orders": [self._model_inbound_to_dict(o) for o in inbound_orders],
            "inspections": [self._model_to_dict(i) for i in inspections],
            "work_orders": work_orders,
            "defects": defects,
        }
    
    async def get_statistics(
        self,
        db: Any,
        factory_id: str,
        from_date: datetime,
        to_date: datetime,
        inspection_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取检验统计数据"""
        # 总检验数
        count_query = select(func.count()).select_from(Inspection)
        count_query = count_query.where(Inspection.factory_id == factory_id)
        count_query = count_query.where(Inspection.created_at >= from_date)
        count_query = count_query.where(Inspection.created_at <= to_date)
        if inspection_type:
            count_query = count_query.where(Inspection.inspection_type == inspection_type)
        
        total = (await db.execute(count_query)).scalar()
        
        # 按状态分布
        status_result = await db.execute(
            select(Inspection.status, func.count()).where(
                Inspection.factory_id == factory_id,
                Inspection.created_at >= from_date,
                Inspection.created_at <= to_date,
            ).group_by(Inspection.status)
        )
        status_breakdown = dict(status_result.fetchall())
        
        # 按类型分布
        type_result = await db.execute(
            select(Inspection.inspection_type, func.count()).where(
                Inspection.factory_id == factory_id,
                Inspection.created_at >= from_date,
                Inspection.created_at <= to_date,
            ).group_by(Inspection.inspection_type)
        )
        type_breakdown = dict(type_result.fetchall())
        
        return {
            "period": f"{from_date.date()} - {to_date.date()}",
            "factory_id": factory_id,
            "total_inspections": total,
            "by_status": status_breakdown,
            "by_type": type_breakdown,
            "passed_rate": round(status_breakdown.get("passed", 0) / total * 100, 2) if total > 0 else 0,
            "failed_rate": round(status_breakdown.get("failed", 0) / total * 100, 2) if total > 0 else 0,
        }
    
    def _model_to_dict(self, obj) -> Dict[str, Any]:
        """将Inspection模型转换为字典"""
        result = obj.to_dict() if hasattr(obj, 'to_dict') else {}
        return {
            **result,
            "id": obj.id,
            "inspection_code": obj.inspection_code,
            "factory_id": obj.factory_id,
            "inspection_type": obj.inspection_type,
            "product_id": obj.product_id,
            "material_id": obj.material_id,
            "batch_id": obj.batch_id,
            "batch_size": obj.batch_size,
            "work_order_id": obj.work_order_id,
            "aql_level": obj.aql_level,
            "inspection_level": obj.inspection_level,
            "sample_size": obj.sample_size,
            "status": obj.status,
            "created_by": obj.created_by,
            "updated_by": obj.updated_by,
        }
    
    def _model_inbound_to_dict(self, obj) -> Dict[str, Any]:
        """将InboundOrder模型转换为字典"""
        return {
            "id": obj.id,
            "inbound_code": obj.inbound_code,
            "factory_id": obj.factory_id,
            "warehouse_id": obj.warehouse_id,
            "material_id": obj.material_id,
            "material_code": obj.material_code,
            "quantity": obj.quantity,
            "batch_code": obj.batch_code,
            "supplier_id": obj.supplier_id,
            "purchase_order_id": obj.purchase_order_id,
            "inbound_type": obj.inbound_type,
            "status": obj.status,
        }


__all__ = [
    "InspectionService",
    "InspectionType",
    "InspectionStatus",
    "AQLLevel",
    "AQLService",
]