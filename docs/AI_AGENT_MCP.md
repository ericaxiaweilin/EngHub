# EngHub AI Agent + MCP

EngHub exposes a manufacturing AI agent and a Model Context Protocol (MCP) server so tools like **Codex**, Cursor, and Claude Desktop can read MES data through a standard protocol.

## What you get

| Surface | Path / entry | Purpose |
|---------|--------------|---------|
| Agent HTTP API | `/api/v1/agent/*` | Chat + tool invoke for apps/UI |
| MCP Streamable HTTP | `POST /mcp` | Remote MCP clients (Codex URL mode) |
| MCP stdio | `python scripts/enghub_mcp.py` | Local Codex / Cursor MCP config |
| Shared tools | `core/agent/tools.py` | Same MES read tools for both surfaces |

### Built-in tools

- `list_work_orders` / `get_work_order`
- `list_stations` / `get_station`
- `list_equipment`
- `get_inventory`
- `get_production_summary`
- `get_oee_snapshot`
- `search_mes_entities`
- `get_system_status`

Tools prefer live DB reads when `DATABASE_URL` is reachable, otherwise they return deterministic demo data so Codex can still explore the schema offline.

## Quick start

```bash
# install deps
pip install -r requirements.txt

# run API (agent + MCP HTTP)
uvicorn main:app --host 0.0.0.0 --port 8000

# health
curl http://localhost:8000/api/v1/agent/health
curl http://localhost:8000/mcp
```

### Agent chat

```bash
curl -X POST http://localhost:8000/api/v1/agent/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"当前有哪些进行中的工单？","use_tools":true}'
```

If the LLM gateway is down, the agent still returns direct tool output (offline fallback).

### MCP over HTTP

```bash
curl -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":1,
    "method":"initialize",
    "params":{
      "protocolVersion":"2024-11-05",
      "capabilities":{},
      "clientInfo":{"name":"codex","version":"1"}
    }
  }'
```

```bash
curl -X POST http://localhost:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{"name":"list_work_orders","arguments":{"limit":5}}
  }'
```

## Codex configuration

### Option A — stdio (recommended for local Codex)

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.enghub]
command = "python"
args = ["/absolute/path/to/EngHub/scripts/enghub_mcp.py"]

# optional live DB / factory defaults
[mcp_servers.enghub.env]
DEFAULT_FACTORY_ID = "factory-001"
# DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/enghub"
# LLM_GATEWAY_URL = "http://127.0.0.1:14041"
```

Restart Codex. You should see tools like `list_work_orders` and resources like `enghub://inventory`.

### Option B — remote Streamable HTTP

If your Codex/Cursor build supports URL MCP servers:

```toml
[mcp_servers.enghub]
url = "http://127.0.0.1:8000/mcp"
```

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `LLM_GATEWAY_URL` / `MODEL_GATEWAY_URL` | `http://100.96.188.77:14041` | OpenAI-compatible chat gateway |
| `LLM_API_KEY` | empty | Optional bearer token |
| `LLM_MODEL_NAME` | `qwen-max` | Model id |
| `DEFAULT_FACTORY_ID` | `factory-001` | Default factory scope for tools |
| `MCP_SERVER_NAME` | `enghub-mes` | MCP serverInfo.name |
| `DATABASE_URL` | local postgres URL | Enables live MES reads |

## Architecture

```
Codex / Cursor                Web / App
     │                            │
     │ stdio or /mcp              │ /api/v1/agent/chat
     ▼                            ▼
 EngHubMCPServer  <──shared──>  ManufacturingAgent
     │                            │
     └──────── ToolRegistry ──────┘
                  │
         demo data or PostgreSQL
```

## Resources & prompts (MCP)

Resources:

- `enghub://status`
- `enghub://work-orders`
- `enghub://stations`
- `enghub://inventory`
- `enghub://production-summary`

Prompts:

- `production_briefing`
- `shortage_check`
- `work_order_deep_dive`

## Tests

```bash
PYTHONPATH=. pytest tests/unit/test_agent_mcp.py -q
```
