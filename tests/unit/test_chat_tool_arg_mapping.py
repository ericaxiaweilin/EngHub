"""聊天工具的参数映射：显式 0 与没填必须分得开。

这条测试存在的理由是本轮实测：`args.get("worklist_limit") or 12` 让"关掉活清单"这个开关
在聊天出口上根本不存在（实测传 0 仍然跑完那条扫 9 张表的普查，7.1 秒照付）。
"""
import asyncio

from api.services.chat_tools_service import _tool_query_safety_stock_authority

BASE = {"status": "ok", "factory_id": "FAC", "sources": [], "rulers": [],
        "disagreement": {}, "config_table_rows": 0, "trigger_fallbacks": {},
        "shortfall_units": {}, "ruler_spread_x": None, "auto_replenishment": {},
        "reading": [], "claim_guard": ""}


def _capture(monkeypatch):
    seen = []

    async def fake(db, fid, **kw):
        seen.append(kw)
        return dict(BASE, master_data_worklist=(None if kw.get("worklist_limit", 0) <= 0 else {"x": 1}))

    monkeypatch.setattr("core.mes.safety_stock_authority.safety_stock_authority", fake)
    return seen


def test_zero_means_do_not_run_the_worklist(monkeypatch):
    seen = _capture(monkeypatch)
    out = asyncio.run(_tool_query_safety_stock_authority(None, {"worklist_limit": 0}, "FAC"))
    assert seen[0]["worklist_limit"] == 0, "显式 0 被吃回默认值，开关就是假的"
    assert out["master_data_worklist"] is None


def test_absent_means_use_the_default(monkeypatch):
    seen = _capture(monkeypatch)
    out = asyncio.run(_tool_query_safety_stock_authority(None, {}, "FAC"))
    assert seen[0]["worklist_limit"] == 12
    assert out["master_data_worklist"] == {"x": 1}


def test_out_of_range_args_are_clamped_not_passed_through(monkeypatch):
    seen = _capture(monkeypatch)
    asyncio.run(_tool_query_safety_stock_authority(None, {"worklist_limit": 5000, "examples": 99}, "FAC"))
    assert seen[0]["worklist_limit"] == 200 and seen[0]["examples"] == 20
