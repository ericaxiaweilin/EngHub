"""
API v1 版本模块
"""
from fastapi import APIRouter

# 导入所有端点路由
from .endpoints.expert import router as expert_router
from .endpoints.search.search import router as search_router_v1
from .endpoints.search.v2.search import router as search_router_v2

# 创建 v1 主路由
api_router = APIRouter(prefix="/api/v1")

# 注册所有端点
api_router.include_router(expert_router)
api_router.include_router(search_router_v1, prefix="/search")  # v1 search at /api/v1/search
api_router.include_router(search_router_v2)  # v2 search at /api/v1/search/v2

__all__ = ["api_router"]
