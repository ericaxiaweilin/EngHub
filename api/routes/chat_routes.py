"""
AI Assistant chat routes.

代理到 litellm 网关 (OpenAI 兼容 /v1/chat/completions)。
所有连接参数通过环境变量配置，未配置或网关不可达时返回友好降级回复，保证前端可用。
"""

from __future__ import annotations

import os
from typing import List, Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/chat", tags=["ai-assistant"])

# --- 配置 (环境变量驱动，非硬编码) ---
GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "http://host.docker.internal:14040").rstrip("/")
API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))

SYSTEM_PROMPT = (
    "你是 EngHub MES 制造执行系统的智能助手。"
    "你熟悉生产工单、报工、检验、不良品、库存、生产计划(MRP)、"
    "工位/工艺/设备、员工技能矩阵以及合规仿真引擎(Sim-ERP)等模块。"
    "请用简洁专业的中文回答制造与车间管理相关问题；"
    "涉及具体数据操作时，引导用户到对应模块页面。"
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
    temperature: float = 0.3


class ChatResponse(BaseModel):
    reply: str
    model: str
    degraded: bool = False


@router.get("/health")
async def chat_health():
    """返回 AI 网关配置与连通性状态。"""
    configured = bool(GATEWAY_URL)
    reachable = False
    detail = "gateway url not configured"
    if configured:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{GATEWAY_URL}/health")
                reachable = resp.status_code < 500
                detail = f"status={resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            detail = f"unreachable: {type(exc).__name__}"
    return {
        "configured": configured,
        "reachable": reachable,
        "model": MODEL,
        "gateway": GATEWAY_URL,
        "detail": detail,
    }


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """转发对话到 litellm 网关；失败时降级返回。"""
    model = request.model or MODEL
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}]
        + [m.model_dump() for m in request.messages],
        "temperature": request.temperature,
    }
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(
                f"{GATEWAY_URL}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
        if resp.status_code >= 400:
            return ChatResponse(
                reply=_degraded_message(f"网关返回 {resp.status_code}"),
                model=model,
                degraded=True,
            )
        data = resp.json()
        reply = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not reply:
            return ChatResponse(reply=_degraded_message("网关无有效回复"), model=model, degraded=True)
        return ChatResponse(reply=reply, model=model, degraded=False)
    except Exception as exc:  # noqa: BLE001
        return ChatResponse(
            reply=_degraded_message(f"网关连接失败 ({type(exc).__name__})"),
            model=model,
            degraded=True,
        )


def _degraded_message(reason: str) -> str:
    return (
        f"⚠️ AI 服务暂不可用（{reason}）。\n\n"
        "请检查后端环境变量 `LLM_GATEWAY_URL` / `LLM_API_KEY` / `LLM_MODEL` "
        "是否指向可用的 litellm 网关。配置完成后即可正常对话。"
    )


__all__ = ["router"]
