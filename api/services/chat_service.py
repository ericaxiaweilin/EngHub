"""Chat Service Layer - Orchestrates ChatAdapter components.

This service class integrates the newly refactored ChatAdapter architecture,
providing a clean separation between routing (HTTP handling) and business logic.
All chat-related processing is delegated to ChatAdapter while this service
manages dependencies and provides a simple interface for routes.
"""

from typing import Optional, Dict, Any
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User
from api.routes.chat_routes import ChatRequest, ChatResponse
from api.services.chat_architecture.adapters.chat_adapter import ChatAdapter  # Simplified import


class ChatService:
    """Chat business logic service using the new architectural pattern."""
    
    def __init__(self, db: AsyncSession, current_user: Optional[User] = None):
        self.db = db
        self.current_user = current_user
        
        # Create ChatAdapter with all its internal dependencies
        self.adapter = ChatAdapter(db=db)
    
    async def handle_chat_request(self, request: ChatRequest) -> ChatResponse:
        """Handle a complete chat request through the adapter pipeline."""
        try:
            result = await self.adapter.handle_request(request, self.current_user)
            # Convert dict result to ChatResponse model
            return ChatResponse(**result)
        except HTTPException as he:
            raise he
        except Exception as exc:
            error_msg = f"Chat processing failed: {str(exc)}"
            return ChatResponse(reply=error_msg, model="unknown", degraded=True)
    
    async def execute_tool_call(self, tool_name: str, params: Dict[str, Any], factory_id: str = "F01") -> Dict[str, Any]:
        """Execute a specific tool call through the integrated toolchain."""
        from api.services.chat_tools_service import _tool_query_inventory, _tool_get_production_summary, _tool_query_work_orders
        
        if tool_name == "query_inventory":
            return await _tool_query_inventory(self.db, params, factory_id=factory_id)
        elif tool_name == "get_production_summary":
            return await _tool_get_production_summary(self.db, params, factory_id=factory_id)
        elif tool_name == "query_work_orders":
            return await _tool_query_work_orders(self.db, params, factory_id=factory_id)
        else:
            return {"error": f"Unknown tool: {tool_name}"}