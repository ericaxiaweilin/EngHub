"""flush 层行归属观察器的判据（默认 observe，只记不拦）。

这里钉的是"什么算一条真实违例"：不是每张表都按厂分（没有 factory_id 列的表必须沉默），
超管与无调用者上下文也必须沉默 —— 否则日志会被噪声淹没，观察期就白跑。
"""
import types

from core.auth.security import (
    _UNSET, allowed_factory_ids, remember_request_identity, current_request_identity,
    tenant_write_violation,
)


def _row(factory="FAC_MECH_001", pk="row-1"):
    return types.SimpleNamespace(id=pk, factory_id=factory)


def _user(factory="FAC_MECH_001", active=None, superuser=False, username="u1"):
    return types.SimpleNamespace(username=username, factory_id=factory,
                                 active_factory_id=active, is_superuser=superuser)


class TestSilentCases:
    def test_table_without_factory_column_is_not_reported(self):
        obj = types.SimpleNamespace(id="x")          # 没有 factory_id 的表（码表/日志表等）
        assert tenant_write_violation(obj, {"FAC_MECH_001"}) is None

    def test_in_scope_row_is_not_reported(self):
        assert tenant_write_violation(_row("FAC_MECH_001"), {"FAC_MECH_001"}) is None

    def test_no_caller_context_is_silent(self):
        # 引擎循环/定时任务：没有"调用者"，不该被算成越界
        assert tenant_write_violation(_row("FAC_ELEC_DEMO_2026"), _UNSET) is None

    def test_superuser_is_unbounded(self):
        assert tenant_write_violation(_row("FAC_ELEC_DEMO_2026"), None) is None


class TestReportedCase:
    def test_out_of_scope_row_names_the_offender(self):
        v = tenant_write_violation(_row("FAC_ELEC_DEMO_2026", pk="plan-9"),
                                   {"FAC_MECH_001", "FAC_OTHER"})
        assert v is not None
        assert v["row_factory"] == "FAC_ELEC_DEMO_2026"
        assert v["id"] == "plan-9"
        assert v["allowed"] == ["FAC_MECH_001", "FAC_OTHER"]   # 排序稳定，便于聚合

    def test_row_with_null_factory_is_labeled_not_silently_allowed(self):
        v = tenant_write_violation(_row(None), {"FAC_MECH_001"})
        assert v is not None and v["row_factory"] == "(未标注)"


class TestRequestIdentity:
    def test_identity_is_taken_from_the_loaded_user_row(self):
        remember_request_identity(_user(active="FAC_ELEC_DEMO_2026"))
        ident = current_request_identity()
        assert ident["username"] == "u1"
        assert ident["allowed"] == allowed_factory_ids(_user(active="FAC_ELEC_DEMO_2026"))

    def test_superuser_identity_carries_unbounded_scope(self):
        remember_request_identity(_user(superuser=True, username="root"))
        assert current_request_identity()["allowed"] is None
