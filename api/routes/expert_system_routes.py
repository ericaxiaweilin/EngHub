

"""
v2.5 - Expert System Hybrid Inference API Routes
混合推理专家系统 — 规则优先 + LLM兜底 + 前端Expert模式开关
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

router = APIRouter(prefix="/api/v1/expert-system", tags=["expert-system - 混合推理"])


class ExpertQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    industry: str = Field(default="mold", description="行业: mold / electronics / sporting_goods")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="工艺参数")
    expert_mode: str = Field(default="hybrid", description="hybrid | rules_only | ai_first")


class ExpertHealthResponse(BaseModel):
    status: str
    rule_engine_available: bool = True
    llm_gateway_configured: bool = False
    supported_industries: list


@router.get("/health", response_model=ExpertHealthResponse)
async def expert_health():
    """检查专家系统状态"""
    from os import environ
    return ExpertHealthResponse(
        status="running",
        rule_engine_available=True,
        llm_gateway_configured=bool(environ.get("LLM_GATEWAY_URL")),
        supported_industries=["mold", "electronics", "sporting_goods"],
    )


@router.post("/answer", summary="混合推理问答")
async def answer_expert_query(request: ExpertQueryRequest):
    """
    生产专家系统问答入口。
    - hybrid 模式：先跑规则检查，有异常直接返回；无异常则调用 LLM 生成通用建议
    - rules_only 模式：仅执行硬编码规则
    - ai_first 模式：优先调用 LLM，规则层作为兜底（当前仅返回查询摘要）
    """
    try:
        from core.expert_system.hybrid_engine import expert_engine

        result = await expert_engine.answer(
            query=request.query,
            industry=request.industry,
            params=request.params or {},
            expert_mode=request.expert_mode,
        )
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/rules/mold", summary="模具厂规则预览")
async def get_mold_rules():
    """获取模具厂硬编码规则定义"""
    from core.expert_system.hybrid_engine import IndustryRules
    return {
        "industry": "mold",
        "rules": IndustryRules.MOLD_FACTORY,
    }


@router.get("/rules/electronics", summary="电子厂规则预览")
async def get_electronics_rules():
    """获取电子厂硬编码规则定义"""
    from core.expert_system.hybrid_engine import IndustryRules
    return {
        "industry": "electronics",
        "rules": IndustryRules.ELECTRONICS_FACTORY,
    }


@router.get("/rules/sporting-goods", summary="运动器材厂规则预览")
async def get_sporting_goods_rules():
    """获取运动器材厂硬编码规则定义"""
    from core.expert_system.hybrid_engine import IndustryRules
    return {
        "industry": "sporting_goods",
        "rules": IndustryRules.SPORTING_GOODS_FACTORY,
    }


__all__ = ["router"]


