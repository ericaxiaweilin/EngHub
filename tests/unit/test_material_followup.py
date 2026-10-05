"""缺料催办的合约：责任人从 HR 映射来、一张单一条、没依据就不开单。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import material_followup as mf


def _order(wo_id="wo-1", code="WO-CMP-1", model="1000461205", buy=0, make=2, short=13.0):
    return {
        "factory_id": "FAC_MECH_001",
        "work_order_id": wo_id, "work_order_code": code, "model_code": model,
        "wo_type": "component", "planned_qty": 24, "wo_status": "pending", "lines": [
            {"material_code": "1000472426", "material_name": "車架組", "unit": "PCS",
             "required": 24, "received": 0, "available": 11, "shortage": short,
             "level": 3, "parent_code": model, "item_type": "make" if make else "buy",
             "child_orders": None},
        ][:1],
        "shortage_total": short, "purchase_lines": buy, "make_lines": make,
    }


def _db(existing_payloads=(), owner=None, station="涂装车间", created=None):
    calls = []

    async def execute(statement, params=None):
        sql = str(statement)
        calls.append(sql)
        r = MagicMock()
        if "FROM followup_tasks" in sql and "payload->>'work_order_id'" in sql:
            r.scalars.return_value.all.return_value = list(existing_payloads)
        elif "route_station" in sql:
            r.all.return_value = [("wo-1", "ST-TZ-01")]
        elif "SELECT station_name FROM stations" in sql:
            r.scalar.return_value = station
        elif "FROM hr_employees" in sql:
            r.mappings.return_value.all.return_value = ([] if owner is None else [owner])
        else:
            r.mappings.return_value.all.return_value = []
            r.scalars.return_value.all.return_value = []
        return r

    db = MagicMock()
    db.execute = execute
    db.commit = AsyncMock()
    db.calls = calls
    return db


OWNER = {"name": "崔强芳", "employee_code": "MEC-0546", "position": "组长", "department": "生产一部"}


@pytest.mark.asyncio
async def test_owner_comes_from_hr_station_leader_even_when_names_differ_by_suffix(monkeypatch):
    """stations 写"涂装车间"、HR 写"涂装"：两种叫法都要能落到同一个组长。"""
    async def fake_group(db, fid, models, limit):
        return [_order()]
    async def fake_owner(db, fid, role, station_name):
        assert station_name == "涂装车间"
        assert role == "make"
        return {"assigned_to": "崔强芳", "owner_basis": "生产一部／组长（MEC-0546）"}
    monkeypatch.setattr(mf, "_group_per_order", fake_group)
    monkeypatch.setattr(mf, "_owner", fake_owner)
    created = []

    async def fake_create(db, factory_id, created_by, title, **kw):
        created.append((title, kw.get("assigned_to"), kw.get("agent_key"), kw.get("payload")))
        return {"task_id": "t1"}
    monkeypatch.setattr("api.services.followup_task_service.create_task", fake_create)

    out = await mf.chase_material_shortages(_db(), "FAC_MECH_001", limit=5, apply=True)
    assert out["created"] == 1 and out["unassigned"] == 0
    title, assigned, agent, payload = created[0]
    assert assigned == "崔强芳" and agent == "pmc_agent" and "催料｜WO-CMP-1" in title
    ev = json.loads(payload)
    assert ev["category"] == "material_shortage" and ev["work_order_id"] == "wo-1"
    assert ev["lines"][0]["shortage"] == 13.0 and ev["lines"][0]["item_type"] == "make"
    assert "齐套快照" in ev["blocked_by"]


@pytest.mark.asyncio
async def test_no_hr_owner_still_opens_the_task_but_never_invents_a_person(monkeypatch):
    async def fake_group(db, fid, models, limit):
        return [_order()]
    monkeypatch.setattr(mf, "_group_per_order", fake_group)
    monkeypatch.setattr(mf, "_owner", AsyncMock(return_value={"assigned_to": None,
                                                              "owner_basis": "HR 里没有工位「涂装车间」的组长/技术员在岗人员"}))
    captured = {}

    async def fake_create(db, factory_id, created_by, title, **kw):
        captured.update(kw)
        return {"task_id": "t1"}
    monkeypatch.setattr("api.services.followup_task_service.create_task", fake_create)

    out = await mf.chase_material_shortages(_db(), "FAC_MECH_001", limit=5, apply=True)
    assert out["created"] == 1 and out["unassigned"] == 1
    assert captured.get("assigned_to") is None
    assert captured.get("item_type") == "followup"
    assert "HR 里没有" in captured.get("block_reason", "")


@pytest.mark.asyncio
async def test_one_open_chase_per_order_and_dry_run_creates_nothing(monkeypatch):
    orders = [_order(wo_id="wo-1"), _order(wo_id="wo-2")]

    async def fake_group(db, fid, models, limit):
        return orders
    monkeypatch.setattr(mf, "_group_per_order", fake_group)
    monkeypatch.setattr(mf, "_owner", AsyncMock(return_value={"assigned_to": "崔强芳",
                                                             "owner_basis": "生产一部／组长"}))
    calls = []

    async def fake_create(db, factory_id, created_by, title, **kw):
        calls.append(kw.get("payload"))
        return {"task_id": "t"}
    monkeypatch.setattr("api.services.followup_task_service.create_task", fake_create)

    # wo-1 已经有一条未关闭的催办 → 不许再挂第二条（890 万行申请那次的教训）
    db = _db(existing_payloads=["wo-1"])
    out = await mf.chase_material_shortages(db, "FAC_MECH_001", limit=5, apply=True)
    assert out["skipped_open"] == 1 and out["created"] == 1
    assert len(calls) == 1 and json.loads(calls[0])["work_order_id"] == "wo-2"

    dry = await mf.chase_material_shortages(_db(), "FAC_MECH_001", limit=5, apply=False)
    assert dry["created"] == 0 and dry["dry_run"] is True
    assert len(calls) == 1, "预演不许创建任何待办"


def test_station_alias_normalization_drops_the_workshop_suffix():
    assert mf._station_aliases("涂装车间") == ["涂装车间", "涂装"]
    assert mf._station_aliases("ST-ASSY-LINE") == ["ST-ASSY-LINE", "ST-ASSY-LINE"]
    assert mf._station_aliases(None) == []
