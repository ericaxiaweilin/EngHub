"""分层验收：自下而上，每层一个能算的数，过不了线就不往上报。

平行堆指标最后会变成"我们全都做得好"的自嗨报告。所以这里规定死了：
· 每层的判据不一样，且必须是算出来的数（不是打分表）；
· 依赖关系是硬的：从最低一层往上找第一个不过线的，它**以上**的读数一律标 `not_reportable`；
· 算不出来的项写 `not_computable` 并点名缺哪个输入，不许用别的数冒充，也不许算 0 分。

五层（L1 内核 / L2A 敏感度 / L2B 准确度 / L3 决策 / L4 Agent 接口）。
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 阈值是我定的口径，每条都写清理由；要改改这里（或对应环境变量），不要改判据本身。
THRESHOLDS: Dict[str, Dict[str, float]] = {
    "L1": {"reproducible_rate": 1.0,        # 同输入不同结果 = 上面所有数都不可引用
           "p50_seconds": 120.0,            # 链条一轮预算 900 秒，内核最多占 1/8
           # 崩溃率判窗口不判累计：插桩前查不到成因的历史失败不该永久压住上层
           "crash_rate": 0.01, "crash_window_min_ticks": 12,
           # 心跳必须新鲜：这次心跳台账断写了几小时，库里所有读数都还在"上一次成功"上
           "heartbeat_alive_rate": 1.0},
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
           "flip_rate": 0.20},              # 推荐反复翻转说明结论不稳
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
    ("这版计划能开工几张", "query_plan_commit_gate"),
    ("库存健康度怎么样", "query_wms_inventory_health"),
    ("哪些料该补", "query_wms_inventory_health"),
    ("交期风险有哪些", "query_pmc_control_tower"),
]


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
        _metric("逐轮心跳新鲜率", hb_rate, THRESHOLDS["L1"]["heartbeat_alive_rate"], "gte", "比例",
                f"{len(ticking) - len(stale)}/{len(ticking)} 个已报过完整一轮的循环在 2 个间隔内跳过；"
                f"另有 {len(waiting)} 个刚启动还没跳过手（不判生死：{[w['loop'] for w in waiting]}）；"
                "心跳断写时台账里的每个数都停在最后一次成功上，比崩溃更隐蔽"
                + (f"（自检读取失败：{hb_error}）" if hb_error else ""),
                missing=(hb_error or (None if ticking else "没有任何循环在逐轮报心跳")),),
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
                "只报最差那个，供人看是哪条曲线量不出来"),
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
    priced = float(acc.get("overall_accuracy") or 0)
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
                "这一格量的是**两种需求算法点的第一名是否相同**，不是引擎准不准 —— "
                "三个解释里只剩一个成立：料号宇宙是同一批（台账行与引擎展开 100% 重合，"
                f"{univ.get('ledger_top_in_engine_bom', {}).get('agree')}/"
                f"{univ.get('ledger_top_in_engine_bom', {}).get('of')} 张单的台账第一件在引擎展开里），"
                f"快照过期不成立（把台账缺口按今天的库存重算，一致率仍 "
                f"{same_gen.get('qty_top_rate')}），"
                f"剩下的是算法差：{basis.get('engine_lower_than_ledger')}/"
                f"{basis.get('rows_paired')} 行引擎的需求量更低（其中 "
                f"{basis.get('engine_says_zero_ledger_asks_positive')} 行引擎判 0 = 父层够用就不往下炸），"
                f"更高的 {basis.get('engine_higher_than_ledger')} 行。要判准不准，得先把齐套行按同一算法刷一遍",
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
                "同一宇宙的分母才谈得上对错，剩下的分母是覆盖率问题"),
        _metric("BOM 取数来源", (agree.get("bom_sources") or [None])[0], None, "lte", "",
                f"这批可比单的仿真取数来自 {agree.get('bom_sources')}；"
                "镜像没有行的机种会如实回落本地 bom_items 并在每台单的读数里标注（见 sim-readiness）"),
        _metric("台账缺口行覆盖率", (round(agree.get("median_ledger_parts") / max(1, agree.get("median_shortage_parts") or 1), 3)
                  if agree.get("median_ledger_parts") is not None else None),
                THRESHOLDS["L2B"]["kit_line_coverage"], "gte", "比例",
                f"每张单台账里记录的缺口件数中位 {agree.get('median_ledger_parts')} 件 vs 引擎按真源 BOM "
                f"展开的缺口件数中位 {agree.get('median_shortage_parts')} 件 —— "
                "一致率与 top-5 重叠都被这个覆盖率封顶：台账只看得到一部分缺料行。"
                f"但盖子是**登记世代**不是源侧缺账 —— {order_n} 张里 {depth_txt}"
                f"（中位 {depth.get('median_buy_rows')} 行、最多 {depth.get('max_buy_rows')} 行；"
                "同一个机种按多层展开登记过的单能到 680 行、深 9 层），"
                "所以这一格要先重跑齐套登记（#30 那条路径）才谈得上命中率准不准；"
                "#46 只解释其中键在镜像里压根没有子 BOM 的那部分",
                missing=(None if agree.get("median_shortage_parts") else
                         "引擎没展开出缺口件，覆盖率无从计算")),
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
        _metric("输入映射精度", round(priced / 100.0, 3), None, "gte", "0~1",
                "六项输入的加权覆盖率（工时/提前期/供应商/库存/自制外购/单价），只作分母透明化"),
    ], "readiness": await _readiness(db, factory_id),
        "bottleneck_agreement": {k: v for k, v in agree.items() if k != "disagreements"},
        "sim_bottleneck": sim, "ledger_top_short": ledger,
        "ledger_short_lines": ledger_lines,
        "backtest_pairs": pairs[:12], "backtest_skipped": skipped,
        "backtest_pairs_available": int(mape or 0)}


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
        SELECT status, block_reason FROM followup_tasks
        WHERE factory_id = :fid AND payload->>'category' = 'simulation_recommendation'
    """), {"fid": factory_id})).mappings().all()
    # 引擎自己取代的不算人的态度；只有 done（人真采纳）与人工关闭才进分母
    mine = [r for r in human if "已被更新的推演推荐取代" not in str(r.get("block_reason") or "")]
    done = sum(1 for r in mine if str(r.get("status")) == "done")
    human_closed = sum(1 for r in mine if str(r.get("status")) == "cancelled")
    adoption = round(done / (done + human_closed), 3) if (done + human_closed) else None
    return {"metrics": [
        _metric("推荐相对基线的再跑差值（暴雨档）", gain, THRESHOLDS["L3"]["retest_improvement_days"], "gte", "天",
                "推荐政策比「现况」少延几天；0 = 推荐就是基线，决策层没有增量（差距另报 gap_to_best）"),
        _metric("人工采纳率", adoption, THRESHOLDS["L3"]["adoption_rate"], "gte", "",
                f"done {done} / (done {done} + 人工关闭 {human_closed})；引擎自己取代的 {len(human) - len(mine)} 条不计入"),
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
    hist = (await db.execute(text("""
        SELECT session_id, content, tool_calls::text AS tc
        FROM chat_messages
        WHERE role='assistant' AND COALESCE(content,'') <> ''
          AND created_at > NOW() - INTERVAL '30 days'
        ORDER BY session_id, created_at, id
    """))).mappings().all()
    from core.kernel.reply_sanitizer import numeric_claims

    corpus: Dict[str, str] = {}
    checked = same_turn = from_history = disclosed = 0
    unbacked_samples: List[Dict[str, Any]] = []
    for r in hist:
        sid = str(r.get("session_id"))
        tc = str(r.get("tc") or "").replace(",", "")
        nums = numeric_claims(r.get("content"))
        prior = corpus.get(sid, "")
        if len(prior) > 120000:          # 语料只留最近一段，判据要的是"能不能回溯"不是全文检索
            prior = prior[-120000:]
        if nums:
            def _hit(needle: str, hay: str) -> bool:
                return bool(hay) and (needle in hay or (len(needle) > 4 and needle[:4] in hay))
            now_ok = sum(1 for n in nums if _hit(n.replace(",", ""), tc))
            all_ok = sum(1 for n in nums if _hit(n.replace(",", ""), tc)
                         or _hit(n.replace(",", ""), prior))
            rate_now, rate_sess = now_ok / len(nums), all_ok / len(nums)
            checked += 1
            if rate_now >= 0.6:
                same_turn += 1
            elif rate_sess >= 0.6:
                from_history += 1
            elif "没有调用 MES 工具核实" in str(r.get("content") or ""):
                # 模型自己已经把"这些数没查过库"写在答复上了 —— 那是披露，不是编造。
                # 判据必须奖励披露，否则只会逼出"听起来像台账读数"的自信假话。
                disclosed += 1
            elif len(unbacked_samples) < 6:
                missing = [n for n in nums if not _hit(n.replace(",", ""), tc)
                           and not _hit(n.replace(",", ""), prior)]
                unbacked_samples.append({
                    "session": sid[:8], "numbers": missing[:5],
                    "backed_within_session": round(rate_sess, 2),
                    "excerpt": re.sub(r"\s+", " ", str(r.get("content") or ""))[:110],
                })
        corpus[sid] = (prior + " " + tc)[-160000:]
    number_rate = round((same_turn + from_history + disclosed) / checked, 3) if checked else None
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
        _metric("回答带仿真调用率", backing, THRESHOLDS["L4"]["tool_backing_rate"], "gte", "",
                f"近 30 天 {assistants} 条助手回复里 {with_tools} 条真调了工具"),
        _metric("每轮真调工具的比例", turn_backing, THRESHOLDS["L4"]["tool_backing_rate"], "gte", "",
                f"近 30 天 {with_call + without_call} 个完成轮里真发生工具调用的比例"),
        _metric("回答数字可回溯率", number_rate, THRESHOLDS["L4"]["number_backing_rate"], "gte", "",
                f"近 30 天 {checked} 条带数字的助手回复里，数字能在**本会话**工具返回里找到出处，"
                f"或答复自己已显式标注「未经工具核实」的比例"
                f"（本轮直查 {same_turn}、引用前几轮 {from_history}、已披露 {disclosed}）；"
                "年份/日期/ID 片段不算引用数据",
                n=checked, min_n=20,
                missing=(None if checked >= 20 else
                         f"可比回复只有 {checked} 条（判线要 ≥20 条）：样本太少不判"),),
        _metric("本轮工具直查率", round(same_turn / checked, 3) if checked else None, None, "gte", "",
                f"{same_turn}/{checked} 条：数字直接来自当轮工具返回（引用前轮结果也算可回溯，但这一格"
                f"低说明模型在复述而不是重新核实）；已披露率 {round(disclosed / max(1, checked), 3)}"
                f"（{disclosed} 条写明了未经核实）"),
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


async def layered_acceptance(db: AsyncSession, factory_id: str,
                              models: List[str]) -> Dict[str, Any]:
    """五层逐层自测。任何一层查崩了只让那一层 not_computable，不拖垮整份报告，
    也不许把事务打成脏的（那样后面四层会一起报同一个假错）。"""
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
    return out
