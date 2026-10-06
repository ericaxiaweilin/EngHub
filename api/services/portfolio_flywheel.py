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

import json
import logging
import os
from datetime import date, datetime
from typing import List
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

LAST_SQL = text("""
    SELECT portfolio_score, top_constraint, engine_date, created_at
    FROM simulation_scorecards WHERE factory_id = :fid
    ORDER BY created_at DESC LIMIT 1
""")

TRADEOFF_NOTE = (
    "工厂是取舍不是考试：记分卡存的是目标向量、帕累托前沿与跨天气的稳健推荐，"
    "不存'唯一最高分'。推荐规则是 minimax regret（最坏场景后悔最小），"
    "产量不达标的解直接淘汰（否则'干脆不做'永远最优）。")


OPEN_TASK_SQL = text("""
    SELECT id, status, payload->>'constraint' AS slot_constraint
    FROM followup_tasks
    WHERE factory_id = :fid AND status NOT IN ('done', 'cancelled')
      AND payload->>'category' = :cat
""")


def _gen_id() -> str:
    import uuid
    return str(uuid.uuid4())


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


async def record_tradeoffs(db: AsyncSession, factory_id: str, *, apply: bool = True,
                            models: Optional[List[str]] = None) -> Dict[str, Any]:
    """扫一遍政策×天气，把权衡矩阵与稳健推荐写进记分卡；推荐变了才动待办。"""
    from api.services.virtual_run import auto_tune, default_models
    # 不再用固定标定：先自调（太松/太紧会自己改批量与交期系数），调稳了才比较
    tuned = await auto_tune(db, factory_id, models or await default_models(db, factory_id, n=2),
                            rounds=4)
    verdict = {"by_scenario": {k: v for k, v in (tuned["final"]["per_scenario"] or {}).items()},
               "robust_recommendation": {"policy": tuned["final"]["robust"]},
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
                           "no_feasible": bool(res.get("no_feasible"))}
                    for name, res in (verdict.get("by_scenario") or {}).items()}
    signature = f"{robust.get('policy')}|{json.dumps(per_scenario, ensure_ascii=False, sort_keys=True)}"

    last = (await db.execute(LAST_SQL, {"fid": factory_id})).mappings().first()
    changed = (not last) or str((last or {}).get("top_constraint") or "") != signature
    receipt = {"factory_id": factory_id, "apply": apply, "changed": changed,
               "robust_recommendation": robust, "by_scenario": per_scenario,
               "calibration": [(t.get("model_code"), t.get("units"), t.get("due_in_days"),
                                t.get("calibration")) for t in (tuned.get("targets") or [])],
               "selection_rule": verdict.get("selection_rule"), "note": TRADEOFF_NOTE,
               "tuning_trajectory": [{"round": t["round"], "calibration": t["calibration"],
                                      "diagnosis": t["diagnosis"], "next_tweak": t["next_tweak"],
                                      "robust": t["robust"]} for t in tuned["trajectory"]],
               "card_written": False}
    if not changed:
        receipt["skipped_reason"] = "稳健推荐与各场景前沿都没变，不重复写卡"
        return receipt
    if not apply:
        receipt["skipped_reason"] = "apply=false，只算不写"
        return receipt

    # 先给推荐解本身算一遍代价：钱和天数值不值得，写在建议里，不让人再去问模型
    objectives: Dict[str, Any] = {}
    for res in (verdict.get("by_scenario") or {}).values():
        if isinstance(res, dict) and res.get("objectives"):
            objectives = res["objectives"]
            break
    await db.execute(INSERT_SQL, {
        "id": _gen_id(), "fid": factory_id, "eday": date.today(),
        "models": len(per_scenario), "score": float(objectives.get("on_time_rate") or 0) * 100.0,
        "weights": json.dumps({"rule": "minimax regret over weather scenarios",
                               "objectives": objectives},
                              ensure_ascii=False),
        "top": signature[:200],
        "levers": json.dumps(robust, ensure_ascii=False),
        "detail": json.dumps({"by_scenario": per_scenario, "calibration": receipt["calibration"],
                              "tuning": receipt["tuning_trajectory"],
                              "self_check": tuned["final"].get("notes") or [],
                              "note": TRADEOFF_NOTE}, ensure_ascii=False),
        "source": "virtual_run_tradeoff",
    })
    await db.commit()
    receipt["card_written"] = True

    # 推荐变了 = 一条建议待办；旧的那条要收掉（同一个问题不留两条互相矛盾的建议）
    from api.services.followup_task_service import create_task
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
        created = await create_task(
            db, factory_id, "virtual_factory",
            f"推演推荐｜{rec}（好天~暴雨都不误期，代价 ${float(objs.get('expedite_cost_usd') or 0) + float(objs.get('line_activation_cost_usd') or 0):,.0f}）"[:200],
            description=(
                f"政策×天气扫描（{len(per)} 个天气场景 × {scan['policies_tried']} 个政策）的稳健推荐：{rec}。\n"
                f"各场景推荐：" + "；".join(f"{k}→{v}" for k, v in per.items()) + "\n"
                f"代价：加急 ${float(objs.get('expedite_cost_usd') or 0):,.0f}"
                f" + 开并联线 ${float(objs.get('line_activation_cost_usd') or 0):,.0f}"
                f" + 人工 ${float(objs.get('labor_cost_usd') or 0):,.0f}；"
                f"等料空档 {float(objs.get('standby_person_days') or 0):,.0f} 人日。\n"
                f"选择规则：{verdict.get('selection_rule')}\n"
                f"（不是'分最高'：交期与产量是硬约束，其余维度取最小最大后悔，避免为刷一个维度牺牲另一维。）\n"
                f"场景标定：" + "；".join(f"{c[0]} {c[1]}台/{c[2]}天" for c in receipt["calibration"])),
            agent_key="pmc_agent", item_type="followup", source="virtual_factory",
            block_reason="推演建议，采纳与否看厂里的取舍；不自动改排产与采购",
            conversation_hint="采纳的话：把这个瓶颈件的到货目标日压到推荐值，并确认并联线/班组是否可用。",
            payload=json.dumps({"category": "simulation_recommendation", "policy": rec,
                                "per_scenario": per, "objectives": objs,
                                "robust_why": robust.get("why")}, ensure_ascii=False),
            follow_interval_minutes=24 * 60)
        if created.get("task_id"):
            await db.execute(text("""
                UPDATE followup_tasks SET next_follow_at = NOW() + INTERVAL '10 minutes'
                WHERE id = :id"""), {"id": str(created["task_id"])})
            await db.commit()
        receipt["recommendation_task"] = {"task_id": created.get("task_id"),
                                          "superseded": int(superseded or 0)}
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
