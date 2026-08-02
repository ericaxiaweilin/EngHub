"""
工艺路线模板 CRUD 路由（016）

端点：
- GET    /api/v1/routing-templates         列表（factory 隔离）
- POST   /api/v1/routing-templates         创建模板+步骤
- GET    /api/v1/routing-templates/{id}    详情含步骤
- PUT    /api/v1/routing-templates/{id}    更新
- DELETE /api/v1/routing-templates/{id}    软删除(is_active=false)
"""

import uuid
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.db_config import db_config
from database.models import RoutingTemplate, RoutingTemplateStep, User
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/routing-templates", tags=["routing-templates"])


# ============== Schemas ==============

class StepCreate(BaseModel):
    seq: int
    process_code: str
    operation_name: str
    work_center: Optional[str] = None
    standard_hours: float = 0
    is_parallel: bool = False
    is_qc_gate: bool = False
    remark: Optional[str] = None


class TemplateCreate(BaseModel):
    template_code: str
    template_name: str
    factory_id: str
    description: Optional[str] = None
    steps: List[StepCreate] = []


class TemplateUpdate(BaseModel):
    template_name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    steps: Optional[List[StepCreate]] = None


# ============== Helpers ==============

def _template_to_dict(t: RoutingTemplate, include_steps: bool = True) -> dict:
    d = {
        "id": t.id,
        "template_code": t.template_code,
        "template_name": t.template_name,
        "factory_id": t.factory_id,
        "description": t.description,
        "is_active": t.is_active,
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }
    if include_steps:
        d["steps"] = [
            {
                "id": s.id,
                "seq": s.seq,
                "process_code": s.process_code,
                "operation_name": s.operation_name,
                "work_center": s.work_center,
                "standard_hours": float(s.standard_hours) if s.standard_hours else 0,
                "is_parallel": s.is_parallel,
                "is_qc_gate": s.is_qc_gate,
                "remark": s.remark,
            }
            for s in (t.steps or [])
        ]
    return d


# ============== Routes ==============

@router.get("")
async def list_templates(
    factory_id: str = Query(...),
    active_only: bool = Query(True),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
):
    """列表（factory 隔离）"""
    async with db_config.session_factory() as db:
        query = select(RoutingTemplate).where(RoutingTemplate.factory_id == factory_id)
        count_query = select(func.count()).select_from(RoutingTemplate).where(RoutingTemplate.factory_id == factory_id)

        if active_only:
            query = query.where(RoutingTemplate.is_active == True)
            count_query = count_query.where(RoutingTemplate.is_active == True)

        total = (await db.execute(count_query)).scalar() or 0
        query = query.order_by(RoutingTemplate.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query.options(selectinload(RoutingTemplate.steps)))
        templates = result.scalars().all()

        return {
            "items": [_template_to_dict(t) for t in templates],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


@router.post("", status_code=201)
async def create_template(
    body: TemplateCreate,
    current_user: User = Depends(get_current_user),
):
    """创建模板+步骤"""
    async with db_config.session_factory() as db:
        # 检查编码唯一
        existing = await db.execute(
            select(RoutingTemplate).where(RoutingTemplate.template_code == body.template_code)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(400, f"模板编码 {body.template_code} 已存在")

        now = datetime.utcnow()
        template = RoutingTemplate(
            id=str(uuid.uuid4()),
            template_code=body.template_code,
            template_name=body.template_name,
            factory_id=body.factory_id,
            description=body.description,
            is_active=True,
            created_by=current_user.username,
            created_at=now,
            updated_at=now,
        )
        db.add(template)

        for step_data in body.steps:
            step = RoutingTemplateStep(
                id=str(uuid.uuid4()),
                template_id=template.id,
                seq=step_data.seq,
                process_code=step_data.process_code,
                operation_name=step_data.operation_name,
                work_center=step_data.work_center or step_data.process_code,
                standard_hours=step_data.standard_hours,
                is_parallel=step_data.is_parallel,
                is_qc_gate=step_data.is_qc_gate,
                remark=step_data.remark,
                created_at=now,
            )
            db.add(step)

        await db.commit()

        # 重新加载含 steps
        result = await db.execute(
            select(RoutingTemplate)
            .where(RoutingTemplate.id == template.id)
            .options(selectinload(RoutingTemplate.steps))
        )
        created = result.scalar_one()
        return _template_to_dict(created)


@router.get("/{template_id}")
async def get_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
):
    """详情含步骤"""
    async with db_config.session_factory() as db:
        result = await db.execute(
            select(RoutingTemplate)
            .where(RoutingTemplate.id == template_id)
            .options(selectinload(RoutingTemplate.steps))
        )
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(404, "模板不存在")
        return _template_to_dict(template)


@router.put("/{template_id}")
async def update_template(
    template_id: str,
    body: TemplateUpdate,
    current_user: User = Depends(get_current_user),
):
    """更新模板（含步骤全量替换）"""
    async with db_config.session_factory() as db:
        result = await db.execute(
            select(RoutingTemplate)
            .where(RoutingTemplate.id == template_id)
            .options(selectinload(RoutingTemplate.steps))
        )
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(404, "模板不存在")

        if body.template_name is not None:
            template.template_name = body.template_name
        if body.description is not None:
            template.description = body.description
        if body.is_active is not None:
            template.is_active = body.is_active
        template.updated_at = datetime.utcnow()

        # 步骤全量替换
        if body.steps is not None:
            # 删除旧步骤
            for old_step in list(template.steps):
                await db.delete(old_step)
            await db.flush()

            # 创建新步骤
            now = datetime.utcnow()
            for step_data in body.steps:
                step = RoutingTemplateStep(
                    id=str(uuid.uuid4()),
                    template_id=template.id,
                    seq=step_data.seq,
                    process_code=step_data.process_code,
                    operation_name=step_data.operation_name,
                    work_center=step_data.work_center or step_data.process_code,
                    standard_hours=step_data.standard_hours,
                    is_parallel=step_data.is_parallel,
                    is_qc_gate=step_data.is_qc_gate,
                    remark=step_data.remark,
                    created_at=now,
                )
                db.add(step)

        await db.commit()

        # 重新加载
        result = await db.execute(
            select(RoutingTemplate)
            .where(RoutingTemplate.id == template_id)
            .options(selectinload(RoutingTemplate.steps))
        )
        updated = result.scalar_one()
        return _template_to_dict(updated)


@router.delete("/{template_id}")
async def delete_template(
    template_id: str,
    current_user: User = Depends(get_current_user),
):
    """软删除（is_active=false）"""
    async with db_config.session_factory() as db:
        result = await db.execute(
            select(RoutingTemplate).where(RoutingTemplate.id == template_id)
        )
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(404, "模板不存在")

        template.is_active = False
        template.updated_at = datetime.utcnow()
        await db.commit()
        return {"message": "已停用", "id": template_id}
