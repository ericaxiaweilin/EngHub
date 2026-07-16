"""
EngHub MES Application Entry Point
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import (
    agent_router,
    auth_router,
    employee_skill_router,
    mcp_router,
    mes_router,
    pp_router,
    qms_router,
    sim_erp_router,
    wms_router,
)
from core.agent import get_tool_registry
from core.config import settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Wire live DB sessions into agent/MCP tools when available."""
    try:
        from database.db_config import db_config

        get_tool_registry().set_session_factory(db_config.session_factory)
    except Exception:
        # Demo payloads still work without a database.
        pass
    yield


app = FastAPI(
    title="EngHub MES",
    description="Manufacturing Execution System API with AI Agent + MCP",
    version="1.1.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(mes_router)
app.include_router(pp_router)
app.include_router(qms_router)
app.include_router(wms_router)
if employee_skill_router is not None:
    app.include_router(employee_skill_router)
app.include_router(sim_erp_router)
app.include_router(agent_router)
app.include_router(mcp_router)


@app.get("/")
def root():
    return {
        "message": "EngHub MES API",
        "status": "running",
        "agent": "/api/v1/agent/health",
        "mcp": "/mcp",
        "mcp_stdio": "python scripts/enghub_mcp.py",
        "llm_gateway": settings.LLM_GATEWAY_URL,
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
