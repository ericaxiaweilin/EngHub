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


def test_streamed_tool_call_fragments_are_merged():
    calls = {}
    chat_routes._merge_stream_tool_calls(calls, [{
        "index": 0,
        "id": "call-1",
        "type": "function",
        "function": {
            "name": "query_work_orders",
            "arguments": '{"status":"in_',
        },
    }])
    chat_routes._merge_stream_tool_calls(calls, [{
        "index": 0,
        "function": {"arguments": 'progress"}'},
    }])

    assert calls[0]["id"] == "call-1"
    assert calls[0]["function"] == {
        "name": "query_work_orders",
        "arguments": '{"status":"in_progress"}',
    }


@pytest.mark.asyncio
async def test_model_route_is_supplied_by_control_plane(monkeypatch):
    captured = {}

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, params=None):
            if url.endswith("/providers/deployed"):
                return FakeResponse({
                    "providers": [{
                        "provider": "control-plane-selected-provider",
                        "target_model": "gateway-execution-target",
                    }],
                })
            captured["url"] = url
            captured["params"] = params
            return FakeResponse({
                "route_request": {
                    "dispatch_scenario": "enghub.chat.primary",
                    "providers": ["control-plane-selected-provider"],
                    "runtime_policy": {
                        "request_timeout_ms": 45000,
                        "max_completion_tokens": 640,
                    },
                },
            })

    monkeypatch.setattr(
        chat_routes,
        "MODEL_STACK_CONTROL_PLANE_URL",
        "http://model-stack-control-plane:8080",
    )
    monkeypatch.setattr(chat_routes.httpx, "AsyncClient", FakeClient)

    route = await chat_routes._resolve_model_route(
        "enghub.chat.primary",
        prompt_tokens=321,
        max_completion_tokens=999,
    )

    assert captured["url"].endswith(
        "/business-tasks/enghub.chat.primary/route-request"
    )
    assert captured["params"]["require_deployed"] == "true"
    assert route == {
        "task_id": "enghub.chat.primary",
        "provider": "control-plane-selected-provider",
        "gateway_model": "gateway-execution-target",
        "request_timeout": 45.0,
        "max_completion_tokens": 640,
    }


@pytest.mark.asyncio
async def test_business_capability_is_selected_by_model(monkeypatch):
    calls = []
    routed_tasks = []
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

    async def fake_resolve_model_route(task_id, **_kwargs):
        routed_tasks.append(task_id)
        return {
            "task_id": task_id,
            "provider": "control-plane-selected-provider",
            "gateway_model": "gateway-execution-target",
            "request_timeout": 30.0,
            "max_completion_tokens": 768,
        }

    async def fake_execute_tool(db, tool_name, arguments, operator, factory_id):
        assert tool_name == "query_work_orders"
        assert arguments == {"status": "in_progress"}
        return {
            "count": 1,
            "work_orders": [{"work_order_code": "WO-1", "status": "in_progress"}],
        }

    monkeypatch.setattr(chat_routes, "_resolve_model_route", fake_resolve_model_route)
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

    assert routed_tasks == [chat_routes.MODEL_STACK_CHAT_TASK_ID]
    assert calls[0]["model"] == "gateway-execution-target"
    assert calls[0]["max_tokens"] == 768
    assert calls[0]["messages"][-1]["content"] == "请理解我的业务需求"
    assert calls[0]["tool_choice"] == "auto"
    assert calls[0]["tools"] == chat_routes.TOOL_DEFINITIONS
    assert calls[1]["messages"][-2]["role"] == "tool"
    assert calls[1]["messages"][-1] == {
        "role": "system",
        "content": chat_routes.FINAL_GROUNDING_PROMPT,
    }
    assert "tools" not in calls[1]
    assert "tool_choice" not in calls[1]
    assert calls[2]["temperature"] == 0
    assert "事实审校器" in calls[2]["messages"][0]["content"]
    assert result.reply == "当前有 1 条在制工单。"
    assert result.model == chat_routes.MODEL_STACK_CHAT_TASK_ID
    assert result.actions[0].tool == "query_work_orders"
