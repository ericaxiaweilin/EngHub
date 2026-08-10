"""统一业务工作流图接口。"""

from fastapi import APIRouter, Depends, Query

from api.services.process_knowledge_service import POSITION_SOPS, build_position_workflow_diagram
from core.auth.security import get_current_user
from database.models import User


router = APIRouter(prefix="/api/v1/workflow-diagrams", tags=["统一工作流图"])


@router.get("/catalog", summary="获取可渲染的业务工作流目录")
async def workflow_diagram_catalog(
    current_user: User = Depends(get_current_user),
):
    del current_user
    return {
        "items": [
            {
                "workflow_key": f"position:{key}",
                "type": "position_sop",
                "title": f"{sop['title']} 工作流",
                "role": sop["title"],
                "description": sop.get("duties", ""),
                "step_count": len(sop.get("daily_flow", [])),
            }
            for key, sop in POSITION_SOPS.items()
        ]
    }


@router.get("/render", summary="按注册键或职位渲染详细工作流图")
async def render_workflow_diagram(
    workflow_key: str = Query("", description="工作流注册键，如 position:pmc_planner"),
    position: str = Query("", description="职位名称或别名，如 PMC"),
    current_step: int = Query(1, ge=1, description="当前重点步骤，按1开始"),
    current_user: User = Depends(get_current_user),
):
    del current_user
    selector = position.strip()
    if not selector and workflow_key.startswith("position:"):
        selector = workflow_key.split(":", 1)[1]
    return build_position_workflow_diagram(selector or workflow_key, current_step=current_step - 1)


__all__ = ["router"]
