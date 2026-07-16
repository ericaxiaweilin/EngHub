"""
Unit tests for EngHub AI Agent + MCP protocol support.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from core.agent.agent import ManufacturingAgent
from core.agent.llm_client import LLMGatewayClient
from core.agent.tools import ToolRegistry
from core.mcp.server import EngHubMCPServer
from core.mcp.transports import (
    decode_stdio_messages_for_tests,
    encode_stdio_message_for_tests,
)
from main import app


@pytest.fixture
def tools() -> ToolRegistry:
    return ToolRegistry(factory_id="factory-demo")


@pytest.fixture
def mcp_server(tools: ToolRegistry) -> EngHubMCPServer:
    return EngHubMCPServer(tools=tools)


@pytest.mark.asyncio
async def test_tool_registry_lists_builtin_tools(tools: ToolRegistry):
    names = {item.name for item in tools.list_definitions()}
    assert "list_work_orders" in names
    assert "get_inventory" in names
    assert "get_system_status" in names
    assert len(tools.openai_tools()) == len(tools.mcp_tools())


@pytest.mark.asyncio
async def test_list_work_orders_demo_fallback(tools: ToolRegistry):
    result = await tools.call("list_work_orders", {"limit": 2})
    assert result["source"] == "demo"
    assert result["count"] == 2
    assert result["items"][0]["work_order_code"]


@pytest.mark.asyncio
async def test_search_mes_entities(tools: ToolRegistry):
    result = await tools.call("search_mes_entities", {"query": "WO-20260716"})
    assert result["count"] >= 1


@pytest.mark.asyncio
async def test_mcp_initialize_and_tools_list(mcp_server: EngHubMCPServer):
    init = await mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "codex", "version": "test"},
            },
        }
    )
    assert init["result"]["serverInfo"]["name"] == "enghub-mes"
    assert "tools" in init["result"]["capabilities"]

    listed = await mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    )
    tool_names = {tool["name"] for tool in listed["result"]["tools"]}
    assert "list_work_orders" in tool_names
    assert "inputSchema" in listed["result"]["tools"][0]


@pytest.mark.asyncio
async def test_mcp_tools_call_and_resources(mcp_server: EngHubMCPServer):
    called = await mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "get_production_summary",
                "arguments": {},
            },
        }
    )
    assert called["result"]["isError"] is False
    assert called["result"]["content"][0]["type"] == "text"
    assert "open_work_orders" in called["result"]["structuredContent"]

    resources = await mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 4, "method": "resources/list"}
    )
    uris = {item["uri"] for item in resources["result"]["resources"]}
    assert "enghub://work-orders" in uris

    read = await mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "resources/read",
            "params": {"uri": "enghub://status"},
        }
    )
    payload = json.loads(read["result"]["contents"][0]["text"])
    assert payload["service"] == "enghub-agent"


@pytest.mark.asyncio
async def test_mcp_prompts_get(mcp_server: EngHubMCPServer):
    prompt = await mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "prompts/get",
            "params": {
                "name": "work_order_deep_dive",
                "arguments": {"work_order_code": "WO-1"},
            },
        }
    )
    assert "WO-1" in prompt["result"]["messages"][0]["content"]["text"]


@pytest.mark.asyncio
async def test_mcp_notification_returns_none(mcp_server: EngHubMCPServer):
    response = await mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
    )
    assert response is None


@pytest.mark.asyncio
async def test_agent_offline_fallback_without_llm(tools: ToolRegistry):
    class BrokenLLM(LLMGatewayClient):
        async def chat_completion(self, *args, **kwargs):
            return {"error": "down", "fallback": True}

        async def health_check(self) -> bool:
            return False

    agent = ManufacturingAgent(tools=tools, llm=BrokenLLM())
    response = await agent.chat("查看当前工单状态")
    assert response.fallback is True
    assert "WO-" in response.reply or "work_order" in response.reply.lower() or "list_work_orders" in response.reply or "items" in response.reply


def test_http_mcp_and_agent_endpoints():
    client = TestClient(app)

    discover = client.get("/mcp")
    assert discover.status_code == 200
    assert discover.json()["transport"] == "streamable-http-json"

    init = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "codex", "version": "0"},
            },
        },
    )
    assert init.status_code == 200
    assert init.json()["result"]["serverInfo"]["name"] == "enghub-mes"

    notify = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert notify.status_code == 202

    tools = client.get("/api/v1/agent/tools")
    assert tools.status_code == 200
    assert tools.json()["count"] >= 8

    invoke = client.post(
        "/api/v1/agent/tools/invoke",
        json={"name": "get_system_status", "arguments": {}},
    )
    assert invoke.status_code == 200
    assert invoke.json()["result"]["mcp_server"] == "enghub-mes"

    root = client.get("/")
    assert root.json()["mcp"] == "/mcp"


def test_stdio_framing_roundtrip():
    payload = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    framed = encode_stdio_message_for_tests(payload)
    decoded = decode_stdio_messages_for_tests(framed)
    assert decoded == (payload,)
