"""Tests for Phase 3 — Chat 会话持久化 + Trace/Replay。

使用内存 SQLite（aiosqlite）验证：
- 会话新建 / 复用（get_or_create_session）
- append_message / get_history 消息链
- persist_round 完整落库
- save_telemetry / get_trace Trace 重建
- HarnessKernel persist_hook 成功后落库
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from database.models import Base, ChatSession, ChatMessage, ChatTelemetry, ChatMessageAttachment, FileRecord
from api.services import chat_persistence_service as cp


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def user():
    return SimpleNamespace(username="eric", id="u-eric", factory_id="F01")


@pytest_asyncio.fixture
async def db():
    from sqlalchemy.schema import CreateTable

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # 只建本测试用到的 3 张表（其余模型含 SQLite 不支持的 JSONB）
    async with engine.begin() as conn:
        tables = [ChatSession.__table__, ChatMessage.__table__, ChatTelemetry.__table__, ChatMessageAttachment.__table__, FileRecord.__table__]
        for table in tables:
            await conn.execute(CreateTable(table))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _k(x):
    return x


# ──────────────────────────────────────────────
# Session
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_or_create_session_new(db, user):
    s = await cp.get_or_create_session(db, factory_id="F01", user=user)
    assert s.id
    assert s.factory_id == "F01"
    assert s.user_id == "u-eric"
    # 未提交时 flush 后仍可按 id 查到
    got = await cp._get_session(db, s.id)
    assert got is not None


@pytest.mark.asyncio
async def test_get_or_create_session_reuses(db, user):
    s1 = await cp.get_or_create_session(db, factory_id="F01", user=user)
    s2 = await cp.get_or_create_session(db, factory_id="F01", user=user, session_id=s1.id)
    assert s2.id == s1.id


@pytest.mark.asyncio
async def test_get_or_create_session_rejects_wrong_owner(db, user):
    s = await cp.get_or_create_session(db, factory_id="F01", user=user)
    other = SimpleNamespace(username="alice", id="u-alice", factory_id="F01")
    with pytest.raises(cp.ChatSessionAccessError):
        await cp.get_or_create_session(
            db, factory_id="F01", user=other, session_id=s.id,
        )


@pytest.mark.asyncio
async def test_get_or_create_session_rejects_wrong_factory(db, user):
    s = await cp.get_or_create_session(db, factory_id="F01", user=user)
    with pytest.raises(cp.ChatSessionAccessError):
        await cp.get_or_create_session(
            db, factory_id="F02", user=user, session_id=s.id,
        )


@pytest.mark.asyncio
async def test_list_sessions(db, user):
    s1 = await cp.get_or_create_session(db, factory_id="F01", user=user)
    await cp.get_or_create_session(db, factory_id="F01", user=user)
    await db.commit()
    rows = await cp.list_sessions(db, user=user, factory_id="F01")
    assert len(rows) == 2
    assert rows[0]["session_id"] in (s1.id, rows[0]["session_id"])


# ──────────────────────────────────────────────
# Message
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_append_and_get_history(db, user):
    s = await cp.get_or_create_session(db, factory_id="F01", user=user)
    await cp.append_message(db, session_id=s.id, role="user", content="查一下库存")
    await cp.append_message(
        db, session_id=s.id, role="assistant", content="有 3 条",
        tool_calls=[{"tool": "query_inventory", "id": "c1"}],
        model="deepseek",
    )
    history = await cp.get_history(db, s.id)
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["content"] == "有 3 条"
    assert history[1]["tool_calls"][0]["tool"] == "query_inventory"


@pytest.mark.asyncio
async def test_history_limit_is_latest_messages_in_chronological_order(db, user):
    s = await cp.get_or_create_session(db, factory_id="F01", user=user)
    for idx in range(4):
        await cp.append_message(db, session_id=s.id, role="user", content=f"q{idx}")
    history = await cp.get_history(db, s.id, limit=2)
    assert [m["content"] for m in history] == ["q2", "q3"]


@pytest.mark.asyncio
async def test_history_can_hide_persisted_tool_action_shape(db, user):
    s = await cp.get_or_create_session(db, factory_id="F01", user=user)
    await cp.append_message(db, session_id=s.id, role="user", content="查库存")
    await cp.append_message(
        db,
        session_id=s.id,
        role="assistant",
        content="查到了",
        tool_calls=[{"tool": "query_inventory", "id": "a1"}],
    )
    history = await cp.get_history(db, s.id, include_tool_calls=False)
    assert history[-1] == {"role": "assistant", "content": "查到了"}


@pytest.mark.asyncio
async def test_persist_round_traces_actions(db, user):
    s = await cp.get_or_create_session(db, factory_id="F01", user=user)
    action = SimpleNamespace(
        tool="query_inventory", label="查询库存",
        arguments={"kw": "钢"}, result={"count": 1}, success=True,
    )
    await cp.persist_round(
        db, session_id=s.id, user_content="查库存",
        reply="查到 1 条", model="deepseek", actions=[action], request_id="req-abc",
    )
    rows = (await db.execute(select(ChatMessage))).scalars().all()
    assert len(rows) == 2
    assert rows[0].role == "user"
    assert rows[0].content == "查库存"
    assert rows[1].role == "assistant"
    assert rows[1].tool_calls[0]["tool"] == "query_inventory"


@pytest.mark.asyncio
async def test_persist_round_is_idempotent_by_request_id(db, user):
    s = await cp.get_or_create_session(db, factory_id="F01", user=user)
    await cp.persist_round(
        db,
        session_id=s.id,
        user_content="查库存",
        reply="查到了",
        request_id="req-idempotent",
    )
    await cp.persist_round(
        db,
        session_id=s.id,
        user_content="查库存",
        reply="查到了",
        request_id="req-idempotent",
    )
    rows = (await db.execute(select(ChatMessage))).scalars().all()
    assert len(rows) == 2


# ──────────────────────────────────────────────
# Telemetry / Trace
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_telemetry_and_get_trace(db, user):
    s = await cp.get_or_create_session(db, factory_id="F01", user=user)
    await cp.persist_round(
        db, session_id=s.id, user_content="查工单",
        reply="工单正常", model="deepseek",
        actions=[SimpleNamespace(tool="query_work_orders", success=True)],
        request_id="req-trace-1",
    )
    await cp.save_telemetry(
        db, request_id="req-trace-1", session_id=s.id,
        model="deepseek", tools_called=["query_work_orders"],
        rounds=1, success=True,
    )
    await db.commit()

    trace = await cp.get_trace(db, "req-trace-1")
    assert trace["request_id"] == "req-trace-1"
    assert trace["session_id"] == s.id
    assert trace["session"]["factory_id"] == "F01"
    assert trace["messages"][0]["role"] == "user"
    assert len(trace["telemetry"]) == 1
    assert trace["telemetry"][0]["tools_called"] == ["query_work_orders"]


@pytest.mark.asyncio
async def test_get_trace_by_session(db, user):
    s = await cp.get_or_create_session(db, factory_id="F01", user=user)
    await cp.persist_round(
        db, session_id=s.id, user_content="hi", reply="hello",
        request_id="req-1",
    )
    await cp.save_telemetry(db, request_id="req-1", session_id=s.id, success=True)
    await db.commit()
    trace = await cp.get_trace(db, None, session_id=s.id)
    assert trace["session_id"] == s.id
    assert len(trace["messages"]) >= 1


@pytest.mark.asyncio
async def test_trace_rejects_wrong_owner(db, user):
    s = await cp.get_or_create_session(db, factory_id="F01", user=user)
    other = SimpleNamespace(username="alice", id="u-alice", factory_id="F01")
    with pytest.raises(cp.ChatSessionAccessError):
        await cp.get_trace(
            db, None, session_id=s.id, user=other, factory_id="F01",
        )


# ──────────────────────────────────────────────
# Kernel persist_hook
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kernel_persist_hook_called(db, user):
    from core.kernel import HarnessKernel
    from core.kernel.context import KernelContext

    persisted = []

    async def persist_hook(ctx, response):
        persisted.append((ctx.session_id, response.reply, len(response.actions)))

    async def responder(payload):
        return MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "最终回复"}}]},
        )

    kernel = HarnessKernel(
        db=db,
        call_llm=responder,
        resolve_model_route=AsyncMock(return_value={
            "task_id": "t", "provider": "p", "gateway_model": "m",
            "request_timeout": 5.0, "max_completion_tokens": 256,
        }),
        execute_tool=AsyncMock(return_value={"ok": True}),
        clean_reply=lambda c: c,
        ground_tool_result=lambda r: "result",
        verify_reply=None,
        make_tool_action=lambda *a, **k: SimpleNamespace(tool="x"),
        write_tools=frozenset(), sim_tools=frozenset(),
        tool_definitions=[],
        system_prompt="sys", final_grounding_prompt="ground",
        max_tool_rounds=3,
        persist_hook=persist_hook,
    )
    ctx = KernelContext(
        request_id="req-hook", factory_id="F01", user=user,
        messages=[{"role": "user", "content": "hi"}],
        model_route={"task_id": "t", "provider": "p", "gateway_model": "m"},
        session_id="sess-hook", operator="eric",
    )
    result = await kernel.handle(ctx)
    assert persisted == [("sess-hook", "最终回复", 0)]
    assert result.reply == "最终回复"


@pytest.mark.asyncio
async def test_kernel_persist_hook_failure_does_not_break(db, user):
    from core.kernel import HarnessKernel
    from core.kernel.context import KernelContext

    async def bad_hook(ctx, response):
        raise RuntimeError("db down")

    async def responder(payload):
        return MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "仍返回"}}]},
        )

    kernel = HarnessKernel(
        db=db,
        call_llm=responder,
        resolve_model_route=AsyncMock(return_value={
            "task_id": "t", "provider": "p", "gateway_model": "m",
            "request_timeout": 5.0, "max_completion_tokens": 256,
        }),
        execute_tool=AsyncMock(return_value={"ok": True}),
        clean_reply=lambda c: c,
        ground_tool_result=lambda r: "result",
        verify_reply=None,
        make_tool_action=lambda *a, **k: SimpleNamespace(tool="x"),
        write_tools=frozenset(), sim_tools=frozenset(),
        tool_definitions=[],
        system_prompt="sys", final_grounding_prompt="ground",
        max_tool_rounds=3,
        persist_hook=bad_hook,
    )
    ctx = KernelContext(
        request_id="req-bad", factory_id="F01", user=user,
        messages=[{"role": "user", "content": "hi"}],
        model_route={"task_id": "t", "provider": "p", "gateway_model": "m"},
        session_id="sess-bad", operator="eric",
    )
    result = await kernel.handle(ctx)
    assert result.reply == "仍返回"
