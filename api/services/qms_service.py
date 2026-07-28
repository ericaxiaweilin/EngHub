from typing import Optional, Dict, Any, List
from datetime import datetime

from core.qms.iqc_service import IQCService, IQCStatus, InspectionResultType, DispositionType


class QMSService:
    """简化的 QMS 服务（内存实现，用于演示业务流程）"""
    
    def __init__(self):
        self.iqc = IQCService()
    
    def create_iqc_record(self, **kwargs) -> Dict[str, Any]:
        """创建 IQ C 记录（内存版）"""
        record = self.iqc.create_record(**kwargs)
        return {
            "id": record.id,
            "batch_no": record.batch_no,
            "product_name": record.product_name,
            "status": record.status.value,
            "created_at": record.created_at.isoformat(),
        }
    
    def complete_iqc(self, record_id: str, result: str, sample_size: int, defects: List[dict] = None) -> bool:
        """完成 IQ C 检验"""
        # 简化：在实际版本中会检查记录状态
        return True
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self.iqc.get_statistics()
        return stats
