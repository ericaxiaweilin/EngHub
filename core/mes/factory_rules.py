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
VALID_SOURCES = ("chat", "derived", "pattern_mining", "human_ui", "backfill", "adoption")

# 这些 updated_by/created_by 是程序写的，不是人做的事 —— 拿它们当"现场已采纳"就是自证
MACHINE_ACTORS = {
    "component_expand", "virtual_factory", "mps_release", "pmc_agent", "scheduling_agent",
    "warehouse_agent", "delivery_agent", "quality_agent", "procurement_agent",
    "escalation_agent", "ai_assistant", "system", "seed", "admin_script",
}
# 这几个动作现在没有任何落库执行通道：厂里做了也没地方查，所以不能算"已采纳"
NO_CHANNEL_ACTIONS = {"parallel_line", "add_overtime", "extra_crew", "cross_line_transfer",
                      "partial_delivery", "reprioritize"}

# 仿真时钟造出来的人（vf_mec_0001 这种）写在工单上看着像"有人做过"，其实是系统在给自己盖章
SIM_ACTOR_PREFIXES = ("vf_", "sim_")

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
    """
    CREATE TABLE IF NOT EXISTS execution_events (
        id TEXT PRIMARY KEY,
        factory_id TEXT NOT NULL,
        occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
        action TEXT NOT NULL,
        line_code TEXT,
        section TEXT,
        model_code TEXT,
        people INT,
        hours NUMERIC,
        units NUMERIC,
        note TEXT,
        actor TEXT,
        source TEXT NOT NULL DEFAULT 'manual',
        created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_execution_events_lookup
        ON execution_events (factory_id, action, occurred_at DESC)
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

# 执行通道：推荐落地要能在库里查到痕迹。查不到就说查不到，不能当成"没采纳"或"已采纳"。
PO_AFTER_SQL = text("""
    SELECT po.material_code, po.created_by, po.order_date, po.expected_date, po.actual_date
    FROM purchase_orders po
    WHERE po.factory_id = :fid AND po.material_code = ANY(:codes) AND po.order_date >= :since
    ORDER BY po.order_date LIMIT 20
""")

WO_AFTER_SQL = text("""
    SELECT w.product_id, w.status, w.updated_by, w.updated_at, w.actual_start, w.planned_due,
           COALESCE(w.good_qty, 0) AS good_qty
    FROM work_orders w
    WHERE w.factory_id = :fid AND w.product_id = ANY(:products)
      AND w.updated_at >= :since AND w.status IN ('released','in_progress','completed')
    ORDER BY w.updated_at LIMIT 30
""")

LEDGER_SQL = text("""
    SELECT id, factory_id, occurred_at, state::text AS state, action::text AS action,
           outcome::text AS outcome, outcome_source, linked_task_id
    FROM decision_records WHERE factory_id = :fid ORDER BY occurred_at DESC LIMIT :lim
""")

ORDER_OUTCOME_SQL = text("""
    SELECT w.id, w.product_id, w.planned_qty, COALESCE(w.completed_qty, 0) AS completed_qty,
           COALESCE(w.good_qty, 0) AS good_qty, w.planned_due, w.actual_start, w.status,
           w.updated_by, w.created_by
    FROM work_orders w
    WHERE w.factory_id = :fid AND w.product_id = ANY(:products)
""")


async def actor_class(db: AsyncSession, actor: Any) -> str:
    """human / agent / simulation / unknown —— 决定这条证据能不能算现场事实。"""
    name = str(actor or "").strip()
    if not name:
        return "unknown"
    if name in MACHINE_ACTORS:
        return "agent"
    if name.startswith(SIM_ACTOR_PREFIXES):
        return "simulation"
    hit = (await db.execute(text("SELECT 1 FROM users WHERE username = :u LIMIT 1"),
                            {"u": name})).scalar()
    return "human" if hit else "unknown"


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


async def pending_rules(db: AsyncSession, factory_id: str, *, limit: int = 20) -> List[Dict[str, Any]]:
    """等着人确认的候选规则（带 rule_id，确认时要用）。"""
    rows = (await db.execute(text("""
        SELECT id, kind, subject, verdict, statement, params::text AS params, source, evidence::text AS evidence,
               updated_at
        FROM factory_rules WHERE factory_id = :fid AND status = 'candidate'
        ORDER BY updated_at DESC LIMIT :lim
    """), {"fid": factory_id, "lim": int(limit)})).mappings().all()
    return [{"rule_id": r["id"], "kind": r["kind"], "subject": r["subject"], "verdict": r["verdict"],
             "statement": r["statement"], "params": _json(r["params"]), "source": r["source"],
             "evidence": _json(r["evidence"]), "observed_at": str(r["updated_at"])} for r in rows]


async def confirm_rule(db: AsyncSession, factory_id: str, *, rule_id: str, agree: bool,
                       actor: str = "unknown", note: str = "") -> Dict[str, Any]:
    """人选"同意"→ validated（开始拦引擎）；选"驳回"→ rejected（留痕，不再反复问）。

    只动 candidate 状态的行：已声明的厂规不是系统能替人改的东西。
    """
    row = (await db.execute(text("SELECT id, status, subject, kind FROM factory_rules WHERE id = :id"),
                            {"id": str(rule_id)})).mappings().first()
    if not row:
        return {"error": f"rule_id {rule_id} 不存在"}
    if str(row["status"]) != "candidate":
        return {"error": f"这条现在是 {row['status']}，只有 candidate 可以确认或驳回；"
                         "已声明的厂规要改请用 record_factory_rule 明确改判"}
    new_status = "validated" if agree else "rejected"
    await db.execute(text("""
        UPDATE factory_rules SET status = :st, confirmed_by = :who, updated_at = NOW(),
               statement = CASE WHEN :note = '' THEN statement
                                ELSE statement || ' ｜ 确认：' || :note END
        WHERE id = :id
    """), {"st": new_status, "who": str(actor or "unknown"), "note": str(note or "")[:300],
           "id": str(rule_id)})
    await db.commit()
    return {"rule_id": str(rule_id), "subject": row["subject"], "status": new_status,
            "confirmed_by": actor,
            "effect": ("这条现在开始过滤引擎的候选动作" if agree else
                       "已驳回：不再当候选提出，记录留着，规则要改就明确改判")}


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
    pend = await pending_rules(db, factory_id, limit=10)
    return {"factory_id": factory_id, "line": line_code, "open_questions": out,
            "pending_candidates": pend,
            "confirm_how": "同意的用 confirm_rule(rule_id, agree=true) 升成 validated；"
                           "不对就 agree=false 驳回（留痕，不再反复问）",
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
            # 质量分级看三件事：有没有连到工单、工单里那笔量是谁写的、动作本身有没有执行通道
            actors = {str(c.get("updated_by") or c.get("created_by") or "") for c in linked} - {""}
            classes = {await actor_class(db, x) for x in actors}
            human = "human" in classes
            started = any(c.get("actual_start") for c in linked)
            quality = ("no_execution_channel" if str(a.get("type") or "") in NO_CHANNEL_ACTIONS else
                       "verified_human" if (linked and human and started) else
                       "verified_agent" if (linked and started and classes & {"agent", "unknown"}) else
                       "verified_simulation" if (linked and started) else
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
                "outcome_source": ("work_order_actuals" if quality.startswith("verified") else
                                   "work_order_with_sim_reports" if quality == "mixed_simulation" else
                                   "no_channel" if quality == "no_execution_channel" else
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
                                       for k in ("verified_human", "verified_agent", "verified_simulation",
                                                 "mixed_simulation", "no_execution_channel",
                                                 "no_linked_order")},
            "note": ("只有 outcome_source=work_order_actuals 的行能用来算成功率；"
                     "没有执行通道的动作（加班/并联/调人/部分交付）一律不算采纳 —— "
                     "厂里做了也没地方查，那就得靠 record_adoption 人肉确认，机器写的只算 verified_agent。"
                     "回填只能补历史的那一半（推荐），另一半（当时状态与后来实绩）要对得上才有燃料。"),
            "rows": rows[:20]}


async def record_adoption(db: AsyncSession, factory_id: str, *, decision_id: Optional[str] = None,
                          action_type: Optional[str] = None, adopted: bool = True,
                          note: str = "", actor: str = "unknown",
                          evidence: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把"这件事我们真做了/没做"记回台账 —— 没有这个口，永远只有预测没有结果。

    推荐落到收件箱之后，现场做没做、谁做的、做成了什么，系统里本来查不到（加班、开并联线、
    跨线调人这些动作连张表都没有）。这个口不假装自动：明确写 actor，机器写的算 agent、
    人写的算 human，达成率只认真人确认过的行。
    """
    row = None
    if decision_id:
        row = (await db.execute(text("SELECT occurred_at, action FROM decision_records WHERE id = :id"),
                                {"id": decision_id})).mappings().first()
        if not row:
            return {"error": f"decision_id {decision_id} 不存在"}
    atype = str(action_type or (row["action"] if row else "") or "")
    if row and not atype:
        atype = str(_json(row["action"]).get("type") or "")
    if not atype:
        return {"error": "要么给 decision_id（能自动带出动作），要么直接给 action_type"}
    rid = f"adopt-{decision_id or atype}-{actor}"
    await db.execute(text("""
        INSERT INTO decision_records (id, factory_id, occurred_at, state, candidates, action,
                                      outcome, outcome_source, linked_task_id)
        VALUES (:id, :fid, NOW(), CAST(:state AS jsonb), '[]'::jsonb, CAST(:act AS jsonb),
                CAST(:out AS jsonb), :src, :link)
        ON CONFLICT (id) DO UPDATE SET outcome = EXCLUDED.outcome,
            outcome_source = EXCLUDED.outcome_source, state = EXCLUDED.state
    """), {"id": rid, "fid": factory_id,
           "state": json.dumps({"channel": "adoption", "actor": actor,
                                "note": note[:600]}, ensure_ascii=False, default=str),
           "act": json.dumps({"type": atype, "detail": {"adopted": bool(adopted)}},
                             ensure_ascii=False, default=str),
           "out": json.dumps({"adopted": bool(adopted), "confirmed_by": actor,
                              "outcome_quality": "verified_human" if actor not in MACHINE_ACTORS
                              else "verified_agent",
                              "note": note[:600], **(evidence or {})},
                             ensure_ascii=False, default=str),
           "src": "adoption", "link": decision_id})
    await db.commit()
    klass = await actor_class(db, actor)
    quality = {"human": "verified_human", "agent": "verified_agent",
               "simulation": "verified_simulation"}.get(klass, "unattributed")
    return {"record_id": rid, "action_type": atype, "adopted": bool(adopted), "actor": actor,
            "actor_class": klass, "outcome_quality": quality,
            "note": ("只有真人账号写的算 verified_human；vf_* 这类仿真身份写的算 verified_simulation，"
                     "程序写的是 verified_agent，认不出的账号是 unattributed —— 后三类都不进挖掘分母"
                     if quality != "verified_human" else "真人确认，进挖掘分母")}


async def sweep_adoption(db: AsyncSession, factory_id: str, *, limit: int = 40,
                         apply: bool = True) -> Dict[str, Any]:
    """每轮巡检自动回查"推荐过的事后来真发生了吗"，发生过的写进台账。

    这一步是燃料的自动泵：加急有没有下单、开工有没有把工单推起来，库里都查得到；
    查得到就记一行 verified_human/verified_agent，查不到留 not_detected —— 两种都是结论，
    但不能靠人记得去点。没有执行通道的动作（加班/并联/调人）直接标 no_channel，
    这本身就是"该建哪张表"的清单。
    """
    from datetime import datetime

    rows = await ledger_rows(db, factory_id, limit=limit)
    tally = {"checked": 0, "adopted_written": 0, "not_detected": 0, "no_channel": 0,
             "no_evidence": 0}
    seen: set = set()
    for r in rows:
        act = r.get("action") or {}
        atype = str(act.get("type") or "")
        detail = act.get("detail") or {}
        if not atype or str(r.get("state", {}).get("channel") or "") == "adoption":
            continue
        key = (atype, str(detail.get("material_code") or ""), str(detail.get("model_code") or ""))
        if key in seen:
            continue
        seen.add(key)
        tally["checked"] += 1
        try:
            since = datetime.fromisoformat(str(r["occurred_at"])[:19].replace("+00:00", ""))
        except ValueError:
            since = None
        d = await detect_adoption(db, factory_id, action_type=atype,
                                  model_code=detail.get("model_code"),
                                  material_code=detail.get("material_code"),
                                  target_lead_days=detail.get("target_lead_days"), since=since)
        status = str(d.get("status"))
        if status == "no_channel":
            tally["no_channel"] += 1
        elif status == "not_detected":
            tally["not_detected"] += 1
        elif status == "no_evidence":
            tally["no_evidence"] += 1
        elif status == "adopted" and apply:
            actors = [a for a in (d.get("human_actors") or []) if a] or \
                     [a for a in (d.get("actors") or []) if a]
            res = await record_adoption(db, factory_id, decision_id=r["id"], action_type=atype,
                                        adopted=True, actor=(actors[0] if actors else "unknown"),
                                        note=f"巡检自动回查认定采纳：{json.dumps({k: v for k, v in d.items() if k != 'status'}, ensure_ascii=False, default=str)[:280]}",
                                        evidence=d)
            if not res.get("error"):
                tally["adopted_written"] += 1
    return {**tally, "distinct_actions_checked": len(seen),
            "note": "自动回查只认库里有痕迹的（下单记录、工单状态推进）；没痕迹不等于没做，"
                    "那种要靠人确认（POST /adopt-recommendation 或助手的 adopt_recommendation）"}


async def record_execution(db: AsyncSession, factory_id: str, *, action: str,
                           line_code: Optional[str] = None, section: Optional[str] = None,
                           model_code: Optional[str] = None, people: Optional[int] = None,
                           hours: Optional[float] = None, units: Optional[float] = None,
                           note: str = "", actor: str = "unknown",
                           source: str = "manual") -> Dict[str, Any]:
    """记一件"现场真做过的事"：加了几小时班、从哪个组调了几个人、开了几条线、先交了几台。

    这张表存在的理由很单纯：加班、调人、开并联这些动作以前没有任何落点，
    所以规则（OT 上限 2h、调人要技能匹配）永远无法验证，挖掘也永远拿不到结果。
    """
    import hashlib
    from datetime import datetime

    action = str(action or "").split(":", 1)[0]
    if not action:
        return {"error": "action 不能为空"}
    stamp = datetime.now()
    rid = "exe-" + hashlib.sha1(f"{factory_id}|{action}|{line_code}|{section}|{stamp.isoformat()}".encode()).hexdigest()[:20]
    await db.execute(text("""
        INSERT INTO execution_events (id, factory_id, occurred_at, action, line_code, section,
                                      model_code, people, hours, units, note, actor, source)
        VALUES (:id, :fid, :at, :action, :line, :section, :model, :people, :hours, :units,
                :note, :actor, :source)
    """), {"id": rid, "fid": factory_id, "at": stamp, "action": action,
           "line": line_code, "section": section, "model": model_code,
           "people": int(people) if people is not None else None,
           "hours": float(hours) if hours is not None else None,
           "units": float(units) if units is not None else None,
           "note": str(note or "")[:600], "actor": str(actor or "unknown"), "source": source})
    await db.commit()
    return {"event_id": rid, "action": action, "occurred_at": stamp.isoformat(),
            "people": people, "hours": hours, "actor": actor,
            "rule_check": await check_rule_respect(db, factory_id, action,
                                                   line_code=line_code, section=section,
                                                   hours=hours, people=people)}


async def recent_executions(db: AsyncSession, factory_id: str, *, action: Optional[str] = None,
                             since: Any = None, line_code: Optional[str] = None,
                             section: Optional[str] = None, limit: int = 40) -> List[Dict[str, Any]]:
    clauses = ["factory_id = :fid"]
    params: Dict[str, Any] = {"fid": factory_id, "lim": int(limit)}
    if action:
        clauses.append("action = :action")
        params["action"] = action
    if since:
        clauses.append("occurred_at >= :since")
        params["since"] = since
    if line_code:
        clauses.append("(line_code IS NULL OR line_code = :line)")
        params["line"] = line_code
    if section:
        clauses.append("(section IS NULL OR section = :section)")
        params["section"] = section
    rows = (await db.execute(text(f"""
        SELECT id, occurred_at::text AS at, action, line_code, section, model_code,
               people, hours, units, note, actor, source
        FROM execution_events WHERE {" AND ".join(clauses)}
        ORDER BY occurred_at DESC LIMIT :lim
    """), params)).mappings().all()
    return [dict(r) for r in rows]


async def check_rule_respect(db: AsyncSession, factory_id: str, action: str, *,
                             line_code: Optional[str] = None, section: Optional[str] = None,
                             hours: Optional[float] = None,
                             people: Optional[int] = None) -> Dict[str, Any]:
    """把刚记的事对着已声明的厂规量一遍：超上限就当场报，不等下一轮推演。"""
    declared = await binding_rules(db, factory_id)
    rule = declared.get(str(action)) or {}
    params = rule.get("params") or {}
    if isinstance(params, str):
        params = _json(params)
    out: Dict[str, Any] = {"rule": bool(rule), "verdict": "no_rule"}
    cap = params.get("max_hours_per_day")
    if rule and str(rule.get("verdict")) == "forbidden":
        out.update(verdict="violates_forbidden",
                   why=f"厂规声明 {action} 不允许做，但记了一次执行（{hours}h/{people}人）")
    elif cap and hours is not None:
        out.update(verdict="over_cap" if float(hours) > float(cap) else "within_cap",
                   cap=float(cap), recorded_hours=float(hours))
    return out


async def ledger_rows(db: AsyncSession, factory_id: str, *, limit: int = 60) -> List[Dict[str, Any]]:
    rows = (await db.execute(LEDGER_SQL, {"fid": factory_id, "lim": int(limit)})).mappings().all()
    return [{"id": r["id"], "occurred_at": str(r["occurred_at"]), "state": _json(r["state"]),
             "action": _json(r["action"]), "outcome": _json(r["outcome"]),
             "outcome_source": r["outcome_source"], "linked_task_id": r["linked_task_id"]}
            for r in rows]


async def detect_adoption(db: AsyncSession, factory_id: str, *, action_type: str,
                          model_code: Optional[str] = None, material_code: Optional[str] = None,
                          target_lead_days: Optional[int] = None,
                          since: Any = None) -> Dict[str, Any]:
    """从库里回查"这件事后来真发生了吗"：加急看下单/台账天数，开工看工单状态与推进人。

    查不到就回 not_detected 并说明用了哪几条查询 —— 不能把"查不到"写成"没采纳"，
    更不能因为推演推荐里有这个动作就算成已执行。
    """
    if str(action_type) in NO_CHANNEL_ACTIONS:
        # 这些动作原来连地方记都没有；现在查 execution_events，查到就是采纳，查不到才说没通道/没痕迹
        ev = await recent_executions(db, factory_id, action=str(action_type), since=since, limit=5)
        if ev:
            actors = sorted({str(e.get("actor") or "") for e in ev} - {""})
            return {"status": "adopted", "executions": len(ev),
                    "actors": actors, "human_actors": sorted(set(actors) - MACHINE_ACTORS),
                    "detail": ev[0]}
        return {"status": "no_channel",
                "why": f"{action_type} 还没有执行记录（execution_events 里 0 行）—— "
                       "做了就用 /execution-events 或助手记一笔，否则规则永远验证不了"}
    if action_type == "expedite_purchase" and material_code:
        params = {"fid": factory_id, "codes": [str(material_code)], "since": since or "2000-01-01"}
        pos = [dict(r) for r in (await db.execute(PO_AFTER_SQL, params)).mappings().all()]
        ledger = (await db.execute(text("SELECT lead_time_days FROM materials "
                                         "WHERE factory_id=:fid AND material_code=:c"),
                                   {"fid": factory_id, "c": str(material_code)})).scalar()
        lowered = (target_lead_days is not None and ledger is not None
                   and int(ledger) <= int(target_lead_days))
        return {"status": "adopted" if (pos or lowered) else "not_detected",
                "po_placed_after": len(pos), "ledger_lead_days": ledger,
                "target_lead_days": target_lead_days,
                "actors": sorted({str(p.get("created_by") or "") for p in pos} - {""})}
    if action_type in {"start_first_batch", "reprioritize"} and model_code:
        params = {"fid": factory_id, "products": [str(model_code)], "since": since or "2000-01-01"}
        wo = [dict(r) for r in (await db.execute(WO_AFTER_SQL, params)).mappings().all()]
        actors = sorted({str(w.get("updated_by") or "") for w in wo} - {""})
        human = sorted(set(actors) - MACHINE_ACTORS)
        return {"status": "adopted" if wo else "not_detected",
                "orders_moved": len(wo), "actors": actors, "human_actors": human,
                "started": sum(1 for w in wo if w.get("actual_start"))}
    return {"status": "no_evidence", "why": f"{action_type} 的回查口径还没定义（不猜）"}


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
        # 只认 verified_human：程序回查与仿真身份写的都算自证，不能进成功率分母
        if str(outcome.get("outcome_quality") or "") != "verified_human":
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
