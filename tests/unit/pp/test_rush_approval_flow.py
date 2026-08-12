"""
插单审批流测试（审计 Q4）：
- 决策权矩阵定级（determine_approval_level）
- 状态机全路径（draft→submitted→approved→executed）
- 角色越权审批拒绝
- 自我审批拒绝
- 驳回必填原因
- 紧急单无批文不触发调度（scheduling_agent 挂钩）

注：异步服务方法通过 asyncio.run() 包装为同步调用，规避
pytest-asyncio 1.3.0 + Python 3.14 的循环作用域不兼容。
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from core.pp.rush_approval_service import (
    RushApprovalService,
    determine_approval_level,
    _can_approve_level,
    LEVEL_ROLE_MAP,
)


def _run(coro):
    return asyncio.run(coro)


# ─────────────── 决策矩阵纯函数 ───────────────

def test_level1_low_impact_delay_under_1day():
    assert determine_approval_level(affected_orders=2, max_delay_days=0.5, rush_priority="urgent") == 1


def test_level2_delay_up_to_3days():
    assert determine_approval_level(affected_orders=3, max_delay_days=2.0, rush_priority="urgent") == 2


def test_level3_delay_over_3days():
    assert determine_approval_level(affected_orders=5, max_delay_days=4.0, rush_priority="urgent") == 3


def test_emergency_forces_level3_regardless_of_impact():
    assert determine_approval_level(affected_orders=0, max_delay_days=0.0, rush_priority="emergency") == 3


def test_high_priority_delayed_order_raises_to_level3():
    impact = {"delayed_orders": [{"priority": "urgent", "delay_days": 1}]}
    assert determine_approval_level(1, 0.5, "urgent", impact) == 3


def test_role_approval_level_mapping():
    assert LEVEL_ROLE_MAP[1] == "planner"
    assert LEVEL_ROLE_MAP[2] == "production_manager"
    assert LEVEL_ROLE_MAP[3] == "production_director"


# ─────────────── 角色校验 ───────────────

class FakeUser:
    def __init__(self, username="alice", role=None, is_superuser=False):
        self.username = username
        self.role = role
        self.is_superuser = is_superuser


def test_production_manager_can_approve_level2():
    user = FakeUser(username="boss", role="production_manager")
    assert _can_approve_level(user, 2) is True


def test_factory_manager_can_approve_level3():
    user = FakeUser(username="boss", role="factory_manager")
    assert _can_approve_level(user, 3) is True


def test_planner_cannot_approve_level3():
    user = FakeUser(username="planner", role="planner")
    assert _can_approve_level(user, 3) is False


def test_superuser_can_approve_any_level():
    user = FakeUser(username="admin", role="planner", is_superuser=True)
    assert _can_approve_level(user, 3) is True


# ─────────────── 审批引擎状态机 ───────────────

def _make_approval(**overrides):
    approval = MagicMock()
    approval.id = "RA-001"
    approval.approval_code = "RA-20260811-ABC123"
    approval.factory_id = "F001"
    approval.product_id = "P-01"
    approval.quantity = 100
    approval.due_date = None
    approval.rush_priority = "urgent"
    approval.impact_json = {"delayed_orders": [], "affected_orders": 0}
    approval.affected_orders = 0
    approval.max_delay_days = 0
    approval.process_hours = 2.5
    approval.recommendation = "可插单"
    approval.approval_level = 2
    approval.required_role = "production_manager"
    approval.status = "submitted"
    approval.applicant = "planner"
    approval.approver = None
    approval.approved_at = None
    approval.reject_reason = None
    approval.target_schedule_id = None
    approval.target_wo_id = None
    approval.executed_at = None
    approval.created_at = None
    approval.to_dict = MagicMock(return_value={"id": "RA-001", "status": "submitted", "approval_code": "RA-20260811-ABC123"})
    for k, v in overrides.items():
        setattr(approval, k, v)
    return approval


def _make_db(approval):
    db = MagicMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=res)
    db.get = AsyncMock(return_value=approval)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def test_submit_requires_draft():
    approval = _make_approval(status="submitted")
    svc = RushApprovalService(_make_db(approval))
    result = _run(svc.submit("RA-001", "planner"))
    assert result["success"] is False


def test_approve_self_application_rejected():
    approval = _make_approval(applicant="boss")
    svc = RushApprovalService(_make_db(approval))
    user = FakeUser(username="boss", role="production_manager")
    result = _run(svc.approve("RA-001", "boss", user, run_execute=False))
    assert result["success"] is False
    assert "同一人" in result["message"]


def test_approve_role_mismatch_rejected():
    approval = _make_approval(approval_level=3, required_role="production_director")
    svc = RushApprovalService(_make_db(approval))
    user = FakeUser(username="manager", role="production_manager")
    result = _run(svc.approve("RA-001", "manager", user, run_execute=False))
    assert result["success"] is False
    assert "角色权限不足" in result["message"]


def test_approve_success_and_executes_reschedule():
    approval = _make_approval()
    svc = RushApprovalService(_make_db(approval))
    user = FakeUser(username="boss", role="production_manager")

    with patch.object(svc, "_execute", new=AsyncMock(return_value={"success": True, "schedule_id": "S-999"})) as mock_exec:
        result = _run(svc.approve("RA-001", "boss", user))
    assert result["success"] is True
    mock_exec.assert_awaited_once()
    assert approval.status == "approved"
    assert approval.approver == "boss"


def test_approve_execute_failure_rolls_back_status():
    approval = _make_approval()
    svc = RushApprovalService(_make_db(approval))
    user = FakeUser(username="boss", role="production_manager")

    with patch.object(svc, "_execute", new=AsyncMock(return_value={"success": False, "message": "无产能"})) as mock_exec:
        result = _run(svc.approve("RA-001", "boss", user))
    assert result["success"] is False
    assert approval.status == "submitted"  # 回滚


def test_reject_requires_reason():
    approval = _make_approval()
    svc = RushApprovalService(_make_db(approval))
    user = FakeUser(username="boss", role="production_manager")
    result = _run(svc.reject("RA-001", "boss", user, reason=""))
    assert result["success"] is False
    assert "原因" in result["message"]


def test_reject_success():
    approval = _make_approval()
    svc = RushApprovalService(_make_db(approval))
    user = FakeUser(username="boss", role="production_manager")
    result = _run(svc.reject("RA-001", "boss", user, reason="产能不足"))
    assert result["success"] is True
    assert approval.status == "rejected"
    assert approval.reject_reason == "产能不足"


def test_cancel_only_applicant_or_superuser():
    approval = _make_approval(applicant="planner")
    svc = RushApprovalService(_make_db(approval))
    stranger = FakeUser(username="other", role="production_manager")
    result = _run(svc.cancel("RA-001", "other", stranger))
    assert result["success"] is False

    applicant = FakeUser(username="planner", role="planner")
    result = _run(svc.cancel("RA-001", "planner", applicant))
    assert result["success"] is True
    assert approval.status == "cancelled"


def test_create_from_eval_persists_draft():
    db = MagicMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=res)
    db.get = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    svc = RushApprovalService(db)
    with patch.object(svc, "_gen_code", return_value="RA-20260811-XYZ"):
        result = _run(svc.create_from_eval(
            factory_id="F001",
            product_id="P-01",
            quantity=100,
            due_date="2026-08-15",
            rush_priority="urgent",
            impact={"affected_orders": 3, "total_existing_orders": 8, "max_delay_hours": 48, "delayed_orders": []},
            rush={"process_hours": 2.5, "due_feasible": True},
            recommendation="可插单，影响可控",
            applicant="planner",
        ))
    assert result["status"] == "draft"
    assert result["approval_level"] == 2
    assert result["required_role"] == "production_manager"
    assert result["approval_code"] == "RA-20260811-XYZ"


# ─────────────── 调度代理挂钩 ───────────────

def _make_wo_agent(priority="urgent", product_id="P-01"):
    db = MagicMock()
    wo_row = MagicMock()
    wo_row._mapping = {"work_order_code": "WO-URGENT", "priority": priority, "planned_qty": 10, "planned_due": None, "product_id": product_id}
    wo_result = MagicMock()
    wo_result.first.return_value = wo_row

    async def fake_execute(stmt, params=None):
        return wo_result

    db.execute = fake_execute
    return db


def test_urgent_order_without_approval_does_not_reschedule():
    """紧急工单无已批准审批单时，应挂起待审，不触发全厂重排（Q4 核心）。"""
    from api.services.scheduling_agent_service import SchedulingAgent

    db = _make_wo_agent(priority="emergency")
    agent = SchedulingAgent(db)
    with patch("core.pp.rush_approval_service.RushApprovalService") as mock_svc_cls, \
         patch.object(agent, "auto_reschedule", new=AsyncMock()) as mock_resched, \
         patch.object(agent, "_append_to_schedule", new=AsyncMock()) as mock_append:
        mock_svc = mock_svc_cls.return_value
        mock_svc.find_approved_for_wo = AsyncMock(return_value=None)
        result = _run(agent.on_work_order_released("F001", "WO-1"))

    assert result["action"] == "pending_approval"
    mock_resched.assert_not_awaited()
    mock_append.assert_not_awaited()


def test_urgent_order_with_approval_triggers_reschedule():
    from api.services.scheduling_agent_service import SchedulingAgent

    db = _make_wo_agent(priority="urgent")
    approved = MagicMock()
    approved.approval_code = "RA-20260811-ABC123"

    agent = SchedulingAgent(db)
    with patch("core.pp.rush_approval_service.RushApprovalService") as mock_svc_cls, \
         patch.object(agent, "auto_reschedule", new=AsyncMock(return_value={"success": True})) as mock_resched:
        mock_svc = mock_svc_cls.return_value
        mock_svc.find_approved_for_wo = AsyncMock(return_value=approved)
        result = _run(agent.on_work_order_released("F001", "WO-1"))

    assert result["action"] == "reschedule"
    assert result["approval_code"] == "RA-20260811-ABC123"
    mock_resched.assert_awaited_once()
