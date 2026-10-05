"""PMC 控制塔：确定性路由和答复契约测试。"""

from api.routes.chat_routes import _direct_tool_reply
from api.services.chat_tools_service import TOOL_DEFINITIONS, resolve_intent
from api.services.pmc_control_tower_service import PmcControlTowerService


def _tool_names():
    return {
        item["function"]["name"]
        for item in TOOL_DEFINITIONS
        if item.get("type") == "function"
    }


def test_pmc_nine_question_bundle_is_forced_to_control_tower():
    message = (
        "PMC能不能回答;排过多少订单;控过多少物料;shortage怎么处理;库存怎么降;"
        "OTD怎么保证;产能怎么平衡;紧急插单怎么排;EC/BOM change怎么处理;"
        "supplier delay怎么处理"
    )
    intent = resolve_intent(message)

    assert intent == {"tool": "query_pmc_control_tower", "args": {"scope": "all"}}


def test_each_pmc_question_maps_to_its_fact_scope():
    cases = {
        "排过多少订单": "orders",
        "控过多少物料": "materials",
        "shortage怎么处理": "shortage",
        "库存怎么降": "inventory",
        "OTD怎么保证": "otd",
        "产能怎么平衡": "capacity",
        "紧急插单怎么排": "rush",
        "EC/BOM change怎么处理": "engineering_change",
        "supplier delay怎么处理": "supplier_delay",
    }
    for message, scope in cases.items():
        intent = resolve_intent(message)
        assert intent and intent["tool"] == "query_pmc_control_tower"
        assert intent["args"]["scope"] == scope


def test_data_gap_question_also_uses_control_tower_evidence():
    intent = resolve_intent("需要补齐什么数据，才能让PMC回答这些问题")

    assert intent == {"tool": "query_pmc_control_tower", "args": {"scope": "all"}}


def test_control_tower_is_exposed_and_direct_reply_contains_all_sections():
    assert "query_pmc_control_tower" in _tool_names()
    result = {
        "type": "pmc_control_tower",
        "factory_id": "FAC_MECH_001",
        "scope": "all",
        "facts": {
            "orders": {"scheduled_order_count": 2, "aps_schedule_count": 1, "aps_task_count": 4, "mps_plan_count": 3, "mps_planned_qty": 54, "work_order_count": 3, "master_work_order_count": 3},
            "materials": {"controlled_material_count": 5, "bom_material_count": 5, "work_order_material_count": 5, "inventory_sku_count": 5, "historical_transaction_material_count": 2, "inventory_transaction_count": 8},
            "shortage": {"affected_work_order_count": 1, "shortage_material_count": 1, "total_shortage_qty": 2, "items": []},
            "inventory": {"sku_count": 5, "total_qty": 10, "available_qty": 8, "reserved_qty": 2, "stagnant_count": 0, "stagnant_threshold_days": 180, "items": []},
            "otd": {"otd_scope": "work_order_fallback", "due_order_count": 2, "completed_order_count": 1, "on_time_order_count": 1, "otd_pct": 100.0, "open_overdue_count": 0},
            "capacity": {"load_source": "routing_UHN_and_station_CPH", "bottlenecks": [], "stations": []},
            "rush": {"approval_count": 0, "executed_count": 0, "status_counts": {}, "simulation": {}},
            "engineering_change": {"ecn_count": 0, "ecn_marked_work_order_count": 0, "bom_product_version_count": 1},
            "supplier_delay": {"po_count": 0, "open_po_count": 0, "overdue_count": 0, "max_delay_days": 0},
        },
        "data_quality": [],
        "actions": [],
    }
    reply = _direct_tool_reply("query_pmc_control_tower", result)
    for heading in ("订单排程", "物料控制", "Shortage", "库存下降", "OTD", "产能平衡", "紧急插单", "EC/BOM变更", "Supplier delay"):
        assert heading in reply


def test_selfmade_blocker_names_the_missing_master_data_object():
    """自制件开不出工单时，建议动作要点名卡在哪一样，并说清哪一样系统能自己补。"""
    facts = {
        "shortage": {
            "total_shortage_qty": 20731,
            "selfmade_readiness": {
                "no_routing": {"parts": 123, "shortage_qty": 20731},
                "ready": {"parts": 4, "shortage_qty": 0},
            },
        }
    }
    actions = PmcControlTowerService(None)._actions(facts)
    blocker = [a for a in actions if "自制件排不动" in a]
    assert blocker and "缺工艺路线 123 种" in blocker[0]
    assert "ready" not in blocker[0], "已就绪的件不该混进阻塞清单"
    assert "工艺路线与工步只能由工艺给" in blocker[0], "要说清系统不会替工厂编路线"


def test_shortage_only_counts_master_snapshot_once():
    """缺口只在主工单齐套快照上数一次；下级工单是同一需求的执行，不能重复计入。"""
    from api.services.pmc_control_tower_service import PmcControlTowerService

    src = PmcControlTowerService._shortage.__code__.co_consts
    assert any("wo.wo_type = 'master'" in str(c) for c in src), \
        "取缺口的 SQL 必须限定主工单快照，否则 component 工单会把同一批料数两遍"
    note = " ".join(str(c) for c in src)
    assert "不重复计入" in note, "口径要写在读数说明里，不然别人还会再加一遍"
