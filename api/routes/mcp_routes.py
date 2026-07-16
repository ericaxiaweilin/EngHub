"""
MCP Streamable HTTP endpoint for Codex / Cursor remote MCP clients.

POST /mcp  - JSON-RPC request/response (application/json)
GET  /mcp  - server metadata / discovery helper
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from core.config import settings
from core.mcp import get_mcp_server
from core.mcp.transports import handle_streamable_http_json

router = APIRouter(tags=["MCP"])


@router.get("/mcp")
async def mcp_discover() -> Dict[str, Any]:
    server = get_mcp_server()
    return {
        "name": server.server_name,
        "version": server.server_version,
        "protocolVersion": server.protocol_version,
        "transport": "streamable-http-json",
        "endpoint": "/mcp",
        "stdio": "python scripts/enghub_mcp.py",
        "capabilities": ["tools", "resources", "prompts"],
        "instructions": (
            "POST JSON-RPC messages to /mcp. "
            "For Codex stdio mode, run scripts/enghub_mcp.py."
        ),
    }


@router.post("/mcp")
async def mcp_streamable_http(
    request: Request,
    response: Response,
    mcp_protocol_version: Optional[str] = Header(
        default=None, alias="mcp-protocol-version"
    ),
) -> Response:
    """
    Streamable HTTP JSON transport.

    Accepts one JSON-RPC message (or a batch array). Notifications return 202
    with an empty body; requests return application/json JSON-RPC responses.
    """
    server = get_mcp_server()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            },
        )

    result = await handle_streamable_http_json(server, body)

    # Echo negotiated protocol version when client provided one.
    headers = {}
    if mcp_protocol_version:
        headers["mcp-protocol-version"] = mcp_protocol_version
    else:
        headers["mcp-protocol-version"] = settings.MCP_PROTOCOL_VERSION

    if result is None:
        return Response(status_code=202, headers=headers)

    return JSONResponse(content=result, headers=headers)
