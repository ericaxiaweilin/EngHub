"""
API v1 版本模块
"""
from fastapi import APIRouter

# 导入所有端点路由
from .endpoints.expert import router as expert_router

# 创建 v1 主路由
api_router = APIRouter(prefix="/api/v1")

# 注册所有端点
api_router.include_router(expert_router)

__all__ = ["api_router"]
