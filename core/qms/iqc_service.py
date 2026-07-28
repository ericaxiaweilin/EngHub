"""
IQCL来料检验服务 - 供应链质量第一道关卡

负责处理供应商送货后的抽样检验、判定与处置流程。
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from uuid import uuid4


class InspectionResultType(Enum):
    """检验结果类型"""
    PASS = "pass"      # 合格
    FAIL = "fail"      # 不合格
    HOLD = "hold"      # 待判定（搁置）


class DispositionType(Enum):
    """处置类型"""
    ACCEPT = "accept"        # 接收入库
    REJECT = "reject"        # 退货
    RETURN_TO_VENDOR = "return_to_vendor"
    USE_AS_IS = "use_as_is"  # 让步接收
    SCRAP = "scrap"         # 报废


class IQCStatus(Enum):
    """IQ C 状态流转"""
    PENDING = "pending"      # 待检验
    IN_PROGRESS = "in_progress"  # 检验中
    PASSED = "passed"        # 合格
    FAILED = "failed"        # 不合格
    DISPOSED = "disposed"    # 已处置


class IQCRecord:
    """IQ C 记录实体"""
    
    def __init__(
        self,
        order_id: str,
        supplier_id: str,
        product_id: str,
        product_name: str,
        quantity_received: int,
        batch_no: str,
        delivery_date: datetime,
        inspector_id: str,
        inspection_criteria: Dict[str, Any] = None,
    ):
        self.id = str(uuid4())
        self.order_id = order_id          # 关联采购/收货单
        self.supplier_id = supplier_id
        self.product_id = product_id
        self.product_name = product_name
        self.quantity_received = quantity_received
        self.batch_no = batch_no            # 批次号
        self.delivery_date = delivery_date
        
        self.inspector_id = inspector_id     # 检验员ID
        self.status = IQCStatus.PENDING     # 初始状态
        
        # 检验参数
        self.inspection_criteria = inspection_criteria or {
            "sampling_method": "AQL",
            "aql_level": "II",
            "sample_size": 50,
            "critical_defect_reject": 0,
            "major_defect_reject": 2,
            "minor_defect_reject": 4,
        }
        
        # 检验结果
        self.result: Optional[InspectionResultType] = None
        self.sample_inspected: int = 0          # 实际抽检数量
        self.defects_found: List[Dict] = []       # 发现的缺陷列表
        
        # 处置信息
        self.disposition: Optional[DispositionType] = None
        self.disposition_by: Optional[str] = None  # 处置人
        self.disposition_at: Optional[datetime] = None
        
        # 时间戳
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def start_inspection(self) -> None:
        """开始检验（状态：待检验 -> 检验中）"""
        if self.status == IQCStatus.PENDING:
            self.status = IQCStatus.IN_PROGRESS
            self.updated_at = datetime.utcnow()
    
    def record_result(
        self,
        result: InspectionResultType,
        sample_inspected: int,
        defects: Optional[List[Dict]] = None,
    ) -> None:
        """记录检验结果"""
        self.result = result
        self.sample_inspected = sample_inspected
        if defects:
            self.defects_found = defects
        self.status = IQCStatus.FAILED if result == InspectionResultType.FAIL else IQCStatus.PASSED
        self.updated_at = datetime.utcnow()
    
    def dispose(self, disposition: DispositionType, by: str) -> None:
        """处置决定"""
        self.disposition = disposition
        self.disposition_by = by
        self.disposition_at = datetime.utcnow()
        self.status = IQCStatus.DISPOSED
        self.updated_at = datetime.utcnow()


class IQCService:
    """IQ C 业务服务类"""
    
    def __init__(self):
        # 内存存储（实际应使用数据库）
        self._records: Dict[str, IQCRecord] = {}
        # 供应商质量评分（累积）
        self._supplier_quality: Dict[str, Dict[str, Any]] = {}
    
    def create_record(
        self,
        order_id: str,
        supplier_id: str,
        product_id: str,
        product_name: str,
        quantity_received: int,
        batch_no: str,
        delivery_date: datetime,
        inspector_id: str,
        inspection_criteria: Optional[Dict[str, Any]] = None,
    ) -> IQCRecord:
        """创建一个新的 IQC 记录"""
        record = IQCRecord(
            order_id=order_id,
            supplier_id=supplier_id,
            product_id=product_id,
            product_name=product_name,
            quantity_received=quantity_received,
            batch_no=batch_no,
            delivery_date=delivery_date,
            inspector_id=inspector_id,
            inspection_criteria=inspection_criteria,
        )
        self._records[record.id] = record
        return record
    
    def get_record(self, record_id: str) -> Optional[IQCRecord]:
        """获取单个 IQC 记录"""
        return self._records.get(record_id)
    
    def list_records(
        self,
        factory_id: Optional[str] = None,
        status: Optional[IQCStatus] = None,
        product_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[IQCRecord]:
        """列出 IQC 记录（带过滤条件）"""
        results = list(self._records.values())
        
        if status:
            results = [r for r in results if r.status == status]
        if product_id:
            results = [r for r in results if r.product_id == product_id]
        if supplier_id:
            results = [r for r in results if r.supplier_id == supplier_id]
        if start_date:
            results = [r for r in results if r.delivery_date >= start_date]
        if end_date:
            results = [r for r in results if r.delivery_date <= end_date]
        
        # 按创建时间倒序排序
        results.sort(key=lambda r: r.created_at, reverse=True)
        
        return results[:limit]
    
    def start_inspection(self, record_id: str, inspector_id: str) -> bool:
        """开始检验（仅当状态为 PENDING 时）"""
        record = self._records.get(record_id)
        if record and record.status == IQCStatus.PENDING:
            record.start_inspection()
            record.inspector_id = inspector_id
            return True
        return False
    
    def complete_inspection(
        self,
        record_id: str,
        result: InspectionResultType,
        sample_inspected: int,
        defects: Optional[List[Dict]] = None,
    ) -> bool:
        """完成检验"""
        record = self._records.get(record_id)
        if record and record.status == IQCStatus.IN_PROGRESS:
            record.record_result(result, sample_inspected, defects)
            
            # 更新供应商质量评分
            self._update_supplier_quality(record.supplier_id, result)
            return True
        return False
    
    def dispose_record(self, record_id: str, disposition: DispositionType, by: str) -> bool:
        """执行处置（仅在检验完成后）"""
        record = self._records.get(record_id)
        if record and record.status in (IQCStatus.PASSED, IQCStatus.FAILED):
            record.dispose(disposition, by)
            return True
        return False
    
    def _update_supplier_quality(self, supplier_id: str, result: InspectionResultType) -> None:
        """更新供应商质量评分"""
        if supplier_id not in self._supplier_quality:
            self._supplier_quality[supplier_id] = {
                "total_inspections": 0,
                "passed_count": 0,
                "failed_count": 0,
                "quality_rate": 100.0,
                "last_updated": datetime.utcnow(),
            }
        
        stats = self._supplier_quality[supplier_id]
        stats["total_inspections"] += 1
        
        if result == InspectionResultType.PASS:
            stats["passed_count"] += 1
        else:
            stats["failed_count"] += 1
        
        # 重新计算合格率
        stats["quality_rate"] = round(
            (stats["passed_count"] / stats["total_inspections"]) * 100, 1
        )
        stats["last_updated"] = datetime.utcnow()
    
    def get_supplier_quality_score(self, supplier_id: str) -> Optional[Dict[str, Any]]:
        """获取供应商质量评分"""
        return self._supplier_quality.get(supplier_id)
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取 IQC 统计汇总"""
        total = len(self._records)
        passed = sum(1 for r in self._records.values() if r.status == IQCStatus.PASSED)
        failed = sum(1 for r in self._records.values() if r.status == IQCStatus.FAILED)
        disposed = sum(1 for r in self._records.values() if r.status == IQCStatus.DISPOSED)
        
        rate = round((passed / total * 100), 1) if total > 0 else 0.0
        
        return {
            "total_records": total,
            "passed_count": passed,
            "failed_count": failed,
            "disposed_count": disposed,
            "pass_rate": f"{rate}%",
            "by_status": {
                "pending": sum(1 for r in self._records.values() if r.status == IQCStatus.PENDING),
                "in_progress": sum(1 for r in self._records.values() if r.status == IQCStatus.IN_PROGRESS),
                "passed": passed,
                "failed": failed,
                "disposed": disposed,
            },
        }
