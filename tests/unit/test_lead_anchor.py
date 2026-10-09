"""提前期锚定：唯一出处、缺测要说明、锚定问题要挂到待回答清单上。"""

import pytest

pytestmark = [pytest.mark.unit]

from core.mes import measurement_priority as mp
from core.mes import factory_rules as fr


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _Db:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *a, **kw):
        return _Rows(self._rows)


def _row(code, ledger, measured, n):
    return {"material_code": code, "ledger_days": ledger, "n": n,
            "measured_days": measured, "ratio": measured / ledger if ledger else None}


def test_lead_ratio_census_excludes_zero_days_and_single_po_rows():
    import asyncio

    db = _Db([_row("RM-Z", 10, 0, 4),          # 实测 0 天：收货记录缺失，不是快
              _row("RM-A", 15, 95.5, 4),        # 6.37×
              _row("RM-B", 7, 111.5, 2),        # 15.93×
              _row("RM-C", 15, 17.5, 4),        # 1.17×
              _row("RM-D", 20, 40, 1)])         # 只有 1 张单 → 样本不是依据
    out = asyncio.run(mp.lead_ratio_census(db, "FAC"))
    assert (out["rows"], out["zero_ratio_rows"]) == (5, 1)
    assert out["reliable_rows"] == 3, "po≥2 且非零才算依据"
    assert out["anchor"] and out["anchor"] > 1.0, "台账偏乐观 → 锚定要往上挪"
    assert out["median_all"] != out["median_nonzero"] or out["rows"] == out["reliable_rows"]
    assert all(e["po_count"] >= 2 for e in out["examples"])
    assert "不肯把缺失当观测" in out["caveat"]


def test_lead_ratio_census_says_so_when_nothing_is_measured():
    import asyncio

    out = asyncio.run(mp.lead_ratio_census(_Db([]), "FAC"))
    assert out["rows"] == 0 and out["anchor"] is None
    assert out["median_nonzero"] is None and out["examples"] == []


def test_anchor_question_is_registered_only_when_there_is_an_anchor(monkeypatch):
    import asyncio

    import asyncio

    async def fake_cov(db, fid):
        return {"capacity_unit_ambiguous": False, "station_capacity_rows": 10, "stations": 10,
                "station_capacity_hours_min": 0.07, "station_capacity_hours_max": 54.5,
                "capacity_unit_mix": [], "reading": "…"}

    async def fake_eff(db, fid):
        return {"rows": [], "note": "…"}

    async def fake_cross(db, fid):
        return {"verdict": {}}

    monkeypatch.setattr("core.mes.capacity_math.efficiency_basis_census", fake_eff)
    monkeypatch.setattr("core.mes.data_evidence.line_claim_coverage", fake_cov)
    monkeypatch.setattr("core.mes.plant_architecture.capacity_cross_check", fake_cross)

    _rules(monkeypatch, None)
    strong = {"rows": 12, "zero_ratio_rows": 2, "median_all": 7.17, "median_nonzero": 7.17,
              "p25_nonzero": 3.0, "p75_nonzero": 15.93, "min_nonzero": 0.05, "max_nonzero": 38.7,
              "reliable_rows": 9, "anchor": 7.17,
              "examples": [{"material_code": "RM-CAST-01", "ledger_days": 15,
                            "measured_median_days": 95.5, "po_count": 4, "ratio": 6.37}],
              "caveat": "…"}

    async def with_anchor(db, fid):
        return strong

    monkeypatch.setattr(mp, "lead_ratio_census", with_anchor)
    res = asyncio.run(fr.capacity_questions(None, "FAC"))
    q = [x for x in res["questions"] if x.get("topic") == "lead_time_anchor"]
    assert len(q) == 1 and "7.17" in q[0]["question"]
    assert "sim-lead-calibration" in q[0]["why_it_matters"]
    assert q[0]["record_as"]["subject"] == "lead_time_anchor"
    assert "RM-CAST-01" in q[0]["prefilled_evidence"]

    empty = dict(strong, rows=0, anchor=None, median_nonzero=None, examples=[], reliable_rows=0,
                 zero_ratio_rows=0, median_all=None)

    async def no_data(db, fid):
        return empty

    monkeypatch.setattr(mp, "lead_ratio_census", no_data)
    res2 = asyncio.run(fr.capacity_questions(None, "FAC"))
    hidden = [x for x in res2["questions"] if x.get("topic") == "lead_time_anchor"]
    assert not hidden, "没有实测行就不许挂一条看起来像依据的问题"

    partial = dict(empty, rows=3, zero_ratio_rows=3)

    async def only_zeros(db, fid):
        return partial

    monkeypatch.setattr(mp, "lead_ratio_census", only_zeros)
    res3 = asyncio.run(fr.capacity_questions(None, "FAC"))
    q3 = [x for x in res3["questions"] if x.get("topic") == "lead_time_anchor"]
    assert q3 and "没有可用校准比" in q3[0]["question"], "有行但全是 0 天 → 要说明而不是不提"


CEN = {"factory_id": "FAC", "rows": 12, "zero_ratio_rows": 2, "median_all": 7.17,
       "median_nonzero": 9.033, "p25_nonzero": 3.0, "p75_nonzero": 15.79,
       "min_nonzero": 0.05, "max_nonzero": 38.7, "reliable_rows": 9, "anchor": 9.033,
       "examples": [], "caveat": "…"}
NO_CEN = dict(CEN, rows=0, anchor=None, median_nonzero=None, reliable_rows=0, zero_ratio_rows=0)


def _rules(monkeypatch, verdict=None):
    from core.mes import factory_rules as fr

    async def fake(db, fid):
        if verdict is None:
            return {}
        return {"lead_time_anchor": {"subject": "lead_time_anchor", "verdict": verdict,
                                     "status": "declared", "statement": f"锚定={verdict}"}}

    monkeypatch.setattr(fr, "binding_rules", fake)


def _census(monkeypatch, cen=CEN):
    from core.mes import measurement_priority as mp

    async def fake(db, fid):
        return dict(cen)

    monkeypatch.setattr(mp, "lead_ratio_census", fake)


def test_resolve_lead_anchor_follows_the_declared_rule_and_never_guesses(monkeypatch):
    import asyncio
    from api.services import sim_sensitivity as ss

    session = object()      # 真会话的位置放个哨兵：db=None 现在表示"读不到厂规"，有专门的出口
    _rules(monkeypatch, None)
    _census(monkeypatch)
    out = asyncio.run(ss.resolve_lead_anchor(session, "FAC"))
    assert out["center"] == 1.0 and out["in_force"] == "ledger" and out["question_open"] is True
    assert "9.033" in out["basis"] and "lead_time_anchor" in out["basis"]

    _rules(monkeypatch, "measured")
    out = asyncio.run(ss.resolve_lead_anchor(session, "FAC"))
    assert out["center"] == 9.033 and out["calibrated"] is True

    _census(monkeypatch, NO_CEN)                     # 说按实测锚，但没有任何可用实测
    out = asyncio.run(ss.resolve_lead_anchor(session, "FAC"))
    assert out["center"] == 1.0 and out["in_force"] == "ledger"
    assert "不能假装锚过" in out["basis"]

    _census(monkeypatch)
    _rules(monkeypatch, "hybrid")
    out = asyncio.run(ss.resolve_lead_anchor(session, "FAC"))
    assert out["center"] == 1.0 and "整批中心" in out["basis"], "实现不了的口径要说不实现，不许猜一个数"

    _rules(monkeypatch, "ledger")
    out = asyncio.run(ss.resolve_lead_anchor(session, "FAC"))
    assert out["center"] == 1.0 and "未校准" in out["basis"]


def test_risk_setup_uses_the_declared_centre_unless_the_caller_overrides_it(monkeypatch):
    import asyncio
    from api.services import sim_sensitivity as ss

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 70.0, "hours_error_band": 0.05,
                            "components": {"lead_time": {"score": 1.0},
                                           "hours": {"score": 1.0, "basis": "route_standard_hours"}}}]}

    async def anchored(db, fid, *, census=None):
        return {"center": 3.0, "in_force": "measured", "calibrated": True, "anchor": 3.0,
                "basis": "厂里定的口径：按实测中位 3× 锚", "reliable_rows": 9, "zero_ratio_rows": 2}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "resolve_lead_anchor", anchored)

    setup = asyncio.run(ss._risk_setup(None, "FAC", ["M-1"], samples=8))
    assert setup["lead_center"] == 3.0 and setup["lead_anchor"]["in_force"] == "measured"
    assert all(2.8 <= d["lead_multiplier"] <= 3.2 for d in setup["draws"]), "抽样中心真的挪了"

    forced = asyncio.run(ss._risk_setup(None, "FAC", ["M-1"], samples=8, lead_center=1.0))
    assert forced["lead_anchor"]["in_force"] == "explicit", "显式 what-if 不读厂规，也不冒充厂规"


def test_risk_reading_stays_a_string_and_names_the_anchor(monkeypatch):
    import asyncio
    from api.services import sim_sensitivity as ss

    from datetime import date, timedelta

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 100, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 70.0, "hours_error_band": 0.05,
                            "components": {"lead_time": {"score": 1.0},
                                           "hours": {"score": 1.0, "basis": "route_standard_hours"}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None):
        d = perturb or {}
        late = round(10.0 * float(d.get("lead_multiplier", 1.0)) - 25.0, 1)
        return {"finish_date": str(date(2026, 11, 1) + timedelta(days=int(late))),
                "days_late_worst": late, "days_late_per_model": {"M-1": late},
                "labor_cost_usd": 10.0, "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "binding": "material_arrival", "bottleneck_parts": {}, "lines_used": [],
                "material_arrival_days": {}, "capacity_line_declared_max": 0.0,
                "crew_before_staffing_sum": 10.0, "crew_effective_sum": 9.0}

    async def anchored(db, fid, *, census=None):
        return {"center": 2.0, "in_force": "measured", "calibrated": True, "anchor": 2.0,
                "basis": "厂里定的口径：按实测中位 2× 锚"}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)
    monkeypatch.setattr(ss, "resolve_lead_anchor", anchored)

    out = asyncio.run(ss.schedule_risk(None, "FAC", ["M-1"], samples=8, seed=4))
    assert out["status"] == "ok" and isinstance(out["reading"], str), "reading 是字符串，渲染点在原样打印它"
    assert "锚定：按实测 2×" in out["reading"] and "厂里定的口径" in out["reading"]
    assert out["lead_center_used"] == 2.0 and out["lead_anchor"]["in_force"] == "measured"


def test_anchor_question_disappears_once_declared(monkeypatch):
    import asyncio
    from core.mes import factory_rules as fr

    _census(monkeypatch)

    async def fake_cov(db, fid):
        return {"capacity_unit_ambiguous": False, "station_capacity_rows": 10, "stations": 10,
                "station_capacity_hours_min": 0.07, "station_capacity_hours_max": 54.5,
                "capacity_unit_mix": [], "reading": "…"}

    async def fake_eff(db, fid):
        return {"rows": [], "note": "…"}

    async def fake_cross(db, fid):
        return {"verdict": {}}

    monkeypatch.setattr("core.mes.capacity_math.efficiency_basis_census", fake_eff)
    monkeypatch.setattr("core.mes.data_evidence.line_claim_coverage", fake_cov)
    monkeypatch.setattr("core.mes.plant_architecture.capacity_cross_check", fake_cross)

    _rules(monkeypatch, None)
    res = asyncio.run(fr.capacity_questions(None, "FAC"))
    assert [q for q in res["questions"] if q["topic"] == "lead_time_anchor"]
    assert res["declared_anchor"] is None

    _rules(monkeypatch, "measured")
    res2 = asyncio.run(fr.capacity_questions(None, "FAC"))
    assert not [q for q in res2["questions"] if q["topic"] == "lead_time_anchor"], "定了口径就不再问"
    assert res2["declared_anchor"]["verdict"] == "measured" and res2["declared_anchor"]["anchor_available"]
