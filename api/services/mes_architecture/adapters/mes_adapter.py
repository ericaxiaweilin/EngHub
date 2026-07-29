"""MES Adapter - Thin Orchestrator for MES Operations

This adapter serves as the single entry point for all MES operations.
It delegates to the extracted orthogonal components and should NOT contain
business logic for decisions or recovery - only orchestration.

The pattern follows: Request → Parser → Validation Engine → State Machine 
→ Repository (data access) → Response Formatter → Response
"""

from typing import Optional, Dict, Any, List
from fastapi import HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...schemas.mes_schemas import (
    WorkOrderQueryCriteria, WorkOrderResponse, WorkOrderUpdateRequest,
    ProductionReportRequest, ProductionReportResponse
)
from ...resolvers.factory_resolver import FactoryResolver
from ...resolvers.intent_resolver import IntentResolver  # May be reused from chat architecture
from ..state_machine.work_order_state_machine import (
    WorkOrderStatus, WorkOrderStateMachine, InvalidStateTransitionError, StateGuardFailedError
)
from ..repository.mes_repository import MESRepository
from ..recovery.base import MesRecoveryStrategy, MesRecoveryResult
from ..formatter.response_formatter import ResponseFormatter


class MESAdapter:
    """MES thin adapter - coordinates all MES operations by delegating to
    specialized components. Contains zero business decision logic.
    
    Responsibilities:
    - Receive requests and validate input parameters
    - Delegate state transition validation to state machine
    - Coordinate recovery strategy execution
    - Format responses using DTOs
    - Handle high-level error translation to HTTP exceptions
    
    Does NOT:
    - Directly query database (delegates to repository)
    - Make business decisions about transitions (delegates to state machine)
    - Implement recovery logic (delegates to strategies)
    - Serialize domain models directly (delegates to formatter)
    """
    
    def __init__(self, db: AsyncSession, current_user_id: Optional[str] = None):
        self.db = db
        self.current_user_id = current_user_id
        
        # Injected dependencies (DI framework would provide these in production)
        self.factory_resolver = FactoryResolver()
        self.state_machine = WorkOrderStateMachine()
        self.repository = MESRepository(db)
        self.response_formatter = ResponseFormatter()
        
        # Collection of recovery strategies (ordered for priority application)
        self.recovery_strategies: List[MesRecoveryStrategy] = [
            MaterialShortagePause(),  # Check first - blocking issue
            CapacityLimitReject(),    # Second check - quantity constraint
            EquipmentFailureRecovery(),  # Third - equipment issues
            DefectThresholdAlert(),   # Fourth - quality concerns
        ]
    
    # ────────────────────────────────────────
    # Work Order Query Operations
    # ────────────────────────────────────────
    
    async def get_work_orders(self, criteria: WorkOrderQueryCriteria) -> dict:
        """Retrieve work orders with filtering, pagination, and formatting.
        
        Delegates all concerns to appropriate components:
        - Criteria validation through intent resolver (optional)
        - Factories permission via factory resolver
        - Data retrieval via repository
        - Formatting via response formatter
        """
        # Validate factory access
        if criteria.factory_id and not self._validate_factory_access(criteria.factory_id):
            raise HTTPException(
                status_code=403,
                detail=f"User {self.current_user_id} does not have access to factory {criteria.factory_id}"
            )
        
        # Fetch raw data from repository
        raw_orders = await self.repository.find_work_orders(
            factory_id=criteria.factory_id,
            status=criteria.status,
            product_id=criteria.product_id,
            page=criteria.page,
            size=criteria.size
        )
        
        # Format response using DTOs
        formatted_items = [
            self.response_formatter.format_work_order(wo) for wo in raw_orders
        ]
        
        # Get total count separately (more efficient than counting already fetched items)
        total_count = await self.repository.count_work_orders(
            factory_id=criteria.factory_id,
            status=criteria.status,
            product_id=criteria.product_id
        )
        
        return {
            "items": formatted_items,
            "total": total_count,
            "page": criteria.page,
            "size": criteria.size,
            "factory_id": criteria.factory_id
        }
    
    async def update_work_order_status(self, request: WorkOrderUpdateRequest) -> dict:
        """Update work order status through validated state transition.
        
        This is where the state machine comes into play - we never directly
        set a status; we go through the state machine which validates
        transitions according to rules defined in WorkOrderStateMachine.
        """
        # Get existing work order
        order = await self.repository.get_work_order_by_id(request.order_id)
        
        if not order:
            raise HTTPException(status_code=404, detail="Work order not found")
        
        from_status = WorkOrderStatus(order.status)
        try:
            to_status = WorkOrderStatus(request.new_status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status value: {request.new_status}. Valid values: {list(s.value for s in WorkOrderStatus)}"
            )
        
        # Validate transition through state machine (guards checked here)
        context = self._build_transition_context(order, request)
        
        try:
            self.state_machine.transition(from_status, to_status, context=context)
        except InvalidStateTransitionError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e)
            )
        except StateGuardFailedError as e:
            raise HTTPException(
                status_code=422,
                detail=f"Guard condition '{e.guard_name}' failed: {e.context}"
            )
        
        # Apply the transition via repository (within transaction)
        updated_order = await self.repository.update_work_order_status(
            order.id, 
            request.new_status,
            self.current_user_id
        )
        
        # After successful transition, publish any side effects (notifications, etc.)
        # These are handled by event listeners/subscribers, not here
        await self._publish_transition_event(order, from_status, to_status)
        
        return {
            "success": True,
            "order_id": updated_order.id,
            "previous_status": from_status.value,
            "new_status": to_status.value,
            "updated_at": updated_order.updated_at.isoformat() if updated_order.updated_at else None
        }
    
    # ────────────────────────────────────────
    # Production Report Operations
    # ────────────────────────────────────────
    
    async def create_production_report(self, report_data: ProductionReportRequest) -> ProductionReportResponse:
        """Create a production report with full validation pipeline.
        
        Steps:
        1. Validate factory access
        2. Run recovery strategies in order (first one that applies wins)
        3. If any recovery triggered, abort creation
        4. Otherwise, persist to repository
        5. Return formatted DTO
        """
        # Build context for recovery strategies
        context = self._build_report_context(report_data)
        
        # Apply recovery strategies sequentially
        for strategy in self.recovery_strategies:
            if strategy.should_apply(context):
                result = strategy.execute(context)
                if result.applied:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Recovery strategy {result.strategy_name} triggered: {result.message}"
                    )
        
        # All strategies passed - proceed to persistence
        report = await self.repository.create_production_report(report_data)
        
        # Return formatted response
        return self.response_formatter.format_production_report(report)
    
    # ────────────────────────────────────────
    # Helper Methods (Internal Only)
    # ────────────────────────────────────────
    
    def _validate_factory_access(self, factory_id: str) -> bool:
        """Validate that current user has access to this factory."""
        # In real implementation, check against user's permissions/roles
        # For now, assume all users can access factories F01 and FAC_ELEC_DEMO_2026
        allowed = ["F01", "FAC_ELEC_DEMO_2026", "FAC_MECH_001"]
        return factory_id in allowed or factory_id == "all"  # admin override
    
    def _build_transition_context(self, order, request) -> Dict[str, Any]:
        """Build context dictionary for state transition guards."""
        return {
            "work_order_id": order.id,
            "product_id": order.product_id,
            "station_id": order.station_id if hasattr(order, 'station_id') else None,
            "factory_id": order.factory_id,
            "user_id": self.current_user_id,
            "timestamp": datetime.now().isoformat()
        }
    
    def _build_report_context(self, report_data) -> Dict[str, Any]:
        """Build context for production report recovery strategies."""
        return {
            "material_id": report_data.material_id,
            "reported_qty": report_data.quantity,
            "station_id": report_data.station_id,
            "factory_id": report_data.factory_id,
            "operator_id": report_data.operator_id,
            "good_qty": report_data.good_qty,
            "defect_qty": report_data.defect_qty,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _publish_transition_event(self, order, from_status: WorkOrderStatus, to_status: WorkOrderStatus) -> None:
        """Publish transition event for side-effect consumers (notifications, logging, etc.).
        
        In production, this would emit an event to a message queue (RabbitMQ/Kafka)
        that other services subscribe to. For now, it's a no-op placeholder.
        """
        logger.info(f"Work order {order.id} state changed: {from_status.value} → {to_status.value}")
        # Actual event publishing would go here


# ────────────────────────────────────────────────────────────────────────────────
# Composition Root - Entry Point Used by Routes
# ────────────────────────────────────────────────────────────────────────────────

def get_mes_adapter(db: AsyncSession, current_user_id: Optional[str] = None) -> MESAdapter:
    """Factory function to create MESAdapter instance with injected dependencies.
    
    This function is used by FastAPI dependency injection to create a fresh
    adapter per request, ensuring each request gets its own stateless adapter.
    """
    return MESAdapter(db, current_user_id=current_user_id)