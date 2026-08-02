"""
IQ C 专属 API 端点 - 用于来料检验业务
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, List, Dict
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User
from api.services.qms_service import QMSService

# router = APIRouter(prefix="/api/v1", tags=["iqc"])  # 注意：不应重复创建router，应在qms_routes中使用已存在的router


class IQCCreateRequest(BaseModel):
    """IQ C 创建请求体"""
    inbound_order_id: str
    factory_id: str
    supplier_id: str
    product_id: str
    product_name: str
    quantity_received: int
    batch_no: str
    inspector_id: str
    sample_size: Optional[int] = None


class IQCStartRequest(BaseModel):
    """开始检验请求"""
    inspector_id: str


class IQCCompleteRequest(BaseModel):
    """完成检验请求"""
    result: str  # "PASS" or "FAIL"
    sample_inspected: int
    defects: Optional[List[Dict]] = None


class IQCDIsposalRequest(BaseModel):
    """处置请求"""
    disposition: str  # "accept", "reject", "use_as_is" etc.
    by: str


# 这些函数将被导入到 qms_routes.py 中作为现有 router 的附加端点
# 实际使用时应该直接粘贴到 qms_routes.py 文件内，而不是作为独立模块
