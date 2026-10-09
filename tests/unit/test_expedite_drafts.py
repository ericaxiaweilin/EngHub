"""催购 → 请购草稿：判据是纯函数，写库那一半靠开关，引擎不能给自己造证据。

三条必须钉住的性质：
1. 就绪门：没供应商 / 没主档 / 缺口不是正数 → 不开单，并点名为什么不开（不许静默丢）；
2. 幂等：同一条推荐（task_key）+ 同一个料号只开一张；
3. 自供证据：引擎自己写的草稿不能算进「建议落地了没有」的证据，批/拒要人的账号署名。
"""
from api.services.expedite_drafts import (
    decision_summary,
    draft_ids,
    plan_drafts,
    short_ref,
)

MASTER = {"RM-A": {"id": "m1", "material_code": "RM-A", "material_name": "电机"},
          "RM-B": {"id": "m2", "material_code": "RM-B", "material_name": "轴承"}}


def _act(**kw):
    base = {"type": "expedite_purchase", "material_code": "RM-A", "qty_short": 1200,
            "supplier": "中联重工(佛山)", "target_lead_days": 10, "current_lead_days": 20,
            "required_arrival_date": "2026-11-01", "order_by_date": "2026-10-09",
            "scenario": "暴雨（到岗 0.70）", "model_code": "FG-TREAD-001",
            "evidence_flags": ["提前期 20 天的依据=ledger_declared（不是实测交期）"]}
    base.update(kw)
    return base


def test_plan_opens_one_draft_per_recommended_part():
    plan = plan_drafts([_act()], existing_keys=[], master=MASTER, task_key="tk1")
    assert plan["would_write"] == 1 and plan["skipped"] == []
    row = plan["rows"][0]
    assert row["material_code"] == "RM-A" and row["qty"] == 1200
    # source_id 那一列只有 50 字，所以写的是推荐的短引用 + 料号（不是整串 task_key）
    assert row["source_id"] == f"{short_ref('tk1')}|RM-A"
    # 到货日取动作自己给的，不是"今天加一周"这种拍出来的数
    assert str(row["required_date"]) == "2026-11-01"
    assert row["priority"] == "URGENT", "暴雨档要标成紧急，不能和正常档同形"
    assert row["evidence_flags"], "依据旗标要跟着草稿走，采购员得知道这个提前期是几手的"


def test_plan_refuses_to_draft_without_supplier_or_master_data():
    plan = plan_drafts([_act(supplier=""), _act(material_code="RM-Z"),
                        _act(material_code="RM-B", qty_short=0),
                        _act(type="split_release")],
                       existing_keys=[], master=MASTER, task_key="tk1")
    assert plan["would_write"] == 0
    whys = "；".join(x["why"] for x in plan["skipped"])
    assert "没有供应商" in whys and "主档" in whys and "缺口件数" in whys, "跳过必须点名原因"


def test_plan_is_idempotent_per_recommendation_and_part():
    plan = plan_drafts([_act()], existing_keys=[f"{short_ref('tk1')}|RM-A"],
                       master=MASTER, task_key="tk1")
    assert plan["would_write"] == 0
    assert plan["skipped"][0]["why"] == "这条推荐已有活着的草稿，不重复开"
    # 同一条推荐里同一料号出现两次（多个场景都点名它）只开一张
    twice = plan_drafts([_act(), _act(scenario="雨季（到岗 0.85）")],
                        existing_keys=[], master=MASTER, task_key="tk1")
    assert twice["would_write"] == 1


def test_draft_id_is_stable_so_the_database_enforces_idempotence():
    a = draft_ids("tk1", "RM-A")
    assert a == draft_ids("tk1", "RM-A") != draft_ids("tk1", "RM-B")


def test_plan_caps_per_run_and_says_so():
    plan = plan_drafts([{**_act(), "material_code": f"RM-{i}"} for i in range(9)],
                       existing_keys=[],
                       master={f"RM-{i}": {"id": f"m{i}", "material_code": f"RM-{i}",
                                           "material_name": ""} for i in range(9)},
                       task_key="tk9", limit=2)
    assert plan["would_write"] == 2
    assert any("单轮上限" in x["why"] for x in plan["skipped"])


def test_only_human_signatures_count_as_a_disposition():
    summary = decision_summary([
        {"pr_code": "P1", "material_code": "RM-A", "status": "pending",
         "approved_by": None, "auto_approved": False},
        {"pr_code": "P2", "material_code": "RM-A", "status": "approved",
         "approved_by": "eric", "auto_approved": False},
        # 系统自己批掉的（金额低于阈值自动通过）不是人对引擎的态度
        {"pr_code": "P3", "material_code": "RM-B", "status": "approved",
         "approved_by": "system", "auto_approved": True},
        {"pr_code": "P4", "material_code": "RM-C", "status": "rejected",
         "approved_by": "eric", "auto_approved": False},
        {"pr_code": "P5", "material_code": "RM-D", "status": "cancelled",
         "approved_by": "virtual_factory", "auto_approved": False},
    ])
    assert summary["waiting"] == 1
    assert summary["adopted_by_human"] == 1
    assert summary["rejected_by_human"] == 1
    assert summary["closed_by_machine"] == 2
    assert summary["total"] == 5
    assert summary["detail"][2]["reads_as"] == "系统自己转的（没人表态）"


def test_followthrough_ruler_excludes_engine_drafts():
    """引擎自己写的草稿不能算"有人动过" —— 排除条件必须写在那条 SQL 里。

    这一格是判据的一部分：#63 之后催购会自动开 pending 草稿，如果复查按料号数单据
    不分成因，引擎写一批草稿就能把自己上一轮"建议没落地"的判词刷成"有下落"。
    """
    from api.services.virtual_run import FOLLOWTHROUGH_SQL

    sql = str(FOLLOWTHROUGH_SQL)
    assert "COALESCE(rq.source, '') <> 'simulation_recommendation'" in sql
    assert "engine_draft_since" in sql, "草稿数要单列成一格，而不是混进证据里"
