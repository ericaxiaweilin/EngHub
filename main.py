"""
EngHub MES Application Entry Point
"""
from fastapi import FastAPI
from api.routes import (
    ai_router,
    auth_router,
    employee_skill_router,
    mes_router,
    pp_router,
    qms_router,
    sim_erp_router,
    wms_router,
)
from api.v1 import api_router as v1_router

app = FastAPI(
    title="EngHub MES",
    description="Manufacturing Execution System API",
    version="1.0.0"
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
app.include_router(sim_erp_router)
app.include_router(v1_router)


@app.get("/")
def root():
    return {"message": "EngHub MES API", "status": "running"}


@app.get("/health")
def health():
    return {"status": "healthy"}
