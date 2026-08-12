"""Query Work Orders Business Executor.

Handles the business logic for querying work order data.
"""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.chat_architecture.business_executors.base import BaseBusinessExecutor
from api.services.chat_tools_service import _tool_query_work_orders


class QueryWorkOrdersExecutor(BaseBusinessExecutor):
    """Execute work order query operations."""
    
    def get_intent_name(self) -> str:
        return "query_work_orders"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute work order query.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: Additional context (may contain status)
            
        Returns:
            Work order query result
        """
        params = {
            "status": context.get("status", "in_progress"),
            "limit": context.get("limit", 10),
        }
        
        result = await _tool_query_work_orders(db, params, factory_id=factory_id)
        return result
    
    def can_handle(self, intent: str) -> bool:
        return self.get_intent_name() == intent