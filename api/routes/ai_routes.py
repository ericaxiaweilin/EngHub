"""
AI / model-base HTTP API.

Exposes:
- health for model-engineering-base + model-stack
- model-stack domain tasks (optimize / predict / analyze)
- convenience chat via the unified model-base client
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.model_base import get_model_base_client
from integrations.luaguage import get_luaguage

router = APIRouter(prefix="/api/v1/ai", tags=["AI / Model Base"])


class ScheduleOptimizationRequest(BaseModel):
    work_orders: List[Dict[str, Any]]
    constraints: Dict[str, Any] = Field(default_factory=dict)


class DefectPredictionRequest(BaseModel):
    process_params: Dict[str, Any]


class QualityAnalysisRequest(BaseModel):
    inspection_data: List[Dict[str, Any]]


class ChatRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None


@router.get("/health")
async def ai_health() -> Dict[str, Any]:
    model_base = await get_model_base_client().health()
    luaguage = await get_luaguage().health()
    healthy = (
        model_base["model_engineering_base"]["ok"]
        or model_base["model_stack"]["ok"]
    )
    payload = {
        "status": "healthy" if healthy else "degraded",
        "model_base": model_base,
        "luaguage": luaguage,
        "note": (
            "luaguage is ERP master data, not an LLM backend. "
            "Chat/tool-calling prefers model-engineering-base; "
            "MES optimize/predict/analyze use model-stack."
        ),
    }
    if not healthy:
        # Still return 200 with degraded so ops dashboards can read details.
        payload["hint"] = (
            "Set MODEL_ENGINEERING_BASE_URL / MODEL_STACK_URL to reachable hosts."
        )
    return payload


@router.post("/optimize/schedule")
async def optimize_production_schedule(
    request: ScheduleOptimizationRequest,
) -> Dict[str, Any]:
    result = await get_model_base_client().optimize_schedule(
        work_orders=request.work_orders,
        constraints=request.constraints,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="model-stack optimize API unavailable",
        )
    return result


@router.post("/predict/defects")
async def predict_defect_rate(request: DefectPredictionRequest) -> Dict[str, Any]:
    result = await get_model_base_client().predict_defects(request.process_params)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="model-stack predict API unavailable",
        )
    return result


@router.post("/analyze/quality")
async def analyze_quality_trends(request: QualityAnalysisRequest) -> Dict[str, Any]:
    result = await get_model_base_client().analyze_quality(request.inspection_data)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="model-stack analyze API unavailable",
        )
    return result


@router.post("/chat")
async def chat_with_model_base(request: ChatRequest) -> Dict[str, Any]:
    client = get_model_base_client()
    messages = [{"role": "user", "content": request.message}]
    if request.context:
        messages.insert(
            0,
            {
                "role": "system",
                "content": f"Context: {request.context}",
            },
        )
    result = await client.chat_completion(messages=messages, tools=None)
    if result.get("fallback") or result.get("error"):
        return {
            "response": (
                f"收到问题：'{request.message}'。"
                "当前 model-engineering-base / model-stack 暂不可用，请检查底座地址。"
            ),
            "fallback": True,
            "backend_status": await client.health(),
        }
    content = (
        ((result.get("choices") or [{}])[0].get("message") or {}).get("content")
        or result.get("response")
        or ""
    )
    return {
        "response": content,
        "fallback": False,
        "backend": result.get("backend"),
        "model": result.get("model"),
    }
