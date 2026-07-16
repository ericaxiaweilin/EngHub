"""
MCP transport helpers: Streamable HTTP (JSON) and stdio (Content-Length framing).
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional, TextIO, Tuple

from core.mcp.server import EngHubMCPServer


async def handle_streamable_http_json(
    server: EngHubMCPServer,
    body: Any,
) -> Optional[Any]:
    """
    Process a Streamable HTTP JSON body.

    Codex / Cursor clients typically POST a single JSON-RPC message and
    accept application/json responses. Notifications return no body.
    """
    return await server.handle_message(body)


def _read_stdio_message(stdin_buffer) -> Optional[Dict[str, Any]]:
    """
    Read one MCP stdio message using Content-Length framing.

    Frame format (same as official MCP SDKs):
      Content-Length: <byte-length>\\r\\n
      \\r\\n
      <json-bytes>
    """
    headers: Dict[str, str] = {}
    while True:
        line = stdin_buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        headers[key.decode("utf-8").strip().lower()] = value.decode("utf-8").strip()

    if "content-length" not in headers:
        return None
    length = int(headers["content-length"])
    body = stdin_buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_stdio_message(stdout_buffer, message: Any) -> None:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
    stdout_buffer.write(header)
    stdout_buffer.write(payload)
    stdout_buffer.flush()


async def run_stdio_server(
    server: EngHubMCPServer,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
) -> None:
    """
    Run MCP over stdio with Content-Length framing for Codex compatibility.

    Example Codex config:
      [mcp_servers.enghub]
      command = "python"
      args = ["/path/to/EngHub/scripts/enghub_mcp.py"]
    """
    import asyncio

    in_stream = stdin or sys.stdin
    out_stream = stdout or sys.stdout
    in_buf = in_stream.buffer
    out_buf = out_stream.buffer
    loop = asyncio.get_event_loop()

    while True:
        message = await loop.run_in_executor(None, _read_stdio_message, in_buf)
        if message is None:
            break
        response = await server.handle_message(message)
        if response is None:
            continue
        await loop.run_in_executor(None, _write_stdio_message, out_buf, response)


def encode_stdio_message_for_tests(message: Dict[str, Any]) -> bytes:
    """Helper used by unit tests to build framed stdio payloads."""
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    return f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload


def decode_stdio_messages_for_tests(raw: bytes) -> Tuple[Dict[str, Any], ...]:
    """Parse one or more framed stdio messages from a bytes buffer."""
    messages = []
    offset = 0
    while offset < len(raw):
        header_end = raw.find(b"\r\n\r\n", offset)
        if header_end < 0:
            break
        header_blob = raw[offset:header_end].decode("utf-8")
        length = None
        for line in header_blob.split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        if length is None:
            break
        start = header_end + 4
        end = start + length
        messages.append(json.loads(raw[start:end].decode("utf-8")))
        offset = end
    return tuple(messages)
