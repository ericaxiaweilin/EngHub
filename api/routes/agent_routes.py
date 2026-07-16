"""
AI Agent HTTP API.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core.agent import ManufacturingAgent, get_tool_registry
from core.agent.models import AgentChatRequest, AgentChatResponse
from core.config import settings

router = APIRouter(prefix="/api/v1/agent", tags=["AI Agent"])


class ToolInvokeRequest(BaseModel):
    name: str = Field(..., description="Tool name")
    arguments: Dict[str, Any] = Field(default_factory=dict)


def get_agent() -> ManufacturingAgent:
    return ManufacturingAgent()


@router.get("/health")
async def agent_health(agent: ManufacturingAgent = Depends(get_agent)) -> Dict[str, Any]:
    llm_ok = await agent.llm.health_check()
    backend = await agent.llm.backend_status()
    tools = get_tool_registry()
    return {
        "status": "healthy",
        "llm_reachable": llm_ok,
        "model_base": backend,
        "llm_gateway": settings.LLM_GATEWAY_URL,
        "llm_model": settings.LLM_MODEL_NAME,
        "tool_count": len(tools.list_definitions()),
        "mcp": {
            "server": settings.MCP_SERVER_NAME,
            "http_path": "/mcp",
            "stdio_script": "scripts/enghub_mcp.py",
        },
    }


@router.get("/tools")
async def list_agent_tools() -> Dict[str, Any]:
    tools = get_tool_registry()
    return {
        "count": len(tools.list_definitions()),
        "tools": [item.model_dump() for item in tools.list_definitions()],
    }


@router.post("/tools/invoke")
async def invoke_agent_tool(request: ToolInvokeRequest) -> Dict[str, Any]:
    tools = get_tool_registry()
    result = await tools.call(request.name, request.arguments)
    return {"name": request.name, "arguments": request.arguments, "result": result}


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat(
    request: AgentChatRequest,
    agent: ManufacturingAgent = Depends(get_agent),
) -> AgentChatResponse:
    return await agent.chat(
        message=request.message,
        history=request.history,
        factory_id=request.factory_id,
        use_tools=request.use_tools,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )


@router.post("/chat/simple")
async def agent_chat_simple(
    message: str,
    factory_id: Optional[str] = None,
    agent: ManufacturingAgent = Depends(get_agent),
) -> AgentChatResponse:
    """Convenience endpoint for quick manual testing."""
    return await agent.chat(message=message, factory_id=factory_id)
