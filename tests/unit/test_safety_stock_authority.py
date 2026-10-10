"""安全库存这句话的口径对照：判定线、四个数、以及"引擎不选边"这件事本身。

测的是读数会不会撒谎：粒度混了、交集数成并集、模板判定漏掉"众数 95.7%"这种最明显的情形，
都是这轮实测里真出现过的问题（第一条测试就是那条判定线）。

活清单（master_data_worklist）那批测试钉的是另一件事：**合计格与分档格必须出自同一次取数**，
以及"能回填供应商"要按交集算不是并集 —— 一个料号在采购单里出现过不等于那行写了供应商。
"""
import asyncio
import json
from decimal import Decimal as _D

from core.mes import safety_stock_authority as ssa

INV = {"rows_total": 11228, "distinct_values": 47, "mode_value": 2, "nulls": 0, "zeros": 0}
MAT = {"rows_total": 31672, "distinct_values": 10, "mode_value": 100, "nulls": 0, "zeros": 0}
JOIN = {"joined_materials": 31685, "in_both": 11171, "disagree": 11171,
        "only_in_inventory": 13, "only_in_materials": 20501,
        "below_by_inventory": 406, "below_by_materials": 4666,
        "shortfall_by_inventory": 41000.0, "shortfall_by_materials": 778703.0}
TRIG = {"below_trigger_line": 476, "no_reorder_qty": 0, "no_reorder_point": 0,
        "no_inventory_safety": 0}
AUTO = {"pr_materials": 512, "pr_lines": 512, "pr_units": _D("10520"),
        "pr_in_kit_universe": 149, "gap_materials": 821, "gap_units": _D("4237670"),
        "gap_without_request": 675, "request_without_gap": 366,
        "last_created": "2026-10-09"}

# WORKLIST_SQL 的行形状 —— 这一批行同时喂给 shortage_backlog（合计）和
# master_data_worklist（分档），所以两格的数在这里就能被钉成同一个。
WORKLIST_ROWS = [
    {"material_code": "1000455461", "need": _D("12000"), "work_orders": 7,
     "has_master_row": True, "material_name": "电子料甲", "default_supplier": "宝钢金属(佛山)",
     "lead_time_days": 20, "unit_cost": _D("3.5"), "inv_rows": 3,
     "named_products": 2, "units_unattributed": _D("0"),
     "named_units": "FG-TREAD-90:8000 / FG-BIKE-26:4000"},
    # 只差供应商这一列：用来钉"只填一列就能催单"那条分支
    {"material_code": "RM-ELEC-999", "need": _D("900"), "work_orders": 2,
     "has_master_row": True, "material_name": "无供应商料号", "default_supplier": None,
     "lead_time_days": 12, "unit_cost": _D("8.0"), "inv_rows": 1,
     "named_products": 1, "units_unattributed": _D("0"), "named_units": "FG-TREAD-90:900"},
    # 单价 0 元占位 + 无库存行 + 供应商名悬空 + 一条成品号都报不出
    {"material_code": "RM-STEEL-009", "need": _D("500"), "work_orders": 4,
     "has_master_row": True, "material_name": "钢带", "default_supplier": "某贸易行",
     "lead_time_days": 30, "unit_cost": _D("0"), "inv_rows": 0,
     "named_products": 0, "units_unattributed": _D("500"), "named_units": None},
    # 主数据行不存在：那不是"填一列"，是建这条档
    {"material_code": "NEW-PART-7", "need": _D("2"), "work_orders": 1,
     "has_master_row": False, "material_name": None, "default_supplier": None,
     "lead_time_days": None, "unit_cost": None, "inv_rows": 0,
     "named_products": 1, "units_unattributed": _D("0"), "named_units": "FG-BIKE-26:2"},
]

# 本厂实测形状：没有任何料号只差一列，且九个出处点不出一个能回填的供应商
PROD_SHAPED_ROWS = [
    dict(WORKLIST_ROWS[0]),
    {"material_code": "P-2", "need": _D("600"), "work_orders": 3, "has_master_row": True,
     "material_name": "差供应商+提前期", "default_supplier": None, "lead_time_days": None,
     "unit_cost": _D("2.0"), "inv_rows": 2, "named_products": 1,
     "units_unattributed": _D("0"), "named_units": "FG-TREAD-90:600"},
    {"material_code": "P-3", "need": _D("300"), "work_orders": 2, "has_master_row": True,
     "material_name": "差供应商+单价", "default_supplier": None, "lead_time_days": 10,
     "unit_cost": None, "inv_rows": 1, "named_products": 1,
     "units_unattributed": _D("0"), "named_units": "FG-BIKE-26:300"},
    dict(WORKLIST_ROWS[3]),
]

# 逐出处普查：code 出现（seen）与该行真写了值（recoverable）是两件事
SCAN_ROWS = [
    {"source": "bom_items.vendor_name", "codes_in_source": 1244, "codes_with_value": 0,
     "seen_codes": ["RM-ELEC-999"], "recoverable_codes": []},
    {"source": "purchase_orders.supplier_name", "codes_in_source": 88, "codes_with_value": 3,
     "seen_codes": [], "recoverable_codes": []},
    {"source": "supplier_materials.supplier_id", "codes_in_source": 15, "codes_with_value": 15,
     "seen_codes": ["RM-ELEC-999", "NEW-PART-7"], "recoverable_codes": ["RM-ELEC-999"]},
]
SCAN_ROWS_NONE = [
    {"source": "bom_items.vendor_name", "codes_in_source": 1244, "codes_with_value": 0,
     "seen_codes": ["RM-ELEC-999", "P-2", "P-3"], "recoverable_codes": []},
    {"source": "purchase_orders.supplier_name", "codes_in_source": 88, "codes_with_value": 3,
     "seen_codes": [], "recoverable_codes": []},
]
MIRROR = {"rows_total": 481557, "distinct_parts": 13455, "rows_with_vendor": 0,
          "parts_with_vendor": 0}
SUPPLIER_MASTER = {"supplier_rows": 10, "names_on_materials": 15, "dangling_names": 9,
                  "rows_with_dangling_name": 490}
DANGLING = [{"name": "某贸易行", "material_rows": 210}, {"name": "旧目录名", "material_rows": 3}]
SUPPLIER_NAMES = [{"supplier_name": "宝钢金属(佛山)"}, {"supplier_name": "南钢物流"}]

DEFAULTS = {"worklist_rows": WORKLIST_ROWS, "scan_rows": SCAN_ROWS,
            "mirror": MIRROR, "master": SUPPLIER_MASTER, "dangling": DANGLING,
            "names": SUPPLIER_NAMES}


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
    """按 SQL 里的独有别名分派。每条都记进 calls，好在测试里断"只取了一次数""没跑这一条"。"""

    def __init__(self, config_rows=0, decimal=False, **over):
        self.config_rows = config_rows
        # 真库里 numeric 列回来就是 Decimal：测试要能复现这个形状，不然改不出这个坑
        self.decimal = decimal
        self.k = dict(DEFAULTS, **over)
        self.calls = []

    def _num(self, v):
        return _D(str(v)) if self.decimal else v

    def tagged(self, tag):
        return [p for t, p in self.calls if t == tag]

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        tag = self._tag(sql)
        self.calls.append((tag, params or {}))
        k = self.k
        if tag == "inv_census":
            return _Res([INV])
        if tag == "mat_census":
            return _Res([MAT])
        if tag == "inv_mode":
            return _Res([{"value": 2, "n": 10745}, {"value": 10, "n": 209},
                         {"value": 3, "n": 137}])
        if tag == "mat_mode":
            return _Res([{"value": 100, "n": 19448}, {"value": 300, "n": 4179}])
        if tag == "disagree":
            return _Res([JOIN])
        if tag == "trigger":
            return _Res([TRIG])
        if tag == "auto_pr":
            return _Res([AUTO])
        if tag == "worklist":
            return _Res(k["worklist_rows"])
        if tag == "scan":
            return _Res(k["scan_rows"])
        if tag == "mirror_gate":
            return _Res([k["mirror"]])
        if tag == "supplier_master":
            return _Res([k["master"]])
        if tag == "dangling":
            return _Res(k["dangling"])
        if tag == "supplier_names":
            return _Res(k["names"])
        if tag == "cost_census":
            return _Res([{"distinct_values": 10, "mode_value": _D("18"), "filled": 11092}])
        if tag == "cost_mode":
            return _Res([{"n": 10981}])
        if tag == "cost_zero":
            return _Res([{"z": 10981, "pos": 108}])
        if tag == "config":
            return _Res([], self.config_rows)
        if tag == "top_gap":
            return _Res([{"material_code": "0000081207", "by_inventory": self._num(2),
                          "by_materials": self._num(500), "available": self._num(262.0),
                          "gap": self._num(498)},
                         {"material_code": "0000081249", "by_inventory": self._num(2),
                          "by_materials": self._num(500), "available": self._num(1859.0),
                          "gap": _D("498")}])
        raise AssertionError(f"没准备好的语句：{sql[:80]}")

    @staticmethod
    def _tag(sql):
        # 判定顺序有意义：worklist 里也含 "FROM inventory"，先认它独有的别名
        for tag, needles in (
                ("worklist", ("AS has_master_row",)),
                ("scan", ("hits AS",)),
                ("mirror_gate", ("FROM enghub_bom_items",)),
                ("supplier_master", ("AS dangling_names",)),
                ("dangling", ("AS material_rows",)),
                ("supplier_names", ("SELECT supplier_name FROM suppliers",)),
                ("cost_census", ("count(DISTINCT unit_cost) AS distinct_values",)),
                ("cost_mode", ("AS n FROM inventory", "unit_cost =")),
                ("cost_zero", ("AS z", "unit_cost = 0")),
                ("config", ("FROM safety_stock_config",)),
                ("top_gap", ("ORDER BY abs(inv.inv_ss - mat.mat_ss) DESC",)),
                ("inv_census", ("count(DISTINCT safety_stock) AS distinct_values", "FROM inventory")),
                ("mat_census", ("count(DISTINCT safety_stock) AS distinct_values",)),
                ("inv_mode", ("FROM inventory", "GROUP BY 1 ORDER BY 2 DESC")),
                ("mat_mode", ("FROM materials", "GROUP BY 1 ORDER BY 2 DESC")),
                ("disagree", ("in_both",)),
                ("trigger", ("below_trigger_line",)),
                ("auto_pr", ("pr_lines",)),
        ):
            if all(n in sql for n in needles):
                return tag
        return "?"

    def quiet(self, *tags):
        """把某条语句改成空结果，用来测"这一格本来没数"的分支。"""
        orig = self.execute

        async def patched(stmt, params=None):
            if self._tag(str(stmt)) in tags:
                return _Res([])
            return await orig(stmt, params)

        self.execute = patched
        return self


def _wl(db, limit=12):
    return asyncio.run(ssa.master_data_worklist(db, "FAC_MECH_001", limit=limit))


def _auth(db, **kw):
    return asyncio.run(ssa.safety_stock_authority(db, "FAC_MECH_001", **kw))


def _lines(out, needle):
    return [x for x in out["reading"] if needle in x]


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
    out = _auth(_Db(), examples=2)
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
    out = _auth(_Db(config_rows=42))
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

    asked = {}

    async def fake_auth(db, fid, **kw):
        asked.update(kw)
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
            "auto_replenishment": {"pr_lines": 512, "pr_units": 10520.0, "pr_materials": 512,
                                   "pr_in_kit_universe": 149, "gap_materials": 821,
                                   "gap_units": 4237670.0, "gap_without_request": 675,
                                   "request_without_gap": 366, "last_created": "2026-10-09"},
            "shortage_backlog": {"parts": 675, "units": 3224319.0, "work_order_lines": 33638,
                                 "without_supplier": 663, "without_cost": 470, "without_lead": 3,
                                 "ready_to_act": 12},
            "master_data_worklist": {
                "universe": {"parts": 675}, "can_expedite_today": 12,
                "supplier_backfill": {"parts_without_supplier": 663, "sources_scanned": 10,
                                      "recoverable_parts": 0, "units_without_supplier": 3220802.0,
                                      "verdict": "no_record_names_a_supplier"}},
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
    assert asked.get("worklist_limit"), "活清单没被要，那一句『能不能回填供应商』就没有依据"

    gate = [q for q in qs if q.get("topic") == "auto_replenishment_demand_gate"]
    assert gate, "已经有自动开单记录时，需求侧就绪门那条要跟着挂出来"
    assert "能回填的是 0 个" in gate[0]["why_it_matters"], (
        "『让他们填供应商』这一步无台账可依，是加门的代价，必须跟着问题走而不是留成空话")
    assert "no_record_names_a_supplier" in gate[0]["why_it_matters"], "判据要指名，不能只说没查到"
    assert "供应商这一列逐个出处查过" in gate[0]["prefilled_evidence"]

    monkeypatch.setattr(fr, "binding_rules", rules_declared)
    qs2 = asyncio.run(fr.capacity_questions(object(), "FAC"))["questions"]
    assert not [q for q in qs2 if q.get("topic") == "safety_stock_authority"], "拍过就不再问"


def test_the_whole_payload_must_survive_json_because_it_gets_persisted():
    """答复要落进 chat_messages 的 jsonb：一个 Decimal 就让整轮 500（实测过一次）。

    活清单那一格带 string_agg 出来的文本和 round() 出来的 numeric，所以必须一起走一遍。
    """
    out = _auth(_Db(decimal=True), examples=2, worklist_limit=12)
    assert out["master_data_worklist"] is not None
    bad = []

    def walk(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, (_D, bytes)):
            bad.append((path, type(node).__name__))

    walk(out)
    assert not bad, f"SQL 的类型漏进来了：{bad}"
    json.dumps(out, ensure_ascii=False)   # 落库前最后一道：能序列化


def test_top_gap_samples_are_cast_not_passed_through():
    out = _auth(_Db(), examples=2)
    row = out["disagreement"]["widest_examples"][0]
    assert type(row["available"]) is float and type(row["gap"]) is float, row


def test_auto_replenishment_is_audited_against_real_shortages_and_stays_serialisable():
    out = _auth(_Db(decimal=True), examples=2)
    line = _lines(out, "已经开出去的自动补货")
    assert line, "水位线已经在开单这件事必须跟着读数出去"
    assert "512 条" in line[0] and "366 个料号引擎当前并不缺" in line[0]
    assert "675 个一条单都没开" in line[0]
    assert out["auto_replenishment"]["pr_units"] == 10520.0
    assert out["auto_replenishment"]["gap_units"] == 4237670.0
    assert isinstance(out["auto_replenishment"]["pr_lines"], int)
    json.dumps(out, ensure_ascii=False)     # Decimal/date 都转掉了才能落 jsonb


def test_no_auto_line_when_nothing_has_been_ordered():
    """没开过单就不要凭空写一条"自动补货对不上"。"""
    db = _Db(decimal=True).quiet("auto_pr")
    out = _auth(db)
    assert not _lines(out, "已经开出去的自动补货")


def test_backlog_lists_what_can_be_acted_on_today_and_names_the_missing_master_data():
    out = _auth(_Db(decimal=True), examples=2)
    line = _lines(out, "缺口却没开过单的料号")
    assert line and "4 个 / 13,402 件" in line[0], "件数要按千分位印，别印成科学计数法"
    assert "挂在 14 个工单行上" in line[0]
    assert "今天就能去催的只有 1 个" in line[0]
    assert "2 个没供应商" in line[0] and "2 个没单价" in line[0] and "1 个没提前期" in line[0]
    assert "不给金额" in line[0], "没有可信单价就不许折算成钱"
    bl = out["shortage_backlog"]
    assert bl["without_master_row"] == 1, "主数据没这条要单独数，它不是'填一列'"
    assert "1 个连物料主数据行都没有，那不是填一列，是建这条档" in line[0], (
        "把没建档的料号混进'缺哪一列'里，现场就会以为填一列能解决")
    assert bl["items"][0]["ready_to_act"] is True and bl["items"][0]["supplier"] == "宝钢金属(佛山)"
    assert bl["items"][1]["ready_to_act"] is False and bl["items"][1]["supplier"] is None
    json.dumps(out, ensure_ascii=False)


def test_backlog_line_is_absent_when_no_shortage_is_uncovered():
    db = _Db(decimal=True).quiet("worklist")
    out = _auth(db)
    assert not _lines(out, "缺口却没开过单的料号"), "0 个就不要印一行空话"
    assert out["shortage_backlog"]["parts"] == 0
    assert out["shortage_backlog"]["items"] == []


def test_unit_cost_being_present_is_not_the_same_as_it_being_real():
    """三项齐 ≠ 能算钱：单价自己也是铺的就要当场说破。"""
    out = _auth(_Db(decimal=True), examples=2)
    basis = out["shortage_backlog"]["unit_cost_basis"]
    assert basis["verdict"] == "template_default" and basis["distinct_values"] == 10
    assert basis["zero_cost_rows_share"] == 0.99, "单价是 0 的行要单独报，不能算成有价"
    assert basis["mode_share"] == 0.99
    line = _lines(out, "却没开过单")[0]
    assert "单价也只有" in line or "不折成金额" in line

    # 0 元占位不能让"有 unit_cost"就变成可催
    assert ssa._gap_missing({"has_material_master_row": True, "supplier": "宝钢金属(佛山)",
                             "lead_time_days": 30, "unit_cost": 0.0}) == ["cost"]
    assert ssa._gap_missing({"has_material_master_row": True, "supplier": "宝钢金属(佛山)",
                             "lead_time_days": 30, "unit_cost": None}) == ["cost"]


def test_both_cells_come_from_a_single_fetch_and_must_agree():
    """这次重构的全部理由：合计格与分档格各跑各的 SQL 会隔两秒互相打脸。"""
    db = _Db(decimal=True)
    out = _auth(db, examples=2, worklist_limit=3)
    assert len(db.tagged("worklist")) == 1, (
        f"取数口跑了两遍（{len(db.tagged('worklist'))} 次），两格的数就不是同一个时刻的")
    ag = out["backlog_worklist_agreement"]
    assert ag["agree"] is True and ag["backlog_parts"] == ag["worklist_parts"] == 4
    assert ag["backlog_ready"] == ag["worklist_ready"] == 1
    assert ag["why"]
    assert not _lines(out, "数不一致"), "同一批行却报打脸，就是分档算错了"
    assert out["master_data_worklist"]["universe"]["units"] == out["shortage_backlog"]["units"]


def test_worklist_is_not_fetched_unless_asked():
    """默认 0 就不跑：那几条出处普查虽快，但每个聊天回合都跑一遍是白付的钱。"""
    db = _Db(decimal=True)
    out = _auth(db, examples=2)
    assert out["master_data_worklist"] is None and out["master_data_worklist_error"] is None
    for tag in ("scan", "mirror_gate", "supplier_master", "dangling"):
        assert not db.tagged(tag), f"没要活清单却跑了 {tag}"
    # 缺口那一格仍然要算出来，它不依赖活清单
    assert out["shortage_backlog"]["parts"] == 4


def test_grades_partition_the_universe_exactly():
    """分档不重不漏：档数合计=全集，件数合计=全集，否则'差供应商 660 个'就是编的。"""
    wl = _wl(_Db())
    uni = wl["universe"]
    assert uni["parts"] == 4 and uni["units"] == 13402.0 and uni["work_order_lines"] == 14
    assert sum(g["parts"] for g in wl["grades"]) == uni["parts"]
    assert round(sum(g["units"] for g in wl["grades"]), 1) == uni["units"]
    assert sum(g["work_order_lines"] for g in wl["grades"]) == uni["work_order_lines"]
    assert [g["label"] for g in wl["grades"]] == [
        "三项齐 —— 今天就能开单/催单", "差供应商", "差单价",
        "物料主数据没这条 —— 要先建档，不是填一列"]
    assert wl["grades"][0]["units"] >= wl["grades"][1]["units"], "按缺口件数从大往小列"
    assert wl["can_expedite_today"] == 1
    assert wl["no_master_row_parts"] == 1
    line = " ".join(wl["reading"])
    assert "差供应商 1 个 / 900 件（2 个工单行）" in line, "档位要带自己的工单行数"


def test_only_one_column_missing_is_named_when_it_exists_and_denied_when_it_does_not():
    """"补上供应商就能下单"这条推理只有在真有只差一列的料号时才成立 —— 本厂不成立。"""
    wl = _wl(_Db())
    by_col = {c["column"]: c for c in wl["columns"]}
    assert by_col["materials.default_supplier"]["parts_only_this_missing"] == 1
    assert by_col["inventory.unit_cost"]["parts_only_this_missing"] == 1
    assert by_col["materials.lead_time_days"]["parts_only_this_missing"] == 0
    assert "只填一列就能催单的料号" in " ".join(wl["reading"])

    prod = _wl(_Db(decimal=True, worklist_rows=PROD_SHAPED_ROWS, scan_rows=SCAN_ROWS_NONE))
    assert all(c["parts_only_this_missing"] == 0 for c in prod["columns"]), prod["columns"]
    line = _wl_line(prod, "只填一列")
    assert "0 个 —— 三列" in line and "『补上供应商就能下单』这条推理在本厂不成立" in line


def _wl_line(wl, needle):
    return [x for x in wl["reading"] if needle in x][0]


def test_backfill_is_the_intersection_not_the_union():
    """料号在该出处出现过 ≠ 那行写了供应商；只有带值的那些才算能回填。"""
    wl = _wl(_Db())
    bf = wl["supplier_backfill"]
    bom = [s for s in bf["sources"] if s["source"] == "bom_items.vendor_name"][0]
    assert bom["nosup_parts_seen"] == 1 and bom["recoverable_parts"] == 0, "出现当回填就虚高了"
    sup = [s for s in bf["sources"] if s["source"] == "supplier_materials.supplier_id"][0]
    assert sup["nosup_parts_seen"] == 2 and sup["recoverable_parts"] == 1
    assert sup["recoverable_units"] == 900.0, "能回填要带它自己那 900 件，不能只有个数"
    # 并集是从逐出处返回的料号去重来的：同一个料号在两个出处都出现过，不能数两次
    assert sum(s["nosup_parts_seen"] for s in bf["sources"]) == 3
    assert bf["parts_seen_in_any_source"] == 2
    assert bf["scan_ran"] is True and bf["scan_why_skipped"] is None
    assert bf["recoverable_parts"] == 1 and bf["recoverable_units"] == 900.0
    assert bf["recoverable_material_codes"] == ["RM-ELEC-999"]
    assert bf["verdict"] == "partially_recoverable"
    assert bf["parts_without_supplier"] == 2 and bf["units_without_supplier"] == 902.0
    # 能回填的排前面，其次按在该出处真出现过的料号数
    assert [s["source"] for s in bf["sources"]][:2] == [
        "supplier_materials.supplier_id", "bom_items.vendor_name"]


def test_backfill_only_is_asked_for_the_parts_that_need_it():
    """:codes 传的是缺供应商的那几个料号，不是全清单 —— 传错就悄悄把交集算宽了。"""
    db = _Db()
    _wl(db)
    asked = [(t, p) for t, p in db.calls if t == "scan"]
    assert len(asked) == 1, asked
    for _, params in asked:
        assert sorted(params["codes"]) == ["NEW-PART-7", "RM-ELEC-999"]
        assert params["fid"] == "FAC_MECH_001"
    assert len(db.tagged("worklist")) == 1, "逐出处普查不许重跑齐套展开那条（那是 2 秒的）"


def test_zero_vendor_mirror_is_judged_at_the_source_level_and_says_why():
    wl = _wl(_Db())
    mb = wl["supplier_backfill"]["mirror_bom"]
    assert mb["judged_at"] == "出处级"
    assert mb["rows_total"] == 481557 and mb["rows_with_vendor_name"] == 0
    assert "必然是 0" in mb["why_not_per_part"]
    line = _wl_line(wl, "供应商这一列能不能从台账回填")
    assert "无处可查" in line, "要说破这是没这东西，不是我没查到"

    with_vendor = _wl(_Db(mirror={**MIRROR, "rows_with_vendor": 77, "parts_with_vendor": 40}))
    mb2 = with_vendor["supplier_backfill"]["mirror_bom"]
    assert "逐料号可回填数见 sources" in mb2["why_not_per_part"]
    assert "77 行带 vendor_name" in _wl_line(with_vendor, "供应商这一列能不能从台账回填")


def test_no_supplier_record_anywhere_is_a_verdict_not_a_blank():
    wl = _wl(_Db(decimal=True, worklist_rows=PROD_SHAPED_ROWS, scan_rows=SCAN_ROWS_NONE))
    bf = wl["supplier_backfill"]
    assert bf["verdict"] == "no_record_names_a_supplier"
    assert bf["recoverable_parts"] == 0 and bf["parts_without_supplier"] == 3
    assert "扫了" in _wl_line(wl, "供应商这一列能不能从台账回填")


def test_scan_is_not_paid_for_when_nothing_needs_backfill():
    """缺供应商的料号一个都没有 → 那条扫 9 张表的普查不跑；这一格的 0 是"没有对象"。

    不区分这两种 0，就是拿"没查"冒充"查了没有"（本厂真跑出来的是后者）。
    """
    rows = [dict(WORKLIST_ROWS[0]), dict(WORKLIST_ROWS[2], default_supplier="南钢物流")]
    db = _Db(worklist_rows=rows)
    wl = _wl(db)
    bf = wl["supplier_backfill"]
    assert not db.tagged("scan"), "没有要回填的对象还去扫 9 张表"
    assert bf["scan_ran"] is False and bf["parts_without_supplier"] == 0
    assert bf["verdict"] == "nothing_to_backfill"
    assert bf["sources"] == [] and bf["sources_scanned"] == 1, "只剩镜像那一条出处级判定"
    line = _wl_line(wl, "供应商这一列不用回填")
    assert "不是『查了没有』" in line
    by_col = {c["column"]: c for c in wl["columns"]}
    assert by_col["materials.default_supplier"]["parts_missing"] == 0
    assert by_col["inventory.unit_cost"]["parts_missing"] == 1, (
        "省掉的只是供应商普查，不是整张前置条件表 —— 还缺别的列要照报")


def test_dangling_supplier_names_are_counted_twice_from_two_directions():
    """档案侧（物料上写的名字不在 suppliers 里）与清单侧（缺口料号指着同一个悬空名）。"""
    wl = _wl(_Db())
    sm = wl["supplier_master"]
    assert sm["supplier_rows"] == 10 and sm["distinct_names_on_materials"] == 15
    assert sm["names_not_in_supplier_master"] == 9 and sm["material_rows_with_dangling_name"] == 490
    assert sm["gap_parts_declaring_supplier"] == 2, "清单里声明过供应商的料号数"
    assert sm["gap_parts_with_dangling_supplier"] == 1, "RM-STEEL-009 指的『某贸易行』不在档案里"
    assert sm["dangling_examples"][0]["supplier_name"] == "某贸易行"
    assert sm["supplier_names"] == ["南钢物流", "宝钢金属(佛山)"], "要给人有得选，先列出有什么可填"
    line = _wl_line(wl, "要填也得先有得选")
    assert "9 个在这 10 行里不存在" in line and "某贸易行 210 行" in line


def test_cost_placeholders_name_parts_with_no_inventory_row_at_all():
    wl = _wl(_Db())
    cp = wl["cost_placeholders"]
    assert cp["parts_without_inventory_row"] == 2, "连单价的出处都没有，这一格不给金额"
    assert cp["parts_with_zero_cost"] == 1
    assert cp["note"]


def test_product_attribution_reports_the_unattributed_part_instead_of_hiding_it():
    wl = _wl(_Db())
    pa = wl["product_attribution"]
    assert pa["units_on_work_orders_without_product"] == 500.0
    assert pa["parts_fully_unattributed"] == 1
    assert "（工单没写成品号）" in pa["note"]
    assert wl["items"][0]["waiting_for"] == "FG-TREAD-90:8000 / FG-BIKE-26:4000"
    assert wl["items"][2]["waiting_for"] is None
    line = _wl_line(wl, "这些缺口挂在哪些机上")
    assert "3 个料号能报到成品号" in line and "这一格按工单行计" in line


def test_empty_worklist_explains_which_of_the_two_causes_it_is():
    """空清单有两种成因，报成"没有待办"就是把引擎没算当成库存健康。"""
    wl = _wl(_Db(worklist_rows=[]))
    assert wl["universe"]["parts"] == 0 and wl["grades"] == [] and wl["can_expedite_today"] == 0
    assert wl["reading"] == [wl["reading"][0]]
    assert "两种都不是『库存正常』" in wl["reading"][0]
    assert "items_are" in wl and wl["items"] == []


def test_worklist_truncates_items_but_not_the_grades():
    wl = _wl(_Db(), limit=2)
    assert len(wl["items"]) == 2 and wl["rows_total"] == 4
    assert "前 2 行" in wl["items_are"]
    assert sum(g["parts"] for g in wl["grades"]) == 4, "截断只影响清单，分档必须看全集"
