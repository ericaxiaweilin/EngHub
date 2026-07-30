"""
CrewAI推理层 + 个人知识层 路由
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from pydantic import BaseModel

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User

router = APIRouter(prefix="/api/v1/crew", tags=["CrewAI推理+个人知识"])


# ═══════════════════════════════════════════════════════════
# CrewAI 推理层（组织层）
# ═══════════════════════════════════════════════════════════

@router.get("/list")
async def list_crews(current_user: User = Depends(get_current_user)):
    """列出所有Crew（决策场景）"""
    from api.services.crew_orchestration_service import CrewOrchestration
    svc = CrewOrchestration(None)
    return await svc.list_crews()


@router.post("/execute")
async def execute_crew(
    crew_key: str = Query(...),
    factory_id: str = Query(...),
    context: dict = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行Crew（多Agent协商决策）"""
    from api.services.crew_orchestration_service import CrewOrchestration
    svc = CrewOrchestration(db)
    return await svc.execute_crew(crew_key, factory_id, context or {})


@router.get("/history")
async def crew_history(
    factory_id: str = Query(...),
    limit: int = Query(20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Crew决策历史（审计）"""
    from api.services.crew_orchestration_service import CrewOrchestration
    svc = CrewOrchestration(db)
    return await svc.get_decision_history(factory_id, limit)


# ═══════════════════════════════════════════════════════════
# 个人知识层
# ═══════════════════════════════════════════════════════════

class KnowledgeCreate(BaseModel):
    factory_id: str
    employee_id: str
    category: str = "tip"  # tip/lesson/expertise/decision/trick
    title: str
    content: str
    tags: List[str] = []
    source: str = "manual"


@router.post("/knowledge/add")
async def add_knowledge(
    body: KnowledgeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """沉淀个人知识"""
    from api.services.personal_knowledge_service import PersonalKnowledgeService
    svc = PersonalKnowledgeService(db)
    return await svc.add_knowledge(
        body.factory_id, body.employee_id, body.category,
        body.title, body.content, body.tags, body.source,
    )


@router.get("/knowledge/person")
async def get_person_knowledge(
    factory_id: str = Query(...),
    employee_id: str = Query(...),
    category: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取某人的知识"""
    from api.services.personal_knowledge_service import PersonalKnowledgeService
    svc = PersonalKnowledgeService(db)
    return await svc.get_person_knowledge(factory_id, employee_id, category)


class DecisionCreate(BaseModel):
    factory_id: str
    employee_id: str
    decision_type: str
    situation: str
    decision: str
    reasoning: str = ""
    outcome: Optional[str] = None


@router.post("/decision/record")
async def record_decision(
    body: DecisionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录个人决策"""
    from api.services.personal_knowledge_service import PersonalKnowledgeService
    svc = PersonalKnowledgeService(db)
    return await svc.record_decision(
        body.factory_id, body.employee_id, body.decision_type,
        body.situation, body.decision, body.reasoning, body.outcome,
    )


@router.get("/expert/find")
async def find_expert(
    factory_id: str = Query(...),
    topic: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """找专家（组织层咨询个人层）"""
    from api.services.personal_knowledge_service import PersonalKnowledgeService
    svc = PersonalKnowledgeService(db)
    return await svc.find_expert(factory_id, topic)


@router.get("/assistant/ask")
async def ask_personal_assistant(
    factory_id: str = Query(...),
    employee_id: str = Query(...),
    question: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """个人助手：基于某人知识回答问题"""
    from api.services.personal_knowledge_service import PersonalKnowledgeService
    svc = PersonalKnowledgeService(db)
    return await svc.personal_assistant_query(factory_id, employee_id, question)


@router.get("/communication/protocol")
async def communication_protocol(
    factory_id: str = Query(...),
    from_type: str = Query("agent"),
    to_type: str = Query("person"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """交流协议查询"""
    from api.services.personal_knowledge_service import PersonalKnowledgeService
    svc = PersonalKnowledgeService(db)
    return await svc.route_communication(factory_id, from_type, to_type, {})
