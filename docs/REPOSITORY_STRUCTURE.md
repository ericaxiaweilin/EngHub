# Repository Structure

## Active application layout

The current runnable backend uses the repository root layout:

- `main.py`
- `api/`
- `core/`
- `database/`
- `tests/`

New backend features should be added to this structure.

## Sim-ERP layout

The Sim-ERP compliance engine lives under:

- `core/sim_erp/`
- `api/routes/sim_erp_routes.py`
- `tests/unit/test_sim_erp.py`

This is the active path for simulation, arbitration, plugin execution, and audit logging.

## AI Agent + MCP layout

The manufacturing AI agent and MCP server live under:

- `core/agent/` — tool registry, LLM client, agent loop
- `core/mcp/` — MCP JSON-RPC server + stdio/HTTP transports
- `core/model_base/` — adapters for model-engineering-base + model-stack
- `integrations/luaguage.py` — ERP master-data client used by agent tools
- `api/routes/agent_routes.py` — `/api/v1/agent/*`
- `api/routes/ai_routes.py` — `/api/v1/ai/*` model-base proxy
- `api/routes/mcp_routes.py` — `/mcp` Streamable HTTP
- `scripts/enghub_mcp.py` — Codex-compatible stdio entrypoint
- `docs/AI_AGENT_MCP.md` / `docs/MODEL_BASES.md`
- `tests/unit/test_agent_mcp.py` / `tests/unit/test_model_bases.py`

New agent tools should be registered in `core/agent/tools.py` so both the HTTP agent and MCP clients share them.

## Legacy layout

The `app/` directory is legacy code and is not part of the active backend boot path.

Known issues in the legacy layout:

- The original `app/` HRM prototype files were removed because they depended on missing modules and were not wired into `main.py`.

Do not place new production code under `app/` unless the repository is intentionally migrated back to that layout.

## Cleanup guidance

Safe next cleanup steps:

1. Remove or archive the legacy `app/` directory after confirming nothing external imports it.
2. Keep all new simulation and compliance work inside `core/sim_erp/`.
