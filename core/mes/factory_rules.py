"""规则与决策台账：没有燃料就自己造，不等谁来补。

三家一起跑的那条链是 —— 规则把 AI 关进现实边界 → 引擎只在边界内推演 → 决策与结果记账 →
账上的样本长出 candidate rule → 人确认后变成正式规则。缺任何一环都会退化成"等 IE 填表"。
这个模块补的是平时没人做的三件事：

1. **自己挖**：`operators.skills` / `hr_employees` 里已经有人写的技能与等级，把它算成
   "这个厂有几个能干这件事的人" —— 0 个和"没声明"是两件事，0 个就是物理上不能做（只能等）；
2. **自己问**：`open_questions()` 把约束层摊出来的空白变成一条条**可回答的闭合问题**，
   交给 chatbot 在当班对话里问现场的人，回答用 `record_rule()` 落成规则（source=chat，带消息证据）；
3. **自己记账**：`backfill_decision_ledger()` 把已经存在但从未被连起来的三张表
   （推演推荐 = 当时的状态与动作、工单实绩 = 结果、约束判定 = 候选集）连成决策台账，
   `mine_patterns()` 再从台账里按"同状态同动作"算成功率，产出 `status=candidate` 的模式 ——
   candidate 不参与约束判定，只有人确认成 validated/declared 才会拦住引擎。

写库范围只有两张新表（`factory_rules`、`decision_records`）。事实表一律不动。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALID_VERDICTS = ("allowed", "forbidden", "bounded")
VALID_KINDS = ("constraint", "pattern")
VALID_STATUSES = ("candidate", "declared", "validated", "rejected")
VALID_SOURCES = ("chat", "derived", "pattern_mining", "human_ui", "backfill")

DDL = [
    """
    CREATE TABLE IF NOT EXISTS factory_rules (
        id TEXT PRIMARY KEY,
        factory_id TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'constraint',
        subject TEXT NOT NULL,
        verdict TEXT NOT NULL,
        statement TEXT,
        params JSONB NOT NULL DEFAULT '{}'::jsonb,
        status TEXT NOT NULL DEFAULT 'candidate',
        source TEXT NOT NULL DEFAULT 'derived',
        evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
        asked_by TEXT,
        confirmed_by TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_factory_rules_lookup
        ON factory_rules (factory_id, subject, status)
    """,
    """
    CREATE TABLE IF NOT EXISTS decision_records (
        id TEXT PRIMARY KEY,
        factory_id TEXT NOT NULL,
        occurred_at TIMESTAMPTZ NOT NULL,
        state JSONB NOT NULL DEFAULT '{}'::jsonb,
        candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
        action JSONB NOT NULL DEFAULT '{}'::jsonb,
        outcome JSONB NOT NULL DEFAULT '{}'::jsonb,
        outcome_source TEXT NOT NULL DEFAULT 'unknown',
        linked_task_id TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_decision_records_lookup
        ON decision_records (factory_id, occurred_at DESC)
    """,
]

SKILL_CENSUS_SQL = text("""
    SELECT o.factory_id,
           count(*) AS operators,
           count(*) FILTER (WHERE COALESCE(o.skills::text, '') NOT IN ('', '{}', 'null')) AS with_skills,
           count(*) FILTER (WHERE o.skills::text ~* '(inspection|检测|检验|测量|measurement|test|试验)') AS inspector_like,
           count(*) FILTER (WHERE o.skills::text ~* '(assembly|组立|装配)') AS assembly_like,
           count(*) FILTER (WHERE o.skills::text ~* '(weld|焊接|smt|polish|mold|注塑|浸塑| machining|加工)') AS special_like,
           count(*) FILTER (WHERE o.skills::text ~* '(组长|leader|supervisor|技术员|technician|engineer|工程师)') AS lead_or_tech
    FROM operators o WHERE o.factory_id = :fid GROUP BY 1
""")

HR_SECTION_SQL = text("""
    SELECT e.station AS section, count(*) AS n,
           mode() WITHIN GROUP (ORDER BY e.skill_level) AS modal_level,
           count(DISTINCT e.skill_level) AS distinct_levels,
           count(*) FILTER (WHERE COALESCE(e.skill_level, '') <> '') AS with_level
    FROM hr_employees e
    WHERE e.factory_id = :fid AND COALESCE(e.status, 'active') = 'active'
    GROUP BY 1 ORDER BY 2 DESC
""")

LEDGER_SOURCE_SQL = text("""
    SELECT id, title, description, created_at, payload, status, assigned_to
    FROM followup_tasks
    WHERE factory_id = :fid AND title LIKE '推演推荐%'
      AND payload->'actions' IS NOT NULL
    ORDER BY created_at DESC LIMIT :lim
""")

ORDER_OUTCOME_SQL = text("""
    SELECT w.id, w.product_id, w.planned_qty, COALESCE(w.completed_qty, 0) AS completed_qty,
           COALESCE(w.good_qty, 0) AS good_qty, w.planned_due, w.actual_start, w.status
    FROM work_orders w
    WHERE w.factory_id = :fid AND w.product_id = ANY(:products)
""")


async def ensure_schema(db: AsyncSession) -> List[str]:
    done: List[str] = []
    for stmt in DDL:
        await db.execute(text(stmt))
        done.append(text(stmt).compile().string.split("(")[0].strip()[:48])
    await db.commit()
    return ["create table if not exists factory_rules", "create table if not exists decision_records"]


def _json(v: Any) -> Dict[str, Any]:
    """jsonb 经 asyncpg 可能已经是 dict，也可能是 str —— 两种都要吃得下，别在此处抛异常。"""
    if isinstance(v, dict):
        return v
    try:
        return json.loads(v or "{}")
    except (TypeError, ValueError):
        return {}


def _sid(seed: str) -> str:
    import hashlib
    return "rule-" + hashlib.sha1(seed.encode()).hexdigest()[:20]


async def upsert_rule(db: AsyncSession, factory_id: str, *, subject: str, verdict: str,
                      kind: str = "constraint", statement: str = "", status: str = "candidate",
                      source: str = "derived", params: Optional[Dict[str, Any]] = None,
                      evidence: Optional[Dict[str, Any]] = None, asked_by: Optional[str] = None,
                      confirmed_by: Optional[str] = None,
                      discriminator: Optional[str] = None) -> Dict[str, Any]:
    """规则落库的唯一入口。subject 必须落在动作词表里 —— 不许有"随手编一条规则"这条路。"""
    from core.mes.action_constraints import ACTIONS

    subject = str(subject or "").strip()
    head = subject.split(":", 1)[0]
    if head not in ACTIONS:
        return {"error": f"subject 必须是封闭动作词表里的一个，收到 {subject}；"
                         f"可选：{'、'.join(sorted(ACTIONS))}"}
    if verdict not in VALID_VERDICTS:
        return {"error": f"verdict 只能是 {'/'.join(VALID_VERDICTS)}"}
    if status not in VALID_STATUSES:
        return {"error": f"status 只能是 {'/'.join(VALID_STATUSES)}"}
    if source not in VALID_SOURCES:
        return {"error": f"source 只能是 {'/'.join(VALID_SOURCES)}"}
    # 同一个动作可以有多条并行事实（例：调人这件事上"能顶检测的有 2 人"和"能顶焊接的有 4 人"），
    # 不带判别键的话后写的会把前面的覆盖成同一条 —— 覆盖掉的那条读起来像从没存在过。
    # 话术指向的动作和 subject 不一致时拒绝写入：实测模型把"暴雨不许外发"记到了
    # reroute_line 上，一旦 binding 生效，引擎会挡掉改派而不是挡掉外发 —— 边界记反比没边界更糟。
    statement_txt = str(statement or "")
    hints = {
        "subcontract": ["外发", "外协", "外包", "subcontract"],
        "add_overtime": ["加班", "上限", "OT"],
        "cross_line_transfer": ["调人", "跨线", "顶岗", "借人", "检测岗", "技能"],
        "parallel_line": ["并联", "第二条线", "开两条线", "临时加设备", "增加设备"],
        "reroute_line": ["改派", "换线", "改线", "移线", "挪到别的线"],
        "expedite_purchase": ["加急", "催料", "催货", "提前期压"],
        "partial_delivery": ["部分交付", "分批交付", "先交一部分"],
        "split_release": ["分批开工", "先开", "不等齐套"],
        "reprioritize": ["优先级", "插单", "先后顺序"],
        "extra_crew": ["加人", "补人", "增加人手", "外部补人"],
    }
    hit = sorted(k for k, words in hints.items() if any(w in statement_txt for w in words))
    head = subject.split(":", 1)[0]
    if len(hit) == 1 and hit[0] != head:
        return {"error": f"话术里指向的动作是 {hit[0]}（{statement_txt[:40]}），但 subject 是 {subject}。"
                         f"请用 subject={hit[0]} 重新记录 —— 动作记错会让引擎挡错方向，比没有边界更糟。",
                "suggested_subject": hit[0]}
    ambiguity = None if hit else "话术里没有任何动作线索，按传入 subject 记录，建议人工复核"

    rid = _sid(f"{factory_id}|{subject}|{kind}|{discriminator or ''}")
    await db.execute(text("""
        INSERT INTO factory_rules (id, factory_id, kind, subject, verdict, statement, params,
                                   status, source, evidence, asked_by, confirmed_by)
        VALUES (:id, :fid, :kind, :subject, :verdict, :stmt, CAST(:params AS jsonb),
                :status, :source, CAST(:evidence AS jsonb), :asked_by, :confirmed_by)
        ON CONFLICT (id) DO UPDATE SET
            verdict = EXCLUDED.verdict, statement = EXCLUDED.statement,
            params = EXCLUDED.params, status = EXCLUDED.status, source = EXCLUDED.source,
            evidence = EXCLUDED.evidence, asked_by = COALESCE(EXCLUDED.asked_by, factory_rules.asked_by),
            confirmed_by = COALESCE(EXCLUDED.confirmed_by, factory_rules.confirmed_by),
            updated_at = NOW()
    """), {"id": rid, "fid": factory_id, "kind": kind, "subject": subject,
           "verdict": verdict, "stmt": statement[:1000],
           "params": json.dumps(params or {}, ensure_ascii=False, default=str),
           "status": status, "source": source,
           "evidence": json.dumps(evidence or {}, ensure_ascii=False, default=str),
           "asked_by": asked_by, "confirmed_by": confirmed_by})
    await db.commit()
    return {"rule_id": rid, "subject": subject, "verdict": verdict, "status": status,
            "source": source, "binding": status in ("declared", "validated"),
            **({"ambiguity": ambiguity} if ambiguity else {}),
            **({"detected_actions_in_statement": hit} if len(hit) != 1 else {})}


async def binding_rules(db: AsyncSession, factory_id: str) -> Dict[str, Dict[str, Any]]:
    """只有 declared/validated 才是约束；candidate 是"发现了但还没人确认"，不参与拦。"""
    rows = (await db.execute(text("""
        SELECT kind, subject, verdict, statement, params, status, source, evidence::text AS evidence
        FROM factory_rules WHERE factory_id = :fid AND status IN ('declared', 'validated')
        ORDER BY updated_at DESC
    """), {"fid": factory_id})).mappings().all()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = str(r["subject"])
        if key not in out:
            out[key] = {"kind": r["kind"], "subject": key, "verdict": r["verdict"],
                        "statement": r["statement"], "status": r["status"], "source": r["source"],
                        "params": _json(r["params"]),
                        "evidence": r["evidence"]}
    return out


async def candidate_patterns(db: AsyncSession, factory_id: str) -> List[Dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT subject, verdict, statement, params::text AS params, evidence::text AS evidence, updated_at
        FROM factory_rules WHERE factory_id = :fid AND status = 'candidate' AND kind = 'pattern'
        ORDER BY updated_at DESC LIMIT 50
    """), {"fid": factory_id})).mappings().all()
    return [{"subject": r["subject"], "verdict": r["verdict"], "statement": r["statement"],
             "params": _json(r["params"]), "evidence": _json(r["evidence"]),
             "status": "candidate", "observed_at": str(r["updated_at"])} for r in rows]


async def workforce_census(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """从已经有人填过的数据里算"有几双手"：这是挖出来的证据，不是声明的规则。"""
    cen = dict((await db.execute(SKILL_CENSUS_SQL, {"fid": factory_id})).mappings().first() or {})
    sections = [dict(r) for r in (await db.execute(HR_SECTION_SQL, {"fid": factory_id})).mappings().all()]
    ops = int(cen.get("operators") or 0)
    with_skills = int(cen.get("with_skills") or 0)
    inspectors = int(cen.get("inspector_like") or 0)
    coverage = round(with_skills / ops, 3) if ops else None
    return {"operators": ops, "with_skills": with_skills, "skill_coverage": coverage,
            "qualified_like": {"inspector_or_qc": inspectors,
                               "assembly": int(cen.get("assembly_like") or 0),
                               "special_process": int(cen.get("special_like") or 0),
                               "lead_or_technician": int(cen.get("lead_or_tech") or 0)},
            "hr_sections": sections,
            "reading": ("0 个与'没声明'不是一回事：0 个是这件事在这个厂现在没有手可做，只能等；"
                        "没声明是规则还没写。技能填充率低于 30% 时，人数证据只能当参考，不能当放行依据。"),
            "basis": "operators.skills（技能:等级 JSON）+ hr_employees.station/skill_level（花名册在册口径）"}


# 空白规则 → 可回答的闭合问题。现场的人回答不了"请填 required_skills"，
# 但能回答"组立线今天能不能让焊接的人顶检测岗"。答案落成规则，缺口当场少一条。
QUESTION_TEMPLATES = [
    ("subcontract", "今天这种缺人手的情况下，{scope} 允许外发吗？（允许 / 禁止 / 只允许某几个件）"),
    ("add_overtime", "{scope} 加班上限是每天几小时？（给个数，没有上限就别让系统建议加班）"),
    ("cross_line_transfer", "{scope} 缺人时，允许从哪些组调人？调过去需要什么技能或等级？"),
    ("partial_delivery", "{scope} 这个客户/订单允许部分交付吗？（算不算违约）"),
    ("parallel_line", "{scope} 开第二条线时，合并日产能上限是多少台/天？"),
]


async def open_questions(db: AsyncSession, factory_id: str, *,
                         line_code: Optional[str] = None) -> Dict[str, Any]:
    """把约束层的 undeclared 变成现场能一句话回答的问题，并按已挖到的证据预填候选答案。"""
    from core.mes.action_constraints import action_constraints

    census = await workforce_census(db, factory_id)
    cons = await action_constraints(db, factory_id, line_code=line_code)
    sections = [str(s.get("section")) for s in (census.get("hr_sections") or [])[:6]]
    scope = line_code or ("组立/焊接/加工 等 " + str(len(sections)) + " 个在册工段")
    by_action = {a["action"]: a for a in cons["actions"]}
    out: List[Dict[str, Any]] = []
    for action, tpl in QUESTION_TEMPLATES:
        verdict = str((by_action.get(action) or {}).get("verdict") or "")
        if not verdict.startswith("undeclared"):
            continue
        hint = None
        if action == "cross_line_transfer":
            q = census.get("qualified_like") or {}
            hint = (f"册上技能覆盖 {census.get('skill_coverage')}；像检测/检验这类技能的人数 "
                    f"{q.get('inspector_or_qc')}，组长/技术员 {q.get('lead_or_technician')} —— "
                    "如果这几个数是错的，请指出哪个组实际有多少人能干")
        out.append({"action": action, "question": tpl.format(scope=scope),
                    "why_it_matters": (by_action.get(action) or {}).get("why"),
                    "expected_answer": "allowed / forbidden / 上限数值",
                    "prefilled_evidence": hint,
                    "record_as": {"subject": action, "verdict": "allowed|forbidden|bounded",
                                  "status": "declared", "source": "chat"}})
    return {"factory_id": factory_id, "line": line_code, "open_questions": out,
            "asked_count": len(out), "checked": {"actions_evaluated": len(by_action),
                                                 "operators_seen": census.get("operators")},
            "workforce_census": census,
            "how_to_answer": "POST /api/v1/pmc/factory-rules 或在对话里直接回答，"
                             "助手用工具 record_factory_rule 落成 declared 规则"}


async def record_candidates_from_census(db: AsyncSession, factory_id: str, *,
                                         apply: bool = False) -> Dict[str, Any]:
    """把人手上挖出来的事实先记成 candidate 规则（不拦引擎，等人确认）。"""
    census = await workforce_census(db, factory_id)
    q = census.get("qualified_like") or {}
    made: List[Dict[str, Any]] = []
    checks = [("cross_line_transfer", "inspector_or_qc", "厂里能顶检测/检验岗的人数"),
              ("cross_line_transfer", "special_process", "能顶特殊工艺（焊接/注塑/SMT 等）的人数"),
              ("cross_line_transfer", "lead_or_technician", "组长/技术员可调配人数")]
    for subject, key, label in checks:
        n = int(q.get(key) or 0)
        verdict = "forbidden" if n == 0 else "bounded"
        stmt = (f"{label}：册上算出 {n} 人"
                + (" —— 0 个人 means 这件事现在没人可做，只能等或外发（不是'没声明'）" if n == 0 else ""))
        item = {"subject": subject, "verdict": verdict, "statement": stmt,
                "params": {"qualified_count": n, "basis": key},
                "evidence": {"operators": census.get("operators"),
                             "skill_coverage": census.get("skill_coverage")}}
        made.append(item)
        if apply:
            await upsert_rule(db, factory_id, subject=subject, verdict=verdict, kind="constraint",
                              statement=stmt[:900], status="candidate", source="derived",
                              params=item["params"], evidence=item["evidence"], discriminator=key)
    return {"factory_id": factory_id, "candidates": made, "written": bool(apply),
            "note": "全是 candidate：从花名册推出来的人数不能当放行依据，要现场确认才升 declared/validated"}


async def backfill_decision_ledger(db: AsyncSession, factory_id: str, *, limit: int = 50,
                                   apply: bool = False) -> Dict[str, Any]:
    """把"引擎当时推荐了什么 + 后来实际做到多少"连成一行台账。

    这三张表本来都在写，但从没被连起来过 —— 推荐留在 followup_tasks、实绩留在 work_orders，
    中间那段"当时是什么状态、还有哪些候选没被选"没人记，所以成功率永远算不出来。
    """
    tasks = [dict(r) for r in (await db.execute(
        LEDGER_SOURCE_SQL, {"fid": factory_id, "lim": int(limit)})).mappings().all()]
    products: List[str] = []
    for t in tasks:
        for act in (_json(t["payload"]).get("actions") or []):
            code = str((act or {}).get("model_code") or "")
            if code and code not in products:
                products.append(code)
    orders = [dict(r) for r in (await db.execute(
        ORDER_OUTCOME_SQL, {"fid": factory_id, "products": products})).mappings().all()] if products else []
    by_product: Dict[str, List[Dict[str, Any]]] = {}
    for o in orders:
        by_product.setdefault(str(o["product_id"]), []).append(o)
    rows: List[Dict[str, Any]] = []
    for t in tasks:
        payload = _json(t["payload"])
        acts = payload.get("actions") or []
        shared_state = {"policy": payload.get("policy"), "predicted": payload.get("objectives") or {},
                        "per_scenario": payload.get("per_scenario") or {}, "source_task": str(t["id"])}
        for i, a in enumerate(acts):
            a = a or {}
            model = str(a.get("model_code") or "")
            linked = by_product.get(model) or []
            planned = sum(float(c.get("planned_qty") or 0) for c in linked)
            good = sum(float(c.get("good_qty") or 0) for c in linked)
            # 结果质量必须分级：这些工单的计划量/交期是厂里的，但 good_qty 是自家仿真时钟报的工
            quality = "verified_field" if (linked and any(c.get("actual_start") for c in linked)
                                           and not bool(a.get("sandbox_only"))) else (
                "mixed_simulation" if linked else "no_linked_order")
            rows.append({
                "id": f"dec-{t['id']}-{i}", "factory_id": factory_id, "occurred_at": t["created_at"],
                "state": {**shared_state, "scenario": a.get("scenario"), "model_code": model or None},
                "candidates": acts,
                "action": {"type": a.get("type"), "policy": payload.get("policy"),
                           "detail": a, "linked_task_id": str(t["id"])},
                "outcome": {"action_type": a.get("type"), "model_code": model or None,
                            "promised_due_date": a.get("due_date"),
                            "planned_finish_date": a.get("planned_finish_date"),
                            "orders_linked": len(linked), "planned_units": planned,
                            "good_units": good,
                            "achievement_rate": round(good / planned, 3) if planned else None,
                            "outcome_quality": quality},
                "outcome_source": ("work_order_actuals" if quality == "verified_field" else
                                   "work_order_with_sim_reports" if quality == "mixed_simulation" else
                                   "no_linked_order"),
                "linked_task_id": str(t["id"]),
            })
    if apply:
        for r in rows:
            await db.execute(text("""
                INSERT INTO decision_records (id, factory_id, occurred_at, state, candidates, action,
                                              outcome, outcome_source, linked_task_id)
                VALUES (:id, :fid, :at, CAST(:state AS jsonb), CAST(:cands AS jsonb), CAST(:act AS jsonb),
                        CAST(:out AS jsonb), :src, :task)
                ON CONFLICT (id) DO UPDATE SET outcome = EXCLUDED.outcome,
                    outcome_source = EXCLUDED.outcome_source, candidates = EXCLUDED.candidates,
                    state = EXCLUDED.state, action = EXCLUDED.action
            """), {"id": r["id"], "fid": factory_id, "at": r["occurred_at"],
                   "state": json.dumps(r["state"], ensure_ascii=False, default=str),
                   "cands": json.dumps(r["candidates"], ensure_ascii=False, default=str),
                   "act": json.dumps(r["action"], ensure_ascii=False, default=str),
                   "out": json.dumps(r["outcome"], ensure_ascii=False, default=str),
                   "src": r["outcome_source"], "task": r["linked_task_id"]})
        await db.commit()
    counted: Dict[str, int] = {}
    for r in rows:
        counted[r["outcome_source"]] = counted.get(r["outcome_source"], 0) + 1
    real = counted.get("work_order_actuals", 0)
    return {"factory_id": factory_id, "recommendations_read": len(tasks), "records": len(rows),
            "written": bool(apply), "outcome_source_counts": counted,
            "minable_samples": real,
            "outcome_quality_counts": {k: sum(1 for r in rows
                                              if r["outcome"]["outcome_quality"] == k)
                                       for k in ("verified_field", "mixed_simulation", "no_linked_order")},
            "note": ("只有 outcome_source=work_order_actuals 的行能用来算成功率；"
                     "sandbox_prediction_only 是引擎自己的预测，拿它当'结果'就是闭环自证。"
                     "回填只能补历史的那一半（推荐），另一半（当时状态与后来实绩）要对得上才有燃料。"),
            "rows": rows[:20]}


async def mine_patterns(db: AsyncSession, factory_id: str, *, min_samples: int = 5,
                        apply: bool = False) -> Dict[str, Any]:
    """从决策台账里按"同状态 + 同动作"分组算达成率，产出 candidate 规则（不拦引擎）。"""
    # 归因只能用"当时真被执行的那个动作"（action 那一列）。展开 candidates 会把同一份
    # 候选清单里没被选中的动作也算成做过一次 —— 实测虚高 13 倍（199 行变 2589 行）。
    rows = (await db.execute(text("""
        SELECT COALESCE(state->>'scenario', state->'scenarios'->>0) AS scenario,
               action->>'policy' AS policy, action AS act, outcome, outcome_source
        FROM decision_records WHERE factory_id = :fid
    """), {"fid": factory_id})).mappings().all()
    groups: Dict[tuple, Dict[str, Any]] = {}
    for r in rows:
        outcome = _json(r["outcome"])
        # 只有真实现场结果才进统计：引擎自己的预测、仿真时钟报的工都不算
        if outcome.get("outcome_quality") != "verified_field":
            continue
        act = _json(r["act"])
        if not act.get("type"):
            continue
        detail = act.get("detail") or {}
        key = (str(r["scenario"] or ""), str(act.get("type")),
               str(detail.get("model_code") or detail.get("material_code") or ""))
        rate = outcome.get("achievement_rate")
        g = groups.setdefault(key, {"samples": 0, "rated": 0, "sum": 0.0, "policies": set(),
                                    "outcome_sources": set()})
        g["samples"] += 1
        g["policies"].add(str(r["policy"] or ""))
        if isinstance(rate, (int, float)):
            g["rated"] += 1
            g["sum"] += float(rate)
    patterns: List[Dict[str, Any]] = []
    for (scenario, act_type, scope), g in groups.items():
        if g["samples"] < min_samples or not act_type:
            continue
        avg = round(g["sum"] / g["rated"], 3) if g["rated"] else None
        subject = f"cross_line_transfer:{scope}" if "transfer" in act_type else {
            "expedite_purchase": "expedite_purchase", "start_first_batch": "split_release",
            "overtime": "add_overtime", "extra_crew": "extra_crew"}.get(act_type, None)
        if not subject or subject not in {"expedite_purchase", "split_release", "add_overtime", "extra_crew",
                                          "cross_line_transfer"} and not subject.startswith("cross_line_transfer"):
            continue
        patterns.append({"subject": subject, "scenario": scenario or None, "samples": g["samples"],
                         "with_achievement_rate": g["rated"], "mean_achievement_rate": avg,
                         "action_type": act_type, "status": "candidate",
                         "statement": (f"在 {scenario or '未知天气'} 下做过 {g['samples']} 次 {act_type}"
                                       f"（有达成率读数的 {g['rated']} 次，均值 {avg}）"
                                       "—— 这是发现的模式，未经确认不拦引擎")})
    if apply:
        for p in patterns:
            await upsert_rule(db, factory_id, subject=p["subject"], verdict="bounded", kind="pattern",
                              statement=p["statement"], status="candidate", source="pattern_mining",
                              params={"scenario": p["scenario"], "action_type": p["action_type"],
                                      "mean_achievement_rate": p["mean_achievement_rate"]},
                              evidence={"samples": p["samples"], "with_achievement_rate": p["with_achievement_rate"]},
                              discriminator=f"{p['action_type']}|{p['scenario']}")
    return {"factory_id": factory_id, "records_scanned": len(rows), "groups": len(groups),
            "patterns_found": len(patterns), "min_samples": min_samples, "written": bool(apply),
            "patterns": patterns,
            "rule": "样本不足 min_samples 不产出；产出一律 status=candidate，人确认成 validated 才进约束判定"}
