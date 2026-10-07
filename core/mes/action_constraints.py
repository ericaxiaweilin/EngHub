"""动作约束层：先知道这个厂"现实中哪些动作根本不存在"，再去生成方案。

现在的引擎是"把可能的优化都枚举一遍"（POLICIES 里写死 8 个政策），这条路的问题不是算得慢，
而是它会把厂里根本不能做的事当成候选：暴雨时建议外发、组立线建议临时加设备、
把普通作业员调去顶检测员。用户 10-07 定的路线是两段式 ——
先用**显式领域约束**把 AI 关进现实边界，再让真实运行数据在"能做的事情"里挖哪条最有效。
这个模块是第一段，它只回答三件事：

1. 这个动作在当前厂区/线/状态下是 `forbidden`（有声明说不行）、`allowed_bounded`（能做，但有上限）、
   还是 `undeclared`（厂里没人声明过这条规则）；
2. 判定吃了哪些表的哪些行（`checked`）—— 没数据必须说成没数据，不能把"没说"当成"允许"或"禁止"；
3. 每条 `undeclared` 给出**要填哪一列才生效**，让规则缺口变成可执行的补数据任务。

诚实的前提：本厂资格约束目前基本没有落库 —— `station_capacity.required_skills` 38 行全空、
`hr_employees.certifications` 只有 3 行、`line_profiles.cannot_make_models` 3 条线全是 `{}`、
加班上限/外发政策整张表都没有。所以现在能判死的只有工艺能力，其余一律回 `undeclared`，
并把它们列进 `constraint_gaps`。这一步的价值正是把这些洞摊开，而不是假装规则在。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 动作词表是封闭的：引擎只会产出这几个动作，约束层也只判这几个。
# 新增动作必须同时在这里登记，否则它进不了候选集（不做"所有理论动作枚举一遍"）。
ACTIONS: Dict[str, str] = {
    "reroute_line": "把这单改派到工艺上同样能做的另一条线",
    "parallel_line": "开并联线（同线组共享合并产能）",
    "cross_line_transfer": "跨线调人（需要技能/资格匹配）",
    "add_overtime": "加班补工时",
    "extra_crew": "加班加人（外部补人进班组）",
    "expedite_purchase": "压瓶颈件提前期 / 加急采购",
    "split_release": "分批开工（先出现料能做的部分）",
    "reprioritize": "调整工单先后（这台机往后放或往前插）",
    "partial_delivery": "与客户协商部分交付",
    "subcontract": "外发 / 外协",
}

LINES_SQL = text("""
    SELECT line_code, line_group, crew_size, units_per_day, group_units_per_day,
           can_make_models::text AS can_models, cannot_make_models::text AS cannot_models,
           default_model, parallel_lines
    FROM line_profiles WHERE factory_id = :fid AND is_active = true ORDER BY line_code
""")

# 资格/技能的真落点：工位要什么技能、人有什么技能、证书有没有过期
STATION_SKILLS_SQL = text("""
    -- station_capacity.station_id 存的其实是工位编码（不是 UUID），这里按它的实际含义取名
    SELECT station_id AS station_code, required_skills::text AS required_skills
    FROM station_capacity WHERE factory_id = :fid
""")

EMPLOYEE_SKILLS_SQL = text("""
    SELECT count(*) AS n,
           count(*) FILTER (WHERE COALESCE(e.skill_level, '') <> '') AS with_skill_level,
           count(*) FILTER (WHERE COALESCE(e.certifications::text, '') NOT IN ('', '[]', 'null')) AS with_certs,
           count(DISTINCT e.station) AS stations_covered
    FROM hr_employees e WHERE e.factory_id = :fid AND COALESCE(e.status, 'active') = 'active'
""")

EMPLOYEE_CERT_SQL = text("""
    SELECT count(*) AS bindings,
           count(*) FILTER (WHERE s.expiry_date IS NOT NULL) AS with_expiry,
           count(*) FILTER (WHERE s.expiry_date IS NOT NULL AND s.expiry_date < CURRENT_DATE) AS expired
    FROM hr_employee_skills s
""")

# 加急这个动作的效果取决于"原来几天" —— 提前期若是铺的默认值，加急到 N 天无从校验
LEAD_FLAGS_SQL = text("""
    WITH g AS (SELECT make_or_buy, material_type, count(*) AS n,
                      count(DISTINCT lead_time_days) AS distinct_values,
                      mode() WITHIN GROUP (ORDER BY lead_time_days) AS modal_days
               FROM materials WHERE factory_id = :fid AND lead_time_days IS NOT NULL GROUP BY 1,2)
    SELECT count(*) AS buy_rows,
           count(*) FILTER (WHERE g.n >= 50 AND g.distinct_values <= 15
                              AND m.lead_time_days = g.modal_days) AS unverified
    FROM materials m JOIN g ON g.make_or_buy = m.make_or_buy AND g.material_type = m.material_type
    WHERE m.factory_id = :fid AND m.make_or_buy = '外购'
""")

# 规则缺口 → 该谁填哪一列。写不出来的规则不算规则，所以每条都指到具体列/具体行数。
GAP_OWNER = {
    "line_profiles.cannot_make_models": "IE / 工艺（写明每条线不能做什么，别只靠正向白名单）",
    "station_capacity.required_skills": "IE / 工艺（每个工位需要哪些技能与等级）",
    "hr_employees.certifications": "HR（人的资格与证书，跨线调人要按这个匹配）",
    "overtime_policy.max_hours_per_day": "厂里 /  labour 规则（加班上限，没有上限就别自动建议加班）",
    "outsourcing_policy.allowed": "采购 / 厂里（哪些工段允许外发、什么条件下不允许）",
    "delivery_policy.partial_shipment_allowed": "销售 / 客户协议（部分交付算不算违约）",
    "line_profiles.group_units_per_day": "IE / 生产（线组合并产能，并联只能用这个上限）",
    "materials.lead_time_days": "采购（按料号量实际到货天数，先量引擎点名的那一档）",
}


def _tokens(arr_text: Any) -> List[str]:
    s = str(arr_text or "").strip("{}")
    return [t.strip().strip('"') for t in s.split(",") if t.strip().strip('"')]


def _verdict(action: str, verdict: str, why: str, *, checked: Dict[str, Any],
             bound: Optional[Dict[str, Any]] = None, gap: Optional[str] = None,
             observed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = {"action": action, "meaning": ACTIONS.get(action, action), "verdict": verdict,
           "why": why, "checked": checked}
    if bound:
        out["bound"] = bound
    if observed:
        # 现场观测不等于声明：规则没落库时这里给"厂里实际怎么做过的数"，
        # 引擎可以引用它排序候选，但不许拿它当 binding 边界。
        out["observed"] = observed
    if gap:
        out["gap_to_make_it_binding"] = gap
        out["gap_owner"] = GAP_OWNER.get(gap)
    return out


def _opt_float(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _observed_attendance(att: Dict[str, Any], *, action: str,
                         cap_hours: Optional[float] = None) -> Dict[str, Any]:
    """把到岗普查里跟这个动作有关的读数挑出来；查不到就明说查不到，不填假设值。"""
    if not att or not att.get("available"):
        return {"available": False,
                "why": (att or {}).get("empty_reason")
                       or "attendance 普查没跑成（不是没有加班，是没读到数）"}
    if action == "add_overtime":
        ot = att.get("overtime") or {}
        extra = ot.get("max_observed_extra_hours")
        block = {"window": att.get("window"), "person_days": ot.get("observed_person_days"),
                 "max_extra_hours": extra, "reading": ot.get("reading"),
                 "norm_hours": (att.get("shift_norm") or {}).get("norm_hours")}
        if cap_hours is not None and extra is not None:
            block["respects_declared_cap"] = float(extra) <= float(cap_hours)
            block["cap_hours"] = float(cap_hours)
        return block
    if action == "extra_crew":
        ds = att.get("double_shift") or {}
        ab = att.get("absence") or {}
        return {"window": att.get("window"), "double_shift_person_days": ds.get("observed_person_days"),
                "top_sections": ds.get("top_sections"), "reading": ds.get("reading"),
                "overall_absence_rate": ab.get("overall_rate"),
                "worst_sections": [{"section": s["section"], "absence_rate": s["absence_rate"]}
                                   for s in (ab.get("by_section") or [])[:4]]}
    if action == "cross_line_transfer":
        return dict(att.get("observability") or {}, window=att.get("window"))
    return {"available": True, "window": att.get("window"),
            "why": f"{action} 没有对应的到岗观测口径（attendance 只记出勤/班时）"}


def policy_actions(pol: Dict[str, Any]) -> List[str]:
    """把引擎的一个政策位翻译成它对现实动了什么动作 —— 约束层只能判动作，判不了字典。"""
    acts = ["reprioritize"]
    if int(pol.get("parallel_lines") or 1) > 1:
        acts.append("parallel_line")
    if float(pol.get("crew_bonus") or 0) > 0:
        acts += ["extra_crew", "add_overtime"]
    if pol.get("expedite_lead_days") is not None:
        acts.append("expedite_purchase")
    if pol.get("line_staffing"):
        acts.append("reroute_line")
    if bool(pol.get("allow_partial", True)):
        acts.append("split_release")
    if pol.get("subcontract"):
        acts.append("subcontract")
    return acts


CARD_COVERAGE_SQL = text("""
    SELECT detail->'action_coverage' AS cov, created_at
    FROM simulation_scorecards
    WHERE factory_id = :fid AND jsonb_exists(detail, 'action_coverage')
    ORDER BY created_at DESC LIMIT 1
""")

EXEC_30D_SQL = text("""
    SELECT action, count(*) AS n FROM execution_events
    WHERE factory_id = :fid AND occurred_at >= NOW() - INTERVAL '30 days'
    GROUP BY action
""")


def _usage_reading(considered: Optional[int], recorded: int,
                  coverage_known: bool) -> str:
    """把"现场没做"和"引擎没提"分开说 —— 这两个的下一步动作完全不同。"""
    if not coverage_known:
        return (f"近 30 天现场记了 {recorded} 次；引擎侧没有上一张记分卡，"
                "覆盖度无从判断（读成 0 次是假话）")
    n = int(considered or 0)
    if n and not recorded:
        return f"引擎这轮的政策网格想过 {n} 次，现场 30 天一次都没记 —— 要么没做，要么做了没记"
    if not n and recorded:
        return f"现场记了 {recorded} 次，但引擎这轮没把它列进候选（政策网格缺这个杠杆）"
    if n and recorded:
        return f"引擎想过 {n} 次、现场记了 {recorded} 次 —— 这个动作有来有回"
    return "引擎没提、现场没记：这条动作现在是空的"


async def _grid_usage(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """上一张记分卡的动作覆盖度 + 近 30 天执行台账计数（都取不到时返回空，不假装是 0）。"""
    cov: Dict[str, Any] = {}
    at = None
    row = (await db.execute(CARD_COVERAGE_SQL, {"fid": factory_id})).mappings().first()
    if row:
        at = str(row["created_at"])
        raw = row["cov"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw or "{}")
            except (TypeError, ValueError):
                raw = {}
        cov = dict(raw or {})
    execs = {str(r["action"]): int(r["n"] or 0) for r in
             (await db.execute(EXEC_30D_SQL, {"fid": factory_id})).mappings().all()}
    return {"coverage": cov, "coverage_known": bool(cov), "card_at": at,
            "executions_30d": execs}


async def action_constraints(db: AsyncSession, factory_id: str,
                             model: Optional[str] = None,
                             line_code: Optional[str] = None,
                             state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """对每个动作给判定。`state` 是现场状况（例如 {"weather":"storm","absent_share":0.28}），
    只用于说明"在什么条件下规则被触发"，不参与编数字 —— 没有声明的条件一律 undeclared。
    """
    state = state or {}
    lines = [dict(r) for r in (await db.execute(LINES_SQL, {"fid": factory_id})).mappings().all()]
    stations = [dict(r) for r in (await db.execute(STATION_SKILLS_SQL, {"fid": factory_id})).mappings().all()]
    emp = dict(((await db.execute(EMPLOYEE_SKILLS_SQL, {"fid": factory_id})).mappings().first() or {}))
    cert = dict(((await db.execute(EMPLOYEE_CERT_SQL, {})).mappings().first() or {}))
    lead = dict(((await db.execute(LEAD_FLAGS_SQL, {"fid": factory_id})).mappings().first() or {}))

    line = next((l for l in lines if str(l["line_code"]) == str(line_code)), None) if line_code else None
    # 已经落库的厂规优先于"这列没数据"：人只要声明过（declared/validated），
    # 动作就按声明变成 forbidden / allowed_bounded，不再算 undeclared。
    try:
        from core.mes.factory_rules import binding_rules

        declared = await binding_rules(db, factory_id)
    except Exception:  # noqa: BLE001  规则表查不动时退回 undeclared，不能把"没读到"当成"没规则"
        declared = {}
    try:
        from core.mes.data_evidence import attendance_evidence

        att = await attendance_evidence(db, factory_id)
    except Exception:  # noqa: BLE001  普查查不动时报"没读到数"，不许退化成"厂里没加过班"
        att = {}
    try:
        usage = await _grid_usage(db, factory_id)
    except Exception:  # noqa: BLE001  记分卡读不动时不写覆盖度，也不写 0
        usage = {"coverage": {}, "coverage_known": False, "card_at": None, "executions_30d": {}}
    out: List[Dict[str, Any]] = []
    gaps: Dict[str, Dict[str, Any]] = {}

    def add_gap(col: str, affects: List[str], evidence: Any) -> None:
        gaps.setdefault(col, {"column": col, "owner": GAP_OWNER.get(col), "actions": set(),
                              "evidence": evidence})["actions"].update(affects)

    # 1) 改线：唯一现在就能判死的动作 —— 工艺能力有双向声明可依
    if model:
        alternates = [l for l in lines
                      if model in _tokens(l["can_models"]) and model not in _tokens(l["cannot_models"])
                      and (not line_code or str(l["line_code"]) != str(line_code))]
        declared_cannot = [l["line_code"] for l in lines if model in _tokens(l["cannot_models"])]
        checked = {"lines": len(lines), "model": model, "declared_cannot_on": declared_cannot}
        if not alternates:
            out.append(_verdict("reroute_line", "forbidden",
                                f"没有任何一条线声明能做 {model}（负向声明命中 {len(declared_cannot)} 条线）"
                                "→ 现实中不存在改派这个动作，只能等或减载",
                                checked=checked))
        else:
            out.append(_verdict("reroute_line", "allowed_bounded",
                                f"可改派到 {len(alternates)} 条已声明能做 {model} 的线",
                                checked=checked,
                                bound={"max_alternative_lines": len(alternates),
                                       "lines": [l["line_code"] for l in alternates]}))
    else:
        out.append(_verdict("reroute_line", "no_target", "没给机种，无法核对工艺能力", checked={"lines": len(lines)}))

    # 2) 并联线：受"线组是否声明过合并产能"约束（合并 700 不是 800 那一条）
    if line is not None:
        group = str(line.get("line_group") or "")
        members = [l for l in lines if str(l.get("line_group") or "") == group] if group else []
        declared_group_cap = (members and float(members[0].get("group_units_per_day") or 0) > 0)
        checked = {"line": line["line_code"], "line_group": group or None,
                   "members": len(members), "group_capacity_declared": bool(declared_group_cap)}
        if not group or not declared_group_cap:
            out.append(_verdict("parallel_line", "undeclared",
                                "这条线没有线组、或组内合并产能没声明 —— 并联只能按单线乘出来，"
                                "那是凭空造富余（实测合并 700 台而不是 800）",
                                checked=checked, gap="line_profiles.group_units_per_day"))
            add_gap("line_profiles.group_units_per_day", ["parallel_line"], checked)
        else:
            out.append(_verdict("parallel_line", "allowed_bounded",
                                f"组 {group} 声明合并产能 {float(members[0]['group_units_per_day']):g} 台/天，"
                                "并联只能用这个上限",
                                checked=checked,
                                bound={"group_declared_units_per_day": float(members[0]["group_units_per_day"]),
                                       "max_lines": len(members)}))
    else:
        out.append(_verdict("parallel_line", "no_target", "没给线，无法核对线组与合并产能", checked={"lines": len(lines)}))

    # 3) 跨线调人：要看工位需要技能 + 人的资格。工位需求 38 行全空 → 现在无法判定
    filled = sum(1 for s in stations if _tokens(s.get("required_skills")))
    checked = {"station_capacity_rows": len(stations), "with_required_skills": filled,
               "active_employees": int(emp.get("n") or 0),
               "employees_with_skill_level": int(emp.get("with_skill_level") or 0),
               "employees_with_certifications": int(emp.get("with_certs") or 0),
               "skill_bindings": int(cert.get("bindings") or 0),
               "certifications_expired": int(cert.get("expired") or 0)}
    if filled == 0:
        out.append(_verdict("cross_line_transfer", "undeclared",
                            f"{len(stations)} 行工位产能记录里 0 行写了 required_skills → "
                            "系统现在无法判断「谁能顶哪个工位」，任何调人建议都没有依据；"
                            f"人的技能有 {emp.get('with_skill_level') or 0} 人填了等级，但资格证书只有 "
                            f"{emp.get('with_certs') or 0} 行",
                            checked=checked,
                            observed=_observed_attendance(att, action="cross_line_transfer"),
                            gap="station_capacity.required_skills"))
        add_gap("station_capacity.required_skills", ["cross_line_transfer"], checked)
    else:
        out.append(_verdict("cross_line_transfer", "allowed_bounded",
                            f"{filled}/{len(stations)} 个工位声明了技能需求，可按等级匹配筛人",
                            checked=checked, bound={"stations_with_requirements": filled},
                            observed=_observed_attendance(att, action="cross_line_transfer")))

    # 4) 加班：没有任何加班上限落库 → 不能自动推荐，只能等人写规则
    ot_cap = ((declared.get("add_overtime") or {}).get("params") or {}).get("max_hours_per_day")
    out.append(_verdict("add_overtime", "undeclared",
                        "厂里没有加班上限这张表/这一列（hours_per_day 是班时，不是加班上限）→ "
                        "系统不能自动建议加班多少小时",
                        checked={"line_profiles": len(lines), "overtime_policy_rows": 0},
                        observed=_observed_attendance(att, action="add_overtime",
                                                      cap_hours=_opt_float(ot_cap)),
                        gap="overtime_policy.max_hours_per_day"))
    add_gap("overtime_policy.max_hours_per_day", ["add_overtime"], {"overtime_policy_rows": 0})

    # 5) 加人：物理上人多不等于产出高 —— 产能绑在工位与线节拍上
    crew = float((line or {}).get("crew_size") or 0)
    per_day = float((line or {}).get("units_per_day") or 0)
    out.append(_verdict("extra_crew", "allowed_bounded" if line is not None else "no_target",
                        ("加人只能把人折进班组，日产能仍取 min(线声明台/天, 班组按 IE 工时做得完的台/天)。"
                         f"这条线声明 {per_day:g} 台/天配 {crew:g} 人，人均要占到 {per_day / crew if crew else 0:.3g} 台/天"
                         " —— 人多不等于产出高，除非瓶颈在工时那一侧")
                        if line is not None else "没给线",
                        checked={"line": (line or {}).get("line_code"), "crew_size": crew,
                                 "declared_units_per_day": per_day},
                        observed=_observed_attendance(att, action="extra_crew")))

    # 6) 加急：目标值取决于原提前期有没有实测；台账是铺的默认值时"加急到 N 天"无从校验
    buy_rows = int(lead.get("buy_rows") or 0)
    unver = int(lead.get("unverified") or 0)
    checked = {"buy_material_rows": buy_rows, "unverified_default_rows": unver}
    if buy_rows and unver / max(1, buy_rows) > 0.5:
        out.append(_verdict("expedite_purchase", "undeclared_effect",
                            f"{unver}/{buy_rows} 个外购料号的基准提前期是按类别铺的默认值 → "
                            "可以把件催到 N 天，但「催回来几天」这个数没有可校验的基准；"
                            "本厂实测到货中位 54 天 vs 台账均值 9.9 天，方向还可能是反的",
                            checked=checked, gap="materials.lead_time_days"))
        add_gap("materials.lead_time_days", ["expedite_purchase"], checked)
    else:
        out.append(_verdict("expedite_purchase", "allowed_bounded",
                           "基准提前期多数有实测支撑，加急效果可按天数核对", checked=checked))

    # 7) 外发：厂里从没声明过哪些工段允许 → 必须回 undeclared，不能默认允许（暴雨外发就是这条）
    out.append(_verdict("subcontract", "undeclared",
                       "系统里没有任何'哪些工段允许外发/什么条件下禁止'的落库数据（无外协政策表，"
                       "chat 侧只有一个会话开关 accept_subcontracting）→ 引擎不得把外发列入候选",
                       checked={"outsourcing_policy_rows": 0}, gap="outsourcing_policy.allowed"))
    add_gap("outsourcing_policy.allowed", ["subcontract"], {"outsourcing_policy_rows": 0})

    # 8/9/10) 计划层面的动作：不需要现场数据，但要标明"改的是承诺，不是产能"
    out.append(_verdict("split_release", "allowed_bounded",
                        "分批开工是投放策略，不改产能；多一批就多一次换型（系统里唯一换型数是 APS 默认 300 秒）",
                        checked={"changeover_hours_source": "SIM_CHANGEOVER_HOURS"}))
    out.append(_verdict("reprioritize", "allowed_bounded",
                        "改的是先后，不是总产能 —— 受益一台必然推迟另一台，必须成对报出代价",
                        checked={"open_work_orders_not_counted": True}))
    out.append(_verdict("partial_delivery", "undeclared",
                        "没有客户协议/部分交付是否构成违约的落库依据 → 只能当建议，不能当可执行动作",
                        checked={"delivery_policy_rows": 0}, gap="delivery_policy.partial_shipment_allowed"))
    add_gap("delivery_policy.partial_shipment_allowed", ["partial_delivery"], {"delivery_policy_rows": 0})

    override = {"forbidden": "forbidden", "allowed": "allowed_bounded", "bounded": "allowed_bounded"}
    for o in out:
        name = str(o["action"])
        rule = declared.get(name) or next((v for k, v in declared.items()
                                           if str(k).startswith(name + ":")), None)
        if not rule:
            continue
        o["verdict_before_rule"] = o["verdict"]
        o["verdict"] = override.get(str(rule.get("verdict")), o["verdict"])
        o["why"] = (f"按厂里声明的规则判定：{rule.get('statement') or ''}"
                    f"（来源 {rule.get('source')}，状态 {rule.get('status')}）")
        o["binding_rule"] = {k: rule.get(k) for k in ("subject", "verdict", "status", "source", "params")}
        for gap in list(gaps.values()):
            if name in gap["actions"]:
                gap["actions"].discard(name)
                gap["resolved_by_rule"] = rule.get("subject")

    counts: Dict[str, int] = {}
    for o in out:
        counts[o["verdict"]] = counts.get(o["verdict"], 0) + 1
        name = str(o["action"])
        cov = (usage["coverage"].get(name) or {})
        rec = int(usage["executions_30d"].get(name) or 0)
        o["usage"] = {"considered_last_grid": (int(cov.get("times_considered") or 0)
                                              if usage["coverage_known"] else None),
                      "grid_policies": cov.get("policies") or [],
                      "grid_scenarios": cov.get("scenarios") or [],
                      "recorded_executions_30d": rec,
                      "reading": _usage_reading(cov.get("times_considered"), rec,
                                                usage["coverage_known"])}
    return {
        "factory_id": factory_id, "model": model, "line": line_code, "state": state,
        "generated": len(out), "of_candidate_actions": len(ACTIONS),
        "verdict_counts": counts,
        "grid_usage_basis": {"card_at": usage["card_at"],
                             "coverage_known": usage["coverage_known"],
                             "note": ("considered_last_grid 取自**最近一张带覆盖度的记分卡**"
                                      f"（{usage['card_at'] or '无'}）的政策×天气网格，含没被选中的政策；"
                                      "recorded_executions_30d 来自 execution_events。"
                                      "两边都是 0 才叫「这动作没人碰过」"),
                             "actions_in_grid": sorted(usage["coverage"].keys())},
        "actions": out,
        "declared_rules_applied": sorted(str(v.get("subject")) for v in declared.values()),
        "constraint_gaps": sorted(
            [{"column": g["column"], "owner": g["owner"], "actions": sorted(g["actions"]),
              "evidence": g["evidence"],
              **({"resolved_by_rule": g["resolved_by_rule"]} if g.get("resolved_by_rule") else {})}
             for g in gaps.values() if g["actions"]],
            key=lambda x: x["column"]),
        "attendance_observed": ({
            "window": att.get("window"), "checked": att.get("checked"),
            "shift_norm": att.get("shift_norm"), "overtime": att.get("overtime"),
            "double_shift": att.get("double_shift"),
            "absence": {k: v for k, v in (att.get("absence") or {}).items() if k != "by_section"},
            "sections": (att.get("absence") or {}).get("by_section"),
            "observability": att.get("observability"), "basis": att.get("basis"),
        } if att.get("available") else {
            "available": False,
            "why": att.get("empty_reason") or "到岗普查没跑成（不是厂里没有出勤）",
        }),
        "rule": ("forbidden=有声明说不行；allowed_bounded=能做但上限来自落库数据；"
                 "undeclared=厂里没人写过这条规则 —— 一律不进候选推荐，并点名要填哪一列。"
                 "规则负责'不能胡来'，数据只在能做的事情里比较哪个最有效。"),
    }
