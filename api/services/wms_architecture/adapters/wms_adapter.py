"""WMS Adapter - Orchestrator for WMS operations using orthogonal components.

This adapter replaces the monolithic WMS service implementations by delegating all
complex processing to specialized components contained within
api/services/wms_architecture/. All business logic is encapsulated; this file
contains only orchestration sequencing.

Architecture:
- InboundExecutor: Handles inbound operations
- OutboundExecutor: Handles outbound operations
- TransferExecutor: Handles transfer operations
- CountExecutor: Handles inventory count operations
- TraceExecutor: Handles batch trace operations
- FifoExecutor: Handles FIFO picking recommendations
- ReplenishExecutor: Handles replenishment suggestions
- KitCheckExecutor: Handles kit check operations
- DeadStockExecutor: Handles dead stock alerts
- LocationExecutor: Handles location optimization
- StateTransitionEngine: Manages inventory state transitions
- RecoveryExecutor: Handles error recovery strategies
"""

from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

# Import architecture components
from ..executors.inbound_executor import InboundExecutor
from ..executors.outbound_executor import OutboundExecutor
from ..executors.transfer_executor import TransferExecutor
from ..executors.count_executor import CountExecutor
from ..executors.trace_executor import TraceExecutor
from ..executors.fifo_executor import FifoExecutor
from ..executors.replenish_executor import ReplenishExecutor
from ..executors.kit_check_executor import KitCheckExecutor
from ..executors.dead_stock_executor import DeadStockExecutor
from ..executors.location_executor import LocationExecutor
from ..executors.batch_expiry_executor import BatchExpiryExecutor
from ..executors.location_capacity_executor import LocationCapacityExecutor
from ..executors.inventory_alert_executor import InventoryAlertExecutor
from ..executors.abc_analysis_executor import AbcAnalysisExecutor
from ..executors.volume_management_executor import VolumeManagementExecutor
from ..state.engine import StateTransitionEngine, InventoryState
from ..recovery.executor import RecoveryExecutor


class WmsAdapter:
    """WMS processing adapter using fully decoupled architecture.
    
    All business logic resides in delegated components. The adapter itself
    merely sequences operations correctly.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.state_engine = StateTransitionEngine()
        
        # Initialize executors
        self.executors = {
            "inbound": InboundExecutor(),
            "outbound": OutboundExecutor(),
            "transfer": TransferExecutor(),
            "count": CountExecutor(),
            "trace": TraceExecutor(),
            "fifo": FifoExecutor(),
            "replenish": ReplenishExecutor(),
            "kit_check": KitCheckExecutor(),
            "dead_stock": DeadStockExecutor(),
            "location": LocationExecutor(),
            "batch_expiry": BatchExpiryExecutor(),
            "location_capacity": LocationCapacityExecutor(),
            "inventory_alert": InventoryAlertExecutor(),
            "abc_analysis": AbcAnalysisExecutor(),
            "volume_management": VolumeManagementExecutor(),
        }
        
        # Initialize recovery executor
        RecoveryExecutor.initialize_default_strategies()
    
    async def quick_inbound(
        self,
        factory_id: str,
        material_id: str,
        material_code: str,
        quantity: int,
        warehouse_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Quick inbound operation."""
        context = {
            "factory_id": factory_id,
            "material_id": material_id,
            "material_code": material_code,
            "quantity": quantity,
            "warehouse_id": warehouse_id,
            **kwargs,
        }
        
        try:
            return await self.executors["inbound"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def quick_outbound(
        self,
        factory_id: str,
        material_id: str,
        quantity: int,
        **kwargs
    ) -> Dict[str, Any]:
        """Quick outbound operation."""
        context = {
            "factory_id": factory_id,
            "material_id": material_id,
            "quantity": quantity,
            **kwargs,
        }
        
        try:
            return await self.executors["outbound"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def transfer(
        self,
        factory_id: str,
        material_id: str,
        quantity: int,
        from_warehouse_id: str,
        to_warehouse_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Transfer operation."""
        context = {
            "factory_id": factory_id,
            "material_id": material_id,
            "quantity": quantity,
            "from_warehouse_id": from_warehouse_id,
            "to_warehouse_id": to_warehouse_id,
            **kwargs,
        }
        
        try:
            return await self.executors["transfer"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def create_count_task(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Create count task."""
        context = {
            "factory_id": factory_id,
            "operation": "create_task",
            **kwargs,
        }
        
        try:
            return await self.executors["count"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def submit_count(
        self,
        factory_id: str,
        task_id: str,
        item_id: str,
        counted_qty: int,
        **kwargs
    ) -> Dict[str, Any]:
        """Submit count result."""
        context = {
            "factory_id": factory_id,
            "operation": "submit_count",
            "task_id": task_id,
            "item_id": item_id,
            "counted_qty": counted_qty,
            **kwargs,
        }
        
        try:
            return await self.executors["count"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def list_count_tasks(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """List count tasks."""
        context = {
            "factory_id": factory_id,
            "operation": "list_tasks",
            **kwargs,
        }
        
        try:
            return await self.executors["count"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def batch_trace(
        self,
        factory_id: str,
        batch_code: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Batch trace operation."""
        context = {
            "factory_id": factory_id,
            "batch_code": batch_code,
            **kwargs,
        }
        
        try:
            return await self.executors["trace"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def fifo_pick_suggestion(
        self,
        factory_id: str,
        material_code: str,
        qty_needed: int,
        **kwargs
    ) -> Dict[str, Any]:
        """FIFO pick suggestion."""
        context = {
            "factory_id": factory_id,
            "material_code": material_code,
            "qty_needed": qty_needed,
            **kwargs,
        }
        
        try:
            return await self.executors["fifo"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def replenishment_suggestions(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Replenishment suggestions."""
        context = {
            "factory_id": factory_id,
            "operation": "suggestions",
            **kwargs,
        }
        
        try:
            return await self.executors["replenish"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def auto_replenish(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Auto replenish."""
        context = {
            "factory_id": factory_id,
            "operation": "auto_replenish",
            **kwargs,
        }
        
        try:
            return await self.executors["replenish"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def kit_check(
        self,
        factory_id: str,
        work_order_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Kit check operation."""
        context = {
            "factory_id": factory_id,
            "work_order_id": work_order_id,
            **kwargs,
        }
        
        try:
            return await self.executors["kit_check"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def dead_stock_check(
        self,
        factory_id: str,
        days_threshold: int = 90,
        **kwargs
    ) -> Dict[str, Any]:
        """Dead stock check."""
        context = {
            "factory_id": factory_id,
            "operation": "check",
            "days_threshold": days_threshold,
            **kwargs,
        }
        
        try:
            return await self.executors["dead_stock"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def location_optimization(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Location optimization."""
        context = {
            "factory_id": factory_id,
            "operation": "optimize",
            **kwargs,
        }
        
        try:
            return await self.executors["location"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def batch_expiry_check(
        self,
        factory_id: str,
        days_threshold: int = 30,
        **kwargs
    ) -> Dict[str, Any]:
        """Batch expiry check."""
        context = {
            "factory_id": factory_id,
            "operation": "check_expiry",
            "days_threshold": days_threshold,
            **kwargs,
        }
        
        try:
            return await self.executors["batch_expiry"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def batch_expiry_warnings(
        self,
        factory_id: str,
        days_threshold: int = 30,
        **kwargs
    ) -> Dict[str, Any]:
        """Batch expiry warnings."""
        context = {
            "factory_id": factory_id,
            "operation": "get_warnings",
            "days_threshold": days_threshold,
            **kwargs,
        }
        
        try:
            return await self.executors["batch_expiry"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def lock_batch(
        self,
        factory_id: str,
        batch_code: str,
        lock_reason: str = "manual_lock",
        **kwargs
    ) -> Dict[str, Any]:
        """Lock a batch."""
        context = {
            "factory_id": factory_id,
            "operation": "lock_batch",
            "batch_code": batch_code,
            "lock_reason": lock_reason,
            **kwargs,
        }
        
        try:
            return await self.executors["batch_expiry"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def unlock_batch(
        self,
        factory_id: str,
        batch_code: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Unlock a batch."""
        context = {
            "factory_id": factory_id,
            "operation": "unlock_batch",
            "batch_code": batch_code,
            **kwargs,
        }
        
        try:
            return await self.executors["batch_expiry"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_location_capacity(
        self,
        factory_id: str,
        warehouse_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Get location capacity."""
        context = {
            "factory_id": factory_id,
            "operation": "get_capacity",
            "warehouse_id": warehouse_id,
            **kwargs,
        }
        
        try:
            return await self.executors["location_capacity"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def update_location_capacity(
        self,
        factory_id: str,
        location_id: str,
        capacity: int,
        **kwargs
    ) -> Dict[str, Any]:
        """Update location capacity."""
        context = {
            "factory_id": factory_id,
            "operation": "update_capacity",
            "location_id": location_id,
            "capacity": capacity,
            **kwargs,
        }
        
        try:
            return await self.executors["location_capacity"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_location_status(
        self,
        factory_id: str,
        warehouse_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Get location status."""
        context = {
            "factory_id": factory_id,
            "operation": "get_status",
            "warehouse_id": warehouse_id,
            **kwargs,
        }
        
        try:
            return await self.executors["location_capacity"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def list_locations(
        self,
        factory_id: str,
        warehouse_id: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """List all locations."""
        context = {
            "factory_id": factory_id,
            "operation": "list_locations",
            "warehouse_id": warehouse_id,
            **kwargs,
        }
        
        try:
            return await self.executors["location_capacity"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_inventory_alerts(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get all inventory alerts."""
        context = {
            "factory_id": factory_id,
            "operation": "get_alerts",
            **kwargs,
        }
        
        try:
            return await self.executors["inventory_alert"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_low_stock_alerts(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get low stock alerts."""
        context = {
            "factory_id": factory_id,
            "operation": "get_low_stock",
            **kwargs,
        }
        
        try:
            return await self.executors["inventory_alert"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_overstock_alerts(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get overstock alerts."""
        context = {
            "factory_id": factory_id,
            "operation": "get_overstock",
            **kwargs,
        }
        
        try:
            return await self.executors["inventory_alert"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_stagnant_alerts(
        self,
        factory_id: str,
        days_threshold: int = 90,
        **kwargs
    ) -> Dict[str, Any]:
        """Get stagnant stock alerts."""
        context = {
            "factory_id": factory_id,
            "operation": "get_stagnant",
            "days_threshold": days_threshold,
            **kwargs,
        }
        
        try:
            return await self.executors["inventory_alert"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_expiry_alerts(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get expiry alerts."""
        context = {
            "factory_id": factory_id,
            "operation": "get_expiry",
            **kwargs,
        }
        
        try:
            return await self.executors["inventory_alert"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def abc_analysis(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """ABC analysis."""
        context = {
            "factory_id": factory_id,
            "operation": "analyze",
            **kwargs,
        }
        
        try:
            return await self.executors["abc_analysis"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_turnover_analysis(
        self,
        factory_id: str,
        period_days: int = 30,
        **kwargs
    ) -> Dict[str, Any]:
        """Get turnover analysis."""
        context = {
            "factory_id": factory_id,
            "operation": "get_turnover",
            "period_days": period_days,
            **kwargs,
        }
        
        try:
            return await self.executors["abc_analysis"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_cost_analysis(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get cost analysis."""
        context = {
            "factory_id": factory_id,
            "operation": "get_cost",
            **kwargs,
        }
        
        try:
            return await self.executors["abc_analysis"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_utilization_analysis(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get utilization analysis."""
        context = {
            "factory_id": factory_id,
            "operation": "get_utilization",
            **kwargs,
        }
        
        try:
            return await self.executors["abc_analysis"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def track_volume(
        self,
        factory_id: str,
        material_id: str,
        quantity: float,
        **kwargs
    ) -> Dict[str, Any]:
        """Track volume for inventory items."""
        context = {
            "factory_id": factory_id,
            "material_id": material_id,
            "quantity": quantity,
            "operation": "track_volume",
            **kwargs,
        }
        
        try:
            return await self.executors["volume_management"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_volume_summary(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get volume summary."""
        context = {
            "factory_id": factory_id,
            "operation": "get_volume_summary",
            **kwargs,
        }
        
        try:
            return await self.executors["volume_management"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def calculate_shipping_volume(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Calculate shipping volume."""
        context = {
            "factory_id": factory_id,
            "operation": "calculate_shipping_volume",
            **kwargs,
        }
        
        try:
            return await self.executors["volume_management"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def get_space_utilization(
        self,
        factory_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Get space utilization analysis."""
        context = {
            "factory_id": factory_id,
            "operation": "get_space_utilization",
            **kwargs,
        }
        
        try:
            return await self.executors["volume_management"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def update_volume(
        self,
        factory_id: str,
        material_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Update volume and weight for inventory items."""
        context = {
            "factory_id": factory_id,
            "material_id": material_id,
            "operation": "update_volume",
            **kwargs,
        }
        
        try:
            return await self.executors["volume_management"].execute(self.db, factory_id, context)
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def transition_state(
        self,
        factory_id: str,
        inventory_id: str,
        from_state: InventoryState,
        to_state: InventoryState,
        **context
    ) -> Dict[str, Any]:
        """Transition inventory state."""
        try:
            new_state = self.state_engine.transition(from_state, to_state, context)
            return {
                "success": True,
                "inventory_id": inventory_id,
                "from_state": from_state.value,
                "to_state": new_state.value,
                "timestamp": context.get("timestamp", datetime.utcnow().isoformat()),
            }
        except Exception as e:
            return await self._handle_error(e, context)
    
    async def _handle_error(self, error: Exception, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle errors with recovery strategies."""
        error_context = {
            **context,
            "error": str(error),
            "error_type": type(error).__name__,
        }
        
        # Try recovery strategies
        recovery_result = RecoveryExecutor.execute_all(error_context)
        if recovery_result:
            return {
                "success": False,
                "error": str(error),
                "recovery_applied": recovery_result.strategy_name,
                "recovery_message": recovery_result.message,
                "suggestion": recovery_result.context.get("suggestion"),
            }
        
        # No recovery applied
        return {
            "success": False,
            "error": str(error),
            "error_type": type(error).__name__,
            "suggestion": "建议联系管理员",
        }