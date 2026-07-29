"""
Code Table Routes - 统一码表/基础数据管理 API
=============================================
系统设置 > 码表管理：分类查询、新增、编辑、删除、启停用。
权限：admin 角色可写；所有登录用户可读。
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, List
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from core.auth.security import get_current_user
from api.services.code_table_service import CodeTableService

router = APIRouter(prefix="/api/v1/code-tables", tags=["code-tables"])


# ---- Request Models ----

class CodeTableCreate(BaseModel):
    category: str
    code: str
    name: str
    name_en: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[List[str]] = None
    extra: Optional[dict] = None
    sort_order: int = 0
    factory_id: Optional[str] = None


class CodeTableUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    name_en: Optional[str] = None
    description: Optional[str] = None
    keywords: Optional[List[str]] = None
    extra: Optional[dict] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    factory_id: Optional[str] = None


# ---- 查询 ----

@router.get("/categories")
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """获取所有码表分类及条目数"""
    svc = CodeTableService(db)
    return await svc.list_categories()


@router.get("/{category}")
async def list_by_category(
    category: str,
    factory_id: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """按分类获取码表条目"""
    svc = CodeTableService(db)
    items = await svc.list_by_category(category, factory_id=factory_id, include_inactive=include_inactive)
    return {"category": category, "items": items, "total": len(items)}


# ---- 新增 ----

@router.post("/{category}")
async def create_item(
    category: str,
    body: CodeTableCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """新增码表条目（用户自定义）"""
    if current_user.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可维护码表")
    svc = CodeTableService(db)
    try:
        item = await svc.create(
            category=category,
            code=body.code,
            name=body.name,
            name_en=body.name_en,
            description=body.description,
            keywords=body.keywords,
            extra=body.extra,
            sort_order=body.sort_order,
            factory_id=body.factory_id,
        )
        await db.commit()
        return item.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- 更新 ----

@router.put("/{category}/{item_id}")
async def update_item(
    category: str,
    item_id: str,
    body: CodeTableUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """更新码表条目"""
    if current_user.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可维护码表")
    svc = CodeTableService(db)
    try:
        fields = body.model_dump(exclude_unset=True)
        item = await svc.update(item_id, **fields)
        await db.commit()
        return item.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- 删除 ----

@router.delete("/{category}/{item_id}")
async def delete_item(
    category: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """删除码表条目（仅非系统内置）"""
    if current_user.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="仅管理员可维护码表")
    svc = CodeTableService(db)
    try:
        await svc.delete(item_id)
        await db.commit()
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
