"""
EngHub MES Application Entry Point
"""
from fastapi import FastAPI
from api.routes import (
    ai_router,
    auth_router,
    chat_router,
    employee_skill_router,
    intelligence_router,
    mes_router,
    pp_router,
    qms_router,
    sim_erp_router,
    wms_router,
    tms_router,
)
from api.v1 import api_router as v1_router

app = FastAPI(
    title="EngHub MES",
    description="Manufacturing Execution System API with TMS (Task Management System)",
    version="1.1.0"
)

# Include routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(mes_router)
app.include_router(pp_router)
app.include_router(qms_router)
app.include_router(wms_router)
if employee_skill_router is not None:
    app.include_router(employee_skill_router)
app.include_router(ai_router)
app.include_router(intelligence_router)
app.include_router(sim_erp_router)
app.include_router(chat_router)  # AI 助手
app.include_router(tms_router)  # TMS 任务管理系统
app.include_router(v1_router)  # 专家系统 / 搜索引擎 v2 等 v1 端点


@app.get("/")
def root():
    return {
        "message": "EngHub Manufacturing Intelligence API",
        "status": "running",
        "system_type": "simulation_ai_scenario_decision",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}
