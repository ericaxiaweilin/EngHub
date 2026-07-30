"""Equipment Failure Recovery Strategy for Mes Operations

When equipment failure is detected, this strategy triggers downtime logging
and initiates the recovery process.
"""

from typing import Dict, Any, Optional
from datetime import datetime
from ..recovery.base import MesRecoveryStrategy, MesRecoveryResult


class EquipmentFailureRecovery(MesRecoveryStrategy):
    """Handles equipment failures by logging downtime and triggering alerts."""
    
    def __init__(self, min_downtime_minutes: int = 5):
        self.min_downtime_minutes = min_downtime_minutes
    
    def get_strategy_name(self) -> str:
        return "equipment_failure_recovery"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        has_equipment = "equipment_id" in context
        has_downtime = ("downtime_minutes" in context or 
                       "start_time" in context and "end_time" in context)
        return has_equipment and has_downtime
    
    def execute(self, context: Dict[str, Any]) -> MesRecoveryResult:
        equipment_id = context["equipment_id"]
        factory_id = context.get("factory_id", "F01")
        
        downtime_minutes = context.get("downtime_minutes")
        start_time = context.get("start_time")
        end_time = context.get("end_time")
        
        if downtime_minutes is None and start_time and end_time:
            try:
                if isinstance(start_time, str):
                    start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                else:
                    start_dt = start_time
                
                if isinstance(end_time, str):
                    end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                else:
                    end_dt = end_time
                
                downtime_minutes = ((end_dt - start_dt).total_seconds() / 60)
            except Exception:
                downtime_minutes = 0
        
        if downtime_minutes is None:
            downtime_minutes = 0
        
        if downtime_minutes >= self.min_downtime_minutes:
            recovery_action = self._initiate_repair_process(equipment_id, factory_id, downtime_minutes)
            
            return MesRecoveryResult(
                strategy_name=self.get_strategy_name(),
                applied=True,
                context=context,
                message=f"Equipment {equipment_id} downtime {downtime_minutes:.1f}min triggered repair process. Action: {recovery_action}"
            )
        
        return MesRecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=False,
            context=context,
            message=f"Equipment {equipment_id} downtime {downtime_minutes:.1f}min below threshold ({self.min_downtime_minutes}min), no recovery required"
        )
    
    def _initiate_repair_process(self, equipment_id: str, factory_id: str, downtime_minutes: float) -> str:
        if downtime_minutes > 60:
            return f"Scheduled extended maintenance for {equipment_id} at {factory_id}"
        elif downtime_minutes > 15:
            return f"Dispatched maintenance team for {equipment_id}"
        else:
            return f"Logged minor maintenance note for {equipment_id}"