"""
IPC（制程巡检）业务模块 - 生产过程中的质量把关

IPC 是在生产过程中按预设的时间间隔或产品数量间隔进行的抽样检验，
用于监控生产过程的稳定性，及时发现和预防批量不良品的产生。
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List
from uuid import uuid4


class IPCFrequencyType(Enum):
    """巡检频率类型"""
    TIME_BASED = "time_based"      # 定时巡检（如每小时一次）
    QUANTITY_BASED = "quantity_based"  # 定量巡检（如每生产500件一次）
    RANDOM = "random"              # 随机抽检


class IPCResultType(Enum):
    """巡检结果"""
    PASS = "pass"      # 合格
    FAIL = "fail"      # 不合格
    HOLD = "hold"      # 搁置待处理


class IPCStatus(Enum):
    """IPC 状态流转"""
    PENDING = "pending"     # 待执行
    IN_PROGRESS = "in_progress"  # 巡检中
    PASSED = "passed"       # 合格
    FAILED = "failed"       # 不合格
    DISPOSED = "disposed"   # 已处置


class IPCCheckItem:
    """单个检验项目记录"""
    
    def __init__(self, item_id: str, name: str, spec_min: float, spec_max: float, actual_value: float = None, passed: bool = None):
        self.item_id = item_id
        self.name = name
        self.spec_min = spec_min
        self.spec_max = spec_max
        self.actual_value = actual_value
        self.passed = passed if passed is not None else (spec_min <= actual_value <= spec_max if actual_value is not None else None)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "name": self.name,
            "spec_min": self.spec_min,
            "spec_max": self.spec_max,
            "actual_value": self.actual_value,
            "passed": self.passed,
        }


class IPCRecord:
    """制程巡检记录实体"""
    
    def __init__(
        self,
        work_order_id: str,          # 关联的生产工单
        product_id: str,             # 产品编码
        process_stage: str,          # 工序阶段（如总装、测试、包装等）
        frequency_type: IPCFrequencyType,  # 巡检频率类型
        frequency_value: int,        # 频率值（如60分钟/500件）
        operator_id: str,            # 当班操作员ID
        inspector_id: str,           # 巡检员ID
        check_items: Optional[List[Dict]] = None,  # 预定义的检查项列表
    ):
        self.id = str(uuid4())
        self.work_order_id = work_order_id
        self.product_id = product_id
        self.process_stage = process_stage
        self.frequency_type = frequency_type
        self.frequency_value = frequency_value
        self.operator_id = operator_id
        self.inspector_id = inspector_id
        
        # 检查项
        self.check_items = [IPCCheckItem(**item) for item in check_items] if check_items else []
        
        # 初始状态
        self.status = IPCStatus.PENDING
        self.result: Optional[IPCResultType] = None
        self.inspected_at: Optional[datetime] = None
        self.defects_found: List[Dict] = []  # 发现的缺陷
        
        self.created_at = datetime.utcnow()
        self.updated_at = self.created_at
    
    def start_inspection(self, inspector_id: str) -> None:
        """开始巡检"""
        if self.status == IPCStatus.PENDING:
            self.status = IPCStatus.IN_PROGRESS
            self.inspector_id = inspector_id
            self.updated_at = datetime.utcnow()
    
    def record_check_result(self, item_id: str, actual_value: float, passed: bool) -> None:
        """记录单个检查项的结果"""
        for item in self.check_items:
            if item.item_id == item_id:
                item.actual_value = actual_value
                item.passed = passed
                break
    
    def record_defect(self, defect: Dict) -> None:
        """记录发现的缺陷"""
        self.defects_found.append(defect)
    
    def complete_inspection(self, result: IPCResultType) -> None:
        """完成巡检并得出判定结果"""
        self.result = result
        self.inspected_at = datetime.utcnow()
        self.status = IPCStatus.FAILED if result == IPCResultType.FAIL else IPCStatus.PASSED
        self.updated_at = datetime.utcnow()
    
    def dispose(self, disposition: str, by: str) -> None:
        """处置决定"""
        self.disposition = disposition
        self.disposition_by = by
        self.disposition_at = datetime.utcnow()
        self.status = IPCStatus.DISPOSED
        self.updated_at = datetime.utcnow()


class IPCService:
    """IPC 业务服务类"""
    
    def __init__(self):
        self._records: Dict[str, IPCRecord] = {}
        self._planning_cache: Dict[str, List[datetime]] = {}  # 计划下一次巡检时间缓存
    
    def create_ipc_plan(
        self,
        work_order_id: str,
        product_id: str,
        process_stage: str,
        frequency_type: IPCFrequencyType,
        frequency_value: int,
        operator_id: str,
        inspector_id: str,
        check_items: Optional[List[Dict]] = None,
    ) -> IPCRecord:
        """创建 IPC 巡检计划（记录）"""
        record = IPCRecord(
            work_order_id=work_order_id,
            product_id=product_id,
            process_stage=process_stage,
            frequency_type=frequency_type,
            frequency_value=frequency_value,
            operator_id=operator_id,
            inspector_id=inspector_id,
            check_items=check_items,
        )
        self._records[record.id] = record
        return record
    
    def get_record(self, record_id: str) -> Optional[IPCRecord]:
        """获取单个 IPC 记录"""
        return self._records.get(record_id)
    
    def list_records(
        self,
        work_order_id: Optional[str] = None,
        status: Optional[IPCStatus] = None,
        product_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[IPCRecord]:
        """列出 IPC 记录（带过滤条件）"""
        results = list(self._records.values())
        
        if work_order_id:
            results = [r for r in results if r.work_order_id == work_order_id]
        if status:
            results = [r for r in results if r.status == status]
        if product_id:
            results = [r for r in results if r.product_id == product_id]
        if start_date:
            results = [r for r in results if r.created_at >= start_date]
        if end_date:
            results = [r for r in results if r.created_at <= end_date]
        
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]
    
    def start_inspection(self, record_id: str, inspector_id: str) -> bool:
        """开始巡检（仅当状态为 PENDING 时）"""
        record = self._records.get(record_id)
        if record and record.status == IPCStatus.PENDING:
            record.start_inspection(inspector_id)
            return True
        return False
    
    def complete_inspection(
        self,
        record_id: str,
        result: IPCResultType,
        defects: Optional[List[Dict]] = None,
    ) -> bool:
        """完成巡检并记录结果"""
        record = self._records.get(record_id)
        if record and record.status == IPCStatus.IN_PROGRESS:
            record.complete_inspection(result)
            if defects:
                for defect in defects:
                    record.record_defect(defect)
            return True
        return False
    
    def dispose_record(self, record_id: str, disposition: str, by: str) -> bool:
        """处置 IPC 记录（仅在检验完成后）"""
        record = self._records.get(record_id)
        if record and record.status in (IPCStatus.PASSED, IPCStatus.FAILED):
            record.dispose(disposition, by)
            return True
        return False
    
    def schedule_next_inspection(self, record_id: str, next_time: datetime) -> None:
        """计划下次巡检时间（内部使用）"""
        pass  # 实际实现会写入数据库或计划调度器
