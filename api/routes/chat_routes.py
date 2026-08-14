"""
AI Assistant chat routes（支持 Tool Calling）。

代理到 litellm 网关 (OpenAI 兼容 /v1/chat/completions)。
- 纯问答：直接转发对话。
- 操作型：通过 function-calling 让模型调用 MES 工具（查工单/建工单/报工/查库存等），
  后端执行工具并把结果回传给模型生成最终回复，同时把"已执行的操作"返回给前端展示。
所有连接参数通过环境变量配置，未配置或网关不可达时返回友好降级回复，保证前端可用。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from database.models import (
    ChatEvalCase,
    ChatMessage as ChatMessageRecord,
    ChatMessageAttachment,
    ChatSession,
    ChatTelemetry,
    FileRecord,
    User,
    WorkbookRecord,
)
from core.auth.security import get_current_user
from api.services.chat_tools_service import (
    TOOL_DEFINITIONS, TOOL_LABELS, WRITE_TOOLS, SIM_TOOLS, execute_tool, resolve_intent,
)
from api.services.quick_command_service import (
    build_agent_system_prompt, record_agent_dispatch,
)
from api.services.workbook_service import apply_workbook_operations, xlsx_to_workbook_snapshot

router = APIRouter(prefix="/api/v1/chat", tags=["ai-assistant"])
_logger = logging.getLogger("enghub.chat")

# --- 模型底座接入配置 ---
GATEWAY_URL = os.getenv("LLM_GATEWAY_URL", "http://host.docker.internal:14040").rstrip("/")
API_KEY = os.getenv("LLM_API_KEY", "")
REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
MAX_TOOL_ROUNDS = int(os.getenv("LLM_MAX_TOOL_ROUNDS", "5"))
MODEL_STACK_CONTROL_PLANE_URL = os.getenv("MODEL_STACK_CONTROL_PLANE_URL", "").rstrip("/")
MODEL_STACK_CHAT_TASK_ID = os.getenv("MODEL_STACK_CHAT_TASK_ID", "").strip()
MODEL_STACK_VISION_TASK_ID = os.getenv("MODEL_STACK_VISION_TASK_ID", "").strip()
MODEL_STACK_ROUTE_TIMEOUT = float(os.getenv("MODEL_STACK_ROUTE_TIMEOUT", "5"))
MODEL_COLD_START_RETRY_TIMEOUT = max(
    REQUEST_TIMEOUT,
    float(os.getenv("LLM_COLD_START_RETRY_TIMEOUT", "90")),
)
MODEL_WARMUP_ENABLED = os.getenv("LLM_WARMUP_ENABLED", "1").lower() not in {
    "0", "false", "no", "off",
}
MODEL_WARMUP_INTERVAL_SECONDS = max(
    60.0,
    float(os.getenv("LLM_WARMUP_INTERVAL_SECONDS", "600")),
)
CHECKPOINT_PERSISTENCE_ENABLED = os.getenv(
    "CHECKPOINT_PERSISTENCE_ENABLED", "0"
).lower() not in {"0", "false", "no", "off"}

SYSTEM_PROMPT = (
    "你是 EngHub MES 制造执行系统的智能助手，可以直接操作系统完成用户的请求。"
    "你熟悉生产工单、报工、检验、不良品、库存、生产计划(MRP)、"
    "工位/工艺/设备、员工技能矩阵以及合规仿真引擎(Sim-ERP)等模块。\n"
    "重要：当用户要求查询数据或执行操作（如查工单、建工单、报工、查库存、查不良品、查设备、下达工单、"
    "完工/暂停/拆分工单、查工艺路线、查技能矩阵、运行合规仿真、查仿真审计记录等）时，"
    "你必须调用对应的工具(tool)来获取真实数据或完成操作，不要凭空编造数据。"
    "写操作（创建工单/下达工单/报工/完工等）执行后，请向用户确认操作结果。\n"
    "【工作流优先】当用户请求复合任务（如'帮我复盘今天生产'、'质量异常分诊'、'全面合规检查'、'建一个工单并下达'）时，"
    "优先调用 run_workflow 工具运行预置工作流（生产日度复盘/质量异常分诊/全面合规检查/一键建单下达），"
    "而不是逐个调用单步工具。\n"
    "【多模态附件】用户可能上传图片或文件。若收到图片，请结合图片内容回答（如识别设备/工件/缺陷/图纸/仪表盘），"
    "描述你看到的内容并给出专业判断；若用户要求“识别/OCR/提取文字”，请完整提取图片中所有文字内容（保留原始结构与格式）；"
    "若收到文件，基于文字与附件信息回答。\n"
    "【严禁推诿】绝对不要回答“建议你进入XX看板/日报中心/实时看板查看”、"
    "“具体数值需结合你的实时数据源/PLC采集”这类把用户打发走的话。"
    "你能直接读到真实数据库，必须立即调用工具取数并以表格/清单形式呈现给用户。\n"
    "【预警情报中枢】你不仅是查询助手，更是预警情报审查员。当系统产生被动预警（安灯工单/质量缺陷/设备故障/工单超时）时，"
    "你会自动进行初步审查（严重度/根因/建议/分派）。用户可随时问你“有什么预警”“预警简报”获取当前态势，"
    "也可以说“巡检”让你主动扫描异常。只有工具返回了对应证据时，才能给出根因、处置建议和分派对象。\n"
    "【流程知识库】系统内置了完整的流程知识：工单全生命周期（8阶段：创建→下达→派工→执行→报工→质检→完工→入库）、"
    "6大职位标准作业流程(操作员/品检员/设备工程师/PMC计划员/生产主管/仓管员)、各环节RACI责任矩阵。"
    "用户只问职责、阶段责任或SOP文字时调用 query_process_knowledge；模型先识别用户所指的岗位、独立业务子流程或审批实例，只有明确要求将该对象画成流程图、查看完整工作流、正常路径、fallback、输入输出物或关联方时才调用 query_workflow_diagram。"
    "范围必须严格匹配：用户点名“替代料验证”等子流程时，scope=standalone_process，并使用该子流程注册键（替代料验证为 process:alternate_material_validation），不得展开 PMC 父流程；只有明确要求 PMC 端到端时才使用 pmc:end_to_end。"
    "不要仅因出现“流程图”三个字就触发工具；若对象不明确，先向用户追问。未知流程不得回退PMC或DCC。工具返回后只呈现一张完整连通图，不要拆成散点知识卡。\n"
    "【PMC控制塔】当用户询问‘排过多少订单、控过多少物料、shortage怎么处理、库存怎么降、OTD怎么保证、产能怎么平衡、紧急插单怎么排、EC/BOM change怎么处理、supplier delay怎么处理’中的任一项或多项时，必须调用 query_pmc_control_tower。单项使用对应 scope，多个问题使用 scope=all。回答必须区分系统事实、统计口径、当前无记录/缺失来源和处理流程；没有历史记录时明确说无系统记录，不得补造订单、PO、供应商、ECN或OTD数字。\n"
    "【PMC工作矩阵】用户提到 PMC 矩阵、预排程沙盘、时间锤/物料锤/生产锤/出货锤/紧急锤、UHN、可加工时间或库存齐套时，"
    "有主工单号时必须调用 query_pmc_work_matrix；没有主工单号但只问物料齐套/供应证据时调用 query_pmc_material_supply。该工具只读取真实工单/BOM/库存/工位/APS，沙盘开关只改变本次计算，不修改工单；"
    "输出必须区分真实数据、假设、判断结论、风险和下一步交付物。UHN 未定义时不得猜测。\n"
    "【PMC供应证据】用户问库存、在途、PO编号、供应商ETA、物料LT、180天呆滞料能否被BOM/新订单复用时，"
    "必须调用 query_pmc_material_supply 或 query_stagnant，把 inventory、inventory_transactions、bom_items、purchase_orders 关联后回答；"
    "没有PO表或没有BOM关联时必须明确显示数据缺失，不得把普通库存查询冒充为完整供应结论。\n"
    "【任务中心】工业场景很多任务无法一次完成（等物料/等审批/等设备恢复/等供应商）。"
    "当用户交代的事情当前无法闭环、或用户说'跟进一下''盯着这个''挂起来''到时候提醒我'时，"
    "调用 create_followup_task 把任务挂入任务中心，系统会按频率（默认2小时，用户可指定）定期自动跟进并推送通知；"
    "挂账成功后告知用户可在「任务中心」页面查看进度。不要把能立即完成的查询/操作挂账。\n"
    "【回答边界】工具结果未提供的信息不得猜测，不得擅自补充故障、缺料、同步异常等可能原因。"
    "最终回答只输出面向用户的结论，禁止输出 <think>、推理过程、内部分析或工具选择过程。\n"
    "请用简洁专业的中文回答制造与车间管理相关问题。"
)

_model_warmup_lock = asyncio.Lock()
_model_warmup_state: Dict[str, Any] = {
    "enabled": MODEL_WARMUP_ENABLED,
    "interval_seconds": MODEL_WARMUP_INTERVAL_SECONDS,
    "last_started_at": None,
    "last_finished_at": None,
    "last_ok": None,
    "last_error": None,
}

TOOL_RESULT_GROUNDING = (
    "以下 JSON 是本次回答唯一可用的业务事实。只陈述 JSON 明确提供的数据，"
    "不得补充可能原因、假设、示例编号、风险结论或系统未执行的动作。"
    "数值为 0 或列表为空时，只说明当前返回无记录，不推测原因。"
)
FINAL_GROUNDING_PROMPT = (
    "最终答复必须逐项对应前面的工具 JSON。禁止添加 JSON 中不存在的状态、"
    "原因、风险、预警、示例、建议或已执行动作；不要用常识补全缺失字段。"
)


def _workbook_context_prompt(workbook_id: Optional[str]) -> str:
    if not workbook_id:
        return ""
    return (
        "\n【当前在线工作簿】用户当前绑定的 Univer 在线工作簿 ID 是 "
        f"{workbook_id}。用户询问或要求修改当前在线表格时，必须优先调用 "
        "scan_online_workbook/query_online_workbook/edit_online_workbook，并把该 workbook_id 传入；"
        "不得只在文字中假装已经修改。修改类操作必须只执行用户明确指定的单元格、公式或行。\n"
    )


_ONLINE_WORKBOOK_TOOL_NAMES = frozenset({
    "scan_online_workbook",
    "query_online_workbook",
    "recalculate_online_workbook",
    "reload_online_workbook",
    "edit_online_workbook",
    "export_online_workbook",
    "create_online_pivot",
})


def _chat_tool_definitions(
    *, has_spreadsheet_attachment: bool, workbook_id: Optional[str] = None,
    scope: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """选择本轮模型工具，并把表格附件绑定到唯一工作簿。

    有 XLSX 附件时只开放在线工作簿工具，避免模型把附件文件名误当成
    MES 业务实体调用 search_entity；但不再关闭表格工具，这样同一轮可以
    读取公式、修改单元格并导出原工作簿。
    """
    try:
        tool_catalog = _get_skill_registry().all_tool_definitions(scope=scope)
    except Exception:  # noqa: BLE001
        # Import/startup fallback only; normal requests always use the registry.
        tool_catalog = TOOL_DEFINITIONS
    if not has_spreadsheet_attachment:
        return tool_catalog
    if not workbook_id:
        return []
    return [
        definition for definition in tool_catalog
        if definition.get("function", {}).get("name") in _ONLINE_WORKBOOK_TOOL_NAMES
    ]


def _attachment_analysis_context(
    has_spreadsheet_attachment: bool, workbook_id: Optional[str] = None,
) -> str:
    if not has_spreadsheet_attachment:
        return ""
    bound = (
        f"已绑定在线工作簿 ID 为 {workbook_id}。"
        if workbook_id else
        "当前附件尚未生成可编辑工作簿，不能执行写操作。"
    )
    return (
        "\n【本轮 XLSX 附件工作簿模式】系统已经成功读取用户上传的表格，并把真实摘要追加在最后一条用户消息中。"
        f"{bound} 本轮必须只根据这份附件/绑定工作簿回答；不要调用 MES 业务检索工具或 search_entity，"
        "不要把文件名当成业务实体，也不要说无法访问用户电脑上的文件。"
        "用户明确要求扫描公式、查看依赖、修改、写公式、重算、重新加载、追加行、透视或导出时，必须调用对应的在线工作簿工具，"
        "并使用绑定的 workbook_id；没有明确修改要求时只读取和分析。"
    )


class ChatMessage(BaseModel):
    role: str
    content: str


class Attachment(BaseModel):
    """随消息提交的附件引用（前端先调 /files/upload 拿 file_id，再随消息提交）。"""
    file_id: str
    kind: Optional[str] = None  # image / file，缺省时按 content_type 推断


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    temperature: float = 0.3
    enable_tools: bool = True  # 是否启用工具调用
    attachments: List[Attachment] = Field(default_factory=list)  # 本轮用户消息附带的附件
    agent_key: Optional[str] = None  # 指定调度的智能体（空=自动，由模型自行选择工具）
    session_id: Optional[str] = None  # Chat V2 会话 ID（新建对话传空）
    workbook_id: Optional[str] = None  # 当前绑定的 Univer 在线工作簿，供 chatbot 读写


class ToolAction(BaseModel):
    """一次工具执行记录，供前端展示'AI 已执行的操作'。"""
    tool: str
    label: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    is_write: bool = False
    is_sim: bool = False
    success: bool = True


class ChatResponse(BaseModel):
    reply: str
    model: str
    degraded: bool = False
    actions: List[ToolAction] = Field(default_factory=list)
    diagrams: List[Dict[str, Any]] = Field(default_factory=list)
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    session_id: Optional[str] = None  # Chat V2：供前端带入下一轮
    request_id: Optional[str] = None  # Chat V2：Trace 锚点
    memory: Optional[Dict[str, Any]] = None  # 记忆/画像载荷：profile + 注入块 + facts（供前端展示）


@router.get("/health")
async def chat_health():
    """返回模型底座任务路由与网关连通性状态。"""
    configured = bool(
        GATEWAY_URL
        and MODEL_STACK_CONTROL_PLANE_URL
        and MODEL_STACK_CHAT_TASK_ID
    )
    reachable = False
    detail = "model-stack configuration incomplete"
    if configured:
        try:
            route = await _resolve_model_route(MODEL_STACK_CHAT_TASK_ID)
            gateway_headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
            async with httpx.AsyncClient(timeout=5.0) as client:
                gateway_resp = await client.get(
                    f"{GATEWAY_URL}/v1/models", headers=gateway_headers,
                )
            reachable = gateway_resp.status_code < 400
            detail = (
                f"control-plane=ready, gateway_models={gateway_resp.status_code}, "
                f"route={route['task_id']}"
            )
        except Exception as exc:  # noqa: BLE001
            detail = f"unreachable: {type(exc).__name__}"
    return {
        "configured": configured,
        "reachable": reachable,
        "model": MODEL_STACK_CHAT_TASK_ID,
        "gateway": GATEWAY_URL,
        "control_plane": MODEL_STACK_CONTROL_PLANE_URL,
        "detail": detail,
        "warmup": dict(_model_warmup_state),
    }


@router.get("/tools")
async def chat_tools():
    """返回当前可用的 MES 工具清单与工作流清单（供前端展示能力/快捷指令）。"""
    from api.services.workflow_service import list_workflows  # 懒加载，避免循环导入
    try:
        tool_catalog = _get_skill_registry().all_tool_definitions()
    except Exception:  # noqa: BLE001
        tool_catalog = TOOL_DEFINITIONS
    return {
        "tools": [
            {
                "name": t["function"]["name"],
                "label": TOOL_LABELS.get(t["function"]["name"], t["function"]["name"]),
                "description": t["function"]["description"],
                "is_write": t["function"]["name"] in WRITE_TOOLS,
                "is_sim": t["function"]["name"] in SIM_TOOLS,
            }
            for t in tool_catalog
        ],
        "workflows": list_workflows(),
    }


@router.get("/memory")
async def chat_memory(
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回当前用户的个人画像与长期记忆事实（供前端「记忆/画像」面板展示）。"""
    from api.services import chat_memory_service as mem
    from database.models import Role as RoleModel
    factory_id = _chat_factory_id(http_request, current_user)
    user_identity = str(current_user.id) or str(current_user.username) or "anonymous"
    memory_facts = await mem.load_user_memory(
        db, user_id=user_identity, factory_id=factory_id,
    )
    memory_rows = await mem.load_user_memory_rows(
        db, user_id=user_identity, factory_id=factory_id,
    )
    if not memory_facts:
        memory_facts = mem.memory_from_user_row(current_user)
    role_obj = None
    if getattr(current_user, "role_id", None):
        role_obj = (await db.execute(
            select(RoleModel).where(RoleModel.id == current_user.role_id)
        )).scalars().first()
    user_profile = mem.build_user_profile(current_user, memory_facts, role_obj=role_obj)
    return {
        "user_id": user_identity,
        "factory_id": factory_id,
        "profile": user_profile,
        "facts": memory_rows,
        "injected_block": mem.build_memory_block(memory_facts, profile=user_profile),
        "context_pieces": mem.build_context_pieces(memory_facts, profile=user_profile),
    }


@router.delete("/memory/{key}")
async def chat_memory_forget(
    key: str,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """遗忘一条记忆（从当前用户的记忆中删除该 key）。"""
    from api.services import chat_memory_service as mem
    factory_id = _chat_factory_id(http_request, current_user)
    user_identity = str(current_user.id) or str(current_user.username) or "anonymous"
    await mem.forget(db, user_id=user_identity, key=key)
    await db.commit()
    return {"ok": True, "key": key}


async def _resolve_model_route(
    task_id: str,
    *,
    prompt_tokens: int = 1000,
    max_completion_tokens: int = 1024,
) -> Dict[str, Any]:
    """向模型底座申请任务路由；业务侧不维护模型候选或回退链。"""
    if not MODEL_STACK_CONTROL_PLANE_URL or not task_id:
        raise RuntimeError("model-stack task routing is not configured")

    url = (
        f"{MODEL_STACK_CONTROL_PLANE_URL}/api/model-management/"
        f"business-tasks/{quote(task_id, safe='')}/route-request"
    )
    params = {
        "prompt_tokens": max(0, int(prompt_tokens)),
        "max_completion_tokens": max(0, int(max_completion_tokens)),
        "require_deployed": "true",
    }
    async with httpx.AsyncClient(timeout=MODEL_STACK_ROUTE_TIMEOUT) as client:
        resp, manifest_resp = await asyncio.gather(
            client.get(url, params=params),
            client.get(
                f"{MODEL_STACK_CONTROL_PLANE_URL}/api/model-management/providers/deployed"
            ),
        )
    resp.raise_for_status()
    manifest_resp.raise_for_status()

    envelope = resp.json()
    route = envelope.get("route_request") if isinstance(envelope, dict) else None
    providers = route.get("providers") if isinstance(route, dict) else None
    provider = str(providers[0] if providers else "").strip()
    if not provider:
        raise RuntimeError(f"model-stack returned no deployed route for {task_id}")

    manifest = manifest_resp.json()
    provider_rows = manifest.get("providers") if isinstance(manifest, dict) else None
    provider_row = next(
        (
            row for row in (provider_rows or [])
            if isinstance(row, dict)
            and str(row.get("provider") or row.get("key") or "").strip() == provider
        ),
        None,
    )
    gateway_model = str(
        (provider_row or {}).get("target_model")
        or (provider_row or {}).get("model")
        or ""
    ).strip()
    if not gateway_model:
        raise RuntimeError(f"model-stack returned no execution target for {provider}")

    runtime_policy = route.get("runtime_policy") or {}
    timeout_ms = (
        route.get("request_timeout_ms")
        or runtime_policy.get("request_timeout_ms")
        or int(REQUEST_TIMEOUT * 1000)
    )
    completion_limit = (
        route.get("max_completion_tokens")
        or runtime_policy.get("max_completion_tokens")
        or max_completion_tokens
    )
    return {
        "task_id": str(route.get("dispatch_scenario") or task_id),
        "provider": provider,
        "gateway_model": gateway_model,
        "request_timeout": max(1.0, float(timeout_ms) / 1000),
        "max_completion_tokens": max(1, int(completion_limit)),
    }


async def _call_llm(
    payload: Dict[str, Any],
    *,
    request_timeout: Optional[float] = None,
) -> httpx.Response:
    """通过模型底座网关调用控制面下发的 provider。"""
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    async with httpx.AsyncClient(timeout=request_timeout or REQUEST_TIMEOUT) as client:
        return await client.post(
            f"{GATEWAY_URL}/v1/chat/completions",
            json=payload,
            headers=headers,
        )


async def _warm_model_once(reason: str = "interval") -> bool:
    """Send a tiny no-tools request so a sleeping upstream is ready for users.

    This is deliberately separate from user traffic.  It never executes MES
    tools and it is guarded by a lock so startup and interval ticks cannot
    create concurrent warmup requests.
    """
    if not MODEL_WARMUP_ENABLED or not MODEL_STACK_CHAT_TASK_ID:
        return False
    async with _model_warmup_lock:
        started = time.monotonic()
        _model_warmup_state["last_started_at"] = time.time()
        _model_warmup_state["last_error"] = None
        try:
            route = await _resolve_model_route(
                MODEL_STACK_CHAT_TASK_ID,
                prompt_tokens=8,
                max_completion_tokens=1,
            )
            response = await _call_llm(
                {
                    "model": route["gateway_model"],
                    "messages": [{
                        "role": "user",
                        "content": "连接预热。只回复 OK。",
                    }],
                    "temperature": 0,
                    "max_tokens": 1,
                },
                request_timeout=max(
                    route["request_timeout"],
                    MODEL_COLD_START_RETRY_TIMEOUT,
                ),
            )
            response.raise_for_status()
            _model_warmup_state["last_ok"] = True
            _logger.info(
                "[model-warmup] ok reason=%s model=%s elapsed_ms=%.0f",
                reason,
                route["gateway_model"],
                (time.monotonic() - started) * 1000,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            _model_warmup_state["last_ok"] = False
            _model_warmup_state["last_error"] = type(exc).__name__
            _logger.warning(
                "[model-warmup] failed reason=%s error=%s elapsed_ms=%.0f",
                reason,
                type(exc).__name__,
                (time.monotonic() - started) * 1000,
            )
            return False
        finally:
            _model_warmup_state["last_finished_at"] = time.time()


async def model_warmup_loop() -> None:
    """Keep the selected Chatbot route warm across upstream idle periods."""
    if not MODEL_WARMUP_ENABLED:
        _logger.info("[model-warmup] disabled by LLM_WARMUP_ENABLED")
        return
    _logger.info(
        "[model-warmup] started interval=%ss retry_timeout=%ss",
        int(MODEL_WARMUP_INTERVAL_SECONDS),
        int(MODEL_COLD_START_RETRY_TIMEOUT),
    )
    while True:
        await _warm_model_once("startup" if _model_warmup_state["last_finished_at"] is None else "interval")
        await asyncio.sleep(MODEL_WARMUP_INTERVAL_SECONDS)


def _clean_model_reply(content: str) -> str:
    """清除模型协议中误混入 content 的推理区块，不改变最终答案语义."""
    reply = (content or "").strip()
    return re.sub(
        r"<think>.*?</think>",
        "",
        reply,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()


def _grounded_tool_result(result: Dict[str, Any]) -> str:
    return (
        f"{TOOL_RESULT_GROUNDING}\n"
        f"{json.dumps(result, ensure_ascii=False, default=str)}"
    )


def _format_orchestration_reply(orch_result) -> str:
    """将并行编排结果格式化为用户可读的回复"""
    parts = [f"🤖 多智能体协作完成：{orch_result.intent_name}"]
    parts.append(f"参与智能体：{len(orch_result.sub_tasks)} 个 | 耗时：{orch_result.total_duration_ms:.0f}ms")
    parts.append("")

    # 各Agent状态
    for t in orch_result.sub_tasks:
        icon = "✅" if t.status == "success" else "❌" if t.status == "error" else "⏳"
        parts.append(f"{icon} {t.agent_name} ({t.duration_ms:.0f}ms)")

    # 综合结论
    syn = orch_result.synthesis
    if syn and isinstance(syn, dict):
        parts.append("")
        if syn.get("summary"):
            parts.append(f"📋 综合判断：{syn['summary']}")
        if syn.get("findings"):
            parts.append("\n🔍 关键发现：")
            for f in syn["findings"][:5]:
                parts.append(f"  • {f}")
        if syn.get("risks"):
            parts.append("\n⚠️ 风险点：")
            for r in syn["risks"][:3]:
                parts.append(f"  • {r}")
        if syn.get("actions"):
            parts.append("\n🎯 建议行动：")
            for i, a in enumerate(syn["actions"][:5], 1):
                parts.append(f"  {i}. {a}")
        if syn.get("need_human"):
            parts.append("\n👤 需人工决策：")
            for h in syn["need_human"]:
                parts.append(f"  • {h}")
        if syn.get("degraded"):
            parts.append("\n⚠️ LLM不可用，以上为各智能体原始数据")

    return "\n".join(parts)


def _direct_tool_reply(tool_name: str, result: Dict[str, Any]) -> str:
    """Deterministic fallback reply for clear business intents."""
    label = TOOL_LABELS.get(tool_name, tool_name)
    if "error" in result:
        return f"{label}执行失败：{result['error']}"
    if tool_name == "run_virtual_factory_pulse":
        rhythm = result.get("rhythm", {})
        advanced = result.get("advanced", {})
        return (
            "虚拟工厂脉搏已推进。\n"
            f"- 月产能：{rhythm.get('monthly_capacity_containers', 300)} 柜/月，"
            f"日节奏：{rhythm.get('daily_capacity_containers', 10)} 柜/日\n"
            f"- 新建订单：{len(result.get('created_orders', []))} 个\n"
            f"- 本次报工：{advanced.get('containers_reported', 0)} 柜，"
            f"{advanced.get('reports_created', 0)} 条报工\n"
            f"- 节奏预警：{len(result.get('alerts', []))} 条"
        )
    if tool_name == "query_order_work_order_status":
        orders = result.get("orders", [])
        return (
            "订单到生产工单核对完成：\n"
            f"- 销售订单：{result.get('count', 0)} 个，已有生产工单：{result.get('orders_with_work_orders', 0)} 个"
            f"（覆盖率 {result.get('work_order_coverage_pct', 0)}%）\n"
            f"- 生产工单：{result.get('total_work_orders', 0)} 张，其中工序工单 {result.get('total_operation_work_orders', 0)} 张\n"
            f"- 工序工单已下达：{result.get('released_operation_work_orders', 0)}/{result.get('total_operation_work_orders', 0)}"
            f"（{result.get('operation_release_coverage_pct', 0)}%）\n"
            f"- 所有工序全部下达的订单：{result.get('orders_fully_released', 0)}/{len(orders)}\n"
            "结论：订单是否已经生成生产工单，与工序工单是否全部 released 是两件事；请按上面两个口径判断。"
        )
    if tool_name == "get_virtual_factory_status":
        return (
            "虚拟工厂当前状态：\n"
            f"- 虚拟销售订单：{result.get('virtual_sales_orders', 0)} 个\n"
            f"- 在制虚拟主工单：{result.get('active_virtual_orders', 0)} 个\n"
            f"- 虚拟报工记录：{result.get('virtual_report_count', 0)} 条"
        )
    if tool_name == "query_workflow_diagram":
        if result.get("error"):
            return f"流程引擎暂时无法生成图：{result['error']}\n{result.get('hint', '')}"
        diagram = result.get("diagram") or {}
        nodes = diagram.get("nodes") or []
        inputs = diagram.get("inputs") or []
        outputs = diagram.get("outputs") or []
        parties = diagram.get("related_parties") or []
        fallbacks = diagram.get("fallback_paths") or []
        meta = diagram.get("meta") or {}
        is_business = diagram.get("flow_type") == "business_workflow"
        return (
            f"已生成「{diagram.get('title', result.get('title', '详细流程图'))}」。\n"
            f"- 流程引擎步骤：{meta.get('step_count', meta.get('approval_node_count', len(nodes)))} 个，连线：{len(diagram.get('edges') or [])} 条\n"
            f"- 正常路径：{len(diagram.get('normal_path') or [])} 段；Fallback/回流：{len(fallbacks)} 条\n"
            f"- 输入物：{'、'.join(str(item) for item in inputs[:8]) or '未配置'}\n"
            f"- 输出物：{'、'.join(str(item) for item in outputs[:8]) or '未配置'}\n"
            f"- 关联方：{'、'.join(str(item) for item in parties[:8]) or '未配置'}\n"
            f"- {'点击任一步可查看输入、判断标准、输出、交付物、下一步与异常回流' if is_business else '图中保留审批角色、会签/或签、审批条件和异常路径'}\n"
            f"- {diagram.get('engine_note', '节点与连线均来自流程引擎定义。')}"
        )
    if tool_name == "query_pmc_work_matrix":
        if result.get("error"):
            return f"PMC 工作矩阵暂时无法生成：{result['error']}\n{result.get('hint', '')}"
        judgement = result.get("judgement") or {}
        focus = result.get("next_focus") or []
        computed = result.get("computed") or {}
        risks = result.get("risk_flags") or []
        calendar = result.get("calendar") or {}
        return (
            f"已生成「{result.get('title', 'PMC 工作矩阵')}」。\n"
            f"- 总体判定：{judgement.get('overall', 'needs_evidence')}\n"
            f"- 工作日历：{calendar.get('code', '未配置')}（{calendar.get('holiday_count', 0)} 个日期，状态：{calendar.get('status', 'unknown')}）\n"
            f"- 预计 FG Ready：{computed.get('fg_ready_at', '未知')}；预计 ETA：{computed.get('estimated_eta', '未知')}\n"
            f"- 当前重点：{'；'.join(str(item) for item in focus)}\n"
            f"- 风险/假设：{'；'.join(str(item) for item in risks) if risks else '暂无额外风险'}\n"
            f"- 交付物：{'；'.join(str(item) for item in result.get('deliverables') or [])}"
        )
    if tool_name == "query_pmc_control_tower":
        return _format_pmc_control_tower_reply(result)
    if tool_name in {"query_pmc_material_supply", "query_stagnant"}:
        items = result.get("items") or []
        if not items:
            return f"{label}查询完成：当前没有符合条件的记录（阈值 {result.get('threshold_days', 180)} 天）。"
        lines = [
            f"{label}查询完成：{len(items)} 种物料；呆滞阈值 {result.get('threshold_days', 180)} 天。",
            f"采购订单数据：{result.get('purchase_order_data_status', 'unknown')}。",
        ]
        for item in items[:20]:
            candidates = item.get("bom_reuse_candidates") or []
            candidate_names = [
                c.get("product_code") or c.get("product_name")
                for c in candidates
                if c.get("can_consume", True)
            ]
            po_codes = item.get("po_codes") or []
            lines.append(
                f"- {item.get('material_code')}: 可用{item.get('available_qty', item.get('qty', 0))}，"
                f"库龄{item.get('aging_days', item.get('stagnant_days', '?'))}天，"
                f"LT {item.get('supplier_lead_days', '?')}天，在途{item.get('in_transit_qty', 0)}，PO {','.join(map(str, po_codes)) or '无'}，"
                f"BOM可复用: {','.join(map(str, candidate_names[:5])) or '无关联'}"
            )
        if len(items) > 20:
            lines.append(f"- 其余 {len(items) - 20} 种物料已保留在结构化结果中。")
        return "\n".join(lines)
    if tool_name == "query_pmc_rush_impact":
        rush = result.get("rush_order") or {}
        impact = result.get("impact") or {}
        lines = [
            "PMC插单影响沙盘完成（只读）：",
            f"- 急单：{rush.get('product_id') or '未指定产品'} × {rush.get('quantity', 0)}，预计加工 {rush.get('process_hours', 0)} 小时，产能占用 {rush.get('capacity_share', 0.5) * 100:g}%",
            f"- 受影响订单：{impact.get('affected_order_count', 0)} 张；按当前模型每张延迟约 {impact.get('impact_hours_per_order', 0)} 小时",
        ]
        for item in (impact.get("delayed_orders") or [])[:20]:
            lines.append(
                f"- {item.get('work_order_code')}: 原交期 {item.get('original_due')} → 新预计 {item.get('new_estimated_end')}，延迟 {item.get('delay_days')} 天"
            )
        lines.append(result.get("note", ""))
        return "\n".join(line for line in lines if line)
    return f"{label}已完成：\n{json.dumps(result, ensure_ascii=False, default=str)[:1800]}"


def _format_pmc_control_tower_reply(result: Dict[str, Any]) -> str:
    """统一 PMC 控制塔的无模型兜底答复；所有数字均直接来自工具结果。"""
    if result.get("error"):
        return f"PMC控制塔查询失败：{result['error']}"

    def n(value: Any) -> str:
        if value is None:
            return "暂无"
        try:
            number = float(value)
            return str(int(number)) if number.is_integer() else f"{number:.2f}"
        except (TypeError, ValueError):
            return str(value)

    facts = result.get("facts") or {}
    lines = [f"PMC控制塔（工厂 {result.get('factory_id', '未指定')}，范围 {result.get('scope', 'all')}）"]

    orders = facts.get("orders")
    if orders is not None:
        lines.extend([
            "\n1. 订单排程",
            f"- 系统APS实际排程订单：{n(orders.get('scheduled_order_count'))} 张；APS方案：{n(orders.get('aps_schedule_count'))} 个；APS任务：{n(orders.get('aps_task_count'))} 条",
            f"- MPS计划：{n(orders.get('mps_plan_count'))} 个、计划数量 {n(orders.get('mps_planned_qty'))}；工单：{n(orders.get('work_order_count'))} 张（主工单 {n(orders.get('master_work_order_count'))} 张）",
            f"- 口径：只有APS任务去重工单数算“排过”；MPS/工单数不冒充APS排程历史。",
        ])

    materials = facts.get("materials")
    if materials is not None:
        lines.extend([
            "\n2. 物料控制",
            f"- 当前控制物料：{n(materials.get('controlled_material_count'))} 种；BOM {n(materials.get('bom_material_count'))} 种；工单物料 {n(materials.get('work_order_material_count'))} 种；库存SKU {n(materials.get('inventory_sku_count'))} 种",
            f"- 有历史库存流水的物料：{n(materials.get('historical_transaction_material_count'))} 种，流水 {n(materials.get('inventory_transaction_count'))} 条",
            "- 口径：这是系统当前主数据/工单控制范围，不等于线下历史累计控制过的物料数。",
        ])

    shortage = facts.get("shortage")
    if shortage is not None:
        lines.extend([
            "\n3. Shortage",
            f"- 受影响工单：{n(shortage.get('affected_work_order_count'))} 张；缺料物料：{n(shortage.get('shortage_material_count'))} 种；缺口合计：{n(shortage.get('total_shortage_qty'))}",
        ])
        for item in (shortage.get("items") or [])[:10]:
            lines.append(f"- {item.get('material_code')}: 缺 {n(item.get('shortage_qty'))}，影响工单 {','.join(map(str, item.get('affected_work_orders') or [])) or '暂无'}")
        lines.append("- 处理闭环：锁定缺口与受影响工单 → 核实库存/在途/PO ETA → 替代料验证或调整排程 → 齐套后放行。")

    inventory = facts.get("inventory")
    if inventory is not None:
        lines.extend([
            "\n4. 库存下降",
            f"- SKU：{n(inventory.get('sku_count'))}；总量：{n(inventory.get('total_qty'))}；可用：{n(inventory.get('available_qty'))}；预留：{n(inventory.get('reserved_qty'))}；呆滞：{n(inventory.get('stagnant_count'))} 种（阈值 {n(inventory.get('stagnant_threshold_days'))} 天）",
            "- 降库存动作：按已确认需求/BOM净需求停止无需求补货；优先复用共用BOM，再做调拨/退供应商/报废审批；用库存流水按周验证效果。",
        ])
        for item in [i for i in (inventory.get("items") or []) if i.get("dead_stock")][:8]:
            lines.append(f"- 呆滞 {item.get('material_code')}: 可用 {n(item.get('available_qty'))}，库龄 {n(item.get('aging_days'))} 天")

    otd = facts.get("otd")
    if otd is not None:
        pct = otd.get("otd_pct")
        lines.extend([
            "\n5. OTD",
            f"- 口径：{otd.get('otd_scope')}；到期订单 {n(otd.get('due_order_count'))}；已完工 {n(otd.get('completed_order_count'))}；准时 {n(otd.get('on_time_order_count'))}；OTD：{f'{pct}%' if pct is not None else '暂无已完工样本'}；未完工逾期 {n(otd.get('open_overdue_count'))} 张",
            "- 保证方法：MPS前同时核对ATP/物料齐套/产能/RDD；每日重算计划完工与实际完工；插单、缺料、ECN、供应延迟均触发影响评估和重排。",
        ])

    capacity = facts.get("capacity")
    if capacity is not None:
        lines.append("\n6. 产能平衡")
        lines.append(f"- 当前负荷来源：{capacity.get('load_source')}；瓶颈按利用率排序：")
        for item in (capacity.get("bottlenecks") or [])[:3]:
            lines.append(f"- {item.get('station_code') or item.get('station_name')}: 利用率 {n(item.get('utilization_pct'))}%、负荷 {n(item.get('load_hours_used'))}/{n(item.get('available_hours'))} 小时，{item.get('status')}")
        lines.append("- 平衡方法：先重排未开工工单和换型顺序，再评估加班/换线/外协/分批交付，重排后复核物料、交期和工序重叠。")

    rush = facts.get("rush")
    if rush is not None:
        lines.extend([
            "\n7. 紧急插单",
            f"- 系统插单审批记录：{n(rush.get('approval_count'))} 单；已执行：{n(rush.get('executed_count'))} 单；状态：{rush.get('status_counts') or {}}",
            "- 排法：核对BOM/库存/产能/交期 → 只读评估受影响订单和最大延迟 → 审批 → APS生成新版本并保留差异/日志 → 重算OTD风险。",
        ])
        simulation = rush.get("simulation") or {}
        if simulation:
            lines.append(f"- 本次急单沙盘：数量 {n(simulation.get('quantity'))}，预计加工 {n(simulation.get('estimated_process_hours'))} 小时，交期可行：{simulation.get('due_feasible')}")

    engineering = facts.get("engineering_change")
    if engineering is not None:
        lines.extend([
            "\n8. EC/BOM变更",
            f"- ECN记录：{n(engineering.get('ecn_count'))}；ECN标记工单：{n(engineering.get('ecn_marked_work_order_count'))}；当前产品/BOM版本组合：{n(engineering.get('bom_product_version_count'))}",
            "- 处理闭环：评审影响 → 批准并生效新BOM/工艺版本 → 重算MRP并核对旧料/替代料/在途PO → 传播到未完工工单 → APS重排并留审计。",
        ])

    supplier = facts.get("supplier_delay")
    if supplier is not None:
        lines.extend([
            "\n9. Supplier delay",
            f"- PO：{n(supplier.get('po_count'))}；未关闭：{n(supplier.get('open_po_count'))}；逾期：{n(supplier.get('overdue_count'))}；最大延迟：{n(supplier.get('max_delay_days'))} 天",
            "- 处理闭环：按逾期天数和受影响工单升级跟催 → 更新PO新ETA → 重评Shortage/ATP/OTD → 必要时切换合格供应商、空运或调整排产并保留审批原因。",
        ])

    quality = [q for q in (result.get("data_quality") or []) if q.get("status") not in ("ready",)]
    if quality:
        lines.append("\n数据质量提示：")
        for item in quality:
            missing = ", ".join(map(str, item.get("missing_sources") or [])) or "无缺表，当前记录不足"
            lines.append(f"- {item.get('key')}: {item.get('status')}；{missing}。{item.get('note') or ''}")

    if result.get("actions"):
        lines.append("\n当前建议动作：")
        lines.extend(f"- {action}" for action in result["actions"][:8])
    return "\n".join(lines)


async def _verify_grounded_reply(
    reply: str,
    actions: List[ToolAction],
    route: Dict[str, Any],
) -> str:
    """让模型按工具事实审校草稿；业务侧不参与语义改写。"""
    if not actions:
        return reply
    facts = [
        {"tool": action.tool, "result": action.result}
        for action in actions
    ]
    verification_payload = {
        "model": route["gateway_model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是事实审校器。仅保留能从工具 JSON 逐项验证的陈述，"
                    "删除所有原因猜测、风险推断、预警、建议、示例和未执行动作。"
                    "保持中文自然表达，只输出修订后的最终答复。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"工具事实：\n{json.dumps(facts, ensure_ascii=False, default=str)}"
                    f"\n\n待审校草稿：\n{reply}"
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": route["max_completion_tokens"],
    }
    resp = await _call_llm(
        verification_payload,
        request_timeout=route["request_timeout"],
    )
    if resp.status_code >= 400:
        return reply
    data = resp.json()
    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    return _clean_model_reply(content) or reply


async def _load_attachment_records(
    db: AsyncSession, attachments: List[Attachment], user: User,
) -> List[FileRecord]:
    """按 file_id 加载附件记录（做工厂隔离：普通用户不可引用其他工厂文件）。"""
    records: List[FileRecord] = []
    for att in attachments:
        rec = (await db.execute(
            select(FileRecord).where(FileRecord.id == att.file_id)
        )).scalar_one_or_none()
        if not rec:
            continue
        if not user.is_superuser and rec.factory_id and user.factory_id \
                and rec.factory_id != user.factory_id:
            continue  # 跨工厂附件直接忽略，避免越权
        records.append(rec)
    return records


def _is_image_record(rec: FileRecord) -> bool:
    return (rec.content_type or "").startswith("image/")


def _build_multimodal_content(text: str, image_records: List[FileRecord]) -> Any:
    """构造 OpenAI 多模态 content：文本 + 图片(base64 data URL)。

    图片实体从 UPLOAD_DIR 落盘文件读取并转 base64；实体缺失则跳过。
    无可用图片时退化为纯文本字符串。"""
    parts: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    for rec in image_records:
        try:
            data = Path(rec.storage_path).read_bytes()
        except OSError:
            continue
        b64 = base64.b64encode(data).decode("ascii")
        ctype = rec.content_type or "image/png"
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{ctype};base64,{b64}"},
        })
    if len(parts) == 1:
        return text
    return parts


# ---- Excel/CSV 附件解析（让模型真正"读到"表格内容，而非只知道文件名） ----

_SPREADSHEET_CONTENT_TYPES = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.ms-excel",  # .xls
    "text/csv",
    "application/csv",
)


def _is_spreadsheet_record(rec: FileRecord) -> bool:
    """判断附件是否为 Excel/CSV 表格文件（按扩展名 + content_type 双重识别）。"""
    fn = (rec.filename or "").lower()
    ct = (rec.content_type or "").lower()
    return fn.endswith((".xlsx", ".xlsm", ".xls", ".csv")) or ct in _SPREADSHEET_CONTENT_TYPES


async def _ensure_attachment_workbooks(
    db: AsyncSession,
    records: List[FileRecord],
    *,
    operator: str,
    factory_id: Optional[str],
) -> Dict[str, WorkbookRecord]:
    """把本轮 XLSX 附件绑定为唯一在线工作簿。

    /files/upload 先保存原文件；这里复用同一个文件路径创建 Univer 快照，
    因而不会生成只含计算结果的副本。重复发送同一个附件时复用原工作簿，
    也把 workbook_id 写回 files.related_id 作为稳定绑定。
    """
    bound: Dict[str, WorkbookRecord] = {}
    dirty = False
    for rec in records:
        if not _is_spreadsheet_record(rec):
            continue
        suffix = Path(rec.filename or "").suffix.lower()
        if suffix not in {".xlsx", ".xlsm"}:
            continue

        workbook: Optional[WorkbookRecord] = None
        if rec.related_id:
            workbook = (
                await db.execute(
                    select(WorkbookRecord).where(WorkbookRecord.id == rec.related_id)
                )
            ).scalar_one_or_none()
        if workbook is None:
            workbook = (
                await db.execute(
                    select(WorkbookRecord)
                    .where(WorkbookRecord.source_file_id == rec.id)
                    .order_by(WorkbookRecord.updated_at.desc())
                )
            ).scalars().first()

        if workbook is not None:
            if factory_id and workbook.factory_id and workbook.factory_id != factory_id:
                _logger.warning(
                    "[xlsx] skip cross-factory workbook binding file=%s workbook=%s",
                    rec.id, workbook.id,
                )
                continue
            if rec.related_type != "workbook" or rec.related_id != workbook.id:
                rec.related_type = "workbook"
                rec.related_id = workbook.id
                dirty = True
            bound[str(rec.id)] = workbook
            continue

        source_path = Path(rec.storage_path)
        if not source_path.is_file():
            _logger.warning("[xlsx] attachment source missing file=%s path=%s", rec.id, source_path)
            continue
        try:
            snapshot = await asyncio.to_thread(xlsx_to_workbook_snapshot, source_path)
            snapshot, _ = await asyncio.to_thread(
                apply_workbook_operations, snapshot, [], source_path,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[xlsx] workbook binding failed file=%s error=%s", rec.id, type(exc).__name__)
            continue

        workbook = WorkbookRecord(
            id=str(uuid.uuid4()),
            name=(Path(rec.filename or "workbook.xlsx").stem or "上传工作簿")[:255],
            factory_id=factory_id or rec.factory_id,
            snapshot=snapshot,
            source_file_id=rec.id,
            created_by=operator,
            updated_by=operator,
        )
        rec.related_type = "workbook"
        rec.related_id = workbook.id
        db.add(workbook)
        dirty = True
        bound[str(rec.id)] = workbook
        formula_count = sum(
            1
            for sheet in (snapshot.get("sheets") or {}).values()
            for row in (sheet.get("cellData") or {}).values()
            for item in (row or {}).values()
            if isinstance(item, dict) and item.get("f")
        )
        _logger.info(
            "[xlsx] attachment bound file=%s workbook=%s formula_cells=%s",
            rec.id, workbook.id, formula_count,
        )

    if dirty:
        await db.commit()
    return bound


def _parse_spreadsheet_record(
    rec: FileRecord, max_rows: int = 100, max_cols: int = 20,
) -> Optional[Dict[str, Any]]:
    """解析 Excel/CSV 附件 → 结构化表格数据（与前端 TableData 结构一致）。

    返回 {title, columns:[{key,label}], rows:[{...}]}；解析失败返回 None。
    首行视作表头；截断 max_rows/max_cols 避免超大文件撑爆模型上下文。"""
    try:
        path = Path(rec.storage_path)
        if not path.is_file():
            return None
        fn = (rec.filename or "").lower()
        ct = (rec.content_type or "").lower()
        grid: List[List[Any]] = []
        if fn.endswith(".csv") or ct in ("text/csv", "application/csv"):
            import csv as _csv
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
                for row in _csv.reader(f):
                    grid.append(list(row))
                    if len(grid) >= max_rows + 1:
                        break
        elif fn.endswith((".xlsx", ".xlsm")) or "spreadsheetml" in ct:
            from openpyxl import load_workbook
            wb = load_workbook(path, read_only=True, data_only=False)
            cached_wb = load_workbook(path, read_only=True, data_only=True)
            formula_details: List[Dict[str, Any]] = []
            try:
                ws = wb.active
                cached_ws = cached_wb[ws.title] if ws.title in cached_wb.sheetnames else None
                formula_rows = ws.iter_rows(max_row=max_rows + 1, max_col=max_cols)
                cached_rows = (
                    cached_ws.iter_rows(max_row=max_rows + 1, max_col=max_cols)
                    if cached_ws is not None else None
                )
                for row in formula_rows:
                    cached_row = next(cached_rows, None) if cached_rows is not None else None
                    values: List[Any] = []
                    for index, cell in enumerate(row):
                        cached_cell = (
                            cached_row[index]
                            if cached_row is not None and index < len(cached_row)
                            else None
                        )
                        if isinstance(cell.value, str) and cell.value.startswith("="):
                            formula_details.append({
                                "cell": cell.coordinate,
                                "formula": cell.value,
                                "value": cached_cell.value if cached_cell is not None else None,
                            })
                            values.append(
                                cached_cell.value
                                if cached_cell is not None and cached_cell.value is not None
                                else cell.value
                            )
                        else:
                            values.append(cell.value)
                    grid.append(values)
            finally:
                wb.close()
                cached_wb.close()
        else:
            return None  # .xls 等暂不支持的格式 → 退化为普通文件提示

        # 去掉全空行
        grid = [r for r in grid if any(c is not None and str(c).strip() != "" for c in r)]
        if not grid:
            return None

        header = [
            str(c).strip() if c is not None and str(c).strip() else f"列{i + 1}"
            for i, c in enumerate(grid[0][:max_cols])
        ]
        columns = [{"key": f"c{i}", "label": h} for i, h in enumerate(header)]
        rows: List[Dict[str, Any]] = []
        for raw in grid[1:]:
            rows.append({
                f"c{i}": ("" if i >= len(raw) or raw[i] is None else str(raw[i]))
                for i in range(len(header))
            })
        is_xlsx = fn.endswith((".xlsx", ".xlsm")) or "spreadsheetml" in ct
        return {
            "title": rec.filename or "上传表格",
            "columns": columns,
            "rows": rows,
            "formula_cells": len(formula_details) if is_xlsx else 0,
            "formula_details": formula_details if is_xlsx else [],
        }
    except Exception:  # noqa: BLE001
        return None


async def _load_spreadsheet_tables(
    records: List[FileRecord],
    *,
    workbooks: Optional[Dict[str, WorkbookRecord]] = None,
) -> Dict[str, Dict[str, Any]]:
    """在线程池中解析表格附件，避免 openpyxl 阻塞 FastAPI 事件循环。

    同一轮请求后续还要生成模型摘要；这里统一解析一次，流式表格事件和模型
    prompt 共用结果，避免大表被重复打开、重复遍历。
    """
    spreadsheet_records = [r for r in records if _is_spreadsheet_record(r)]
    if not spreadsheet_records:
        return {}

    async def load_one(rec: FileRecord):
        started = time.monotonic()
        table = await asyncio.to_thread(_parse_spreadsheet_record, rec)
        workbook = (workbooks or {}).get(str(rec.id))
        if table and workbook:
            table["workbook_id"] = workbook.id
            table["workbook_name"] = workbook.name
            table["source_file_id"] = rec.id
        _logger.info(
            "[xlsx] parsed file=%s rows=%s cols=%s elapsed_ms=%.0f",
            rec.filename,
            len(table.get("rows", [])) if table else 0,
            len(table.get("columns", [])) if table else 0,
            (time.monotonic() - started) * 1000,
        )
        return str(rec.id), table

    loaded = await asyncio.gather(*(load_one(rec) for rec in spreadsheet_records))
    return {file_id: table for file_id, table in loaded if table}


def _spreadsheet_to_summary(table: Dict[str, Any], sample_rows: int = 30) -> str:
    """智能摘要：表头 + 统计 + 样本行，替代全量 Markdown dump。

    小表（≤ sample_rows 行）给出全部行以保证 AI 分析精确；大表仅给统计+前 N 行样本省 token，
    完整数据由前端 Univer 在线表格渲染。明确告知模型数据是否完整，防止其编造表中不存在的行/值。"""
    cols = table["columns"]
    rows = table["rows"]
    total_rows = len(rows)
    col_labels = [c["label"] for c in cols]

    # --- 推断列类型 + 统计 ---
    col_stats: List[str] = []
    for c in cols:
        key, label = c["key"], c["label"]
        values = [r.get(key, "") for r in rows if r.get(key, "") != ""]
        if not values:
            col_stats.append(f"  - {label}: 全空")
            continue
        # 尝试数值推断
        nums = []
        for v in values:
            try:
                nums.append(float(str(v).replace(",", "")))
            except (ValueError, TypeError):
                break
        if nums and len(nums) == len(values):
            col_stats.append(
                f"  - {label} [数值]: min={min(nums):.2f}, max={max(nums):.2f}, "
                f"avg={sum(nums)/len(nums):.2f}, 非空{len(nums)}条"
            )
        else:
            unique = set(str(v) for v in values)
            top = list(unique)[:5]
            col_stats.append(
                f"  - {label} [文本]: {len(unique)}种取值"
                + (f", 如: {', '.join(top)}" if len(unique) <= 20 else f", 前5: {', '.join(top)}")
            )

    # --- 样本行：小表给全部行（保证精确），大表截断（省 token） ---
    shown = rows[:sample_rows]
    is_full = total_rows <= sample_rows
    sample_lines = []
    if shown:
        sample_lines.append("| " + " | ".join(col_labels) + " |")
        sample_lines.append("|" + "|".join(["---"] * len(cols)) + "|")
        for r in shown:
            sample_lines.append("| " + " | ".join(str(r.get(c["key"], "")) for c in cols) + " |")

    parts = [
        f"共 {total_rows} 行 × {len(cols)} 列",
        "列信息：\n" + "\n".join(col_stats),
    ]
    formula_details = table.get("formula_details") or []
    if formula_details:
        formula_lines = [
            f"- {item.get('cell')}: {item.get('formula')}；最近计算结果={item.get('value')}"
            for item in formula_details[:100]
        ]
        parts.append(
            f"公式单元格共 {table.get('formula_cells', len(formula_details))} 个（公式已保留）：\n"
            + "\n".join(formula_lines)
        )
    if sample_lines:
        header = (
            "全部数据如下（请严格基于这些真实数据分析，禁止编造表中不存在的行或数值）："
            if is_full else
            f"前 {sample_rows} 行样本（共 {total_rows} 行，其余见用户在线表格）："
        )
        parts.append(header + "\n" + "\n".join(sample_lines))
    if is_full:
        parts.append("（以上即该表格的全部行；分析时不得新增或修改任何数据）")
    else:
        parts.append("（完整数据已在用户的在线表格中展示，用户可直接查看/筛选/编辑）")
    return "\n".join(parts)


def _attachment_text_note(
    records: List[FileRecord],
    *,
    spreadsheet_tables: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """附件文字摘要。

    - Excel/CSV：智能摘要（表头+统计+样本），完整数据由 Univer 在线表格渲染；
    - 图片/其他文件：仅告知文件名/类型/大小（用于不支持 vision 时的优雅降级）。"""
    if not records:
        return ""
    lines = ["\n\n【用户本次上传的附件（已存入系统文件库）】"]
    for rec in records:
        if _is_spreadsheet_record(rec):
            table = (
                spreadsheet_tables.get(str(rec.id))
                if spreadsheet_tables is not None
                else _parse_spreadsheet_record(rec)
            )
            if table:
                lines.append(f"- 表格文件：{rec.filename}\n{_spreadsheet_to_summary(table)}")
            else:
                # 解析失败（文件缺失/格式不支持/损坏）：明确告知模型，避免其按文件名幻觉编造表格内容
                lines.append(
                    f"- ⚠️ 表格文件：{rec.filename} 当前无法解析或文件不可达。"
                    f"严禁编造其内容，请直接告知用户该表格暂时无法读取，并请其重新上传。"
                )
            continue
        kind = "图片" if _is_image_record(rec) else "文件"
        lines.append(f"- {kind}：{rec.filename}（{rec.content_type or '未知类型'}，{rec.size} 字节）")
    return "\n".join(lines)


def _is_attachment_analysis_request(text: str) -> bool:
    """判断用户是否在要求读取/解析本轮附件，而不是普通业务问答。"""
    return bool(re.search(r"文件|附件|表格|xlsx|xls|csv|numbers|解析|读取|导入|分析", text or "", re.I))


def _unsupported_attachment_message(
    records: List[FileRecord],
    spreadsheet_tables: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[str]:
    """对已收到但暂不能解析的附件给出确定性提示，禁止模型误报“未收到文件”。"""
    tables = spreadsheet_tables or {}
    for rec in records:
        if _is_image_record(rec):
            continue
        if _is_spreadsheet_record(rec) and tables.get(str(rec.id)):
            continue
        filename = rec.filename or "未命名文件"
        suffix = Path(filename).suffix.lower()
        if suffix == ".numbers" or "iwork-numbers" in (rec.content_type or "").lower():
            return (
                f"已收到附件《{filename}》，但它实际是 Apple Numbers 格式（.numbers），不是 XLSX。\n\n"
                "当前 Chatbot 暂不能直接读取 Numbers 文件内容。请在 Numbers 中选择“文件 → 导出到 → Excel（.xlsx）”，"
                "再重新上传导出的 .xlsx 文件，我就可以继续解析。"
            )
        if _is_spreadsheet_record(rec):
            return (
                f"已收到表格附件《{filename}》，但当前文件无法解析。\n\n"
                "请确认文件未损坏，并另存为标准 .xlsx 后重新上传。"
            )
        return (
            f"已收到附件《{filename}》（{rec.content_type or '未知格式'}），但当前 Chatbot 暂不能读取该文件格式。\n\n"
            "请上传 .xlsx、.xlsm 或 .csv 文件后再试。"
        )
    return None


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """统一 Chat 入口；V1 保持兼容，但实际执行只走 HarnessKernel。"""
    return await _handle_kernel_chat(request, http_request, db, current_user)


async def _legacy_chat_disabled(
    request: ChatRequest,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """已停用的旧内联编排，仅保留在历史提交中，不能被路由访问。"""
    operator = current_user.username or current_user.id
    factory_id = (http_request.headers.get("x-factory-id") if http_request else None) or getattr(current_user, "active_factory_id", None) or current_user.factory_id or "FAC_MECH_001"

    last_user = next(
        (m.content for m in reversed(request.messages) if m.role == "user"), ""
    )
    actions: List[ToolAction] = []

    # ---- 加载本轮附件（工厂隔离）：图片走多模态 vision，非图片以文字摘要告知 ----
    att_records = await _load_attachment_records(db, request.attachments, current_user) \
        if request.attachments else []
    image_records = [r for r in att_records if _is_image_record(r)]
    non_image_records = [r for r in att_records if not _is_image_record(r)]
    has_spreadsheet_attachment = any(_is_spreadsheet_record(r) for r in non_image_records)
    attachment_workbooks = await _ensure_attachment_workbooks(
        db,
        non_image_records,
        operator=operator,
        factory_id=factory_id,
    )

    # 这组 PMC 管理问题必须有确定性事实答复；不让模型自行决定是否查数。
    direct_intent = (
        resolve_intent(last_user)
        if request.enable_tools and not image_records and not has_spreadsheet_attachment
        else None
    )
    if direct_intent and direct_intent.get("tool") == "query_pmc_control_tower":
        arguments = direct_intent.get("args") or {}
        result = await execute_tool(db, "query_pmc_control_tower", arguments, operator=operator, factory_id=factory_id)
        action = ToolAction(
            tool="query_pmc_control_tower",
            label=TOOL_LABELS["query_pmc_control_tower"],
            arguments=arguments,
            result=result,
            is_write=False,
            is_sim=False,
            success="error" not in result,
        )
        return ChatResponse(
            reply=_direct_tool_reply("query_pmc_control_tower", result),
            model="pmc-control-tower",
            degraded="error" in result,
            actions=[action],
        )
    if direct_intent and direct_intent.get("tool") == "query_order_work_order_status":
        arguments = direct_intent.get("args") or {}
        result = await execute_tool(
            db,
            "query_order_work_order_status",
            arguments,
            operator=operator,
            factory_id=factory_id,
        )
        action = ToolAction(
            tool="query_order_work_order_status",
            label=TOOL_LABELS["query_order_work_order_status"],
            arguments=arguments,
            result=result,
            is_write=False,
            is_sim=False,
            success="error" not in result,
        )
        return ChatResponse(
            reply=_direct_tool_reply("query_order_work_order_status", result),
            model="order-work-order-status",
            degraded="error" in result,
            actions=[action],
        )

    # ---- 多智能体并行编排：识别复合意图 → 多Agent并行执行 ----
    if request.enable_tools and not image_records and not request.agent_key:
        try:
            from api.services.parallel_orchestrator import ParallelOrchestrator
            orchestrator = ParallelOrchestrator(db)
            parallel_intent = orchestrator.resolve_intent(last_user)
            if parallel_intent == "__commander__":
                # 工厂指挥官模式
                from api.services.factory_commander import FactoryCommander
                commander = FactoryCommander(db)
                report = await commander.run_cycle(factory_id, auto_execute=True, created_by=operator)
                reply = report.to_chatbot_reply()
                actions.append(ToolAction(
                    tool="factory_commander:cycle",
                    label="工厂指挥官: 自主决策",
                    arguments={"factory_id": factory_id},
                    result=report.to_dict(),
                    is_write=True,
                    is_sim=False,
                    success=True,
                ))
                return ChatResponse(
                    reply=reply,
                    model="factory-commander",
                    degraded=False,
                    actions=actions,
                )
            elif parallel_intent:
                orch_result = await orchestrator.execute(
                    intent=parallel_intent,
                    factory_id=factory_id,
                    context={"user_message": last_user, "operator": operator},
                    user_message=last_user,
                )
                # 构建回复
                reply = _format_orchestration_reply(orch_result)
                actions.append(ToolAction(
                    tool=f"parallel_orchestrator:{parallel_intent}",
                    label=f"多智能体协作: {orch_result.intent_name}",
                    arguments={"intent": parallel_intent},
                    result=orch_result.to_dict(),
                    is_write=False,
                    is_sim=False,
                    success=orch_result.status in ("completed", "partial"),
                ))
                return ChatResponse(
                    reply=reply,
                    model="parallel-orchestrator",
                    degraded=False,
                    actions=actions,
                )
        except Exception as _orch_err:
            import logging as _lg
            _lg.getLogger("chat").debug(f"parallel orchestrator skip: {_orch_err}")

    spreadsheet_tables = await _load_spreadsheet_tables(
        non_image_records,
        workbooks=attachment_workbooks,
    )
    non_image_note = _attachment_text_note(
        non_image_records,
        spreadsheet_tables=spreadsheet_tables,
    )
    unsupported_attachment = _unsupported_attachment_message(
        non_image_records,
        spreadsheet_tables,
    )
    if unsupported_attachment and _is_attachment_analysis_request(last_user):
        return ChatResponse(
            reply=unsupported_attachment,
            model="attachment-parser",
            degraded=False,
            actions=actions,
        )
    task_id = MODEL_STACK_VISION_TASK_ID if image_records else MODEL_STACK_CHAT_TASK_ID
    prompt_tokens = max(
        1,
        (sum(len(m.content or "") for m in request.messages) + len(non_image_note)) // 4,
    )
    try:
        route = await _resolve_model_route(task_id, prompt_tokens=prompt_tokens)
    except Exception as exc:  # noqa: BLE001
        return ChatResponse(
            reply=_degraded_message(f"模型底座路由失败 ({type(exc).__name__})"),
            model=task_id, degraded=True, actions=actions,
        )

    # 有本轮表格附件时，模型只基于附件回答；不能把浏览器里残留的在线工作簿
    # ID 注入进来，否则会把“上传文件”和“在线工作簿”混成两条数据链路。
    bound_workbook_id = next(
        (workbook.id for workbook in attachment_workbooks.values()),
        None,
    )
    workbook_context = (
        _workbook_context_prompt(bound_workbook_id)
        if spreadsheet_tables else _workbook_context_prompt(request.workbook_id)
    )
    tool_definitions = _chat_tool_definitions(
        has_spreadsheet_attachment=bool(spreadsheet_tables),
        workbook_id=bound_workbook_id,
        scope=factory_id,
    )
    # 所有文本意图统一交给模型解析；后端仅执行模型返回的 tool_calls。
    messages: List[Dict[str, Any]] = [{
        "role": "system",
        "content": SYSTEM_PROMPT + _attachment_analysis_context(
            bool(spreadsheet_tables), bound_workbook_id,
        ) + workbook_context,
    }]
    # ---- 智能体调度：指定 agent 时注入其职责提示词，并记录监督心跳 ----
    if request.agent_key:
        agent_prompt = build_agent_system_prompt(request.agent_key)
        if agent_prompt:
            messages.append({"role": "system", "content": agent_prompt})
            await record_agent_dispatch(db, factory_id, request.agent_key, last_user)
    history = [m.model_dump() for m in request.messages]
    # 将附件注入「最后一条用户消息」：图片 → 多模态 content；非图片 → 文字摘要追加
    injected = False
    for idx in range(len(history) - 1, -1, -1):
        if history[idx].get("role") == "user":
            text = history[idx].get("content") or ""
            if non_image_note:
                text = f"{text}{non_image_note}"
            history[idx]["content"] = _build_multimodal_content(text, image_records)
            injected = True
            break
    if not injected and image_records:
        # 历史中无用户消息（异常场景）：补一条多模态用户消息
        history.append({"role": "user", "content": _build_multimodal_content(last_user, image_records)})
    messages += history

    payload: Dict[str, Any] = {
        "model": route["gateway_model"],
        "messages": messages,
        "temperature": request.temperature,
        "max_tokens": route["max_completion_tokens"],
    }
    # 图片内容由视觉任务模型理解；业务侧不再用 OCR 关键词选择具体模型。
    if not image_records and request.enable_tools and tool_definitions:
        payload["tools"] = tool_definitions
        payload["tool_choice"] = "auto"

    model_request_timeout = (
        max(route["request_timeout"], MODEL_COLD_START_RETRY_TIMEOUT)
        if spreadsheet_tables
        else route["request_timeout"]
    )
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            resp = await _call_llm(
                payload,
                request_timeout=model_request_timeout,
            )

            if resp.status_code >= 400:
                return ChatResponse(
                    reply=_degraded_message(f"网关返回 {resp.status_code}"),
                    model=route["task_id"], degraded=True, actions=actions,
                )

            data = resp.json()
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {}) or {}
            tool_calls = message.get("tool_calls") or []

            # 无工具调用 → 最终回复
            if not tool_calls:
                reply = _clean_model_reply(message.get("content") or "")
                if not reply:
                    return ChatResponse(
                        reply=_degraded_message("网关无有效回复"),
                        model=route["task_id"], degraded=True, actions=actions,
                    )
                reply = await _verify_grounded_reply(reply, actions, route)
                return ChatResponse(
                    reply=reply,
                    model=route["task_id"],
                    degraded=False,
                    actions=actions,
                    diagrams=_collect_diagrams(actions),
                )

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
                    is_sim=tool_name in SIM_TOOLS,
                    success=not is_error,
                ))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": _grounded_tool_result(result),
                })

            # 继续下一轮，让模型基于工具结果生成回复
            messages.append({"role": "system", "content": FINAL_GROUNDING_PROMPT})
            payload["messages"] = messages
            # 能力已由模型完成语义选择；后续只让模型基于工具结果生成答复，
            # 不再重复发送完整工具清单，避免无意义的 token 消耗和二次工具调用。
            payload.pop("tools", None)
            payload.pop("tool_choice", None)

        # 超过最大轮次
        return ChatResponse(
            reply="操作轮次过多，已停止。请简化您的请求后重试。",
            model=route["task_id"], degraded=True, actions=actions,
        )
    except Exception as exc:  # noqa: BLE001
        return ChatResponse(
            reply=_degraded_message(f"网关连接失败 ({type(exc).__name__})"),
            model=route["task_id"], degraded=True, actions=actions,
        )


# =================================================================
# Chat V2 — Harness Kernel 链路（Phase 1 Skeleton）
# =================================================================
# 逐步把上述 chat() 的非 HTTP 逻辑收敛进 core/kernel。
# V2 与 V1 保持行为等价。
#
# CLI 独立于本链路，不经过 Harness Kernel。

_skill_registry_instance = None


def _get_skill_registry():
    """按需构建并缓存 Skill 注册表（含自动发现）。"""
    global _skill_registry_instance
    if _skill_registry_instance is not None:
        return _skill_registry_instance
    from core.skills import SkillRegistry
    reg = SkillRegistry.get_instance()
    reg.autodiscover()
    _skill_registry_instance = reg
    return reg


def _checkpoint_options() -> Dict[str, Any]:
    """按环境开关给 Chat V2 Kernel 注入 checkpoint DB 冷存储。"""
    if not CHECKPOINT_PERSISTENCE_ENABLED:
        return {}
    from database.db_config import db_config

    return {
        "checkpoint_session_factory": db_config.session_factory,
        "checkpoint_persistence_enabled": True,
    }


def _chat_factory_id(http_request: Optional[Request], current_user: User) -> str:
    """解析当前请求工厂；会话访问必须使用同一个解析结果。"""
    return (
        (http_request.headers.get("x-factory-id") if http_request else None)
        or getattr(current_user, "active_factory_id", None)
        or getattr(current_user, "factory_id", None)
        or "FAC_MECH_001"
    )


async def _open_chat_session(
    db: AsyncSession,
    *,
    factory_id: str,
    user: User,
    session_id: Optional[str],
    title: Optional[str],
):
    """打开会话并把越权/失效 session 转成稳定的 HTTP 403。"""
    from api.services.chat_persistence_service import (
        ChatSessionAccessError,
        get_or_create_session,
    )

    try:
        return await get_or_create_session(
            db,
            factory_id=factory_id,
            user=user,
            session_id=session_id,
            title=title,
        )
    except ChatSessionAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


async def _build_chat_history(
    db: AsyncSession,
    *,
    session_id: str,
    request_messages: List[ChatMessage],
) -> List[Dict[str, Any]]:
    """以服务端持久化历史为主，兼容新会话/旧客户端的 messages 回退。"""
    from api.services.chat_persistence_service import get_history

    client_history = [m.model_dump() for m in request_messages]
    persisted = await get_history(
        db,
        session_id,
        limit=50,
        include_tools=False,
        include_tool_calls=False,
        include_attachments=False,
    )
    if not persisted:
        return client_history

    current_user = next(
        (m for m in reversed(client_history) if m.get("role") == "user"),
        None,
    )
    history = list(persisted)
    if current_user:
        # 当前轮尚未落库；历史中最后一条通常是上一轮 assistant。
        last_persisted = persisted[-1]
        if not (
            last_persisted.get("role") == "user"
            and last_persisted.get("content") == current_user.get("content")
        ):
            history.append(current_user)
    return history


def _inject_chat_attachments(
    history: List[Dict[str, Any]],
    *,
    image_records: List[Any],
    non_image_note: str,
    fallback_user_text: str,
) -> None:
    """只把本轮附件挂到最后一条用户消息，避免重复污染历史轮次。"""
    injected = False
    for idx in range(len(history) - 1, -1, -1):
        if history[idx].get("role") != "user":
            continue
        text = history[idx].get("content") or ""
        if non_image_note:
            text = f"{text}{non_image_note}"
        history[idx]["content"] = _build_multimodal_content(text, image_records)
        injected = True
        break
    if not injected and image_records:
        history.append({
            "role": "user",
            "content": _build_multimodal_content(fallback_user_text, image_records),
        })


async def _handle_kernel_chat(
    request: ChatRequest,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """统一 Harness Kernel 请求处理器，供 V1/V2/SSE 共用。

    Phase 3：会话持久化——无 session_id 自动建会话，请求结束落库消息+遥测。
    """
    from core.kernel import HarnessKernel, KernelResponse

    operator = current_user.username or current_user.id
    factory_id = _chat_factory_id(http_request, current_user)
    last_user = next(
        (m.content for m in reversed(request.messages) if m.role == "user"),
        "",
    )

    # ── 会话持久化（Phase 3）：取既有或新建 session ──
    session = await _open_chat_session(
        db,
        factory_id=factory_id,
        user=current_user,
        session_id=request.session_id,
        title=last_user,
    )
    session_id = session.id

    # ── 用户长期记忆（跨会话）：加载用户维度的已记事实，注入 system prompt ──
    from api.services import chat_memory_service as mem
    from database.models import Role as RoleModel
    user_identity = str(current_user.id) or str(current_user.username) or "anonymous"
    memory_facts = await mem.load_user_memory(
        db, user_id=user_identity, factory_id=factory_id,
    )
    if not memory_facts:
        memory_facts = mem.memory_from_user_row(current_user)
    role_obj = None
    if getattr(current_user, "role_id", None):
        role_obj = (await db.execute(
            select(RoleModel).where(RoleModel.id == current_user.role_id)
        )).scalars().first()
    user_profile = mem.build_user_profile(current_user, memory_facts, role_obj=role_obj)
    memory_block = mem.build_memory_block(memory_facts, profile=user_profile)

    # 附件加载与 V1 一致
    att_records = await _load_attachment_records(db, request.attachments, current_user) \
        if request.attachments else []
    image_records = [r for r in att_records if _is_image_record(r)]
    non_image_records = [r for r in att_records if not _is_image_record(r)]
    attachment_workbooks = await _ensure_attachment_workbooks(
        db,
        non_image_records,
        operator=operator,
        factory_id=factory_id,
    )
    spreadsheet_tables = await _load_spreadsheet_tables(
        non_image_records,
        workbooks=attachment_workbooks,
    )
    non_image_note = _attachment_text_note(
        non_image_records,
        spreadsheet_tables=spreadsheet_tables,
    )
    unsupported_attachment = _unsupported_attachment_message(
        non_image_records,
        spreadsheet_tables,
    )

    # 历史消息注入附件（图片 → 多模态 content；非图片 → 文字摘要）
    history = await _build_chat_history(
        db,
        session_id=session_id,
        request_messages=request.messages,
    )
    _inject_chat_attachments(
        history,
        image_records=image_records,
        non_image_note=non_image_note,
        fallback_user_text=last_user,
    )

    prompt_tokens = max(
        1,
        (sum(len(m.content or "") for m in request.messages) + len(non_image_note)) // 4,
    )

    async def bound_execute(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from api.services.chat_tools_service import execute_tool as exec_tool
        return await exec_tool(db, tool_name, arguments, operator=operator, factory_id=factory_id)

    def make_tool_action(
        tool: str, label: str, arguments: Dict[str, Any],
        result: Dict[str, Any], is_write: bool, is_sim: bool, success: bool,
    ) -> ToolAction:
        return ToolAction(
            tool=tool, label=label, arguments=arguments, result=result,
            is_write=is_write, is_sim=is_sim, success=success,
        )

    # 所有工具都通过显式 SkillRegistry 边界执行。
    skill_registry = _get_skill_registry()

    # Phase 4：权限门控（基于用户权限集 + 数据作用域）
    from core.kernel.permission import PermissionGate
    permission_gate = PermissionGate()

    # Phase 5：结构化事实审查（Evidence 链 → ModelReview）
    from core.kernel.model_review import ModelReviewer
    model_reviewer = ModelReviewer(
        call_llm=_call_llm,
        clean_reply=_clean_model_reply,
        request_timeout=(
            MODEL_COLD_START_RETRY_TIMEOUT if spreadsheet_tables else 60.0
        ),
    )
    bound_workbook_id = next(
        (workbook.id for workbook in attachment_workbooks.values()),
        None,
    )
    workbook_context = (
        _workbook_context_prompt(bound_workbook_id)
        if spreadsheet_tables else _workbook_context_prompt(request.workbook_id)
    )
    tool_definitions = _chat_tool_definitions(
        has_spreadsheet_attachment=bool(spreadsheet_tables),
        workbook_id=bound_workbook_id,
        scope=factory_id,
    )

    async def deterministic_handler(ctx, execute, action_factory):
        """Handle facts that already have a stable server-side intent mapping.

        This remains inside HarnessKernel so direct PMC/order answers receive
        the same permission, telemetry and persistence treatment as model-led
        tool calls.
        """
        if unsupported_attachment and _is_attachment_analysis_request(last_user):
            return KernelResponse(
                reply=unsupported_attachment,
                model="attachment-parser",
                request_id=ctx.request_id,
            )
        if (
            not request.enable_tools
            or image_records
            or spreadsheet_tables
        ):
            return None
        intent = resolve_intent(ctx.last_user_content)
        if not intent:
            return None
        tool_name = intent.get("tool")
        if tool_name not in {
            "query_pmc_control_tower",
            "query_order_work_order_status",
        }:
            return None
        arguments = intent.get("args") or {}
        result = await execute(tool_name, arguments)
        action = None
        if action_factory is not None:
            action = action_factory(
                tool_name,
                TOOL_LABELS.get(tool_name, tool_name),
                arguments,
                result,
                tool_name in WRITE_TOOLS,
                tool_name in SIM_TOOLS,
                "error" not in result,
            )
        tables = []
        table_data = _extract_table_data(tool_name, result)
        if table_data:
            tables.append(table_data)
        return KernelResponse(
            reply=_direct_tool_reply(tool_name, result),
            model=(
                "pmc-control-tower"
                if tool_name == "query_pmc_control_tower"
                else "order-work-order-status"
            ),
            degraded="error" in result,
            actions=[action] if action is not None else [],
            tables=tables,
            request_id=ctx.request_id,
        )

    async def persist_after(ctx, response):
        """Phase 3：请求结束后落库（消息 + 遥测 + 事件流）。"""
        from api.services import chat_persistence_service as cp
        last_user = ctx.last_user_content
        await cp.persist_round(
            db, session_id=session_id,
            user_content=last_user or "（图片/附件消息）",
            reply=response.reply,
            model=response.model,
            actions=response.actions,
            request_id=ctx.request_id,
            attachment_ids=[str(record.id) for record in att_records],
        )
        await cp.save_telemetry(
            db, request_id=ctx.request_id, session_id=session_id,
            model=response.model,
            tools_called=[a.tool for a in response.actions],
            rounds=len(response.actions),
            success=not response.degraded,
        )
        # 事件流（DSH SessionEvent 对齐）：注入上下文 → 用户消息 → 工具调用 → 回复。
        try:
            pieces = mem.build_context_pieces(memory_facts, profile=user_profile)
            events: List[Dict[str, Any]] = []
            for piece in pieces:
                events.append({
                    "type": "context_injection",
                    "data": {
                        "source": piece.get("source"),
                        "label": piece.get("label"),
                        "content": piece.get("content"),
                    },
                })
            events.append({
                "type": "user_message",
                "data": {"content": last_user or "（图片/附件消息）"},
            })
            for action in response.actions:
                events.append({
                    "type": "tool_call",
                    "data": {
                        "tool": action.tool,
                        "label": getattr(action, "label", action.tool),
                        "args": getattr(action, "arguments", None),
                        "result": getattr(action, "result", None),
                        "success": getattr(action, "success", True),
                        "is_write": getattr(action, "is_write", False),
                    },
                })
            events.append({
                "type": "assistant_reply",
                "data": {
                    "reply": response.reply,
                    "model": response.model,
                    "duration_ms": getattr(response, "duration_ms", None),
                    "degraded": response.degraded,
                    "tool_count": len(response.actions),
                },
            })
            await cp.append_session_events(
                db, session_id=session_id, request_id=ctx.request_id, events=events,
            )
        except Exception:  # noqa: BLE001
            _logger.exception("[chat-kernel] 事件流写入失败 request=%s", ctx.request_id)
        # 记忆：从本轮用户消息规则提取新事实并落库（用户明确告知才记）
        for fact in mem.learn_from_text(last_user or ""):
            await mem.remember(
                db, user_id=user_identity, key=fact["key"], value=fact["value"],
                factory_id=factory_id, confidence=fact.get("confidence", 2),
            )
        # StreamingResponse cleanup happens after the body is consumed. Commit
        # here so the shared Kernel path never leaves the request transaction
        # idle while the client or proxy is still holding the response open.
        await db.commit()

    kernel = HarnessKernel(
        db=db,
        call_llm=_call_llm,
        resolve_model_route=_resolve_model_route,
        execute_tool=bound_execute,
        clean_reply=_clean_model_reply,
        ground_tool_result=_grounded_tool_result,
        verify_reply=_verify_grounded_reply,
        make_tool_action=make_tool_action,
        write_tools=frozenset(WRITE_TOOLS),
        sim_tools=frozenset(SIM_TOOLS),
        tool_definitions=tool_definitions,
        system_prompt=(memory_block + "\n" + SYSTEM_PROMPT if memory_block else SYSTEM_PROMPT)
        + _attachment_analysis_context(
            bool(spreadsheet_tables), bound_workbook_id,
        ) + workbook_context,
        final_grounding_prompt=FINAL_GROUNDING_PROMPT,
        chat_task_id=MODEL_STACK_CHAT_TASK_ID,
        vision_task_id=MODEL_STACK_VISION_TASK_ID,
        max_tool_rounds=MAX_TOOL_ROUNDS,
        skill_registry=skill_registry,
        persist_hook=persist_after,
        permission_gate=permission_gate,
        model_reviewer=model_reviewer,
        deterministic_handler=deterministic_handler,
        **_checkpoint_options(),
    )

    deterministic_intent = (
        resolve_intent(last_user)
        if request.enable_tools and not image_records and not spreadsheet_tables
        else None
    )
    route_not_required = bool(
        (unsupported_attachment and _is_attachment_analysis_request(last_user))
        or (deterministic_intent and deterministic_intent.get("tool") in {
            "query_pmc_control_tower",
            "query_order_work_order_status",
        })
    )
    ctx = await kernel.build_context(
        factory_id=factory_id,
        user=current_user,
        messages=history,
        attachments=att_records,
        enable_tools=request.enable_tools,
        agent_key=request.agent_key,
        temperature=request.temperature,
        session_id=session_id,
        prompt_tokens=prompt_tokens,
        resolve_route=not route_not_required,
    )
    result = await kernel.handle(ctx)

    return ChatResponse(
        reply=result.reply,
        model=result.model,
        degraded=result.degraded,
        actions=result.actions,
        diagrams=(
            list(result.diagrams)
            + [
                diagram
                for action in result.actions
                if (diagram := _extract_diagram_data(
                    getattr(action, "tool", ""),
                    getattr(action, "result", {}) or {},
                ))
            ]
        ),
        tables=(
            list(spreadsheet_tables.values())
            + list(result.tables)
            + [
                table
                for action in result.actions
                if (table := _extract_table_data(
                    getattr(action, "tool", ""),
                    getattr(action, "result", {}) or {},
                ))
            ]
        ),
        session_id=session_id,
        request_id=result.request_id,
        memory={
            "profile": user_profile,
            "injected_block": memory_block,
            "context_pieces": mem.build_context_pieces(memory_facts, profile=user_profile),
            "facts": [
                {"key": k, "value": v}
                for k, v in memory_facts.items()
            ],
        },
    )


@router.post("/v2", response_model=ChatResponse)
async def chat_v2(
    request: ChatRequest,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """兼容入口；与 V1 共用同一个 HarnessKernel 处理器。"""
    return await _handle_kernel_chat(request, http_request, db, current_user)


def _degraded_message(reason: str) -> str:
    return (
        f"AI 服务暂不可用（{reason}）。\n\n"
        "模型任务未能由模型底座正常下发，请检查控制面与模型网关状态。"
    )


# ==================== 结构化表格提取（chatbot → 在线表格） ====================

# 各查询工具结果 → 表格列定义（key=字段名, label=中文表头）
_TABLE_COLUMNS: Dict[str, List[Dict[str, str]]] = {
    "query_work_orders": [
        {"key": "work_order_code", "label": "工单号"},
        {"key": "product_name", "label": "产品"},
        {"key": "planned_qty", "label": "计划数"},
        {"key": "completed_qty", "label": "完成数"},
        {"key": "progress_pct", "label": "进度%"},
        {"key": "status", "label": "状态"},
        {"key": "priority", "label": "优先级"},
        {"key": "planned_due", "label": "交期"},
    ],
    "query_order_work_order_status": [
        {"key": "sales_order_code", "label": "销售订单"},
        {"key": "sales_order_status", "label": "订单状态"},
        {"key": "actual_work_order_count", "label": "生产工单数"},
        {"key": "master_work_order_code", "label": "主工单"},
        {"key": "master_status", "label": "主工单状态"},
        {"key": "operation_work_order_count", "label": "工序工单数"},
        {"key": "released_operation_count", "label": "已下达工序"},
        {"key": "pending_operation_count", "label": "待下达工序"},
        {"key": "all_operation_work_orders_released", "label": "工序是否全下达"},
    ],
    "query_inventory": [
        {"key": "material_code", "label": "物料编码"},
        {"key": "material_id", "label": "物料ID"},
        {"key": "warehouse_id", "label": "仓库"},
        {"key": "batch_code", "label": "批次"},
        {"key": "total_qty", "label": "总数量"},
        {"key": "available_qty", "label": "可用"},
        {"key": "reserved_qty", "label": "预留"},
        {"key": "status", "label": "状态"},
    ],
    "query_pmc_material_supply": [
        {"key": "material_code", "label": "物料编码"},
        {"key": "material_name", "label": "物料名称"},
        {"key": "available_qty", "label": "可用库存"},
        {"key": "reserved_qty", "label": "预留"},
        {"key": "in_transit_qty", "label": "在途"},
        {"key": "on_order_qty", "label": "未收货PO"},
        {"key": "supplier_lead_days", "label": "供应商LT(天)"},
        {"key": "aging_days", "label": "库龄(天)"},
        {"key": "dead_stock", "label": "180天呆滞"},
        {"key": "po_codes", "label": "PO编号"},
        {"key": "bom_reuse_candidates", "label": "BOM可复用产品"},
    ],
    "query_stagnant": [
        {"key": "material_code", "label": "物料编码"},
        {"key": "qty", "label": "可用库存"},
        {"key": "stagnant_days", "label": "呆滞天数"},
        {"key": "supplier_lead_days", "label": "供应商LT(天)"},
        {"key": "in_transit_qty", "label": "在途"},
        {"key": "po_codes", "label": "PO编号"},
        {"key": "bom_reuse_candidates", "label": "BOM可复用产品"},
    ],
    "query_pmc_rush_impact": [
        {"key": "work_order_code", "label": "受影响工单"},
        {"key": "product_id", "label": "产品"},
        {"key": "original_due", "label": "原交期"},
        {"key": "new_estimated_end", "label": "新预计完工"},
        {"key": "delay_hours", "label": "延迟小时"},
        {"key": "delay_days", "label": "延迟天数"},
    ],
    "query_defects": [
        {"key": "record_code", "label": "记录编号"},
        {"key": "defect_type", "label": "不良类型"},
        {"key": "severity", "label": "严重度"},
        {"key": "quantity", "label": "数量"},
        {"key": "disposition", "label": "处置"},
        {"key": "root_cause_category", "label": "根因分类"},
        {"key": "description", "label": "描述"},
        {"key": "created_at", "label": "时间"},
    ],
    "query_equipment": [
        {"key": "equipment_code", "label": "设备编号"},
        {"key": "equipment_name", "label": "设备名称"},
        {"key": "equipment_type", "label": "类型"},
        {"key": "status", "label": "状态"},
        {"key": "station_id", "label": "工位"},
    ],
}

# 工具结果中存放列表数据的字段名
_TABLE_LIST_KEY: Dict[str, str] = {
    "query_work_orders": "work_orders",
    "query_order_work_order_status": "orders",
    "query_inventory": "inventory",
    "query_pmc_material_supply": "items",
    "query_stagnant": "items",
    "query_pmc_rush_impact": "delayed_orders",
    "query_defects": "defects",
    "query_equipment": "equipment",
}

# 生产汇总 → 指标型表格（指标/数值 两列）
_SUMMARY_LABELS: Dict[str, str] = {
    "date": "日期",
    "today_good_output": "今日良品产出",
    "today_defect": "今日不良数",
    "yield_rate_pct": "良率(%)",
    "today_report_count": "今日报工次数",
    "active_work_orders": "在制工单",
    "pending_work_orders": "待开工单",
    "total_work_orders": "工单总数",
    "equipment_total": "设备总数",
    "equipment_running": "运行中设备",
    "equipment_fault": "故障设备",
    "equipment_utilization_pct": "设备利用率(%)",
}


def _extract_table_data(tool_name: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从查询工具结果中提取结构化表格数据，供前端渲染可交互表格/电子表格。

    返回 {title, columns: [{key, label}], rows: [{...}]} 或 None（不适用表格的工具）。
    """
    if tool_name in {
        "query_online_workbook", "edit_online_workbook", "recalculate_online_workbook",
        "reload_online_workbook", "create_online_pivot",
    }:
        table = result.get("table")
        if isinstance(table, dict) and table.get("columns"):
            return table
        return None

    # 指标汇总型 → 转为 指标/数值 两列表格
    if tool_name == "get_production_summary":
        rows = [
            {"metric": _SUMMARY_LABELS.get(k, k), "value": v}
            for k, v in result.items()
            if k != "error"
        ]
        if not rows:
            return None
        return {
            "title": "生产概况汇总",
            "columns": [{"key": "metric", "label": "指标"}, {"key": "value", "label": "数值"}],
            "rows": rows,
        }

    # 单条详情型 → 字段/值 两列表格
    if tool_name == "get_work_order_detail":
        label_map = {
            "work_order_code": "工单号", "product_name": "产品", "planned_qty": "计划数",
            "completed_qty": "完成数", "good_qty": "良品数", "defect_qty": "不良数",
            "scrap_qty": "报废数", "progress_pct": "进度(%)", "status": "状态",
            "priority": "优先级", "planned_due": "交期", "station_id": "工位",
            "routing_step": "当前工序", "created_at": "创建时间", "actual_start": "实际开工",
            "remark": "备注",
        }
        rows = [
            {"field": label_map.get(k, k), "value": v}
            for k, v in result.items()
            if k not in ("id", "product_id", "error") and v is not None
        ]
        if not rows:
            return None
        return {
            "title": f"工单详情 {result.get('work_order_code', '')}",
            "columns": [{"key": "field", "label": "字段"}, {"key": "value", "label": "值"}],
            "rows": rows,
        }

    if tool_name == "query_pmc_work_matrix":
        rows = result.get("matrix_rows")
        columns = result.get("matrix_columns")
        if not isinstance(rows, list) or not rows or not isinstance(columns, list):
            return None
        return {
            "type": "pmc_work_matrix",
            "title": result.get("title", "PMC 工作矩阵"),
            "columns": columns,
            "rows": rows,
            "work_order_code": (result.get("work_order") or {}).get("code"),
            "pmc_options": result.get("options") or {},
            "pmc_option_schema": result.get("option_schema") or [],
            "pmc_result": result,
        }

    if tool_name == "query_pmc_rush_impact":
        rows = (result.get("impact") or {}).get("delayed_orders") or []
        if not rows:
            return None
        return {
            "title": "PMC插单影响明细",
            "columns": _TABLE_COLUMNS["query_pmc_rush_impact"],
            "rows": rows,
        }

    if tool_name == "query_pmc_control_tower":
        facts = result.get("facts") or {}
        summary_fields = {
            "orders": [("APS实际排程订单", "scheduled_order_count"), ("MPS计划", "mps_plan_count"), ("工单", "work_order_count")],
            "materials": [("当前控制物料", "controlled_material_count"), ("库存SKU", "inventory_sku_count"), ("库存流水物料", "historical_transaction_material_count")],
            "shortage": [("受影响工单", "affected_work_order_count"), ("缺料物料", "shortage_material_count"), ("缺口合计", "total_shortage_qty")],
            "inventory": [("库存SKU", "sku_count"), ("可用库存", "available_qty"), ("呆滞物料", "stagnant_count")],
            "otd": [("到期订单", "due_order_count"), ("已完工", "completed_order_count"), ("OTD(%)", "otd_pct")],
            "capacity": [("负荷来源", "load_source")],
            "rush": [("插单审批", "approval_count"), ("已执行插单", "executed_count")],
            "engineering_change": [("ECN记录", "ecn_count"), ("ECN标记工单", "ecn_marked_work_order_count"), ("BOM版本组合", "bom_product_version_count")],
            "supplier_delay": [("PO", "po_count"), ("逾期PO", "overdue_count"), ("最大延迟天数", "max_delay_days")],
        }
        rows = []
        quality = {item.get("key"): item for item in result.get("data_quality") or []}
        for domain, fields in summary_fields.items():
            fact = facts.get(domain) or {}
            for metric, key in fields:
                rows.append({
                    "domain": domain,
                    "metric": metric,
                    "value": fact.get(key),
                    "data_status": (quality.get(domain) or {}).get("status", "unknown"),
                })
        if not rows:
            return None
        return {
            "title": "PMC控制塔事实汇总",
            "columns": [
                {"key": "domain", "label": "事实域"},
                {"key": "metric", "label": "指标"},
                {"key": "value", "label": "数值"},
                {"key": "data_status", "label": "数据状态"},
            ],
            "rows": rows,
        }

    # 列表型查询工具
    list_key = _TABLE_LIST_KEY.get(tool_name)
    columns = _TABLE_COLUMNS.get(tool_name)
    if not list_key or not columns:
        # ---- 流程知识工具：根据返回类型动态构建表格 ----
        if tool_name == "query_process_knowledge":
            return _extract_knowledge_table(result)
        return None
    items = result.get(list_key)
    if not isinstance(items, list) or not items:
        return None
    return {
        "title": TOOL_LABELS.get(tool_name, tool_name),
        "columns": columns,
        "rows": items,
    }


def _extract_diagram_data(tool_name: str, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract a deterministic flow diagram payload for the chatbot UI."""
    if tool_name != "query_workflow_diagram":
        return None
    diagram = result.get("diagram")
    if not isinstance(diagram, dict) or not diagram.get("nodes"):
        return None
    return diagram


def _collect_diagrams(actions: List[ToolAction]) -> List[Dict[str, Any]]:
    """Collect unique diagrams from executed tool actions for non-stream responses."""
    diagrams: List[Dict[str, Any]] = []
    seen_titles = set()
    for action in actions:
        diagram = _extract_diagram_data(action.tool, action.result)
        if not diagram:
            continue
        key = (diagram.get("title"), diagram.get("version"))
        if key in seen_titles:
            continue
        seen_titles.add(key)
        diagrams.append(diagram)
    return diagrams


def _extract_knowledge_table(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """流程知识查询结果 → 结构化表格（工单流/职位SOP/RACI/概览）。"""
    rtype = result.get("type", "")

    # 工单全生命周期 / 单阶段
    if rtype in ("work_order_flow", "work_order_stage"):
        stages = result.get("stages") or []
        if not stages:
            return None
        return {
            "title": result.get("title", "工单流程"),
            "columns": [
                {"key": "stage", "label": "阶段"},
                {"key": "status", "label": "状态"},
                {"key": "role", "label": "负责角色"},
                {"key": "actions", "label": "动作"},
                {"key": "blockpoint", "label": "卡点/异常处理"},
            ],
            "rows": stages,
        }

    # 职位 SOP → 步骤表
    if rtype == "position_sop":
        pos = result.get("position") or {}
        flow = pos.get("daily_flow") or []
        if not flow:
            return None
        rows = [
            {"step": s.get("step"), "task": s.get("task"), "detail": s.get("detail")}
            for s in flow
        ]
        return {
            "title": result.get("title", "职位SOP"),
            "columns": [
                {"key": "step", "label": "序号"},
                {"key": "task", "label": "任务"},
                {"key": "detail", "label": "说明"},
            ],
            "rows": rows,
        }

    # RACI 责任归属
    if rtype == "who_handles":
        raci = result.get("raci") or []
        if not raci:
            return None
        return {
            "title": result.get("title", "责任归属"),
            "columns": [
                {"key": "role", "label": "角色"},
                {"key": "responsibility", "label": "RACI"},
                {"key": "meaning", "label": "含义"},
            ],
            "rows": raci,
        }

    # 全阶段主要负责人
    if rtype == "who_handles_all":
        stages = result.get("stages") or []
        if not stages:
            return None
        return {
            "title": result.get("title", "各环节负责人"),
            "columns": [
                {"key": "stage", "label": "阶段"},
                {"key": "status", "label": "状态"},
                {"key": "primary_role", "label": "主要负责人"},
                {"key": "blockpoint", "label": "卡点处理"},
            ],
            "rows": stages,
        }

    # 职位概览
    if rtype == "position_overview":
        positions = result.get("positions") or []
        if not positions:
            return None
        return {
            "title": result.get("title", "职位概览"),
            "columns": [
                {"key": "position", "label": "职位"},
                {"key": "duties", "label": "核心职责"},
                {"key": "steps", "label": "SOP步骤数"},
            ],
            "rows": positions,
        }

    return None


# ==================== 流式输出（SSE） ====================

def _sse(event: str, data: Any) -> str:
    """格式化一条 SSE 帧。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _stream_llm_deltas(
    payload: Dict[str, Any],
    *,
    request_timeout: float,
):
    """调用网关 SSE，逐块返回 OpenAI delta。"""
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    stream_payload = {
        **payload,
        "stream": True,
        "cache": {"no-cache": True},
    }
    base_timeout = max(5.0, float(request_timeout))
    timeouts = (base_timeout, max(base_timeout, MODEL_COLD_START_RETRY_TIMEOUT))
    emitted_any = False
    for attempt, read_timeout in enumerate(timeouts, start=1):
        try:
            timeout = httpx.Timeout(
                read=read_timeout,
                connect=min(10.0, read_timeout),
                write=min(30.0, read_timeout),
                pool=min(10.0, read_timeout),
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{GATEWAY_URL}/v1/chat/completions",
                    json=stream_payload,
                    headers=headers,
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        raise RuntimeError(
                            f"gateway {resp.status_code}: {body[:300].decode(errors='replace')}"
                        )
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {}) or {}
                            if delta:
                                emitted_any = True
                            yield delta
                        except (json.JSONDecodeError, IndexError, KeyError):
                            continue
            return
        except httpx.ReadTimeout:
            if attempt >= len(timeouts) or emitted_any:
                raise
            _logger.warning(
                "[model-stream] cold-start timeout; retrying with extended read timeout=%ss",
                int(timeouts[1]),
            )
            await asyncio.sleep(0.25)


def _merge_stream_tool_calls(
    accumulated: Dict[int, Dict[str, Any]],
    deltas: List[Dict[str, Any]],
) -> None:
    """合并 OpenAI 流式 tool_calls 的分片。"""
    for item in deltas:
        index = int(item.get("index", 0))
        target = accumulated.setdefault(index, {
            "id": "",
            "type": "function",
            "function": {"name": "", "arguments": ""},
        })
        if item.get("id"):
            target["id"] = item["id"]
        if item.get("type"):
            target["type"] = item["type"]
        function_delta = item.get("function") or {}
        if function_delta.get("name"):
            target["function"]["name"] += function_delta["name"]
        if function_delta.get("arguments"):
            target["function"]["arguments"] += function_delta["arguments"]


async def _legacy_stream_disabled(
    request: ChatRequest,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE 流式对话：工具执行实时推送 action 事件，最终回复逐 token 流式输出。"""
    operator = current_user.username or current_user.id
    factory_id = _chat_factory_id(http_request, current_user)
    last_user = next(
        (m.content for m in reversed(request.messages) if m.role == "user"), ""
    )

    # Phase 3：会话持久化（新建/复用 session；done 事件回传 session_id）
    from core.kernel.permission import PermissionGate
    session = await _open_chat_session(
        db,
        factory_id=factory_id,
        user=current_user,
        session_id=request.session_id,
        title=last_user,
    )
    session_id = session.id
    round_started = time.monotonic()
    stream_request_id = f"req-{uuid.uuid4().hex[:12]}"
    # 生成器在首个 status 帧之后才真正开始执行；先初始化，保证客户端在冷启动/断开
    # 时进入 finally 也不会因为附件变量尚未赋值而跳过整轮落库。
    att_records: List[FileRecord] = []

    async def generate():
        actions: List[ToolAction] = []
        acc_reply = ""  # 累积最终答复（Phase 3 持久化用）
        stream_degraded = False
        permission_gate = PermissionGate()
        try:
            from core.auth.roles import get_user_permissions
            stream_permissions = get_user_permissions(current_user) or []
        except Exception:  # noqa: BLE001
            stream_permissions = []

        async def persist_stream_round(model: Optional[str] = None) -> None:
            """流式链路结束时写消息与 telemetry；落库失败不影响 SSE。"""
            from api.services.chat_persistence_service import (
                persist_round,
                save_telemetry,
            )
            try:
                await persist_round(
                    db,
                    session_id=session_id,
                    user_content=last_user or "（图片/附件消息）",
                    reply=acc_reply or "（本轮无文本回复）",
                    model=model,
                    actions=actions,
                    request_id=stream_request_id,
                    duration_ms=(time.monotonic() - round_started) * 1000,
                    attachment_ids=[str(record.id) for record in att_records],
                )
                await save_telemetry(
                    db,
                    request_id=stream_request_id,
                    session_id=session_id,
                    model=model,
                    tools_called=[a.tool for a in actions],
                    rounds=len(actions),
                    success=not stream_degraded,
                )
                # StreamingResponse 的依赖清理发生在响应结束后；如果只依赖 get_db
                # 的 finally commit，客户端断开/代理超时会留下 idle-in-transaction，
                # 后续同一会话的 updated_at 全部被锁住。每轮落库后立即提交，确保
                # 历史检索可见并释放连接锁。
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                _logger.exception(
                    "[chat-stream-persist] failed session=%s request=%s error=%s",
                    session_id,
                    stream_request_id,
                    type(exc).__name__,
                )
                await db.rollback()

        # 先发状态帧，避免大一点的表格解析期间代理/浏览器误判连接空闲。
        yield _sse("status", {"message": "正在读取表格附件…"})

        # ---- 加载附件 ----
        att_records = await _load_attachment_records(db, request.attachments, current_user) \
            if request.attachments else []
        image_records = [r for r in att_records if _is_image_record(r)]
        non_image_records = [r for r in att_records if not _is_image_record(r)]
        has_spreadsheet_attachment = any(_is_spreadsheet_record(r) for r in non_image_records)
        attachment_workbooks = await _ensure_attachment_workbooks(
            db,
            non_image_records,
            operator=operator,
            factory_id=factory_id,
        )
        spreadsheet_tables = await _load_spreadsheet_tables(
            non_image_records,
            workbooks=attachment_workbooks,
        )
        non_image_note = _attachment_text_note(
            non_image_records,
            spreadsheet_tables=spreadsheet_tables,
        )

        # Stream 是前端主链路；PMC九类问题在这里直接执行统一事实工具，保证不依赖模型是否正确选工具。
        direct_intent = (
            resolve_intent(last_user)
            if request.enable_tools and not image_records and not has_spreadsheet_attachment
            else None
        )
        if direct_intent and direct_intent.get("tool") == "query_pmc_control_tower":
            arguments = direct_intent.get("args") or {}
            result = await execute_tool(db, "query_pmc_control_tower", arguments, operator=operator, factory_id=factory_id)
            action = ToolAction(
                tool="query_pmc_control_tower",
                label=TOOL_LABELS["query_pmc_control_tower"],
                arguments=arguments,
                result=result,
                is_write=False,
                is_sim=False,
                success="error" not in result,
            )
            actions.append(action)
            acc_reply = _direct_tool_reply("query_pmc_control_tower", result)
            yield _sse("action", action.model_dump())
            table_data = _extract_table_data("query_pmc_control_tower", result)
            if table_data:
                yield _sse("table", table_data)
            yield _sse("delta", {"content": acc_reply})
            yield _sse("done", {
                "model": "pmc-control-tower",
                "degraded": "error" in result,
                "session_id": session_id,
                "request_id": stream_request_id,
            })
            await persist_stream_round("pmc-control-tower")
            return

        if direct_intent and direct_intent.get("tool") == "query_order_work_order_status":
            arguments = direct_intent.get("args") or {}
            result = await execute_tool(
                db,
                "query_order_work_order_status",
                arguments,
                operator=operator,
                factory_id=factory_id,
            )
            action = ToolAction(
                tool="query_order_work_order_status",
                label=TOOL_LABELS["query_order_work_order_status"],
                arguments=arguments,
                result=result,
                is_write=False,
                is_sim=False,
                success="error" not in result,
            )
            actions.append(action)
            acc_reply = _direct_tool_reply("query_order_work_order_status", result)
            yield _sse("action", action.model_dump())
            table_data = _extract_table_data("query_order_work_order_status", result)
            if table_data:
                yield _sse("table", table_data)
            yield _sse("delta", {"content": acc_reply})
            yield _sse("done", {
                "model": "order-work-order-status",
                "degraded": "error" in result,
                "session_id": session_id,
                "request_id": stream_request_id,
            })
            await persist_stream_round("order-work-order-status")
            return

        unsupported_attachment = _unsupported_attachment_message(
            non_image_records,
            spreadsheet_tables,
        )
        if unsupported_attachment and _is_attachment_analysis_request(last_user):
            acc_reply = unsupported_attachment
            yield _sse("delta", {"content": acc_reply})
            yield _sse("done", {
                "model": "attachment-parser",
                "degraded": False,
                "session_id": session_id,
                "request_id": stream_request_id,
            })
            await persist_stream_round("attachment-parser")
            return

        task_id = MODEL_STACK_VISION_TASK_ID if image_records else MODEL_STACK_CHAT_TASK_ID
        prompt_tokens = max(
            1,
            (sum(len(m.content or "") for m in request.messages) + len(non_image_note)) // 4,
        )
        try:
            route = await _resolve_model_route(task_id, prompt_tokens=prompt_tokens)
        except Exception as exc:  # noqa: BLE001
            stream_degraded = True
            acc_reply = _degraded_message(
                f"模型底座路由失败 ({type(exc).__name__})"
            )
            yield _sse("delta", {
                "content": acc_reply,
            })
            yield _sse("done", {
                "model": task_id,
                "degraded": True,
                "session_id": session_id,
                "request_id": stream_request_id,
            })
            await persist_stream_round(task_id)
            return

        # ---- Excel/CSV 附件 → 推送结构化表格事件（前端渲染可交互表格 + Univer 电子表格） ----
        for rec in att_records:
            if _is_spreadsheet_record(rec):
                tbl = spreadsheet_tables.get(str(rec.id))
                if tbl:
                    yield _sse("table", tbl)

        bound_workbook_id = next(
            (workbook.id for workbook in attachment_workbooks.values()),
            None,
        )
        workbook_context = (
            _workbook_context_prompt(bound_workbook_id)
            if spreadsheet_tables else _workbook_context_prompt(request.workbook_id)
        )
        tool_definitions = _chat_tool_definitions(
            has_spreadsheet_attachment=bool(spreadsheet_tables),
            workbook_id=bound_workbook_id,
            scope=factory_id,
        )
        # 所有文本意图统一交给模型解析；后端仅执行模型返回的 tool_calls。
        messages: List[Dict[str, Any]] = [{
            "role": "system",
            "content": SYSTEM_PROMPT + _attachment_analysis_context(
                bool(spreadsheet_tables), bound_workbook_id,
            ) + workbook_context,
        }]
        # ---- 智能体调度：指定 agent 时注入其职责提示词，并记录监督心跳 ----
        if request.agent_key:
            agent_prompt = build_agent_system_prompt(request.agent_key)
            if agent_prompt:
                messages.append({"role": "system", "content": agent_prompt})
                await record_agent_dispatch(db, factory_id, request.agent_key, last_user)
        history = await _build_chat_history(
            db,
            session_id=session_id,
            request_messages=request.messages,
        )
        _inject_chat_attachments(
            history,
            image_records=image_records,
            non_image_note=non_image_note,
            fallback_user_text=last_user,
        )
        messages += history

        payload: Dict[str, Any] = {
            "model": route["gateway_model"],
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": route["max_completion_tokens"],
        }
        # 图片内容由视觉任务模型做语义理解，不在业务侧做关键词分流。
        if not image_records and request.enable_tools and tool_definitions:
            payload["tools"] = tool_definitions
            payload["tool_choice"] = "auto"

        model_request_timeout = (
            max(route["request_timeout"], MODEL_COLD_START_RETRY_TIMEOUT)
            if spreadsheet_tables
            else route["request_timeout"]
        )
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                streamed_content: List[str] = []
                streamed_tool_calls: Dict[int, Dict[str, Any]] = {}
                async for delta in _stream_llm_deltas(
                    payload,
                    request_timeout=model_request_timeout,
                ):
                    text = delta.get("content") or ""
                    if text:
                        streamed_content.append(text)
                        acc_reply += text
                        yield _sse("delta", {"content": text})
                    _merge_stream_tool_calls(
                        streamed_tool_calls,
                        delta.get("tool_calls") or [],
                    )

                tool_calls = [
                    streamed_tool_calls[index]
                    for index in sorted(streamed_tool_calls)
                    if streamed_tool_calls[index]["function"]["name"]
                ]
                if not tool_calls:
                    if not streamed_content:
                        stream_degraded = True
                        acc_reply = _degraded_message("网关无有效回复")
                        yield _sse("delta", {"content": acc_reply})
                        yield _sse("done", {
                            "model": route["task_id"],
                            "degraded": True,
                            "session_id": session_id,
                            "request_id": stream_request_id,
                        })
                        return
                    yield _sse("done", {"model": route["task_id"], "degraded": False,
                                        "session_id": session_id,
                                        "request_id": stream_request_id})
                    return

                # 模型通过流协议下发工具调用，后端执行并实时推送 action。
                messages.append({
                    "role": "assistant",
                    "content": "".join(streamed_content),
                    "tool_calls": tool_calls,
                })
                for tc in tool_calls:
                    fn = tc.get("function", {}) or {}
                    tool_name = fn.get("name", "")
                    try:
                        arguments = json.loads(fn.get("arguments") or "{}")
                    except (json.JSONDecodeError, TypeError):
                        arguments = {}
                    permission_error = None
                    if stream_permissions:
                        permission_error = permission_gate.check(
                            tool_name=tool_name,
                            ctx=SimpleNamespace(user=current_user),
                            user_permissions=stream_permissions,
                            operator=operator,
                            factory_id=factory_id,
                        )
                    if permission_error:
                        result = {
                            "error": permission_error,
                            "permission_denied": True,
                        }
                    else:
                        result = await execute_tool(
                            db,
                            tool_name,
                            arguments,
                            operator=operator,
                            factory_id=factory_id,
                        )
                    is_error = "error" in result
                    action = ToolAction(
                        tool=tool_name,
                        label=TOOL_LABELS.get(tool_name, tool_name),
                        arguments=arguments,
                        result=result,
                        is_write=tool_name in WRITE_TOOLS,
                        is_sim=tool_name in SIM_TOOLS,
                        success=not is_error,
                    )
                    actions.append(action)
                    yield _sse("action", action.model_dump())
                    table_data = _extract_table_data(tool_name, result)
                    if table_data:
                        yield _sse("table", table_data)
                    diagram_data = _extract_diagram_data(tool_name, result)
                    if diagram_data:
                        yield _sse("diagram", diagram_data)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": _grounded_tool_result(result),
                    })

                # 最终回答直接流式生成。语义选择仍由首轮模型完成，业务层只提供工具事实。
                facts = [
                    {"tool": action.tool, "result": action.result}
                    for action in actions
                ]
                payload = {
                    "model": route["gateway_model"],
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                f"{FINAL_GROUNDING_PROMPT}"
                                "请根据用户问题和工具事实生成简洁、自然的中文答复，"
                                "只输出最终答复。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"用户问题：{last_user}\n"
                                f"工具事实：{json.dumps(facts, ensure_ascii=False, default=str)}"
                            ),
                        },
                    ],
                    "temperature": 0,
                    "max_tokens": route["max_completion_tokens"],
                }

            stream_degraded = True
            acc_reply = "操作轮次过多，已停止。请简化您的请求后重试。"
            yield _sse("delta", {"content": acc_reply})
            yield _sse("done", {"model": route["task_id"], "degraded": True,
                                "session_id": session_id,
                                "request_id": stream_request_id})
        except Exception as exc:  # noqa: BLE001
            stream_degraded = True
            yield _sse("delta", {"content": _degraded_message(f"网关连接失败 ({type(exc).__name__})")})
            yield _sse("done", {"model": route["task_id"], "degraded": True,
                                "session_id": session_id, "request_id": stream_request_id})
        finally:
            # Phase 3：本轮落库（user + assistant 草稿 + 工具轨迹 + telemetry）。
            await persist_stream_round(
                route.get("gateway_model") if "route" in locals() else None
            )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Kernel-backed SSE adapter.

    The browser event contract remains status/action/table/diagram/delta/done;
    execution and persistence are owned by the same Kernel path as /chat and
    /chat/v2.  The final reply is emitted as one delta when Kernel completes.
    """
    request_id = f"req-{uuid.uuid4().hex[:12]}"

    async def generate():
        yield _sse("status", {"message": "正在由统一 Chat Kernel 处理…"})
        try:
            result = await _handle_kernel_chat(
                request, http_request, db, current_user,
            )
            for action in result.actions:
                payload = action.model_dump() if hasattr(action, "model_dump") else action
                yield _sse("action", payload)
            for table in result.tables:
                yield _sse("table", table)
            for diagram in result.diagrams:
                yield _sse("diagram", diagram)
            if result.reply:
                yield _sse("delta", {"content": result.reply})
            yield _sse("done", {
                "model": result.model,
                "degraded": result.degraded,
                "session_id": result.session_id,
                "request_id": result.request_id or request_id,
                "memory": getattr(result, "memory", None),
            })
        except Exception as exc:  # noqa: BLE001
            _logger.exception("[chat-stream-kernel] failed request=%s", request_id)
            yield _sse("delta", {
                "content": _degraded_message(
                    f"统一 Chat Kernel 失败 ({type(exc).__name__})",
                ),
            })
            yield _sse("done", {
                "model": MODEL_STACK_CHAT_TASK_ID,
                "degraded": True,
                "session_id": request.session_id,
                "request_id": request_id,
            })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =================================================================
# 快速检索：用户自己的会话、文件、照片和历史引用
# =================================================================

@router.get("/search")
async def chat_search(
    q: str = "",
    kind: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 20,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search the current user's chat memory without exposing another tenant.

    A blank query returns recent items.  Text searches cover session titles,
    message content, uploaded filenames and attachment usage, so the frontend
    can let the user quote/reuse a previous photo or file in one click.
    """
    user_id = str(getattr(current_user, "id", "")) or current_user.username or "anonymous"
    factory_id = _chat_factory_id(http_request, current_user)
    query = (q or "").strip()
    pattern = f"%{query}%" if query else None
    page_limit = max(1, min(int(limit or 20), 100))
    session_filter = []
    if session_id:
        session_filter.append(ChatSession.id == session_id)

    session_stmt = (
        select(ChatSession)
        .where(
            ChatSession.user_id == user_id,
            ChatSession.factory_id == factory_id,
            *session_filter,
        )
        .order_by(ChatSession.updated_at.desc())
        .limit(page_limit)
    )
    if pattern:
        matching_message_sessions = select(ChatMessageRecord.session_id).where(
            ChatMessageRecord.content.ilike(pattern)
        )
        session_stmt = session_stmt.where(or_(
            ChatSession.title.ilike(pattern),
            ChatSession.id.in_(matching_message_sessions),
        ))
    sessions = (await db.execute(session_stmt)).scalars().all()

    message_stmt = (
        select(ChatMessageRecord, ChatSession)
        .join(ChatSession, ChatSession.id == ChatMessageRecord.session_id)
        .where(
            ChatSession.user_id == user_id,
            ChatSession.factory_id == factory_id,
            *([ChatSession.id == session_id] if session_id else []),
        )
        .order_by(ChatMessageRecord.created_at.desc(), ChatMessageRecord.id.desc())
        .limit(page_limit)
    )
    if pattern:
        message_stmt = message_stmt.where(ChatMessageRecord.content.ilike(pattern))
    message_rows = (await db.execute(message_stmt)).all()

    file_scope = [FileRecord.uploaded_by == current_user.username]
    if not current_user.is_superuser:
        file_scope.append(FileRecord.factory_id == factory_id)
    file_stmt = (
        select(FileRecord)
        .where(*file_scope)
        .order_by(FileRecord.created_at.desc())
        .limit(page_limit)
    )
    if kind in {"image", "file"}:
        if kind == "image":
            file_stmt = file_stmt.where(FileRecord.content_type.ilike("image/%"))
        else:
            file_stmt = file_stmt.where(~FileRecord.content_type.ilike("image/%"))
    if pattern:
        file_stmt = file_stmt.where(or_(
            FileRecord.filename.ilike(pattern),
            FileRecord.content_type.ilike(pattern),
        ))
    if session_id:
        linked_files = select(ChatMessageAttachment.file_id).where(
            ChatMessageAttachment.session_id == session_id
        )
        file_stmt = file_stmt.where(FileRecord.id.in_(linked_files))
    files = (await db.execute(file_stmt)).scalars().all()

    file_ids = [str(item.id) for item in files]
    usage_by_file: Dict[str, List[Dict[str, Any]]] = {file_id: [] for file_id in file_ids}
    if file_ids:
        usage_stmt = (
            select(ChatMessageAttachment, ChatMessageRecord, ChatSession)
            .join(ChatMessageRecord, ChatMessageRecord.id == ChatMessageAttachment.message_id)
            .join(ChatSession, ChatSession.id == ChatMessageAttachment.session_id)
            .where(
                ChatMessageAttachment.file_id.in_(file_ids),
                ChatSession.user_id == user_id,
                ChatSession.factory_id == factory_id,
            )
        )
        if session_id:
            usage_stmt = usage_stmt.where(ChatSession.id == session_id)
        for link, message, linked_session in (await db.execute(usage_stmt)).all():
            usage_by_file.setdefault(str(link.file_id), []).append({
                "session_id": linked_session.id,
                "session_title": linked_session.title or "新会话",
                "message_id": message.id,
                "message_excerpt": (message.content or "")[:160],
                "created_at": message.created_at.isoformat() if message.created_at else None,
            })

    def file_item(record: FileRecord) -> Dict[str, Any]:
        is_image = (record.content_type or "").startswith("image/")
        return {
            **record.to_dict(),
            "kind": "image" if is_image else "file",
            "is_image": is_image,
            "download_url": f"/api/v1/files/{record.id}",
            "preview_url": f"/api/v1/files/{record.id}" if is_image else None,
            "used_in": usage_by_file.get(str(record.id), []),
        }

    return {
        "query": query,
        "kind": kind,
        "session_id": session_id,
        "sessions": [
            {
                "session_id": item.id,
                "title": item.title or "新会话",
                "factory_id": item.factory_id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in sessions
        ],
        "messages": [
            {
                "message_id": message.id,
                "session_id": session.id,
                "session_title": session.title or "新会话",
                "role": message.role,
                "content": message.content or "",
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }
            for message, session in message_rows
        ],
        "files": [file_item(record) for record in files],
    }


# =================================================================
# Phase 6 — Engineering Surface（Trace / Replay / Eval / Plugins /
#           Version / Model-Compare / Failures）
# =================================================================

@router.get("/trace/{request_id}")
async def chat_trace(
    request_id: str,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """单次请求的完整执行链：会话 + 消息 + 遥测。"""
    from api.services.chat_persistence_service import ChatSessionAccessError, get_trace
    try:
        return await get_trace(
            db,
            request_id,
            user=current_user,
            factory_id=_chat_factory_id(http_request, current_user),
        )
    except ChatSessionAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/replay/{session_id}")
async def chat_replay(
    session_id: str,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """会话回放：按时间序返回全部消息（含工具轨迹）。"""
    from api.services.chat_persistence_service import ChatSessionAccessError, get_trace
    try:
        return await get_trace(
            db,
            None,
            session_id=session_id,
            user=current_user,
            factory_id=_chat_factory_id(http_request, current_user),
        )
    except ChatSessionAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/trajectory/{session_id}")
async def chat_trajectory(
    session_id: str,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """会话轨迹（DSH Trajectory 对齐）：从事件流组装注入/消息/工具/回复节点。"""
    from api.services.chat_persistence_service import ChatSessionAccessError, get_trajectory
    try:
        return await get_trajectory(
            db,
            session_id,
            user=current_user,
            factory_id=_chat_factory_id(http_request, current_user),
        )
    except ChatSessionAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/sessions")
async def chat_sessions(
    http_request: Request = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """当前用户在当前工厂的会话列表，供会话恢复 UI 使用。"""
    from api.services.chat_persistence_service import list_sessions

    return {
        "sessions": await list_sessions(
            db,
            user=current_user,
            factory_id=_chat_factory_id(http_request, current_user),
            limit=max(1, min(limit, 100)),
        )
    }


@router.get("/plugins")
async def chat_plugins():
    """Plugin Registry：当前注册的全部 Skill 及其工具。"""
    reg = _get_skill_registry()
    return {
        "plugins": [
            {
                "name": s.name,
                "module": s.module,
                "tools": s.tool_names(),
            }
            for s in reg.get_all()
        ],
        "tool_count": len(reg.all_tool_definitions()),
    }


@router.get("/version")
async def chat_version():
    """Harness 版本信息（与路由端点同时暴露完整能力面）。"""
    from core.kernel import __version__ as harness_version
    from core.agent import event_bus as event_bus_mod
    return {
        "harness": harness_version,
        "api": "/api/v1/chat (and /v2, /stream)",
        "phases": [1, 2, 3, 4, 5, 6],
        "event_bus": event_bus_mod.__file__,
        "execution": "HarnessKernel",
        "skill_registry": len(_get_skill_registry().all_tool_definitions()),
    }


@router.get("/failures")
async def chat_failures(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """失败分析：聚合最近失败请求（进程内 ring + DB 遥测）。"""
    from core.kernel.telemetry import Telemetry
    mem = Telemetry.get_instance().failures(limit)

    stmt = (
        select(ChatTelemetry)
        .where(ChatTelemetry.success == False)  # noqa: E712
        .order_by(ChatTelemetry.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    db_failures = [
        {
            "request_id": t.request_id,
            "phase": t.phase,
            "error": t.error,
            "model": t.model,
            "duration_ms": float(t.duration_ms or 0),
            "created_at": t.created_at.strftime("%Y-%m-%d %H:%M:%S") if t.created_at else None,
        }
        for t in rows
    ]
    return {"db": db_failures, "memory": mem}


class EvalRunRequest(BaseModel):
    prompt: str
    expected_tool: Optional[str] = None
    expected_reply_keyword: Optional[str] = None
    model: Optional[str] = None
    factory_id: str = "F01"


@router.post("/eval")
async def chat_eval_run(
    request: EvalRunRequest,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量评估单个用例：发起一次 Kernel 执行并返回通过/失败 + 证据链。

    Phase 6 简化版：逐 case 跑 /v2 同款链路（不依赖会话），输出结构化结果。
    """
    from core.kernel import HarnessKernel
    from core.kernel.model_review import ModelReviewer
    from core.kernel.permission import PermissionGate

    operator = current_user.username or current_user.id
    factory_id = request.factory_id
    model_task_id = request.model or MODEL_STACK_CHAT_TASK_ID

    async def bound_execute(tool_name, arguments):
        from api.services.chat_tools_service import execute_tool as exec_tool
        return await exec_tool(db, tool_name, arguments, operator=operator, factory_id=factory_id)

    kernel = HarnessKernel(
        db=db,
        call_llm=_call_llm,
        resolve_model_route=_route_resolver_for(model_task_id),
        execute_tool=bound_execute,
        clean_reply=_clean_model_reply,
        ground_tool_result=_grounded_tool_result,
        verify_reply=None,
        make_tool_action=lambda tool, label, args, res, is_w, is_s, ok: {
            "tool": tool, "success": ok,
        },
        write_tools=frozenset(WRITE_TOOLS),
        sim_tools=frozenset(SIM_TOOLS),
        tool_definitions=TOOL_DEFINITIONS,
        system_prompt=SYSTEM_PROMPT,
        final_grounding_prompt=FINAL_GROUNDING_PROMPT,
        chat_task_id=model_task_id,
        vision_task_id=MODEL_STACK_VISION_TASK_ID,
        max_tool_rounds=MAX_TOOL_ROUNDS,
        skill_registry=_get_skill_registry(),
        legacy_execute_tool=bound_execute,
        permission_gate=PermissionGate(),
        model_reviewer=ModelReviewer(call_llm=_call_llm, clean_reply=_clean_model_reply),
        **_checkpoint_options(),
    )
    ctx = await kernel.build_context(
        factory_id=factory_id, user=current_user,
        messages=[{"role": "user", "content": request.prompt}],
        prompt_tokens=max(1, len(request.prompt) // 4),
    )
    import time
    started = time.monotonic()
    result = await kernel.handle(ctx)
    elapsed_ms = (time.monotonic() - started) * 1000

    called_tools = [a.tool if isinstance(a, dict) else getattr(a, "tool", "") for a in result.actions]
    tool_ok = (request.expected_tool is None) or (request.expected_tool in called_tools)
    keyword_ok = (request.expected_reply_keyword is None) or (
        request.expected_reply_keyword in result.reply
    )
    passed = bool(tool_ok and keyword_ok and not result.degraded)

    # 记录评估用例（供后续聚合）
    case = ChatEvalCase(
        name=f"eval-{request.prompt[:40]}", prompt=request.prompt,
        expected_tool=request.expected_tool,
        expected_reply_keyword=request.expected_reply_keyword,
        model=request.model, factory_id=factory_id,
    )
    db.add(case)

    return {
        "passed": passed,
        "reply": result.reply,
        "tools_called": called_tools,
        "expected_tool": request.expected_tool,
        "expected_reply_keyword": request.expected_reply_keyword,
        "duration_ms": round(elapsed_ms, 1),
        "request_id": result.request_id,
        "review": result.telemetry.get("review"),
    }


class ModelCompareRequest(BaseModel):
    prompt: str
    models: List[str]
    factory_id: str = "F01"


@router.post("/model-compare")
async def chat_model_compare(
    request: ModelCompareRequest,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """模型对比：同一 prompt 分别路由到多个模型，返回各自的回复与耗时。"""
    results = []
    for model_task_id in request.models:
        try:
            route = await _resolve_model_route(model_task_id, prompt_tokens=max(1, len(request.prompt) // 4))
            payload = {
                "model": route.get("gateway_model"),
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": request.prompt},
                ],
                "temperature": 0.2,
                "max_tokens": route.get("max_completion_tokens", 768),
                "_task_id": model_task_id,
            }
            import httpx as _httpx
            timeout = float(route.get("request_timeout", REQUEST_TIMEOUT))
            async with _httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{GATEWAY_URL}/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {API_KEY}"} if API_KEY else {},
                )
            status = resp.status_code
            if status >= 400:
                results.append({"model": model_task_id, "status": status, "reply": "", "error": "gateway_error"})
                continue
            data = resp.json()
            reply = (data.get("choices", [{}])[0].get("message", {}).get("content", ""))
            results.append({"model": model_task_id, "status": status, "reply": reply})
        except Exception as exc:  # noqa: BLE001
            results.append({"model": model_task_id, "status": 0, "reply": "", "error": str(exc)})
    return {"prompt": request.prompt, "results": results}


def _route_resolver_for(task_id: str):
    """生成解析指定任务路由的闭包（供 eval 与 v2 同源）。"""
    async def _resolve(_task_id: str, prompt_tokens: int = 1000):
        return await _resolve_model_route(_task_id, prompt_tokens=prompt_tokens)
    return _resolve


__all__ = ["router"]
