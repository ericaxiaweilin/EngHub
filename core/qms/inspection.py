"""
QMS Inspection Service
检验管理模块

功能:
- IQC 来料检验 (独立创建，不关联工单)
- IPQC 过程检验 (必须关联工单)
- FQC 最终检验 (必须关联工单 出货)
- OQC检验 (必须关联工单)
- AQL判定逻辑
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


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
    GENERAL_III = "general_iii"  # 一般检验水平 III
    SPECIAL_S1 = "special_s1"  # 特殊检验水平 S1
    SPECIAL_S2 = "special_s2"  # 特殊检验水平 S2


class AQLService:
    """AQL查表计算服务"""
    
    # AQL标准表 (样本大小代码)
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
    
    # AQL判定标准 (Ac=合格判定数, Re=不合格判定数)
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
            aql_level: AQL等级 (0.1, 0.25, 0.4, 0.65, 1.0, 1.5, 2.5)
        
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
    - 创建检验单 (根据类型自动验证必填字段)
    - AQL判定
    - 检验结果提交
    - 不合格自动创建不良品单
    """
    
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
        self.aql_service = AQLService()
    
    def generate_inspection_code(self, factory_code: str, inspection_type: str) -> str:
        today = datetime.now().strftime("%Y%m%d")
        return f"INS-{factory_code}-{inspection_type.upper()}-{today}"
    
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
    ) -> Dict[str, Any]:
        """
        创建检验单
        
        业务规则:
        - IQC: material_id必填, work_order_id可选
        - IPQC/FQC/OQC: work_order_id必填
        """
        # 验证必填字段
        if inspection_type == InspectionType.IQC.value:
            if not material_id:
                raise ValueError("IQC检验必须指定物料")
        else:
            if not work_order_id:
                raise ValueError(f"{inspection_type}检验必须关联工单")
        
        inspection = {
            "id": str(uuid.uuid4()),
            "inspection_code": self.generate_inspection_code(factory_id, inspection_type),
            "factory_id": factory_id,
            "inspection_type": inspection_type,
            "product_id": product_id,
            "material_id": material_id,
            "batch_id": batch_id,
            "batch_size": batch_size,
            "work_order_id": work_order_id,
            "aql_level": aql_level,
            "inspection_level": inspection_level,
            "status": InspectionStatus.PENDING.value,
            "created_by": created_by,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        
        # 计算样本大小
        if batch_size > 0:
            inspection["sample_size"] = self.aql_service.calculate_sample_size(batch_size, inspection_level)
        
        return inspection
    
    async def submit_inspection_result(
        self,
        inspection_id: str,
        inspected_qty: int,
        defective_qty: int,
        defect_details: List[Dict[str, Any]] = None,
        inspector_id: str = None,
    ) -> Dict[str, Any]:
        """
        提交检验结果
        
        自动进行AQL判定:
        - 合格: status = passed
        - 不合格: status = failed, 自动创建不良品单
        """
        # 获取检验单
        inspection = await self.get_inspection(inspection_id)
        
        # AQL判定
        aql_result = self.aql_service.evaluate(
            batch_size=inspection["batch_size"],
            defective_count=defective_qty,
            aql_level=inspection["aql_level"],
        )
        
        # 更新检验单
        inspection["inspected_qty"] = inspected_qty
        inspection["defective_qty"] = defective_qty
        inspection["defect_details"] = defect_details or []
        inspection["inspector_id"] = inspector_id
        inspection["inspected_at"] = datetime.now()
        
        if aql_result["result"] == "pass":
            inspection["status"] = InspectionStatus.PASSED.value
        else:
            inspection["status"] = InspectionStatus.FAILED.value
        
        inspection["aql_result"] = aql_result
        
        return inspection
    
    async def get_inspection(self, inspection_id: str) -> Optional[Dict[str, Any]]:
        """获取检验单详情"""
        pass
    
    async def list_inspections(
        self,
        factory_id: str,
        inspection_type: Optional[str] = None,
        status: Optional[str] = None,
        work_order_id: Optional[str] = None,
        material_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取检验单列表"""
        return []
    
    async def associate_work_order(
        self,
        inspection_id: str,
        work_order_id: str,
    ) -> Dict[str, Any]:
        """将IQC检验单关联到工单"""
        inspection = await self.get_inspection(inspection_id)
        
        if inspection["inspection_type"] != InspectionType.IQC.value:
            raise ValueError("只有IQC检验单可以关联工单")
        
        if inspection["work_order_id"]:
            raise ValueError("该检验单已关联工单")
        
        inspection["work_order_id"] = work_order_id
        inspection["updated_at"] = datetime.now()
        
        return inspection


__all__ = [
    "InspectionService",
    "InspectionType",
    "InspectionStatus",
    "AQLLevel",
    "AQLService",
]
