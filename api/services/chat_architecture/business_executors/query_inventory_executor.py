"""Query Inventory Business Executor.

Handles the business logic for querying inventory data.
"""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.chat_architecture.business_executors.base import BaseBusinessExecutor
from api.services.chat_tools_service import _tool_query_inventory


class QueryInventoryExecutor(BaseBusinessExecutor):
    """Execute inventory query operations."""
    
    def get_intent_name(self) -> str:
        return "query_inventory"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute inventory query.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: Additional context (may contain material_keyword, limit)
            
        Returns:
            Inventory query result
        """
        params = {
            "material_keyword": context.get("material_keyword"),
            "limit": context.get("limit", 10),
        }
        
        result = await _tool_query_inventory(db, params, factory_id=factory_id)
        return result
    
    def can_handle(self, intent: str) -> bool:
        return self.get_intent_name() == intent