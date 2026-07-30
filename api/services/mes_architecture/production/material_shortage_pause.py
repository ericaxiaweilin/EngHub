"""Material Shortage Pause Strategy for Mes Operations

When required materials are insufficient for a production order/work operation,
this strategy pauses the operation and returns shortage details.
"""

from typing import Dict, Any
# Import from the central recovery base module (not relative!)
from ..recovery.base import MesRecoveryStrategy, MesRecoveryResult


class MaterialShortagePause(MesRecoveryStrategy):
    """Pauses production when materials are insufficient.
    
    Checks inventory against required quantities and prevents operations
    from proceeding when stock is below the required threshold.
    """
    
    def __init__(self, safety_buffer: int = 10):
        self.safety_buffer = safety_buffer
    
    def get_strategy_name(self) -> str:
        return "material_shortage_pause"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        has_material = "material_id" in context or "product_id" in context
        has_required = "required_qty" in context and isinstance(context["required_qty"], (int, float))
        return has_material and has_required
    
    def execute(self, context: Dict[str, Any]) -> MesRecoveryResult:
        material_id = context.get("material_id") or context.get("product_id")
        required_qty = context["required_qty"]
        factory_id = context.get("factory_id", "F01")
        
        if not material_id:
            return MesRecoveryResult(
                strategy_name=self.get_strategy_name(),
                applied=False,
                context=context,
                message="No material identifier provided"
            )
        
        current_inventory = self._get_inventory(material_id, factory_id)
        available_for_production = max(0, current_inventory - self.safety_buffer)
        
        if required_qty > available_for_production:
            shortage_amount = required_qty - available_for_production
            return MesRecoveryResult(
                strategy_name=self.get_strategy_name(),
                applied=True,
                context=context,
                message=f"Material {material_id} shortage: require {required_qty}, have only {available_for_production} (available after safety buffer)"
            )
        
        return MesRecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=False,
            context=context,
            message=None
        )
    
    def _get_inventory(self, material_id: str, factory_id: str) -> int:
        sample_inventory = {
            ("芯片模组", "F01"): 8000,
            ("鞋底组件", "F01"): 1500,
            ("MAT-CONN-002", "FAC_ELEC_DEMO_2026"): 280,
            ("MAT-BAT-003", "FAC_ELEC_DEMO_2026"): 600,
            ("MAT-PCB-001", "FAC_ELEC_DEMO_2026"): 0,
        }
        return sample_inventory.get((material_id, factory_id), 0)