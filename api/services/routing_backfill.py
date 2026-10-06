"""引擎循环：把没有工艺路线的在制工单补到能排程。

链路上这是最后一段自动活：MRP 多层展开算出要做什么 → 半成品主档按 BOM 自动登记 →
工艺路线按产品族推导（要 BOM 文本佐证才套）。三段里前两段已经在计划下达时做了，
但**历史工单**是在主档/路线还没有的时候建起来的，`routing_id` 为空，
APS 每次都把它们列进 unrouted 清单，永远排不动（实测厂区 65 张未关闭主工单里 64 张如此）。

这个循环每轮：
1. 找若干张「主工单 + 未关闭 + routing_id IS NULL」的 (厂区, 产品)；
2. 逐个走 `derive_routing_for_product`（同族路线 + BOM 文本佐证率 ≥ 50% 才套）；
3. 套上了（或产品本来就有带工步的路线）才回填工单的 `routing_id`，
   **只动 routing_id IS NULL 的行**，不覆盖人工指定过的路线，也不碰已完成/取消的工单；
4. 逐轮写心跳，把 examined/derived/routed_work_orders 和拒绝原因都报出来 ——
   没人看界面猜"引擎在干活吗"，心跳里就是这一轮干了多少。

回填之后排产本身仍由 `periodic-scheduler` 的 APS 轮次负责：这个循环不排程、不下发，
只把"排不动"变成"能排"。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List

from sqlalchemy import bindparam, text

from api.services.bom_data_quality import scan_plant
from api.services.bom_source import subtree_evidence
from api.services.engine_heartbeat import record
from api.services.component_orders import (
    expand_ready_components,
    rebuild_missing_component_kits,
    retire_covered_child_orders,
)
from api.services.component_release import release_kitted_child_orders
from api.services.purchase_receipts import receive_due_purchase_orders
from api.services.line_strategy_advisor import advise_line_strategy
from api.services.time_basis import time_basis_review
from api.services.data_authority import data_authority_report
from api.services.partial_kit import report_partial_kit_splits
from api.services.portfolio_flywheel import run_once as run_portfolio_cycle
from api.services.portfolio_flywheel import record_tradeoffs as record_sim_tradeoffs
from api.services.material_followup import CHASE_LIMIT as MATERIAL_CHASE_LIMIT, chase_material_shortages
from api.services.chain_convergence import report as convergence_report
from api.services.aps_draft_prune import (
    APPLY_ENABLED as DRAFT_PRUNE_APPLY,
    KEEP_VERSIONS as DRAFT_KEEP_VERSIONS,
    prune_superseded_drafts,
)
from api.services.plan_commit_gate import (
    APPLY_ENABLED as PLAN_COMMIT_APPLY,
    MAX_ORDERS as PLAN_COMMIT_MAX_ORDERS,
    audit_false_releases,
    commit_ready_orders,
)
from api.services.snapshot_supply import refresh_snapshot_supply
from api.services.routing_from_family import (
    CREATED_BY,
    MIN_COMPONENT_STEPS,
    corroborated_component_subset,
    derive_routing_for_component,
    derive_routing_for_product,
)

logger = logging.getLogger(__name__)

BACKFILL_INTERVAL_SECONDS = 900
# 开发/测试阶段的规模闸门（用户 10-04 定的口径：从小到大，别一把推成全量）：
# - 一轮只看几个产品；
# - 推导出来的路线总数有预算，用完就停，要继续得显式改环境变量。
#   没有预算的话这个循环会在后台一路把 473 个型号全推一遍。
BATCH_PRODUCTS = max(1, int(os.getenv("ROUTING_BACKFILL_BATCH", "5")))
MAX_DERIVED_ROUTES = max(0, int(os.getenv("ROUTING_BACKFILL_MAX_ROUTES", "20")))

COUNT_DERIVED_SQL = text("""
    SELECT count(*) FROM routings WHERE created_by = 'bom-family-derived'
""")

# 回填只针对"还没排动"的主工单；子工单/已完工/已取消一概不动
TARGET_WO_SQL = text("""
    SELECT DISTINCT wo.factory_id, wo.product_id
    FROM work_orders wo
    WHERE wo.wo_type = 'master'
      AND wo.status NOT IN ('completed', 'cancelled')
      AND wo.routing_id IS NULL
      AND wo.product_id IS NOT NULL
    ORDER BY wo.factory_id, wo.product_id
    LIMIT :limit
""")

BIND_WO_SQL = text("""
    UPDATE work_orders
    SET routing_id = :routing_id, updated_at = NOW()
    WHERE wo_type = 'master'
      AND status NOT IN ('completed', 'cancelled')
      AND routing_id IS NULL
      AND factory_id = :fid AND product_id = :pid
""")

# 半成品级：只看已经有整机型路线、且齐套快照带层级的主工单
COMPONENT_WO_SQL = text("""
    SELECT wo.id, wo.factory_id, wo.product_id
    FROM work_orders wo
    WHERE wo.wo_type = 'master'
      AND wo.status NOT IN ('completed', 'cancelled')
      AND wo.routing_id IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM work_order_materials m
          WHERE m.work_order_id = wo.id AND m.item_type = 'make' AND m.parent_code IS NOT NULL
      )
    ORDER BY wo.created_at DESC
    LIMIT :limit
""")

COMPONENT_ROWS_SQL = text("""
    SELECT material_code, material_name, item_type, level, parent_code
    FROM work_order_materials
    WHERE work_order_id = :wo_id
""")

ROUTED_CODES_SQL = text("""
    SELECT p.product_code
    FROM products p
    JOIN routings r ON r.id = p.current_routing_id
    WHERE p.product_code = ANY(:codes)
      AND r.steps IS NOT NULL AND COALESCE(jsonb_array_length(r.steps::jsonb), 0) > 0
""")

COMPONENT_BATCH = max(1, int(os.getenv("ROUTING_BACKFILL_WOS_PER_TICK", "2")))
# 例行 BOM 自检的范围（只读，扫几颗机种；心跳一行，不写业务表）
QUALITY_MODELS_PER_TICK = max(1, int(os.getenv("BOM_QUALITY_MODELS_PER_TICK", "2")))
QUALITY_FACTORY_ID = os.getenv("BOM_QUALITY_FACTORY_ID", "FAC_MECH_001")

# 记分卡要不要落库、瓶颈待办要不要发（默认开：只写我们自己那张推演读数表）
PORTFOLIO_FLYWHEEL_APPLY = os.getenv("PORTFOLIO_FLYWHEEL_APPLY", "1").strip().lower() in {"1", "true", "yes", "on"}

# 无人排产按哪个目标占产能。词汇与 cost_model.OBJECTIVES 一致：
# labor_first / delivery_first / total_cost / balanced。目标是一个参数，不是引擎的偏好，
# 所以它必须能从部署配置上看见、能改，而不是写死在代码里。
SCHEDULE_OBJECTIVE = os.getenv("ENGINE_SCHEDULE_OBJECTIVE", "labor_first")
# 旧逻辑把整条产线套到子件上过（10-05 实测 14 条：6 道/4 道工序的子件路线）。
# 收窄一轮就能收敛：只动自己推导出来的草案路线，且只往少了改。
REPAIR_BATCH = max(0, int(os.getenv("ROUTING_BACKFILL_REPAIR_BATCH", "20")))

# 子件却拿着整条产线的路线：那些料号在齐套快照里是别人的下层，不是机种
OVERCLAIMED_SQL = text("""
    SELECT DISTINCT ON (r.id)
           r.id AS routing_id, r.product_id AS material_code,
           COALESCE(jsonb_array_length(r.steps::jsonb), 0) AS nsteps,
           wo.factory_id, wo.product_id AS model_code
    FROM routings r
    JOIN work_order_materials m ON m.material_code = r.product_id AND m.item_type = 'make'
    JOIN work_orders wo ON wo.id = m.work_order_id AND wo.wo_type = 'master'
    WHERE r.created_by = :created_by
      AND COALESCE(jsonb_array_length(r.steps::jsonb), 0) > :min_steps
      AND NOT EXISTS (
          SELECT 1 FROM work_orders w2
          WHERE w2.wo_type = 'master' AND w2.product_id = r.product_id
      )
    ORDER BY r.id, wo.created_at DESC
    LIMIT :limit
""")

NARROW_SQL = text("""
    UPDATE routings
    SET steps = CAST(:steps AS jsonb), remark = :remark, updated_at = NOW()
    WHERE id = :routing_id AND created_by = :created_by
""")


async def _subtree_corpus(rows: List[Any], root_code: str) -> str:
    """从齐套快照的 parent_code 链取某个半成品的整棵子树文本。

    半成品自己的下层就在同一份 BOM 里（用户 10-05 的口径：L3 即半成品），
    所以子件不用再传一次 BOM —— 子件行写的"烤漆/鹽浴滲氮/45#"就是工序佐证材料。
    """
    children: Dict[str, List[Any]] = {}
    for row in rows:
        parent = str(row["parent_code"] or "")
        children.setdefault(parent, []).append(row)

    texts: List[str] = []
    stack = list(children.get(root_code, []))
    seen = set()
    while stack:
        node = stack.pop()
        code = str(node["material_code"] or "")
        if code and code not in seen:
            seen.add(code)
            texts.append(str(node["material_name"] or ""))
            stack.extend(children.get(code, []))
    return " ".join(t for t in texts if t)


async def backfill_component_routes(
    db, *, limit: int = COMPONENT_BATCH, budget_left: int, apply: bool = True
) -> Dict[str, Any]:
    """给已下达到、有层级快照的自制半成品补工艺路线（同一道佐证门）。"""
    receipt: Dict[str, Any] = {
        "examined": 0, "derived": 0, "existing": 0, "not_derived": 0,
        "no_master": 0, "no_bom_text": 0, "rejected": [],
        # 佐证语料的来源分布：BOM 镜像子树（含材料/表面處理原文）才是全量结构，
        # 齐套快照只剩清洗后的品名，用它当语料会把"烤漆/鹽浴滲氮"这些证据丢掉。
        "corpus_by_source": {},
    }
    if budget_left <= 0:
        receipt["status"] = "budget_exhausted"
        return receipt

    wos = (await db.execute(COMPONENT_WO_SQL, {"limit": limit})).mappings().all()
    for wo in wos:
        fid = str(wo["factory_id"])
        rows = (await db.execute(COMPONENT_ROWS_SQL, {"wo_id": wo["id"]})).mappings().all()
        made = [r for r in rows if str(r["item_type"] or "") == "make"]
        receipt["examined"] += len(made)
        routed = {str(c) for c in (await db.execute(ROUTED_CODES_SQL, {
            "codes": [str(r["material_code"]) for r in made] or ["__none__"]
        })).scalars().all()}
        model = str(wo["product_id"] or "")
        codes = [str(r["material_code"]) for r in made]
        evidence = await subtree_evidence(db, fid, model, codes)

        for row in made:
            if receipt["derived"] >= budget_left:
                receipt["status"] = "budget_reached"
                return receipt
            code = str(row["material_code"])
            if code in routed:
                receipt["existing"] += 1
                continue
            corpus = str((evidence["evidence"] or {}).get(code) or "")
            corpus_source = "bom_mirror_subtree" if corpus.strip() else ""
            if not corpus.strip():
                # 镜像里没有这个型号的结构（本地 BOM 建的型号才会这样）才退回快照品名
                corpus = await _subtree_corpus(rows, code)
                corpus_source = "wo_snapshot_subtree" if corpus.strip() else "none"
            receipt["corpus_by_source"][corpus_source] = \
                receipt["corpus_by_source"].get(corpus_source, 0) + 1
            result = await derive_routing_for_component(
                db, fid, code, corpus, level=row["level"]
            )
            status = str(result.get("status"))
            receipt[status] = receipt.get(status, 0) + 1
            if status in ("not_derived", "no_bom_text") and len(receipt["rejected"]) < 5:
                receipt["rejected"].append({
                    "material_code": code, "status": status,
                    "reason": result.get("reason"), "coverage": result.get("coverage"),
                    "corpus_source": corpus_source,
                    "corpus_chars": len(corpus),
                })
        if apply:
            await db.commit()
        receipt["status"] = receipt.get("status", "ok")
    receipt.setdefault("status", "ok")
    return receipt



async def rederive_overclaimed_routes(db, *, limit: int = REPAIR_BATCH, apply: bool = True
                                      ) -> Dict[str, Any]:
    """把"整条产线套在子件上"的路线收窄到它自己子树佐证的工序。

    只动 `created_by='bom-family-derived'` 的草案，且只在**工序变少**时改写；
    收窄后不足 2 道工序的不改（那说明这个件该怎么工艺本来就没证据，列出来交工艺部，
    不是让引擎再套一条更假的路线）。路线 id 不动，所以工单与 APS 的引用不会断。
    """
    receipt: Dict[str, Any] = {
        "examined": 0, "narrowed": 0, "unchanged": 0,
        "needs_process_engineering": [], "samples": [],
    }
    if limit <= 0:
        receipt["status"] = "disabled"
        return receipt

    rows = (await db.execute(OVERCLAIMED_SQL, {
        "created_by": CREATED_BY, "min_steps": MIN_COMPONENT_STEPS, "limit": limit,
    })).mappings().all()
    receipt["examined"] = len(rows)
    for row in rows:
        fid = str(row["factory_id"])
        code = str(row["material_code"])
        model = str(row["model_code"])
        evidence = await subtree_evidence(db, fid, model, [code])
        corpus = str((evidence["evidence"] or {}).get(code) or "")
        if not corpus.strip():
            receipt["unchanged"] += 1
            continue
        subset = await corroborated_component_subset(db, fid, corpus)
        steps = subset.get("steps") or []
        if len(steps) < MIN_COMPONENT_STEPS or len(steps) >= int(row["nsteps"]):
            # 佐不到 2 道 = 没人知道这个件怎么做；比原路线更宽 = 不动，宁缺勿造
            if len(steps) < MIN_COMPONENT_STEPS:
                receipt["needs_process_engineering"].append({
                    "material_code": code, "steps_on_route": int(row["nsteps"]),
                    "corroborated": len(steps), "reason": subset.get("reason")
                    or "子树只佐证到不足 2 道工序",
                })
            receipt["unchanged"] += 1
            continue
        remark = (
            f"收窄自 {int(row['nsteps'])} 道工序：按它在 {model} 的 BOM 子树里只佐证到 "
            f"{subset.get('matched_steps')}/{len(steps)} 道；参考路线 {subset.get('derived_from')}；"
            + "、".join(subset.get("station_sources") or []) +
            "。标准工时未经 IE 确认，排程只能当草案。"
        )
        if apply:
            await db.execute(NARROW_SQL, {
                "routing_id": row["routing_id"], "created_by": CREATED_BY,
                "steps": json.dumps(steps, ensure_ascii=False), "remark": remark,
            })
        receipt["narrowed"] += 1
        if len(receipt["samples"]) < 5:
            receipt["samples"].append({
                "material_code": code, "before": int(row["nsteps"]),
                "after": len(steps),
                "kept": [str(st.get("name")) for st in steps],
            })
    receipt.setdefault("status", "ok")
    return receipt


async def backfill_missing_routings(db, *, apply: bool = True) -> Dict[str, Any]:
    """补一轮路线。返回可对账的凭据：看了几个、套上几个、回填了几张工单、为什么没套上。"""
    already_derived = int((await db.execute(COUNT_DERIVED_SQL)).scalar() or 0)
    receipt: Dict[str, Any] = {
        "examined": 0,
        "by_status": {},
        "derived": 0,
        "routed_products": 0,
        "routed_work_orders": 0,
        "rejected": [],
        "derived_routes_in_db": already_derived,
        "route_budget": MAX_DERIVED_ROUTES,
    }
    if already_derived >= MAX_DERIVED_ROUTES:
        # 预算用完了就停手，并把"为什么这轮没干活"写进心跳，别让人以为循环挂了
        receipt["status"] = "budget_exhausted"
        return receipt

    targets = (await db.execute(
        TARGET_WO_SQL, {"limit": BATCH_PRODUCTS}
    )).mappings().all()
    receipt["examined"] = len(targets)
    for row in targets:
        if already_derived + receipt["derived"] >= MAX_DERIVED_ROUTES:
            receipt["status"] = "budget_reached"
            break
        fid = str(row["factory_id"])
        product_code = str(row["product_id"])
        result = await derive_routing_for_product(db, fid, product_code)
        status = str(result.get("status") or "unknown")
        receipt["by_status"][status] = receipt["by_status"].get(status, 0) + 1
        if status in ("derived", "existing"):
            receipt["derived"] += status == "derived"
            receipt["routed_products"] += 1
            if apply and result.get("routing_id"):
                updated = await db.execute(BIND_WO_SQL, {
                    "routing_id": result["routing_id"], "fid": fid, "pid": product_code,
                })
                receipt["routed_work_orders"] += int(updated.rowcount or 0)
        elif len(receipt["rejected"]) < 5:
            # 拒绝要说得出原因，否则下一轮还是同样一批排不动，也没人知道差什么
            receipt["rejected"].append({
                "product_code": product_code,
                "status": status,
                "reason": result.get("reason"),
                "coverage": result.get("coverage"),
            })
    receipt.setdefault("status", "ok")
    if apply:
        await db.commit()
    else:
        await db.rollback()

    # 型号级之后再看半成品级：同一份预算里继续往下推，仍受佐证率那道门管
    budget_left = max(0, MAX_DERIVED_ROUTES - already_derived - receipt["derived"])
    components = await backfill_component_routes(
            db, budget_left=budget_left, apply=apply)
    receipt["components"] = components
    # 旧草案里"子件拿整条产线"的那些，按现在的证据收窄；id 不变，工单引用不受影响
    receipt["route_repairs"] = await rederive_overclaimed_routes(db, apply=apply)
    # 路线推出来后，把 ready 的半成品拆成子工单：这是"无人"真正能落任务的那一步
    if apply:
        await db.commit()
    orders = await expand_ready_components(db, apply=apply)
    receipt["component_orders"] = orders
    if apply:
        await db.commit()
    # 到货先记账，再刷缺口：PO 的预计到货日过了不等于货到了 —— 以前没人把在途收成库存，
    # 于是 MRP 永远算缺料、门永远不放行（实测 31 张单飘了一个半月）。
    receipt["purchase_receipts"] = await receive_due_purchase_orders(db)
    # 最后把主快照的缺口按当前台账刷一遍：下级完工入库后，父层齐套门才会自己放行
    receipt["supply_refresh"] = await refresh_snapshot_supply(db, apply=apply)
    # 刷完缺口再判能否开工：下级装配件的料齐了就 released，没齐就报卡在哪
    # 刷完缺口再判能否开工：下级装配件的料齐了就 released，没齐就报卡在哪
    receipt["child_releases"] = await release_kitted_child_orders(
        db, factory_id=None, apply=apply
    )
    # 组件单的对账（同一轮只做这三格，顺序固定：补依据 → 停掉没有依据的放行 → 收净缺口 0 的）
    receipt["kit_rebuild"] = await rebuild_missing_component_kits(db)
    receipt["covered_children"] = await retire_covered_child_orders(db)
    # 数据脏不脏也要每天自己看一次：这步只读，产出写在心跳里（不改 BOM 原始行）
    receipt["bom_quality"] = await scan_plant(
        db, QUALITY_FACTORY_ID, limit=QUALITY_MODELS_PER_TICK)
    # 预计时间的出处是否唯一、线报的日产量和工位主档的时产能是不是互相打架。
    # 这一格只报不判：谁对谁错要 IE 核定，引擎不取平均，也不许用默认工时蒙过去。
    receipt["time_basis"] = await time_basis_review(db, QUALITY_FACTORY_ID)
    # 最后一格：这版计划到底有没有单能开工。逐单就绪门按"排齐+齐套+工位可映射"放行，
    # 默认只预演（PLAN_COMMIT_APPLY），开发尺度每轮最多 PLAN_COMMIT_MAX_ORDERS 张。
    receipt["plan_commit"] = await commit_plan_ready(db, apply_enabled=PLAN_COMMIT_APPLY,
                                                     max_orders=PLAN_COMMIT_MAX_ORDERS)
    # 扩张期每轮都会新写一份方案，旧草案不会自己变少：这里按 keep-last-N 回收，
    # 只动没确认过的 draft，压着锁定工序的那几份跳过（默认预演，开关在 compose）。
    receipt["draft_prune"] = await prune_superseded_drafts(
        db, apply=DRAFT_PRUNE_APPLY, keep=DRAFT_KEEP_VERSIONS)
    # 缺料不能执行，就得有人去追：按 HR 岗位映射开催料待办（一张单最多一条未关闭）
    receipt["material_chase"] = await chase_material_shortages(
        db, QUALITY_FACTORY_ID, limit=MATERIAL_CHASE_LIMIT, apply=True)
    # 停在哪条线更贵、能不能挪过去：把线组比较发成 PMC 待办（有差额才发，一组一条）
    receipt["line_strategy"] = await advise_line_strategy(db, QUALITY_FACTORY_ID)
    # 料没齐不等于停工：算出"这张单现在还能先开几台"，发成分批待办（不自动拆单）。
    partial = await report_partial_kit_splits(db, QUALITY_FACTORY_ID)
    receipt["partial_kit"] = partial
    # 数据源台账：仿真每一维今天到底有没有真值（IE 工时 / 考勤 / 设备 / 排产 / 齐套），
    # 以及哪些数是我们自己灌的、不能当现场证据。只读，不改任何表。
    receipt["data_authority"] = await data_authority_report(db, QUALITY_FACTORY_ID)
    # 飞轮那一圈：组合推演打分 → 记分卡落库 → 瓶颈换了就开一条待办（同瓶颈不重复催）。
    receipt["portfolio_scorecard"] = await run_portfolio_cycle(
        db, QUALITY_FACTORY_ID, apply=PORTFOLIO_FLYWHEEL_APPLY)
    # 政策×天气的权衡矩阵：前沿与稳健推荐变了才写卡（工厂是取舍，不是把某个分数刷到最高）
    receipt["sim_tradeoffs"] = await record_sim_tradeoffs(
        db, QUALITY_FACTORY_ID, apply=PORTFOLIO_FLYWHEEL_APPLY)
    if isinstance(receipt.get("plan_commit"), dict):
        # 就绪门的读数旁边挂上同一份口径：压着的单里有多少其实能先开一批。
        receipt["plan_commit"]["partial_option"] = {
            "orders": partial.get("orders_with_partial_option"),
            "units_startable_now": partial.get("units_startable_now"),
            "units_still_waiting": partial.get("units_still_waiting"),
            "tasks_created": partial.get("tasks_created"),
        }
    # 最后一格是自我核对：这一轮工厂到底有没有往前走。
    # 上一轮的读数就从这条心跳自己那一行里读，所以这是"逐轮对撞"而不是每次从零开始看。
    receipt["convergence"] = await convergence_report(
        db, QUALITY_FACTORY_ID, gate=receipt.get("plan_commit"))
    receipt["dry_run"] = not apply
    return receipt


async def commit_plan_ready(db, *, factory_id: str = QUALITY_FACTORY_ID,
                            apply_enabled: bool, max_orders: int) -> Dict[str, Any]:
    """引擎替计划走完最后一格：先保证有一版"当前输入"的方案，再按门逐单下达。

    排程这一步放在门前面是有讲究的：同输入被写量刹车复用（0 行写入），输入变了才出新方案，
    于是"要不要重排"由数据决定，而不是由定时器决定。下达本身仍是限量 + 显式开关。
    """
    from api.services.aps_service import ApsService

    plan = await ApsService(db).generate_schedule(
        factory_id, optimize_for=SCHEDULE_OBJECTIVE,
        created_by="routing-backfill", change_reason="engine_tick"
    )
    # 先把机制自己放错行的放行收回来（没有领料依据的"齐套"），再判这一轮能放哪些单：
    # 顺序是有意的 —— 收回之后门就不会在同一轮里把同一批单又放一遍。
    revoked = await audit_false_releases(db, factory_id)
    gate = await commit_ready_orders(
        db, factory_id, apply=apply_enabled, actor="plan-commit-gate", max_orders=max_orders
    )
    gate["false_releases"] = {k: revoked.get(k) for k in
                              ("false_releases_found", "revoked", "tasks_reset", "dry_run")}
    gate["plan_reused"] = bool(plan.get("reused"))
    gate["plan_schedule_code"] = plan.get("schedule_code")
    gate["plan_tasks"] = plan.get("total_tasks")
    return gate


async def routing_backfill_loop() -> None:
    """引擎循环主体：自己报逐轮心跳，异常也如实记 failed 再退避。"""
    from database.db_config import db_config

    while True:
        try:
            async with db_config.session_factory() as db:
                receipt = await backfill_missing_routings(db)
            await record("routing-backfill", "tick", detail=receipt,
                         interval_seconds=BACKFILL_INTERVAL_SECONDS)
            if receipt.get("routed_work_orders"):
                logger.info("[routing-backfill] 回填 %s 张工单的工艺路线：%s",
                            receipt["routed_work_orders"], receipt["by_status"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("[routing-backfill] 本轮失败: %s", exc)
            await record("routing-backfill", "failed",
                         error=f"{type(exc).__name__}: {exc}",
                         interval_seconds=BACKFILL_INTERVAL_SECONDS)
        await asyncio.sleep(BACKFILL_INTERVAL_SECONDS)
