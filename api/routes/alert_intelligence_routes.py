"""
预警情报审查 API 路由（017）

端点：
- GET  /api/v1/alert-intelligence/reviews     — 审查记录列表
- GET  /api/v1/alert-intelligence/summary     — 待处理预警汇总
- POST /api/v1/alert-intelligence/reviews/{id}/acknowledge — 确认/驳回
- POST /api/v1/alert-intelligence/patrol      — 主动巡检
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user
from api.services.alert_intelligence_service import (
    list_reviews, get_pending_alerts_summary, acknowledge_review, patrol,
)

router = APIRouter(prefix="/api/v1/alert-intelligence", tags=["alert-intelligence"])


class AcknowledgeBody(BaseModel):
    action: str = "acknowledged"  # acknowledged / dismissed


@router.get("/reviews")
async def get_reviews(
    factory_id: str = Query(...),
    source: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询 AI 预警审查记录"""
    items = await list_reviews(db, factory_id, source=source, status=status, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/summary")
async def get_summary(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前待处理预警汇总"""
    return await get_pending_alerts_summary(db, factory_id)


@router.post("/reviews/{review_id}/acknowledge")
async def post_acknowledge(
    review_id: str,
    body: AcknowledgeBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认/驳回 AI 审查建议"""
    if body.action not in ("acknowledged", "dismissed"):
        raise HTTPException(status_code=400, detail="action 须为 acknowledged 或 dismissed")
    result = await acknowledge_review(db, review_id, body.action, current_user.username)
    if not result:
        raise HTTPException(status_code=404, detail="审查记录不存在")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/patrol")
async def post_patrol(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """主动巡检：扫描工单超时/安灯未响应 → 生成预警 → 触发 AI 审查"""
    result = await patrol(db, factory_id)
    return result
