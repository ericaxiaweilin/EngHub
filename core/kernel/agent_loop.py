"""AgentLoop - 工具调用循环（从 chat_routes.py 抽取，行为保持等价）。

依赖注入：LLM 调用、工具执行、清理/校验函数均由构造方传入，循环本身不
触碰任何全局状态，便于独立单测与后续扩展（Skills / Model Adapters）。

与原实现差异：
- 原实现把 agent loop 内联在 chat() 端点里，与 HTTP/路由耦合。
- 这里将循环收敛为纯 async 函数，输入 KernelContext，输出 LoopResult。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.kernel.checkpoint import CheckpointManager
from core.kernel.events import new_item_id

MAX_TOOL_ROUNDS = 5


@dataclass
class LoopResult:
    """Agent Loop 一次执行的输出。"""

    reply: str = ""
    model: str = ""
    degraded: bool = False
    rounds_used: int = 0
    actions: List[Any] = field(default_factory=list)
    diagrams: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "complete"  # complete | cancelled | no_reply | max_rounds | gateway_error | tool_error | exception
    error: Optional[str] = None
    checkpoint_key: Optional[str] = None
    restored_from_checkpoint: bool = False


# 类型别名：外部注入的能力
LlmCallFn = Callable[[Dict[str, Any]], Awaitable[Any]]
ToolExecFn = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]
StreamLlmFn = Callable[[Dict[str, Any]], Any]
CleanReplyFn = Callable[[str], str]
GroundToolResultFn = Callable[[Dict[str, Any]], str]
VerifyReplyFn = Callable[[str, List[Any], Dict[str, Any]], Awaitable[str]]
MakeToolActionFn = Callable[[str, str, Dict[str, Any], Dict[str, Any], bool, bool, bool], Any]
EventCallbackFn = Callable[[str, Dict[str, Any], Optional[str]], Awaitable[None]]
SteerDrainFn = Callable[[], Awaitable[List[Dict[str, Any]]]]


class AgentLoop:
    """可复用的工具调用循环。

    Args:
        max_rounds: 最大工具调用轮次（默认 5，与原实现一致）
        call_llm:   发起一次 LLM 调用，返回 httpx.Response 兼容对象
                    （.status_code >= 400 判定为网关错误，.json() 解析响应体）
        execute_tool: 执行单个工具，输入 (tool_name, arguments)，返回 dict
        clean_reply: 清理模型原始回复中的推理区块
        ground_tool_result: 将工具结果包装为注入模型的 grounding 文本
        verify_reply: 对最终回复做 grounding 校验（可空）
        make_tool_action: 构造前端展示的 ToolAction 对象（可空，空则不收集）
        write_tools / sim_tools: 判断工具是否写/仿真，用于标注 action
        final_grounding_prompt: 每轮工具执行后追加给模型的 grounding 约束
    """

    def __init__(
        self,
        call_llm: LlmCallFn,
        execute_tool: ToolExecFn,
        clean_reply: CleanReplyFn,
        ground_tool_result: GroundToolResultFn,
        verify_reply: Optional[VerifyReplyFn] = None,
        make_tool_action: Optional[MakeToolActionFn] = None,
        write_tools: Optional[frozenset] = None,
        sim_tools: Optional[frozenset] = None,
        final_grounding_prompt: str = "",
        max_rounds: int = MAX_TOOL_ROUNDS,
        stream_llm: Optional[StreamLlmFn] = None,
    ) -> None:
        self._call_llm = call_llm
        self._execute_tool = execute_tool
        self._clean_reply = clean_reply
        self._ground_tool_result = ground_tool_result
        self._verify_reply = verify_reply
        self._make_tool_action = make_tool_action
        self._write_tools = write_tools or frozenset()
        self._sim_tools = sim_tools or frozenset()
        self._final_grounding_prompt = final_grounding_prompt
        self.max_rounds = max_rounds
        self._stream_llm = stream_llm

    async def run(
        self,
        payload: Dict[str, Any],
        *,
        request_id: Optional[str] = None,
        checkpoint: Optional[CheckpointManager] = None,
        event_callback: Optional[EventCallbackFn] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        cancel_wait: Optional[Callable[[], Awaitable[None]]] = None,
        steer_drain: Optional[SteerDrainFn] = None,
    ) -> LoopResult:
        """执行一次工具调用循环。

        Args:
            payload: LLM 请求体（含 model/messages/tools/tool_choice 等）。
                     循环内部会在工具执行后更新 payload["messages"] 并移除 tools，
                     行为与原实现一致。

        Returns:
            LoopResult。degraded=True 表示本轮未能正常给出回复。
        """
        messages: List[Dict[str, Any]] = payload.get("messages", [])
        tools: Optional[List[Dict[str, Any]]] = payload.get("tools")
        tool_choice = payload.get("tool_choice")
        model = payload.get("model", "")
        actions: List[Any] = []
        diagrams: List[Dict[str, Any]] = []
        last_checkpoint_key: Optional[str] = None

        async def notify(
            event_type: str,
            data: Dict[str, Any],
            item_id: Optional[str] = None,
        ) -> None:
            """Runtime events are observability/UI signals, never control flow."""
            if event_callback is None:
                return
            try:
                await event_callback(event_type, data, item_id)
            except Exception:  # noqa: BLE001
                # A disconnected SSE client or unavailable event store must
                # never interrupt the business tool loop.
                pass

        async def append_steering() -> int:
            """Append messages submitted through ``turn/steer``.

            The queue is drained at model-round boundaries.  A model call that
            is already in flight is allowed to finish; the steering input then
            becomes the next user turn in the same Kernel context.
            """
            if steer_drain is None:
                return 0
            try:
                incoming = await steer_drain()
            except Exception:  # noqa: BLE001
                return 0
            normalized: List[Dict[str, Any]] = []
            for item in incoming or []:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if content is None:
                    continue
                normalized.append({
                    "role": str(item.get("role") or "user"),
                    "content": str(content),
                })
            if not normalized:
                return 0
            messages.extend(normalized)
            await notify(
                "turn/steered",
                {"message_count": len(normalized), "messages": normalized},
            )
            return len(normalized)

        async def retry_text_only() -> tuple[Optional[Dict[str, Any]], bool]:
            """摘掉 tools 重试一次纯文本轮，返回 (模型消息, 是否被取消)。

            网关/上游在工具轮上返回 4xx 时，旧 chat_architecture 的
            ToolFallbackExecutor 会降级为自由文本，Kernel 接手时漏掉了这条路径，
            于是一次工具轮失败就把整轮变成空回复。降级答复不经过工具，
            因此调用方必须标记为未核实。
            """
            if not payload.get("tools"):
                return None, False
            payload.pop("tools", None)
            payload.pop("tool_choice", None)
            resp, cancelled = await self._await_with_cancel(
                self._call_llm(payload), cancel_wait,
            )
            if cancelled:
                return None, True
            if resp.status_code >= 400:
                return None, False
            data = resp.json()
            message = ((data.get("choices") or [{}])[0]).get("message") or None
            return message, False

        for round_no in range(self.max_rounds):
            await append_steering()
            if cancel_check is not None and cancel_check():
                return LoopResult(
                    model=model,
                    degraded=True,
                    rounds_used=round_no,
                    actions=actions,
                    status="cancelled",
                    error="turn cancellation requested",
                )

            model_item_id = new_item_id("model")
            await notify(
                "item/started",
                {"item_type": "model_call", "round": round_no + 1},
                model_item_id,
            )
            streamed_content: List[str] = []
            streamed_tool_calls: Dict[int, Dict[str, Any]] = {}
            if self._stream_llm is not None:
                try:
                    stream_iterator = self._stream_llm(payload).__aiter__()
                    while True:
                        if cancel_check is not None and cancel_check():
                            return self._cancelled_result(
                                model=model,
                                rounds_used=round_no,
                                actions=actions,
                            )
                        try:
                            chunk, cancelled = await self._await_with_cancel(
                                stream_iterator.__anext__(), cancel_wait,
                            )
                        except StopAsyncIteration:
                            break
                        if cancelled:
                            return self._cancelled_result(
                                model=model,
                                rounds_used=round_no,
                                actions=actions,
                            )
                        delta = chunk
                        if isinstance(chunk, dict) and "choices" in chunk:
                            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                        if not isinstance(delta, dict):
                            continue
                        text = delta.get("content") or ""
                        if text:
                            streamed_content.append(text)
                            await notify(
                                "item/delta",
                                {
                                    "item_type": "assistant_text",
                                    "round": round_no + 1,
                                    "delta": text,
                                },
                                model_item_id,
                            )
                        self._merge_tool_call_deltas(
                            streamed_tool_calls,
                            delta.get("tool_calls") or [],
                        )
                except Exception as exc:  # noqa: BLE001
                    await notify(
                        "item/completed",
                        {
                            "item_type": "model_call",
                            "round": round_no + 1,
                            "status": "error",
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                        model_item_id,
                    )
                    return LoopResult(
                        model=model,
                        degraded=True,
                        rounds_used=round_no + 1,
                        status="gateway_error",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                tool_calls = [
                    streamed_tool_calls[index]
                    for index in sorted(streamed_tool_calls)
                    if streamed_tool_calls[index]["function"]["name"]
                ]
                message = {
                    "role": "assistant",
                    "content": "".join(streamed_content),
                    "tool_calls": tool_calls,
                }
                status_code = 200
            else:
                resp, cancelled = await self._await_with_cancel(
                    self._call_llm(payload), cancel_wait,
                )
                if cancelled:
                    return self._cancelled_result(
                        model=model,
                        rounds_used=round_no,
                        actions=actions,
                    )
                status_code = resp.status_code
                data = resp.json() if status_code < 400 else {}
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                tool_calls = message.get("tool_calls") or []

            if status_code >= 400:
                fallback_message, cancelled = await retry_text_only()
                if cancelled:
                    return self._cancelled_result(
                        model=model,
                        rounds_used=round_no + 1,
                        actions=actions,
                    )
                fallback_reply = self._clean_reply(
                    (fallback_message or {}).get("content") or "",
                )
                if fallback_reply and not (fallback_message or {}).get("tool_calls"):
                    await notify(
                        "item/completed",
                        {
                            "item_type": "model_call",
                            "round": round_no + 1,
                            "status": "tool_fallback",
                        },
                        model_item_id,
                    )
                    return LoopResult(
                        reply=fallback_reply,
                        model=model,
                        degraded=True,
                        rounds_used=round_no + 1,
                        actions=actions,
                        diagrams=diagrams,
                        status="tool_fallback",
                        error=f"gateway returned {status_code}；本轮未经 MES 工具核实",
                    )
                await notify(
                    "item/completed",
                    {
                        "item_type": "model_call",
                        "round": round_no + 1,
                        "status": "error",
                        "status_code": status_code,
                    },
                    model_item_id,
                )
                return LoopResult(
                    model=model,
                    degraded=True,
                    rounds_used=round_no + 1,
                    status="gateway_error",
                    error=f"gateway returned {status_code}",
                )

            await notify(
                "item/completed",
                {
                    "item_type": "model_call",
                    "round": round_no + 1,
                    "status": "tool_calls" if tool_calls else "final",
                    "tool_call_count": len(tool_calls),
                },
                model_item_id,
            )

            steered = await append_steering()

            # A steering message supersedes an unexecuted model answer/tool
            # proposal.  Preserve only visible assistant text, then let the
            # next model call see the new user direction.
            if steered:
                if message.get("content"):
                    messages.append({
                        "role": "assistant",
                        "content": message.get("content") or "",
                    })
                payload["messages"] = messages
                continue

            # 无工具调用 → 最终回复
            if not tool_calls:
                reply = self._clean_reply(message.get("content") or "")
                if not reply:
                    # 流式轮可能因上游错误只回来空内容；同样先做一次纯文本重试。
                    fallback_message, cancelled = await retry_text_only()
                    if cancelled:
                        return self._cancelled_result(
                            model=model,
                            rounds_used=round_no + 1,
                            actions=actions,
                        )
                    reply = self._clean_reply(
                        (fallback_message or {}).get("content") or "",
                    )
                    if reply and not (fallback_message or {}).get("tool_calls"):
                        return LoopResult(
                            reply=reply,
                            model=model,
                            degraded=True,
                            rounds_used=round_no + 1,
                            actions=actions,
                            diagrams=diagrams,
                            status="tool_fallback",
                            error="工具轮无返回；本轮未经 MES 工具核实",
                        )
                    return LoopResult(
                        model=model,
                        degraded=True,
                        rounds_used=round_no + 1,
                        status="no_reply",
                    )
                if self._verify_reply is not None:
                    reply = await self._verify_reply(reply, actions, payload)
                return LoopResult(
                    reply=reply,
                    model=model,
                    degraded=False,
                    rounds_used=round_no + 1,
                    actions=actions,
                    diagrams=diagrams,
                    status="complete",
                    checkpoint_key=last_checkpoint_key,
                )

            # 有工具调用 → 逐个执行并回填上下文
            messages.append({
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            })
            for tc in tool_calls:
                fn = tc.get("function") or {}
                tool_name = fn.get("name", "")
                arguments = self._parse_arguments(fn.get("arguments"))
                tool_item_id = new_item_id("tool")
                await notify(
                    "item/started",
                    {
                        "item_type": "tool_call",
                        "tool": tool_name,
                        "arguments": arguments,
                    },
                    tool_item_id,
                )

                try:
                    result = await self._execute_tool(tool_name, arguments)
                except Exception as exc:  # noqa: BLE001
                    await notify(
                        "item/completed",
                        {
                            "item_type": "tool_result",
                            "tool": tool_name,
                            "status": "error",
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                        tool_item_id,
                    )
                    # 工具可能已经完成前序副作用；恢复到最近已完成轮次，避免
                    # 调用方误以为当前半轮可以安全重放。
                    restored_key = None
                    restored = None
                    if checkpoint is not None and request_id:
                        restored = await checkpoint.restore_async(request_id)
                    if restored is not None:
                        messages = restored.get("messages") or []
                        payload["messages"] = messages
                        restored_key = restored.get("key")
                        saved_actions = max(0, int(restored.get("actions_count", 0)))
                        del actions[saved_actions:]
                    return LoopResult(
                        model=model,
                        degraded=True,
                        rounds_used=round_no + 1,
                        actions=actions,
                        status="tool_error",
                        error=f"{type(exc).__name__}: {exc}",
                        checkpoint_key=restored_key,
                        restored_from_checkpoint=restored is not None,
                    )
                is_error = "error" in result
                await notify(
                    "item/completed",
                    {
                        "item_type": "tool_result",
                        "tool": tool_name,
                        "status": "error" if is_error else "complete",
                        "result": result,
                    },
                    tool_item_id,
                )

                if self._make_tool_action is not None:
                    action = self._make_tool_action(
                        tool_name, tool_name, arguments, result,
                        tool_name in self._write_tools,
                        tool_name in self._sim_tools,
                        not is_error,
                    )
                    actions.append(action)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": self._ground_tool_result(result),
                })

                if cancel_check is not None and cancel_check():
                    return LoopResult(
                        model=model,
                        degraded=True,
                        rounds_used=round_no + 1,
                        actions=actions,
                        status="cancelled",
                        error="turn cancellation requested",
                    )

            steered_after_tools = await append_steering()

            # 追加 grounding 约束，进入下一轮
            if self._final_grounding_prompt:
                messages.append({"role": "system", "content": self._final_grounding_prompt})
            payload["messages"] = messages
            # 工具保留给后续轮次：摘掉 tools 会让想再查一次数的模型把调用写成正文，
            # 前端于是看到工具调用文本（或清洗后的空回复）。轮数仍受 max_rounds 约束。

            if checkpoint is not None and request_id:
                last_checkpoint_key = await checkpoint.save_async(
                    request_id,
                    messages=messages,
                    actions_count=len(actions),
                )

        # 超过最大轮次
        return LoopResult(
            model=model,
            degraded=True,
            rounds_used=self.max_rounds,
            actions=actions,
            status="max_rounds",
            checkpoint_key=last_checkpoint_key,
        )

    @staticmethod
    async def _await_with_cancel(
        awaitable: Awaitable[Any],
        cancel_wait: Optional[Callable[[], Awaitable[None]]],
    ) -> tuple[Any, bool]:
        """Await model I/O while allowing a thread cancellation to interrupt it."""
        if cancel_wait is None:
            return await awaitable, False

        work_task = asyncio.ensure_future(awaitable)
        cancel_task = asyncio.create_task(cancel_wait())
        try:
            done, _ = await asyncio.wait(
                {work_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done:
                work_task.cancel()
                await asyncio.gather(work_task, return_exceptions=True)
                return None, True
            return work_task.result(), False
        finally:
            if not work_task.done():
                work_task.cancel()
            if not cancel_task.done():
                cancel_task.cancel()
            await asyncio.gather(work_task, return_exceptions=True)
            await asyncio.gather(cancel_task, return_exceptions=True)

    @staticmethod
    def _cancelled_result(
        *,
        model: str,
        rounds_used: int,
        actions: List[Any],
    ) -> LoopResult:
        return LoopResult(
            model=model,
            degraded=True,
            rounds_used=rounds_used,
            actions=actions,
            status="cancelled",
            error="turn cancellation requested",
        )

    @staticmethod
    def _merge_tool_call_deltas(
        accumulated: Dict[int, Dict[str, Any]],
        deltas: List[Dict[str, Any]],
    ) -> None:
        """Merge OpenAI-compatible streaming function-call fragments."""
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

    @staticmethod
    def _parse_arguments(raw: Any) -> Dict[str, Any]:
        """解析工具调用的 JSON arguments，解析失败返回空 dict。"""
        import json

        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}
