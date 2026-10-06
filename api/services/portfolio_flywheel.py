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

    # 瓶颈没换就不开新待办：同一件事每 15 分钟催一次，接收的人会直接忽略它
    open_tasks = [dict(r) for r in (await db.execute(
        OPEN_TASK_SQL, {"fid": factory_id, "cat": CATEGORY})).mappings().all()]
    same_open = next((t for t in open_tasks if str(t.get("slot_constraint") or "") == constraint), None)
    receipt["bottleneck_tasks_open"] = len(open_tasks)
    if same_open:
        receipt["task"] = {"action": "same_bottleneck_already_open", "task_id": same_open["id"]}
        return receipt
    if last is not None and str(last.get("top_constraint") or "") == constraint:
        receipt["task"] = {"action": "bottleneck_unchanged", "skip": True}
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
    receipt["task"] = {"action": "opened", "task_id": created.get("task_id"), "title": title}
    return receipt


async def run_once(db: AsyncSession, factory_id: str, *, apply: bool = True,
                   models: Optional[list] = None, attendance_factor: Optional[float] = None) -> Dict[str, Any]:
    """跑一轮推演（含四个杠杆对比）并记账。"""
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
