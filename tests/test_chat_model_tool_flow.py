import copy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


_CHAT_ROUTES_PATH = Path(__file__).resolve().parents[1] / "api/routes/chat_routes.py"
_SPEC = importlib.util.spec_from_file_location("enghub_chat_routes_test", _CHAT_ROUTES_PATH)
chat_routes = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules[_SPEC.name] = chat_routes
_SPEC.loader.exec_module(chat_routes)


def test_model_reasoning_block_is_removed_from_user_reply():
    content = "<think>内部推理</think>\n最终业务答复"
    assert chat_routes._clean_model_reply(content) == "最终业务答复"


@pytest.mark.asyncio
async def test_business_capability_is_selected_by_model(monkeypatch):
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
                            "name": "query_work_orders",
                            "arguments": '{"status":"in_progress"}',
                        },
                    }],
                },
            }],
        },
        {
            "choices": [{
                "message": {
                    "content": "当前有 1 条在制工单。",
                },
            }],
        },
    ]

    async def fake_call_llm(payload, **_kwargs):
        calls.append(copy.deepcopy(payload))
        response = MagicMock(status_code=200)
        response.json.return_value = responses.pop(0)
        return response

    async def fake_execute_tool(db, tool_name, arguments, operator, factory_id):
        assert tool_name == "query_work_orders"
        assert arguments == {"status": "in_progress"}
        return {
            "count": 1,
            "work_orders": [{"work_order_code": "WO-1", "status": "in_progress"}],
        }

    monkeypatch.setattr(chat_routes, "_call_llm", fake_call_llm)
    monkeypatch.setattr(chat_routes, "execute_tool", fake_execute_tool)

    result = await chat_routes.chat(
        chat_routes.ChatRequest(messages=[
            chat_routes.ChatMessage(role="user", content="请理解我的业务需求"),
        ]),
        http_request=SimpleNamespace(headers={"x-factory-id": "F01"}),
        db=MagicMock(),
        current_user=SimpleNamespace(
            username="tester",
            id="user-1",
            active_factory_id="F01",
            factory_id="F01",
        ),
    )

    assert calls[0]["messages"][-1]["content"] == "请理解我的业务需求"
    assert calls[0]["tool_choice"] == "auto"
    assert calls[0]["tools"] == chat_routes.TOOL_DEFINITIONS
    assert calls[1]["messages"][-1]["role"] == "tool"
    assert "tools" not in calls[1]
    assert "tool_choice" not in calls[1]
    assert result.reply == "当前有 1 条在制工单。"
    assert result.actions[0].tool == "query_work_orders"
