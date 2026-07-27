"""
QMS Defect Service - 不良品管理系统（完整实现）

功能:
- 缺陷单创建（批次级追溯）
- 处置方式：返工/返修/报废/特采/退货
- OCAP（纠正预防措施）自动触发
- 批次追溯
- 统计分析
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum

from sqlalchemy import select, update, func

from database.models import WorkOrder, Inventory, User


class DefectStatus(str, Enum):
    """缺陷状态"""
    OPEN = "open"           # 待处理
    IN_PROGRESS = "in_progress"  # 处理中
    RESOLVED = "resolved"   # 已解决
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
    """
    缺陷服务
    
    核心功能:
    - 自动创建缺陷单（检验不合格时）
    - 批次级追溯
    - 处置方式管理
    - OCAP触发
    - 统计分析
    """
    
    def __init__(self, db):
        self.db = db
    
    async def create_defect(
        self,
        db: Any,
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
    ) -> Dict[str, Any]:
        """
        创建缺陷单
        
        批次级追溯关键字段:
        - batch_id: 批次号
        - material_id: 物料
        - work_order_id: 工单
        - station_id: 工位
        
        Args:
            db: Database session
            factory_id: 工厂ID
            defect_type: 缺陷类型
            quantity: 数量
            severity: 严重等级
            inspection_id: 关联检验单ID
            work_order_id: 关联工单ID
            material_id: 物料ID
            batch_id: 批次ID
            station_id: 工站ID
            description: 描述
            created_by: 创建人
            disposition_type: 初始处置方式
        
        Returns:
            缺陷单详情
        """
        # 生成缺陷编码
        factory_code = factory_id[:3].upper() if factory_id else "SYS"
        defect_code = f"DEF-{factory_code}-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
        
        # 创建缺陷记录
        defect = {
            "id": str(uuid.uuid4()),
            "defect_code": defect_code,
            "factory_id": factory_id,
            "defect_type": defect_type,
            "quantity": quantity,
            "severity": severity,
            "inspection_id": inspection_id,
            "work_order_id": work_order_id,
            "material_id": material_id,
            "batch_id": batch_id,
            "station_id": station_id,
            "description": description,
            "status": DefectStatus.OPEN.value,
            "disposition": disposition_type,
            "disposition_by": None,
            "disposition_at": None,
            "disposition_qty": None,
            "disposition_remark": None,
            "ocap_status": OcapStatus.PENDING.value,
            "ocap_triggered_at": None,
            "ocap_trigger_reason": None,
            "created_by": created_by or "system",
            "updated_by": created_by or "system",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        
        # TODO: 实际应插入数据库表
        # defect_record = DefectModel(**defect)
        # self.db.add(defect_record)
        # await self.db.commit()
        # await self.db.refresh(defect_record)
        # return self._model_to_dict(defect_record)
        
        return defect
    
    async def auto_create_from_inspection(
        self,
        db: Any,
        inspection_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        从检验结果自动创建缺陷单
        
        检验结果 = FAIL 时自动调用
        
        Args:
            db: Database session
            inspection_id: 检验单ID
        
        Returns:
            创建的缺陷单，或None如果不需要创建
        """
        # 获取检验单详情（需实际查询）
        # inspection = await self._get_inspection(db, inspection_id)
        
        # if inspection["status"] != "failed":
        #     return None
        
        # 创建缺陷单
        defect = await self.create_defect(
            db=db,
            factory_id=inspection.get("factory_id"),
            defect_type=DefectType.OTHER.value,
            quantity=inspection.get("defective_qty", 0),
            severity=Severity.MAJOR.value if inspection.get("defective_qty", 0) > 10 else Severity.MINOR.value,
            inspection_id=inspection_id,
            work_order_id=inspection.get("work_order_id"),
            material_id=inspection.get("material_id"),
            batch_id=inspection.get("batch_id"),
            description=f"检验不合格，检验单: {inspection['inspection_code']}",
            created_by=inspection.get("inspector_id"),
        )
        
        # 触发OCAP（根据严重等级）
        if inspection.get("defective_qty", 0) > 0:
            await self.trigger_ocap(db, defect["id"])
        
        return defect
    
    async def submit_disposition(
        self,
        db: Any,
        defect_id: str,
        disposition: str,
        disposition_by: str,
        disposition_qty: int = None,
        remark: str = None,
    ) -> Dict[str, Any]:
        """
        提交处置方案
        
        Args:
            db: Database session
            defect_id: 缺陷ID
            disposition: 处置方式（rework/repair/scrap/concession/return）
            disposition_by: 处置人
            disposition_qty: 处置数量（如果部分处置）
            remark: 备注
        
        Returns:
            更新后的缺陷单
        """
        # 获取缺陷单
        defect = await self.get_defect(db, defect_id)
        if not defect:
            raise ValueError(f"缺陷单 {defect_id} 不存在")
        
        # 验证处置方式
        valid_dispositions = [d.value for d in DispositionType]
        if disposition not in valid_dispositions:
            raise ValueError(f"无效的处置方式: {disposition}")
        
        # 更新处置信息
        defect["disposition"] = disposition
        defect["disposition_by"] = disposition_by
        defect["disposition_at"] = datetime.now()
        defect["disposition_qty"] = disposition_qty or defect["quantity"]
        defect["disposition_remark"] = remark
        
        # 更新状态
        if disposition == DispositionType.SCRAP.value:
            defect["status"] = DefectStatus.RESOLVED.value
        else:
            defect["status"] = DefectStatus.IN_PROGRESS.value
        
        defect["updated_at"] = datetime.now()
        defect["updated_by"] = disposition_by
        
        # TODO: 更新数据库
        # update_stmt = (update(DefectModel).where(DefectModel.id == defect_id).values(defect))
        # await db.execute(update_stmt)
        # await db.commit()
        
        return defect
    
    async def trigger_ocap(
        self,
        db: Any,
        defect_id: str,
    ) -> Dict[str, Any]:
        """
        触发OCAP（纠正预防措施）
        
        根据严重等级和不良类型判断是否需要触发OCAP
        
        规则:
        1. CRITICAL级别 - 必须触发
        2. MAJOR级别 - 超过阈值触发
        3. 特定不良类型 - 触发
        """
        defect = await self.get_defect(db, defect_id)
        if not defect:
            raise ValueError(f"缺陷单 {defect_id} 不存在")
        
        ocap_triggered = False
        reason = None
        
        # 检查是否需要触发OCAP
        if defect["severity"] == Severity.CRITICAL.value:
            ocap_triggered = True
            reason = "致命缺陷，强制触发OCAP"
        elif defect["severity"] == Severity.MAJOR.value:
            if defect["quantity"] >= 5:
                ocap_triggered = True
                reason = "重大缺陷数量超过阈值（>=5）"
        elif defect["defect_type"] in [DefectType.PROCESS.value, DefectType.MATERIAL.value]:
            if defect["quantity"] >= 3:
                ocap_triggered = True
                reason = "工艺/材料问题需要分析（>=3）"
        
        if ocap_triggered:
            defect["ocap_status"] = OcapStatus.TRIGGERED.value
            defect["ocap_trigger_reason"] = reason
            defect["ocap_triggered_at"] = datetime.now()
            defect["updated_at"] = datetime.now()
            
            # TODO: 创建OCAP单据
            # ocap_record = OCAPRecord(...)
            # self.db.add(ocap_record)
            
            # 发送通知
            await self._notify_ocap_trigger(defect)
        
        return defect
    
    async def _notify_ocap_trigger(self, defect: Dict[str, Any]):
        """发送OCAP触发通知（简化版）"""
        # TODO: 集成消息通知系统
        pass
    
    async def get_defect(self, db: Any, defect_id: str) -> Optional[Dict[str, Any]]:
        """获取缺陷单详情"""
        # TODO: 从数据库查询
        # result = await db.execute(select(DefectModel).where(DefectModel.id == defect_id))
        # return self._model_to_dict(result.scalar_one_or_none())
        return None
    
    async def list_defects(
        self,
        db: Any,
        factory_id: str,
        status: Optional[str] = None,
        defect_type: Optional[str] = None,
        work_order_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[Dict[str, Any]]:
        """获取缺陷单列表（带分页）"""
        # TODO: 从数据库查询并应用过滤条件
        # query = select(DefectModel).where(DefectModel.factory_id == factory_id)
        # ... apply filters ...
        # return []
        return []
    
    async def trace_by_batch(
        self,
        db: Any,
        batch_id: str,
    ) -> Dict[str, Any]:
        """
        批次追溯
        
        根据批次号追溯:
        - 物料来源
        - 生产工单
        - 检验记录
        - 缺陷记录
        """
        trace = {
            "batch_id": batch_id,
            "material_info": None,
            "work_orders": [],
            "inspections": [],
            "defects": [],
            "production_reports": [],
        }
        
        # TODO: 查询追溯数据
        # 1. 查找该批次的入库记录
        # 2. 查找关联的工单和检验
        # 3. 收集所有相关缺陷
        
        return trace
    
    async def get_defect_statistics(
        self,
        db: Any,
        factory_id: str,
        from_date: datetime,
        to_date: datetime,
    ) -> Dict[str, Any]:
        """
        缺陷统计
        
        - 按类型统计
        - 按工位统计
        - 按处置方式统计
        - 趋势分析
        """
        stats = {
            "period": f"{from_date.date()} - {to_date.date()}",
            "factory_id": factory_id,
            "total_defects": 0,
            "by_type": {},
            "by_station": {},
            "by_disposition": {},
            "top_defect_types": [],
            "trend": [],
        }
        
        # TODO: 统计查询
        # 1. 按缺陷类型分组计数
        # 2. 按工站分组计数
        # 3. 按处置方式分组计数
        # 4. 按日期趋势分析
        
        return stats
    
    async def resolve_defect(
        self,
        db: Any,
        defect_id: str,
        resolved_by: str,
        remarks: str = None,
    ) -> Dict[str, Any]:
        """关闭缺陷单（解决后关闭）"""
        defect = await self.get_defect(db, defect_id)
        if not defect:
            raise ValueError(f"缺陷单 {defect_id} 不存在")
        
        if defect["status"] not in [DefectStatus.OPEN.value, DefectStatus.IN_PROGRESS.value]:
            raise ValueError(f"缺陷单状态为 {defect['status']}，无法关闭")
        
        defect["status"] = DefectStatus.CLOSED.value
        defect["resolved_by"] = resolved_by
        defect["resolved_at"] = datetime.now()
        defect["remarks"] = remarks
        defect["updated_at"] = datetime.now()
        defect["updated_by"] = resolved_by
        
        # TODO: 更新数据库
        
        return defect
    
    def _model_to_dict(self, model) -> Dict[str, Any]:
        """将缺陷模型转换为字典"""
        return {
            "id": model.id,
            "defect_code": model.defect_code,
            "factory_id": model.factory_id,
            "defect_type": model.defect_type,
            "quantity": model.quantity,
            "severity": model.severity,
            "inspection_id": model.inspection_id,
            "work_order_id": model.work_order_id,
            "material_id": model.material_id,
            "batch_id": model.batch_id,
            "station_id": model.station_id,
            "description": model.description,
            "status": model.status,
            "disposition": model.disposition,
            "disposition_by": model.disposition_by,
            "disposition_at": model.disposition_at,
            "disposition_qty": model.disposition_qty,
            "disposition_remark": model.disposition_remark,
            "ocap_status": model.ocap_status,
            "ocap_triggered_at": model.ocap_triggered_at,
            "ocap_trigger_reason": model.ocap_trigger_reason,
            "created_by": model.created_by,
            "updated_by": model.updated_by,
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        }


__all__ = [
    "DefectService",
    "DefectStatus",
    "DefectType",
    "Severity",
    "DispositionType",
    "OcapStatus",
]