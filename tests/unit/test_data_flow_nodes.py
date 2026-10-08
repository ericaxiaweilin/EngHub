"""数据流节点剖面的判据：分类不许漂，外推不许变成事实。"""
import pytest

pytestmark = [pytest.mark.unit]

from core.mes.data_flow import (GRAPH_SQL, LEDGER_NODES, RUN_NODE_KEYS, scaled_node_need)


def _row(node, rows, kind):
    return {"node": node, "rows": rows, "scales": kind, "status": "ok"}


def test_volume_nodes_scale_by_throughput_and_are_marked_derived():
    """volume 类等比外推是需求估算，必须带 basis=derived 与"不回填事实表"那句。"""
    rows = [_row("镜像多层 BOM 行", 481557, "volume")]
    out = scaled_node_need(rows, factor=4.78927)
    assert out[0]["now"] == 481557
    assert out[0]["needed_at_scale"] == round(481557 * 4.78927)
    assert out[0]["basis"] == "derived"
    assert "绝不回填事实表" in out[0]["why"]


def test_headcount_nodes_move_and_structure_nodes_never_do():
    rows = [_row("考勤在册人头", 1044, "heads"), _row("在册产线", 3, "fixed"),
            _row("工位档案", 28, "fixed")]
    out = {o["node"]: o for o in scaled_node_need(rows, factor=4.78927)}
    assert out["考勤在册人头"]["needed_at_scale"] == 5000
    assert out["考勤在册人头"]["basis"] == "heads"
    # 线数/工位数等比放大就是编数据：结构类节点在缩放下必须一动不动
    assert out["在册产线"]["needed_at_scale"] == 3 and out["在册产线"]["basis"] == "fixed"
    assert out["工位档案"]["needed_at_scale"] == 28


def test_scale_need_never_goes_negative_and_skips_unreadable():
    rows = [_row("工单", 862, "volume"),
            {"node": "路线模板工序", "rows": None, "scales": "volume", "status": "unreadable",
             "why": "关系不存在的表"}]
    out = scaled_node_need(rows, factor=0.0957854)
    assert len(out) == 1, "读不到的节点不能混进需求表"
    assert out[0]["needed_at_scale"] >= 0
    assert out[0]["now"] > out[0]["needed_at_scale"], "缩小时需求本该变小"


def test_every_ledger_node_is_scoped_to_one_factory():
    """每条台账节点都得带 :f —— 少一个绑定条件就会把全库行数当这座厂的节点数。"""
    for node in LEDGER_NODES:
        assert ":f" in node["sql"], f"{node['label']} 没按厂区过滤"
        assert node["scales"] in ("heads", "volume", "fixed"), f"{node['label']} 没定缩放类"


def test_graph_counts_are_declared_without_factory_binding():
    """图结构（表数/外键边）是全库口径，别让它冒充厂区数。"""
    assert set(GRAPH_SQL) == {"public 表数", "有数据的表", "外键边（表→表）"}
    for label, sql in GRAPH_SQL.items():
        assert ":f" not in sql, f"{label} 声称全库却带了厂区条件"


def test_run_node_labels_exist_for_every_counted_key():
    """推演层每个键都要有中文含义，否则读数里会出现没人能解释的数字。"""
    assert set(RUN_NODE_KEYS) == {"bom_parts", "kit_lines", "kit_shortage_lines", "po_lines",
                                 "arrival_critical_parts", "route_steps", "work_days",
                                 "materials_without_price"}


def test_node_profile_wins_over_the_scale_model_when_both_match():
    """"千人工厂有多少数据流节点"两格规则都命中，规模模型会抢走它。

    规模模型答的是结构比例，答不了台账/推演里有几行多少节点 —— 更具体的问法必须排在前面。
    """
    from api.services.chat_tools_service import _resolve_intent_keyword

    hit = _resolve_intent_keyword("千人工厂有多少数据流节点？一次推演流经多少台账行")
    assert hit["tool"] == "query_data_flow_profile"
    assert hit["args"]["headcount"] == 1000, "规模要传进去，否则规模层外推不会出现在答复里"
    # 但纯规模问法仍是架构模型
    assert _resolve_intent_keyword("千人工厂长什么样")["tool"] == "generate_plant_architecture"
