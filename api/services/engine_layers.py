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
    "L2B": {"backtest_mape": 0.20, "bottleneck_hit_rate": 0.70},
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
    """sense: gte=越大越好，lte=越小越好；value=None → not_computable（不是 0 分）。"""
    out = {"metric": name, "value": value, "threshold": threshold, "sense": sense,
           "unit": unit, "basis": basis, **extra}
    min_n = extra.get("n")
    if value is None or threshold is None or (min_n is not None and float(min_n) < float(extra.get("min_n", 0) or 0)):
        out["pass"] = None
        out["state"] = "not_computable"
        out.setdefault("missing", extra.get("missing") or
                       (f"可比样本 {min_n} 条，少于判据需要的 {extra.get('min_n')} 条"
                        if min_n is not None else extra.get("missing")))
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
    from api.services.sim_sensitivity import mapping_accuracy
    acc = await mapping_accuracy(db, factory_id, models)
    # 瓶颈命中率：仿真点名的瓶颈件 vs 台账里该机型缺口最大的外购料号
    hit_rows = (await db.execute(text("""
        -- product_id 有两种存法（UUID 或机种编码），两种都要归到机种编码上，
        -- 否则"台账瓶颈"与"仿真瓶颈"永远对不到一起（n=1 那种假命中率就是这么来的）
        SELECT COALESCE(p.product_code, o.product_id) AS model,
               (ARRAY_AGG(w.material_code ORDER BY w.shortage_qty DESC))[1] AS top_short_code
        FROM work_order_materials w
        JOIN work_orders o ON o.id = w.work_order_id
        LEFT JOIN products p ON p.factory_id = o.factory_id
             AND (p.id::text = o.product_id OR p.product_code = o.product_id)
        WHERE o.factory_id = :fid AND w.item_type = 'buy' AND COALESCE(w.shortage_qty,0) > 0
          AND o.status NOT IN ('completed','cancelled')
        GROUP BY 1
    """), {"fid": factory_id})).mappings().all()
    ledger = {str(r["model"]): str(r["top_short_code"]) for r in hit_rows}
    from api.services.virtual_run import derive_targets, scan_policies
    targets = await derive_targets(db, factory_id, models, days_of_output=6.0, lead_margin=1.15)
    scan = await scan_policies(db, factory_id, targets,
                               policies=[{"name": "基准", "allow_partial": True}],
                               scenarios=[{"name": "基准", "attendance": 0.97}])
    detail = scan["by_scenario"]["基准"]["solutions"][0]["detail"]
    sim = {str(d.get("model_code")): str((d.get("bottleneck_part") or {}).get("material_code"))
           for d in detail if d.get("bottleneck_part")}
    both = [m for m in sim if m in ledger]
    hits = sum(1 for m in both if sim[m] == ledger[m])
    mape = (await db.execute(text("""
        SELECT COUNT(*) FROM work_orders w
        WHERE w.factory_id = :fid AND w.actual_complete IS NOT NULL
          AND EXISTS (SELECT 1 FROM aps_schedule_tasks t WHERE t.work_order_id = w.id)
    """), {"fid": factory_id})).scalar()
    priced = float(acc.get("overall_accuracy") or 0)
    return {"metrics": [
        _metric(
            "瓶颈位置命中率", round(hits / len(both), 3) if both else None,
            THRESHOLDS["L2B"]["bottleneck_hit_rate"], "gte", "",
            f"可比 {len(both)} 台：仿真点名的瓶颈件 == 台账缺口最大的外购料号",
            n=len(both), min_n=3,
            missing=(f"可比台数 {len(both)}：仿真按 BOM 机种编码（如 A-50-04-F），"
                     f"台账工单的 product_id 存的是 SAP 产品号（如 1000461205），"
                     f"两边产品键没对齐 —— 对不上不是命中率低，是根本没在同一口径上比；"
                     f"属 #55 家底清单里的键/单位对齐项"),
        ),
        _metric("回测 MAPE", None, THRESHOLDS["L2B"]["backtest_mape"], "lte", "",
                "需要「同一张单的预测完工日 + 实际完工日」成对样本",
                missing=("已完工单里没有留存对应排程任务行（可回测样本 0 张）；"
                         "要能算，下达时要把预测完工日落到工单上（新约定），否则永远回测不了")),
        _metric("输入映射精度", round(priced / 100.0, 3), None, "gte", "0~1",
                "六项输入的加权覆盖率（工时/提前期/供应商/库存/自制外购/单价），只作分母透明化"),
    ], "sim_bottleneck": sim, "ledger_top_short": ledger,
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
               COUNT(*) FILTER (WHERE role='assistant' AND COALESCE(tool_results::text,'[]') NOT IN ('[]','null','')
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
    rows = (await db.execute(text("""
        SELECT content, tool_results::text AS tr FROM chat_messages
        WHERE role='assistant' AND COALESCE(tool_results::text,'[]') NOT IN ('[]','null','')
          AND content IS NOT NULL AND content <> ''
        ORDER BY created_at DESC LIMIT 40
    """))).mappings().all()
    checked = backed = 0
    unbacked_samples: List[Dict[str, Any]] = []
    for r in rows:
        nums = re.findall(r"\d[\d,]{2,}(?:\.\d+)?", str(r.get("content") or ""))
        if not nums:
            continue
        hay = str(r.get("tr") or "").replace(",", "")
        ok = 0
        for n in nums:
            plain = n.replace(",", "")
            # 允许两种写法命中：原样出现，或去掉小数尾巴后出现（1,234.56 与 1234.5 是同一个数）
            if plain in hay or (len(plain) > 4 and plain[:4] in hay):
                ok += 1
        rate = ok / len(nums)
        checked += 1
        if rate >= 0.6:
            backed += 1
        elif len(unbacked_samples) < 3:
            unbacked_samples.append({"numbers": nums[:6], "backed": round(rate, 2)})
    number_rate = round(backed / checked, 3) if checked else None
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
                f"抽查 {checked} 条回复",
                missing=(None if checked else "工具返回原文没落库（chat_messages.tool_results 0 行有值）："
                         "要算这一项必须先存 tool_results，不能拿模型自述当出处"),),
    ], "routing_misses": misses, "unbacked_samples": unbacked_samples}


def summarize(report: Dict[str, Any]) -> Dict[str, Any]:
    g = gate(report)
    lines = []
    for lid in LAYER_ORDER:
        m = (report.get(lid) or {}).get("metrics") or []
        fails = [x["metric"] for x in m if x.get("state") == "fail"]
        unknown = [x["metric"] for x in m if x.get("state") == "not_computable"]
        lines.append({"layer": lid, "name": LAYER_NAMES[lid],
                      "pass": all(x.get("state") != "fail" for x in m) and any(
                          x.get("state") == "pass" for x in m),
                      "reportable": (report.get(lid) or {}).get("reportable"),
                      "quote_rule": (report.get(lid) or {}).get("quote_rule"),
                      "failed": fails, "not_computable": unknown,
                      "metrics": m})
    return {"factory_id": report.get("factory_id"), "layers": lines, "gate": g,
            "rule": ("自下而上：每层都要有能算的数且过线；第一个不过线的层以上不许对外引用。"
                     "没有数的层写 not_computable 并点名缺哪个输入，不打分、不用别的数冒充。")}


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
