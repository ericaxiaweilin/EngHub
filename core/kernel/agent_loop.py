"""AgentLoop - 工具调用循环（从 chat_routes.py 抽取，行为保持等价）。

依赖注入：LLM 调用、工具执行、清理/校验函数均由构造方传入，循环本身不
触碰任何全局状态，便于独立单测与后续扩展（Skills / Model Adapters）。

与原实现差异：
- 原实现把 agent loop 内联在 chat() 端点里，与 HTTP/路由耦合。
- 这里将循环收敛为纯 async 函数，输入 KernelContext，输出 LoopResult。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.kernel.checkpoint import CheckpointManager

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
    status: str = "complete"  # complete | no_reply | max_rounds | gateway_error | exception
    error: Optional[str] = None
    error_detail: Optional[str] = None
    checkpoint_key: Optional[str] = None
    restored_from_checkpoint: bool = False


# 类型别名：外部注入的能力
LlmCallFn = Callable[[Dict[str, Any]], Awaitable[Any]]
ToolExecFn = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]
CleanReplyFn = Callable[[str], str]
GroundToolResultFn = Callable[[Dict[str, Any]], str]
VerifyReplyFn = Callable[[str, List[Any], Dict[str, Any]], Awaitable[str]]
MakeToolActionFn = Callable[[str, str, Dict[str, Any], Dict[str, Any], bool, bool, bool], Any]
ToolEventFn = Callable[[Dict[str, Any]], Awaitable[None]]


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
        on_tool_event: 每次工具执行完成后异步回调（用于 SSE 实时推送轨迹）
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
        on_tool_event: Optional[ToolEventFn] = None,
        write_tools: Optional[frozenset] = None,
        sim_tools: Optional[frozenset] = None,
        final_grounding_prompt: str = "",
        max_rounds: int = MAX_TOOL_ROUNDS,
    ) -> None:
        self._call_llm = call_llm
        self._execute_tool = execute_tool
        self._clean_reply = clean_reply
        self._ground_tool_result = ground_tool_result
        self._verify_reply = verify_reply
        self._make_tool_action = make_tool_action
        self._on_tool_event = on_tool_event
        self._write_tools = write_tools or frozenset()
        self._sim_tools = sim_tools or frozenset()
        self._final_grounding_prompt = final_grounding_prompt
        self.max_rounds = max_rounds

    async def run(
        self,
        payload: Dict[str, Any],
        *,
        request_id: Optional[str] = None,
        checkpoint: Optional[CheckpointManager] = None,
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

        for round_no in range(self.max_rounds):
            resp = await self._call_llm(payload)

            if resp.status_code >= 400:
                body_text = ""
                try:
                    body_text = resp.text or ""
                except Exception:  # noqa: BLE001
                    body_text = ""
                return LoopResult(
                    model=model,
                    degraded=True,
                    rounds_used=round_no + 1,
                    status="gateway_error",
                    error=f"gateway returned {resp.status_code}",
                    error_detail=body_text[:4000],
                )

            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            content = message.get("content") or ""

            # 模型（agnes-2.5-flash 等 Anthropic 系）偶发在 content 里输出
            # Claude XML 工具调用标签（<tool_call>/<function=call:tools>/<parameter=...>）
            # 而非 OpenAI 协议 tool_calls 字段。识别并转换为真实 tool_calls 执行，
            # 避免 XML 标签被当作最终回复返回给用户（前端刷屏）。
            if not tool_calls:
                tool_calls = _parse_xml_tool_calls(content)

            # 无工具调用 → 最终回复
            if not tool_calls:
                reply = self._clean_reply(content)
                if not reply:
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

                try:
                    result = await self._execute_tool(tool_name, arguments)
                except Exception as exc:  # noqa: BLE001
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

                if self._make_tool_action is not None:
                    action = self._make_tool_action(
                        tool_name, tool_name, arguments, result,
                        tool_name in self._write_tools,
                        tool_name in self._sim_tools,
                        not is_error,
                    )
                    actions.append(action)

                # SSE 实时推送轨迹：每次工具执行完成即触发（不阻塞循环关键路径）
                if self._on_tool_event is not None:
                    try:
                        await self._on_tool_event({
                            "type": "tool_call",
                            "tool": tool_name,
                            "label": tool_name,
                            "args": arguments,
                            "result": result,
                            "success": not is_error,
                            "is_write": tool_name in self._write_tools,
                        })
                    except Exception:  # noqa: BLE001
                        pass

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": self._ground_tool_result(result),
                })

            # 追加 grounding 约束，进入下一轮
            if self._final_grounding_prompt:
                messages.append({"role": "system", "content": self._final_grounding_prompt})
            payload["messages"] = messages
            payload.pop("tools", None)
            payload.pop("tool_choice", None)

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
    def _parse_arguments(raw: Any) -> Dict[str, Any]:
        """解析工具调用的 JSON arguments，解析失败返回空 dict。"""
        import json

        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}


def _parse_xml_tool_calls(content: str):
    """解析模型 content 中混入的 Claude XML 工具调用标签，返回 OpenAI tool_calls 列表。

    支持形态（agnes-2.5-flash 实测）：
      <tool_call>
        <function=call:tools>
          <parameter=tool_name>query_sales_order_detail</parameter>
          <parameter=so_numbers>[...]</parameter>
        </function>
        <parameter=tool_inputs>{"so_numbers": [...]}</parameter>
      </tool_call>
    以及简化形态 <tool_call><function=...>...</function></tool_call>。
    解析失败/无有效调用返回空列表。
    """
    if not content or not any(tag in content for tag in ("<tool_call", "<invoke", "antml:invoke")):
        return []
    import json
    import re

    results = []
    # 逐块提取 <tool_call>...</tool_call>
    pattern = re.compile(r"<tool_call\b[^>]*>(.*?)</tool_call>", re.DOTALL | re.IGNORECASE)
    for m in pattern.finditer(content):
        block = m.group(1)
        # 工具名：<parameter=tool_name>xxx</parameter>
        tm = re.search(r"<parameter=tool_name>\s*(.*?)\s*</parameter>", block, re.DOTALL | re.IGNORECASE)
        if not tm:
            continue
        tool_name = tm.group(1).strip()
        if not tool_name:
            continue
        arguments = {}
        # 优先 tool_inputs（完整 JSON）
        im = re.search(r"<parameter=tool_inputs>\s*(.*?)\s*</parameter>", block, re.DOTALL | re.IGNORECASE)
        if im:
            raw = im.group(1).strip()
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    arguments = parsed
            except (json.JSONDecodeError, TypeError):
                arguments = {}
        # 其余 <parameter=name>value</parameter> 键值
        if not arguments:
            for pm in re.finditer(r"<parameter=([a-zA-Z_][a-zA-Z0-9_]*)>\s*(.*?)\s*</parameter>", block, re.DOTALL | re.IGNORECASE):
                key = pm.group(1)
                if key in ("tool_name", "tool_inputs"):
                    continue
                val = pm.group(2).strip()
                try:
                    arguments[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    arguments[key] = val
        results.append({
            "id": f"xml_call_{len(results)}",
            "type": "function",
            "function": {"name": tool_name, "arguments": json.dumps(arguments, ensure_ascii=False)},
        })
    # Anthropic 标准格式：<invoke name="tool_name">...</invoke>（可能带 antml: 前缀）
    if not results and ("<invoke" in content or "antml:invoke" in content):
        invoke_pattern = re.compile(
            r'<(?:antml:)?invoke\s+name\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</(?:antml:)?invoke>',
            re.DOTALL | re.IGNORECASE,
        )
        for m in invoke_pattern.finditer(content):
            tool_name = m.group(1).strip()
            if not tool_name:
                continue
            block = m.group(2)
            arguments = {}
            # <parameter name="arg">value</parameter> 或 <antml:parameter name="arg">value</antml:parameter>
            param_pattern = re.compile(
                r'<(?:antml:)?parameter\s+name\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</(?:antml:)?parameter>',
                re.DOTALL | re.IGNORECASE,
            )
            for pm in param_pattern.finditer(block):
                key = pm.group(1).strip()
                val = pm.group(2).strip()
                try:
                    arguments[key] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    arguments[key] = val
            results.append({
                "id": f"xml_invoke_{len(results)}",
                "type": "function",
                "function": {"name": tool_name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            })
    return results

