"""
EngHub MES Application Entry Point
"""
from fastapi import FastAPI
from api.routes import (
    auth_router,
    chat_router,
    employee_skill_router,
    mes_router,
    pp_router,
    qms_router,
    sim_erp_router,
    sim_factory_router,
    wms_router,
    tms_router,
)
from api.routes.test_switch import test_router

app = FastAPI(
    title="EngHub MES",
    description="Manufacturing Execution System API with TMS (Task Management System)",
    version="1.2.0"
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
app.include_router(sim_factory_router)
app.include_router(chat_router)
app.include_router(tms_router)
app.include_router(test_router)  # 测试模式角色切换（仅 TEST_MODE=true 时可用）


@app.get("/")
def root():
    return {"message": "EngHub MES API", "status": "running"}


@app.get("/health")
def health():
    return {"status": "healthy"}
