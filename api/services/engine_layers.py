"""分层验收：自下而上，每层一个能算的数，过不了线就不往上报。

平行堆指标最后会变成"我们全都做得好"的自嗨报告。所以这里规定死了：
· 每层的判据不一样，且必须是算出来的数（不是打分表）；
· 依赖关系是硬的：从最低一层往上找第一个不过线的，它**以上**的读数一律标 `not_reportable`；
· 算不出来的项写 `not_computable` 并点名缺哪个输入，不许用别的数冒充，也不许算 0 分；
  量出来了但没有判线的项写 `reported` —— "有数没线"和"没数"是两回事，混着标会让人去补本来就有的数。

五层（L1 内核 / L2A 敏感度 / L2B 准确度 / L3 决策 / L4 Agent 接口）。
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 阈值是我定的口径，每条都写清理由；要改改这里（或对应环境变量），不要改判据本身。
THRESHOLDS: Dict[str, Dict[str, float]] = {
    "L1": {"reproducible_rate": 1.0,        # 同输入不同结果 = 上面所有数都不可引用
           "p50_seconds": 120.0,            # 链条一轮预算 900 秒，内核最多占 1/8
           # 崩溃率判窗口不判累计：插桩前查不到成因的历史失败不该永久压住上层
           "crash_rate": 0.01, "crash_window_min_ticks": 12,
           # 心跳判生死交给"真断写数"：2×预期间隔那一格会被长轮（一轮里落进 4-6 小时的闸门）压住，
           # 那是慢不是死。断写仍然要拦 —— 台账里的每个数都停在最后一次成功上，比崩溃更隐蔽。
           "heartbeat_stalled_loops_max": 0},
    "L2A": {"elastic_coverage": 0.60,       # 六成以上参数能算出弹性，才谈"弹性表"
            "direction_hit_rate": 1.0,      # 符号错就是模型坏，不是精度问题
            "ci_width_steps": 1.5,           # 90% 置信区间宽过 1.5 个档距就等于没测出来
            "elastic_ci_usable": 0.5},      # 至少一半杠杆的弹性是"测得出来的"，才算这一层成立
    "L2B": {"kit_line_coverage": 0.60,    # 台账缺口行至少覆盖引擎展开的六成，否则一致率没有意义
            "top5_overlap": 0.50,         # 两边前 5 名要有一半以上重合
            "bottleneck_min_orders": 20,   # 按单算命中率：20 张才有对错可言（1 张不算命中率）
            "backtest_mape": 0.20,        # 预测与实际工期之比，偏差 20% 以内才算能用
            "backtest_min_pairs": 10,      # 少于 10 张成对样本不判线（3 张能算出数但说明不了精度）
            "bottleneck_hit_rate": 0.70},
    "L3": {"retest_improvement_days": 0.5,  # 推荐相对基线至少要值半天，否则别推荐
           "adoption_rate": 0.30,           # 人真采纳过；全被引擎自己取代 = 没人看
           "flip_rate": 0.20,
           # 催购动作可以全部建立在铺出来的提前期与演示供应商上（10-07 实测 5/5），
           # 那不等于可以下单：这条判线把"数据没到家"从推荐文案里提到闸门上。
           "actions_on_unverified_max": 0},
    "L4": {"routing_accuracy": 0.85, "tool_backing_rate": 0.80,
           "number_backing_rate": 0.90, "contract_leaks": 0, "envelope_violations": 0,
           "internal_names_rejected": 1.0},
}
from api.services.engine_heartbeat import window_hours as _window_hours

WINDOW_HOURS_LABEL = f"{_window_hours()}h"
LAYER_ORDER = ["L1", "L2A", "L2B", "L3", "L4"]
LAYER_NAMES = {"L1": "仿真内核", "L2A": "能力·敏感度", "L2B": "能力·准确度",
               "L3": "决策逻辑", "L4": "Agent 接口"}
LAYER_QUESTIONS = {"L1": "跑得动、跑得稳、同输入同结果吗",
                   "L2A": "参数动一档，输出怎么动，测得准吗",
                   "L2B": "和真实对得上吗",
                   "L3": "结论能指导行动吗",
                   "L4": "能被问、被解释、被复现吗"}

# 「未经核实」标注真正挂到 kernel 出口的那一刻（提交 22c71493，2026-10-06 15:51 UTC）。
# 早于它的轮次没有标注机会，会被算成"无出处" —— 那是在为历史扣分，不是在测现在的行为，
# 所以另报一格"上线以来"，并在判线那格的依据里写清有多少条属于历史。
PROVENANCE_NOTE_SINCE = datetime(2026, 10, 6, 15, 51)

# 自然问法 → 应该被选中的工具。这是路由的回归集，不是模型评分。
ROUTING_GOLDEN: List[Tuple[str, str]] = [
    ("引擎在建议什么", "query_simulation_recommendation"),
    ("该催哪个料号", "query_simulation_recommendation"),
    ("上次让它催的料催了没有", "query_simulation_recommendation"),
    ("补 IE 工时值几天", "query_simulation_sensitivity"),
    ("加班和开第二条线划不划算", "query_simulation_sensitivity"),
    ("这个交期有多可信", "query_simulation_sensitivity"),
    ("为什么交期是这天", "query_engine_attribution"),
    ("这台单卡在哪儿", "query_engine_attribution"),
    ("把提前期砍半为什么能早这么多", "query_engine_attribution"),
    ("该先松哪个约束", "query_engine_attribution"),
    ("工厂现在是在推进还是停滞", "query_chain_convergence"),
    ("积压在涨还是在消", "query_chain_convergence"),
    ("瓶颈件一致率为什么只有 0.057", "query_engine_capability_layers"),
    ("先补哪个数据才能让命中率上得去", "query_sim_evidence_readiness"),
    ("这些单为什么没有齐套行", "query_sim_evidence_readiness"),
    ("这版计划能开工几张", "query_plan_commit_gate"),
    ("库存健康度怎么样", "query_wms_inventory_health"),
    ("哪些料该补", "query_wms_inventory_health"),
    ("交期风险有哪些", "query_pmc_control_tower"),
]


# 引擎自己的身份：这些账号写的处置记录是系统在收尾，不是人对引擎的态度
MACHINE_ACTORS = frozenset({
    "virtual_factory", "virtual_factory_scenario", "system", "night-watch",
    "plan-commit-gate", "partial_kit_advisor", "time_basis_auditor",
    "equipment_agent", "quality_agent", "pmc_agent", "procurement_agent",
    "scheduling_agent", "warehouse_agent", "delivery_agent", "ai_assistant",
})
# 少于这个条数就不判采纳率：1 条处置算出来的"0.0 采纳率"不是证据，是噪声
MIN_ADOPTION_DISPOSITIONS = 3


def row_coverage(ledger_rows: int, engine_rows: int) -> Optional[float]:
    """台账登记到的缺口行 ÷ 引擎本轮展开出的缺口件行 —— 「台账缺口行覆盖率」只允许这一把尺。

    必须是**逐单求和**之比：两张中位数之比说的是「典型那张单齐了没」，浅档单少时它会
    明显乐观（10-09 实测：中位数比 0.961、求和比 0.821），而补登记的工作量是按行数推进的，
    放行门看的也是行。分母为 0 时返回 None —— 引擎没展开出缺口件，覆盖率无从计算，不许报 0。
    """
    eng = int(engine_rows or 0)
    return round(int(ledger_rows or 0) / eng, 3) if eng else None


def adoption_from_dispositions(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """人工采纳率：只数**有人的账号写过处置日志**的那些单。

    为什么要挑 actor：上一版只看终态 —— 24 条推演建议里 23 条是引擎换了推荐后自己关的，
    剩下 1 条连处置日志都没有；那 1 条被算成"人拒了"，采纳率就报成 0.0。
    没有证据的收尾不能当人对引擎的态度；有效条数不够就不判，也不给 0 分。
    """
    adopted = rejected = engine_churn = unlogged = 0
    for r in rows:
        status = str(r.get("status") or "")
        actor = str(r.get("actor") or "").strip()
        superseded = "已被更新的推演推荐取代" in str(r.get("block_reason") or "")
        if superseded or (actor and actor in MACHINE_ACTORS):
            engine_churn += 1
            continue
        if not actor:
            unlogged += 1
            continue
        if status == "done":
            adopted += 1
        elif status in ("cancelled", "closed"):
            rejected += 1
    judged = adopted + rejected
    return {"adopted": adopted, "rejected": rejected, "judged": judged,
            "engine_churn": engine_churn, "unlogged": unlogged,
            "rate": round(adopted / judged, 3) if judged >= MIN_ADOPTION_DISPOSITIONS else None}


def _metric(name: str, value: Any, threshold: Optional[float], sense: str, unit: str,
            basis: str, **extra: Any) -> Dict[str, Any]:
    """sense: gte=越大越好，lte=越小越好。三种状态必须分清：

    · pass / fail —— 算得出且有判线；
    · reported —— 算得出，但这一格没有判线（只报数不打分，比如峰值内存、累计崩溃率）；
    · not_computable —— 真的算不出：没有值，或样本少于判据要的条数，必须点名缺哪个输入。

    以前"没有判线"也写成 not_computable，于是"峰值内存 191.8 MB"这种明明量出来的数
    在报告里挂着"算不出"—— 读报告的人会去补一个本来就有的数，而真正缺的那格反而没人追。
    """
    out = {"metric": name, "value": value, "threshold": threshold, "sense": sense,
           "unit": unit, "basis": basis, **extra}
    min_n = extra.get("n")
    short_sample = min_n is not None and float(min_n) < float(extra.get("min_n", 0) or 0)
    if value is None or short_sample:
        out["pass"] = None
        out["state"] = "not_computable"
        out.setdefault("missing", extra.get("missing") or
                       (f"可比样本 {min_n} 条，少于判据需要的 {extra.get('min_n')} 条"
                        if min_n is not None else extra.get("missing")))
        return out
    if threshold is None:
        out["pass"] = None
        out["state"] = "reported"
        out.setdefault("missing", None)
        return out
    ok = float(value) >= float(threshold) if sense == "gte" else float(value) <= float(threshold)
    out["pass"] = bool(ok)
    out["state"] = "pass" if ok else "fail"
    return out


def boot_ci_slope(levels: List[float], days: List[float], step: float,
                  *, samples: int = 200, seed: int = 7) -> Dict[str, Any]:
    """弹性系数的置信区间：对曲线档位做 bootstrap 重采样，量它的散布（单位=档距）。

    用 bootstrap 而不是解析式，是因为这些曲线本来就是台阶型的：正态假设会给出一条
    看起来很窄、其实不存在的区间。区间宽过 1.5 个档距就是"没测出来"，不该报斜率。
    """
    xs, ys = [list(map(float, levels)), list(map(float, days))]
    if len(xs) < 3 or step <= 0:
        return {"computable": False, "why": "档位不足 3 个"}
    def slope(idx: List[int]) -> Optional[float]:
        sx = sum(xs[i] for i in idx) / len(idx)
        sy = sum(ys[i] for i in idx) / len(idx)
        denom = sum((xs[i] - sx) ** 2 for i in idx)
        if denom <= 1e-12:
            return None
        return sum((xs[i] - sx) * (ys[i] - sy) for i in idx) / denom * step
    base = slope(list(range(len(xs))))
    import random
    rnd = random.Random(seed)
    draws: List[float] = []
    for _ in range(int(samples)):
        idx = [rnd.randrange(len(xs)) for _ in range(len(xs))]
        s = slope(idx)
        if s is not None:
            draws.append(s)
    if len(draws) < 10 or base is None:
        return {"computable": False, "why": "重采样退化（曲线是平的或档位太少）"}
    draws.sort()
    lo = draws[int(0.05 * len(draws))]
    hi = draws[min(len(draws) - 1, int(0.95 * len(draws)))]
    return {"computable": True, "slope_per_step": round(base, 3),
            "ci90": [round(lo, 3), round(hi, 3)],
            "ci_width_steps": round(abs(hi - lo) / step, 2)}


def worst_ci_row(ci_rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """区间最宽的那条杠杆 —— 「最差」必须能指到具体一条曲线，否则这格只是个大数。

    平的曲线与样本不够是两件事：区间跨过 0 说明方向都没定；不跨 0 只是幅值不定。
    """
    if not ci_rows:
        return None
    return max(ci_rows, key=lambda r: float(r.get("ci_width_steps") or 0.0))


def direction_expectations() -> List[Dict[str, Any]]:
    """已知冲击的方向判据：符号错了不是精度问题，是模型坏。"""
    return [
        {"label": "外购提前期砍一半", "perturb": {"lead_multiplier": 0.5}, "sign": "lte",
         "why": "料更早到，完工不可能更晚"},
        {"label": "到岗率降到 0.70", "attendance": 0.70, "sign": "gte",
         "why": "人力绑定的线，人少了只会更晚"},
        {"label": "单件工时估高 1.5 倍", "perturb": {"hours_multiplier": 1.5}, "sign": "gte",
         "why": "工时变多，最多持平（若线声明才是约束），绝不提前"},
        {"label": "同一张单拆 4 批投放", "perturb": {"batches": 4.0}, "sign": "gte",
         "why": "多三次换型只会更晚或持平"},
        {"label": "可用库存少一半", "perturb": {"stock_multiplier": 0.5}, "sign": "gte",
         "why": "先开批次变少，整单只会持平或更晚"},
    ]


def check_direction(sign: str, base_finish: float, probe_finish: Optional[float]) -> bool:
    if base_finish is None or probe_finish is None:
        return False        # 跑不出结果也算方向不明，不许算通过
    return probe_finish <= base_finish if sign == "lte" else probe_finish >= base_finish


def gate(report: Dict[str, Any]) -> Dict[str, Any]:
    """自下而上：找到第一个不过线的层，它以上的层一律不许对外引用。"""
    first_fail = None
    for i, lid in enumerate(LAYER_ORDER):
        m = (report.get(lid) or {}).get("metrics") or []
        states = [x.get("state") for x in m]
        layer_pass = all(s != "fail" for s in states) and "pass" in states
        computable = any(s != "not_computable" for s in states)
        if not computable:
            first_fail = first_fail or lid
        if not layer_pass:
            first_fail = lid
            break
    blocked_from = first_fail or None
    floor = LAYER_ORDER.index(blocked_from) if blocked_from else len(LAYER_ORDER)
    for lid in LAYER_ORDER:
        idx = LAYER_ORDER.index(lid)
        (report[lid] or {})["reportable"] = blocked_from is None or idx < floor
        (report[lid] or {})["quote_rule"] = (
            "可对外引用" if (report[lid] or {}).get("reportable") else
            f"不作对外结论：下层 {blocked_from} 未过线，本层的数只是中间产物")
    return {"first_unmet_layer": blocked_from,
            "reportable_through": LAYER_ORDER[:floor] or ["（无）"],
            "rule": "自下而上，第一个不过线（或整层算不出数）的层以上，一律不引用"}


async def _l1_kernel(db: AsyncSession, factory_id: str, models: List[str],
                     runner: Callable[..., Any]) -> Dict[str, Any]:
    from api.services.virtual_run import derive_targets, scan_policies
    targets = await derive_targets(db, factory_id, models, days_of_output=6.0, lead_margin=1.15)
    pol = {"name": "基准（分批开工）", "allow_partial": True}
    digests: List[str] = []
    times: List[float] = []
    crashes = 0
    for _ in range(3):
        t0 = time.perf_counter()
        try:
            scan = await scan_policies(db, factory_id, targets, policies=[pol],
                                       scenarios=[{"name": "基准", "attendance": 0.97}])
            sols = scan["by_scenario"]["基准"]["solutions"]
            digests.append(json.dumps([sols[0]["objectives"],
                                       [d.get("finish_date") for d in sols[0]["detail"]]],
                                      ensure_ascii=False, sort_keys=True))
        except Exception as exc:                      # 崩溃要计数，不能整层报错退出
            crashes += 1
            digests.append(f"error:{type(exc).__name__}")
        times.append(round(time.perf_counter() - t0, 3))
    repro = round(sum(1 for d in digests[1:] if d == digests[0]) / max(1, len(digests) - 1), 3) if digests else None
    loop = (await db.execute(text("""
        SELECT ticks, failures, window_ticks, window_failures, window_started_at,
               recent_errors::text AS errs
        FROM engine_loop_state WHERE loop_name='routing-backfill'
    """))).mappings().first()
    from api.services.engine_heartbeat import window_hours
    window_label = f"{window_hours()}h"
    w_ticks = int((loop or {}).get("window_ticks") or 0)
    w_fails = int((loop or {}).get("window_failures") or 0)
    window_rate = round(w_fails / w_ticks, 5) if w_ticks else None
    window_start = str((loop or {}).get("window_started_at") or "")[:19]
    try:
        recent_errs = json.loads((loop or {}).get("errs") or "[]")
    except (TypeError, ValueError):
        recent_errs = []
    loop_crash = round(float((loop or {}).get("failures") or 0) /
                       max(1, float((loop or {}).get("ticks") or 1)), 5)
    import resource
    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    # 无人任务中心"在跑"这件事要能被算出来，不能靠日志。一次性任务（跑完就 exited）
    # 不进分母 —— 说它活着是假话；但每个逐轮报心跳的循环都必须新鲜。
    from api.services.engine_heartbeat import read_states

    try:
        states = await read_states()
    except Exception as exc:
        states = []
        hb_error = f"{type(exc).__name__}: {exc}"
    else:
        hb_error = None
    # 只判已经报过完整一轮的循环：刚 spawned 还没跳过手的，判它死是误报，说它活是假话，
    # 所以不进分母、单独点名
    ticking = [x for x in states if x.get("state") == "ticking"]
    waiting = [x for x in states if x.get("state") == "spawned-unverified"]
    stale = [x for x in ticking if not x.get("alive")]
    hb_rate = round((len(ticking) - len(stale)) / len(ticking), 3) if ticking else None
    crash_attr = [str(x.get("error"))[:120] for x in recent_errs][-3:]
    # 判线交给催办用的那条线（2×预期间隔再宽一倍），2× 那一格只报数：
    # 调度器一轮里落进 4-6 小时那道闸门时单轮会 >240 秒 —— 那是长轮不是断写，
    # 10-07 有两次 L1 被它压住、上面四层全部标成不可引用。两处共用一把尺，
    # 界面与判据不会各说各话（判线函数只定义在 engine_watchdog 一处）。
    try:
        from api.services.engine_watchdog import is_down as _watchdog_down
        hard_stuck = [str(x.get("loop")) for x in ticking if _watchdog_down(x)]
    except Exception as exc:  # noqa: BLE001
        hard_stuck = []
        hb_error = hb_error or f"断写判线读取失败：{type(exc).__name__}: {exc}"
    return {"metrics": [
        _metric("同输入可复现率", repro, THRESHOLDS["L1"]["reproducible_rate"], "gte", "",
                "同一输入跑 3 轮，比较目标向量与完工日摘要（3 次里 2 次比对）"),
        _metric("单轮耗时 p50", (statistics.median(times) if times else None),
                THRESHOLDS["L1"]["p50_seconds"], "lte", "秒", "5 台机种 × 1 政策单轮，含排队"),
        _metric("探针崩溃率", round(crashes / max(1, len(times)), 3), 0.0, "lte", "", "本次 3 轮里抛异常的次数"),
        _metric("引擎循环窗口崩溃率", window_rate, THRESHOLDS["L1"]["crash_rate"], "lte", "",
                f"当前窗口（{window_start} 起，{window_label}）内 routing-backfill 失败 "
                f"{w_fails}/{w_ticks} 跳。判据只看过得去的窗口：累计口径里那些没有错误小环、"
                "查不到成因的历史失败，永远压着上层却没人能修",
                n=w_ticks, min_n=int(THRESHOLDS["L1"]["crash_window_min_ticks"]),
                missing=(None if w_ticks >= int(THRESHOLDS["L1"]["crash_window_min_ticks"])
                         else f"窗口才 {w_ticks} 跳（判线要 ≥{THRESHOLDS['L1']['crash_window_min_ticks']} 跳）："
                              "心跳 900 秒一跳，得等窗口攒够样本；0/2 不算通过"),),
        _metric("逐轮心跳新鲜率（2×标称间隔，只报数）", hb_rate, None, "gte", "比例",
                f"{len(ticking) - len(stale)}/{len(ticking)} 个已报过完整一轮的循环在 2 个间隔内跳过；"
                f"另有 {len(waiting)} 个刚启动还没跳过手（不判生死：{[w['loop'] for w in waiting]}）。"
                "这一格只报敏感度不判线 —— 长轮（一轮里落进 4-6 小时的闸门）会把它压到 1.0 以下，"
                "真断写由下面那一格判",
                missing=(hb_error or (None if ticking else "没有任何循环在逐轮报心跳"))),
        _metric("引擎循环真断写数（与催办同一条线）", (len(hard_stuck) if ticking else None),
                THRESHOLDS["L1"]["heartbeat_stalled_loops_max"], "lte", "个",
                "判线 = engine_watchdog.stall_deadline_seconds（2×预期间隔 ×2），和收件箱里那条催办同一把尺。"
                f"当前不过线的循环：{hard_stuck or '无'}。"
                "心跳断写时台账里的每个数都停在最后一次成功上，比崩溃更隐蔽，"
                "所以这一格不过线就不许引用上层",
                missing=(hb_error or (None if ticking else "没有任何循环在逐轮报心跳"))),
        _metric("窗口内已归因失败数", len(crash_attr), None, "lte", "条",
                f"recent_errors 小环里带时间戳的最近几条：崩溃必须能被归因才有意义；"
                f"内容见 detail.recent_errors（{'; '.join(crash_attr)[:120] or '环是空的，说明窗口内没崩过'}）"),
        _metric("引擎循环累计崩溃率", loop_crash, None, "lte", "",
                "engine_loop_state 的 failures/ticks（自进程启动累计）：只报数不判线。"
                "已知的 5 次失败成因从日志回查得到：cached plan 失效（加列迁移那次，一次性的）、"
                "心跳 INSERT 列序错位（10-06 已修）、回填链里三处代码缺陷（现均已不在树上）"),
        _metric("峰值内存", rss_mb, None, "lte", "MB", "只报数不判线：这台机器上还跑别的容器"),
    ], "recent_errors": recent_errs}


async def _l2a_sensitivity(db: AsyncSession, factory_id: str, models: List[str],
                           runner: Callable[..., Any]) -> Dict[str, Any]:
    from api.services.sim_sensitivity import LEVERS as LEVERS_META, sensitivity
    from api.services.virtual_run import equipment_rate, scan_policies, derive_targets
    sens = await sensitivity(db, factory_id, models)
    levers = sens.get("levers") or []
    computable = [l for l in levers if (l.get("slope") or {}).get("computable")]
    ci_rows, width_worst = [], None
    ci_usable = 0
    for l in levers:
        rows = [c for c in (l.get("curve") or []) if c.get("finish_date") is not None]
        levels = [float(c["level"]) for c in rows]
        days = [float(c.get("days_vs_base") or 0) for c in rows]
        step = float(next((x["step"] for x in LEVERS_META if x["key"] == l.get("key")), 0.1))
        ci = boot_ci_slope(levels, days, step)
        if ci.get("computable"):
            ci_rows.append({"lever": l["label"], "step": step, **ci})
            if float(ci["ci_width_steps"]) <= THRESHOLDS["L2A"]["ci_width_steps"]:
                ci_usable += 1
            width_worst = max(width_worst or 0.0, float(ci["ci_width_steps"]))
    # 方向探针：已知冲击打进去，看符号会不会反
    targets = await derive_targets(db, factory_id, models, days_of_output=6.0, lead_margin=1.15)
    pol = {"name": "基准（分批开工）", "allow_partial": True}
    eq = float((await equipment_rate(db, factory_id)).get("rate") or 1.0)

    async def _finish(perturb: Dict[str, float], attendance: float) -> Optional[float]:
        scan = await scan_policies(db, factory_id, targets, policies=[pol],
                                   scenarios=[{"name": "基准", "attendance": attendance}],
                                   perturb={**perturb, "equip_rate": eq})
        dates = [d.get("finish_date") for d in scan["by_scenario"]["基准"]["solutions"][0]["detail"]
                 if d.get("finish_date")]
        return max(dates) if dates else None

    from datetime import date as _d
    base_finish = await _finish({}, 0.97)
    base_val = _d.fromisoformat(base_finish).toordinal() if base_finish else None
    probes = []
    for p in direction_expectations():
        got = await _finish(dict(p.get("perturb") or {}), float(p.get("attendance") or 0.97))
        val = _d.fromisoformat(got).toordinal() if got else None
        ok = check_direction(p["sign"], base_val, val)
        probes.append({"probe": p["label"], "expected": p["sign"], "base": base_finish,
                       "got": got, "ok": ok, "why": p["why"]})
    hits = sum(1 for p in probes if p["ok"])
    ci_usable_rate = round(ci_usable / len(ci_rows), 3) if ci_rows else None
    worst = worst_ci_row(ci_rows)
    return {"metrics": [
        _metric("弹性可算覆盖率", round(len(computable) / max(1, len(levers)), 3),
                THRESHOLDS["L2A"]["elastic_coverage"], "gte", "",
                f"{len(computable)}/{len(levers)} 个杠杆能算出局部斜率"),
        _metric("方向命中率", round(hits / max(1, len(probes)), 3),
                THRESHOLDS["L2A"]["direction_hit_rate"], "gte", "",
                "已知冲击打进去，完工日只能朝一个方向动；符号反了就是模型坏"),
        _metric("置信区间可用的杠杆占比", ci_usable_rate, THRESHOLDS["L2A"]["elastic_ci_usable"], "gte", "",
                f"{ci_usable}/{len(ci_rows)} 个杠杆的 90% 区间宽 <= {THRESHOLDS['L2A']['ci_width_steps']} 个档距"
                "（bootstrap 200 次重采样；区间宽过档距就是没测出来，不报斜率）",
                n=len(ci_rows), min_n=3),
        _metric("最差置信区间宽度", width_worst, None, "lte", "档距",
                (f"最差的是「{worst['lever']}」：{worst['ci_width_steps']} 个档距，"
                 f"斜率 {worst['slope_per_step']} 天/档，90% 区间 {worst['ci90']}。"
                 + ("区间跨过 0 —— 这条杠杆连方向都没定，斜率不报；"
                    if float(worst['ci90'][0]) <= 0.0 <= float(worst['ci90'][1])
                    else "区间没跨 0 —— 方向定了，只是幅值量不准；")
                 + f"步长 {worst.get('step')} 档，判线是宽 <= "
                   f"{THRESHOLDS['L2A']['ci_width_steps']} 个档距算测出来")
                if worst else "本轮没有算得出区间的杠杆"),
    ], "probes": probes, "ci": ci_rows, "base_finish": base_finish,
        "levers": [{"lever": l["label"], "slope": l.get("slope"),
                    "not_a_scheduling_lever": l.get("not_a_scheduling_lever")} for l in levers]}


async def _l2b_accuracy(db: AsyncSession, factory_id: str, models: List[str]) -> Dict[str, Any]:
    from api.services.sim_backtest import readiness as _readiness
    from api.services.sim_sensitivity import mapping_accuracy
    acc = await mapping_accuracy(db, factory_id, models)
    # 瓶颈命中率：仿真点名的瓶颈件 vs 台账里该机型缺口最大的外购料号
    # 台账瓶颈必须归到**整机机种**再比：工单有下级自制件子单（实测机械厂 791 张有父单），
    # 子单上的 product_id 是 SAP 组件号（1000461205 这类），直接按它分组的话
    # 17 个"机种"里有 16 个根本不是机种，和仿真的整机瓶颈永远对不上（实测滚一层就够：16/17 落回 A-50-04-F）
    hit_rows = (await db.execute(text("""
        WITH led AS (
            SELECT w.material_code, w.shortage_qty,
                   COALESCE(pp.product_code, p.product_code, o.product_id) AS model
            FROM work_order_materials w
            JOIN work_orders o ON o.id = w.work_order_id
            LEFT JOIN products p ON p.factory_id = o.factory_id
                 AND (p.id::text = o.product_id OR p.product_code = o.product_id)
            LEFT JOIN work_orders par ON par.id = o.parent_work_order_id
            LEFT JOIN products pp ON pp.factory_id = par.factory_id
                 AND (pp.id::text = par.product_id OR pp.product_code = par.product_id)
            WHERE o.factory_id = :fid AND w.item_type = 'buy'
              AND COALESCE(w.shortage_qty,0) > 0
              AND o.status NOT IN ('completed','cancelled'))
        SELECT model,
               (ARRAY_AGG(material_code ORDER BY shortage_qty DESC))[1] AS top_short_code,
               COUNT(*) AS short_lines
        FROM led GROUP BY 1
    """), {"fid": factory_id})).mappings().all()
    ledger = {str(r["model"]): str(r["top_short_code"]) for r in hit_rows}
    ledger_lines = {str(r["model"]): int(r["short_lines"] or 0) for r in hit_rows}
    # 引擎侧的瓶颈件：按政策"现况、好天"跑一轮，取每台单点名的那件
    from api.services.virtual_run import derive_targets, scan_policies

    _t = await derive_targets(db, factory_id, models, days_of_output=6.0, lead_margin=1.15)
    _scan = await scan_policies(db, factory_id, _t, policies=[{"name": "基准", "allow_partial": True}],
                                scenarios=[{"name": "基准", "attendance": 0.97}])
    _detail = _scan["by_scenario"]["基准"]["solutions"][0]["detail"]
    sim = {str(d.get("model_code")): str((d.get("bottleneck_part") or {}).get("material_code"))
           for d in _detail if d.get("bottleneck_part")}
    both = [m for m in sim if m in ledger]
    hits = sum(1 for m in both if sim[m] == ledger[m])
    # 命中率按「同一张单、同一数量、同一库存」两边各选一次来判，两种定义都算（见 sim_backtest）
    from api.services.sim_backtest import bottleneck_agreement

    agree = await bottleneck_agreement(db, factory_id, limit=120)
    order_n = int(agree.get("orders_compared") or 0)
    order_hits = int((agree.get("lead_based") or {}).get("agree") or 0)
    qty_hits = int((agree.get("quantity_based") or {}).get("agree") or 0)
    order_models = list(agree.get("model_list") or [])
    # 0 命中要先分清"模型判错"和"两边根本不在同一套料号上比"：
    # 仿真的瓶颈件取自本地 bom_items（实测机械厂 1,055 行全是 RM-* 合成料号，SAP 数字料号 0 行），
    # 而台账缺口行多是 engflow 真源的 SAP 料号（1000108191 螺絲 这类）。料号不同源时命中率必为 0。
    ledger_codes = {str(c) for (c,) in (await db.execute(text("""
        SELECT DISTINCT w.material_code FROM work_order_materials w
        JOIN work_orders o ON o.id = w.work_order_id
        WHERE o.factory_id = :fid AND w.item_type = 'buy'
          AND COALESCE(w.shortage_qty,0) > 0
    """), {"fid": factory_id})).all()}
    sim_codes = {c for c in sim.values() if c}
    same_system = sorted(c for c in sim_codes if c in ledger_codes)
    mirror_real_lines = int((await db.execute(text(
        "SELECT COUNT(*) FROM enghub_bom_items WHERE product_model = ANY(CAST(:ms AS text[]))"
    ), {"ms": list(sim.keys())})).scalar() or 0)
    sim_bom_system = ("合成 RM-*" if any(str(c).startswith("RM-") for c in sim_codes)
                      else "SAP 数字料号")
    # 回测不靠 aps_schedule_tasks（实测已完工 28 张里 0 张留有排程任务行，等于永远回测不了）：
    # 用"计划开工日为今天、按现主数据重跑一次"得到预测完工日，与实际完工日成对比。
    # 局限必须一起报：重跑用的是**现在**的 BOM/工时/提前期，不是当时的主数据快照。
    from datetime import date as _date, timedelta as _td
    from api.services.virtual_run import scan_policies as _scan

    pairs, skipped = [], {"no_planned_start": 0, "model_not_in_bom": 0}
    done_rows = (await db.execute(text("""
        SELECT o.id, o.planned_start, o.planned_due, o.actual_complete,
               o.planned_qty AS qty,
               COALESCE(pp.product_code, p.product_code, o.product_id) AS model
        FROM work_orders o
        LEFT JOIN products p ON p.factory_id = o.factory_id
             AND (p.id::text = o.product_id OR p.product_code = o.product_id)
        LEFT JOIN work_orders par ON par.id = o.parent_work_order_id
        LEFT JOIN products pp ON pp.factory_id = par.factory_id
             AND (pp.id::text = par.product_id OR pp.product_code = par.product_id)
        WHERE o.factory_id = :fid AND o.status = 'completed'
          AND o.actual_complete IS NOT NULL
        ORDER BY o.actual_complete DESC LIMIT 60
    """), {"fid": factory_id})).mappings().all()
    for r in done_rows:
        model = str(r["model"] or "")
        start, due, actual = r["planned_start"], r["planned_due"], r["actual_complete"]
        if start is None or due is None:
            skipped["no_planned_start"] += 1
            continue
        has_bom = (await db.execute(text(
            "SELECT 1 FROM bom_items WHERE factory_id=:fid AND product_id=:m LIMIT 1"
        ), {"fid": factory_id, "m": model})).first()
        if not has_bom:
            skipped["model_not_in_bom"] += 1
            continue
        start_d = start.date() if hasattr(start, "date") else _date.fromisoformat(str(start)[:10])
        due_d = due.date() if hasattr(due, "date") else _date.fromisoformat(str(due)[:10])
        actual_d = actual.date() if hasattr(actual, "date") else _date.fromisoformat(str(actual)[:10])
        units = float(r["qty"] or 0) or 1.0
        scan = await _scan(db, factory_id,
                           [{"model_code": model, "units": units,
                             "due_in_days": max(1, (due_d - start_d).days)}],
                           today=start_d,
                           policies=[{"name": "基准", "allow_partial": True}],
                           scenarios=[{"name": "基准", "attendance": 0.97}])
        sols = (((scan.get("by_scenario") or {}).get("基准") or {}).get("solutions") or [{}])
        det = sols[0].get("detail") or []
        pred = det[0].get("finish_date") if det else None
        if not pred:
            continue
        pred_d = _date.fromisoformat(str(pred)[:10])
        err = abs((pred_d - actual_d).days)
        span = max(1, (actual_d - start_d).days)
        pairs.append({"work_order_id": str(r["id"]), "model": model, "units": units,
                      "planned_start": str(start_d), "planned_due": str(due_d),
                      "actual_complete": str(actual_d), "sim_predicted_finish": str(pred_d),
                      "error_days": err, "actual_span_days": span})
    mape_value = (round(sum(p["error_days"] for p in pairs)
                        / max(1, sum(p["actual_span_days"] for p in pairs)), 4)
                  if pairs else None)
    mape = len(pairs)
    # 留痕法那格要的是账本实况：记了几张、配了几对、误差中位数与 MAPE
    try:
        from api.services.prediction_ledger import delivery_accuracy as _acc

        _led = await _acc(db, factory_id)
    except Exception:  # noqa: BLE001 - 账本读不动时这一格如实 not_computable，不带崩整层
        _led = {"mape": None, "paired": 0, "orders_recorded": 0}
    priced = float(acc.get("overall_accuracy") or 0)
    srs = agree.get("short_row_sums") or {}
    eng_rows = int(srs.get("engine_rows") or 0)
    led_rows = int(srs.get("ledger_rows") or 0)
    row_cov = row_coverage(led_rows, eng_rows)
    coinc = agree.get("top_choice_coincidence") or {}
    univ = agree.get("bom_universe") or {}
    same_gen = univ.get("same_generation") or {}
    basis = same_gen.get("requirement_basis") or {}
    depth = univ.get("ledger_row_depth") or {}
    depth_txt = "、".join(f"{int(v)} 张停在 {k}" for k, v in (depth.get("buy_rows_per_order_buckets") or {}).items()
                          if v) or "没有可比单"
    return {"metrics": [
        _metric("瓶颈件一致率（提前期口径）", round(order_hits / order_n, 3) if order_n else None,
                THRESHOLDS["L2B"]["bottleneck_hit_rate"], "gte", "",
                f"{order_hits}/{order_n} 张在流程单：引擎选的「决定到货日那件」== 台账同一张单里提前期最长的缺料件；"
                f"覆盖机种 {len(order_models)} 个（{order_models}）。"
                + str(univ.get("note") or ""),
                n=order_n, min_n=int(THRESHOLDS["L2B"]["bottleneck_min_orders"]),
                missing=(None if order_n >= int(THRESHOLDS["L2B"]["bottleneck_min_orders"])
                         else f"可比单数 {order_n}（判线要 ≥{THRESHOLDS['L2B']['bottleneck_min_orders']} 张）")),
        _metric("瓶颈件一致率（数量口径）", round(qty_hits / order_n, 3) if order_n else None,
                None, "gte", "",
                f"{qty_hits}/{order_n} 张：引擎选的「净缺口最大那件」== 台账该单缺口最大的那件。"
                "两种定义分开报，是因为它们回答的不是同一个问题"
                "（提前期口径管「哪天能开工」，数量口径管「该现在下单多少」）。"
                f"两边都点到名的单只有 {univ.get('shared_universe_orders')} 张"
                f"（另有 {univ.get('off_universe_orders')} 张的引擎第一件压根不在该单当日的缺口行里），"
                f"在这 {univ.get('shared_universe_orders')} 张上的一致率是 "
                f"{univ.get('qty_based_on_shared_universe', {}).get('rate')} —— "
                "同一宇宙的分母才谈得上对错，剩下的分母是覆盖率问题。"
                f"本轮引擎两名（提前期最长 vs 净缺最大）点到同一件料号的单 "
                f"{coinc.get('engine_two_names_same')}/{coinc.get('of')}，"
                f"台账两名（提前期最长 vs 缺最多）为同一件的单 "
                f"{coinc.get('ledger_two_names_same')}/{coinc.get('of')} —— "
                "两名重合率高时这两格不是两次独立验证，只是一个数读了两遍"),
        _metric("BOM 取数来源", (agree.get("bom_sources") or [None])[0], None, "lte", "",
                f"这批可比单的仿真取数来自 {agree.get('bom_sources')}；"
                "镜像没有行的机种会如实回落本地 bom_items 并在每台单的读数里标注（见 sim-readiness）"),
        _metric("台账缺口行覆盖率", row_cov,
                THRESHOLDS["L2B"]["kit_line_coverage"], "gte", "比例",
                f"这 {order_n} 张可比单上：引擎按真源 BOM 展开出的外购缺口件共 {eng_rows} 行，"
                f"台账登记到的缺口行共 {led_rows} 行 —— 比值 {row_cov}。"
                "一致率与 top-5 重叠都被这一格封顶：台账只看得到一部分缺料行。"
                f"盖子是**登记世代**不是源侧缺账 —— {order_n} 张里 {depth_txt}"
                f"（中位 {depth.get('median_buy_rows')} 行、最多 {depth.get('max_buy_rows')} 行），"
                "补登记由 engine_kit_backfill 那道闸在做（只加行、每单有行数上限）；"
                "这一格与 /api/v1/pmc/kit-coverage-gap 的 coverage_rate、"
                "engine_watchdog 的 kit_line_coverage 同一把尺"
                "（那里按抽样单、这里按可比单池，两个数不必相等但必须同向）。"
                "旧读法取两张中位数之比，说的是「典型那张单齐了没」，"
                "浅档单少时它比求和口径乐观 —— 判线换到求和口径，中位数留成下面那格对照",
                missing=(None if eng_rows else "引擎没展开出缺口件，覆盖率无从计算")),
        _metric("每单缺口件数中位比（只报数）",
                (round(agree.get("median_ledger_parts")
                       / max(1, agree.get("median_shortage_parts") or 1), 3)
                 if agree.get("median_ledger_parts") is not None else None),
                None, "gte", "比例",
                f"台账缺口件数中位 {agree.get('median_ledger_parts')} 件 vs 引擎按真源 BOM 展开的"
                f"缺口件数中位 {agree.get('median_shortage_parts')} 件 —— 判线曾经用这个比值。"
                "留着当对照：它比上面那格乐观，说明浅档单被中位数抹掉了；"
                "两格反向时先信求和那格，因为补登记是按行数推进的"),
        _metric("瓶颈件 top-5 重叠率", agree.get("top5_overlap_rate"),
                THRESHOLDS["L2B"]["top5_overlap"], "gte", "",
                f"两边各取前 5 名的交集比例；台账第一件落进引擎前 5 的有 "
                f"{(agree.get('ledger_first_found_in_engine_top5') or {}).get('rate')}，"
                f"倒数排名 MRR {agree.get('engine_reciprocal_rank_on_ledger')} —— "
                "比只看第一名更贴近「是不是在盯同一批料」"),
        _metric("可比机种数（只报数）", len(both), None, "gte", "个",
                f"仿真给出瓶颈件且台账有缺口行的机种 {len(both)} 个："
                + "、".join(f"{k} {v} 行" for k, v in
                            sorted(ledger_lines.items(), key=lambda x: -x[1])[:4])
                + "；机种数由主数据决定，不是算法能补的（分类明细见 /api/v1/pmc/sim-readiness）"),
        _metric("命中率能覆盖几个机种", round(len(order_models) / max(1, len(sim)), 3),
                None, "gte", "比例",
                f"仿真这轮给出瓶颈件的 {len(sim)} 个机种里，{len(order_models)} 个有真实缺口单可比"),
        _metric("回测 MAPE", mape_value, THRESHOLDS["L2B"]["backtest_mape"], "lte", "",
                "已完工单按计划开工日重跑一次沙箱（政策=现况、好天），比预测完工日与实际完工日；"
                "误差按实际工期归一。**已知偏差方向**：重跑用的是**今天**的库存与提前期，"
                "历史单当时'料还没到'今天已不成立 → 沙箱会判得偏早（实测 3 张样本全部偏早，"
                "偏差等于整段实际工期）。所以这一格即使样本够也只能当下限看，"
                "真要精度回测需要当时的齐套/库存快照（见 #54）",
                n=mape, min_n=THRESHOLDS["L2B"]["backtest_min_pairs"],
                missing=(f"成对样本 {mape} 张（判线要 ≥{THRESHOLDS['L2B']['backtest_min_pairs']} 张）："
                         f"已完成且有实际完工日 {len(done_rows)} 张，其中"
                         f" {skipped['no_planned_start']} 张没留计划开工日、"
                         f" {skipped['model_not_in_bom']} 张的机种在 BOM 里没有行。"
                         "要补的是下达/完工时把计划开工日与预测完工日一起落到工单上（#54）")),
        _metric("交期误差（留痕法）", _led["mape"], THRESHOLDS["L2B"]["backtest_mape"], "lte", "",
                "上一格是**追溯法**：拿今天的主数据重跑历史单，问的是「今天这套数据会不会算错」。"
                "这一格是**留痕法**：引擎当时在工单上写下「预计几号交」，完工那天与实际对一次 —— "
                "只有这一格才回答「客户拿到的那个日期准不准」。样本只能攒不能补："
                "历史单当时没写过这句话，配不出对。",
                n=_led["paired"], min_n=THRESHOLDS["L2B"]["backtest_min_pairs"],
                # 文案取自账本那一格自己算的归因：同一条判线结论不许两处各拼一次
                missing=(None if _led["paired"] >= THRESHOLDS["L2B"]["backtest_min_pairs"] and
                         _led["mape"] is not None else
                         (f"账本里已记 {_led['orders_recorded']} 张在流程单的当日预计；"
                          f"{_led.get('missing') or '成对够数'}"))),
        _metric("输入映射精度", round(priced / 100.0, 3), None, "gte", "0~1",
                "六项输入的加权覆盖率（工时/提前期/供应商/库存/自制外购/单价），只作分母透明化"),
    ], "readiness": await _readiness(db, factory_id),
        "bottleneck_agreement": {k: v for k, v in agree.items() if k != "disagreements"},
        "sim_bottleneck": sim, "ledger_top_short": ledger,
        "ledger_short_lines": ledger_lines,
        "backtest_pairs": pairs[:12], "backtest_skipped": skipped,
        "backtest_pairs_available": int(mape or 0)}


async def _ledger_covered(db: AsyncSession, factory_id: str) -> int:
    """留痕账本今天记了几张单（账本没建时按 0 报，不把这格带崩）。"""
    from sqlalchemy import text as _text

    from api.services.prediction_ledger import ensure_schema

    try:
        await ensure_schema(db)
        return int((await db.execute(_text(
            "SELECT COUNT(DISTINCT work_order_id) FROM engine_order_predictions "
            "WHERE factory_id = :fid"), {"fid": factory_id})).scalar() or 0)
    except Exception:  # noqa: BLE001 - 账本查不动不影响别的格，缺席由上一格的 missing 说明
        return 0


async def _l3_decision(db: AsyncSession, factory_id: str, models: List[str]) -> Dict[str, Any]:
    from api.services.virtual_run import derive_targets, scan_policies, build_policy_grid
    from datetime import date as _d
    targets = await derive_targets(db, factory_id, models, days_of_output=6.0, lead_margin=1.15)
    grid = await build_policy_grid(db, factory_id, targets)
    scan = await scan_policies(db, factory_id, targets, policies=grid,
                               scenarios=[{"name": "基准", "attendance": 0.70}])
    sols = scan["by_scenario"]["基准"]["solutions"]
    def _late(s):
        return int((s.get("objectives") or {}).get("days_late_worst") or 0)
    base = next((s for s in sols if "现况" in str(s.get("name"))), None)
    best = min(sols, key=lambda s: (_late(s),
                                    float((s.get("objectives") or {}).get("labor_cost_usd") or 0))) if sols else None
    # 推荐是跨场景 minimax regret 选的，不等于本档延误最小 —— 决策层要量的是"推荐相对基线值几天"
    rec_row = (await db.execute(text("""
        SELECT lever_deltas::text AS ld FROM simulation_scorecards
        WHERE factory_id = :fid AND source = 'virtual_run_tradeoff'
        ORDER BY created_at DESC LIMIT 1
    """), {"fid": factory_id})).mappings().first()
    try:
        rec_name = str(json.loads((rec_row or {}).get("ld") or "{}").get("policy") or "")
    except (TypeError, ValueError):
        rec_name = ""
    rec = next((s for s in sols if str(s.get("name")) == rec_name), None)
    gain = (max(0, _late(base) - _late(rec))) if (base and rec) else None
    gap_to_best = (max(0, _late(rec) - _late(best))) if (rec and best) else None
    cards = (await db.execute(text("""
        SELECT top_constraint FROM simulation_scorecards
        WHERE factory_id = :fid AND source = 'virtual_run_tradeoff'
        ORDER BY created_at DESC LIMIT 12
    """), {"fid": factory_id})).mappings().all()
    # 入库的短指纹形如 "政策名|哈希"，取政策名即可判"这轮有没有换人"
    pols = [str(c["top_constraint"] or "").split("|")[0] for c in reversed(list(cards))]
    flips = sum(1 for a, b in zip(pols, pols[1:]) if a and b and a != b)
    flip_rate = round(flips / max(1, len(pols) - 1), 3) if len(pols) > 1 else None
    human = (await db.execute(text("""
        SELECT t.status, t.block_reason,
               (SELECT l.created_by FROM followup_task_logs l
                 WHERE l.task_id = t.id AND l.status_after IN ('done','cancelled','closed')
                 ORDER BY l.created_at DESC LIMIT 1) AS actor
        FROM followup_tasks t
        WHERE t.factory_id = :fid AND t.payload->>'category' = 'simulation_recommendation'
          AND t.status IN ('done','cancelled')
    """), {"fid": factory_id})).mappings().all()
    disp = adoption_from_dispositions([dict(r) for r in human])
    adoption = disp["rate"]
    # 催购落点（#63）：引擎把动作落成 pending 请购草稿之后，"人表过态没有"多了一条更细的证据。
    # 这一格**只报数、不进「人工采纳率」的判线** —— 那条尺数的是"每条推荐有没有人被表态"，
    # 草稿是按料号开的，混进去会把分母从"条推荐"换成"张单子"，同一个名字就又是两把尺。
    drafts = {"waiting": 0, "adopted_by_human": 0, "rejected_by_human": 0,
              "closed_by_machine": 0, "total": 0}
    draft_error = None
    try:
        from api.services.expedite_drafts import decision_summary

        drows = (await db.execute(text("""
            SELECT pr_code, material_code, status, approved_by, auto_approved
            FROM purchase_requisitions
            WHERE factory_id = :fid AND source = 'simulation_recommendation'
        """), {"fid": factory_id})).mappings().all()
        drafts = decision_summary([dict(r) for r in drows])
    except Exception as exc:  # noqa: BLE001  读不到草稿要写出来，不能当"没有草稿"
        draft_error = f"{type(exc).__name__}: {exc}"
    card = (await db.execute(text("""
        SELECT detail::text AS dt FROM simulation_scorecards
        WHERE factory_id = :fid AND source = 'virtual_run_tradeoff'
        ORDER BY created_at DESC LIMIT 1
    """), {"fid": factory_id})).mappings().first()
    try:
        cd = json.loads((card or {}).get("dt") or "{}")
    except (TypeError, ValueError):
        cd = {}
    flagged = int(cd.get("actions_on_unverified_input") or 0)
    reasons = cd.get("action_flag_reasons") or {}
    exp_total = int(cd.get("actions_total_expedite") or 0)

    return {"metrics": [
        _metric("推荐动作压在未核实依据上的条数", (flagged if exp_total else None),
                THRESHOLDS["L3"]["actions_on_unverified_max"], "lte", "条",
                f"最近一张权衡卡里 {exp_total} 条催购动作有 {flagged} 条至少一项依据未核实。"
                + (f"按原因分开数（一条动作可占多项）：提前期未实测 "
                   f"{reasons.get('lead_time_unverified', 0)} 条、料号来自本地表而非 engflow 镜像 "
                   f"{reasons.get('bom_source_not_mirror', 0)} 条、没有默认供应商 "
                   f"{reasons.get('no_supplier', 0)} 条。"
                   # 料号那一项别记到供应商主数据头上：本轮查取数入口，这些机种在镜像里本来就没行
                   "料号那一项是这些机种在 engflow 镜像里本来就没有行（回落本地表是如实标注），"
                   "要清掉它得厂里把那批机种的 BOM 交进来。"
                   if reasons else
                   f"这张卡写于旗标原因上线前，{flagged} 条没有原因分解 —— "
                   "照旧按整条数判线，下一张写卡的轮次起会分开点名三种原因。")
                + "这一格不过线不是推荐算错，是**照着下单的人没有可核的对象**，不是再推演一遍能解决的",
                missing=(None if exp_total else "最近这张卡没有催购动作，判不了依据质量")),
        _metric("推荐相对基线的再跑差值（暴雨档）", gain, THRESHOLDS["L3"]["retest_improvement_days"], "gte", "天",
                "推荐政策比「现况」少延几天；0 = 推荐就是基线，决策层没有增量（差距另报 gap_to_best）"),
        _metric("人工采纳率", adoption, THRESHOLDS["L3"]["adoption_rate"], "gte", "",
                f"人真采纳 {disp['adopted']} / 人处置过的 {disp['judged']} 条"
                f"（另有 {disp['engine_churn']} 条是引擎换推荐后自己关的、"
                f"{disp['unlogged']} 条终态没有处置日志，两条都不进分母）",
                n=disp["judged"], min_n=MIN_ADOPTION_DISPOSITIONS,
                missing=(None if disp["judged"] >= MIN_ADOPTION_DISPOSITIONS else
                         f"人处置过的只有 {disp['judged']} 条（判线要 ≥{MIN_ADOPTION_DISPOSITIONS} 条）："
                         "推演建议大多被引擎自己更新的推荐关掉，没人表过态 —— "
                         "这一格算不出，不能读成「没人采纳」")),
        _metric("催购落成请购草稿（只报数）", drafts.get("total") or None, None, "gte", "张",
                f"引擎把催购动作开成 pending 请购单：共 {drafts.get('total')} 张 —— "
                f"等人批 {drafts.get('waiting')}、人已批 {drafts.get('adopted_by_human')}、"
                f"人已拒 {drafts.get('rejected_by_human')}、系统自己收尾 {drafts.get('closed_by_machine')}。"
                "批/拒必须是人的账号写的，`auto_approved` 或机器署名都算「没人表态」；"
                "这些草稿**不计进**「人工采纳率」那条判线（那条按推荐计，这一格按料号计），"
                "也不计进「上一轮建议落地了没有」的证据 —— 引擎自己写的单子不能当厂里的动作"
                + (f"（读草稿失败：{draft_error}）" if draft_error else ""),
                missing=("读不到草稿：" + draft_error if draft_error else None)),
        _metric("推荐翻转率", flip_rate, THRESHOLDS["L3"]["flip_rate"], "lte", "",
                "最近 12 张记分卡里稳健推荐换人的次数占比；反复翻转=结论不稳"),
    ], "base_policy": (base or {}).get("name"), "recommended_policy": rec_name or (base or {}).get("name"),
        "best_policy": (best or {}).get("name"),
        "base_late_days": _late(base) if base else None,
        "recommended_late_days": _late(rec) if rec else None,
        "best_late_days": _late(best) if best else None,
        "gap_recommended_vs_best_days": gap_to_best,
        "note": "推荐按跨天气 minimax regret 选，允许不是本档延误最小；两者差值一并报，不藏"}


async def _l4_agent(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    from api.routes.chat_routes import _select_tool_names_for_message
    hits = 0
    misses: List[Dict[str, Any]] = []
    for q, expected in ROUTING_GOLDEN:
        try:
            chosen = await _select_tool_names_for_message(q)
        except Exception as exc:
            chosen = set()
            misses.append({"question": q, "error": type(exc).__name__})
            continue
        if expected in chosen:
            hits += 1
        else:
            misses.append({"question": q, "expected": expected, "chosen": sorted(chosen)[:6]})
    stats = (await db.execute(text("""
        SELECT COUNT(*) FILTER (WHERE role='assistant' AND content IS NOT NULL AND content <> '') AS assistants,
               COUNT(*) FILTER (WHERE role='assistant' AND COALESCE(tool_calls::text,'[]') NOT IN ('[]','null','')) AS with_tools,
               COUNT(*) FILTER (WHERE role='assistant' AND tool_calls::text LIKE '%"result"%'
                                     AND COALESCE(content,'') <> '') AS answerable
        FROM chat_messages WHERE created_at > NOW() - INTERVAL '30 days'
    """))).mappings().first()
    assistants = int((stats or {}).get("assistants") or 0)
    with_tools = int((stats or {}).get("with_tools") or 0)
    backing = round(with_tools / assistants, 3) if assistants else None
    # "回答里的数有没有出处"：抽最近带工具结果的回答，把正文里的数字逐个回查 tool_results 原文
    turn_rows = (await db.execute(text("""
        SELECT data::text AS d FROM chat_events
        WHERE event_type = 'item/completed' AND data::text LIKE '%tool_call_count%'
          AND created_at > NOW() - INTERVAL '30 days' ORDER BY created_at DESC LIMIT 400
    """))).mappings().all()
    with_call = without_call = 0
    for tr in turn_rows:
        try:
            n = int(json.loads(tr["d"]).get("tool_call_count") or 0)
        except (TypeError, ValueError):
            continue
        with_call += 1 if n > 0 else 0
        without_call += 1 if n == 0 else 0
    turn_backing = round(with_call / max(1, with_call + without_call), 3)
    # 「回答里的数有没有出处」：工具返回原文一直存在 chat_messages.tool_calls[].result
    # （tool_results 那列没有单独再写一遍 —— 同一份 JSON 存两遍会把写入量翻倍，没必要）。
    # 判据按**会话**算而不是按单条算：上一轮查到的数这一轮引用是正常且必要的，
    # 只有整个会话里都找不到出处的数才是编出来的。年份/日期不计入（"2026" 不是引用数据）。
    # 出处语料要分两条：工具返回（引擎给的数）与用户自己说的话（人给的数）。
    # 把用户刚报的数当"无出处编造"是误判，把正文里复述的数字当"有出处"是放水 ——
    # 所以两边分开存、分开算，用户给的那一类不进判线分母，单列报出来给人看。
    hist = (await db.execute(text("""
        SELECT session_id, role, content, tool_calls::text AS tc, created_at
        FROM chat_messages
        WHERE role IN ('assistant', 'user') AND COALESCE(content,'') <> ''
          AND created_at > NOW() - INTERVAL '30 days'
        ORDER BY session_id, created_at, id
    """))).mappings().all()
    from core.kernel.reply_sanitizer import number_backing, numeric_claims

    corpus: Dict[str, str] = {}
    asked: Dict[str, str] = {}
    rows: List[Dict[str, Any]] = []
    after_note: List[bool] = []
    for r in hist:
        sid = str(r.get("session_id"))
        if str(r.get("role") or "") == "user":
            asked[sid] = (asked.get(sid, "") + " " + str(r.get("content") or ""))[-40000:]
            continue
        tc = str(r.get("tc") or "").replace(",", "")
        nums = numeric_claims(r.get("content"))
        prior = corpus.get(sid, "")
        if len(prior) > 120000:          # 语料只留最近一段，判据要的是"能不能回溯"不是全文检索
            prior = prior[-120000:]
        if nums:
            # 判线本体在 kernel 的 number_backing —— 人的总结格调的是同一个函数，
            # 不许这里再写第二条"多少算过线"的规则（同名两把尺就是这么长出来的）。
            rows.append({"claims": [str(n) for n in nums],
                         "reply": str(r.get("content") or ""),
                         "turn": tc, "history": prior, "user": asked.get(sid, ""),
                         "session": sid[:8],
                         # 这一轮真发生了工具调用（不管数是不是从它里面来的）
                         "tool_bearing": bool(tc.strip(' \"{}[]null'))})
            stamp = r.get("created_at")
            after_note.append(bool(stamp) and stamp.replace(tzinfo=None) >= PROVENANCE_NOTE_SINCE)
        corpus[sid] = (prior + " " + tc)[-160000:]
    stats = number_backing(rows)
    since = number_backing([row for row, flag in zip(rows, after_note) if flag])
    checked = int(stats["replies_judged"])
    from_user = int(stats["replies_user_only"])
    number_rate = stats["number_backing_rate"]
    same_turn = int(stats["claims_same_turn"])
    from_history = int(stats["claims_from_history"])
    disclosed = int(stats["claims_disclosed"])
    unbacked_total = int(stats["claims_unbacked"])
    # 只在"进了判线分母"的答复里数本轮真调工具的条数：全部报人给的数的答复不算分母，
    # 也不能算分子（否则「报数轮次里本轮真查的比例」会被抬上去）。
    claims_with_tool = sum(1 for item in stats["per_reply"]
                           if rows[int(item["index"])].get("tool_bearing"))
    unbacked_before_note = unbacked_total - int(since["claims_unbacked"])
    since_checked = int(since["claims_total"])
    since_ok = since_checked - int(since["claims_unbacked"])
    unbacked_samples: List[Dict[str, Any]] = []
    for item in stats["per_reply"]:
        if item["disclosed"] or not item["unbacked"]:
            continue
        if len(unbacked_samples) >= 6:
            break
        src = rows[int(item["index"])]
        unbacked_samples.append({
            "session": src.get("session"), "numbers": item["unbacked"][:5],
            "backed_within_reply": round(item["backed"] / max(1, item["total"]), 2),
            "excerpt": re.sub(r"\s+", " ", str(src.get("reply") or ""))[:110],
        })
    contract, contract_error = {}, None
    try:
        from api.services.engine_contract import self_check as contract_self_check

        contract = await contract_self_check(db, factory_id)
    except Exception as exc:
        contract_error = f"{type(exc).__name__}: {exc}"
    tried = contract.get("internal_names_tried") or []
    return {"metrics": [
        _metric("契约泄漏内部标识数", contract.get("internal_token_leaks"),
                THRESHOLDS["L4"]["contract_leaks"], "lte", "处",
                "响应里把内部 kwarg 名/节点/工位当接口名用的键数。破了就意味着 agent 会照内部名传参，"
                "引擎内部一改它就崩"
                + (f"（自检失败：{contract_error}）" if contract_error else ""),
                missing=("契约自检没跑成：" + contract_error if contract_error else None)),
        _metric("契约信封违规数", contract.get("envelope_violations"),
                THRESHOLDS["L4"]["envelope_violations"], "lte", "处",
                "数没带单位/依据，或说算不出却没点名缺什么"),
        _metric("内部参数名被拒率",
                (round(contract.get("internal_names_rejected", 0) / max(1, len(tried)), 3)
                 if contract else None),
                THRESHOLDS["L4"]["internal_names_rejected"], "gte", "",
                f"拿 {len(tried)} 个内部 kwarg 名当参数传进来，被结构化拒绝的比例 —— "
                "接口必须是封闭词表，静默忽略等于把内部结构当公共接口"),
        _metric("问题→查询准确率", round(hits / len(ROUTING_GOLDEN), 3),
                THRESHOLDS["L4"]["routing_accuracy"], "gte", "",
                f"{hits}/{len(ROUTING_GOLDEN)} 条自然问法命中应选工具（回归集在 ROUTING_GOLDEN）"),
        _metric("助手回复里调过工具的比例（只报数）", backing, None, "gte", "",
                f"近 30 天 {assistants} 条助手回复里 {with_tools} 条真调了工具。"
                "这一格和下面那格是同一个毛口径的两件外衣，都不再当判据 —— "
                "分母里全是追问、确认、引用前轮这些本来就不该查库的回复；"
                "要判的是「报了数的回复有没有出处」，看「报数轮次里本轮真查的比例」和「回答数字可回溯率」"),
        _metric("报数轮次里本轮真查的比例",
                round(claims_with_tool / checked, 3) if checked else None,
                THRESHOLDS["L4"]["tool_backing_rate"], "gte", "",
                f"近 30 天 {checked} 条「引擎自己给数」的回复里，{claims_with_tool} 条本轮真调了工具"
                f" = {round(claims_with_tool / max(1, checked), 3)}。分母从「所有完成轮」换成「报了数的轮」："
                "判据要管的是「给数必须有出处」，不是「每轮都得调一次工具」—— 追问、确认、"
                "用户自己报数的轮次调工具没有意义（近 30 天没调工具的回复里 76% 根本没给数字）",
                n=checked, min_n=20,
                missing=(None if checked >= 20 else
                         f"报数回复只有 {checked} 条（判线要 ≥20 条）：样本太少不判"),),
        _metric("所有完成轮里调工具的比例（只报数）", turn_backing, None, "gte", "",
                f"近 30 天 {with_call + without_call} 个完成轮里 {with_call} 个发生过工具调用。"
                "这一格不再当判据：里面一大半是不需要查库的轮次（追问/确认/引用前轮），"
                "拿它判线只会逼人为了调工具而调工具"),
        _metric("回答数字可回溯率", number_rate, THRESHOLDS["L4"]["number_backing_rate"], "gte", "",
                f"近 30 天 {checked} 条**引擎自己给数**的助手回复里，逐个数出来的：正文共 {stats['claims_total']} 个读数，"
                f"本轮工具返回里查到 {same_turn} 个、引用本会话前几轮 {from_history} 个、"
                f"答复自己已标注未经核实 {disclosed} 个、查无字面出处 {unbacked_total} 个。"
                "**判线按读数条数（每个数一票），不按答复条数** —— 这个名字说的就是"
                "「数字可回溯」，10-09 之前这里按「整条答复 ≥60% 的数有出处」判（0.904 判过线），"
                "人的总结格按「整条答复的数全部有出处」判（0.891 判不过线），同一段对话在同一页上又绿又红；"
                "两条都不是名字说的那件事，现在收成 kernel 里的一份函数（number_backing），"
                "按答复算的降级成只报数（见下一格）。另有 "
                f"{from_user} 条报的全是用户自己刚给的数，从判线分母里拿出来单列；年份/日期/ID 片段不算引用数据",
                n=checked, min_n=20,
                missing=(None if checked >= 20 else
                         f"可比回复只有 {checked} 条（判线要 ≥20 条）：样本太少不判"),),
        _metric("整条答复一个查无出处的数都没有的比例（只报数）",
                stats["reply_clean_rate"], None, "gte", "",
                f"{checked} 条报数回复里 {checked - stats['replies_with_unbacked']} 条"
                f"（{stats['reply_clean_rate']}）通篇读数都能回溯。这一格刻意**不判线**："
                "它把「一张 60 行的表里有 1 个派生数没落进工具返回」和「整段都在编」算成同一个扣分，"
                "量出来的是模型写了多少个数，不是有没有出处。10-09 实测三套口径："
                f"按读数 {number_rate}、按答复全中 {stats['reply_clean_rate']}、"
                "按答复六成放行 0.904（那条 0.6 的常数没人按业务定过，已废）"),
        _metric("报的是用户自己给的数（不进判线分母）", from_user if checked else None, None,
                "gte", "条",
                f"{from_user} 条：正文里的数字全部能在用户自己的话里找到 —— 人给的数不需要引擎核实，"
                "但也不许算进「可回溯」把上面那个率抬上去。这一格存在是为了让判线分母说得出是什么"),
        _metric("标注上线以来的数字可回溯率",
                (round(since_ok / since_checked, 3) if since_checked else None),
                THRESHOLDS["L4"]["number_backing_rate"], "gte", "",
                f"只看 {PROVENANCE_NOTE_SINCE:%Y-%m-%d %H:%M} UTC（提交 22c71493，标注挂上 kernel 出口）"
                f"之后的 {since['replies_judged']} 条答复、{since_checked} 个读数："
                f"能回溯 {since_ok} 个，查无出处 {since['claims_unbacked']} 个。"
                f"判线那格里 {unbacked_total} 个无出处读数有 {unbacked_before_note} 个早于这次上线 —— "
                "它们在为历史扣分，不该被当成现在还在编数；这一格攒够 20 个读数才顶上去判线",
                n=since_checked, min_n=20,
                missing=(None if since_checked >= 20 else
                         f"上线后只有 {since_checked} 个可比读数（判线要 ≥20 个）：样本太少不判"),),
        _metric("本轮工具直查率", (round(same_turn / stats["claims_total"], 3)
                                  if stats["claims_total"] else None), None, "gte", "",
                f"{same_turn}/{stats['claims_total']} 个读数直接来自当轮工具返回（引用前几轮也算可回溯，"
                f"但这一格低说明模型在复述而不是重新核实）；已披露 "
                f"{round(disclosed / max(1, stats['claims_total']), 3)}（{disclosed} 个写明了未经核实）"),
    ], "routing_misses": misses, "unbacked_samples": unbacked_samples,
        "provenance_note": ("工具返回原文存在 chat_messages.tool_calls[].result；"
                            "tool_results 列没用起来（同一份 JSON 不打算存两遍）")}


def summarize(report: Dict[str, Any]) -> Dict[str, Any]:
    g = gate(report)
    lines = []
    for lid in LAYER_ORDER:
        m = (report.get(lid) or {}).get("metrics") or []
        fails = [x["metric"] for x in m if x.get("state") == "fail"]
        unknown = [x["metric"] for x in m if x.get("state") == "not_computable"]
        reported = [x["metric"] for x in m if x.get("state") == "reported"]
        lines.append({"layer": lid, "name": LAYER_NAMES[lid],
                      "pass": all(x.get("state") != "fail" for x in m) and any(
                          x.get("state") == "pass" for x in m),
                      "reportable": (report.get(lid) or {}).get("reportable"),
                      "quote_rule": (report.get(lid) or {}).get("quote_rule"),
                      "failed": fails, "not_computable": unknown, "reported": reported,
                      "metrics": m})
    return {"factory_id": report.get("factory_id"), "layers": lines, "gate": g,
            "rule": ("自下而上：每层都要有能算的数且过线；第一个不过线的层以上不许对外引用。"
                     "not_computable=真的算不出（点名缺哪个输入，不打分、不用别的数冒充），"
                     "reported=量出来了但这一格没有判线，两者不是一回事。")}


# 分层验收一次要 35~52 秒（L2A 的 bootstrap 重采样、L2B 的 70 单回测、L3 的 12 张
# 记分卡重跑都是真算），agent 与前端拿不动这个延迟：一轮对话等 50 秒等于没有这个功能。
# 所以按"厂区 + 机种集合 + 当天"缓存一份结果，默认 15 分钟；缓存命中如实标 from_cache，
# 并且提供 refresh 让"刚改完输入"的人立刻拿到新数 —— 不能让人对着缓存猜输入生效没有。
LAYERS_CACHE: Dict[tuple, tuple] = {}
LAYERS_CACHE_TTL_SECONDS = 900


def _layers_cache_key(factory_id: str, models: List[Any]) -> tuple:
    parts = []
    for m in models or []:
        if isinstance(m, dict):
            parts.append(f"{m.get('model_code')}:{m.get('units')}:{m.get('due_date')}")
        else:
            parts.append(str(m))
    return (str(factory_id), datetime.utcnow().date().isoformat(), "|".join(sorted(parts)))


async def layered_acceptance(db: AsyncSession, factory_id: str,
                              models: List[str], *,
                              use_cache: bool = True,
                              ttl_seconds: Optional[int] = None) -> Dict[str, Any]:
    """五层逐层自测。任何一层查崩了只让那一层 not_computable，不拖垮整份报告，
    也不许把事务打成脏的（那样后面四层会一起报同一个假错）。"""
    ttl = LAYERS_CACHE_TTL_SECONDS if ttl_seconds is None else int(ttl_seconds)
    key = _layers_cache_key(factory_id, models)
    hit = LAYERS_CACHE.get(key)
    if use_cache and hit:
        age = (datetime.utcnow() - hit[0]).total_seconds()
        if age <= ttl:
            cached = json.loads(hit[1])
            cached["cache"] = {"from_cache": True, "age_seconds": round(age, 1),
                               "ttl_seconds": ttl, "computed_at": hit[0].isoformat()}
            return cached

    report: Dict[str, Any] = {"factory_id": factory_id, "models": models}
    layers = (("L1", _l1_kernel(db, factory_id, models, None)),
              ("L2A", _l2a_sensitivity(db, factory_id, models, None)),
              ("L2B", _l2b_accuracy(db, factory_id, models)),
              ("L3", _l3_decision(db, factory_id, models)),
              ("L4", _l4_agent(db, factory_id)))
    for lid, coro in layers:
        try:
            report[lid] = await coro
        except Exception as exc:
            await db.rollback()
            report[lid] = {"metrics": [_metric("本层探针", None, None, "gte", "",
                                                f"探针失败：{type(exc).__name__}: {str(exc)[:160]}")]}
    out = summarize(report)
    out["detail"] = {k: v for k, v in report.items() if k in LAYER_ORDER}
    computed_at = datetime.utcnow()
    out["cache"] = {"from_cache": False, "age_seconds": 0.0, "ttl_seconds": ttl,
                    "computed_at": computed_at.isoformat()}
    LAYERS_CACHE[key] = (computed_at, json.dumps(out, ensure_ascii=False, default=str))
    return out
