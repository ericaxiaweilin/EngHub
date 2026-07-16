"""
Manufacturing AI agent with MCP-aligned tool calling.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from core.agent.llm_client import LLMGatewayClient
from core.agent.models import AgentChatResponse, ChatMessage, ToolCallRecord
from core.agent.tools import ToolRegistry, get_tool_registry
from core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are EngHub Manufacturing Agent, an AI assistant for MES/WMS operations.

You can call tools to read live or demo manufacturing data (work orders, stations,
equipment, inventory, OEE, production summaries). Prefer tool results over guesses.

Guidelines:
1. Be concise and operational.
2. Cite concrete IDs, quantities, and statuses from tool output.
3. If data is marked source=demo, say so briefly.
4. Suggest next actions when useful (release WO, check shortage, maintenance).
5. Answer in the user's language.
"""


class ManufacturingAgent:
    """LLM agent that loops on tool calls against the shared MES tool registry."""

    def __init__(
        self,
        tools: Optional[ToolRegistry] = None,
        llm: Optional[LLMGatewayClient] = None,
    ) -> None:
        self.tools = tools or get_tool_registry()
        self.llm = llm or LLMGatewayClient()

    async def chat(
        self,
        message: str,
        history: Optional[List[ChatMessage]] = None,
        factory_id: Optional[str] = None,
        use_tools: bool = True,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AgentChatResponse:
        if factory_id:
            self.tools.factory_id = factory_id

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        for item in history or []:
            payload = item.model_dump(exclude_none=True)
            messages.append(payload)
        messages.append({"role": "user", "content": message})

        openai_tools = self.tools.openai_tools() if use_tools else None
        collected_calls: List[ToolCallRecord] = []
        model_name: Optional[str] = None

        for round_idx in range(1, settings.AGENT_MAX_TOOL_ROUNDS + 1):
            result = await self.llm.chat_completion(
                messages=messages,
                tools=openai_tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if result.get("fallback") or result.get("error"):
                fallback_reply = await self._offline_reply(message)
                return AgentChatResponse(
                    reply=fallback_reply,
                    tool_calls=collected_calls,
                    model=model_name,
                    fallback=True,
                    rounds=round_idx,
                )

            model_name = result.get("model") or self.llm.model
            choice = (result.get("choices") or [{}])[0]
            assistant_message = choice.get("message") or {}
            tool_calls = assistant_message.get("tool_calls") or []

            # Persist assistant turn
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_message.get("content"),
                    "tool_calls": tool_calls or None,
                }
            )

            if not tool_calls:
                content = (assistant_message.get("content") or "").strip()
                if not content:
                    content = "No response generated."
                return AgentChatResponse(
                    reply=content,
                    tool_calls=collected_calls,
                    model=model_name,
                    fallback=False,
                    rounds=round_idx,
                )

            for call in tool_calls:
                call_id = call.get("id") or f"call_{round_idx}"
                function = call.get("function") or {}
                name = function.get("name") or "unknown"
                raw_args = function.get("arguments") or "{}"
                try:
                    arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except json.JSONDecodeError:
                    arguments = {}
                tool_result = await self.tools.call(name, arguments)
                collected_calls.append(
                    ToolCallRecord(
                        id=call_id,
                        name=name,
                        arguments=arguments,
                        result=tool_result,
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": name,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

        # Exhausted tool rounds — ask model for a final answer without tools.
        final = await self.llm.chat_completion(
            messages=messages + [
                {
                    "role": "user",
                    "content": "Please provide your final answer now using the tool results above.",
                }
            ],
            tools=None,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if final.get("fallback") or final.get("error"):
            return AgentChatResponse(
                reply=await self._offline_reply(message, collected_calls),
                tool_calls=collected_calls,
                model=model_name,
                fallback=True,
                rounds=settings.AGENT_MAX_TOOL_ROUNDS,
            )
        content = (
            ((final.get("choices") or [{}])[0].get("message") or {}).get("content")
            or ""
        ).strip()
        return AgentChatResponse(
            reply=content or "Reached tool-call limit before a final answer.",
            tool_calls=collected_calls,
            model=final.get("model") or model_name,
            fallback=False,
            rounds=settings.AGENT_MAX_TOOL_ROUNDS,
        )

    async def _offline_reply(
        self,
        message: str,
        prior_calls: Optional[List[ToolCallRecord]] = None,
    ) -> str:
        """Deterministic fallback when the LLM gateway is unreachable."""
        if prior_calls:
            summaries = []
            for call in prior_calls:
                summaries.append(f"- {call.name}: {json.dumps(call.result, ensure_ascii=False)[:400]}")
            return (
                "LLM gateway is unavailable, but tool results were collected:\n"
                + "\n".join(summaries)
            )

        # Heuristic: run a useful read tool so Codex-less HTTP clients still get data.
        lower = message.lower()
        if any(token in lower for token in ("工单", "work order", "wo-")):
            data = await self.tools.call("list_work_orders", {})
        elif any(token in lower for token in ("库存", "inventory", "物料")):
            data = await self.tools.call("get_inventory", {})
        elif any(token in lower for token in ("工位", "station")):
            data = await self.tools.call("list_stations", {})
        elif any(token in lower for token in ("设备", "equipment", "oee")):
            data = await self.tools.call("list_equipment", {})
        else:
            data = await self.tools.call("get_production_summary", {})

        return (
            "LLM gateway is unavailable. Showing direct MES tool output instead.\n"
            f"{json.dumps(data, ensure_ascii=False, indent=2)}"
        )
