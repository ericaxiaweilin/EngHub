"""
Shared schemas for the AI agent and MCP layer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User question or instruction")
    history: List[ChatMessage] = Field(default_factory=list)
    factory_id: Optional[str] = None
    use_tools: bool = True
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class ToolCallRecord(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Any = None


class AgentChatResponse(BaseModel):
    reply: str
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    model: Optional[str] = None
    fallback: bool = False
    rounds: int = 0


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any] = Field(default_factory=dict)

    def to_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema
                or {"type": "object", "properties": {}},
            },
        }

    def to_mcp_tool(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema
            or {"type": "object", "properties": {}},
        }
