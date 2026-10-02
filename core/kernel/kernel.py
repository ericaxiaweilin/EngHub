"""HarnessKernel - Chat V2 编排内核。

将一次 Chat V2 请求收敛为：
    1. 解析 context（工厂 / 用户 / 权限 / 模型路由）
    2. 权限门控（Phase 1 基础版：读/写工具开关）
    3. Agent Loop 执行（含 checkpoint 断点）
    4. Telemetry 上报
    5. 返回结构化 KernelResponse

依赖通过构造函数注入，路由层负责组装（见 chat_routes.py 的 /chat/v2）。
"""

from __future__ import annotations

import inspect
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.kernel.context import KernelContext
from core.kernel.agent_loop import AgentLoop, LoopResult
from core.kernel.checkpoint import CheckpointManager
from core.kernel.events import (
    EventPersistFn,
    HarnessEvent,
    get_harness_event_bus,
    new_item_id,
)
from core.kernel.telemetry import Telemetry
from core.kernel.plugins import HarnessPluginRegistry, get_harness_plugin_registry

_logger = logging.getLogger("engflow_kernel")


@dataclass
class KernelResponse:
    """Kernel 对外输出，语义与 V1 ChatResponse 对齐。"""

    reply: str
    model: str = ""
    degraded: bool = False
    actions: List[Any] = field(default_factory=list)
    diagrams: List[Dict[str, Any]] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    request_id: str = ""
    status: str = "complete"
    telemetry: Dict[str, Any] = field(default_factory=dict)


class HarnessKernel:
    """Chat V2 编排内核。

    Args:
        db: AsyncSession（透传给工具执行）
        call_llm: LLM 调用函数（同 AgentLoop）
        resolve_model_route: 异步函数 (task_id, prompt_tokens) -> route dict
        execute_tool: 工具执行函数 (tool_name, arguments) -> dict
        clean_reply / ground_tool_result / verify_reply: 文本处理函数
        make_tool_action: 构造 ToolAction
        write_tools / sim_tools: 写/仿真工具集合
        tool_definitions: OpenAI 工具定义列表
        system_prompt / final_grounding_prompt: 提示词
        chat_task_id / vision_task_id: 模型任务 id
    """

    def __init__(
        self,
        *,
        db: Any,
        call_llm: Callable[[Dict[str, Any]], Awaitable[Any]],
        resolve_model_route: Callable[..., Awaitable[Dict[str, Any]]],
        execute_tool: Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]],
        clean_reply: Callable[[str], str],
        ground_tool_result: Callable[[Dict[str, Any]], str],
        verify_reply: Optional[Callable[..., Awaitable[str]]] = None,
        make_tool_action: Optional[Callable[..., Any]] = None,
        write_tools: Optional[frozenset] = None,
        sim_tools: Optional[frozenset] = None,
        tool_definitions: Optional[List[Dict[str, Any]]] = None,
        system_prompt: str = "",
        final_grounding_prompt: str = "",
        chat_task_id: str = "",
        vision_task_id: str = "",
        max_tool_rounds: int = 5,
        telemetry: Optional[Telemetry] = None,
        skill_registry: Any = None,
        legacy_execute_tool: Optional[Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]] = None,
        persist_hook: Optional[Callable[[KernelContext, "KernelResponse"], Awaitable[None]]] = None,
        permission_gate: Any = None,
        model_reviewer: Any = None,
        checkpoint_manager: Optional[CheckpointManager] = None,
        checkpoint_session_factory: Optional[Callable[[], Any]] = None,
        checkpoint_persistence_enabled: bool = False,
        deterministic_handler: Optional[Callable[..., Awaitable[Optional[KernelResponse]]]] = None,
        event_persist: Optional[EventPersistFn] = None,
        event_commit: Optional[Callable[[], Awaitable[None]]] = None,
        event_listener: Optional[Callable[[HarnessEvent], Awaitable[None]]] = None,
        approval_manager: Any = None,
        interactive_approval: bool = False,
        stream_llm: Any = None,
        plugin_registry: Optional[HarnessPluginRegistry] = None,
    ) -> None:
        self.db = db
        self._active_ctx = None
        self._persist_hook = persist_hook
        self._deterministic_handler = deterministic_handler
        self._event_persist = event_persist
        self._event_commit = event_commit
        self._event_listener = event_listener
        self._event_bus = get_harness_event_bus()
        self._approval_manager = approval_manager
        self._interactive_approval = interactive_approval
        self._stream_llm = stream_llm
        # Plugins are an extension seam, not a second execution loop.  The
        # default registry is process-wide so HTTP, SSE and App Server clients
        # observe the same mounted capabilities and lifecycle hooks.
        self._plugins = plugin_registry or get_harness_plugin_registry()
        self._write_tools = write_tools or frozenset()
        self._permission_gate = permission_gate
        self._model_reviewer = model_reviewer
        self._resolve_model_route = resolve_model_route
        self._tool_definitions = tool_definitions or []
        self._system_prompt = system_prompt
        self._final_grounding_prompt = final_grounding_prompt
        self._chat_task_id = chat_task_id
        self._vision_task_id = vision_task_id
        self._max_tool_rounds = max_tool_rounds
        self._telemetry = telemetry or Telemetry.get_instance()
        self._checkpoints = checkpoint_manager or CheckpointManager(
            session_factory=checkpoint_session_factory,
            persistence_enabled=checkpoint_persistence_enabled,
        )
        self._skill_registry = skill_registry
        self._make_tool_action = make_tool_action
        self._execute_tool_without_registry = execute_tool
        # execute_tool 统一走 _skill_execute_tool：始终先做权限门控。
        # 当注册表存在时，所有已注册工具都必须经过 Skill；旧执行器只在
        # 调用方显式传入 legacy_execute_tool 时作为迁移期兼容层存在。
        self._legacy_execute_tool = legacy_execute_tool

        async def call_llm_with_plugins(payload: Dict[str, Any]) -> Any:
            return await self._invoke_model_request(call_llm, payload)

        async def stream_llm_with_plugins(payload: Dict[str, Any]):
            async for chunk in self._stream_model_request(stream_llm, payload):
                yield chunk

        self._loop = AgentLoop(
            call_llm=call_llm_with_plugins,
            execute_tool=self._skill_execute_tool,
            clean_reply=clean_reply,
            ground_tool_result=ground_tool_result,
            # ModelReviewer 接管审校时，跳过 AgentLoop 内部 verify（避免重复 LLM 调用）
            verify_reply=None if model_reviewer is not None else verify_reply,
            make_tool_action=make_tool_action,
            write_tools=write_tools,
            sim_tools=sim_tools,
            final_grounding_prompt=final_grounding_prompt,
            max_rounds=max_tool_rounds,
            stream_llm=stream_llm_with_plugins if stream_llm is not None else None,
        )

    # ── 公开入口 ──

    async def handle(self, ctx: KernelContext) -> KernelResponse:
        request_id = ctx.request_id
        self._active_ctx = ctx
        await self._dispatch_plugin(
            "turn/start",
            {"context": ctx, "request_id": request_id, "session_id": ctx.session_id},
        )
        await self._emit_event(
            ctx,
            "turn/started",
            {
                "status": "in_progress",
                "thread_id": ctx.session_id or request_id,
                "turn_id": request_id,
                "goal_id": ctx.goal_id,
                "goal": ctx.goal,
            },
        )
        try:
            with self._telemetry.timed(request_id, "total") as _timer:
                pre_step = await self._dispatch_plugin(
                    "agent/pre-step",
                    {"context": ctx, "request_id": request_id},
                )
                # A plugin may enrich the next model-visible request through
                # the same context object, without importing AgentLoop.
                injected = pre_step.get("messages")
                if isinstance(injected, list):
                    ctx.messages = injected
                # Clear, deterministic business intents (for example PMC control
                # tower facts) can bypass an unnecessary model round while still
                # using the exact same permission, persistence and response path.
                if self._deterministic_handler is not None:
                    if ctx.cancel_check is not None and ctx.cancel_check():
                        response = KernelResponse(
                            reply="本轮已取消，未继续执行。",
                            model=ctx.model_route.get("gateway_model", ""),
                            degraded=True,
                            request_id=request_id,
                            status="cancelled",
                        )
                        await self._emit_response_events(ctx, response)
                        await self._dispatch_plugin(
                            "turn/end", {"context": ctx, "response": response},
                        )
                        await self._commit_events(request_id)
                        return response
                    direct_response = await self._deterministic_handler(
                        ctx, self._skill_execute_tool, self._make_tool_action,
                    )
                    if direct_response is not None:
                        if self._persist_hook is not None:
                            try:
                                await self._persist_hook(ctx, direct_response)
                            except Exception:  # noqa: BLE001
                                _logger.exception(
                                    "[kernel] persist hook failed for %s", request_id,
                                )
                        await self._emit_response_events(ctx, direct_response)
                        await self._dispatch_plugin(
                            "turn/end", {"context": ctx, "response": direct_response},
                        )
                        await self._commit_events(request_id)
                        return direct_response

                # 1) 构建 payload（含 system prompt / 工具定义 / 路由）
                payload = self._build_payload(ctx)

                # 2) 工具级权限门控在 _skill_execute_tool / legacy 执行前逐工具校验

                # 3) Agent Loop（每轮工具执行后保存 checkpoint）
                loop_result = await self._loop.run(
                    payload,
                    request_id=request_id,
                    checkpoint=self._checkpoints,
                    event_callback=(
                        lambda event_type, data, item_id=None: self._emit_event(
                            ctx, event_type, data, item_id=item_id,
                        )
                    ),
                    cancel_check=ctx.cancel_check,
                    cancel_wait=ctx.cancel_wait,
                    steer_drain=ctx.steer_drain,
                )
                ctx.checkpoint_key = (
                    loop_result.checkpoint_key
                    or (self._checkpoints.latest(request_id)["key"]
                        if self._checkpoints.has(request_id) else None)
                )
                if loop_result.restored_from_checkpoint:
                    ctx.metadata["checkpoint_restored"] = True

                # 4) 组装响应（可选 ModelReview 替换草稿）
                reply = loop_result.reply
                review_result = None
                if self._model_reviewer is not None and loop_result.actions:
                    review_result = await self._model_reviewer.review(
                        reply, loop_result.actions,
                        loop_result.model or ctx.model_route.get("gateway_model", ""),
                    )
                    reply = review_result.revised_reply
                    ctx.metadata["model_review"] = review_result.to_dict()

                response = KernelResponse(
                    reply=reply,
                    model=loop_result.model or ctx.model_route.get("gateway_model", ""),
                    degraded=loop_result.degraded,
                    actions=loop_result.actions,
                    diagrams=loop_result.diagrams,
                    request_id=request_id,
                    status=loop_result.status,
                )
                if review_result is not None:
                    response.telemetry["review"] = review_result.to_dict()

                # 5) 会话持久化（Phase 3：写消息 + 遥测，失败不阻断响应）
                if self._persist_hook is not None:
                    try:
                        await self._persist_hook(ctx, response)
                    except Exception:  # noqa: BLE001
                        _logger.exception("[kernel] persist hook failed for %s", request_id)

                await self._emit_response_events(ctx, response)
                await self._dispatch_plugin(
                    "turn/end", {"context": ctx, "response": response},
                )
                await self._commit_events(request_id)
                return response
        except Exception as exc:  # noqa: BLE001
            _logger.exception("[kernel] request %s failed", request_id)
            self._telemetry.record(
                self._telemetry_trace_event(
                    ctx, phase="total", success=False, error=str(exc)
                )
            )
            response = KernelResponse(
                reply=f"Chat V2 处理失败（{type(exc).__name__}）",
                model=ctx.model_route.get("gateway_model", ""),
                degraded=True,
                request_id=request_id,
                status="failed",
            )
            await self._emit_response_events(ctx, response, status="failed")
            await self._dispatch_plugin(
                "turn/error", {"context": ctx, "response": response, "error": exc},
            )
            await self._commit_events(request_id)
            return response

    async def _dispatch_plugin(
        self, event: str, payload: Dict[str, Any], *, strict: bool = False,
    ) -> Dict[str, Any]:
        """Dispatch an optional plugin hook without creating a second loop."""
        if self._plugins is None:
            return payload
        try:
            return await self._plugins.dispatch(event, payload, strict=strict)
        except Exception:  # noqa: BLE001
            _logger.exception("[kernel] plugin hook failed: %s", event)
            return payload

    async def _invoke_model_request(
        self,
        call_llm: Callable[[Dict[str, Any]], Awaitable[Any]],
        payload: Dict[str, Any],
    ) -> Any:
        """Expose the model seam to plugins while keeping one AgentLoop."""
        prepared = await self._dispatch_plugin(
            "agent/request",
            {"context": self._active_ctx, "payload": payload},
        )
        request_payload = prepared.get("payload", payload)
        return await call_llm(request_payload)

    async def _stream_model_request(
        self,
        stream_llm: Callable[[Dict[str, Any]], Any],
        payload: Dict[str, Any],
    ):
        prepared = await self._dispatch_plugin(
            "agent/request",
            {"context": self._active_ctx, "payload": payload},
        )
        request_payload = prepared.get("payload", payload)
        stream = stream_llm(request_payload)
        if inspect.isawaitable(stream):
            stream = await stream
        async for chunk in stream:
            yield chunk

    async def _commit_events(self, request_id: str) -> None:
        """Flush terminal lifecycle events after they are appended.

        The compatibility message projection is committed before the final
        ``item/completed``/``turn/*`` events are emitted.  A second, isolated
        commit closes that small durability gap without allowing a database
        commit failure to change the already-built chat response.
        """
        if self._event_commit is None:
            return
        try:
            await self._event_commit()
        except Exception:  # noqa: BLE001
            _logger.exception("[kernel] terminal event commit failed for %s", request_id)

    async def _emit_event(
        self,
        ctx: KernelContext,
        event_type: str,
        data: Dict[str, Any],
        *,
        item_id: Optional[str] = None,
    ) -> HarnessEvent:
        """Publish a Thread/Turn/Item event without affecting execution."""
        event = await self._event_bus.emit(
            session_id=ctx.session_id or ctx.request_id,
            request_id=ctx.request_id,
            event_type=event_type,
            data=data,
            item_id=item_id,
            persist=self._event_persist,
        )
        if self._event_listener is not None:
            try:
                await self._event_listener(event)
            except Exception:  # noqa: BLE001
                _logger.debug("[kernel] event listener unavailable", exc_info=True)
        return event

    async def _emit_response_events(
        self,
        ctx: KernelContext,
        response: KernelResponse,
        *,
        status: Optional[str] = None,
    ) -> None:
        response_status = status or response.status or ("degraded" if response.degraded else "complete")
        await self._emit_event(
            ctx,
            "item/completed",
            {
                "item_type": "assistant_message",
                "status": response_status,
                "content": response.reply,
                "model": response.model,
                "action_count": len(response.actions),
            },
            item_id=new_item_id("message"),
        )
        await self._emit_event(
            ctx,
            (
                "turn/cancelled"
                if response_status == "cancelled"
                else "turn/failed" if response.degraded else "turn/completed"
            ),
            {
                "status": response_status,
                "degraded": response.degraded,
                "model": response.model,
                "action_count": len(response.actions),
                "goal_id": ctx.goal_id,
            },
        )

    # ── 内部步骤 ──

    def _build_payload(self, ctx: KernelContext) -> Dict[str, Any]:
        """构造 LLM 请求体。与原 chat() 的 payload 组装逻辑对齐。"""
        has_images = bool(
            ctx.attachments
            and any(getattr(a, "content_type", "").startswith("image/") for a in ctx.attachments)
        )
        task_id = self._vision_task_id if has_images else self._chat_task_id
        route = ctx.model_route

        system_prompt = self._system_prompt
        if ctx.goal:
            goal_metrics = ctx.goal.get("metrics") or []
            metric_line = ""
            if goal_metrics:
                metric_line = "\n业务指标：" + "；".join(
                    f"{item.get('label', item.get('metric_code'))}={item.get('current_value', '—')}"
                    f"{('/目标' + str(item.get('target_value'))) if item.get('target_value') is not None else ''}"
                    f"[{item.get('status', 'unknown')}]"
                    for item in goal_metrics[:12]
                )
            system_prompt += (
                "\n【当前线程 Goal】\n"
                f"目标：{ctx.goal.get('objective', '')}\n"
                f"状态：{ctx.goal.get('status', 'active')}；进度：{ctx.goal.get('progress_pct', 0)}%\n"
                f"{metric_line}\n"
                "本轮应围绕该目标推进；若信息不足，明确指出下一步和验证标准。"
            )
        messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        messages += ctx.messages

        payload: Dict[str, Any] = {
            "model": route.get("gateway_model"),
            "messages": messages,
            "temperature": ctx.temperature,
            "max_tokens": route.get("max_completion_tokens", 1024),
        }
        if not has_images and ctx.enable_tools and self._tool_definitions:
            payload["tools"] = self._tool_definitions
            payload["tool_choice"] = "auto"
        payload["_task_id"] = task_id
        payload["_request_timeout"] = route.get("request_timeout", 60.0)
        return payload

    def _telemetry_trace_event(self, ctx: KernelContext, **kwargs: Any):
        from core.kernel.telemetry import TelemetryEvent

        return TelemetryEvent(
            request_id=ctx.request_id,
            model=ctx.model_route.get("gateway_model", ""),
            provider=ctx.model_route.get("provider", ""),
            task_id=ctx.model_route.get("task_id", ""),
            **kwargs,
        )

    async def _skill_execute_tool(
        self, tool_name: str, arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """execute_tool 的 Skill 优先版本。

        - 权限门控：不通过 → 返回拒绝结果（不执行）
        - 注册表有该工具 → 走 Skill
        - Skill 返回 LEGACY_FALLBACK 哨兵 → 仅在显式配置时回退 legacy
        - 注册表无该工具 → 返回未知工具；不再暗中穿透到旧执行器
        """
        from core.skills.registry import is_legacy_fallback

        active = self._active_ctx
        hook_payload = await self._dispatch_plugin(
            "tools/pre-execute",
            {
                "context": active,
                "tool": tool_name,
                "arguments": dict(arguments),
            },
        )
        if isinstance(hook_payload.get("arguments"), dict):
            arguments = hook_payload["arguments"]

        async def finish(result: Dict[str, Any]) -> Dict[str, Any]:
            payload = await self._dispatch_plugin(
                "tools/post-execute",
                {
                    "context": active,
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": result,
                },
            )
            return payload.get("result", result) if isinstance(payload.get("result"), dict) else result

        gate_error = self._check_permission(tool_name, arguments, active)
        if gate_error:
            return await finish({"error": gate_error, "permission_denied": True})

        if (
            self._interactive_approval
            and self._approval_manager is not None
            and tool_name in self._write_tools
            and active is not None
        ):
            approval = await self._approval_manager.request(
                user_id=str(getattr(active.user, "id", "") or getattr(active.user, "username", "")),
                factory_id=active.factory_id,
                session_id=active.session_id or active.request_id,
                request_id=active.request_id,
                tool=tool_name,
                arguments=arguments,
                cancel_check=active.cancel_check,
                cancel_wait=active.cancel_wait,
                notify=lambda data: self._emit_event(
                    active,
                    "approval/request" if data.get("status") == "pending" else "approval/response",
                    data,
                    item_id=data.get("approval_id"),
                ),
            )
            if not approval.get("approved"):
                return await finish({
                    "error": approval.get("reason") or "写操作未获批准",
                    "approval_denied": True,
                    "approval": approval,
                })

        if self._skill_registry is not None:
            if self._skill_registry.has_tool(tool_name):
                operator = active.operator if active else "ai_assistant"
                factory_id = active.factory_id if active else None
                result = await self._skill_registry.execute(
                    tool_name, arguments,
                    db=self.db, operator=operator,
                    factory_id=factory_id,
                    ctx=active,
                )
                if not is_legacy_fallback(result):
                    return await finish(result)
            else:
                return await finish({"error": f"未知工具：{tool_name}"})
        if self._legacy_execute_tool is not None:
            return await finish(await self._legacy_execute_tool(tool_name, arguments))
        if self._skill_registry is None:
            return await finish(await self._execute_tool_without_registry(tool_name, arguments))
        return await finish({"error": f"工具尚未迁移：{tool_name}"})

    def _check_permission(
        self, tool_name: str, arguments: Dict[str, Any], ctx: Optional[KernelContext],
    ) -> Optional[str]:
        """权限门控：基于用户权限集 + 作用域。未配置 gate 时不拦截。"""
        if self._permission_gate is None or ctx is None:
            return None
        from core.auth.roles import get_user_permissions
        user_perm_list = []
        try:
            perms = get_user_permissions(ctx.user) or []
        except Exception:  # noqa: BLE001
            perms = []
        if not perms:
            user_perm_list = list(getattr(ctx, "permissions", set()) or [])
            if not user_perm_list:
                # 无权限集信息：不硬拦截（V2 前端可能不上权限），交由后续阶段收紧
                return None
            perms = user_perm_list
        return self._permission_gate.check(
            tool_name=tool_name, ctx=ctx, user_permissions=perms,
            operator=ctx.operator, factory_id=ctx.factory_id,
        )

    # ── 供路由层使用的辅助 ──

    async def build_context(
        self,
        *,
        factory_id: str,
        user: Any,
        messages: List[Dict[str, Any]],
        attachments: Optional[List[Any]] = None,
        enable_tools: bool = True,
        agent_key: Optional[str] = None,
        temperature: float = 0.3,
        session_id: Optional[str] = None,
        goal_id: Optional[str] = None,
        goal: Optional[Dict[str, Any]] = None,
        permissions: Optional[set] = None,
        prompt_tokens: int = 1000,
        resolve_route: bool = True,
        request_id: Optional[str] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        cancel_wait: Optional[Callable[[], Awaitable[None]]] = None,
        steer_drain: Optional[Callable[[], Awaitable[List[Dict[str, Any]]]]] = None,
    ) -> KernelContext:
        """路由层构建 KernelContext（含模型路由解析）。"""
        request_id = request_id or f"req-{uuid.uuid4().hex[:12]}"
        has_images = bool(
            attachments
            and any(getattr(a, "content_type", "").startswith("image/") for a in attachments)
        )
        task_id = self._vision_task_id if has_images else self._chat_task_id
        if resolve_route:
            route = await self._resolve_model_route(task_id, prompt_tokens=prompt_tokens)
        else:
            # Deterministic handlers (and parser-only attachment responses) do
            # not need a model route.  Keeping a shape-compatible route lets
            # them use the same KernelContext/telemetry/persistence contract
            # while remaining available during a cold or unavailable gateway.
            route = {
                "task_id": task_id,
                "provider": "deterministic",
                "gateway_model": "",
                "request_timeout": 0.0,
                "max_completion_tokens": 1,
            }
        # 若调用方未显式传入权限集，则由用户角色推导（Phase 4）
        if not permissions:
            try:
                from core.auth.roles import get_user_permissions
                permissions = set(str(p) for p in get_user_permissions(user))
            except Exception:  # noqa: BLE001
                permissions = set()
        return KernelContext(
            request_id=request_id,
            factory_id=factory_id,
            user=user,
            messages=messages,
            model_route=route,
            session_id=session_id,
            goal_id=goal_id,
            goal=goal,
            attachments=attachments,
            enable_tools=enable_tools,
            agent_key=agent_key,
            temperature=temperature,
            permissions=permissions or set(),
            operator=getattr(user, "username", "") or str(getattr(user, "id", "")),
            cancel_check=cancel_check,
            cancel_wait=cancel_wait,
            steer_drain=steer_drain,
        )
