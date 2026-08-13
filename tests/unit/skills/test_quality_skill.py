"""Quality Skill tests: routing, factory scoping, and result compatibility."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.skills.quality.skill import QualitySkill
from core.skills.registry import SkillRegistry


@pytest.fixture(scope="session")
def event_loop():
    """Python 3.14 兼容的事件循环 fixture。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_query_defects_uses_factory_and_preserves_legacy_shape():
    db = AsyncMock()
    defect = SimpleNamespace(
        record_code="DR-001",
        defect_type="dimension",
        severity="major",
        quantity=2,
        disposition=None,
        ocap_status="pending",
        root_cause_category="measurement",
        description="尺寸超差" * 20,
        created_at=datetime(2026, 8, 13, 10, 30),
    )
    db.execute.return_value = MagicMock(
        scalars=MagicMock(return_value=MagicMock(all=lambda: [defect]))
    )

    result = await QualitySkill().execute(
        "query_defects",
        {"severity": "major", "limit": 10},
        db=db,
        factory_id="FAC_MECH_001",
    )

    assert result["count"] == 1
    assert result["defects"][0]["record_code"] == "DR-001"
    assert result["defects"][0]["disposition"] == "未处置"
    assert result["defects"][0]["description"] == ("尺寸超差" * 20)[:80]

    stmt = db.execute.call_args.args[0]
    sql = str(stmt)
    assert "defect_records.factory_id" in sql
    assert "defect_records.severity" in sql


@pytest.mark.asyncio
async def test_query_spc_anomalies_returns_summary_and_deviation():
    db = AsyncMock()
    point = SimpleNamespace(
        characteristic_code="C-01",
        characteristic_name="孔径",
        measured_value=10.8,
        ucl=10.5,
        lcl=9.5,
        cl=10.0,
        station_id="ST-01",
        measured_at=datetime(2026, 8, 13, 11, 0),
        measured_by="qc-01",
    )
    first = MagicMock(scalars=MagicMock(return_value=MagicMock(all=lambda: [point])))
    second = MagicMock(scalar_one_or_none=lambda: 3)
    db.execute.side_effect = [first, second]

    result = await QualitySkill().execute(
        "query_spc_anomalies", {"limit": 20}, db=db, factory_id="FAC_MECH_001",
    )

    assert result["factory_id"] == "FAC_MECH_001"
    assert result["total_7d"] == 3
    assert result["anomalies"][0]["characteristic"] == "孔径"
    assert result["anomalies"][0]["deviation"] == 0.3


def test_quality_skill_autodiscovery_and_definitions():
    registry = SkillRegistry()
    assert registry.autodiscover() >= 3
    skill = registry.get("quality")
    assert skill is not None
    assert skill.has_tool("query_defects")
    assert skill.has_tool("query_spc_anomalies")
