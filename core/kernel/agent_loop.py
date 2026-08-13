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


# 类型别名：外部注入的能力
LlmCallFn = Callable[[Dict[str, Any]], Awaitable[Any]]
ToolExecFn = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]
CleanReplyFn = Callable[[str], str]
GroundToolResultFn = Callable[[Dict[str, Any]], str]
VerifyReplyFn = Callable[[str, List[Any], Dict[str, Any]], Awaitable[str]]
MakeToolActionFn = Callable[[str, str, Dict[str, Any], Dict[str, Any], bool, bool, bool], Any]


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

    async def run(self, payload: Dict[str, Any]) -> LoopResult:
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

        for round_no in range(self.max_rounds):
            resp = await self._call_llm(payload)

            if resp.status_code >= 400:
                return LoopResult(
                    model=model,
                    degraded=True,
                    rounds_used=round_no + 1,
                    status="gateway_error",
                    error=f"gateway returned {resp.status_code}",
                )

            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = message.get("tool_calls") or []

            # 无工具调用 → 最终回复
            if not tool_calls:
                reply = self._clean_reply(message.get("content") or "")
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

                result = await self._execute_tool(tool_name, arguments)
                is_error = "error" in result

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

            # 追加 grounding 约束，进入下一轮
            if self._final_grounding_prompt:
                messages.append({"role": "system", "content": self._final_grounding_prompt})
            payload["messages"] = messages
            payload.pop("tools", None)
            payload.pop("tool_choice", None)

        # 超过最大轮次
        return LoopResult(
            model=model,
            degraded=True,
            rounds_used=self.max_rounds,
            actions=actions,
            status="max_rounds",
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