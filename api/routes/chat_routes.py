"""
AI Assistant chat routes（支持 Tool Calling）。

代理到 litellm 网关 (OpenAI 兼容 /v1/chat/completions)。
- 纯问答：直接转发对话。
- 操作型：通过 function-calling 让模型调用 MES 工具（查工单/建工单/报工/查库存等），
  后端执行工具并把结果回传给模型生成最终回复，同时把"已执行的操作"返回给前端展示。
所有连接参数通过环境变量配置，未配置或网关不可达时返回友好降级回复，保证前端可用。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user
from api.services.chat_tools_service import (
    TOOL_DEFINITIONS, TOOL_LABELS, WRITE_TOOLS, execute_tool, resolve_intent,
)

router = APIRouter(prefix="/api/v1/chat", tags=["ai-assistant"])

# --- 配置 (环境变量驱动，非硬编码) ---
GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "http://host.docker.internal:14040").rstrip("/")
API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
MAX_TOOL_ROUNDS = int(os.getenv("LLM_MAX_TOOL_ROUNDS", "5"))

SYSTEM_PROMPT = (
    "你是 EngHub MES 制造执行系统的智能助手，可以直接操作系统完成用户的请求。"
    "你熟悉生产工单、报工、检验、不良品、库存、生产计划(MRP)、"
    "工位/工艺/设备、员工技能矩阵以及合规仿真引擎(Sim-ERP)等模块。\n"
    "重要：当用户要求查询数据或执行操作（如查工单、建工单、报工、查库存、查不良品、查设备、下达工单等）时，"
    "你必须调用对应的工具(tool)来获取真实数据或完成操作，不要凭空编造数据。"
    "写操作（创建工单/下达工单/报工）执行后，请向用户确认操作结果。\n"
    "【严禁推诿】绝对不要回答“建议你进入XX看板/日报中心/实时看板查看”、"
    "“具体数值需结合你的实时数据源/PLC采集”这类把用户打发走的话。"
    "你能直接读到真实数据库，必须立即调用工具取数并以表格/清单形式呈现给用户。"
    "请用简洁专业的中文回答制造与车间管理相关问题。"
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
    temperature: float = 0.3
    enable_tools: bool = True  # 是否启用工具调用


class ToolAction(BaseModel):
    """一次工具执行记录，供前端展示'AI 已执行的操作'。"""
    tool: str
    label: str
    arguments: Dict[str, Any] = {}
    result: Dict[str, Any] = {}
    is_write: bool = False
    success: bool = True


class ChatResponse(BaseModel):
    reply: str
    model: str
    degraded: bool = False
    actions: List[ToolAction] = []


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


@router.get("/tools")
async def chat_tools():
    """返回当前可用的 MES 工具清单（供前端展示能力/快捷指令）。"""
    return {
        "tools": [
            {
                "name": t["function"]["name"],
                "label": TOOL_LABELS.get(t["function"]["name"], t["function"]["name"]),
                "description": t["function"]["description"],
                "is_write": t["function"]["name"] in WRITE_TOOLS,
            }
            for t in TOOL_DEFINITIONS
        ]
    }


async def _call_llm(payload: Dict[str, Any]) -> httpx.Response:
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        return await client.post(
            f"{GATEWAY_URL}/v1/chat/completions",
            json=payload,
            headers=headers,
        )


async def _run_deterministic(
    intent: Dict[str, Any],
    user_question: str,
    model: str,
    operator: str,
    db: AsyncSession,
    actions: List[ToolAction],
    factory_id: Optional[str] = None,
) -> ChatResponse:
    """确定性业务底座（参考 luaguage capability 执行思路）。

    后端根据意图直接执行工具取真实数据（不依赖模型决策），再让 LLM 仅负责把数据组织成自然语言。
    工具一定被调用、数据一定真实，从根本上杜绝“建议查看看板”这类推诿性模糊回答。"""
    tool_name = intent["tool"]
    tool_args = intent.get("args") or {}
    result = await execute_tool(db, tool_name, tool_args, operator=operator, factory_id=factory_id)
    is_error = "error" in result
    actions.append(ToolAction(
        tool=tool_name,
        label=TOOL_LABELS.get(tool_name, tool_name),
        arguments=tool_args,
        result=result,
        is_write=tool_name in WRITE_TOOLS,
        success=not is_error,
    ))
    data_str = json.dumps(result, ensure_ascii=False, default=str)
    if is_error:
        return ChatResponse(
            reply=f"⚠️ 查询失败：{result.get('error')}",
            model=model, degraded=False, actions=actions,
        )
    format_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"用户问题：{user_question}\n\n"
            f"系统已通过工具 `{tool_name}` 从真实数据库取到如下数据（JSON）：\n{data_str}\n\n"
            "请严格基于以上真实数据，用简洁专业的中文、以 Markdown 表格或清单形式直接回答用户，并给出简要分析。"
            "数据已齐全，禁止说‘建议查看看板/日报中心’之类的推诿话术，直接呈现数据。"
        )},
    ]
    try:
        fmt_resp = await _call_llm({
            "model": model,
            "messages": format_messages,
            "temperature": 0.3,
        })
        if fmt_resp.status_code < 400:
            reply = (fmt_resp.json().get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
            if reply:
                return ChatResponse(reply=reply, model=model, degraded=False, actions=actions)
    except Exception:  # noqa: BLE001
        pass
    # 格式化失败兜底：直接返回结构化真实数据
    return ChatResponse(
        reply=f"已从数据库取到真实数据：\n```json\n{data_str}\n```",
        model=model, degraded=False, actions=actions,
    )


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """转发对话到 litellm 网关，支持 tool calling 循环执行 MES 操作。"""
    model = request.model or MODEL
    operator = current_user.username or current_user.id
    factory_id = current_user.factory_id  # 当前工厂：供工具查询做数据隔离，保证与页面口径一致

    last_user = next(
        (m.content for m in reversed(request.messages) if m.role == "user"), ""
    )
    actions: List[ToolAction] = []

    # ---- 确定性业务底座：命中查询意图 → 后端直接执行工具取真实数据，LLM 仅负责组织语言 ----
    intent = resolve_intent(last_user) if request.enable_tools else None
    if intent:
        return await _run_deterministic(intent, last_user, model, operator, db, actions, factory_id)

    # ---- 非确定性意图：走 auto tool-calling 循环（写操作 / 多步 / 通用问答）----
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [m.model_dump() for m in request.messages]

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": request.temperature,
    }
    if request.enable_tools:
        payload["tools"] = TOOL_DEFINITIONS
        payload["tool_choice"] = "auto"

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            resp = await _call_llm(payload)

            # 网关不支持 tools 时（部分模型/网关返回 400），降级为纯问答重试一次
            if resp.status_code >= 400 and request.enable_tools and payload.get("tools"):
                payload.pop("tools", None)
                payload.pop("tool_choice", None)
                resp = await _call_llm(payload)

            if resp.status_code >= 400:
                return ChatResponse(
                    reply=_degraded_message(f"网关返回 {resp.status_code}"),
                    model=model, degraded=True, actions=actions,
                )

            data = resp.json()
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {}) or {}
            tool_calls = message.get("tool_calls") or []

            # 无工具调用 → 最终回复
            if not tool_calls:
                reply = (message.get("content") or "").strip()
                if not reply:
                    return ChatResponse(
                        reply=_degraded_message("网关无有效回复"),
                        model=model, degraded=True, actions=actions,
                    )
                return ChatResponse(reply=reply, model=model, degraded=False, actions=actions)

            # 有工具调用 → 逐个执行，把 assistant 消息和 tool 结果追加到上下文
            messages.append({
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            })
            for tc in tool_calls:
                fn = tc.get("function", {}) or {}
                tool_name = fn.get("name", "")
                try:
                    arguments = json.loads(fn.get("arguments") or "{}")
                except (json.JSONDecodeError, TypeError):
                    arguments = {}

                result = await execute_tool(db, tool_name, arguments, operator=operator, factory_id=factory_id)
                is_error = "error" in result
                actions.append(ToolAction(
                    tool=tool_name,
                    label=TOOL_LABELS.get(tool_name, tool_name),
                    arguments=arguments,
                    result=result,
                    is_write=tool_name in WRITE_TOOLS,
                    success=not is_error,
                ))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

            # 继续下一轮，让模型基于工具结果生成回复
            payload["messages"] = messages

        # 超过最大轮次
        return ChatResponse(
            reply="操作轮次过多，已停止。请简化您的请求后重试。",
            model=model, degraded=True, actions=actions,
        )
    except Exception as exc:  # noqa: BLE001
        return ChatResponse(
            reply=_degraded_message(f"网关连接失败 ({type(exc).__name__})"),
            model=model, degraded=True, actions=actions,
        )


def _degraded_message(reason: str) -> str:
    return (
        f"⚠️ AI 服务暂不可用（{reason}）。\n\n"
        "请检查后端环境变量 `LLM_GATEWAY_URL` / `LLM_API_KEY` / `LLM_MODEL` "
        "是否指向可用的 litellm 网关。配置完成后即可正常对话与执行操作。"
    )


__all__ = ["router"]
