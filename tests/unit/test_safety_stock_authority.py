"""安全库存这句话的口径对照：判定线、四个数、以及"引擎不选边"这件事本身。

测的是读数会不会撒谎：粒度混了、交集数成并集、模板判定漏掉"众数 95.7%"这种最明显的情形，
都是这轮实测里真出现过的问题（第一条测试就是那条判定线）。
"""
import asyncio
import json

from core.mes import safety_stock_authority as ssa

INV = {"rows_total": 11228, "distinct_values": 47, "mode_value": 2, "nulls": 0, "zeros": 0}
MAT = {"rows_total": 31672, "distinct_values": 10, "mode_value": 100, "nulls": 0, "zeros": 0}
JOIN = {"joined_materials": 31685, "in_both": 11171, "disagree": 11171,
        "only_in_inventory": 13, "only_in_materials": 20501,
        "below_by_inventory": 406, "below_by_materials": 4666,
        "shortfall_by_inventory": 41000.0, "shortfall_by_materials": 778703.0}
TRIG = {"below_trigger_line": 476, "no_reorder_qty": 0, "no_reorder_point": 0,
        "no_inventory_safety": 0}


class _Res:
    def __init__(self, rows, scalar=None):
        self._rows = rows
        self._scalar = scalar

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._scalar

    def __iter__(self):
        return iter(self._rows)


class _Db:
    def __init__(self, config_rows=0, decimal=False):
        self.config_rows = config_rows
        # 真库里 numeric 列回来就是 Decimal：测试要能复现这个形状，不然改不出这个坑
        self.decimal = decimal

    def _num(self, v):
        from decimal import Decimal
        return Decimal(str(v)) if self.decimal else v

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "count(DISTINCT safety_stock) AS distinct_values" in sql and "FROM inventory" in sql:
            return _Res([INV])
        if "count(DISTINCT safety_stock) AS distinct_values" in sql:
            return _Res([MAT])
        if "FROM inventory" in sql and "GROUP BY 1 ORDER BY 2 DESC" in sql:
            return _Res([{"value": 2, "n": 10745}, {"value": 10, "n": 209},
                         {"value": 3, "n": 137}])
        if "FROM materials" in sql and "GROUP BY 1 ORDER BY 2 DESC" in sql:
            return _Res([{"value": 100, "n": 19448}, {"value": 300, "n": 4179}])
        if "in_both" in sql:
            return _Res([JOIN])
        if "below_trigger_line" in sql:
            return _Res([TRIG])
        if "FROM safety_stock_config" in sql:
            return _Res([], self.config_rows)
        if "ORDER BY abs(inv.inv_ss - mat.mat_ss) DESC" in sql:
            return _Res([{"material_code": "0000081207", "by_inventory": self._num(2),
                          "by_materials": self._num(500), "available": self._num(262.0),
                          "gap": self._num(498)},
                         {"material_code": "0000081249", "by_inventory": self._num(2),
                          "by_materials": self._num(500), "available": self._num(1859.0),
                          "gap": self._num(498)}])
        raise AssertionError(f"没准备好的语句：{sql[:80]}")


def test_mode_share_alone_can_call_a_template_even_with_many_distinct_values():
    """inventory 侧 47 个取值但 95.7% 都是 2 —— 第一版判定线把它放过了。"""
    src = ssa.classify_source("inventory.safety_stock", INV, 0.957)
    assert src["verdict"] == "template_default", src
    assert "模板铺的" in src["why"]

    sparse = ssa.classify_source("x", {"rows_total": 900, "distinct_values": 400,
                                       "mode_value": 7, "nulls": 0, "zeros": 0}, 0.04)
    assert sparse["verdict"] == "declared_per_item", "取值散布开就不该乱判模板"

    few = ssa.classify_source("y", {"rows_total": 500, "distinct_values": 6,
                                    "mode_value": 20, "nulls": 0, "zeros": 0}, 0.22)
    assert few["verdict"] == "coarse_default" and "按档铺的粗默认值" in few["why"]


def test_authority_reports_three_grains_and_refuses_to_pick_a_side():
    out = asyncio.run(ssa.safety_stock_authority(_Db(), "FAC_MECH_001", examples=2))
    assert out["status"] == "ok"
    assert [r["alerts"] for r in out["rulers"][:3]] == [476, 406, 4666]
    assert out["rulers"][0]["grain"].startswith("行级")
    assert out["rulers"][1]["grain"] == "料号级"
    assert out["ruler_spread_x"] == 11.49, "最大最小倍数要算给读数用，不能只说'差很多'"

    joined = " ".join(out["reading"])
    assert "11171 个料号里 11171 个声明不一致（100.0%）" in joined, "交集不能数成并集"
    assert "引擎不替厂里选哪张表作准" in joined
    assert "template_default" in joined
    # 众数占比要真的出现在读数里（现场看到的百分比必须就是算出来的那个，别只写"绝大多数"）
    assert f"{out['sources'][0]['mode_share']:.1%}" in joined
    assert out["sources"][0]["verdict"] == "template_default"
    assert "safety_stock_config 本厂 0 行" in joined, "空表要说『没填』，不能说成库存正常"
    assert "0000081207" in joined, "差得最远的料号要点名"
    assert out["claim_guard"] and "不合并成一个" in out["claim_guard"]


def test_config_table_with_rows_is_reported_as_filled_not_applied():
    out = asyncio.run(ssa.safety_stock_authority(_Db(config_rows=42), "FAC_MECH_001"))
    assert out["config_table_rows"] == 42
    assert "safety_stock_config 本厂 42 行" in out["reading"][0]


def test_no_session_says_so_instead_of_returning_an_empty_verdict():
    out = asyncio.run(ssa.safety_stock_authority(None, "FAC_MECH_001"))
    assert out["status"] == "no_session" and out["reading"]


def test_the_table_name_is_not_concatenated_from_arbitrary_input():
    with pytest_raises(ValueError):
        asyncio.run(ssa._mode_share(_Db(), "inventory; DROP TABLE x", "FAC"))


class pytest_raises:
    """小垫片：避免为此引一个 pytest 依赖（本文件全是纯函数级断言）。"""

    def __init__(self, exc):
        self.exc = exc

    def __enter__(self):
        return None

    def __exit__(self, typ, val, tb):
        assert val is not None and isinstance(val, self.exc), f"该抛 {self.exc}，实际 {val}"
        return True


def test_question_is_registered_with_its_four_rulers_and_disappears_once_declared(monkeypatch):
    from core.mes import factory_rules as fr

    async def fake_auth(db, fid, *, examples=5):
        return {"status": "ok", "sources": [
                    {"source": "inventory.safety_stock", "mode_value": 2, "mode_share": 0.957,
                     "verdict": "template_default", "rows": 11228, "distinct_values": 47},
                    {"source": "materials.safety_stock", "mode_value": 100, "mode_share": 0.614,
                     "verdict": "template_default", "rows": 31672, "distinct_values": 10}],
            "rulers": [{"ruler": "触发线", "alerts": 476, "condition": "a", "basis": "b",
                        "grain": "行级"},
                       {"ruler": "inventory 侧", "alerts": 406, "condition": "c", "basis": "d",
                        "grain": "料号级"},
                       {"ruler": "materials 侧", "alerts": 4666, "condition": "e", "basis": "f",
                        "grain": "料号级"},
                       {"ruler": "配置表", "alerts": 0, "condition": "g", "basis": "h",
                        "grain": "配置表"}],
            "disagreement": {"materials_in_both": 11171, "disagree": 11171,
                             "disagree_share": 1.0,
                             "widest_examples": [{"material_code": "X", "by_inventory": 2,
                                                  "by_materials": 500}]},
            "config_table_rows": 0, "ruler_spread_x": 11.49, "reading": [], "claim_guard": ""}

    async def rules_none(db, fid):
        return {}

    async def rules_declared(db, fid):
        return {"safety_stock_authority": {"verdict": "inventory", "status": "declared",
                                           "statement": "以 inventory 侧作准"}}

    # capacity_questions 还要读别的表：一并糊掉，只留被测那条
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

    async def fake_gap(db, fid):
        return {"models": [], "orders": 0, "units": 0, "open_orders_total": 0,
                "models_with_capacity": 1, "basis": "line_profiles"}

    from core.mes import data_evidence, capacity_math, measurement_priority as mp
    from core.mes import plant_architecture
    from api.services import prediction_ledger

    monkeypatch.setattr(data_evidence, "line_claim_coverage", fake_cov)
    monkeypatch.setattr(capacity_math, "efficiency_basis_census", fake_eff)
    monkeypatch.setattr(plant_architecture, "capacity_cross_check", fake_cross)
    monkeypatch.setattr(mp, "lead_ratio_census", fake_census)
    monkeypatch.setattr(prediction_ledger, "capacity_gap", fake_gap)
    monkeypatch.setattr("core.mes.safety_stock_authority.safety_stock_authority", fake_auth)
    monkeypatch.setattr(fr, "binding_rules", rules_none)
    qs = asyncio.run(fr.capacity_questions(object(), "FAC"))["questions"]
    mine = [q for q in qs if q.get("topic") == "safety_stock_authority"]
    assert mine and mine[0]["record_as"]["subject"] == "safety_stock_authority"
    assert "11.49" in mine[0]["why_it_matters"] and "0 行" in mine[0]["why_it_matters"]
    assert len(mine[0]["what_records_say"]) == 4, "四条尺都要跟着问题走，否则现场没法拍"

    monkeypatch.setattr(fr, "binding_rules", rules_declared)
    qs2 = asyncio.run(fr.capacity_questions(object(), "FAC"))["questions"]
    assert not [q for q in qs2 if q.get("topic") == "safety_stock_authority"], "拍过就不再问"


def test_the_whole_payload_must_survive_json_because_it_gets_persisted():
    """答复要落进 chat_messages 的 jsonb：一个 Decimal 就让整轮 500（实测过一次）。"""
    import json
    from decimal import Decimal

    out = asyncio.run(ssa.safety_stock_authority(_Db(decimal=True), "FAC_MECH_001", examples=2))
    bad = []

    def walk(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, (Decimal, bytes)):
            bad.append((path, type(node).__name__))

    walk(out)
    assert not bad, f"SQL 的类型漏进来了：{bad}"
    json.dumps(out, ensure_ascii=False)   # 落库前最后一道：能序列化


def test_top_gap_samples_are_cast_not_passed_through():
    out = asyncio.run(ssa.safety_stock_authority(_Db(), "FAC_MECH_001", examples=2))
    row = out["disagreement"]["widest_examples"][0]
    assert type(row["available"]) is float and type(row["gap"]) is float, row
