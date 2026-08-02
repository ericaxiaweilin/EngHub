"""
MES Equipment Service
设备状态关联模块

功能:
- 设备状态管理
- 设备故障时限制下达工单
- 设备状态对生产报工的影响
"""

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class EquipmentStatus(str, Enum):
    """设备状态"""
    RUNNING = "running"       # 运行中
    IDLE = "idle"             # 空闲
    FAULT = "fault"           # 故障
    MAINTENANCE = "maintenance"  # 保养中
    BROKEN = "broken"         # 损坏


class EquipmentService:
    """
    设备服务 - 用于生产工单与设备状态的关联
    
    核心功能:
    - 设备状态查询
    - 设备故障时限制下达工单
    - 报工时检查设备状态
    """
    
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
    
    async def get_equipment_status(
        self,
        equipment_id: str,
    ) -> Optional[Dict[str, Any]]:
        """获取设备状态"""
        equipment = {
            "id": equipment_id,
            "status": EquipmentStatus.RUNNING.value,
            "station_id": "ST-001",
            "last_maintenance_date": None,
            "next_maintenance_date": None,
        }
        return equipment
    
    async def check_equipment_available_for_work_order(
        self,
        station_id: str,
    ) -> Dict[str, Any]:
        """
        检查工位关联的设备是否可用于生产
        
        Args:
            station_id: 工位ID
        
        Returns:
            {
                "can_proceed": True/False,
                "reason": "设备正常" / "设备故障中",
                "equipment_status": "running",
                "affected_work_orders": []
            }
        """
        result = {
            "can_proceed": True,
            "reason": "设备正常",
            "equipment_status": EquipmentStatus.RUNNING.value,
            "station_id": station_id,
            "affected_work_orders": [],
        }
        
        # TODO: 查询设备状态
        # 如果设备状态为 fault/broken/maintenance，则阻止生产
        
        return result
    
    async def check_work_order_equipment_status(
        self,
        work_order_id: str,
    ) -> Dict[str, Any]:
        """
        检查工单关联的设备状态
        
        Args:
            work_order_id: 工单ID
        
        Returns:
            设备状态检查结果
        """
        result = {
            "work_order_id": work_order_id,
            "can_proceed": True,
            "status": "normal",
            "message": "设备状态正常，可以生产",
        }
        
        # 1. 获取工单关联的工位
        # 2. 检查工位关联的设备状态
        # 3. 如果设备故障，返回阻止信息
        
        return result
    
    async def block_work_order_due_to_equipment(
        self,
        work_order_id: str,
        equipment_id: str,
        blocked_by: str,
        reason: str,
    ) -> Dict[str, Any]:
        """
        因设备故障阻止工单下达
        
        Args:
            work_order_id: 工单ID
            equipment_id: 设备ID
            blocked_by: 阻止人ID
            reason: 阻止原因
        
        Returns:
            阻止记录
        """
        block_record = {
            "id": str(uuid.uuid4()),
            "work_order_id": work_order_id,
            "equipment_id": equipment_id,
            "block_type": "equipment_fault",
            "blocked_by": blocked_by,
            "reason": reason,
            "blocked_at": datetime.now(),
            "resolved_at": None,
            "status": "blocked",
        }
        
        return block_record
    
    async def get_equipment_maintenance_schedule(
        self,
        station_id: str,
    ) -> List[Dict[str, Any]]:
        """获取设备保养计划"""
        schedule = [
            {
                "equipment_id": "EQ-001",
                "maintenance_type": "preventive",
                "scheduled_date": "2026-03-01",
                "status": "scheduled",
            }
        ]
        return schedule
    
    async def calculate_oee(
        self,
        station_id: str,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        """
        计算设备综合效率 OEE
        
        OEE = 可用率 × 性能率 × 良品率
        
        Args:
            station_id: 工位ID
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            OEE计算结果
        """
        oee_data = {
            "station_id": station_id,
            "period": f"{start_date} - {end_date}",
            "availability": 0.95,      # 可用率
            "performance": 0.88,       # 性能率
            "quality": 0.98,           # 良品率
            "oee": 0.82,              # OEE = 0.95 * 0.88 * 0.98
            "planned_production_time": 480,  # 计划生产时间(分钟)
            "actual_production_time": 450,    # 实际生产时间
            "ideal_cycle_time": 10,          # 标准周期时间(秒)
            "total_produced": 2500,
            "good_produced": 2450,
        }
        
        return oee_data


__all__ = [
    "EquipmentService",
    "EquipmentStatus",
]
