"""就绪度归因的单测：分类顺序错了就会把"根本不该有齐套行"的单算成"跑一次能补"。"""

from api.services import sim_backtest as sb


def test_seed_orders_never_count_as_fixable():
    assert sb.classify_gap({"is_seed": True, "own_bom_lines": 30, "is_child": False}) == "seed"


def test_container_pseudo_product_is_not_a_missing_kit():
    row = {"is_seed": False, "own_key": "VF-CMECH001-40HQ", "own_bom_lines": 3,
           "is_child": False}
    assert sb.classify_gap(row) == "pseudo_product"


def test_child_component_without_bom_is_source_gap():
    row = {"is_seed": False, "own_key": "1000461220", "own_bom_lines": 0, "is_child": True}
    assert sb.classify_gap(row) == "child_no_bom"


def test_key_absent_from_bom_mirror_is_master_data_gap():
    row = {"is_seed": False, "own_key": "MPL0113-00", "own_bom_lines": 0, "is_child": False}
    assert sb.classify_gap(row) == "key_no_bom"


def test_only_orders_with_bom_and_key_are_fixable_by_rerun():
    row = {"is_seed": False, "own_key": "A-50-04-F", "own_bom_lines": 16, "is_child": False}
    assert sb.classify_gap(row) == "flow_missing_kit"


def test_bucket_labels_cover_every_reason_key():
    assert set(sb.BUCKET_LABELS) == {
        "child_no_bom", "key_no_bom", "pseudo_product", "seed", "flow_missing_kit",
        "backtest_no_planned_start", "backtest_model_no_bom"}


def test_readiness_thresholds_are_stated_in_human_units():
    # 判线口径改动要同时改这里与 engine_layers.THRESHOLDS，不能两边各写一个数
    assert sb.MIN_COMPARABLE_MODELS == 5 and sb.MIN_BACKTEST_PAIRS == 10
    assert "cancelled" not in sb.IN_FLOW
