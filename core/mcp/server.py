"""
EngHub MCP server backed by the shared manufacturing tool registry.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from core.agent.tools import ToolRegistry, get_tool_registry
from core.config import settings
from core.mcp.protocol import (
    MCPError,
    jsonrpc_error,
    jsonrpc_result,
    parse_jsonrpc_message,
    resource_text_contents,
    text_content,
)

logger = logging.getLogger(__name__)


class EngHubMCPServer:
    """JSON-RPC MCP server for MES data access."""

    def __init__(self, tools: Optional[ToolRegistry] = None) -> None:
        self.tools = tools or get_tool_registry()
        self.server_name = settings.MCP_SERVER_NAME
        self.server_version = settings.MCP_SERVER_VERSION
        self.protocol_version = settings.MCP_PROTOCOL_VERSION

    def _resources(self) -> List[Dict[str, Any]]:
        return [
            {
                "uri": "enghub://status",
                "name": "EngHub Agent Status",
                "description": "Agent/MCP capability status and configured defaults.",
                "mimeType": "application/json",
            },
            {
                "uri": "enghub://work-orders",
                "name": "Work Orders",
                "description": "Current work-order catalog for the default factory.",
                "mimeType": "application/json",
            },
            {
                "uri": "enghub://stations",
                "name": "Stations",
                "description": "Production stations for the default factory.",
                "mimeType": "application/json",
            },
            {
                "uri": "enghub://inventory",
                "name": "Inventory",
                "description": "Inventory snapshot for the default factory.",
                "mimeType": "application/json",
            },
            {
                "uri": "enghub://production-summary",
                "name": "Production Summary",
                "description": "Aggregate production progress summary.",
                "mimeType": "application/json",
            },
        ]

    def _prompts(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "production_briefing",
                "description": "Ask for a concise factory production briefing.",
                "arguments": [
                    {
                        "name": "factory_id",
                        "description": "Optional factory id",
                        "required": False,
                    }
                ],
            },
            {
                "name": "shortage_check",
                "description": "Ask the agent to highlight material shortage risks.",
                "arguments": [
                    {
                        "name": "material_id",
                        "description": "Optional material filter",
                        "required": False,
                    }
                ],
            },
            {
                "name": "work_order_deep_dive",
                "description": "Inspect one work order in detail.",
                "arguments": [
                    {
                        "name": "work_order_code",
                        "description": "Work order code",
                        "required": True,
                    }
                ],
            },
        ]

    async def handle_message(self, raw: Any) -> Optional[Dict[str, Any]]:
        """
        Handle one JSON-RPC request/notification.
        Returns None for notifications (no response body required).
        """
        try:
            message = parse_jsonrpc_message(raw)
        except Exception as exc:  # noqa: BLE001
            return jsonrpc_error(None, -32700, f"Parse error: {exc}")

        if isinstance(message, list):
            # Batch: process sequentially
            responses = []
            for item in message:
                response = await self.handle_message(item)
                if response is not None:
                    responses.append(response)
            return responses  # type: ignore[return-value]

        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}

        # Notifications have no id
        is_notification = "id" not in message

        try:
            result = await self._dispatch(method, params)
            if is_notification:
                return None
            return jsonrpc_result(request_id, result)
        except MCPError as exc:
            if is_notification:
                logger.warning("MCP notification error: %s", exc.message)
                return None
            return jsonrpc_error(request_id, exc.code, exc.message, exc.data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("MCP handler failure for method=%s", method)
            if is_notification:
                return None
            return jsonrpc_error(request_id, -32603, f"Internal error: {exc}")

    async def _dispatch(self, method: Optional[str], params: Dict[str, Any]) -> Any:
        if method == "initialize":
            return {
                "protocolVersion": self.protocol_version,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": {
                    "name": self.server_name,
                    "version": self.server_version,
                },
                "instructions": (
                    "EngHub MES MCP server. Use tools to read work orders, "
                    "stations, equipment, inventory, and production summaries. "
                    "Compatible with Codex and other MCP clients."
                ),
            }
        if method == "notifications/initialized":
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self.tools.mcp_tools()}
        if method == "tools/call":
            name = params.get("name")
            if not name:
                raise MCPError(-32602, "Missing tool name")
            arguments = params.get("arguments") or {}
            result = await self.tools.call(name, arguments)
            is_error = isinstance(result, dict) and "error" in result
            return {
                "content": text_content(json.dumps(result, ensure_ascii=False, indent=2)),
                "structuredContent": result,
                "isError": is_error,
            }
        if method == "resources/list":
            return {"resources": self._resources()}
        if method == "resources/read":
            uri = params.get("uri")
            if not uri:
                raise MCPError(-32602, "Missing resource uri")
            payload = await self._read_resource(uri)
            return {
                "contents": resource_text_contents(
                    uri,
                    json.dumps(payload, ensure_ascii=False, indent=2),
                )
            }
        if method == "prompts/list":
            return {"prompts": self._prompts()}
        if method == "prompts/get":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            return self._get_prompt(name, arguments)
        if method in {"logging/setLevel"}:
            return {}
        raise MCPError(-32601, f"Method not found: {method}")

    async def _read_resource(self, uri: str) -> Dict[str, Any]:
        mapping = {
            "enghub://status": ("get_system_status", {}),
            "enghub://work-orders": ("list_work_orders", {}),
            "enghub://stations": ("list_stations", {}),
            "enghub://inventory": ("get_inventory", {}),
            "enghub://production-summary": ("get_production_summary", {}),
        }
        if uri not in mapping:
            raise MCPError(-32602, f"Unknown resource uri: {uri}")
        tool_name, args = mapping[uri]
        return await self.tools.call(tool_name, args)

    def _get_prompt(self, name: Optional[str], arguments: Dict[str, Any]) -> Dict[str, Any]:
        if name == "production_briefing":
            factory_id = arguments.get("factory_id") or settings.DEFAULT_FACTORY_ID
            text = (
                f"Give me a concise production briefing for factory {factory_id}. "
                "Include open work orders, completion rate, and any inventory risks."
            )
        elif name == "shortage_check":
            material_id = arguments.get("material_id")
            if material_id:
                text = f"Check shortage risk for material {material_id} and recommend actions."
            else:
                text = "Review inventory and highlight materials with shortage risk."
        elif name == "work_order_deep_dive":
            code = arguments.get("work_order_code")
            if not code:
                raise MCPError(-32602, "work_order_code is required")
            text = (
                f"Deep dive work order {code}: status, progress, station assignment, "
                "and what to do next."
            )
        else:
            raise MCPError(-32602, f"Unknown prompt: {name}")

        return {
            "description": f"EngHub prompt: {name}",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": text},
                }
            ],
        }


_SERVER: Optional[EngHubMCPServer] = None


def get_mcp_server() -> EngHubMCPServer:
    global _SERVER
    if _SERVER is None:
        _SERVER = EngHubMCPServer()
    return _SERVER
