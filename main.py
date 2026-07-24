

"""
EngHub MES Application Entry Point
"""
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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
from api.routes.andon_routes import router as andon_router
from api.routes.test_switch import test_router
from api.routes.data_consistency_routes import router as data_consistency_router
from api.routes.expert_system_routes import router as expert_system_router
from api.routes.work_order_template_routes import router as work_order_template_router
from api.routes.production_dashboard_routes import router as production_dashboard_router
from api.routes.search_routes import router as search_router
from api.routes.code_table_routes import router as code_table_router
from api.routes.file_routes import router as file_router
from api.routes.routing_template_routes import router as routing_template_router
from api.routes.alert_intelligence_routes import router as alert_intelligence_router

app = FastAPI(
    title="EngHub MES",
    description="Manufacturing Execution System API with TMS (Task Management System)",
    version="2.5.0"
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
app.include_router(andon_router)  # Andon 2.0 智能工单系统
app.include_router(data_consistency_router)
app.include_router(expert_system_router)
app.include_router(work_order_template_router)
app.include_router(production_dashboard_router)  # 生产看板聚合（真实数据，复用仿真结果UI组件）
app.include_router(search_router)  # 全站系统搜索
app.include_router(code_table_router)  # 统一码表/基础数据管理
app.include_router(file_router)  # 文件/附件上传下载（chatbot 多模态 + 表单/报告导出）
app.include_router(routing_template_router)  # 工艺路线模板 CRUD（016 工序流转）
app.include_router(alert_intelligence_router)  # 预警情报审查（017 Chatbot 主动智能）
app.include_router(test_router)  # 测试模式角色切换（仅 TEST_MODE=true 时可用）


@app.get("/health")
def health():
    return {"status": "healthy", "version": "2.5.0"}


# ---------- 前端静态托管（FastAPI 同源服务，替代 nginx） ----------
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", str(Path(__file__).parent / "frontend_dist")))

if FRONTEND_DIST.is_dir():
    # 带 hash 的静态资源 (js/css/woff/png...)
    _assets_dir = FRONTEND_DIST / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="static-assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str):
        """SPA fallback：非 API 路由全部返回前端页面"""
        file_path = FRONTEND_DIST / full_path
        if full_path and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIST / "index.html"))

