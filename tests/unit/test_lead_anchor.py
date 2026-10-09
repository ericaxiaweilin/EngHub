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

    async def no_map(db, fid, *, min_po=2):
        return {"factors": {}, "measured_days": {}, "codes": 0,
                "ledger_rows_with_lead": 4, "coverage": 0.0, "min_po": min_po, "caveat": "…"}

    monkeypatch.setattr("core.mes.measurement_priority.measured_lead_factors", no_map)
    out = asyncio.run(ss.resolve_lead_anchor(session, "FAC"))
    # 口径是 hybrid 但一条都没量过：落回台账，可实测锚必须还带在身上，读数才说得出"偏 9.033×"
    assert out["center"] == 1.0 and out["in_force"] == "ledger" and out["anchor"] == 9.033
    assert "不假装做过校准" in out["basis"], "空 map 不是 hybrid 成功了，要说清按定义就是全按台账"

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

    async def factors(db, fid, *, min_po=2):
        return {"factors": {"RM-A": 6.4}, "measured_days": {"RM-A": 95.5}, "codes": 1,
                "ledger_rows_with_lead": 100, "coverage": 0.01, "min_po": min_po,
                "caveat": "覆盖 1/100 行"}

    monkeypatch.setattr("core.mes.measurement_priority.measured_lead_factors", factors)

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


def test_hybrid_anchor_uses_the_own_ratio_per_measured_code(monkeypatch):
    import asyncio
    from api.services import sim_sensitivity as ss

    async def factors(db, fid, *, min_po=2):
        return {"factors": {"RM-A": 6.37, "RM-B": 1.17}, "measured_days": {"RM-A": 95.5},
                "codes": 2, "ledger_rows_with_lead": 8, "coverage": 0.25, "min_po": min_po,
                "caveat": "覆盖 2/8 行"}

    _rules(monkeypatch, "hybrid")
    _census(monkeypatch)
    monkeypatch.setattr("core.mes.measurement_priority.measured_lead_factors", factors)
    out = asyncio.run(ss.resolve_lead_anchor(object(), "FAC"))
    assert out["in_force"] == "hybrid" and out["center"] == 1.0 and out["calibrated"] is True
    assert out["factor_map"] == {"RM-A": 6.37, "RM-B": 1.17}
    assert out["map_codes"] == 2 and out["map_coverage"] == 0.25
    assert "2/8" in out["basis"] or "覆盖" in out["basis"], "hybrid 必须报覆盖多少，不报成一个总数"


def test_hybrid_without_any_measurement_falls_back_saying_so(monkeypatch):
    import asyncio
    from api.services import sim_sensitivity as ss

    async def empty_factors(db, fid, *, min_po=2):
        return {"factors": {}, "measured_days": {}, "codes": 0, "ledger_rows_with_lead": 8,
                "coverage": 0.0, "min_po": min_po, "caveat": "…"}

    _rules(monkeypatch, "hybrid")
    _census(monkeypatch)
    monkeypatch.setattr("core.mes.measurement_priority.measured_lead_factors", empty_factors)
    out = asyncio.run(ss.resolve_lead_anchor(object(), "FAC"))
    assert out["in_force"] == "ledger" and "不假装做过校准" in out["basis"]


def test_build_kit_applies_the_per_code_factor_on_top_of_the_batch_multiplier():
    """hybrid 的落点：量过的按自己的实测、没量过的按台账，整批乘子另算。"""
    from api.services.virtual_run import build_kit

    bom = [{"material_code": "RM-A", "qty_per_unit": 1, "make_or_buy": "外购",
            "lead_time_days": "15", "default_supplier": "甲", "unit_price": None},
           {"material_code": "RM-B", "qty_per_unit": 1, "make_or_buy": "外购",
            "lead_time_days": "15", "default_supplier": "乙", "unit_price": None}]
    stock = {"RM-A": 0.0, "RM-B": 0.0}
    plain = build_kit(bom, 10.0, stock, 0)
    hybrid = build_kit(bom, 10.0, stock, 0, lead_factor_map={"RM-A": 6.0})
    days = {k["material_code"]: k["arrival_day"] for k in plain["lines"]}
    hd = {k["material_code"]: k["arrival_day"] for k in hybrid["lines"]}
    assert days["RM-A"] == 15 and days["RM-B"] == 15
    assert hd["RM-A"] == 90, "量过的按自己 6× 实测"
    assert hd["RM-B"] == 15, "没量过的保持台账，不许顺手一起放大"
    both = build_kit(bom, 10.0, stock, 0, lead_multiplier=2.0, lead_factor_map={"RM-A": 3.0})
    bd = {k["material_code"]: k["arrival_day"] for k in both["lines"]}
    assert (bd["RM-A"], bd["RM-B"]) == (90, 30), "整批乘子与料号乘子是相乘的两件事"


def test_calibration_impact_reports_the_three_anchors_separately(monkeypatch):
    import asyncio
    from datetime import date, timedelta

    from api.services import sim_sensitivity as ss

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 600, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 70.0, "hours_error_band": 0.05,
                            "components": {"lead_time": {"score": 1.0},
                                           "hours": {"score": 1.0, "basis": "route_standard_hours"}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None, factor_map=None):
        d = perturb or {}
        mult = float(d.get("lead_multiplier", 1.0)) * float((factor_map or {}).get("RM-A", 1.0))
        late = round(10.0 * mult - 20.0, 1)
        return {"finish_date": str(date(2026, 11, 1) + timedelta(days=int(late))),
                "days_late_worst": late, "days_late_per_model": {"M-1": late},
                "labor_cost_usd": 1.0, "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "binding": "material_arrival", "bottleneck_parts": {}, "lines_used": [],
                "material_arrival_days": {}, "capacity_line_declared_max": 0.0,
                "crew_before_staffing_sum": 1.0, "crew_effective_sum": 1.0}

    async def cal(db, fid):
        return {"rows": 6, "zero_ratio_rows": 1, "median_ratio_all_rows": 3.0,
                "median_ratio_nonzero": 4.0, "reliable_rows": 4, "anchor": 4.0,
                "spread_nonzero": {"p25": 2.0, "p75": 6.0, "min": 1.2, "max": 9.0},
                "examples": [], "caveat": "…"}

    # 整批锚固定在 4.0×，只换 map 里那一个料号的倍数：1.5 落在台账与整批之间，
    # 8.0 已经超过整批 —— 读数必须按实测大小换说法，不能固定写"hybrid 更保守"
    holder = {"factor": 1.5}

    async def factors(db, fid, *, min_po=2):
        return {"factors": {"RM-A": holder["factor"]}, "measured_days": {}, "codes": 1,
                "ledger_rows_with_lead": 3, "coverage": 1 / 3, "min_po": min_po, "caveat": "…"}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)
    monkeypatch.setattr(ss, "lead_calibration", cal)
    monkeypatch.setattr("core.mes.measurement_priority.measured_lead_factors", factors)

    out = asyncio.run(ss.calibration_impact(None, "FAC", ["M-1"], samples=8, seed=3))
    assert out["status"] == "ok"
    assert [m["mode"] for m in out["modes"]] == ["ledger", "global_measured", "hybrid"]
    modes = {m["mode"]: m for m in out["modes"]}
    for m in modes.values():
        assert m["p50"] and m["p90"] and m["p_on_time"] is not None, "每一档都得有自己的数"
    assert modes["ledger"]["p90_shift_days"] == 0
    gm = modes["global_measured"]["p90_shift_days"]
    hy = modes["hybrid"]["p90_shift_days"]
    assert 0 < hy < gm, f"map 只放大 1 个料号（1.5×），必须落在台账与整批锚(4×)之间：{hy} vs {gm}"
    assert abs(out["hybrid"]["coverage"] - 1 / 3) < 1e-9
    assert out["hybrid"]["map_codes"] == 1 and out["hybrid"]["ledger_rows_with_lead"] == 3
    assert any("料号级 hybrid" in x for x in out["reading"])
    gm50 = modes["global_measured"]["p50_shift_days"]
    hy50 = modes["hybrid"]["p50_shift_days"]
    diff_line = [x for x in out["reading"] if x.startswith("差值（都相对按台账")]
    assert diff_line and f"整批锚 P50 +{gm50} 天" in diff_line[0] and f"hybrid P50 +{hy50} 天" in diff_line[0], \
        "差值要带符号、并说清各自相对按台账挪了几天"

    holder["factor"] = 8.0
    over = asyncio.run(ss.calibration_impact(None, "FAC", ["M-1"], samples=8, seed=3))
    hy2 = {m["mode"]: m for m in over["modes"]}["hybrid"]["p90_shift_days"]
    assert hy2 > gm, "量过的这件比中位还狠时 hybrid 要能超过整批锚，不许被中心值夹住"
    assert any("偏得比中位还狠" in x for x in over["reading"]), "反超要说在明处，不能仍念『未量的按台账』那句"
    over_modes = {m["mode"]: m for m in over["modes"]}
    over_line = [x for x in over["reading"] if x.startswith("差值（都相对按台账")][0]
    assert f"hybrid P50 +{over_modes['hybrid']['p50_shift_days']} 天" in over_line, \
        "反超要带符号报出来，不能念成『后移 -x』这种反话"



def test_hybrid_reach_recomputes_the_tier_not_the_part_list(monkeypatch):
    """够不够得着 = 按 map 重算最长档差几天，不是"量没量过某个件"。"""
    import asyncio
    from api.services import sim_sensitivity as ss

    class _M:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def all(self):
            return self._rows

    class _Db:
        async def execute(self, stmt, params=None):
            codes = (params or {}).get("codes") or []
            return _M([{"material_code": c,
                        "available": 1000.0 if c == "RM-FULL" else 0.0} for c in codes])

    BOMS = {
        # 20 天那件没量过，但 15 天的量了且实测 6× —— 重算后档位被抬高，算够得着
        "M-1": [{"material_code": "RM-X", "make_or_buy": "外购", "lead_time_days": "20", "qty_per_unit": 1},
                {"material_code": "RM-CAST-01", "make_or_buy": "外购", "lead_time_days": "15", "qty_per_unit": 1}],
        # 并列 15 天，量过的这件实测反而更短：压掉一件还有另一件顶着，档位一天不动
        "M-2": [{"material_code": "RM-SLOW", "make_or_buy": "外购", "lead_time_days": "15", "qty_per_unit": 1},
                {"material_code": "RM-Y", "make_or_buy": "外购", "lead_time_days": "15", "qty_per_unit": 1}],
        # 自制件不进档
        "M-3": [{"material_code": "RM-CAST-01", "make_or_buy": "外购", "lead_time_days": "15", "qty_per_unit": 1},
                {"material_code": "RM-Z", "make_or_buy": "自制", "lead_time_days": "99", "qty_per_unit": 1}],
        # 有库存、不缺料的行不进档（引擎只给缺料的外购件排到货日）
        "M-4": [{"material_code": "RM-FULL", "make_or_buy": "外购", "lead_time_days": "15", "qty_per_unit": 1}],
    }

    async def fake_bom(db, fid, model, units):
        return {"rows": BOMS[model], "source": "engflow_mirror_multi_level"}

    monkeypatch.setattr(ss.vr, "sim_bom_lines", fake_bom)
    targets = [{"model_code": m, "units": 10} for m in BOMS]
    out = asyncio.run(ss.hybrid_reach(_Db(), "FAC", targets, {"RM-CAST-01": 6.0, "RM-SLOW": 0.05}))
    per = {m["model_code"]: m for m in out["per_model"]}
    assert (per["M-1"]["max_short_lead_days"], per["M-1"]["hybrid_max_lead_days"]) == (20, 90)
    assert per["M-1"]["moved_days"] == 70 and per["M-1"]["binding_parts"] == ["RM-X"]
    assert per["M-1"]["measured_at_binding"] == [], "量过的件不在原档位上，但档位仍被它抬高"
    assert per["M-2"]["moved_days"] == 0 and per["M-2"]["measured_at_binding"] == ["RM-SLOW"]
    assert per["M-3"]["binding_parts"] == ["RM-CAST-01"], "自制件不许进最长档"
    assert per["M-4"]["short_buy_rows"] == 0 and per["M-4"]["moved_days"] is None
    assert out["models_reachable"] == 2 and out["reachable_models"] == ["M-1", "M-3"]
    assert out["measured_in_bom_total"] == ["RM-CAST-01", "RM-SLOW"]
    assert out["moved_days_per_model"]["M-2"] == 0


def test_calibration_impact_names_the_tier_when_hybrid_cannot_move(monkeypatch):
    """hybrid 挪不动时必须点名是哪一档、引擎吃的是哪一头 BOM，不能只说"更保守"。"""
    import asyncio
    from datetime import date, timedelta

    from api.services import sim_sensitivity as ss

    async def fake_targets(db, fid, models, **kw):
        return [{"model_code": "M-1", "units": 600, "due_in_days": 23}]

    async def fake_equip(db, fid):
        return {"rate": 0.84}

    async def fake_acc(db, fid, models):
        return {"models": [{"model_code": "M-1", "accuracy_score": 70.0, "hours_error_band": 0.05,
                            "components": {"lead_time": {"score": 1.0},
                                           "hours": {"score": 1.0, "basis": "route_standard_hours"}}}]}

    async def fake_run_one(db, fid, targets, policy, *, attendance, perturb=None, factor_map=None):
        d = perturb or {}
        late = round(10.0 * float(d.get("lead_multiplier", 1.0)) - 20.0, 1)
        return {"finish_date": str(date(2026, 11, 1) + timedelta(days=int(late))),
                "days_late_worst": late, "days_late_per_model": {"M-1": late},
                "labor_cost_usd": 1.0, "expedite_cost_usd": 0.0, "line_activation_cost_usd": 0.0,
                "binding": "material_arrival", "bottleneck_parts": {}, "lines_used": [],
                "material_arrival_days": {}, "capacity_line_declared_max": 0.0,
                "crew_before_staffing_sum": 1.0, "crew_effective_sum": 1.0}

    async def cal(db, fid):
        return {"rows": 6, "zero_ratio_rows": 1, "median_ratio_all_rows": 3.0,
                "median_ratio_nonzero": 4.0, "reliable_rows": 4, "anchor": 4.0,
                "spread_nonzero": {"p25": 2.0, "p75": 6.0, "min": 1.2, "max": 9.0},
                "examples": [], "caveat": "…"}

    async def factors(db, fid, *, min_po=2):
        return {"factors": {"RM-CAST-01": 6.0}, "measured_days": {}, "codes": 1,
                "ledger_rows_with_lead": 5, "coverage": 0.2, "min_po": min_po, "caveat": "…"}

    async def no_reach(db, fid, targets, fac):
        return {"models_checked": 1, "models_reachable": 0, "reachable_models": [],
                "moved_days_per_model": {"M-1": 0}, "binding_parts": {"M-1": ["RM-ELEC-101"]},
                "measured_in_bom_total": [],
                "per_model": [{"model_code": "M-1", "units": 600, "bom_rows": 18,
                               "bom_source": "engflow_mirror_multi_level", "short_buy_rows": 4,
                               "max_short_lead_days": 20, "hybrid_max_lead_days": 20, "moved_days": 0,
                               "binding_parts": ["RM-ELEC-101"], "binding_parts_total": 1,
                               "measured_in_bom": [], "measured_at_binding": []}]}

    for name, value in (("derive_targets", fake_targets), ("equipment_rate", fake_equip)):
        monkeypatch.setattr(ss.vr, name, value)
    monkeypatch.setattr(ss, "mapping_accuracy", fake_acc)
    monkeypatch.setattr(ss, "_run_one", fake_run_one)
    monkeypatch.setattr(ss, "lead_calibration", cal)
    async def force(db, fid, *, census=None):
        return {"in_force": "ledger", "basis": "没人定过锚定口径；实测说台账偏乐观 9.033×",
                "center": 1.0, "anchor": 9.033}

    monkeypatch.setattr(ss, "hybrid_reach", no_reach)
    monkeypatch.setattr(ss, "resolve_lead_anchor", force)
    monkeypatch.setattr("core.mes.measurement_priority.measured_lead_factors", factors)

    out = asyncio.run(ss.calibration_impact(object(), "FAC", ["M-1"], samples=8, seed=3))
    assert out["status"] == "ok" and out["hybrid"]["reach"]["models_reachable"] == 0
    named = [x for x in out["reading"] if "一天也挪不动" in x]
    assert named and "RM-ELEC-101" in named[0], "挪不动要点名是哪一件顶着那一档"
    assert "engflow_mirror_multi_level" in named[0], "要说出引擎吃的是哪一头 BOM，才看得出料号体系对不对得上"
    line = [x for x in out["reading"] if "hybrid 在这几台机上" in x]
    assert line, "够不着要有专门那句，不能混在覆盖率里"
    assert "RM-ELEC-101" in line[0] and "20" in line[0] and "engflow_mirror_multi_level" in line[0]
    assert "量上面点名的那一档" in line[0]
    force_line = [x for x in out["reading"] if "当前在用的是哪一档" in x]
    assert force_line and "ledger" in force_line[0], "三档都算了，还得说清厂里当前拍的是哪一档"
    assert out["anchor_in_force"]["in_force"] == "ledger"

    # 有一台被碰到时，没被碰到的那几台也要点名（否则读数只讲了 successes）
    async def partly(db, fid, targets, fac):
        base = await no_reach(db, fid, targets, fac)
        m2 = {"model_code": "M-2", "units": 600, "bom_rows": 9, "bom_source": "mes_bom_items",
              "short_buy_rows": 3, "max_short_lead_days": 20, "hybrid_max_lead_days": 15,
              "moved_days": -5, "binding_parts": ["RM-ELEC-036"], "binding_parts_total": 1,
              "measured_in_bom": ["RM-ELEC-036"], "measured_at_binding": ["RM-ELEC-036"]}
        base["per_model"].append(m2)
        base["models_reachable"] = 1
        base["models_checked"] = 2
        base["reachable_models"] = ["M-2"]
        base["moved_days_per_model"]["M-2"] = -5
        base["binding_parts"]["M-2"] = ["RM-ELEC-036"]
        base["measured_in_bom_total"] = ["RM-ELEC-036"]
        return base

    monkeypatch.setattr(ss, "hybrid_reach", partly)
    out2 = asyncio.run(ss.calibration_impact(object(), "FAC", ["M-1"], samples=8, seed=3))
    line2 = [x for x in out2["reading"] if "最长档被 map 改了" in x]
    assert line2 and "另 1 台一天没动" in line2[0]
    assert "RM-ELEC-101" in line2[0] and "20→15" in line2[0]


def _gap_env(monkeypatch, gap_result=None, raise_exc=False):
    """把 capacity_questions 依赖的几张表都糊过去，只留 capacity_gap 被测。"""
    async def fake_cov(db, fid):
        return {"capacity_unit_ambiguous": False, "station_capacity_rows": 0, "stations": 0,
                "station_capacity_hours_min": None, "station_capacity_hours_max": None,
                "capacity_unit_mix": [], "reading": "…"}

    async def fake_eff(db, fid):
        return {"rows": [], "note": "…"}

    async def fake_cross(db, fid):
        return {"verdict": {}}

    async def fake_census(db, fid):
        return {"rows": 0, "zero_ratio_rows": 0, "median_all": None, "median_nonzero": None,
                "p25_nonzero": None, "p75_nonzero": None, "min_nonzero": None, "max_nonzero": None,
                "reliable_rows": 0, "anchor": None, "examples": [], "caveat": "…"}

    async def no_rules(db, fid):
        return {}

    monkeypatch.setattr("core.mes.capacity_math.efficiency_basis_census", fake_eff)
    monkeypatch.setattr("core.mes.data_evidence.line_claim_coverage", fake_cov)
    monkeypatch.setattr("core.mes.plant_architecture.capacity_cross_check", fake_cross)
    monkeypatch.setattr(mp, "lead_ratio_census", fake_census)
    monkeypatch.setattr("core.mes.factory_rules.binding_rules", no_rules)

    async def gap(db, fid):
        if raise_exc:
            raise RuntimeError("boom")
        return gap_result or {"models": [], "orders": 0, "units": 0, "open_orders_total": 0,
                              "models_with_capacity": 1, "basis": "line_profiles"}

    monkeypatch.setattr("api.services.prediction_ledger.capacity_gap", gap)


def test_ledger_capacity_gap_becomes_a_question_the_plant_can_act_on(monkeypatch):
    import asyncio

    from core.mes import factory_rules as fr

    _gap_env(monkeypatch, {"models": [{"model_code": "A-30-04-F", "orders": 16, "units": 712.0},
                                      {"model_code": "MPL0113-00", "orders": 15, "units": 718.0}],
                           "orders": 31, "units": 1430.0, "open_orders_total": 726,
                           "models_with_capacity": 1, "basis": "line_profiles（can_make/default）"})
    res = asyncio.run(fr.capacity_questions(None, "FAC"))
    q = [x for x in res["questions"] if x.get("topic") == "delivery_ledger_capacity_basis"]
    assert len(q) == 1
    assert "31" in q[0]["question"] and "A-30-04-F 16 张/712 台" in q[0]["prefilled_evidence"]
    assert "line_profiles" in q[0]["expected_answer"], "要指到厂里能改的那张表"
    assert "留痕法" in q[0]["why_it_matters"]


def test_no_ledger_question_when_every_open_order_has_a_capacity_basis(monkeypatch):
    import asyncio

    from core.mes import factory_rules as fr

    _gap_env(monkeypatch)
    res = asyncio.run(fr.capacity_questions(None, "FAC"))
    assert not [x for x in res["questions"]
                if x.get("topic") == "delivery_ledger_capacity_basis"], "没缺口就不该催"


def test_a_failed_gap_read_is_reported_instead_of_looking_like_no_gap(monkeypatch):
    """空集合≠通过：取数挂了必须自己说出来。"""
    import asyncio

    from core.mes import factory_rules as fr

    _gap_env(monkeypatch, raise_exc=True)
    res = asyncio.run(fr.capacity_questions(None, "FAC"))
    q = [x for x in res["questions"] if x.get("topic") == "delivery_ledger_capacity_basis"]
    assert len(q) == 1 and "没核出来" in q[0]["question"]
    assert q[0]["prefilled_evidence"] == "RuntimeError"
