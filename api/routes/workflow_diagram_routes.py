"""统一业务工作流图接口。"""

from fastapi import APIRouter, Depends, Query

from api.services.process_knowledge_service import build_registered_workflow_diagram, get_workflow_catalog
from core.auth.security import get_current_user
from database.models import User


router = APIRouter(prefix="/api/v1/workflow-diagrams", tags=["统一工作流图"])


@router.get("/catalog", summary="获取可渲染的业务工作流目录")
async def workflow_diagram_catalog(
    current_user: User = Depends(get_current_user),
):
    del current_user
    return {"items": get_workflow_catalog()}


@router.get("/render", summary="按注册键或职位渲染详细工作流图")
async def render_workflow_diagram(
    workflow_key: str = Query("", description="工作流注册键，如 position:pmc_planner"),
    position: str = Query("", description="职位名称或别名，如 PMC"),
    process_name: str = Query("", description="独立业务流程名称，如 替代料验证"),
    current_step: int = Query(1, ge=1, description="当前重点步骤，按1开始"),
    current_user: User = Depends(get_current_user),
):
    del current_user
    return build_registered_workflow_diagram(
        workflow_key=workflow_key,
        process_name=process_name,
        position=position,
        current_step=current_step - 1,
    )


__all__ = ["router"]
