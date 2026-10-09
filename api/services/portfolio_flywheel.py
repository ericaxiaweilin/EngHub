"""飞轮那一圈：组合推演的分数落一张卡，瓶颈变了就开一条待办。

为什么要留历史而不只是"每次都算一遍"：分数只有在**能比较**的时候才有意义 ——
这轮 62.2、上轮 26.2，说明补进来的 IE 工时真的解开了瓶颈；只报当前值，
分不清是变好了还是换了个算法。所以：

- 每轮写一条 `simulation_scorecards`（同一天同厂同分同瓶颈 → 不重复写，避免灌行）；
- **瓶颈类别变化**才发待办（不是分数变化就发）：待办的价值在"这轮卡在哪件事"，
  分数抖一下不算新情况。同一瓶颈只留一条未关闭的待办；
- 待办里带分数走势和杠杆对比的原文，接手的人不用再去问模型算过什么。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, datetime
from typing import List, Tuple
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger(__name__)

CATEGORY = "simulation_bottleneck"
MAX_MODELS = int(os.getenv("PORTFOLIO_SIM_MODELS", "5"))
DEFAULT_UNITS = int(os.getenv("PORTFOLIO_SIM_DEFAULT_UNITS", "300"))
# 分数至少要涨/跌这么多才值得再写一张卡（同瓶颈时），防止每 15 分钟灌一行
SCORE_WRITE_THRESHOLD = float(os.getenv("PORTFOLIO_SIM_WRITE_THRESHOLD", "0.5"))

INSERT_SQL = text("""
    INSERT INTO simulation_scorecards (id, factory_id, engine_date, models_simulated, portfolio_score,
                                       weights, top_constraint, lever_deltas, detail, source, created_at)
    VALUES (:id, :fid, :eday, :models, :score, CAST(:weights AS jsonb), :top,
            CAST(:levers AS jsonb), CAST(:detail AS jsonb), :source, NOW())
""")

CAL_SQL = text("""
    UPDATE simulation_scorecards
       SET detail = jsonb_set(COALESCE(detail, '{}'::jsonb), '{calibration_by_scenario}',
                              CAST(:cal AS jsonb))
     WHERE id = (SELECT id FROM simulation_scorecards WHERE factory_id = :fid
                 ORDER BY created_at DESC LIMIT 1)
""")

LAST_SQL = text("""
    SELECT portfolio_score, top_constraint, engine_date, created_at,
           (detail->'calibration_by_scenario')::text AS calibration,
           (detail->'actions')::text AS actions
    FROM simulation_scorecards WHERE factory_id = :fid
    ORDER BY created_at DESC LIMIT 1
""")

LATEST_SQL = text("""
    SELECT portfolio_score, top_constraint, engine_date, created_at, models_simulated,
           weights, lever_deltas AS levers, detail
    FROM simulation_scorecards WHERE factory_id = :fid
    ORDER BY created_at DESC LIMIT 1
""")


def _flag_reasons(actions) -> Dict[str, int]:
    """催购动作身上的旗标按原因计数：读动作里的机器名，不重新判一遍（判据只在 virtual_run 写一次）。"""
    out: Dict[str, int] = {}
    for a in actions or []:
        if a.get("type") != "expedite_purchase":
            continue
        for k in a.get("evidence_flag_kinds") or []:
            out[k] = out.get(k, 0) + 1
    return out


def _action_coverage(scan: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """这一轮的政策×天气网格里，每个动作被考虑过几次 —— 没被考虑过的动作不可能有现场采纳记录。

    只有赢家进 actions，学习侧就永远收不到其余动作的样本（实测 17 条动作全是催购/分批那几类）。
    这份覆盖度不改任何推演结论，只是把"引擎想过但没选中"记下来，供约束层和界面区分
    "现场没做" 与 "引擎根本没提"。
    """
    from core.mes.action_constraints import policy_actions

    cov: Dict[str, Dict[str, Any]] = {}
    for sname, block in (scan.get("by_scenario") or scan.get("per_scenario") or {}).items():
        for sol in (block.get("solutions") or []):
            pol = sol.get("policy") or {}
            for a in policy_actions(pol):
                c = cov.setdefault(a, {"times_considered": 0, "policies": set(),
                                       "scenarios": set()})
                c["times_considered"] += 1
                c["policies"].add(str(sol.get("name") or ""))
                c["scenarios"].add(str(sname))
    return {k: {"times_considered": int(v["times_considered"]),
                "policies": sorted(x for x in v["policies"] if x),
                "scenarios": sorted(v["scenarios"])}
            for k, v in sorted(cov.items(), key=lambda kv: -kv[1]["times_considered"])}


def _as_dict(val: Any) -> Dict[str, Any]:
    """jsonb 列在 asyncpg 下可能是 str 也可能是 dict：两种都接，别让解析失败静默变成空读数。"""
    if isinstance(val, dict):
        return val
    try:
        loaded = json.loads(val or "{}")
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


async def latest_tradeoff_state(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """把最近一轮推演的结论、准备发的动作与落地复查原样转述出来（只读，不重跑扫描）。

    聊天侧要的是"引擎在建议什么、上次的建议做没做"，重新扫一遍既慢又会给出
    和记分卡不同的数 —— 这里只念台账里那张卡。
    """
    row = (await db.execute(LATEST_SQL, {"fid": factory_id})).mappings().first()
    if not row:
        return {"status": "no_card",
                "message": ("还没跑过政策×天气推演。引擎每 15 分钟自己跑一轮；"
                            "现在想看就 GET /api/v1/pmc/sim-tradeoffs（apply=false 只算不写）。")}
    detail = _as_dict((row or {}).get("detail"))
    levers = _as_dict((row or {}).get("levers"))
    weights = _as_dict((row or {}).get("weights"))
    per = {k: {kk: v.get(kk) for kk in ("recommended", "feasible_ratio", "frontier_size",
                                        "eliminated", "runner_up_regret_gap", "informative",
                                        "tied_with_recommended", "scenario_verdict", "calibration")}
           for k, v in (detail.get("by_scenario") or {}).items() if isinstance(v, dict)}
    return {
        "status": "ok", "as_of": str((row or {}).get("created_at")),
        "engine_date": str((row or {}).get("engine_date")),
        "models_simulated": (row or {}).get("models_simulated"),
        "robust_recommendation": levers,
        "robustness_pct": float((row or {}).get("portfolio_score") or 0),
        "score_meaning": weights.get("score_meaning"),
        "objectives_of_recommended": weights.get("objectives"),
        "actions": (detail.get("actions") or [])[:12],
        "action_total": len(detail.get("actions") or []),
        "followthrough": detail.get("followthrough"),
        "by_scenario": per,
        "calibration_by_scenario": detail.get("calibration_by_scenario"),
        "selection_rule": weights.get("rule"),
        "scenario_divergence": detail.get("scenario_divergence"),
        "promise_conclusion": detail.get("promise_conclusion"),
        "robust_pool": detail.get("robust_pool"),
        "rule": TRADEOFF_NOTE,
        "note": TRADEOFF_NOTE,
    }


TRADEOFF_NOTE = (
    "工厂是取舍不是考试：记分卡存的是目标向量、帕累托前沿与跨天气的稳健推荐，"
    "不存'唯一最高分'。推荐规则是 minimax regret（最坏场景后悔最小），"
    "产量不达标的解直接淘汰（否则'干脆不做'永远最优）。")


OPEN_REC_SIG_SQL = text("""
    SELECT id, payload->>'sig_key' AS sig
    FROM followup_tasks
    WHERE factory_id = :fid AND payload->>'category' = 'simulation_recommendation'
      AND status NOT IN ('done', 'cancelled')
    ORDER BY created_at DESC LIMIT 1
""")

OPEN_TASK_SQL = text("""
    SELECT id, status, payload->>'constraint' AS slot_constraint
    FROM followup_tasks
    WHERE factory_id = :fid AND status NOT IN ('done', 'cancelled')
      AND payload->>'category' = :cat
""")


def _gen_id() -> str:
    import uuid
    return str(uuid.uuid4())


def tradeoff_task_key(policy: Optional[str], on_time_count: int, scenario_count: int,
                      actions: List[Dict[str, Any]]) -> str:
    """待办的"变没变"只看人会据此做决定的三件事：推荐是哪条、有没有准点、点名到哪些料号。

    记分卡的签名比这个细（带前沿宽度、后悔差这些浮点读数，它们随台账动，作历史留痕没问题）；
    但那几项每天都动，拿来判待办就会每 15 分钟给人新挂一条、把上一条取消掉。
    """
    named = sorted({str(a.get("material_code") or a.get("detail") or "")
                    for a in actions if a.get("material_code") or a.get("detail")})
    claim = f"ontime:{on_time_count}-of-{scenario_count}" if scenario_count else "ontime:none"
    return f"{policy or ''}|{claim}|{','.join(x for x in named if x)}"[:200]


def tradeoff_signature(policy: Optional[str], sig_view: Dict[str, Any],
                       action_sig: List[str], follow_state: str = "ft:none") -> Tuple[str, str]:
    """记分卡的"变没变"指纹：短到能进列，又不能把有意义的变化截掉。

    之前直接 [:200] 截断，而场景计数那段本身就超 200 字 —— 后面的动作清单被切没了，
    于是"催的料号换了"这种真变化在比较里看不见，卡与待办都不会更新。
    返回 (入库用的短指纹, 可复核的完整指纹)。
    """
    full = (f"{policy}|{json.dumps(sig_view, ensure_ascii=False, sort_keys=True)}"
            f"|{','.join(action_sig)}|{follow_state}")
    short = f"{(policy or '')[:60]}|{hashlib.sha1(full.encode('utf-8')).hexdigest()[:12]}"
    return short[:200], full


def should_write_card(last: Optional[Dict[str, Any]], score: float, constraint: str) -> bool:
    """同一天同瓶颈且分数没实质变化 → 不写新卡。"""
    if not last:
        return True
    same_day = str(last.get("engine_date")) == datetime.utcnow().date().isoformat()
    same_constraint = str(last.get("top_constraint") or "") == constraint
    drift = abs(float(last.get("portfolio_score") or 0) - float(score))
    if same_day and same_constraint and drift < SCORE_WRITE_THRESHOLD:
        return False
    return True


def _top_constraint(sim: Dict[str, Any]) -> str:
    levers = sim.get("levers") or []
    return str(levers[0]["constraint"]) if levers else "无明显瓶颈"


def _lever_deltas(trials: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for key, value in trials.items():
        if isinstance(value, dict) and "delta" in value:
            out[key] = value["delta"]
    return out


async def record_cycle(db: AsyncSession, sim: Dict[str, Any], *, factory_id: str,
                       trials: Optional[Dict[str, Any]] = None, apply: bool = True) -> Dict[str, Any]:
    """写记分卡 + 瓶颈变化时发一条待办。apply=False 只回报"会写什么"。"""
    score = float(sim.get("portfolio_score") or 0)
    constraint = _top_constraint(sim)
    last = (await db.execute(LAST_SQL, {"fid": factory_id})).mappings().first()
    write = should_write_card(dict(last) if last else None, score, constraint)
    receipt: Dict[str, Any] = {
        "factory_id": factory_id, "portfolio_score": score, "top_constraint": constraint,
        "card_written": False, "previous": dict(last) if last else None,
        "skipped_reason": None, "task": None,
    }
    if not write:
        receipt["skipped_reason"] = "同一天同瓶颈且分数没实质变化，不重复写卡"
    elif apply:
        await db.execute(INSERT_SQL, {
            "id": _gen_id(), "fid": factory_id, "eday": date.today(),
            "models": int(sim.get("models_simulated") or 0), "score": score,
            "weights": json.dumps(sim.get("weights") or {}, ensure_ascii=False),
            "top": constraint,
            "levers": json.dumps(_lever_deltas(trials or {}), ensure_ascii=False),
            "detail": json.dumps({"shift_weekdays": sim.get("shift_weekdays"),
                                  "attendance_factor": sim.get("attendance_factor"),
                                  "equipment_available_rate": sim.get("equipment_available_rate"),
                                  "hr_active_people": sim.get("hr_active_people"),
                                  "orders": sim.get("orders"), "levers": sim.get("levers"),
                                  "caveat": sim.get("caveat")}, ensure_ascii=False),
            "source": "portfolio_sim",
        })
        await db.commit()
        receipt["card_written"] = True
    else:
        receipt["skipped_reason"] = "apply=false，只算不写"

    # 判据是"这个瓶颈当前有没有未关闭的待办"，不是"瓶颈有没有换"：
    # 只看变化会留一个洞 —— 待办被人关掉之后，同一个瓶颈再出现就再也发不出来了。
    open_tasks = [dict(r) for r in (await db.execute(
        OPEN_TASK_SQL, {"fid": factory_id, "cat": CATEGORY})).mappings().all()]
    same_open = next((t for t in open_tasks if str(t.get("slot_constraint") or "") == constraint), None)
    receipt["bottleneck_tasks_open"] = len(open_tasks)
    if same_open:
        receipt["task"] = {"action": "same_bottleneck_already_open", "task_id": same_open["id"]}
        return receipt
    orders = sim.get("orders") or []
    stuck = [o for o in orders if str(o.get("binding_constraint") or "") == constraint]
    levers = _lever_deltas(trials or {})
    title = f"仿真瓶颈｜{constraint}（{len(stuck)} 个机种，组合分 {score:g}）"[:200]
    description = (
        f"组合推演 {len(orders)} 个机种：{score:g} 分。当前最卡的瓶颈是「{constraint}」，"
        f"涉及机种 {'、'.join(str(o['model_code']) for o in stuck[:8]) or '无'}。\n"
        f"杠杆对比（涨分为正）：{json.dumps(levers, ensure_ascii=False)}\n"
        f"上一张卡：分数 {float((last or {}).get('portfolio_score') or 0):g}、"
        f"瓶颈 {(last or {}).get('top_constraint') or '（首次）'}。\n"
        + "；".join(f"{o['model_code']}：{(o.get('estimated_finish') or '算不出完工日')}"
                    f"（依据 {o.get('time_basis')}）" for o in orders[:5])
    )
    if not apply:
        receipt["task"] = {"action": "would_open", "title": title}
        return receipt

    from api.services.followup_task_service import create_task

    created = await create_task(
        db, factory_id, "virtual_factory", title, description=description,
        agent_key="pmc_agent", item_type="followup",
        block_reason=constraint, source="virtual_factory",
        conversation_hint="这是推演瓶颈，不是现场事故：先确认要补的数据或要调的资源，再决定动不动排产。",
        payload=json.dumps({"category": CATEGORY, "constraint": constraint,
                            "portfolio_score": score, "models": [o.get("model_code") for o in stuck],
                            "lever_deltas": levers}, ensure_ascii=False),
        follow_interval_minutes=24 * 60,
    )
    # 收件箱按"下次跟进"排序且只渲染前 10 行：按 24 小时挂会沉到看不见的位置（升级单踩过同一个坑）
    if created.get("task_id"):
        await db.execute(text("""
            UPDATE followup_tasks SET next_follow_at = NOW() + INTERVAL '10 minutes'
            WHERE id = :id
        """), {"id": str(created["task_id"])})
        await db.commit()
    receipt["task"] = {"action": "opened", "task_id": created.get("task_id"), "title": title}
    return receipt


def robust_objectives(scan: Dict[str, Any], policy: str) -> Dict[str, Any]:
    """代价向量必须取"被推荐的那一条政策"的目标值，取最紧的那个天气档。

    以前这里取的是「第一个场景的 recommended_objectives」，而各场景的推荐解可以不是同一条政策 ——
    10-07 实测：稳健推荐是"提前期 15→7 天"，正文里的加急费却读了另一条不花钱的政策，写成 $0，
    而那条政策实测要 $16,560。价签贴错商品，比不贴更坏。
    """
    best: Dict[str, Any] = {}
    best_late = -10 ** 9
    for block in (scan.get("by_scenario") or {}).values():
        for sol in (block.get("solutions") or []):
            if str(sol.get("name")) != str(policy):
                continue
            objs = sol.get("objectives") or {}
            late = int(objs.get("days_late_worst") or 0)
            if late > best_late:
                best, best_late = objs, late
    return best


def late_delta_table(scan: Dict[str, Any], recommended: Optional[str],
                     base: str = "现况（分批开工）") -> Dict[str, Any]:
    """逐台算清"这个政策花多少钱、买到几天、还剩几天不准"。

    取每台在**各场景里最紧的那一档**（按好天的数下单、暴雨天就失约），所以数字比
    记分卡上的 days_late_worst 更保守，也更接近计划员真正要答的那道题。
    这一步存在的原因：推荐文案以前只写"代价 $12,420、延误最小"，
    读起来像加急解决了交期 —— 实测加急到 10 天只把最坏那台从 35 天买到 34 天。
    """
    worst: Dict[str, Dict[str, int]] = {}
    for block in (scan.get("by_scenario") or {}).values():
        for sol in (block.get("solutions") or []):
            name = str(sol.get("name") or "")
            which = "recommended" if name == str(recommended) else ("base" if name == base else None)
            if not which:
                continue
            for d in (sol.get("detail") or []):
                m = str(d.get("model_code"))
                day = int(d.get("days_late") or 0)
                slot = worst.setdefault(m, {"base": -10**6, "recommended": -10**6})
                slot[which] = max(slot[which], day)
    rows, bought, still_late = [], 0, 0
    for m, v in sorted(worst.items()):
        b, r = max(v["base"], 0), max(v["recommended"], 0)
        rows.append({"model_code": m, "days_late_base": b, "days_late_recommended": r,
                     "days_bought": max(0, b - r)})
        bought += max(0, b - r)
        still_late = max(still_late, r)
    return {"per_model": rows, "days_bought_total": bought,
            "worst_still_late_days": still_late,
            "models_not_on_time": sum(1 for x in rows if x["days_late_recommended"] > 0),
            "models_compared": len(rows)}


async def record_tradeoffs(db: AsyncSession, factory_id: str, *, apply: bool = True,
                            models: Optional[List[str]] = None) -> Dict[str, Any]:
    """扫一遍政策×天气，把权衡矩阵与稳健推荐写进记分卡；推荐变了才动待办。"""
    from api.services.virtual_run import auto_tune, default_models
    # 不再用固定标定：先自调（太松/太紧会自己改批量与交期系数），调稳了才比较。
    # 标定从上一张记分卡热启动：15 分钟一轮，每轮从零重摸一遍既白算也收不敛。
    prev = (await db.execute(LAST_SQL, {"fid": factory_id})).mappings().first()
    # 卡里没存过这项时 jsonb->text 是 "null"，json.loads 会给出 None：
    # 静默当"没有热启动"就会让每轮都从零重摸标定（我踩过一次，症状是 warm_started 恒 false）
    seed = _as_dict((prev or {}).get("calibration"))
    tuned = await auto_tune(db, factory_id, models or await default_models(db, factory_id, n=5),
                            rounds=4, calibration=seed)
    verdict = {"by_scenario": {k: v for k, v in (tuned["final"]["per_scenario"] or {}).items()},
               "robust_recommendation": {"policy": tuned["final"].get("robust"),
                                         "why": tuned["final"].get("robust_why"),
                                         "tied_with": tuned["final"].get("robust_tied_with") or []},
               "scenario_divergence": tuned["final"].get("scenario_divergence") or {},
               "conclusion": tuned.get("conclusion"),
               "all_scenarios_beyond_promise": bool(tuned.get("all_scenarios_beyond_promise")),
               "nothing_on_time_at_promise": bool(tuned.get("nothing_on_time_at_promise")),
               "promise_margin": tuned["final"].get("promise_margin"),
               "diagnostic_only_scenarios": tuned["final"].get("diagnostic_only_scenarios") or [],
               "robust_pool": tuned["final"].get("robust_pool") or [],
               "selection_rule": tuned["rule"]}
    scan = {"policies_tried": int(tuned["final"].get("policies_tried") or 0)}
    robust = verdict.get("robust_recommendation") or {}
    def _rec_name(v):
        if isinstance(v, str):
            return v
        return (v or {}).get("name") if isinstance(v, dict) else None
    def _count(v):
        # auto_tune 给的是计数，evaluate_by_scenario 给的是列表 —— 两种都要能吃
        return len(v) if isinstance(v, (list, tuple)) else int(v or 0)
    per_scenario = {name: {"recommended": _rec_name(res.get("recommended")),
                           "frontier_size": _count(res.get("frontier") if "frontier" in res
                                                    else res.get("feasible")),
                           "eliminated": _count(res.get("eliminated")),
                           "no_feasible": bool(res.get("no_feasible")),
                           # 区分度读数：标定按场景各调各的，这几列说明"这一轮比出了什么"
                           "feasible_ratio": res.get("feasible_ratio"),
                           "runner_up_regret_gap": res.get("runner_up_regret_gap"),
                           "live_objectives": res.get("live_objectives"),
                           "informative": res.get("informative"),
                           "calibration": res.get("calibration"),
                           "tied_with_recommended": res.get("tied_with_recommended"),
                           "recommended_objectives": res.get("recommended_objectives"),
                           "scenario_verdict": res.get("verdict")}
                    for name, res in (verdict.get("by_scenario") or {}).items()}
    # 签名只取"推荐变了没、各场景比出了什么"，不带 finish_date/钱数这类每天都动的量：
    # 否则每轮都算"变了"，写卡和写待办的量平白翻几倍。
    sig_view = {name: {k: r.get(k) for k in ("recommended", "frontier_size", "eliminated",
                                             "no_feasible", "feasible_ratio",
                                             "runner_up_regret_gap")}
                for name, r in per_scenario.items()}
    # 推荐不是一个政策名，是一串能执行的动作：催哪个料、哪天到、先开哪一批、开哪条线。
    # 在"要不要写卡"之前就算好：apply=false 也要看得见引擎准备发什么动作。
    from api.services.virtual_run import recommendation_actions
    actions = recommendation_actions(tuned.get("final_scan") or {}, tuned.get("final_verdict") or {})
    # 杠杆经济账：每个输入动一档值几天/多少钱，随推荐一起出去（<1 秒，同一条推演路径）
    from api.services.sim_sensitivity import lever_headline
    levers = await lever_headline(db, factory_id, [t["model_code"] for t in (tuned.get("targets") or [])])
    # 动作清单里"催哪个料"变了才算推荐变了（不带日期与数量：那些每天都动）
    # 身份取"料号/缺口描述"，没有料号的（分批、开线）用机种当身份 ——
    # 否则两台单的分批建议在签名里是同一个元素，动作清单少了一半也看不出来
    action_sig = sorted({f"{a.get('type')}:"
                         f"{a.get('material_code') or a.get('detail') or a.get('model_code') or ','.join(a.get('models') or [])}"
                         for a in actions})
    # 上一轮建议的动作做没做 —— 引擎要能发现自己一直对空气提建议
    from api.services.virtual_run import recommendation_followthrough
    prev_actions: List[Dict[str, Any]] = []
    try:
        prev_actions = json.loads((prev or {}).get("actions") or "[]")
    except (TypeError, ValueError):
        prev_actions = []
    followthrough = (await recommendation_followthrough(
        db, factory_id, prev_actions, since=(prev or {}).get("created_at"))
        if prev_actions else None)
    # 落地状态分三档进签名（没落地/部分/全落地）：有人把提前期压下来就该重算交期换建议；
    # 不逐条进签名，否则每 15 分钟都被判成"变了"而重写卡与待办
    ft_state = (f"ft:{len(followthrough.get('adopted') or [])}-of-{followthrough.get('checked')}"
                if followthrough else "ft:no-named-part")
    # 有没有越过承诺口径也进签名：从"做不到"翻成"放宽后才可行"是结论变了，不是小变化
    promise_state = ("beyond-promise" if verdict.get("all_scenarios_beyond_promise") else "within-promise")
    # "有没有准点解"必须进签名：从"都不误期"翻成"承诺交期下做不到"是结论变了，
    # 待办标题里那句声明跟着变，否则界面上会一直挂着过期的承诺
    on_time_state = ("ontime:{}-of-{}".format(
        sum(1 for r in per_scenario.values() if not r.get("no_feasible")), len(per_scenario)))
    full_signature = tradeoff_signature(robust.get("policy"), sig_view, action_sig,
                                        f"{ft_state}|{promise_state}|{on_time_state}")
    receipt_signature = full_signature[0]
    signature = receipt_signature
    last = prev      # 同一张上一轮记分卡，热启动标定与变更比较都读它，不查第二遍
    changed = (not last) or str((last or {}).get("top_constraint") or "") != signature
    coverage = _action_coverage(tuned.get("final_scan") or {})
    receipt = {"factory_id": factory_id, "apply": apply, "changed": changed,
               "robust_recommendation": robust, "by_scenario": per_scenario,
               "actions": actions, "action_count": len(actions),
               "action_coverage": coverage,
               "lever_economics": levers.get("ranked") or [],
               "mapping_accuracy": levers.get("overall_accuracy"),
               "followthrough": followthrough or {"checked": 0,
                                                  "note": "上一张卡没有点名到料号的动作，无复查对象"},
               "promise_conclusion": verdict.get("conclusion"),
               "all_scenarios_beyond_promise": verdict.get("all_scenarios_beyond_promise"),
               "scenario_divergence": verdict.get("scenario_divergence"),
               "calibration": [(t.get("model_code"), t.get("units"), t.get("due_in_days"),
                                t.get("calibration")) for t in (tuned.get("targets") or [])],
               "selection_rule": verdict.get("selection_rule"), "note": TRADEOFF_NOTE,
               "warm_started": bool(tuned.get("warm_started")),
               "seed_from_last_card": bool(seed),
               "tuning_rounds_used": tuned.get("rounds"),
               "tuning_trajectory": [{"round": t.get("round"), "calibration": t.get("calibration"),
                                      "diagnosis": t.get("diagnosis"),
                                      "next_tweak": t.get("next_tweak"),
                                      "tweaks": t.get("tweaks") or [],
                                      "robust": t.get("robust")} for t in tuned["trajectory"]],
               "calibration_by_scenario": tuned.get("calibration_by_scenario") or {},
               "card_written": False}
    if not changed:
        # 标定得被记住，否则每 15 分钟都从 1.15 重摸一遍暴雨该多紧。
        # 不为此写整张卡：只在标定和上一张卡里存的不一样时补一个 jsonb 字段，收敛后这条写也没有。
        if apply and seed != (tuned.get("calibration_by_scenario") or {}):
            await db.execute(CAL_SQL, {"fid": factory_id,
                                       "cal": json.dumps(tuned.get("calibration_by_scenario") or {},
                                                         ensure_ascii=False)})
            await db.commit()
            receipt["calibration_persisted"] = True
        receipt["skipped_reason"] = "稳健推荐与各场景前沿都没变，不重复写卡"
        return receipt
    if not apply:
        receipt["skipped_reason"] = "apply=false，只算不写"
        return receipt

    # 先给推荐解本身算一遍代价：钱和天数值不值得，写在建议里，不让人再去问模型
    # 卡的 objectives 也走同一个口径：被推荐那条政策的代价，不是"第一个场景恰好推荐的解"
    objectives: Dict[str, Any] = robust_objectives(tuned.get("final_scan") or {},
                                                   str(robust.get("policy") or ""))
    if not objectives:
        for res in (verdict.get("by_scenario") or {}).values():
            if isinstance(res, dict) and res.get("recommended_objectives"):
                objectives = res["recommended_objectives"]
                break
    # 记分卡的"分数"不是总分排名，是稳健度：推荐政策在多少个天气场景下真的准点（0~100）。
    # 以前这里取 on_time_rate，但 auto_tune 不再回传 objectives，于是张张卡都是 0 分。
    on_time_scen = sum(1 for r in per_scenario.values()
                       if int(((r.get("recommended_objectives") or {}).get("days_late_worst")) or 0) == 0
                       and not r.get("no_feasible"))
    robustness_pct = round(100.0 * on_time_scen / max(1, len(per_scenario)), 1)
    await db.execute(INSERT_SQL, {
        "id": _gen_id(), "fid": factory_id, "eday": date.today(),
        # models 列存的是"这轮推演了几台机种"，不是天气场景数（原先误填 len(per_scenario)=3）
        "models": len(tuned.get("targets") or []), "score": robustness_pct,
        "weights": json.dumps({"rule": "minimax regret over weather scenarios",
                               "score_meaning": "稳健度：推荐政策在多少个天气场景下真正准点（不是加权总分）",
                               "objectives": objectives},
                              ensure_ascii=False),
        "top": signature,
        "levers": json.dumps(robust, ensure_ascii=False),
        "detail": json.dumps({"actions": actions[:20],
                              "action_coverage": _action_coverage(tuned.get("final_scan") or {}),
                              "late_delta": late_delta_table(tuned.get("final_scan") or {},
                                                             str(robust.get("policy") or "")),
                              "actions_on_unverified_input": sum(
                                  1 for a in actions
                                  if a.get("type") == "expedite_purchase" and a.get("evidence_flags")),
                              # 同一条判线结论要能说出"谁能把它清掉"：三种原因分开数（一条动作可占多项）
                              "action_flag_reasons": _flag_reasons(actions),
                              "actions_total_expedite": sum(
                                  1 for a in actions if a.get("type") == "expedite_purchase"),
                              "lever_economics": (levers.get("ranked") or [])[:8],
                              "mapping_accuracy": levers.get("overall_accuracy"),
                              "by_scenario": per_scenario,
                              "calibration": receipt["calibration"],
                              "calibration_by_scenario": tuned.get("calibration_by_scenario") or {},
                              "full_signature": full_signature[1],
                              "followthrough": followthrough,
                              "scenario_divergence": verdict.get("scenario_divergence"),
                              "promise_conclusion": verdict.get("conclusion"),
                              "robust_pool": verdict.get("robust_pool"),
                              "tuning": receipt["tuning_trajectory"],
                              "self_check": tuned["final"].get("notes") or [],
                              "note": TRADEOFF_NOTE}, ensure_ascii=False),
        "source": "virtual_run_tradeoff",
    })
    await db.commit()
    receipt["card_written"] = True

    # 推荐变了 = 一条建议待办；旧的那条要收掉（同一个问题不留两条互相矛盾的建议）。
    # 判"变了"用人看得懂的三件事，不看浮点读数，否则每 15 分钟新挂一条又取消上一条。
    from api.services.followup_task_service import create_task
    n_on_time_pre = sum(1 for r in (verdict.get("by_scenario") or {}).values()
                        if not (r or {}).get("no_feasible"))
    n_scen_pre = max(1, len(per_scenario))
    task_key = tradeoff_task_key(robust.get("policy"), n_on_time_pre, n_scen_pre, actions)
    held = (await db.execute(OPEN_REC_SIG_SQL, {"fid": factory_id})).mappings().first()
    if held and str((held or {}).get("sig") or "") == task_key:
        receipt["recommendation_task"] = {"action": "unchanged", "task_id": (held or {}).get("id"),
                                          "task_key": task_key}
        return receipt
    superseded = (await db.execute(text("""
        UPDATE followup_tasks SET status = 'cancelled', updated_at = NOW(),
               block_reason = COALESCE(block_reason, '') || ' ｜ 已被更新的推演推荐取代'
        WHERE factory_id = :fid AND status NOT IN ('done', 'cancelled')
          AND payload->>'category' = 'simulation_recommendation'
    """), {"fid": factory_id})).rowcount
    rec = robust.get("policy")
    if rec:
        def _rec(v):
            if isinstance(v, str):
                return v
            return (v or {}).get("name") if isinstance(v, dict) else None
        per = {n: _rec((r or {}).get("recommended"))
               for n, r in (verdict.get("by_scenario") or {}).items()}
        objs = objectives
        # 标题里那句"准不准点"必须按数据说：降级比较时一个准点解都没有，
        # 还写着"好天~暴雨都不误期"就是引擎在替人编承诺
        claim = (f"{n_on_time_pre}/{n_scen_pre} 个天气场景有准点解" if n_on_time_pre
                 else "承诺交期下没有准点解，按延误最小排")
        ft = followthrough or {}
        promise_line = (("口径提醒：" + str(verdict.get("conclusion")) + "\n")
                        if verdict.get("conclusion") else "")
        ft_line = (f"上一轮建议复查：{ft.get('checked', 0)} 条里 {len(ft.get('adopted') or [])} 条已落地、"
                   f"{len(ft.get('not_acted') or [])} 条无变化（{ft.get('verdict')}）"
                   if ft.get("checked") else "")
        lever_lines = [f"· {r['lever']}：{r['reads_as']}" for r in (levers.get("ranked") or [])[:4]]
        act_lines = []
        try:
            from core.mes.data_evidence import attendance_evidence

            att = await attendance_evidence(db, factory_id)
        except Exception:  # noqa: BLE001  打卡普查读不动时这条动作线照写，只是没有现场对照
            att = {}
        for a in actions[:8]:
            t = a.get("type")
            if t == "expedite_purchase":
                flags = "；先核：" + "、".join(a.get("evidence_flags") or []) if a.get("evidence_flags") else ""
                act_lines.append(f"· 催购 {a['material_code']} {float(a['qty_short']):g} 件"
                                 f"（{a.get('supplier')}）：提前期 {a['current_lead_days']}→"
                                 f"{a['target_lead_days']} 天，{a['order_by_date']} 前下单、"
                                 f"{a['required_arrival_date']} 前要到{flags}")
            elif t == "supplier_master_missing":
                act_lines.append(f"· 补主数据 {a['material_code']}：没有供应商，催购没有对象"
                                 f"（卡的是数据，不是产能）")
            elif t == "start_first_batch":
                act_lines.append(f"· {a['model_code']} 先开 {float(a['units']):g} 台"
                                 f"（{a['start_date']}），不等齐套")
            elif t == "schedule_second_batch_after_arrival":
                act_lines.append(f"· {a['model_code']} 第二批 {float(a['units']):g} 台"
                                 f"排在 {a['not_before']} 到货之后")
            elif t == "activate_parallel_line":
                act_lines.append(f"· {a['model_code']} 开并联线 {a.get('line')}"
                                 f"（{a.get('capacity_basis')}，人手无技能矩阵佐证）")
            elif t == "extra_crew":
                share = float(a.get("capacity_share") or 0)
                obs = ""
                if att.get("available"):
                    ot = att.get("overtime") or {}
                    ds = att.get("double_shift") or {}
                    win = (att.get("window") or {}).get("to_day")
                    obs = (f"；现场实测（截至 {win}）：加班 {ot.get('observed_person_days')} 人次"
                           f"/额外最长 {ot.get('max_observed_extra_hours')}h，两班倒 "
                           f"{ds.get('observed_person_days')} 人次")
                act_lines.append(f"· {a['model_code']} 加产能 {share:.0%}"
                                 f" —— 落地要选一种：加人/双班 还是 加班{obs}")
            elif t in ("master_data_gap", "model_data_gap"):
                act_lines.append(f"· {'机种推演不了' if t == 'model_data_gap' else '主数据缺口'}："
                                 f"{a.get('detail')}")
        delta = late_delta_table(tuned.get("final_scan") or {}, str(rec))
        rec_objs = robust_objectives(tuned.get("final_scan") or {}, str(rec)) or objs
        money = float(rec_objs.get("expedite_cost_usd") or 0) \
            + float(rec_objs.get("line_activation_cost_usd") or 0)
        per_model_txt = "、".join(
            f"{x['model_code']} {x['days_late_base']}→{x['days_late_recommended']} 天"
            for x in (delta.get("per_model") or [])[:8])
        honest_line = (
            f"逐台账（各台取最紧的那个天气档）：{per_model_txt or '没有可比台'}。\n"
            f"这单政策一共买到 {delta.get('days_bought_total')} 天，"
            f"最坏那台仍延 {delta.get('worst_still_late_days')} 天"
            + (f"，${money:,.0f} 买的是 {delta.get('days_bought_total')} 天里的一部分 —— "
               "**加急不解决交期**，要自洽得改承诺口径或补产能路径（#72）。"
               if delta.get("worst_still_late_days") else "（已能准点）。")
            + "\n")
        created = await create_task(
            db, factory_id, "virtual_factory",
            f"推演推荐｜{rec}（{claim}，代价 ${money:,.0f}）"[:200],   # 价钱与正文同一口径：被推荐那条政策自己的代价
            description=(
                f"政策×天气扫描（{len(per)} 个天气场景 × {scan['policies_tried']} 个政策）的稳健推荐：{rec}。\n"
                f"各场景推荐：" + "；".join(f"{k}→{v}" for k, v in per.items()) + "\n"
                + honest_line
                + f"代价：加急 ${float(objs.get('expedite_cost_usd') or 0):,.0f}"
                f" + 开并联线 ${float(objs.get('line_activation_cost_usd') or 0):,.0f}"
                f" + 人工 ${float(objs.get('labor_cost_usd') or 0):,.0f}；"
                f"等料空档 {float(objs.get('standby_person_days') or 0):,.0f} 人日。\n"
                + (promise_line or "")
                + (f"\n{ft_line}\n" if ft_line else "")
                + f"选择规则：{verdict.get('selection_rule')}\n"
                f"（不是'分最高'：交期与产量是硬约束，其余维度取最小最大后悔，避免为刷一个维度牺牲另一维。）\n"
                f"场景标定：" + "；".join(f"{c[0]} {c[1]}台/{c[2]}天" for c in receipt["calibration"])
                + ("\n动作（都在沙箱里，不写 MES/WMS，也不自动开采购单）：\n"
                   + "\n".join(act_lines) if act_lines else "")
                + ("\n杠杆经济账（每动一档实测值多少）：\n" + "\n".join(lever_lines)
                   if lever_lines else "")),
            agent_key="pmc_agent", item_type="followup", source="virtual_factory",
            block_reason="推演建议，采纳与否看厂里的取舍；不自动改排产与采购",
            conversation_hint="采纳的话：把这个瓶颈件的到货目标日压到推荐值，并确认并联线/班组是否可用。",
            payload=json.dumps({"category": "simulation_recommendation", "policy": rec,
                                "per_scenario": per, "objectives": objs,
                                "robust_why": robust.get("why"),
                                "robust_tied_with": robust.get("tied_with") or [],
                                "scenario_divergence": verdict.get("scenario_divergence"),
                                "actions": actions[:20],
                                "sig_key": task_key}, ensure_ascii=False),
            follow_interval_minutes=24 * 60)
        if created.get("task_id"):
            await db.execute(text("""
                UPDATE followup_tasks SET next_follow_at = NOW() + INTERVAL '10 minutes'
                WHERE id = :id"""), {"id": str(created["task_id"])})
            await db.commit()
        receipt["recommendation_task"] = {"task_id": created.get("task_id"),
                                          "superseded": int(superseded or 0)}
    # 推荐一旦落进收件箱，就顺手把它记进决策台账：状态（场景/政策/机种）、被执行的动作、
    # 以及后来工单的量与达成率。没这一步"成功率"永远算不出来，而人不该每次手动触发记账。
    # 同一条推荐重复跑只是 upsert，不会越记越多。
    try:
        from core.mes.factory_rules import backfill_decision_ledger

        led = await backfill_decision_ledger(db, factory_id, limit=60, apply=apply)
        receipt["decision_ledger"] = {
            "records": led["records"], "written": led["written"],
            "outcome_quality": led["outcome_quality_counts"],
            "minable_samples": led["minable_samples"],
        }
    except Exception as exc:  # noqa: BLE001  记账失败不能把这一轮的推荐带崩，但要写进读数
        receipt["decision_ledger"] = {"error": f"{type(exc).__name__}: {exc}"[:200],
                                      "note": "台账本轮没记上，推荐本身不受影响"}
    return receipt


async def run_once(db: AsyncSession, factory_id: str, *, apply: bool = True,
                   models: Optional[list] = None, attendance_factor: Optional[float] = None,
                   with_tradeoff: bool = True) -> Dict[str, Any]:
    """跑一轮推演（政策×天气的权衡扫描 + 记分卡落库）。"""
    from api.services.attendance_model import attendance_factor as attend_of
    from api.services.portfolio_sim import simulate

    attend = attendance_factor
    if attend is None:
        attend = float((await attend_of(db, factory_id)).get("factor") or 1.0)

    base = await simulate(db, factory_id, models=models, n=MAX_MODELS,
                          units_default=DEFAULT_UNITS, attendance_factor=attend)
    trials: Dict[str, Any] = {}
    ie = float(os.getenv("PORTFOLIO_SIM_IE_HOURS_PROBE", "0.037"))
    if ie > 0:
        trials["ie_hours"] = await simulate(db, factory_id, models=models, n=MAX_MODELS,
                                            units_default=DEFAULT_UNITS, attendance_factor=attend,
                                            ie_hours_per_unit=ie)
    trials["extra_line"] = await simulate(db, factory_id, models=models, n=MAX_MODELS,
                                          units_default=DEFAULT_UNITS, attendance_factor=attend,
                                          extra_line=True)
    trials["full_attendance"] = await simulate(db, factory_id, models=models, n=MAX_MODELS,
                                               units_default=DEFAULT_UNITS, attendance_factor=1.0)
    deltas = {k: round(float(v.get("portfolio_score") or 0) - base["portfolio_score"], 1)
              for k, v in trials.items()}
    summary = {"base_score": base["portfolio_score"], "lever_deltas": deltas}
    card = await record_cycle(db, base, factory_id=factory_id, trials=deltas, apply=apply)
    card["levers"] = summary
    return card
