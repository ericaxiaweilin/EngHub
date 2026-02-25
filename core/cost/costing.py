"""
Cost Accounting Service
成本核算模块

功能:
- 工单成本计算 (材料成本 + 人工成本 + 制造费用)
- 产品成本分析
- 实际成本 vs 标准成本差异分析
- 成本报表
"""

import uuid
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from enum import Enum


class CostType(str, Enum):
    """成本类型"""
    MATERIAL = "material"       # 材料成本
    LABOR = "labor"             # 人工成本
    OVERHEAD = "overhead"       # 制造费用
    TOTAL = "total"             # 总成本


class CostStatus(str, Enum):
    """成本状态"""
    PENDING = "pending"         # 待计算
    CALCULATED = "calculated"   # 已计算
    CONFIRMED = "confirmed"    # 已确认
    ADJUSTED = "adjusted"       # 已调整


class CostingService:
    """
    成本核算服务
    
    核心功能:
    - 工单成本计算
    - 产品成本分析
    - 成本差异分析
    - 实际抛料统计
    """
    
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
    
    async def calculate_work_order_cost(
        self,
        work_order_id: str,
    ) -> Dict[str, Any]:
        """
        计算工单成本
        
        工单成本 = 材料成本 + 人工成本 + 制造费用
        
        材料成本来源:
        - 生产报工时根据BOM自动扣减的库存成本
        
        人工成本来源:
        - 报工记录的人工工时
        - 工位的人工费率
        
        制造费用:
        - 设备折旧
        - 能耗
        - 其他间接费用
        """
        # 获取工单信息
        work_order = await self._get_work_order(work_order_id)
        
        # 1. 计算材料成本
        material_cost = await self._calculate_material_cost(work_order_id)
        
        # 2. 计算人工成本
        labor_cost = await self._calculate_labor_cost(work_order_id)
        
        # 3. 计算制造费用
        overhead_cost = await self._calculate_overhead_cost(work_order_id)
        
        # 4. 计算总成本
        total_cost = material_cost + labor_cost + overhead_cost
        
        # 单位成本
        produced_qty = work_order.get("completed_qty", 0) or 1
        unit_cost = total_cost / produced_qty
        
        cost_result = {
            "work_order_id": work_order_id,
            "work_order_code": work_order.get("work_order_code"),
            "product_id": work_order.get("product_id"),
            "produced_qty": produced_qty,
            "material_cost": material_cost,
            "labor_cost": labor_cost,
            "overhead_cost": overhead_cost,
            "total_cost": total_cost,
            "unit_cost": unit_cost,
            "status": CostStatus.CALCULATED.value,
            "calculated_at": datetime.now(),
        }
        
        return cost_result
    
    async def _calculate_material_cost(self, work_order_id: str) -> float:
        """计算材料成本"""
        # 从报工记录获取实际消耗的物料
        material_cost = 0.0
        
        # TODO: 查询报工时扣减的物料成本
        # SELECT sum(quantity * unit_cost) FROM inventory_transactions
        
        # 示例
        material_cost = 15000.0
        
        return material_cost
    
    async def _calculate_labor_cost(self, work_order_id: str) -> float:
        """计算人工成本"""
        # 从报工记录获取实际工时
        labor_hours = 0.0
        labor_rate = 50.0  # 每小时人工费
        
        # TODO: 查询报工记录中的实际工时
        
        # 示例
        labor_hours = 100.0
        labor_cost = labor_hours * labor_rate
        
        return labor_cost
    
    async def _calculate_overhead_cost(self, work_order_id: str) -> float:
        """计算制造费用"""
        # 制造费用 = 人工成本 * 费用率
        labor_cost = await self._calculate_labor_cost(work_order_id)
        overhead_rate = 0.3  # 30% 费用率
        
        overhead_cost = labor_cost * overhead_rate
        
        return overhead_cost
    
    async def _get_work_order(self, work_order_id: str) -> Dict[str, Any]:
        """获取工单信息"""
        # TODO: 查询工单数据
        return {
            "work_order_id": work_order_id,
            "work_order_code": "WO-20260224-001",
            "product_id": "PROD-001",
            "completed_qty": 1000,
        }
    
    async def calculate_product_standard_cost(
        self,
        product_id: str,
        bom_version: str = None,
    ) -> Dict[str, Any]:
        """
        计算产品标准成本
        
        标准成本 = 标准材料成本 + 标准人工成本 + 标准制造费用
        """
        # 获取BOM
        bom = await self._get_bom(product_id, bom_version)
        
        # 1. 标准材料成本
        material_cost = 0.0
        for item in bom.get("items", []):
            material_cost += item["standard_qty"] * item["standard_cost"]
        
        # 2. 标准人工成本
        routing = await self._get_routing(product_id)
        labor_cost = 0.0
        for step in routing.get("steps", []):
            labor_cost += step["standard_time"] / 3600 * step["labor_rate"]
        
        # 3. 标准制造费用
        overhead_cost = labor_cost * 0.3
        
        # 总标准成本
        total_standard_cost = material_cost + labor_cost + overhead_cost
        
        return {
            "product_id": product_id,
            "bom_version": bom_version,
            "material_cost": material_cost,
            "labor_cost": labor_cost,
            "overhead_cost": overhead_cost,
            "total_standard_cost": total_standard_cost,
            "calculated_at": datetime.now(),
        }
    
    async def _get_bom(self, product_id: str, version: str = None) -> Dict[str, Any]:
        """获取BOM"""
        # TODO: 从luaguage获取
        return {"items": []}
    
    async def _get_routing(self, product_id: str) -> Dict[str, Any]:
        """获取工艺路线"""
        # TODO: 查询工艺路线
        return {"steps": []}
    
    async def analyze_cost_variance(
        self,
        work_order_id: str,
    ) -> Dict[str, Any]:
        """
        成本差异分析
        
        差异 = 实际成本 - 标准成本
        """
        # 获取实际成本
        actual_cost = await self.calculate_work_order_cost(work_order_id)
        
        # 获取标准成本
        product_id = actual_cost["product_id"]
        standard_cost_data = await self.calculate_product_standard_cost(product_id)
        
        # 计算差异
        material_variance = actual_cost["material_cost"] - standard_cost_data["material_cost"]
        labor_variance = actual_cost["labor_cost"] - standard_cost_data["labor_cost"]
        overhead_variance = actual_cost["overhead_cost"] - standard_cost_data["overhead_cost"]
        total_variance = actual_cost["total_cost"] - standard_cost_data["total_standard_cost"]
        
        variance_analysis = {
            "work_order_id": work_order_id,
            "actual_cost": actual_cost["total_cost"],
            "standard_cost": standard_cost_data["total_standard_cost"],
            "total_variance": total_variance,
            "variance_rate": (total_variance / standard_cost_data["total_standard_cost"] * 100) if standard_cost_data["total_standard_cost"] > 0 else 0,
            "material_variance": material_variance,
            "labor_variance": labor_variance,
            "overhead_variance": overhead_variance,
            "analysis": self._interpret_variance(total_variance, standard_cost_data["total_standard_cost"]),
        }
        
        return variance_analysis
    
    def _interpret_variance(self, variance: float, standard: float) -> str:
        """解释差异"""
        if standard == 0:
            return "无法分析"
        
        rate = variance / standard * 100
        
        if rate > 10:
            return "成本超支严重，需重点关注"
        elif rate > 5:
            return "成本超出预期，需分析原因"
        elif rate > -5:
            return "成本在正常范围"
        else:
            return "成本节约，表现优秀"
    
    async def calculate_scrapped_material_cost(
        self,
        work_order_id: str,
    ) -> Dict[str, Any]:
        """
        计算实际抛料成本
        
        重点: 实际抛料材料成本黑洞
        """
        # 从不良品记录获取报废数量
        defects = await self._get_defects(work_order_id)
        
        total_scrapped_cost = 0.0
        scrap_by_type = {}
        
        for defect in defects:
            if defect.get("disposition") == "scrap":
                material_cost = defect.get("quantity", 0) * defect.get("unit_cost", 0)
                total_scrapped_cost += material_cost
                
                defect_type = defect.get("defect_type", "unknown")
                scrap_by_type[defect_type] = scrap_by_type.get(defect_type, 0) + material_cost
        
        return {
            "work_order_id": work_order_id,
            "total_scrapped_cost": total_scrapped_cost,
            "scrap_by_type": scrap_by_type,
            "total_defects": len(defects),
        }
    
    async def _get_defects(self, work_order_id: str) -> List[Dict[str, Any]]:
        """获取不良品记录"""
        # TODO: 查询不良品表
        return []
    
    async def get_work_order_cost_report(
        self,
        factory_id: str,
        from_date: date,
        to_date: date,
    ) -> Dict[str, Any]:
        """工单成本报表"""
        report = {
            "factory_id": factory_id,
            "period": f"{from_date} - {to_date}",
            "total_work_orders": 0,
            "total_produced_qty": 0,
            "total_material_cost": 0.0,
            "total_labor_cost": 0.0,
            "total_overhead_cost": 0.0,
            "total_cost": 0.0,
            "average_unit_cost": 0.0,
            "work_orders": [],
        }
        
        # TODO: 查询汇总数据
        
        return report
    
    async def get_product_cost_report(
        self,
        factory_id: str,
        from_date: date,
        to_date: date,
    ) -> Dict[str, Any]:
        """产品成本报表"""
        report = {
            "factory_id": factory_id,
            "period": f"{from_date} - {to_date}",
            "products": [],
            "total_cost": 0.0,
        }
        
        # TODO: 查询产品成本汇总
        
        return report


__all__ = ["CostingService", "CostType", "CostStatus"]
