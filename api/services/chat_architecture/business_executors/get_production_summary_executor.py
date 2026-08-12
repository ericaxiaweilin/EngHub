"""Get Production Summary Business Executor.

Handles the business logic for querying production summary data.
"""

from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.chat_architecture.business_executors.base import BaseBusinessExecutor
from api.services.chat_tools_service import _tool_get_production_summary


class GetProductionSummaryExecutor(BaseBusinessExecutor):
    """Execute production summary query operations."""
    
    def get_intent_name(self) -> str:
        return "get_production_summary"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute production summary query.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: Additional context
            
        Returns:
            Production summary result
        """
        result = await _tool_get_production_summary(db, {}, factory_id=factory_id)
        return result
    
    def can_handle(self, intent: str) -> bool:
        return self.get_intent_name() == intent