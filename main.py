"""
EngHub MES Application Entry Point
"""
from fastapi import FastAPI
from api.routes import mes_router, pp_router, qms_router, wms_router

app = FastAPI(
    title="EngHub MES",
    description="Manufacturing Execution System API",
    version="1.0.0"
)

# Include routers
app.include_router(mes_router)
app.include_router(pp_router)
app.include_router(qms_router)
app.include_router(wms_router)


@app.get("/")
def root():
    return {"message": "EngHub MES API", "status": "running"}


@app.get("/health")
def health():
    return {"status": "healthy"}
