"""
EngHub AI agent package.

Provides a manufacturing data agent with OpenAI-compatible tool calling.
The same tool layer is exposed over MCP for Codex and other MCP clients.
"""

from core.agent.agent import ManufacturingAgent
from core.agent.tools import ToolRegistry, get_tool_registry

__all__ = [
    "ManufacturingAgent",
    "ToolRegistry",
    "get_tool_registry",
]
