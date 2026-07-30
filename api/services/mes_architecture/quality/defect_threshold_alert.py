"""Defect Threshold Alert Strategy for Mes Operations

When defect rate exceeds a defined threshold, this strategy triggers an
alert and may pause production to prevent further quality issues.
"""

from typing import Dict, Any
from ..recovery.base import MesRecoveryStrategy, MesRecoveryResult


class DefectThresholdAlert(MesRecoveryStrategy):
    """Alerts when defect rate exceeds configured threshold."""
    
    def __init__(self, defect_threshold: float = 0.05):
        self.defect_threshold = defect_threshold
    
    def get_strategy_name(self) -> str:
        return "defect_threshold_alert"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        has_good = "good_qty" in context and isinstance(context["good_qty"], (int, float))
        has_defect = "defect_qty" in context and isinstance(context["defect_qty"], (int, float))
        return has_good and has_defect
    
    def execute(self, context: Dict[str, Any]) -> MesRecoveryResult:
        good_qty = context["good_qty"]
        defect_qty = context["defect_qty"]
        total = good_qty + defect_qty
        
        if total == 0:
            return MesRecoveryResult(
                strategy_name=self.get_strategy_name(),
                applied=False,
                context=context,
                message="No production data to evaluate defect rate"
            )
        
        defect_rate = defect_qty / total
        
        if defect_rate > self.defect_threshold:
            return MesRecoveryResult(
                strategy_name=self.get_strategy_name(),
                applied=True,
                context=context,
                message=f"Defect rate {defect_rate:.2%} exceeds threshold {self.defect_threshold:.2%}. Quality alert triggered."
            )
        
        return MesRecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=False,
            context=context,
            message=None
        )