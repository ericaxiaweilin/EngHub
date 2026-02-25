"""
QMS Defect Service
不良 品管理模块

功能:
- 不良品单创建 (批次级追溯)
- 处置方式: 返工/返修/报废/特采
- OCAP触发
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class DefectStatus(str, Enum):
    """不良 品状态"""
    OPEN = "open"           # 待处理
    IN_PROGRESS = "in_progress"  # 处理中
    RESOLVED = "resolved"   # 已解决
    CLOSED = "closed"       # 已关闭
    CANCELLED = "cancelled"  # 已取消


class DefectType(str, Enum):
    """不良类型"""
    APPEARANCE = "appearance"     # 外观缺陷
    DIMENSION = "dimension"        # 尺寸超差
    FUNCTION = "function"          # 功能不良
    PERFORMANCE = "performance"    # 性能不良
    MATERIAL = "material"          # 材料不良
    PROCESS = "process"            # 工艺不良
    OTHER = "other"               # 其他


class Severity(str, Enum):
    """严重等级"""
    CRITICAL = "critical"   # 致命 (影响安全、法规)
    MAJOR = "major"         # 重大 (影响功能)
    MINOR = "minor"         # 轻微 (外观、轻微功能)
    OBSERVATION = "observation"  # 观察项


class DispositionType(str, Enum):
    """处置方式"""
    REWORK = "rework"       # 返工
    REPAIR = "repair"       # 返修
    SCRAP = "scrap"         # 报废
    CONCESSION = "concession"  # 特采 (让步使用)
    RETURN = "return"        # 退货


class OcapStatus(str, Enum):
    """OCAP状态"""
    PENDING = "pending"       # 待触发
    TRIGGERED = "triggered"   # 已触发
    IN_PROGRESS = "in_progress"  # 处理中
    COMPLETED = "completed"   # 已完成


class DefectService:
    """
    不良品服务
    
    核心功能:
    - 自动创建不良品单 (检验不合格时)
    - 批次级追溯
    - 处置方式管理
    - OCAP触发
    """
    
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
    
    def generate_defect_code(self, factory_code: str) -> str:
        today = datetime.now().strftime("%Y%m%d")
        return f"DEF-{factory_code}-{today}"
    
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
    ) -> Dict[str, Any]:
        """
        创建不良品单
        
        批次级追溯关键字段:
        - batch_id: 批次号
        - material_id: 物料
        - work_order_id: 工单
        - station_id: 工位
        """
        defect = {
            "id": str(uuid.uuid4()),
            "defect_code": self.generate_defect_code(factory_id),
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
            "disposition": None,
            "disposition_by": None,
            "disposition_at": None,
            "ocap_status": OcapStatus.PENDING.value,
            "created_by": created_by,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        
        return defect
    
    async def auto_create_from_inspection(
        self,
        inspection_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        从检验结果自动创建不良品单
        
        检验结果 = FAIL 时自动调用
        """
        # 获取检验单
        inspection = await self._get_inspection(inspection_id)
        
        if inspection["status"] != "failed":
            return None
        
        # 创建不良品单
        defect = await self.create_defect(
            factory_id=inspection["factory_id"],
            defect_type=DefectType.其他.value,
            quantity=inspection["defective_qty"],
            severity=Severity.MINOR.value,
            inspection_id=inspection_id,
            work_order_id=inspection.get("work_order_id"),
            material_id=inspection.get("material_id"),
            batch_id=inspection.get("batch_id"),
            description=f"检验不合格，检验单: {inspection['inspection_code']}",
        )
        
        # 触发OCAP (根据严重等级)
        if inspection["defective_qty"] > 0:
            await self.trigger_ocap(defect["id"])
        
        return defect
    
    async def submit_disposition(
        self,
        defect_id: str,
        disposition: str,
        disposition_by: str,
        disposition_qty: int = None,
        remark: str = None,
    ) -> Dict[str, Any]:
        """
        提交处置方案
        
        Args:
            disposition: 处置方式 (rework/repair/scrap/concession/return)
            disposition_qty: 处置数量 (如果部分处置)
        """
        defect = await self.get_defect(defect_id)
        
        # 验证处置方式
        valid_dispositions = [d.value for d in DispositionType]
        if disposition not in valid_dispositions:
            raise ValueError(f"无效的处置方式: {disposition}")
        
        # 更新不良品单
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
        
        return defect
    
    async def trigger_ocap(
        self,
        defect_id: str,
    ) -> Dict[str, Any]:
        """
        触发OCAP (纠正措施预防措施)
        
        根据严重等级和不良类型判断是否需要触发OCAP
        """
        defect = await self.get_defect(defect_id)
        
        # OCAP触发规则
        # 1. CRITICAL级别 - 必须触发
        # 2. MAJOR级别 - 超过阈值触发
        # 3. 特定不良类型 - 触发
        
        ocap_triggered = False
        reason = None
        
        if defect["severity"] == Severity.CRITICAL.value:
            ocap_triggered = True
            reason = "致命缺陷"
        elif defect["severity"] == Severity.MAJOR.value:
            if defect["quantity"] >= 5:
                ocap_triggered = True
                reason = "重大缺陷数量超过阈值"
        elif defect["defect_type"] in [DefectType.工艺不良.value, DefectType.材料不良.value]:
            if defect["quantity"] >= 3:
                ocap_triggered = True
                reason = "工艺/材料问题需要分析"
        
        if ocap_triggered:
            defect["ocap_status"] = OcapStatus.TRIGGERED.value
            defect["ocap_trigger_reason"] = reason
            defect["ocap_triggered_at"] = datetime.now()
            # TODO: 创建OCAP单据
        
        return defect
    
    async def get_defect(self, defect_id: str) -> Optional[Dict[str, Any]]:
        """获取不良品单详情"""
        pass
    
    async def list_defects(
        self,
        factory_id: str,
        status: Optional[str] = None,
        defect_type: Optional[str] = None,
        work_order_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """获取不良品单列表"""
        return []
    
    async def trace_by_batch(
        self,
        batch_id: str,
    ) -> Dict[str, Any]:
        """
        批次追溯
        
        根据批次号追溯:
        - 物料来源
        - 生产工单
        - 检验记录
        - 不良品记录
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
        
        return trace
    
    async def get_defect_statistics(
        self,
        factory_id: str,
        from_date: datetime,
        to_date: datetime,
    ) -> Dict[str, Any]:
        """
        不良品统计
        
        - 按类型统计
        - 按工位统计
        - 按处置方式统计
        - 趋势分析
        """
        stats = {
            "period": f"{from_date.date()} - {to_date.date()}",
            "total_defects": 0,
            "by_type": {},
            "by_station": {},
            "by_disposition": {},
            "top_defect_types": [],
            "trend": [],
        }
        
        # TODO: 统计查询
        
        return stats


__all__ = [
    "DefectService",
    "DefectStatus",
    "DefectType",
    "Severity",
    "DispositionType",
    "OcapStatus",
]
