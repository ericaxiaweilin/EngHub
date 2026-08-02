"""
自动化等级配置路由
- 工厂可选择每条工作流的自动化程度（L0-L3）
- 不是所有工厂都能消化全自动方案，给选择权
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User

router = APIRouter(prefix="/api/v1/automation-level", tags=["自动化等级"])


@router.get("/config")
async def get_automation_config(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取工厂全部工作流的自动化等级（含成熟度评分+建议）"""
    from api.services.automation_level_service import AutomationLevelService
    svc = AutomationLevelService(db)
    return await svc.get_config(factory_id)


@router.post("/set")
async def set_automation_level(
    factory_id: str = Query(...),
    workflow_key: str = Query(..., description="工作流标识"),
    level: int = Query(..., ge=0, le=3, description="0=手工 1=辅助 2=半自动 3=全自动"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """设置单条工作流的自动化等级"""
    from api.services.automation_level_service import AutomationLevelService
    svc = AutomationLevelService(db)
    return await svc.set_level(factory_id, workflow_key, level, current_user.username)


@router.post("/batch-set")
async def batch_set_level(
    factory_id: str = Query(...),
    level: int = Query(..., ge=0, le=3, description="全厂统一等级"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """一键全厂切换（快速设置所有工作流到同一等级）"""
    from api.services.automation_level_service import AutomationLevelService
    svc = AutomationLevelService(db)
    return await svc.batch_set_level(factory_id, level, current_user.username)


@router.get("/simulate")
async def simulate_switch(
    factory_id: str = Query(...),
    workflow_key: str = Query(...),
    target_level: int = Query(..., ge=0, le=3),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """模拟切换（看切换前后行为差异+影响评估，不实际修改）"""
    from api.services.automation_level_service import AutomationLevelService
    svc = AutomationLevelService(db)
    return await svc.simulate_switch(factory_id, workflow_key, target_level)


@router.get("/definitions")
async def get_workflow_definitions(
    current_user: User = Depends(get_current_user),
):
    """获取所有工作流定义（含每个Level的行为描述）"""
    from api.services.automation_level_service import WORKFLOW_DEFINITIONS
    return {
        "total_workflows": len(WORKFLOW_DEFINITIONS),
        "level_description": {
            "L0": "纯手工：系统只记录，全部人做",
            "L1": "辅助提醒：系统预警+建议，人决定+执行",
            "L2": "半自动：标准件自动，异常人处理",
            "L3": "全自动：全部自动+异常自动升级",
        },
        "workflows": WORKFLOW_DEFINITIONS,
    }
