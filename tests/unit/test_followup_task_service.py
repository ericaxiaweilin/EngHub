"""followup_task_service 单元测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from api.services import followup_task_service as svc


@pytest.mark.asyncio
async def test_create_task_interval_sql_uses_integer_interval(monkeypatch):
    """INSERT 中 follow_interval_minutes 不能同一参数既作 int 又作 text 拼接。"""
    db = MagicMock()
    captured_sql = {}

    async def fake_execute(statement, params=None):
        captured_sql["text"] = str(statement)
        captured_sql["params"] = dict(params or {})
        return MagicMock(first=lambda: None)

    db.execute = fake_execute
    db.commit = AsyncMock()

    monkeypatch.setattr(svc, "_append_log", AsyncMock())
    monkeypatch.setattr(
        "api.services.quick_command_service.classify_command",
        AsyncMock(return_value={"agent_key": "quality_agent"}),
    )

    result = await svc.create_task(
        db,
        factory_id="FAC_ELEC_DEMO_2026",
        created_by="eric",
        title="追踪 DEF-20260718-001",
        description="BT芯片蓝牙连接距离不达标",
        follow_interval_minutes=240,
    )

    assert "error" not in result
    assert captured_sql["params"]["interval"] == 240
    assert captured_sql["params"]["interval_next"] == 240
    assert "make_interval(mins => :interval_next)" in captured_sql["text"]
    assert "|| ' minutes'" not in captured_sql["text"]
