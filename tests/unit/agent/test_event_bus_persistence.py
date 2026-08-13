"""Event Bus 的内存实时流 + DB 审计持久化测试。"""

from datetime import datetime
import asyncio
from types import SimpleNamespace

import pytest

from core.agent.event_bus import AgentEventBus, EventType


@pytest.fixture(scope="session")
def event_loop():
    """Python 3.14 兼容的 pytest-asyncio session loop。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class FakeSession:
    def __init__(self, rows=None, fail_commit=False):
        self.rows = rows or []
        self.fail_commit = fail_commit
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("database unavailable")

    async def execute(self, statement):
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: self.rows)
        )


class FakeFactory:
    def __init__(self, session):
        self.session = session

    def __call__(self):
        return self.session


@pytest.mark.asyncio
async def test_emit_persists_event_and_keeps_ring_buffer():
    session = FakeSession()
    bus = AgentEventBus()
    bus.configure_persistence(FakeFactory(session), enabled=True)

    event = await bus.emit(
        EventType.ACTION_END,
        agent_key="dispatch_agent",
        factory_id="F01",
        task_id="task-1",
        data={"success": True},
    )

    assert len(session.added) == 1
    record = session.added[0]
    assert record.event_id == event.event_id
    assert record.event_type == "action_end"
    assert record.factory_id == "F01"
    assert bus.get_recent_events("F01")[0]["event_id"] == event.event_id


@pytest.mark.asyncio
async def test_persistence_failure_does_not_break_subscribers():
    session = FakeSession(fail_commit=True)
    bus = AgentEventBus()
    bus.configure_persistence(FakeFactory(session), enabled=True)
    received = []

    async def subscriber(event):
        received.append(event.event_id)

    bus.subscribe("F01", subscriber)
    event = await bus.emit(
        EventType.ERROR,
        agent_key="quality_agent",
        factory_id="F01",
        data={"error": "boom"},
    )

    assert received == [event.event_id]
    assert bus.get_recent_events("F01")[0]["type"] == "error"


@pytest.mark.asyncio
async def test_replay_reads_database_rows_in_chronological_order():
    rows = [
        SimpleNamespace(
            event_id="e2", event_type="action_end", agent_key="a",
            factory_id="F01", task_id="11111111-1111-1111-1111-111111111111", data={"n": 2},
            created_at=datetime(2026, 1, 1, 0, 0, 2),
        ),
        SimpleNamespace(
            event_id="e1", event_type="action_start", agent_key="a",
            factory_id="F01", task_id="11111111-1111-1111-1111-111111111111", data={"n": 1},
            created_at=datetime(2026, 1, 1, 0, 0, 1),
        ),
    ]
    session = FakeSession(rows=rows)
    bus = AgentEventBus()
    bus.configure_persistence(FakeFactory(session), enabled=True)

    replay = await bus.replay(
        factory_id="F01",
        task_id="11111111-1111-1111-1111-111111111111",
        limit=10,
    )

    assert [event["event_id"] for event in replay] == ["e1", "e2"]
    assert replay[0]["data"] == {"n": 1}
