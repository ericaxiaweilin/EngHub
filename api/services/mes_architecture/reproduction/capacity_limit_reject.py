"""Capacity Limit Reject Strategy for Mes Operations

When a production report or operation exceeds the defined capacity limit
for a station, this strategy rejects the operation and returns an error.
"""

from typing import Dict, Any
# Import from the central recovery base module
from ..recovery.base import MesRecoveryStrategy, MesRecoveryResult


class CapacityLimitReject(MesRecoveryStrategy):
    """Rejects production reports when reported quantity exceeds capacity limit."""
    
    def __init__(self, default_capacity: int = 100):
        self.default_capacity = default_capacity
    
    def get_strategy_name(self) -> str:
        return "capacity_limit_reject"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        return (
            "reported_qty" in context and 
            "station_id" in context and 
            isinstance(context["reported_qty"], (int, float))
        )
    
    def execute(self, context: Dict[str, Any]) -> MesRecoveryResult:
        reported_qty = context["reported_qty"]
        station_id = context["station_id"]
        capacity = self._get_station_capacity(station_id)
        
        if reported_qty > capacity:
            return MesRecoveryResult(
                strategy_name=self.get_strategy_name(),
                applied=True,
                context=context,
                message=f"Reported quantity {reported_qty} exceeds capacity {capacity} for station {station_id}"
            )
        
        return MesRecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=False,
            context=context,
            message=None
        )
    
    def _get_station_capacity(self, station_id: str) -> int:
        capacity_map = {
            "ST-ASSY-01": 500,
            "ST-SMT-01": 800,
            "CNC-001": 200,
            "CNC-002": 200,
            "EDM-001": 100,
        }
        return capacity_map.get(station_id, self.default_capacity)