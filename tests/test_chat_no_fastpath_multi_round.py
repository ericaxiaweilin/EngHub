"""Chatbot anti-fastpath：多轮工具循环，禁止首轮后强制文字收尾。"""

import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_CHAT_ROUTES_PATH = Path(__file__).resolve().parents[1] / "api/routes/chat_routes.py"
_SPEC = importlib.util.spec_from_file_location("enghub_chat_routes_nofastpath", _CHAT_ROUTES_PATH)
chat_routes = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = chat_routes
_SPEC.loader.exec_module(chat_routes)


@pytest.mark.asyncio
async def test_chat_keeps_tools_for_multi_round_after_start_action(monkeypatch):
    """用户说「开始吧」时可连续调用多个工具，不被首轮后剥离 tools。"""
    calls = []
    responses = [
        {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "query_ocap_tasks",
                            "arguments": "{}",
                        },
                    }],
                },
            }],
        },
        {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "call-2",
                        "type": "function",
                        "function": {
                            "name": "create_followup_task",
                            "arguments": json.dumps({
                                "title": "BATCH-20260722 同批次追溯隔离",
                                "block_reason": "OCAP triggered",
                                "agent_key": "quality_agent",
                            }, ensure_ascii=False),
                        },
                    }],
                },
            }],
        },
        {
            "choices": [{
                "message": {
                    "content": "已查询 OCAP 并挂账跟进任务。",
                },
            }],
        },
        {
            "choices": [{
                "message": {
                    "content": "已查询 OCAP 并挂账跟进任务。",
                },
            }],
        },
    ]

    async def fake_call_llm(payload, **_kwargs):
        calls.append(copy.deepcopy(payload))
        response = MagicMock(status_code=200)
        response.json.return_value = responses.pop(0)
        return response

    async def fake_resolve_model_route(task_id, **_kwargs):
        return {
            "task_id": task_id,
            "provider": "control-plane-selected-provider",
            "gateway_model": "gateway-execution-target",
            "request_timeout": 30.0,
            "max_completion_tokens": 768,
        }

    async def fake_execute_tool(db, tool_name, arguments, operator, factory_id):
        if tool_name == "query_ocap_tasks":
            return {
                "count": 1,
                "tasks": [{"record_code": "DEF-20260722-005", "ocap_status": "triggered"}],
            }
        if tool_name == "create_followup_task":
            return {"task_id": "ft-1", "title": arguments.get("title"), "status": "open"}
        return {"error": f"unexpected tool {tool_name}"}

    monkeypatch.setattr(chat_routes, "_resolve_model_route", fake_resolve_model_route)
    monkeypatch.setattr(chat_routes, "_call_llm", fake_call_llm)
    monkeypatch.setattr(chat_routes, "execute_tool", fake_execute_tool)

    result = await chat_routes.chat(
        chat_routes.ChatRequest(messages=[
            chat_routes.ChatMessage(role="user", content="开始吧"),
        ]),
        http_request=SimpleNamespace(headers={"x-factory-id": "FAC_ELEC_DEMO_2026"}),
        db=MagicMock(),
        current_user=SimpleNamespace(
            username="tester",
            id="user-1",
            active_factory_id="FAC_ELEC_DEMO_2026",
            factory_id="FAC_ELEC_DEMO_2026",
        ),
    )

    # 三轮模型调用：工具1 → 工具2 → 最终答复（另 +1 审校）
    assert len(calls) >= 3
    assert calls[0]["tools"] == chat_routes.TOOL_DEFINITIONS
    assert calls[1]["tools"] == chat_routes.TOOL_DEFINITIONS
    assert calls[1]["tool_choice"] == "auto"
    assert [a.tool for a in result.actions] == ["query_ocap_tasks", "create_followup_task"]
    assert "挂账" in result.reply


def test_resolve_intent_is_disabled_no_fastpath():
    from api.services.chat_tools_service import resolve_intent

    assert resolve_intent("质量异常分诊") is None
    assert resolve_intent("查询在制工单") is None
    assert resolve_intent("开始吧") is None


@pytest.mark.asyncio
async def test_chat_adapter_skips_deterministic_fastpath():
    from api.services.chat_architecture.adapters.chat_adapter import ChatAdapter
    from api.services.chat_architecture.resolvers.intent_resolver import IntentResolver

    assert IntentResolver().resolve("查询库存") is None
    adapter = ChatAdapter(db=MagicMock())
    assert adapter._detect_intent(
        SimpleNamespace(messages=[SimpleNamespace(role="user", content="查询库存")])
    ) is None
    result = await adapter.handle_request(
        SimpleNamespace(messages=[SimpleNamespace(role="user", content="查询库存")]),
        current_user=None,
    )
    assert result.get("model") == "tool-loop"
    assert result.get("model") != "deterministic"
