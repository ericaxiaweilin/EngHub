"""
报工小组路由 - 把若干工号打包为一个小组，便于小组长批量报工
CRUD: 列表 / 创建 / 更新 / 删除（软删）
"""
import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from database.models import User, WorkTeam
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/work-teams", tags=["work-teams"])


# ==================== Schemas ====================

class WorkTeamCreate(BaseModel):
    factory_id: str
    team_name: str
    team_code: Optional[str] = None  # 不传则自动生成
    leader_id: Optional[str] = None
    member_ids: List[str] = []
    description: Optional[str] = None


class WorkTeamUpdate(BaseModel):
    team_name: Optional[str] = None
    team_code: Optional[str] = None
    leader_id: Optional[str] = None
    member_ids: Optional[List[str]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


def _serialize(t: WorkTeam) -> dict:
    return {
        "id": t.id,
        "factory_id": t.factory_id,
        "team_code": t.team_code,
        "team_name": t.team_name,
        "leader_id": t.leader_id,
        "member_ids": t.member_ids or [],
        "description": t.description,
        "is_active": t.is_active,
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


# ==================== CRUD ====================

@router.get("")
async def list_work_teams(
    factory_id: str = Query(...),
    include_inactive: bool = Query(False),
    keyword: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """小组列表"""
    conds = [WorkTeam.factory_id == factory_id]
    if not include_inactive:
        conds.append(WorkTeam.is_active == True)  # noqa: E712
    if keyword:
        like = f"%{keyword}%"
        conds.append(WorkTeam.team_name.ilike(like) | WorkTeam.team_code.ilike(like))
    stmt = select(WorkTeam).where(and_(*conds)).order_by(WorkTeam.created_at.desc())
    result = await db.execute(stmt)
    teams = result.scalars().all()
    return {"items": [_serialize(t) for t in teams], "total": len(teams)}


@router.post("")
async def create_work_team(
    req: WorkTeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建小组"""
    team_code = req.team_code
    if not team_code:
        # 自动编码：TEAM-{序号}
        cnt = await db.scalar(
            select(func.count()).select_from(WorkTeam).where(WorkTeam.factory_id == req.factory_id)
        )
        team_code = f"TEAM-{(cnt or 0) + 1:03d}"

    # 同工厂内编码唯一
    dup = await db.scalar(
        select(func.count()).select_from(WorkTeam).where(
            and_(WorkTeam.factory_id == req.factory_id, WorkTeam.team_code == team_code)
        )
    )
    if dup:
        raise HTTPException(status_code=400, detail=f"小组编码 {team_code} 已存在")

    team = WorkTeam(
        id=str(uuid.uuid4()),
        factory_id=req.factory_id,
        team_code=team_code,
        team_name=req.team_name,
        leader_id=req.leader_id,
        member_ids=req.member_ids or [],
        description=req.description,
        is_active=True,
        created_by=current_user.username if current_user else None,
    )
    db.add(team)
    await db.commit()
    await db.refresh(team)
    return _serialize(team)


@router.put("/{team_id}")
async def update_work_team(
    team_id: str,
    req: WorkTeamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新小组"""
    team = await db.get(WorkTeam, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="小组不存在")

    data = req.dict(exclude_unset=True)
    if "team_code" in data and data["team_code"] and data["team_code"] != team.team_code:
        dup = await db.scalar(
            select(func.count()).select_from(WorkTeam).where(
                and_(
                    WorkTeam.factory_id == team.factory_id,
                    WorkTeam.team_code == data["team_code"],
                    WorkTeam.id != team_id,
                )
            )
        )
        if dup:
            raise HTTPException(status_code=400, detail=f"小组编码 {data['team_code']} 已存在")

    for k, v in data.items():
        setattr(team, k, v)
    team.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(team)
    return _serialize(team)


@router.delete("/{team_id}")
async def delete_work_team(
    team_id: str,
    hard: bool = Query(False, description="true=物理删除, 默认软删"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除小组（默认软删，可硬删）"""
    team = await db.get(WorkTeam, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="小组不存在")
    if hard:
        await db.delete(team)
    else:
        team.is_active = False
        team.updated_at = datetime.utcnow()
    await db.commit()
    return {"success": True, "id": team_id, "hard": hard}
