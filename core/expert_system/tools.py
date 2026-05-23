"""
MES 生产专家系统工具集

提供专家系统可调用的工具函数，用于：
- 查询实时生产数据
- 获取工单状态
- 查询设备信息
- 分析质量数据
- 计算 OEE 等指标
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta


class ToolRegistry:
    """工具注册表"""
    
    def __init__(self):
        self.tools = {}
        self._register_builtin_tools()
        
    def _register_builtin_tools(self):
        """注册内置工具"""
        # 生产数据查询类
        self.register("get_work_order_status", self.get_work_order_status)
        self.register("get_station_info", self.get_station_info)
        self.register("get_production_data", self.get_production_data)
        
        # 质量分析类
        self.register("get_quality_metrics", self.get_quality_metrics)
        self.register("analyze_defects", self.analyze_defects)
        
        # 设备监控类
        self.register("get_device_status", self.get_device_status)
        self.register("get_oee_metrics", self.get_oee_metrics)
        
        # 库存物料类
        self.register("get_inventory_level", self.get_inventory_level)
        self.register("get_material_shortage", self.get_material_shortage)
        
    def register(self, name: str, func):
        """注册工具"""
        self.tools[name] = {
            "function": func,
            "name": name,
            "description": func.__doc__ or ""
        }
        
    def get_tool(self, name: str):
        """获取工具"""
        return self.tools.get(name)
        
    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有可用工具"""
        return [
            {
                "name": info["name"],
                "description": info["description"]
            }
            for info in self.tools.values()
        ]
        
    # ========== 生产数据查询工具 ==========
    
    async def get_work_order_status(self, work_order_id: str) -> Dict[str, Any]:
        """
        查询工单状态
        
        Args:
            work_order_id: 工单编号
            
        Returns:
            工单详细信息包括状态、进度、预计完成时间等
        """
        # TODO: 调用实际 API
        return {
            "work_order_id": work_order_id,
            "status": "in_progress",
            "product_name": "示例产品 A",
            "planned_quantity": 1000,
            "completed_quantity": 650,
            "progress_percent": 65.0,
            "start_time": "2025-01-15T08:00:00Z",
            "estimated_completion": "2025-01-16T16:00:00Z",
            "current_station": "SMT-01",
            "priority": "normal"
        }
        
    async def get_station_info(self, station_id: str) -> Dict[str, Any]:
        """
        查询工位信息
        
        Args:
            station_id: 工位编号
            
        Returns:
            工位配置、当前任务、产能等信息
        """
        # TODO: 调用实际 API
        return {
            "station_id": station_id,
            "name": "SMT 贴片线 01",
            "type": "assembly",
            "status": "running",
            "current_operator": "张三",
            "capacity_per_hour": 120,
            "current_wip": 45,
            "queue_length": 12
        }
        
    async def get_production_data(self, 
                                   start_time: str, 
                                   end_time: str,
                                   station_id: Optional[str] = None) -> Dict[str, Any]:
        """
        查询生产数据
        
        Args:
            start_time: 开始时间 (ISO 格式)
            end_time: 结束时间 (ISO 格式)
            station_id: 可选的工位筛选
            
        Returns:
            产量、良率、工时等统计数据
        """
        # TODO: 调用实际 API
        return {
            "period": {"start": start_time, "end": end_time},
            "total_output": 2500,
            "good_quantity": 2425,
            "defect_quantity": 75,
            "yield_rate": 97.0,
            "total_downtime_minutes": 45,
            "stations": station_id or "all"
        }
        
    # ========== 质量分析工具 ==========
    
    async def get_quality_metrics(self, 
                                   product_id: Optional[str] = None,
                                   time_range: str = "24h") -> Dict[str, Any]:
        """
        获取质量指标
        
        Args:
            product_id: 产品 ID (可选)
            time_range: 时间范围 (24h/7d/30d)
            
        Returns:
            FPY、DPU、DPMO 等质量指标
        """
        # TODO: 调用实际 API
        return {
            "time_range": time_range,
            "product_id": product_id or "all",
            "fpy": 96.5,  # 首次通过率
            "dpu": 0.035,  # 单位缺陷数
            "dpmo": 350,  # 百万机会缺陷数
            "top_defects": [
                {"type": "焊接不良", "count": 25, "percent": 33.3},
                {"type": "元件错位", "count": 18, "percent": 24.0},
                {"type": "外观划伤", "count": 15, "percent": 20.0}
            ]
        }
        
    async def analyze_defects(self, 
                               defect_type: str,
                               time_range: str = "24h") -> Dict[str, Any]:
        """
        分析特定缺陷类型
        
        Args:
            defect_type: 缺陷类型
            time_range: 时间范围
            
        Returns:
            缺陷分布、根本原因分析建议
        """
        # TODO: 实现缺陷分析逻辑
        return {
            "defect_type": defect_type,
            "occurrence_count": 25,
            "trend": "increasing",
            "affected_stations": ["SMT-01", "SMT-02"],
            "possible_causes": [
                "钢网张力不足导致锡膏印刷不良",
                "回流焊温度曲线需要优化",
                "元件供料器需要校准"
            ],
            "recommended_actions": [
                "检查钢网张力并重新张紧",
                "验证回流焊温度曲线",
                "安排供料器预防性维护"
            ]
        }
        
    # ========== 设备监控工具 ==========
    
    async def get_device_status(self, device_id: str) -> Dict[str, Any]:
        """
        查询设备状态
        
        Args:
            device_id: 设备编号
            
        Returns:
            设备运行状态、告警信息、维护记录
        """
        # TODO: 调用实际 API
        return {
            "device_id": device_id,
            "name": "贴片机 PM-500",
            "status": "running",
            "uptime_hours": 168.5,
            "current_alarm": None,
            "last_maintenance": "2025-01-10T14:00:00Z",
            "next_maintenance_due": "2025-01-25T14:00:00Z",
            "health_score": 92
        }
        
    async def get_oee_metrics(self, 
                               station_id: str,
                               time_range: str = "24h") -> Dict[str, Any]:
        """
        计算 OEE (整体设备效率) 指标
        
        Args:
            station_id: 工位/设备编号
            time_range: 时间范围
            
        Returns:
            OEE 及三大要素 (可用率、性能率、良品率)
        """
        # TODO: 调用实际 API 计算
        availability = 92.0  # 可用率
        performance = 88.0   # 性能率
        quality = 97.0       # 良品率
        oee = (availability * performance * quality) / 10000
        
        return {
            "station_id": station_id,
            "time_range": time_range,
            "oee": round(oee, 2),
            "availability": availability,
            "performance": performance,
            "quality": quality,
            "target_oee": 85.0,
            "status": "good" if oee >= 85 else "needs_improvement",
            "loss_analysis": {
                "availability_loss": ["设备故障 25min", "换型 35min"],
                "performance_loss": ["小停机 15min", "速度降低 8%"],
                "quality_loss": ["启动不良 12pcs", "过程不良 18pcs"]
            }
        }
        
    # ========== 库存物料工具 ==========
    
    async def get_inventory_level(self, material_id: str) -> Dict[str, Any]:
        """
        查询物料库存水平
        
        Args:
            material_id: 物料编号
            
        Returns:
            当前库存、安全库存、在途数量等
        """
        # TODO: 调用 WMS API
        return {
            "material_id": material_id,
            "name": "电阻 0603 10KΩ",
            "current_stock": 15000,
            "safety_stock": 5000,
            "on_order": 20000,
            "expected_arrival": "2025-01-18",
            "daily_consumption": 1200,
            "days_of_supply": 12.5,
            "status": "normal"
        }
        
    async def get_material_shortage(self, 
                                     work_order_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        查询缺料情况
        
        Args:
            work_order_id: 可选的工单筛选
            
        Returns:
            缺料列表及影响分析
        """
        # TODO: 调用 MRP/WMS API
        return [
            {
                "material_id": "IC-MCU-001",
                "name": "主控芯片 STM32F103",
                "required_quantity": 500,
                "available_quantity": 320,
                "shortage": 180,
                "affected_work_orders": ["WO-2025-0115-001", "WO-2025-0115-003"],
                "impact": "high",
                "expected_resolution": "2025-01-17"
            }
        ]


# 全局工具注册表实例
tool_registry = ToolRegistry()
