"""
EngHub MCP (Model Context Protocol) server package.

Exposes manufacturing read tools/resources so Codex, Cursor, and other
MCP clients can query MES data through a standard protocol.
"""

from core.mcp.server import EngHubMCPServer, get_mcp_server

__all__ = ["EngHubMCPServer", "get_mcp_server"]
