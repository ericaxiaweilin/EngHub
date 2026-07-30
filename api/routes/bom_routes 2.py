"""
BOM Routes - EngHub BOM 对接 EngFlow 数据接口
"""
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from database.db_config import get_db
from api.services.bom_service import BomService
from api.services.bom_sync_service import BomSyncService

router = APIRouter(prefix="/api/v1/bom", tags=["BOM"])


@router.get("/models")
async def get_bom_models(db: AsyncSession = Depends(get_db)):
    """获取所有已同步的产品型号列表"""
    service = BomService(db)
    return await service.get_models()


@router.get("/tree/{model_name}")
async def get_bom_tree(model_name: str, db: AsyncSession = Depends(get_db)):
    """BOM 树形展开"""
    service = BomService(db)
    return await service.get_bom_tree(model_name)


@router.get("/search")
async def search_materials(
    q: str = Query(..., description="搜索关键词（part_number 或 description）"),
    model_name: Optional[str] = Query(None, description="限定产品型号"),
    category_l1: Optional[str] = Query(None, description="一级分类"),
    component_type: Optional[str] = Query(None, description="组件类型"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """物料搜索"""
    service = BomService(db)
    return await service.search_materials(q, model_name, category_l1, component_type, limit, offset)


@router.get("/material/{part_number}")
async def get_material_detail(part_number: str, db: AsyncSession = Depends(get_db)):
    """物料详情"""
    service = BomService(db)
    return await service.get_material_detail(part_number)


@router.post("/sync")
async def trigger_sync(
    sync_type: str = Query("incremental", description="同步类型: full / incremental"),
    db: AsyncSession = Depends(get_db),
):
    """触发 BOM 同步"""
    service = BomSyncService(db)
    if sync_type == "full":
        return await service.full_sync()
    else:
        return await service.incremental_sync()


@router.get("/sync/status")
async def get_sync_status(db: AsyncSession = Depends(get_db)):
    """获取同步状态"""
    service = BomSyncService(db)
    return await service.get_sync_status()


@router.get("/compare")
async def compare_bom(
    model: str = Query(..., description="产品型号"),
    a: str = Query(..., description="时间点A (ISO格式)"),
    b: str = Query(..., description="时间点B (ISO格式)"),
    db: AsyncSession = Depends(get_db),
):
    """BOM 版本对比"""
    service = BomService(db)
    return await service.compare_bom(model, a, b)


@router.get("/work-order/{work_order_id}")
async def get_work_order_bom(work_order_id: str, db: AsyncSession = Depends(get_db)):
    """工单关联 BOM"""
    service = BomService(db)
    return await service.get_bom_for_work_order(work_order_id)
