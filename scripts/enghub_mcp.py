#!/usr/bin/env python3
"""
EngHub MCP stdio server entrypoint for Codex / Cursor.

Usage:
  python scripts/enghub_mcp.py

Codex (~/.codex/config.toml) example:

  [mcp_servers.enghub]
  command = "python"
  args = ["/absolute/path/to/EngHub/scripts/enghub_mcp.py"]
  # optional:
  # env = { "DEFAULT_FACTORY_ID" = "factory-001", "DATABASE_URL" = "..." }
"""

from __future__ import annotations

import asyncio
import os
import sys

# Ensure repository root is importable when launched as a script.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


async def _main() -> None:
    from core.mcp import get_mcp_server
    from core.mcp.transports import run_stdio_server

    # Best-effort: attach DB session factory when database package is available.
    registry_tools = get_mcp_server().tools
    try:
        from database.db_config import db_config

        registry_tools.set_session_factory(db_config.session_factory)
    except Exception:
        pass

    await run_stdio_server(get_mcp_server())


if __name__ == "__main__":
    asyncio.run(_main())
