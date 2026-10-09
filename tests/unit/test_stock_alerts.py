"""报警对账的规矩：只关"本轮评估过且条件已消失"的，没评估到的类型一条都不许碰。

这条是"对账型写入要全集"的 WMS 版本 —— 一次局部重算把别人开的告警整批关掉，
界面看起来是"告警都处理完了"，实际是没人评估过它们。
"""
from api.services.stock_alerts import ALERT_KINDS, merge_alerts


def _a(mid, qty=0, wh="wh1", batch=None):
    return {"material_id": mid, "material_code": f"M{mid}", "warehouse_id": wh,
            "batch_code": batch, "current_qty": qty, "threshold_qty": 1}


def test_new_alerts_are_created_and_repeats_are_renewed():
    firing = {"zero_stock": [_a("m1"), _a("m2")]}
    open_rows = [{"alert_type": "zero_stock", "material_id": "m1", "batch_code": "",
                  "warehouse_id": "wh1", "status": "open"}]
    plan = merge_alerts(firing, open_rows)
    assert plan["to_create_count"] == 1
    assert plan["to_create"][0]["material_id"] == "m2"
    assert plan["renewed_count"] == 1
    assert plan["to_close_count"] == 0


def test_alerts_whose_kind_was_not_evaluated_stay_open():
    """本轮只跑了 zero_stock，别的类型的老告警一条都不许关。"""
    firing = {"zero_stock": []}
    open_rows = [
        {"alert_type": "zero_stock", "material_id": "m1", "batch_code": "",
         "warehouse_id": "wh1", "status": "open"},
        {"alert_type": "below_reorder_point", "material_id": "m9", "batch_code": "",
         "warehouse_id": "wh1", "status": "open"},
    ]
    plan = merge_alerts(firing, open_rows)
    assert plan["to_close_count"] == 1
    assert plan["to_close"][0]["alert_type"] == "zero_stock"
    assert plan["left_alone_count"] == 1, "没评估过的类型必须原样留着"


def test_condition_gone_closes_with_an_auditable_reason():
    plan = merge_alerts({"zero_stock": []},
                        [{"alert_type": "zero_stock", "material_id": "m1", "batch_code": "",
                          "warehouse_id": "wh1", "status": "open"}])
    assert plan["to_close"] == [{"alert_type": "zero_stock", "material_id": "m1",
                                 "warehouse_id": "wh1"}]


def test_every_kind_has_a_declared_basis():
    """四把尺都要写明"判它的是什么数"，读的人不用回头翻代码。"""
    assert len(ALERT_KINDS) == 4
    for kind, severity, basis in ALERT_KINDS:
        assert basis and severity in ("critical", "warning", "info"), kind


def test_warehouse_is_part_of_the_identity_but_batch_is_not():
    """`stock_alerts` 没有 batch_code 列 → 同料同仓的不同批次会并成一条（表的限制，写清）。"""
    firing = {"zero_stock": [_a("m1", batch="B1", wh="wh1"), _a("m1", batch="B2", wh="wh1"),
                             _a("m1", batch="B1", wh="wh2")]}
    plan = merge_alerts(firing, [])
    assert plan["to_create_count"] == 2, "两个仓两条，同仓两批次并成一条"
    whs = sorted({p["warehouse_id"] for p in plan["to_create"]})
    assert whs == ["wh1", "wh2"]
