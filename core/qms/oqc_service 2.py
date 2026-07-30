"""
OQC（Outgoing Quality Control，出货检验）业务模块 - 客户交付前的最后一道关卡

OQC 在产品发货前进行最终质量把关，确保交付产品符合合同/订单要求，
是防止不合格品流入客户手中的关键防线。
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from uuid import uuid4


class OQCResultType(Enum):
    """出货检验结果"""
    PASS = "pass"      # 合格，可以发货
    FAIL = "fail"      # 不合格，不能发货
    HOLD = "hold"      # 待判定（等待客户特殊批准等）


class OQCStatus(Enum):
    """OQC 状态流转"""
    PENDING = "pending"     # 待检验
    IN_PROGRESS = "in_progress"  # 检验中
    PASSED = "passed"       # 合格
    FAILED = "failed"       # 不合格
    DISPOSED = "disposed"   # 已处置（放行/返工/让步接收等）


class OQCItem:
    """单个检验项目"""
    
    def __init__(self, item_id: str, name: str, spec: str, actual_value: str = None, passed: bool = None):
        self.item_id = item_id
        self.name = name
        self.spec = spec  # 规格描述，如"外观无损伤，功能正常"
        self.actual_value = actual_value
        self.passed = passed
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "name": self.name,
            "spec": self.spec,
            "actual_value": self.actual_value,
            "passed": self.passed,
        }


class OQCRecord:
    """出货检验记录实体"""
    
    def __init__(
        self,
        order_id: str,               # 关联的销售订单或出货单号
        customer_id: str,            # 客户编码
        product_id: str,             # 产品编码
        product_name: str,           # 产品名称
        batch_no: str,               # 批次号
        quantity_to_ship: int,       # 拟发货数量
        inspector_id: str,           # 检验员ID
        check_items: Optional[List[Dict]] = None,  # 检验项目列表（含规格和实际值）
    ):
        self.id = str(uuid4())
        self.order_id = order_id
        self.customer_id = customer_id
        self.product_id = product_id
        self.product_name = product_name
        self.batch_no = batch_no
        self.quantity_to_ship = quantity_to_ship
        self.inspector_id = inspector_id
        
        self.check_items = [OQCItem(**item) for item in check_items] if check_items else []
        
        self.status = OQCStatus.PENDING
        self.result: Optional[OQCResultType] = None
        self.shipped_qty = 0  # 实际发货数量（经处置后确定）
        self.rejected_qty = 0 # 拒收数量
        self.defects_found: List[Dict] = []  # 发现的缺陷详情
        
        self.disposition: Optional[str] = None  # pass/return/rework
        self.disposition_by: Optional[str] = None  # 处置人
        self.disposition_at: Optional[datetime] = None  # 处置时间
        
        self.created_at = datetime.utcnow()
        self.updated_at = self.created_at
    
    def start_inspection(self) -> None:
        if self.status == OQCStatus.PENDING:
            self.status = OQCStatus.IN_PROGRESS
            self.updated_at = datetime.utcnow()
    
    def record_check_result(self, item_id: str, actual_value: str, passed: bool) -> None:
        """记录单个检查项的结果"""
        for item in self.check_items:
            if item.item_id == item_id:
                item.actual_value = actual_value
                item.passed = passed
                break
    
    def record_defect(self, defect: Dict) -> None:
        self.defects_found.append(defect)
    
    def complete_inspection(self, result: OQCResultType) -> None:
        self.result = result
        self.status = OQCStatus.FAILED if result == OQCResultType.FAIL else OQCStatus.PASSED
        self.updated_at = datetime.utcnow()
    
    def dispose(self, disposition: str, by: str, shipped_qty: Optional[int] = None) -> None:
        """处置决定（pass放行/re退货/rework返工等）"""
        self.disposition = disposition
        self.disposition_by = by
        self.disposition_at = datetime.utcnow()
        if shipped_qty is not None:
            self.shipped_qty = shipped_qty
        self.status = OQCStatus.DISPOSED
        self.updated_at = datetime.utcnow()


class OQCService:
    """OQC 业务服务类"""
    
    def __init__(self):
        self._records: Dict[str, OQCRecord] = {}
    
    def create_oqc_record(
        self,
        order_id: str,
        customer_id: str,
        product_id: str,
        product_name: str,
        batch_no: str,
        quantity_to_ship: int,
        inspector_id: str,
        check_items: Optional[List[Dict]] = None,
    ) -> OQCRecord:
        record = OQCRecord(
            order_id=order_id,
            customer_id=customer_id,
            product_id=product_id,
            product_name=product_name,
            batch_no=batch_no,
            quantity_to_ship=quantity_to_ship,
            inspector_id=inspector_id,
            check_items=check_items,
        )
        self._records[record.id] = record
        return record
    
    def get_record(self, record_id: str) -> Optional[OQCRecord]:
        return self._records.get(record_id)
    
    def list_records(
        self,
        customer_id: Optional[str] = None,
        status: Optional[OQCStatus] = None,
        limit: int = 100,
    ) -> List[OQCRecord]:
        results = list(self._records.values())
        if customer_id:
            results = [r for r in results if r.customer_id == customer_id]
        if status:
            results = [r for r in results if r.status == status]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]
    
    def start_inspection(self, record_id: str) -> bool:
        record = self._records.get(record_id)
        if record and record.status == OQCStatus.PENDING:
            record.start_inspection()
            return True
        return False
    
    def complete_inspection(self, record_id: str, result: OQCResultType) -> bool:
        record = self._records.get(record_id)
        if record and record.status == OQCStatus.IN_PROGRESS:
            record.complete_inspection(result)
            return True
        return False
    
    def dispose_record(self, record_id: str, disposition: str, by: str, shipped_qty: Optional[int] = None) -> bool:
        record = self._records.get(record_id)
        if record and record.status in (OQCStatus.PASSED, OQCStatus.FAILED):
            record.dispose(disposition, by, shipped_qty)
            return True
        return False
