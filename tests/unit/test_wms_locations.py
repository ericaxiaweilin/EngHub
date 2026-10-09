"""WMS 两格的判据测试：库位派生不许编货架结构，能力矩阵不许把"空表"读成"坏了"。"""
from api.services.wms_audit import SNAPSHOT_FRESH_DAYS, _grade
from api.services.wms_locations import MAX_LOCATIONS_PER_RUN, plan_locations

LEDGER = [
    {"warehouse_id": "wh1", "location_code": "LOC-LG-100048", "line_count": 996,
     "material_count": 996, "total_qty": 1559902},
    {"warehouse_id": "wh1", "location_code": "LOC-LG-100047", "line_count": 868,
     "material_count": 868, "total_qty": 5350717},
    {"warehouse_id": "wh2", "location_code": "LOC-LG-000009", "line_count": 454,
     "material_count": 400, "total_qty": 467615},
]


def test_plan_creates_one_object_per_warehouse_and_code():
    plan = plan_locations(LEDGER, existing_codes=[], warehouse_names={"wh1": "原料仓"})
    assert plan["would_create"] == 3
    row = plan["rows"][0]
    assert row["location_code"] == "LOC-LG-100048" and row["warehouse_id"] == "wh1"
    assert row["warehouse_name"] == "原料仓"


def test_plan_does_not_invent_shelf_structure_or_capacity():
    """库位号 `LOC-LG-100048` 里没有排/层/列信息 —— 硬解析出来就是我编的货架。"""
    plan = plan_locations(LEDGER, existing_codes=[], warehouse_names={})
    for row in plan["rows"]:
        assert row["capacity"] is None, "容量没人声明过就不许填一个数上去"
        assert row["zone"] is None and row["aisle"] is None and row["level"] is None
        assert row["location_name"] == row["location_code"], "厂里没给名字就不替他起一个"


def test_plan_is_idempotent_per_warehouse_and_code():
    plan = plan_locations(LEDGER, existing_codes=["wh1|LOC-LG-100048"], warehouse_names={})
    assert plan["would_create"] == 2
    assert plan["skipped"][0]["why"] == "已登记，不重复开"
    # 同一个 (仓库,号) 永远同一个主键：回填 inventory.location_id 靠它，撞号就挂错格子
    again = plan_locations(LEDGER, existing_codes=[], warehouse_names={})
    ids = [r["id"] for r in again["rows"]]
    assert len(set(ids)) == len(ids)
    assert ids[0] == plan_locations(LEDGER, existing_codes=[], warehouse_names={})["rows"][0]["id"]


def test_plan_caps_per_run_and_says_so():
    many = [{"warehouse_id": "wh1", "location_code": f"LOC-{i}", "line_count": 1,
             "material_count": 1, "total_qty": 1} for i in range(MAX_LOCATIONS_PER_RUN + 5)]
    plan = plan_locations(many, existing_codes=[], warehouse_names={})
    assert plan["would_create"] == MAX_LOCATIONS_PER_RUN
    assert any("单轮上限" in x["why"] for x in plan["skipped"])


def test_empty_table_reads_as_empty_not_broken():
    """判词四态要分得开：0 行=没被走过；缺外部新数=不判；两者都不是"坏了"。"""
    g = _grade("empty", "盘点", "inventory_counts 0 单", so_what="没验证过账实", missing="开周期盘点")
    assert g["state"] == "empty" and g["missing"] == "开周期盘点"
    b = _grade("blocked_on_source", "账实核对", "快照停在 2026-03-22")
    assert b["state"] == "blocked_on_source"
    assert SNAPSHOT_FRESH_DAYS > 0, "新鲜度线必须是个数，不能靠临场感觉"
