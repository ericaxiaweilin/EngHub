"""多目标权衡评估：帕累托前沿 + 最小化最大后悔值，而不是把分数刷到最高。

工厂是取舍，不是考试。单一加权分有两个已被证明的坏行为：

1. **刷分**：把某一维推到极端就能拿高分 —— 例如"这单干脆不开工"能让成本和闲置都最好看，
   但工厂不是这么运作的。所以任何"通过不做来变好"的解必须被硬淘汰（产量不达标就不入围）。
2. **互相掩盖**：交付延 20 天 + 人力爆满，可以被"物料成本低"补回总分，看数字看不出问题。
   所以推荐规则不用加权和，用 **min-max regret**：在所有可行解里选"最大后悔最小"的那个 ——
   它不会为了一个维度牺牲另一个维度到离谱，天然偏平衡。

同时记录前沿（不被支配的解集）和被支配解，让"为什么选它、放弃了什么"能被复核，
而不是给一个没人能挑战的数字。假设/借用依据占比也进目标向量：靠借来的数据跑出来的漂亮解
要看得见它是借来的。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple, Union

# 方向：max 越大越好，min 越小越好
# 只有这五项是"政策能改变"的目标：交期达成与产量都是硬约束（达标就恒定，比不出东西），
# 依据可信度是模型属性（换政策不会变）—— 它们进约束/标注，不进目标向量。
DIRECTIONS = {
    "labor_cost_usd": "min",
    "expedite_cost_usd": "min",       # 加急/插单的对价
    "load_band_gap": "min",           # 离人力健康负载区间的偏离（养闲和超载都要付）
    "line_activation_cost_usd": "min",  # 开第二条线的代价 —— 没有它，"多开线"就是免费的
    "days_late_worst": "min",         # 连续延误天数：0/1 准点率会饱和，延 1 天和延 20 天不该同重
}

# 反 Goodhart 硬门槛：达不到就不参与推荐（不是扣分，是淘汰）
MIN_THROUGHPUT_RATIO = float(0.95)
# 交期是合同约束，不是可牺牲的评分项：延期的解不许靠"成本低"把分补回来。
# 只有在该场景根本没有任何准点解时，才退而比较全部并在结果里标 no_feasible_solution。
ON_TIME_REQUIRED = float(os.getenv("PARETO_ON_TIME_REQUIRED", "1.0"))
# 借来/假设的依据占比超过这个值的解必须标出来（可以进前沿，但不能当推荐）
ASSUMPTION_SHARE_LIMIT = 0.5
# "插单"准点不是产能，是把已经答应该做的活往后推 —— 默认不许靠它宣布方案可行。
# 放开需要人工确认挪哪些单，所以是个显式开关，不是评分项。
ALLOW_QUEUE_JUMPING = os.getenv("PARETO_ALLOW_QUEUE_JUMPING", "0") == "1"
# 只在"整班守着这条线"的前提下成立的量：当目标会让引擎花钱去买加急，代价是估出来的、
# 收益也是估出来的。降级为报告项，不参与择优（要真算就得先有停工待料的实际工时制度）。
REPORT_ONLY = ("standby_person_days",)


# 后悔向量的固定顺序：跨场景比较必须同长同序，否则长度不同的元组字典序没有意义
FIXED_ORDER = tuple(k for k in DIRECTIONS if k not in ("standby_person_days",))


def _dir(key: str) -> str:
    direction = DIRECTIONS.get(key)
    if direction is None:
        raise KeyError(f"目标 {key!r} 没声明方向（DIRECTIONS 里没有这一项）——"
                       f"不能默认按 max 处理，那会把越小越好的目标反过来选")
    return direction


def _value(sol: Dict[str, Any], key: str) -> float:
    return float((sol.get("objectives") or {}).get(key) or 0.0)


def dominates(a: Dict[str, Any], b: Dict[str, Any], keys: List[str]) -> bool:
    """a 支配 b：a 在每个目标上都不比 b 差，且至少一个严格更好。"""
    better_or_equal, strictly_better = True, False
    for k in keys:
        av, bv = _value(a, k), _value(b, k)
        if _dir(k) == "max":
            if av < bv:
                better_or_equal = False
            if av > bv:
                strictly_better = True
        else:
            if av > bv:
                better_or_equal = False
            if av < bv:
                strictly_better = True
    return better_or_equal and strictly_better


def feasible(sol: Dict[str, Any], demand_units: float,
             ignore_deadline: bool = False) -> Tuple[bool, Optional[str]]:
    if sol.get("displaces_committed_work") and not ALLOW_QUEUE_JUMPING:
        return False, ("这条政策靠把已经在排的活往后挪来宣布准点：那不是产能，是抢产能。"
                       "默认不进比较（要放开：PARETO_ALLOW_QUEUE_JUMPING=1，"
                       "并由计划员确认可以挪哪些单）")
    made = _value(sol, "throughput_units")
    if demand_units > 0 and made < demand_units * MIN_THROUGHPUT_RATIO:
        return False, (f"只做出来 {made:g}/{demand_units:g} 台（<{MIN_THROUGHPUT_RATIO:.0%}）—— "
                       f"省下的成本是不干活省的，不参与比较")
    # 交期一旦作为硬约束，"准点率/延误天数"就不能再当比较维度：存活解在这两维必然全同，
    # 留着只会让 regret 算出 0 分并把有效维度稀释掉。它们仍作为事实报出，只是不参与择优。
    if not ignore_deadline and _value(sol, "on_time_rate") < ON_TIME_REQUIRED:
        return False, ("误期：交期是合同约束，不能用低成本/低闲置换回来"
                       f"（准点率 {_value(sol, 'on_time_rate'):.2f} < {ON_TIME_REQUIRED:.2f}）")
    return True, None


def pareto_front(solutions: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    front = []
    for a in solutions:
        if not any(dominates(b, a, keys) for b in solutions if b is not a):
            front.append(a)
    # 目标向量一模一样的政策算同一个解：留第一个，别名并进去
    uniq: List[Dict[str, Any]] = []
    seen: Dict[Tuple, Dict[str, Any]] = {}
    for s in front:
        sig = tuple(round(_value(s, k), 4) for k in keys)
        if sig in seen:
            seen[sig].setdefault("also_same_as", []).append(s.get("name"))
            continue
        seen[sig] = s
        uniq.append(s)
    return uniq


def regret_matrix(solutions: List[Dict[str, Any]], keys: List[str]) -> Dict[str, Dict[str, float]]:
    """每个解在每目标上的后悔值 = 与"这个目标上最好的解"差多少（按比例归一）。"""
    out: Dict[str, Dict[str, float]] = {}
    for k in keys:
        vals = [_value(s, k) for s in solutions]
        if not vals:
            continue
        best = max(vals) if _dir(k) == "max" else min(vals)
        worst = min(vals) if _dir(k) == "max" else max(vals)
        span = abs(best - worst)
        for s in solutions:
            v = _value(s, k)
            gap = (abs(best - v) / span) if span > 0 else 0.0
            out.setdefault(str(s["id"]), {})[k] = round(gap, 4)
    return out


def assumption_share(sol: Dict[str, Any]) -> float:
    """这个解有多少时间是建立在借来的路线/反推的工时上的。"""
    labels = (sol.get("evidence") or {})
    total = sum(int(v or 0) for v in labels.values()) or 0
    if not total:
        return 0.0
    weak = sum(int(labels.get(k) or 0) for k in
               ("borrowed_route_from_family", "takt_from_line_capacity",
                "line_inferred_by_family_name", "assumed_ie_hours"))
    return round(weak / total, 4)


def objective_spread(solutions: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    """哪一维全场同值 = 这一维白算，通常是场景标得不合理（上一轮 12 个政策全部准点 1.00 就是这个）。"""
    out = []
    for k in keys:
        vals = [_value(s, k) for s in solutions]
        if not vals:
            continue
        out.append({"objective": k, "min": round(min(vals), 4), "max": round(max(vals), 4),
                    "distinct": len(set(round(v, 6) for v in vals)),
                    "useless": (max(vals) - min(vals)) < 1e-9})
    return out


def anti_goodhart_check(solutions: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    """自体检：某个维度能被单调"刷好"而别的维度没人付账时，这个目标就是可被过拟合的。"""
    warnings: List[Dict[str, Any]] = []
    if not solutions:
        return warnings
    for k in keys:
        best = max(solutions, key=lambda s: _value(s, k) if _dir(k) == "max"
                   else -_value(s, k))
        worst_on_others = sum(
            1 for other in keys if other != k and
            _value(best, other) == (
                min(_value(s, other) for s in solutions) if _dir(other) == "max"
                else max(_value(s, other) for s in solutions)))
        if worst_on_others >= max(1, (len(keys) - 1) // 3):
            warnings.append({
                "objective": k, "best_solution": best.get("name"),
                "worst_on_other_objectives": worst_on_others,
                "meaning": f"{k} 的最优解同时在 {worst_on_others} 个别的目标上全场最差 —— "
                           f"说明这一维可以单独刷，得给它配一条真实代价再进选择。"})
    return warnings


def evaluate_by_scenario(by_scenario: Dict[str, Any],
                         demand_units: Union[float, Dict[str, float]],
                         keys: Optional[List[str]] = None,
                         robust_scenarios: Optional[List[str]] = None) -> Dict[str, Any]:
    """在每个天气场景内部各算一次前沿，再给一个跨场景稳健推荐。

    天气是外生的，把 0.97 和 0.70 的解混进同一个前沿比后悔是错的 ——
    那等于让引擎"选天气"。正确问题：哪种政策在好天到暴雨都能交。
    """
    per_scenario = {}
    for name, block in (by_scenario or {}).items():
        # 每个场景可以带自己标定的批量（virtual_run.auto_tune 按场景调），需求量就按场景取；
        # 没有该场景的值时用全局量，保持老的调用方式不变。
        dm = (demand_units.get(name) if isinstance(demand_units, dict) else demand_units) or 0.0
        per_scenario[name] = evaluate(block.get("solutions") or [], float(dm), keys)
    # 同一政策在各场景的最大后悔，取最差场景做稳健比较（minimax over scenarios）
    if not by_scenario:
        return {"by_scenario": {}, "robust_recommendation": None,
                "selection_rule": "没有解，不编推荐"}
    by_policy: Dict[str, List[Tuple[float, Dict[str, Any]]]] = {}
    # 只按"承诺范围内的场景"选稳健解：标定被放宽到不是厂里真会承诺的交期之后，
    # 那种场景里准点不算本事，拿它当最坏场景会把推荐抬到一个现实中做不到的位置。
    robust_pool = {k: v for k, v in per_scenario.items()
                   if not robust_scenarios or k in robust_scenarios}
    for name, res in robust_pool.items():
        pool = {str(s.get("id")): s for s in (res.get("frontier") or []) + (res.get("dominated") or [])}
        for sol in pool.values():
            reg = sol.get("regret_by_objective") or {}
            # 与场景内选择同一套比法：把后悔值降序排好再比（谁最吃亏先比那一项）。
            # 原来这里是按 FIXED_ORDER 的**字典键序**取元组，而键序第一位是 labor_cost_usd、
            # 交期在最后 —— 于是"加急费多 0.54 档"能压过"延期整格 1.0 档"，
            # 与本文件自己写的「交期是合同约束，不许靠成本低把分补回来」互相打脸。
            # 10-07 实测：三个天气场景里都赢的政策（提前期减半）在稳健推荐里落选，选了现况。
            # 仍按 FIXED_ORDER 取值补齐（死维度占位为 0，向量必须同长 —— 短元组会靠长度赢），
            # 但比的是降序排好的那一份：谁最吃亏先比那一项，键序不再决定谁当选。
            prof = tuple(sorted((float(reg.get(k) or 0.0) for k in FIXED_ORDER), reverse=True))
            if not prof:
                continue      # 没有后悔向量的解不参与稳健比较
            by_policy.setdefault(str(sol.get("name") or sol.get("id")), []).append((sol.get("max_regret"), prof))
    robust = None
    for policy, rows in by_policy.items():
        worst = max(r[1] for r in rows)          # 该政策在最坏场景下的后悔向量
        covered = len(rows) >= len(robust_pool)
        if not covered:
            continue
        if robust is None or worst < robust[1]:
            robust = (policy, worst, rows)
    robust_tied = []
    if robust:
        robust_tied = [p for p, rows in by_policy.items()
                       if p != robust[0] and len(rows) >= len(robust_pool)
                       and max(r[1] for r in rows) == robust[1]]
    # 天气场景有没有真的改变结论：同一政策在各场景的目标向量若一模一样，这一维就没带信息
    sig_by_policy: Dict[str, List[Tuple]] = {}
    for name, res in per_scenario.items():
        for sol in (res.get("frontier") or []) + (res.get("dominated") or []):
            objs = sol.get("objectives") or {}
            sig_by_policy.setdefault(str(sol.get("name") or sol.get("id")), []).append(
                tuple(round(float(objs.get(k) or 0.0), 4) for k in FIXED_ORDER))
    moved = sum(1 for sigs in sig_by_policy.values() if len(set(sigs)) > 1)
    divergence = {
        "policies_compared": len(sig_by_policy), "policies_that_move": moved,
        "note": (f"{moved}/{len(sig_by_policy)} 个政策在不同天气下的结果确实不一样 —— "
                 "场景分开算有信息" if moved else
                 "所有政策在不同天气下的目标向量一模一样：这批单卡的是到货日不是出勤，"
                 "天气这一维目前不携带任何信息（要么模型里出勤还没接到这条路径，要么本来就该如此）"),
    }
    return {
        "scenario_divergence": divergence,
        "by_scenario": {k: {kk: vv for kk, vv in v.items() if kk != "selection_rule"}
                        for k, v in per_scenario.items()},
        "robust_recommendation": None if not robust else {
            "policy": robust[0], "worst_scenario_regret_profile": list(robust[1]),
            "tied_with": robust_tied,
            "tied_note": (f"稳健推荐与 {'、'.join(str(x) for x in robust_tied[:6])} 在最坏场景下的后悔向量完全并列，"
                          f"这一轮分不出高下" if robust_tied else None),
            "why": "该政策在好天/雨季/暴雨三个场景里都有解进入比较，且最坏场景的后悔向量最好；"
                   "选它不是因为它分数最高，而是因为它不赌天气。"},
        "robust_scenario_pool": sorted(robust_pool),
        "diagnostic_only_scenarios": sorted(set(per_scenario) - set(robust_pool)),
        "selection_rule": ("场景内：可行解 → 帕累托前沿 → 后悔向量降序字典序最小（谁最吃亏先比那一项）；"
                           "跨场景：取最坏场景后悔最小的政策（minimax，同一套降序比法），不是平均最好。"
                           "各场景的批量是各自标定的，跨场景比的是场景内归一化之后的后悔向量，"
                           "不是原始美元/天数 —— 所以'标定'只决定这一轮有没有区分度，不改变谁更好。"),
    }


def evaluate(solutions: List[Dict[str, Any]], demand_units: float,
             keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """产出前沿、被淘汰的解、推荐解，以及每步判定的理由（可复核，不给单一总分）。"""
    base_keys = [k for k in (keys or list(DIRECTIONS)) if k not in REPORT_ONLY]
    scored: List[Dict[str, Any]] = []
    notes: List[str] = []
    eliminated: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for sol in solutions:
        ok, why = feasible(sol, demand_units)
        if not ok:
            rejected.append({"id": sol.get("id"), "name": sol.get("name"),
                             "eliminated_for": why})
            continue
        sol = dict(sol)
        sol["assumption_share"] = assumption_share(sol)
        scored.append(sol)
    no_feasible = False
    report_only_comparison = False
    if not scored and solutions:
        # 一个场景里没有任何准点解：退回比较全部（矮子里拔将军），此时延误天数才重新变成目标
        no_feasible = True
        keys = list(dict.fromkeys(base_keys + ["days_late_worst"]))   # 重键会让同一维算两次后悔
        notes.append("本场景没有准点解：改按延误天数择优，并明确标注这是降级比较")
        for sol in solutions:
            ok, _ = feasible(sol, demand_units, ignore_deadline=True)
            if not ok:
                continue
            s2 = dict(sol)
            s2["assumption_share"] = assumption_share(s2)
            scored.append(s2)
        if not scored:
            # 连"忽略交期"都过不了产量底线：这些解只摆出来对比，不进择优
            for sol in solutions:
                s2 = dict(sol)
                s2["assumption_share"] = assumption_share(s2)
                scored.append(s2)
            report_only_comparison = True
            notes.append("没有任何解达到产量底线：以下只是把政策摆出来，不宣称哪个更好")
        eliminated = rejected
        rejected = []

    keys = locals().get("keys") or base_keys
    # 全场同值的维度没有区分度：留在向量里会让 regret/self_check 说胡话（n=1 时会把每个维度
    # 都报成"可被刷"）。挑出来并从比较用的 keys 里摘掉，但在结果里明说摘了哪些。
    spread = objective_spread(scored, keys + ["on_time_rate", "throughput_units"])
    dead = [s["objective"] for s in spread if s["useless"]]
    # 硬约束吸收掉的维度：准点与产量达标后必然恒定，明确点名而不是默默比
    absorbed = [k for k in ("on_time_rate", "throughput_units", "days_late_worst") if k in dead]
    if dead:
        notes.append(f"{len(dead)} 个维度全场同值，不参与后悔比较：{'、'.join(dead)}"
                     f"（通常说明场景标定太松/太紧，或政策网格没有覆盖到能动这一维的手段）")
        keys = [k for k in keys if k not in dead] or keys
    jumped = [r for r in rejected if "抢产能" in str(r.get("eliminated_for") or "")
              or "往后挪" in str(r.get("eliminated_for") or "")]
    if jumped:
        notes.append(f"{len(jumped)} 条政策只有靠插单（抢占已在排的活）才准点，已排除在比较外："
                     f"{'、'.join(str(j.get('name')) for j in jumped[:4])}。"
                     f"真要采纳得由人确认挪哪些单 —— 本轮推荐不含它。")
    if len(scored) <= 2:
        notes.append(f"可行解只剩 {len(scored)} 个：前沿/后悔在这里没有意义，"
                     f"结论只是「这套组合可行、别的都不行」，不要当成择优结果")
    front = pareto_front(scored, keys)
    # 后悔要在**全部可行解**上算，不是只在前沿内算：只算前沿会让被支配解拿到空后悔向量，
    # 空向量在字典序里"最小"，稳健推荐就会挑一个最差解（实测踩过）。
    regrets = regret_matrix(scored, keys)
    for sol in scored:
        r = regrets.get(str(sol["id"]), {})
        sol["max_regret"] = round(max(r.values()), 4) if r else None
        sol["regret_by_objective"] = r
        sol["on_pareto_front"] = any(s["id"] == sol["id"] for s in front)

    # 推荐：先看前沿里依据够扎实的；若前沿解全靠借用/假设数据撑起来，
    # 宁可退回"可靠依据的解里较好的那个"并明说它不在前沿上 —— 借来的路线不算赢。
    solid = [s for s in scored if s.get("assumption_share", 0) <= ASSUMPTION_SHARE_LIMIT]
    eligible = [s for s in front if s in solid]
    out_of_frontier = False
    pool = eligible
    if not pool and solid:
        pool, out_of_frontier = solid, True
        notes.append("帕累托前沿上的解全靠借用路线/反推工时撑着，不配当结论："
                     "已退到依据可靠的解里选（推荐解不在前沿上，这点会写进结果）")
    pool = pool or front or scored
    recommended = None
    tied_with: List[Any] = []

    def profile(s):
        # 最大后悔并列时不能靠顺序瞎选：把每个解的后悔从最坏到最好排成向量比字典序，
        # 等于"先保证最坏的那维别太糟，再看次坏的" —— 平衡解要一整串都好，不是只一项好。
        r = [(s.get("regret_by_objective") or {}).get(k) or 0.0 for k in FIXED_ORDER]
        return (s.get("max_regret") is None, sorted(r, reverse=True))
    if pool:
        recommended = min(pool, key=profile)
        # 排序后的后悔向量会丢"后悔长在哪一维"，所以两个各让一头的解可能完全并列。
        # 并列不能靠列表顺序假装选出来了：如实报"这一轮分不出高下"，让人去定优先级。
        tied_with = [s.get("name") for s in pool if s is not recommended and profile(s) == profile(recommended)]
        if tied_with:
            notes.append(f"推荐解与 {len(tied_with)} 个政策的后悔向量每一位都相同（"
                         f"{'、'.join(str(x) for x in tied_with[:6])}）："
                         f"这一轮只筛掉了明显更差的，没说哪个最好。要分高下得给目标定优先级，"
                         f"或补一档真能改变成本的政策 —— 列出的先后不代表排序。")
    if recommended is not None and recommended.get("assumption_share", 0) > ASSUMPTION_SHARE_LIMIT:
        recommended_note = (f"前沿里后悔最小的解有 {recommended['assumption_share']:.0%} "
                            f"的时间来自借用/假设依据，作为参考而非结论")
    else:
        recommended_note = None

    return {
        "objectives": keys,
        "directions": {k: _dir(k) for k in keys},
        "candidate_count": len(solutions),
        "frontier": [{"id": s["id"], "name": s.get("name"), "objectives": s.get("objectives"),
                      "max_regret": s.get("max_regret"),
                      "regret_by_objective": s.get("regret_by_objective"),
                      "assumption_share": s.get("assumption_share")}
                     for s in front],
        "dominated": [{"id": s["id"], "name": s.get("name"), "max_regret": s.get("max_regret"),
                       "regret_by_objective": s.get("regret_by_objective"),
                       "assumption_share": s.get("assumption_share")}
                      for s in scored if not s.get("on_pareto_front")],
        "eliminated": rejected,
        "no_feasible_solution": no_feasible,
        "report_only_comparison": report_only_comparison,
        "recommended_tied_with": tied_with,
        "recommended": recommended,
        "recommended_off_frontier": out_of_frontier,
        "recommended_note": recommended_note,
        "report_only": list(REPORT_ONLY),
        "selection_rule": ("可行解 → 帕累托前沿 → 前沿里选后悔向量字典序最小的解"
                           "（先最小化最坏后悔，并列再比次坏，不靠顺序瞎选）。"
                           "不用加权总分：加权和会被'牺牲一维换另一维'刷高，"
                           "而工厂要的是不被任何单一目标绑死的平衡解。"),
        "self_check": anti_goodhart_check(scored, keys) if len(scored) >= 4 else [],
        "objective_spread": spread,
        "non_discriminating_objectives": dead,
        "absorbed_by_constraint": absorbed,
        "notes": notes,
        "anti_goodhart": {
            "throughput_floor_ratio": MIN_THROUGHPUT_RATIO,
            "why": "产量不到需求 95% 的解直接淘汰 —— 否则'干脆不做'永远是最优解。",
            "assumption_share_limit": ASSUMPTION_SHARE_LIMIT,
        },
    }
