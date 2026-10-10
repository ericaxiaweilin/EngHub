"""对象归属闸的纯判据测试（不需要 DB：只打 allowed_factory_ids 与 _require_object_factory）。

这两处是 Unit F 的判据本体 —— 跨厂写要拦、同厂写要放、超管不限、无身份的服务内调用不受影响。
"""
import types

import pytest

from core.auth.security import allowed_factory_ids, ensure_row_in_tenant
from api.services.work_order_service import WorkOrderService, WoTenantError


def _user(username="u", factory="FAC_MECH_001", active=None, superuser=False):
    return types.SimpleNamespace(username=username, factory_id=factory,
                                 active_factory_id=active, is_superuser=superuser)


def _wo(code="WO-1", factory="FAC_MECH_001"):
    return types.SimpleNamespace(id="id-1", work_order_code=code, factory_id=factory)


class TestEnsureRowInTenant:
    """路由侧的行归属判据（pp 计划这类"按 id 取行就改"的路由用它）。"""

    def test_same_factory_passes(self):
        ensure_row_in_tenant(_wo(factory="FAC_MECH_001"), _user(), "取消计划")

    def test_foreign_factory_is_403_naming_the_row_and_scope(self):
        from fastapi import HTTPException
        u = _user(username="pp_planner_09")
        with pytest.raises(HTTPException) as exc:
            ensure_row_in_tenant(_wo(factory="FAC_ELEC_DEMO_2026"), u, "取消计划", label="计划")
        assert exc.value.status_code == 403
        text = str(exc.value.detail)
        assert "取消计划" in text
        assert "FAC_ELEC_DEMO_2026" in text      # 那行属于哪个厂
        assert "pp_planner_09" in text          # 谁在动
        assert "FAC_MECH_001" in text           # 他有权进哪些厂

    def test_superuser_and_in_process_calls_are_unbounded(self):
        ensure_row_in_tenant(_wo(factory="FAC_ELEC_DEMO_2026"), _user(superuser=True), "下达计划")
        ensure_row_in_tenant(_wo(factory="FAC_ELEC_DEMO_2026"), None, "下达计划")

    def test_row_without_factory_label_is_blocked_for_normal_user(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            ensure_row_in_tenant(_wo(factory=None), _user(), "批准变更请求")


class TestAllowedFactoryIds:
    def test_superuser_is_unbounded(self):
        assert allowed_factory_ids(_user(superuser=True)) is None

    def test_normal_user_gets_home_factory(self):
        assert allowed_factory_ids(_user()) == {"FAC_MECH_001"}

    def test_switched_active_factory_is_also_allowed(self):
        # active_factory_id 只能由 /factory/switch（超管/开发账户）写入，所以不是自助后门
        u = _user(active="FAC_ELEC_DEMO_2026")
        assert allowed_factory_ids(u) == {"FAC_MECH_001", "FAC_ELEC_DEMO_2026"}

    def test_none_user_is_unbounded_for_in_process_calls(self):
        assert allowed_factory_ids(None) is None


class TestRequireObjectFactory:
    def setup_method(self):
        self.svc = WorkOrderService(db=None)

    def test_same_factory_passes(self):
        self.svc._require_object_factory(_wo(), _user(), "取消")

    def test_foreign_factory_raises_with_both_sides_named(self):
        u = _user(username="wf_lead_01")
        with pytest.raises(WoTenantError) as exc:
            self.svc._require_object_factory(_wo(code="WO-X", factory="FAC_ELEC_DEMO_2026"),
                                             u, "取消")
        text = str(exc.value)
        # 三类信息都要在：动了哪张单、那单属于哪个厂、动手的人有权进哪些厂
        assert "WO-X" in text
        assert "FAC_ELEC_DEMO_2026" in text
        assert "wf_lead_01" in text
        assert "FAC_MECH_001" in text

    def test_superuser_may_act_cross_factory(self):
        self.svc._require_object_factory(_wo(factory="FAC_ELEC_DEMO_2026"),
                                         _user(superuser=True), "取消")

    def test_in_process_call_without_user_is_not_blocked(self):
        # 引擎/定时任务在进程内调用不带身份，不能把它当越权拦掉
        self.svc._require_object_factory(_wo(factory="FAC_ELEC_DEMO_2026"), None, "取消")

    def test_unassigned_account_blocks_every_target(self):
        u = _user(factory=None, active=None)
        assert allowed_factory_ids(u) == set()
        with pytest.raises(WoTenantError):
            self.svc._require_object_factory(_wo(factory="FAC_MECH_001"), u, "取消")

    def test_row_without_factory_label_is_blocked_for_normal_user(self):
        with pytest.raises(WoTenantError):
            self.svc._require_object_factory(_wo(factory=None), _user(), "取消")
