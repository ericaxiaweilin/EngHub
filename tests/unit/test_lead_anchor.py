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
