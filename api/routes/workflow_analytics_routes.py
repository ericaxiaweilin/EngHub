"""
工作流分析路由 - 看清工厂深层数据流
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User

router = APIRouter(prefix="/api/v1/workflow-analytics", tags=["工作流分析"])


@router.get("/overview")
async def workflow_overview(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """7条工作流全景：量、状态分布、瓶颈"""
    from api.services.workflow_analytics_service import WorkflowAnalyticsService
    svc = WorkflowAnalyticsService(db)
    return await svc.workflow_overview(factory_id)


@router.get("/intersections")
async def department_intersections(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """部门交叉热力图：哪里交互最频繁 = 哪里需要协调人/文员"""
    from api.services.workflow_analytics_service import WorkflowAnalyticsService
    svc = WorkflowAnalyticsService(db)
    return await svc.department_intersection(factory_id)


@router.get("/gaps")
async def information_gaps(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """信息断点分析：哪里系统有数据但流程断了 = 文员存在的原因"""
    from api.services.workflow_analytics_service import WorkflowAnalyticsService
    svc = WorkflowAnalyticsService(db)
    return await svc.information_gap_analysis(factory_id)


@router.get("/material-flow")
async def material_flow(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """物流全景：进→存→产→出 完整链路"""
    from api.services.workflow_analytics_service import WorkflowAnalyticsService
    svc = WorkflowAnalyticsService(db)
    return await svc.material_flow_sankey(factory_id)
