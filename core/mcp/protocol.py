"""
Minimal MCP JSON-RPC protocol helpers compatible with Codex / Cursor clients.

Implements the commonly used subset:
- initialize / notifications/initialized / ping
- tools/list / tools/call
- resources/list / resources/read
- prompts/list / prompts/get
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

JsonRpcId = Union[str, int, None]


def jsonrpc_result(request_id: JsonRpcId, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def jsonrpc_error(
    request_id: JsonRpcId,
    code: int,
    message: str,
    data: Any = None,
) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def parse_jsonrpc_message(raw: Union[str, bytes, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def text_content(text: str) -> List[Dict[str, Any]]:
    return [{"type": "text", "text": text}]


def resource_text_contents(uri: str, text: str, mime_type: str = "application/json") -> List[Dict[str, Any]]:
    return [
        {
            "uri": uri,
            "mimeType": mime_type,
            "text": text,
        }
    ]


class MCPError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
