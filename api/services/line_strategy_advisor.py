"""线组策略建议：把"停哪条线更贵、能不能挪过去"算成 PMC 能拍板的一条待办。

跟 `material_followup`（缺料催办）的分工：催办说的是「这条线在等料，去追」；
这里说的是「就算料不到，还有没有别条线能做、能救回多少台、值多少钱」。
判据是同一批事实（线画像 + 齐套表），决策不同，所以各开各的待办，互不替代。

只用库里有的东西：
- `line_profiles`：用户口述的节拍、班组人数、合并产能、单向兼容（带 source 与更正历史）；
- 在制需求与缺口：`work_orders` + `work_order_materials` 聚合，与就绪门同一口径，不另算一套；
- 单价来自 `cost_model` 的内置标定，钱数一律带 basis，不当财务数用。

写动作只有一个：`followup_task_service.create_task`（通知、日志、状态机都在那儿）。
判重按 payload 里的线组，一轮最多一条未关闭建议；不自动改排产、不自动挪单。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.scenario_sim import LINES_SQL, simulate_lines

ADVISOR_LIMIT_GROUPS = max(1, int(os.getenv("LINE_ADVISOR_MAX_GROUPS", "4")))
MIN_SAVING_PERSON_DAYS = float(os.getenv("LINE_ADVISOR_MIN_PERSON_DAYS", "50"))

# 每个机种还要做多少台、最早交期、物料现在能覆盖多少、本应归属哪条线。
# home_line 由线画像反查，且**默认机型匹配优先于"能做"**：bike 线在 can_make 里也写着跑步机，
# 按 line_code 排序会把跑步机单判给 bike 线（第一版就是这么错的），
# 而"归属线"必须是厂里正常做它的那条线，兼容线只是缺料时的退路。
DEMAND_SQL = text("""
    WITH ord AS (                        -- 工单量：只按订单聚合，绝不与物料行同 JOIN
        SELECT wo.product_id, wo.factory_id,
               SUM(GREATEST(wo.planned_qty - COALESCE(wo.completed_qty, 0), 0)) AS remaining,
               MIN(wo.planned_due) AS first_due
        FROM work_orders wo
        WHERE wo.factory_id = :fid
          AND wo.wo_type IN ('master', 'component')
          AND wo.status IN ('pending', 'released', 'in_progress')
        GROUP BY wo.product_id, wo.factory_id
    ),
    kit AS (                             -- 物料覆盖：先按单算，再按机种加总
        SELECT m.work_order_id,
               SUM(COALESCE(m.required_qty, 0)) AS required,
               SUM(LEAST(COALESCE(m.available_qty, 0), COALESCE(m.required_qty, 0))) AS covered
        FROM work_order_materials m
        GROUP BY m.work_order_id
    ),
    summed AS (
        SELECT o.product_id, o.factory_id, o.remaining, o.first_due,
               COALESCE(SUM(k.required), 0) AS required,
               COALESCE(SUM(k.covered), 0) AS covered
        FROM ord o
        JOIN work_orders w ON w.product_id = o.product_id AND w.factory_id = o.factory_id
        LEFT JOIN kit k ON k.work_order_id = w.id
        GROUP BY o.product_id, o.factory_id, o.remaining, o.first_due
    )
    SELECT s.product_id, s.remaining, s.required, s.covered, s.first_due,
           (SELECT lp.line_code FROM line_profiles lp
             WHERE lp.factory_id = s.factory_id
               AND (s.product_id = lp.default_model OR s.product_id = ANY(lp.can_make_models))
             ORDER BY (lp.default_model = s.product_id) DESC, lp.line_code
             LIMIT 1) AS home_line
    FROM summed s
    WHERE s.remaining > 0
""")


def _jobs(demand: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    jobs = []
    for row in demand:
        due = row.get("first_due")
        jobs.append({
            "id": f"DEMAND-{row['product_id']}",
            "product_id": str(row["product_id"]),
            "qty": float(row["remaining"] or 0),
            "due": due.date() if isinstance(due, datetime) else due,
            "line": str(row["home_line"]) if row.get("home_line") else None,
        })
    return jobs


def _coverage(demand: List[Dict[str, Any]]) -> Dict[str, float]:
    """覆盖率：0 = 现在完全开不了，1 = 齐套。

    口径是这台机种所有在制单合起来的物料覆盖比例，与就绪门用同一批数
    （`work_order_materials`），不另立一套判断。
    """
    out: Dict[str, float] = {}
    for row in demand:
        required = float(row.get("required") or 0)
        covered = float(row.get("covered") or 0)
        out[str(row["product_id"])] = 1.0 if required <= 0 else round(
            min(1.0, covered / required), 4)
    return out


def _group_deltas(fixed: Dict[str, Any], flexible: Dict[str, Any]) -> List[Dict[str, Any]]:
    """两组比较：少闲多少人日、追回多少台。

    "追回台数"按这一组**自己那些单**做完的量之差算，不看机器产出：
    允许挪线时自己的单可能被别组机器做掉，只有按归属算才看得清到底救回了多少。
    """
    home_rows = {r["line_group"]: r for r in fixed["lines"]}
    deltas = []
    for row in flexible["lines"]:
        group = row["line_group"]
        before = home_rows.get(group, {})
        deltas.append({
            "line_group": group,
            "idle_person_days_saved": round(float(before.get("idle_person_days") or 0)
                                            - float(row.get("idle_person_days") or 0), 1),
            "units_recovered": round(float(row.get("own_orders_units") or 0)
                                     - float(before.get("own_orders_units") or 0), 1),
            "crew_size_total": row.get("crew_size_total"),
            "group_units_per_day": row.get("group_units_per_day"),
        })
    return deltas


async def advise_line_strategy(
    db: AsyncSession, factory_id: str, *, days: int = 30,
    labor_rate: Optional[float] = None, as_of=None, apply: bool = True,
) -> Dict[str, Any]:
    """同一批在制需求跑两遍（各线只做自己 vs 允许挪到兼容线），差额发成 PMC 待办。"""
    from api.services.cost_model import resolve_rates
    from api.services.followup_task_service import create_task

    rates = resolve_rates([])
    rate = float(labor_rate if labor_rate is not None
                 else rates["rates"]["labor_person_day"]["amount"])
    lines = [dict(r) for r in (await db.execute(
        LINES_SQL, {"fid": factory_id})).mappings().all()]
    if not lines:
        return {"factory_id": factory_id, "status": "no_line_profiles",
                "reason": "line_profiles 是空的：没有线画像就没有可比的选择，不猜"}

    demand = [dict(r) for r in (await db.execute(
        DEMAND_SQL, {"fid": factory_id})).mappings().all()]
    # 只有线画像里能落到归属线的机种才是"线的产出对象"（= 整机）；
    # 半成品件号没有归属线，硬塞进线推演会算出"bike 组替没归属的件做了两万台"这种假账。
    line_jobs = [j for j in _jobs(demand) if j.get("line")]
    orphan_models = [row for row in demand if not row.get("home_line")]
    jobs = line_jobs
    if not jobs:
        return {"factory_id": factory_id, "status": "no_open_demand", "days": days}
    coverage = _coverage(demand)
    start = as_of or datetime.utcnow().date()

    fixed = simulate_lines(lines, [dict(j) for j in jobs], days=days, available_from={},
                           labor_rate=rate, allow_line_move=False,
                           coverage_by_model=coverage)
    flexible = simulate_lines(lines, [dict(j) for j in jobs], days=days, available_from={},
                              labor_rate=rate, allow_line_move=True,
                              coverage_by_model=coverage)
    deltas = _group_deltas(fixed, flexible)

    suggestions: List[Dict[str, Any]] = []
    created = 0
    threshold = MIN_SAVING_PERSON_DAYS
    for d in deltas:
        if float(d["idle_person_days_saved"]) < threshold and float(d["units_recovered"]) <= 0:
            continue
        evidence = {
            "category": "line_strategy", "line_group": d["line_group"],
            "days": days, "as_of": str(start),
            "idle_person_days_saved": d["idle_person_days_saved"],
            "units_recovered": d["units_recovered"],
            "labor_value": round(float(d["idle_person_days_saved"]) * rate, 2),
            "currency": rates["currency"],
            "moved_units_total": flexible.get("moved_units_to_other_lines"),
            "price_basis": "cost_model 默认标定（不是厂里工资表）",
            "why": "另一组兼容线有富余节拍：这些活不挪过去，就闲在这一组的人上",
        }
        suggestions.append(evidence)
        if not apply:
            continue
        existing = (await db.execute(text("""
            SELECT 1 FROM followup_tasks
            WHERE factory_id = :fid AND status NOT IN ('done', 'cancelled')
              AND payload->>'category' = 'line_strategy'
              AND payload->>'line_group' = :grp
            LIMIT 1
        """), {"fid": factory_id, "grp": d["line_group"]})).first()
        if existing:
            continue
        await create_task(
            db, factory_id, created_by="line_strategy_advisor",
            title=(f"[线组] {d['line_group']}：允许挪线可少闲 {d['idle_person_days_saved']:g} 人日"
                   f"（约 {d['idle_person_days_saved'] * rate:,.0f} {rates['currency']}），"
                   f"追回 {d['units_recovered']:g} 台"),
            description=(
                "同一批在制需求跑了两遍：各线只做自己机种 vs 允许挪到兼容的线。\n"
                f"· 少闲：{d['idle_person_days_saved']:g} 人日（这组 {d['crew_size_total']} 人）\n"
                f"· 追回欠交：{d['units_recovered']:g} 台\n"
                f"· 全厂挪线量：{flexible.get('moved_units_to_other_lines')} 台\n"
                "线画像与单向兼容取自 line_profiles（用户口述）；单价是默认标定，不是工资表。\n"
                "本条只把选择和账摆出来，不自动改排产：挪不挪由 PMC 与车间定。"
            ),
            agent_key="pmc_agent", item_type="followup", source="line_strategy_advisor",
            follow_interval_minutes=480,
            payload=json.dumps(evidence, ensure_ascii=False),
        )
        created += 1
        if len(suggestions) >= ADVISOR_LIMIT_GROUPS:
            break

    return {"factory_id": factory_id, "as_of": str(start), "days": days,
            "open_models": len(jobs), "coverage_by_model": coverage,
            "models_without_home_line": len(orphan_models),
            "units_without_home_line": round(sum(float(o["remaining"] or 0) for o in orphan_models), 1),
            "fixed_units_made": fixed.get("units_made"),
            "flexible_units_made": flexible.get("units_made"),
            "fixed_idle_person_days": fixed.get("total_idle_person_days"),
            "flexible_idle_person_days": flexible.get("total_idle_person_days"),
            "group_deltas": deltas, "suggestions": suggestions,
            "tasks_created": created, "apply": apply,
            "currency": rates["currency"], "labor_rate": rate,
            "labor_rate_basis": "cost_model 默认标定", "status": "ok"}
