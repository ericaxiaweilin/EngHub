"""
API v1 版本模块
"""
from fastapi import APIRouter

from .endpoints.expert import router as expert_router
from .endpoints.search.v2.search import router as search_router_v2

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(expert_router)
api_router.include_router(search_router_v2)

__all__ = ["api_router"]
