"""Capacity Limit Reject Strategy for Mes Operations

When a production report or operation exceeds the defined capacity limit
for a station, this strategy rejects the operation and returns an error.
"""

from typing import Dict, Any
from .base import MesRecoveryStrategy, MesRecoveryResult


class CapacityLimitReject(MesRecoveryStrategy):
    """Rejects production reports when reported quantity exceeds capacity limit.
    
    This is a preventive strategy that stops over-production before it creates
    inventory imbalances or scheduling issues.
    """
    
    def __init__(self, default_capacity: int = 100):
        """Initialize with default capacity per shift."""
        self.default_capacity = default_capacity
    
    def get_strategy_name(self) -> str:
        return "capacity_limit_reject"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        """Check if this strategy applies.
        
        Requires both reported_qty and station_id in context.
        """
        return (
            "reported_qty" in context and 
            "station_id" in context and 
            isinstance(context["reported_qty"], (int, float))
        )
    
    def execute(self, context: Dict[str, Any]) -> MesRecoveryResult:
        """Execute the capacity limit rejection check.
        
        Returns the original context if within limit, otherwise returns
        a rejected result with error details.
        """
        reported_qty = context["reported_qty"]
        station_id = context["station_id"]
        
        # In real implementation, fetch actual capacity from DB/cache
        capacity = self._get_station_capacity(station_id)
        
        if reported_qty > capacity:
            return MesRecoveryResult(
                strategy_name=self.get_strategy_name(),
                applied=True,
                context=context,
                message=f"Reported quantity {reported_qty} exceeds capacity {capacity} for station {station_id}"
            )
        
        # Within capacity, no action needed
        return MesRecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=False,
            context=context,
            message=None
        )
    
    def _get_station_capacity(self, station_id: str) -> int:
        """Fetch station capacity from database or cache.
        
        In production, this should query the Station table or read from
        a capacity cache service. For now, uses a lookup or default.
        """
        # Sample hardcoded capacities - replace with DB call in real implementation
        capacity_map = {
            "ST-ASSY-01": 500,
            "ST-SMT-01": 800,
            "CNC-001": 200,
            "CNC-002": 200,
            "EDM-001": 100,
        }
        return capacity_map.get(station_id, self.default_capacity)