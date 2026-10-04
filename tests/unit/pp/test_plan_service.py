"""生产计划(PP)服务单元测试 - 覆盖创建、状态流转、列表全流程。

用内存 store 模拟 _get_plan_by_id/_update_plan/_insert_plan 的读写语义
（旧版用静态 dict mock，状态机根本转不动，7 个红全是 mock 失真）。
只测真实存在的方法与真实的状态约束。
"""
import copy
from datetime import datetime

import pytest
from unittest.mock import MagicMock, AsyncMock
from types import SimpleNamespace

from core.pp.plan import MPSService, PlanStatus, PlanType, CustomerLevel


@pytest.fixture(scope="function")
def live_plan_service():
    """带内存 store 的 MPSService：读写直通，还原真实状态机语义。"""
    svc = MPSService(MagicMock())
    store = {}

    async def _get(plan_id):
        return copy.deepcopy(store.get(plan_id))

    async def _update(plan_id, updates):
        if plan_id not in store:
            return False
        store[plan_id].update({k: v for k, v in updates.items() if v is not None})
        return True

    async def _insert(plan_data):
        pid = plan_data.get("id") or "plan-001"
        data = dict(plan_data)
        data["id"] = pid
        data.setdefault("plan_code", "MPS-F001-001")
        data.setdefault("created_at", datetime(2026, 8, 1))
        store[pid] = data
        return pid

    svc._get_plan_by_id = _get
    svc._update_plan = _update
    svc._insert_plan = _insert
    svc.detect_capacity_conflict = AsyncMock(return_value=[])
    return svc, store


def _seed(store, pid="plan-001", status="draft"):
    store[pid] = {
        "id": pid, "plan_code": "MPS-F001-001", "factory_id": "F001",
        "status": status,
    }
    return pid


@pytest.mark.asyncio
async def test_plan_create_valid(live_plan_service):
    svc, store = live_plan_service
    result = await svc.create_plan(
        factory_id="F001", product_id="PROD-001", quantity=500,
        required_date=datetime(2026, 8, 15), plan_type=PlanType.MPS.value,
        sales_order_id="SO-001", customer_level=CustomerLevel.A.value,
        priority=50, created_by="scheduler",
    )
    assert result["id"] is not None
    assert result["factory_id"] == "F001"
    assert result["quantity"] == 500
    assert result["status"] == PlanStatus.DRAFT.value
    assert result["customer_level"] == CustomerLevel.A.value
    assert result["priority"] == 50
    assert result["plan_code"] is not None
    assert result["created_at"] is not None


@pytest.mark.asyncio
async def test_plan_get_not_found(live_plan_service):
    svc, _ = live_plan_service
    assert await svc.get_plan("missing") is None


def _plan_obj(**kw):
    base = dict(
        id="p1", plan_code="MPS-F001-001", factory_id="F001", product_id="PR", sales_order_id=None,
        quantity=10, required_date=None, due_date=None, customer_level="B",
        priority=50, priority_score=90.0, status="draft", station_id=None,
        scheduled_start_date=None, scheduled_end_date=None, mrp_status=None,
        created_by="t", updated_by="t", confirmed_by=None, released_by=None,
        confirmed_at=None, released_at=None, created_at=None, updated_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_plan_list_by_factory(live_plan_service):
    svc, _ = live_plan_service
    res = MagicMock()
    res.scalars.return_value.all.return_value = [
        _plan_obj(id="p1", priority_score=90.0),
        _plan_obj(id="p2", status="released", priority_score=85.0),
    ]
    svc.db.execute = AsyncMock(return_value=res)
    results = await svc.list_plans(factory_id="F001", limit=100)
    assert len(results) == 2
    assert all(r["factory_id"] == "F001" for r in results)


@pytest.mark.asyncio
async def test_plan_confirm_success(live_plan_service):
    svc, store = live_plan_service
    _seed(store, status="draft")
    result = await svc.confirm_plan(plan_id="plan-001", confirmed_by="manager")
    assert result["status"] == "confirmed"
    assert result["confirmed_by"] == "manager"


@pytest.mark.asyncio
async def test_plan_confirm_invalid_status(live_plan_service):
    svc, store = live_plan_service
    _seed(store, status="released")
    with pytest.raises(ValueError) as exc_info:
        await svc.confirm_plan(plan_id="plan-001", confirmed_by="manager")
    assert "只有草稿状态的计划可以确认" in str(exc_info.value)


@pytest.mark.asyncio
async def test_plan_release_success(live_plan_service):
    svc, store = live_plan_service
    _seed(store, status="confirmed")
    result = await svc.release_plan(plan_id="plan-001", released_by="planner", trigger_aps=False)
    assert result["status"] == "released"
    assert result["released_by"] == "planner"


@pytest.mark.asyncio
async def test_plan_release_invalid_status(live_plan_service):
    svc, store = live_plan_service
    _seed(store, status="draft")
    with pytest.raises(ValueError) as exc_info:
        await svc.release_plan(plan_id="plan-001", released_by="planner")
    assert "只有已确认的计划可以下达" in str(exc_info.value)


@pytest.mark.asyncio
async def test_plan_complete_success(live_plan_service):
    svc, store = live_plan_service
    _seed(store, status="released")
    result = await svc.complete_plan(plan_id="plan-001", completed_by="operator")
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_plan_cancel_success(live_plan_service):
    svc, store = live_plan_service
    _seed(store, status="in_progress")
    result = await svc.cancel_plan(plan_id="plan-001", cancelled_by="supervisor", reason="生产变更")
    assert result["status"] == "cancelled"
    assert result["cancelled_by"] == "supervisor"


@pytest.mark.asyncio
async def test_plan_cancel_invalid_state(live_plan_service):
    svc, store = live_plan_service
    _seed(store, status="cancelled")
    with pytest.raises(ValueError):
        await svc.cancel_plan(plan_id="plan-001", cancelled_by="x")
