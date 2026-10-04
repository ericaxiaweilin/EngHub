"""Tests for Phase 6 — Engineering Surface（Trace/Replay/Plugins/Version/Failures）。

网络类端点（/eval, /model-compare）不在此直测，走既有 chat_v2/LLM 测试覆盖。
这里覆盖纯查询/自省端点 + ChatEvalCase 模型注册。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi.testclient import TestClient

from database.models import ChatEvalCase


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _import_router():
    import importlib.util, sys
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("chat_routes_v6t", Path("api/routes/chat_routes.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ──────────────────────────────────────────────
# Plugins / Version（无 DB 依赖）
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_plugins_lists_skills():
    mod = _import_router()
    reg = mod._get_skill_registry()
    data = await mod.chat_plugins()
    names = {p["name"] for p in data["plugins"]}
    assert "work_order" in names
    assert "inventory" in names
    assert data["tool_count"] >= 7


@pytest.mark.asyncio
async def test_chat_version_returns_harness():
    mod = _import_router()
    data = await mod.chat_version()
    assert data["harness"].startswith("0.")
    assert data["api"] == "/api/v1/chat/v2"
    assert data["phases"] == [1, 2, 3, 4, 5, 6, 7, 8]


# ──────────────────────────────────────────────
# Failures（内存 ring）
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_failures_aggregates_memory_and_db():
    from core.kernel.telemetry import Telemetry
    tel = Telemetry.get_instance()
    from core.kernel.telemetry import TelemetryEvent
    tel.record(TelemetryEvent(request_id="req-fail", phase="tool_loop", success=False,
                              error="boom", model="m", duration_ms=12.3))

    mod = _import_router()

    class FakeRow:
        request_id = "db-fail"
        phase = "total"
        error = "db down"
        model = "m2"
        duration_ms = 5
        created_at = None

    db = AsyncMock()
    db.execute.return_value = MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [FakeRow()])))

    out = await mod.chat_failures(limit=10, db=db, current_user=SimpleNamespace(is_superuser=True))
    mem_ids = [f["request_id"] for f in out["memory"]]
    assert "req-fail" in mem_ids
    assert out["db"][0]["request_id"] == "db-fail"
    # 清理
    tel._ring = [e for e in tel._ring if e.request_id != "req-fail"]


# ──────────────────────────────────────────────
# Trace / Replay（persistence 层 mock）
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_trace_delegates_to_persistence():
    mod = _import_router()
    fake_trace = {
        "request_id": "req-x", "session_id": "s1", "session": {"id": "s1"},
        "messages": [{"role": "user", "content": "hi"}],
        "telemetry": [{"phase": "total"}],
    }
    db = MagicMock()
    import api.services.chat_persistence_service as cps
    with patch.object(cps, "get_trace", AsyncMock(return_value=fake_trace)):
        out = await mod.chat_trace("req-x", db=db, current_user=SimpleNamespace())
    assert out["request_id"] == "req-x"


@pytest.mark.asyncio
async def test_chat_replay_delegates_to_persistence():
    mod = _import_router()
    fake = {"request_id": None, "session_id": "s9", "session": {"id": "s9"},
            "messages": [], "telemetry": []}
    import api.services.chat_persistence_service as cps
    with patch.object(cps, "get_trace", AsyncMock(return_value=fake)):
        out = await mod.chat_replay("s9", db=MagicMock(), current_user=SimpleNamespace())
    assert out["session_id"] == "s9"


# ──────────────────────────────────────────────
# ChatEvalCase 模型
# ──────────────────────────────────────────────

def test_eval_case_model_fields():
    case = ChatEvalCase(name="n", prompt="p", expected_tool="query_work_orders")
    assert case.name == "n"
    assert case.expected_tool == "query_work_orders"
    # enabled 有默认值（default=True）
    assert ChatEvalCase.__table__.c.enabled.default is not None


# ──────────────────────────────────────────────
# HTTP 冒烟：/plugins /version 可访问
# ──────────────────────────────────────────────

def test_http_plugins_and_version():
    from main import app
    client = TestClient(app)
    r = client.get("/api/v1/chat/plugins")
    assert r.status_code == 200
    data = r.json()
    assert any(p["name"] == "work_order" for p in data["plugins"])
    r2 = client.get("/api/v1/chat/version")
    assert r2.status_code == 200
    assert r2.json()["harness"]