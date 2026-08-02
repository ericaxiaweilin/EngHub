"""
通知系统路由 - 站内通知（报告就绪/异常预警/系统消息）
生产统计员打穿：自动生成报告后推送通知
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update

from database.db_config import get_db
from database.models import Notification
from core.auth.security import get_current_user
from core.auth.user_service import User

router = APIRouter(prefix="/api/v1/notifications", tags=["通知系统"])


@router.get("", summary="通知列表")
async def list_notifications(
    factory_id: str = Query(...),
    category: Optional[str] = Query(None, description="分类: report/anomaly/system/andon"),
    unread_only: bool = Query(False, description="仅未读"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取通知列表（支持分类过滤、仅未读）"""
    conditions = [
        Notification.factory_id == factory_id,
        # 广播(recipient=None) 或 指定给当前用户
        (Notification.recipient == None) | (Notification.recipient == current_user.username),
    ]
    if category:
        conditions.append(Notification.category == category)
    if unread_only:
        conditions.append(Notification.is_read == False)

    # 总数
    count_stmt = select(func.count(Notification.id)).where(and_(*conditions))
    total = (await db.execute(count_stmt)).scalar() or 0

    # 列表
    stmt = (
        select(Notification)
        .where(and_(*conditions))
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    return {
        "total": total,
        "unread_count": total,  # 简化：如果 unread_only 则 total 即未读数
        "items": [{
            "id": n.id,
            "category": n.category,
            "title": n.title,
            "content": n.content,
            "severity": n.severity,
            "source_type": n.source_type,
            "source_id": n.source_id,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        } for n in items],
    }


@router.get("/unread-count", summary="未读通知数")
async def unread_count(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取未读通知数量（前端 Badge 用）"""
    stmt = select(func.count(Notification.id)).where(and_(
        Notification.factory_id == factory_id,
        (Notification.recipient == None) | (Notification.recipient == current_user.username),
        Notification.is_read == False,
    ))
    count = (await db.execute(stmt)).scalar() or 0
    return {"unread_count": count}


@router.put("/{notification_id}/read", summary="标记已读")
async def mark_read(
    notification_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """标记单条通知为已读"""
    notif = await db.get(Notification, notification_id)
    if not notif:
        raise HTTPException(status_code=404, detail="通知不存在")
    notif.is_read = True
    notif.read_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}


@router.put("/read-all", summary="全部标记已读")
async def mark_all_read(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量标记所有未读通知为已读"""
    stmt = (
        update(Notification)
        .where(and_(
            Notification.factory_id == factory_id,
            (Notification.recipient == None) | (Notification.recipient == current_user.username),
            Notification.is_read == False,
        ))
        .values(is_read=True, read_at=datetime.utcnow())
    )
    result = await db.execute(stmt)
    await db.commit()
    return {"ok": True, "updated": result.rowcount}
