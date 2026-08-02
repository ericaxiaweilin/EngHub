"""
FAI (首件检验) 业务模块 - 生产启动前的关键质量检查

FAI 是在正式生产开始前，对第一个生产的工件进行全尺寸检验，
以确认工艺参数、设备状态、工装夹具等均符合要求。
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from uuid import uuid4


class FAILevel(str, Enum):
    """FAI 等级 - 根据产品复杂度决定检验深度"""
    LEVEL_1 = "level1"      # 简版：仅关键尺寸和功能测试
    LEVEL_2 = "level2"      # 标准版：主要尺寸检验
    LEVEL_3 = "level3"      # 完整版：全尺寸检验（含坐标测量）


class FAIStructure(str, Enum):
    """首次检验结构类型"""
    MANUAL = "manual"       # 人工检验
    AUTOMATED = "automated" # 自动化检测
    HYBRID = "hybrid"     # 混合方式


class FAIResultType(Enum):
    """首件检验结果"""
    PASS = "pass"      # 合格
    FAIL = "fail"      # 不合格
    HOLD = "hold"      # 待判定


class FAIStatus(Enum):
    """FAI 状态流转"""
    PENDING = "pending"     # 待检验
    IN_PROGRESS = "in_progress"  # 检验中
    PASSED = "passed"       # 合格
    FAILED = "failed"       # 不合格
    DISPOSED = "disposed"   # 已处置（让步接收/返工等）


class FAIRecord:
    """首件检验记录实体"""
    
    def __init__(
        self,
        factory_id: str,             # 新增工厂ID参数
        work_order_id: str,          # 关联的生产工单
        product_id: str,             # 产品编码
        product_name: str,           # 产品名称
        batch_no: str,               # 批次号
        machine_id: str,             # 加工设备编号
        operator_id: str,            # 操作员ID
        inspector_id: str,           # 检验员ID
        fail_level: FAILevel = FAILevel.LEVEL_2,  # FAI等级
        structure: FAIStructure = FAIStructure.MANUAL,  # 检验结构
        sample_qty: int = 1,         # 抽样数量（通常首件为1）
        check_items: Optional[List[Dict]] = None,  # 检验项目列表
    ):
        self.id = str(uuid4())

        self.factory_id = factory_id
        self.work_order_id = work_order_id  # 关联工单
        self.product_id = product_id
        self.product_name = product_name
        self.batch_no = batch_no
        self.machine_id = machine_id
        self.operator_id = operator_id
        self.inspector_id = inspector_id
        
        self.fail_level = fail_level
        self.structure = structure
        self.sample_qty = sample_qty
        
        # 检验项目 - 关键尺寸/外观/功能等
        self.check_items = check_items or []
        
        # 初始状态
        self.status = FAIStatus.PENDING
        self.result: Optional[FAIResultType] = None
        
        # 缺陷记录
        self.defects_found: List[Dict] = []  # 发现的缺陷
        
        # 处置信息
        self.disposition: Optional[str] = None  # pass/rework/scrap
        self.disposition_by: Optional[str] = None
        self.disposition_at: Optional[datetime] = None
        
        # 时间戳
        self.created_at = datetime.utcnow()
        self.updated_at = self.created_at
    
    def start_inspection(self) -> None:
        """开始首件检验"""
        if self.status == FAIStatus.PENDING:
            self.status = FAIStatus.IN_PROGRESS
            self.updated_at = datetime.utcnow()
    
    def record_check_result(self, item_id: str, result: bool, value: Optional[Any] = None, remark: str = "") -> None:
        """记录单个检验项目的结果"""
        # 简化：实际应更新检查项中的result字段
        pass
    
    def record_defect(self, defect: Dict) -> None:
        """记录发现的缺陷"""
        self.defects_found.append(defect)
    
    def finish_inspection(
        self,
        result: FAIResultType,
        inspected_by: Optional[str] = None,
    ) -> None:
        """完成检验并得出判定结果"""
        self.result = result
        if inspected_by:
            self.inspector_id = inspected_by
        self.status = FAIStatus.FAILED if result == FAIResultType.FAIL else FAIStatus.PASSED
        self.updated_at = datetime.utcnow()
    
    def dispose(self, disposition: str, by: str) -> None:
        """处置决定（合格放行/返工/报废等）"""
        self.disposition = disposition
        self.disposition_by = by
        self.disposition_at = datetime.utcnow()
        self.status = FAIStatus.DISPOSED
        self.updated_at = datetime.utcnow()


class FAIService:
    """FAI 业务服务类"""
    
    def __init__(self):
        self._records: Dict[str, FAIRecord] = {}
        self._check_lists: Dict[str, List[Dict]] = {}  # 预设的检验项目模板
    
    def create_fai_record(
        self,
        factory_id: str,
        work_order_id: str,
        product_id: str,
        product_name: str,
        batch_no: str,
        machine_id: str,
        operator_id: str,
        inspector_id: str,
        fail_level: FAILevel = FAILevel.LEVEL_2,
        structure: FAIStructure = FAIStructure.MANUAL,
        sample_qty: int = 1,
        check_items: Optional[List[Dict]] = None,
    ) -> FAIRecord:
        """创建一个新的 FAI 记录"""
        record = FAIRecord(
            factory_id=factory_id,
            work_order_id=work_order_id,
            product_id=product_id,
            product_name=product_name,
            batch_no=batch_no,
            machine_id=machine_id,
            operator_id=operator_id,
            inspector_id=inspector_id,
            fail_level=fail_level,
            structure=structure,
            sample_qty=sample_qty,
            check_items=check_items,
        )
        self._records[record.id] = record
        return record
    
    def get_record(self, record_id: str) -> Optional[FAIRecord]:
        """获取单个 FAI 记录"""
        return self._records.get(record_id)
    
    def list_records(
        self,
        factory_id: Optional[str] = None,
        status: Optional[FAIStatus] = None,
        product_id: Optional[str] = None,
        work_order_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[FAIRecord]:
        """列出 FAI 记录（带过滤条件）"""
        results = list(self._records.values())
        
        if status:
            results = [r for r in results if r.status == status]
        if product_id:
            results = [r for r in results if r.product_id == product_id]
        if work_order_id:
            results = [r for r in results if r.work_order_id == work_order_id]
        if start_date:
            results = [r for r in results if r.created_at >= start_date]
        if end_date:
            results = [r for r in results if r.created_at <= end_date]
        
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]
    
    def start_inspection(self, record_id: str, inspector_id: str) -> bool:
        """开始检验（仅当状态为 PENDING 时）"""
        record = self._records.get(record_id)
        if record and record.status == FAIStatus.PENDING:
            record.start_inspection()
            record.inspector_id = inspector_id
            return True
        return False
    
    def complete_inspection(
        self,
        record_id: str,
        result: FAIResultType,
        defects: Optional[List[Dict]] = None,
    ) -> bool:
        """完成检验"""
        record = self._records.get(record_id)
        if record and record.status == FAIStatus.IN_PROGRESS:
            record.finish_inspection(result)
            if defects:
                for defect in defects:
                    record.record_defect(defect)
            return True
        return False
    
    def dispose_record(self, record_id: str, disposition: str, by: str) -> bool:
        """执行处置（仅在检验完成后）"""
        record = self._records.get(record_id)
        if record and record.status in (FAIStatus.PASSED, FAIStatus.FAILED):
            record.dispose(disposition, by)
            return True
        return False
    
    def register_checklist(self, product_id: str, checklist: List[Dict]) -> None:
        """注册检验项目模板（供 FAI 引用）"""
        self._check_lists[product_id] = checklist
    
    def get_checklist(self, product_id: str) -> Optional[List[Dict]]:
        """获取检验项目模板"""
        return self._check_lists.get(product_id)
