"""BOM 唯一读入口的口径回归。

背景：同一个"这个产品用什么料"的问题，MRP 端点查 `bom_items`、领料查 engflow
镜像、还有一个 MRPService 读代码里硬编码的演示字典 —— 三个答案。现在只能有一个。
"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]

from api.services import bom_source
from api.services.bom_source import latest_bom_lines


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


def _session(*results):
    db = MagicMock()
    queued = list(results)
    calls = []

    async def execute(statement, params=None):
        calls.append((str(statement), params))
        return _Rows(queued.pop(0) if queued else [])

    db.execute = execute
    db.calls = calls
    return db


@pytest.mark.asyncio
async def test_mirror_wins_when_engflow_has_the_product():
    db = _session([{"material_code": "1000096854", "material_name": None,
                    "qty_per_unit": 1, "unit": "PCS",
                    "vendor_code": "V1", "vendor_name": "供方"}])
    lines, source = await latest_bom_lines(db, "FAC_MECH_001", "A-50-04-F")
    assert source == "engflow_mirror"
    assert [l["material_code"] for l in lines] == ["1000096854"]
    assert len(db.calls) == 1, "镜像命中时不该再去查本地表"


@pytest.mark.asyncio
async def test_falls_back_to_local_only_when_mirror_misses():
    db = _session([], [{"material_code": "VF-RAW-STEEL", "material_name": "钢材",
                        "qty_per_unit": 1.2, "unit": "PCS",
                        "vendor_code": None, "vendor_name": None}])
    lines, source = await latest_bom_lines(db, "FAC_ELEC_DEMO_2026", "VF-CMECH001-40HQ")
    assert source == "mes_bom_items"
    assert lines[0]["qty_per_unit"] == 1.2
    assert "enghub_bom_items" in db.calls[0][0]
    assert "bom_items" in db.calls[1][0]


@pytest.mark.asyncio
async def test_pinned_version_only_reads_local_table():
    db = _session([{"material_code": "RM-X", "material_name": None,
                    "qty_per_unit": 2, "unit": "pcs",
                    "vendor_code": None, "vendor_name": None}])
    lines, source = await latest_bom_lines(
        db, "FAC_MECH_001", "A-50-04-F", version="BOM-V3")
    assert source == "mes_bom_items"
    assert len(db.calls) == 1
    assert db.calls[0][1]["version"] == "BOM-V3"


@pytest.mark.asyncio
async def test_no_bom_anywhere_returns_none_source_not_invented_demand():
    db = _session([], [])
    lines, source = await latest_bom_lines(db, "FAC_X", "GHOST-PRODUCT")
    assert (lines, source) == ([], "none")
    assert "没有" in bom_source.label(source)


@pytest.mark.asyncio
async def test_material_issue_uses_the_same_entry(monkeypatch):
    """领料必须走同一个入口：两处各查各的表就是 MRP 与领料对不上数的根源。"""
    from api.services.wms_service import InventoryService

    seen = {}

    async def fake(db, factory_id, product_code, version=None):
        seen["product"] = product_code
        return [], "none"

    monkeypatch.setattr(bom_source, "latest_bom_lines", fake)
    svc = InventoryService(MagicMock())
    lines, source = await svc._latest_bom_lines("FAC_MECH_001", "A-50-04-F")
    assert (lines, source) == ([], "none")
    assert seen["product"] == "A-50-04-F"


def _row(level, part, qty, order):
    return {"level": level, "material_code": part, "qty_per_unit": qty,
            "material_name": part, "unit": "PCS", "original_row_number": order,
            "vendor_code": None}


def test_tree_parent_comes_from_indent_order():
    """前序缩进行：父级 = 前面最近的一条浅一层行。这是层级 BOM 的本来的读法。"""
    rows = [_row(1, "ASSY-A", 1, 0), _row(2, "SUB-B", 2, 1), _row(3, "RAW-C", 3, 2),
            _row(2, "RAW-D", 5, 3)]
    nodes, problems = bom_source.build_tree(rows)
    assert problems == []
    assert [(n["material_code"], n["parent_code"], n["per_unit_qty"]) for n in nodes] == [
        ("ASSY-A", None, 1.0),
        ("SUB-B", "ASSY-A", 2.0),
        ("RAW-C", "SUB-B", 6.0),
        ("RAW-D", "ASSY-A", 5.0),
    ]


def test_broken_indent_is_reported_not_repaired():
    """层深一次跳 +2 说明中间缺了父级：如实报问题，不猜一个爹挂上去。"""
    rows = [_row(1, "ASSY-A", 1, 0), _row(3, "RAW-X", 2, 1)]
    nodes, problems = bom_source.build_tree(rows)
    assert [n["material_code"] for n in nodes] == ["ASSY-A"]
    assert problems and "找不到上一层父级" in problems[0]


def test_orphan_before_any_root_is_reported():
    rows = [_row(2, "SUB-ORPHAN", 1, 0)]
    nodes, problems = bom_source.build_tree(rows)
    assert nodes == [] and problems


@pytest.mark.asyncio
async def test_no_parent_column_does_not_block_explosion():
    """parent_sap 全空也能展开：结构在行序里，不在那一列。"""
    rows = [_row(1, "ASSY-A", 2, 0), _row(2, "RAW-B", 3, 1)]
    for r in rows:
        r["parent_part"] = None  # 镜像里 parent 列就是空的

    async def fake(*a, **k):
        return rows

    class _R:
        def mappings(self): return self
        def all(self): return []

    db = MagicMock()
    calls = []

    async def execute(statement, params=None):
        calls.append(str(statement))
        r = MagicMock()
        if "enghub_bom_items" in str(statement) and "level" in str(statement) and "SUM" not in str(statement):
            r.mappings.return_value.all.return_value = rows
        else:
            r.mappings.return_value.all.return_value = []
        r.scalars.return_value.all.return_value = []
        return r

    db.execute = execute
    out = await bom_source.explode_requirement(db, "FAC_MECH_001", "A-50-04-F", 10)
    assert out["problems"] == []
    assert out["nodes"] == 2 and out["max_level"] == 2
    # ASSY-A 毛需求 20、无库存 -> 净 20；RAW-B 挂在 ASSY-A 下：20×3=60
    by_code = {l["material_code"]: l for l in out["lines"]}
    assert by_code["ASSY-A"]["required_qty"] == 20
    assert by_code["RAW-B"]["required_qty"] == 60
    assert by_code["RAW-B"]["parent_code"] == "ASSY-A"


@pytest.mark.asyncio
async def test_item_type_splits_selfmade_from_purchased():
    """自制/采购分流：有下级 **且子树写得出工序字样**才算自制。

    旧口径只看结构（有下级=自制）。10-05 用户补了工厂事实：軸承組、電源線这类
    买进来就带结构的组件，子树里没有任何工序字样，把它们判成自制只会卡在
    "缺工艺路线"里；现在归采购口径，缺口才能落到对的人手上。
    """
    rows = [
        {**_row(1, "ASSY-A", 2, 0), "attribute_text": "ASSY-A;;;"},
        {**_row(2, "SUB-B", 3, 1), "attribute_text": "SUB-B;;烤漆;;;"},
        {**_row(3, "RAW-C", 1, 2), "attribute_text": "RAW-C;;;"},
    ]

    async def execute(statement, params=None):
        r = MagicMock()
        if "enghub_bom_items" in str(statement) and "SUM" not in str(statement):
            r.mappings.return_value.all.return_value = rows
        else:
            r.mappings.return_value.all.return_value = []
        r.scalars.return_value.all.return_value = []
        return r

    db = MagicMock()
    db.execute = execute
    out = await bom_source.explode_requirement(db, "FAC_MECH_001", "A-50-04-F", 10)
    by_code = {l["material_code"]: l for l in out["lines"]}
    assert by_code["ASSY-A"]["item_type"] == "make"
    assert by_code["SUB-B"]["item_type"] == "make"      # 它也有下级
    assert by_code["RAW-C"]["item_type"] == "buy"
    assert out["make_parts"] == 2 and out["buy_parts"] == 1


@pytest.mark.asyncio
async def test_merged_placement_keeps_level_and_parent_together():
    """同一料号出现在多处时，报哪一层就写那一层的父级，不能层与父级来自不同位置。"""
    rows = [_row(1, "ASSY-A", 1, 0), _row(2, "SHARED", 2, 1), _row(3, "RAW-X", 1, 2),
            _row(1, "ASSY-B", 1, 3), _row(2, "RAW-Y", 1, 4), _row(2, "SHARED", 5, 5)]

    async def execute(statement, params=None):
        r = MagicMock()
        if "enghub_bom_items" in str(statement) and "SUM" not in str(statement):
            r.mappings.return_value.all.return_value = rows
        else:
            r.mappings.return_value.all.return_value = []
        r.scalars.return_value.all.return_value = []
        return r

    db = MagicMock()
    db.execute = execute
    out = await bom_source.explode_requirement(db, "FAC_MECH_001", "A-50-04-F", 10)
    shared = [l for l in out["lines"] if l["material_code"] == "SHARED"]
    assert len(shared) == 1, "同一料号的多处位置要汇总成一行"
    assert shared[0]["level"] == 2 and shared[0]["parent_code"] in {"ASSY-A", "ASSY-B"}
    assert shared[0]["required_qty"] == 70, "2×10 + 5×10 两处毛需求都要算进来"


@pytest.mark.asyncio
async def test_readiness_names_the_missing_master_data_piece():
    """自制件开不出工单时，要说清缺的是主档、路线还是工步 —— 三种缺法补法不一样。"""
    masters = [
        {"material_code": "HAS-MASTER-OTHER-FACTORY", "master_factory_id": "FAC_ELEC_DEMO_2026",
         "routing_id": "rt-1", "step_rows": 3, "step_json": 0},
        {"material_code": "NO-ROUTING", "master_factory_id": "FAC_MECH_001",
         "routing_id": None, "step_rows": 0, "step_json": 0},
        {"material_code": "EMPTY-ROUTING", "master_factory_id": "FAC_MECH_001",
         "routing_id": "rt-2", "step_rows": 0, "step_json": 0},
        # 推导/种子路线把工步写在 routings.steps JSON 里，routing_steps 表是空的
        {"material_code": "JSON-STEPS-ROUTE", "master_factory_id": "FAC_MECH_001",
         "routing_id": "rt-bom-x", "step_rows": 0, "step_json": 2},
        {"material_code": "READY", "master_factory_id": "FAC_MECH_001",
         "routing_id": "rt-3", "step_rows": 6, "step_json": 0},
    ]
    db = _session(masters)
    out = await bom_source.production_readiness(
        db, "FAC_MECH_001",
        ["NO-MASTER", "HAS-MASTER-OTHER-FACTORY", "NO-ROUTING", "EMPTY-ROUTING",
         "JSON-STEPS-ROUTE", "READY"],
    )
    assert out["NO-MASTER"] == "missing_master"
    assert out["HAS-MASTER-OTHER-FACTORY"] == "master_other_factory"
    assert out["NO-ROUTING"] == "no_routing"
    assert out["EMPTY-ROUTING"] == "empty_routing"
    assert out["JSON-STEPS-ROUTE"] == "ready", "工步写在 JSON 里也算有路线，APS 读的就是它"
    assert out["READY"] == "ready"


def test_readiness_rollup_only_counts_selfmade_and_drops_empty_buckets():
    items = [
        {"material_code": "A", "item_type": "make", "production_readiness": "missing_master", "net_qty": 68},
        {"material_code": "B", "item_type": "make", "production_readiness": "missing_master", "net_qty": 132},
        {"material_code": "C", "item_type": "make", "production_readiness": "ready", "net_qty": 0},
        {"material_code": "D", "item_type": "buy", "production_readiness": None, "net_qty": 500},
    ]
    roll = bom_source.readiness_rollup(items)
    assert roll["missing_master"] == {"parts": 2, "shortage_qty": 200}
    assert "ready" not in roll, "没有缺口的自制件不算待办，种数要和缺口对齐"
    assert "no_routing" not in roll, "没有自制件的桶不该出现在读数里"


@pytest.mark.asyncio
async def test_subtree_evidence_keeps_material_and_surface_finish():
    """半成品的佐证材料要含**属性原文**（材料/表面處理），不能只有清洗后的品名。

    用户给的工厂口径：L3 就是半成品，下层就在同一个上传文件里；
    "烤漆/鹽浴滲氮/45#" 这些工序出处全在被 clean_name 砍掉的那几段里。
    """
    rows = [
        {"material_code": "A-50-04-F", "material_name": "跑步機", "qty_per_unit": 1,
         "unit": "PCS", "level": 1, "original_row_number": 1, "source_file": "f.xlsx",
         "vendor_code": None, "vendor_name": None,
         "attribute_text": "跑步機;;;;", "l3_context": None},
        {"material_code": "1000461221", "material_name": "車架組", "qty_per_unit": 1,
         "unit": "PCS", "level": 2, "original_row_number": 2, "source_file": "f.xlsx",
         "vendor_code": None, "vendor_name": None,
         "attribute_text": "車架組;;;烤漆;DM334;;EP298;", "l3_context": None},
        {"material_code": "1000461222", "material_name": "車架組", "qty_per_unit": 2,
         "unit": "PCS", "level": 3, "original_row_number": 3, "source_file": "f.xlsx",
         "vendor_code": None, "vendor_name": None,
         "attribute_text": "車架組;;;焊接;;EP298", "l3_context": "車架組;;;烤漆;DM334;;EP298;"},
        {"material_code": "1000341659", "material_name": "五通管", "qty_per_unit": 2,
         "unit": "PCS", "level": 4, "original_row_number": 4, "source_file": "f.xlsx",
         "vendor_code": None, "vendor_name": None,
         "attribute_text": "五通管;車架;口50x100;;;45#;EP589", "l3_context": "車架組;;;烤漆;"},
    ]
    db = _session(rows)
    out = await bom_source.subtree_evidence(db, "FAC_MECH_001", "A-50-04-F", ["1000461221"])
    text = out["evidence"]["1000461221"]
    assert out["source"] == "engflow_mirror_tree"
    assert "焊接" in text and "烤漆" in text and "45#" in text
    assert out["codes_with_text"] == 1


@pytest.mark.asyncio
async def test_subtree_evidence_unions_every_placement():
    """同一料号出现在多处时，两处子树都要算进来。

    齐套快照把多父级的行合并且只留一个 parent_code，拿它当语料会漏掉另一半结构。
    """
    rows = [
        {"material_code": "ROOT", "material_name": "整機", "qty_per_unit": 1, "unit": "PCS",
         "level": 1, "original_row_number": 1, "source_file": "f.xlsx",
         "vendor_code": None, "vendor_name": None, "attribute_text": "整機;;;", "l3_context": None},
        {"material_code": "共用件", "material_name": "側板", "qty_per_unit": 1, "unit": "PCS",
         "level": 2, "original_row_number": 2, "source_file": "f.xlsx",
         "vendor_code": None, "vendor_name": None, "attribute_text": "側板;;;電鍍;;;", "l3_context": None},
        {"material_code": "共用件", "material_name": "側板", "qty_per_unit": 1, "unit": "PCS",
         "level": 2, "original_row_number": 3, "source_file": "f.xlsx",
         "vendor_code": None, "vendor_name": None, "attribute_text": "側板;;;鹽浴滲氮;;;", "l3_context": None},
    ]
    db = _session(rows)
    out = await bom_source.subtree_evidence(db, "FAC_MECH_001", "ROOT", ["共用件"])
    text = out["evidence"]["共用件"]
    assert "電鍍" in text and "鹽浴滲氮" in text


@pytest.mark.asyncio
async def test_subtree_evidence_falls_back_then_says_none():
    """镜像没有这个型号的结构时退回本地 BOM（只有一层）；两份都没有就报没有。"""
    db = _session([], [{"material_code": "RM-1", "material_name": "鋼板 45#"}])
    out = await bom_source.subtree_evidence(db, "FAC_MECH_001", "VF-CMECH001-40HQ", ["RM-1"])
    assert out["source"] == "local_bom_flat"
    assert out["evidence"]["RM-1"] == "鋼板 45#"

    empty = _session([])
    none = await bom_source.subtree_evidence(empty, "FAC_MECH_001", "NOPE", ["X"])
    assert none["source"] == "none" and none["codes_with_text"] == 0

@pytest.mark.asyncio
async def test_finished_good_row_is_not_a_material_of_itself():
    """上传文件第 1 行是成品自己的料号（`MF;A-50-04-F;EP298;US;110V;M`）。

    行序重建会把整台机器挂到它名下，于是"这台机器的物料里有这台机器"，
    还会给它开一张下级工单。齐套表要把它认出来并剔掉，同时报出来让人核对。
    """
    rows = [
        {**_row(1, "MEP1791-P0", 1, 0), "attribute_text": "MF;A-50-04-F;EP298;US;110V;M"},
        {**_row(2, "車架組", 1, 1), "attribute_text": "車架組;半成品;;;;"},
        {**_row(3, "五通管", 2, 2), "attribute_text": "五通管;車架;;;45#;"},
    ]

    async def execute(statement, params=None):
        r = MagicMock()
        if "enghub_bom_items" in str(statement) and "SUM" not in str(statement):
            r.mappings.return_value.all.return_value = rows
        else:
            r.mappings.return_value.all.return_value = []
        r.scalars.return_value.all.return_value = []
        return r

    db = MagicMock()
    db.execute = execute
    out = await bom_source.explode_requirement(db, "FAC_MECH_001", "A-50-04-F", 10)
    codes = [line["material_code"] for line in out["lines"]]
    assert out["self_rows_excluded"] == ["MEP1791-P0"]
    assert "MEP1791-P0" not in codes
    assert codes == ["車架組", "五通管"], "剔掉成品自己的行，不能连累它下层的真实用量"
    assert next(l for l in out["lines"] if l["material_code"] == "五通管")["required_qty"] == 20


@pytest.mark.asyncio
async def test_finished_good_row_gets_no_subtree_evidence():
    """同一个判据也管住佐证语料：成品的"子树"就是整台机器，拿它佐证等于想套什么都有证据。"""
    rows = [
        {**_row(1, "MEP1791-P0", 1, 0), "attribute_text": "MF;A-50-04-F;EP298;US;110V;M",
         "l3_context": None, "source_file": "f.xlsx", "unit": "PCS", "material_name": "MF",
         "vendor_code": None, "qty_per_unit": 1, "level": 1, "original_row_number": 0},
        {**_row(2, "車架組", 1, 1), "attribute_text": "車架組;;;烤漆;;EP298",
         "l3_context": None, "source_file": "f.xlsx", "unit": "PCS", "material_name": "車架組",
         "vendor_code": None, "qty_per_unit": 1, "level": 2, "original_row_number": 1},
    ]
    db = _session(rows)
    out = await bom_source.subtree_evidence(
        db, "FAC_MECH_001", "A-50-04-F", ["MEP1791-P0", "車架組"])
    assert out["finished_good_rows"] == ["MEP1791-P0"]
    assert "MEP1791-P0" not in out["evidence"]
    assert "烤漆" in out["evidence"]["車架組"]

@pytest.mark.asyncio
async def test_subassembly_without_any_process_wording_is_purchased_not_selfmade():
    """有下级 ≠ 自制。用户的工厂口径（10-05）：子树里写不出工序字样就是买进来的组件。

    軸承組（`HRB/輝遠` 轴承）这种带下层的东西，判成自制会去追一条"缺工艺路线"，
    而它真正该走的是采购下 PO。
    """
    rows = [
        {**_row(1, "ROOT", 1, 0), "attribute_text": "整機;;;"},
        {**_row(2, "軸承組", 1, 1), "attribute_text": "軸承組;半成品;;;;EP591;"},
        {**_row(3, "軸承", 2, 2), "attribute_text": "軸承;自動調心;2201-2RS;;;HRB/輝遠"},
        {**_row(2, "車架組", 1, 3), "attribute_text": "車架組;半成品;;;;EP298;"},
        {**_row(3, "五通管", 2, 4), "attribute_text": "五通管;車架;口50x100;;;焊接;EP298;"},
    ]

    async def execute(statement, params=None):
        r = MagicMock()
        if "enghub_bom_items" in str(statement) and "SUM" not in str(statement):
            r.mappings.return_value.all.return_value = rows
        else:
            r.mappings.return_value.all.return_value = []
        r.scalars.return_value.all.return_value = []
        return r

    db = MagicMock()
    db.execute = execute
    out = await bom_source.explode_requirement(db, "FAC_MECH_001", "ROOT", 10)
    by_code = {line["material_code"]: line for line in out["lines"]}
    assert by_code["軸承組"]["item_type"] == "buy", "没工序证据的带下层件是外购组件"
    assert by_code["車架組"]["item_type"] == "make", "下层写着焊接，车架组才是厂内要做的"
    assert out["purchased_assemblies"] == ["軸承組"]
    # 需求量不变，只是归到对的人手里
    assert by_code["軸承組"]["required_qty"] == 10
