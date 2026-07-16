"""
Tests for model-engineering-base / model-stack adapters and luaguage tools.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from core.agent.tools import ToolRegistry
from core.model_base import ModelBaseClient, ModelBaseProvider
from integrations.luaguage import LuaguageIntegration
from main import app


def _json_response(request: httpx.Request, status: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"Content-Type": "application/json"},
        json=payload,
        request=request,
    )


@pytest.mark.asyncio
async def test_model_engineering_base_chat_with_tools():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content.decode())
        assert "tools" in body
        return _json_response(
            request,
            200,
            {
                "model": "qwen-max",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "ok from engineering-base",
                        }
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = ModelBaseClient(
        provider="model-engineering-base",
        engineering_base_url="http://meb.test",
        model_stack_url="http://stack.test",
        timeout=2.0,
        probe_timeout=0.5,
    )
    # Inject mock client
    client._clients["http://meb.test|2.0"] = httpx.AsyncClient(
        transport=transport,
        base_url="http://meb.test",
        timeout=2.0,
    )
    result = await client.chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "list_work_orders"}}],
    )
    assert result["backend"] == ModelBaseProvider.MODEL_ENGINEERING_BASE.value
    assert "engineering-base" in result["choices"][0]["message"]["content"]
    await client.close()


@pytest.mark.asyncio
async def test_auto_falls_back_to_model_stack():
    def meb_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    def stack_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/chat"
        return _json_response(request, 200, {"response": "hello from model-stack"})

    client = ModelBaseClient(
        provider="auto",
        engineering_base_url="http://meb.test",
        model_stack_url="http://stack.test",
        timeout=2.0,
        probe_timeout=0.5,
    )
    client._clients["http://meb.test|2.0"] = httpx.AsyncClient(
        transport=httpx.MockTransport(meb_handler),
        base_url="http://meb.test",
        timeout=2.0,
    )
    client._clients["http://stack.test|2.0"] = httpx.AsyncClient(
        transport=httpx.MockTransport(stack_handler),
        base_url="http://stack.test",
        timeout=2.0,
    )
    result = await client.chat_completion(
        messages=[{"role": "user", "content": "status?"}]
    )
    assert result["backend"] == ModelBaseProvider.MODEL_STACK.value
    assert result["choices"][0]["message"]["content"] == "hello from model-stack"
    await client.close()


@pytest.mark.asyncio
async def test_model_stack_optimize():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/optimize"
        return _json_response(request, 200, {"plan": ["WO-1", "WO-2"]})

    client = ModelBaseClient(
        provider="model-stack",
        engineering_base_url="http://meb.test",
        model_stack_url="http://stack.test",
        timeout=2.0,
        probe_timeout=0.5,
    )
    client._clients["http://stack.test|2.0"] = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://stack.test",
        timeout=2.0,
    )
    result = await client.optimize_schedule(
        work_orders=[{"id": "WO-1"}],
        constraints={"capacity": 10},
    )
    assert result is not None
    assert result["plan"] == ["WO-1", "WO-2"]
    assert result["backend"] == ModelBaseProvider.MODEL_STACK.value
    await client.close()


@pytest.mark.asyncio
async def test_luaguage_bom_live_and_demo():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/bom/product/SKU-A100" in request.url.path
        return _json_response(
            request,
            200,
            {"product_id": "SKU-A100", "materials": [{"material_id": "M1", "qty": 1}]},
        )

    live = LuaguageIntegration(
        {"base_url": "http://lua.test", "timeout": 1.0, "enabled": True}
    )
    live._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://lua.test",
        timeout=1.0,
    )
    bom = await live.get_bom("SKU-A100")
    assert bom["source"] == "luaguage"
    assert bom["materials"][0]["material_id"] == "M1"
    await live.close()

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    offline = LuaguageIntegration(
        {"base_url": "http://lua-down.test", "timeout": 0.2, "enabled": True}
    )
    offline._client = httpx.AsyncClient(
        transport=httpx.MockTransport(down),
        base_url="http://lua-down.test",
        timeout=0.2,
    )
    demo = await offline.get_bom("SKU-B")
    assert demo["source"] == "demo"
    await offline.close()


@pytest.mark.asyncio
async def test_agent_tools_include_luaguage_and_model_base():
    tools = ToolRegistry()
    names = {item.name for item in tools.list_definitions()}
    assert "get_luaguage_bom" in names
    assert "get_luaguage_ppap" in names
    assert "get_model_base_status" in names
    bom = await tools.call("get_luaguage_bom", {"product_id": "SKU-A100"})
    assert bom["product_id"] == "SKU-A100"


def test_ai_health_endpoint(monkeypatch):
    async def fake_health(self, use_cache: bool = True):
        return {
            "provider_setting": "auto",
            "selected_chat_backend": "model-engineering-base",
            "model": "qwen-max",
            "model_engineering_base": {"url": "http://meb", "ok": False},
            "model_stack": {"url": "http://stack", "ok": False},
        }

    async def fake_lua_health(self):
        return {"ok": False, "enabled": True, "base_url": "http://lua"}

    monkeypatch.setattr(ModelBaseClient, "health", fake_health)
    monkeypatch.setattr(LuaguageIntegration, "health", fake_lua_health)

    client = TestClient(app)
    response = client.get("/api/v1/ai/health")
    assert response.status_code == 200
    body = response.json()
    assert "model_base" in body
    assert "luaguage" in body
    assert body["status"] == "degraded"
