"""该先量哪些件：把"数据不全"换成一张有优先级的活干清单。

台账提前期是按类别铺的默认值（机械厂 31,452 个外购料号只有 10 个取值），
但真正值得去量的不是这 3 万个，而是**决定开工日那一档**的那几十个件 ——
而且只量其中一个没用：并列最长档有 349 个件时，量 1 个交期一天也买不回来。

这个模块只回答三个问题，全部从库里算，不写任何表：
1. 每个在推演的机种，决定开工日的是哪一档、几个件、台账给的是几天；
2. 本厂有没有任何实测到货可以校准"台账偏乐观多少"（有就用，没有就明说不成立）；
3. 把这一档换成实测量级之后，交期差几天 —— 这就是值得花的人工核对量。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MEASURED_RATIO_SQL = text("""
    WITH po AS (
        SELECT material_code,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY (actual_date::date - order_date::date)) AS measured,
               count(*) AS n
        FROM purchase_orders
        WHERE factory_id = :fid AND order_date IS NOT NULL AND actual_date IS NOT NULL
          AND actual_date >= order_date
        GROUP BY material_code),
    led AS (SELECT material_code, lead_time_days, make_or_buy
            FROM materials WHERE factory_id = :fid)
    SELECT po.material_code, led.lead_time_days AS ledger_days, po.n, po.measured::float AS measured_days,
           led.make_or_buy AS make_or_buy,
           po.measured::float / NULLIF(led.lead_time_days, 0) AS ratio
    FROM po LEFT JOIN led ON led.material_code = po.material_code
    WHERE led.lead_time_days > 0
""")


def _median(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    ordered = sorted(vals)
    mid = len(ordered) // 2
    return round(float(ordered[mid]) if len(ordered) % 2
                 else (ordered[mid - 1] + ordered[mid]) / 2.0, 3)


async def lead_ratio_census(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """实测到货 ÷ 台账提前期：整厂一个数的唯一出处（交期承诺、分布锚定、优先级都从这里取）。

    两件事必须分开报：**中位数偏多少倍**（锚定该挪到哪）与**有多少条能当依据**。
    实测 0 天的行是收货记录缺失或同日进出，不是"快"，留着会同时把中位数往下拖、把极值往上抬；
    只有 1 张单的料号算样本不算依据。两者都不进 anchor。
    """
    rows = [(str(r["material_code"]), int(r["ledger_days"] or 0), float(r["measured_days"]),
             int(r["n"] or 0), float(r["ratio"]))
            for r in (await db.execute(MEASURED_RATIO_SQL, {"fid": factory_id})).mappings().all()
            if r["ratio"] is not None]
    nonzero = [x for x in rows if x[4] > 0]
    reliable = [x for x in nonzero if x[3] >= 2]
    nz_vals = [x[4] for x in nonzero]
    spread = sorted(nz_vals)
    return {
        "factory_id": factory_id, "rows": len(rows),
        "zero_ratio_rows": len(rows) - len(nonzero),
        "median_all": _median([x[4] for x in rows]),
        "median_nonzero": _median(nz_vals),
        "p25_nonzero": (round(float(spread[int(0.25 * (len(spread) - 1))]), 2) if spread else None),
        "p75_nonzero": (round(float(spread[int(0.75 * (len(spread) - 1))]), 2) if spread else None),
        "min_nonzero": (round(float(spread[0]), 2) if spread else None),
        "max_nonzero": (round(float(spread[-1]), 2) if spread else None),
        "reliable_rows": len(reliable),
        "anchor": _median(nz_vals),
        "examples": [{"material_code": x[0], "ledger_days": x[1], "measured_median_days": round(x[2], 1),
                      "po_count": x[3], "ratio": round(x[4], 2)} for x in reliable[:12]],
        "caveat": ("实测 0 天的行＝收货记录缺失或同日进出，不是快；单张单的料号只算样本不算依据。"
                   "两者都不进 anchor，所以 anchor 可能比『全部行的中位数』更极端 —— 那不是挑数据，"
                   "是不肯把缺失当观测"),
    }


LEDGER_BUY_COUNT_SQL = text("""
    SELECT count(*) AS n FROM materials
    WHERE factory_id = :fid AND make_or_buy = '外购'
      AND lead_time_days IS NOT NULL AND lead_time_days > 0
""")


async def measured_lead_factors(db: AsyncSession, factory_id: str, *,
                                min_po: int = 2) -> Dict[str, Any]:
    """hybrid 口径要的料号级乘子：量过的按自己的实测÷台账，没量过的保持台账。

    只给乘子，不猜值：没有实测的料号一个都不进 map，覆盖多少就说多少。
    分子分母同人群 —— 只算外购件，因为引擎只对缺料的外购行按提前期排到货日。
    """
    rows = [(str(r["material_code"]), float(r["measured_days"]), int(r["n"] or 0),
             float(r["ratio"]), str(r["make_or_buy"] or ""))
            for r in (await db.execute(MEASURED_RATIO_SQL, {"fid": factory_id})).mappings().all()
            if r["ratio"] is not None]
    usable = [(c, m, n, rt) for c, m, n, rt, kind in rows
              if rt > 0 and n >= int(min_po) and kind == "外购"]
    ledger = int((await db.execute(LEDGER_BUY_COUNT_SQL, {"fid": factory_id})).scalar() or 0)
    return {
        "factory_id": factory_id,
        "factors": {c: round(rt, 4) for c, _m, _n, rt in usable},
        "measured_days": {c: round(m, 1) for c, m, _n, _rt in usable},
        "codes": len(usable), "ledger_rows_with_lead": ledger,
        "coverage": round(len(usable) / max(1, ledger), 6),
        "min_po": int(min_po),
        "caveat": ("map 里每一条都是这个料号自己的实测÷台账；其余料号按定义保持台账值。"
                   f"覆盖 {len(usable)}/{ledger} 行外购件 —— 覆盖低是事实，不是可以顺手抹平的东西"),
    }


async def measurement_priority(db: AsyncSession, factory_id: str,
                               models: Optional[List[str]] = None,
                               *, units: Optional[float] = None,
                               n_models: int = 5) -> Dict[str, Any]:
    """按机种给出"先量哪一档、值几天"，并说清校准依据来自几个料号。"""
    from api.services import virtual_run as vr

    today = date.today()
    chosen = [str(m) for m in (models or [])] or await vr.default_models(db, factory_id, n=n_models)
    census = await lead_ratio_census(db, factory_id)
    if census["rows"]:
        calibration = {"basis": "本厂采购下单→到货实测 ÷ 台账提前期，取非零行的中位数（唯一出处 lead_ratio_census）",
                       "n_materials": census["rows"], "median_ratio": census["median_nonzero"],
                       "median_all_rows": census["median_all"],
                       "zero_ratio_excluded": census["zero_ratio_rows"],
                       "reliable_rows": census["reliable_rows"],
                       "spread_nonzero": {"p25": census["p25_nonzero"], "p75": census["p75_nonzero"],
                                          "min": census["min_nonzero"], "max": census["max_nonzero"]},
                       "example": (census["examples"] or [None])[0],
                       "samples": census["examples"]}
        factor = max(1.0, float(census["median_nonzero"] or census["median_all"] or 0.0))
    else:
        calibration = {"basis": "本厂没有任何「下单→到货」的实测记录可用来校准 —— 下面的摆动天数是假设值",
                       "n_materials": 0, "median_ratio": None,
                       "assumed_factor": 2.0,
                       "note": "没有实测就没有资格说台账偏乐观多少倍，这里用 2.0 只作量级演示"}
        factor = 2.0

    per_model: List[Dict[str, Any]] = []
    lines = [dict(r) for r in (await db.execute(vr.LINES_SQL, {"fid": factory_id})).mappings().all()]
    shift_days = {int(r["weekday"]) + 1 for r in
                  (await db.execute(vr.CALENDAR_SQL, {"fid": factory_id})).mappings().all()} or {1, 2, 3, 4, 5, 6}
    att = await vr.measured_attendance(db, factory_id)
    curve = {d: float(att["present_ratio"]) for d in range(400)}
    cache: Dict[str, Any] = {}
    for model in chosen:
        try:
            exp = await vr.sim_bom_lines(db, factory_id, model, float(units or 1200))
            codes = [str(r["material_code"]) for r in exp["rows"]]
            stock_rows = (await db.execute(vr.STOCK_SQL, {"fid": factory_id, "codes": codes})).mappings().all() if codes else []
            stock = {str(r["material_code"]): float(r["available"] or 0) for r in stock_rows}
            kit = vr.build_kit(exp["rows"], float(units or 1200), stock, start_day=0)
        except Exception as exc:  # noqa: BLE001  一个机种查不动不影响整张清单
            per_model.append({"model_code": model, "error": f"{type(exc).__name__}: {exc}"[:160]})
            continue
        critical = kit.get("arrival_critical_parts") or []
        due = today + timedelta(days=max(14, int(kit.get("bottleneck_part", {}).get("lead_time_days") or 14) + 5))
        base = await vr.run_target(db, factory_id, model, float(units or 1200), due, today, curve,
                                   lines, shift_days, cached=cache)
        stressed = await vr.run_target(db, factory_id, model, float(units or 1200), due, today, curve,
                                        lines, shift_days, cached=cache, lead_multiplier=factor)
        slip = ((int(stressed.get("finish_day") or 0) - int(base.get("finish_day") or 0))
                if base.get("finish_day") is not None and stressed.get("finish_day") is not None else None)
        per_model.append({
            "model_code": model, "units": float(units or 1200),
            "bom_source": exp.get("source"),
            "short_buy_parts": sum(1 for l in kit["lines"] if l["short"] > 0 and l["make_or_buy"] == "外购"),
            "critical_tier_days": (critical[0]["arrival_day"] if critical else None),
            "critical_part_count": kit.get("arrival_critical_count") or len(critical),
            "second_tier_days": kit.get("second_arrival_day"),
            "ledger_days_in_tier": sorted({int(c.get("lead_time_days") or 0) for c in critical}),
            "parts_to_measure": critical[:20],
            "swing_days_if_measured": slip,
            "baseline_finish": base.get("finish_date"),
            "stressed_finish": stressed.get("finish_date"),
            "status": base.get("status"),
        })
    tiers = sum(int(p.get("critical_part_count") or 0) for p in per_model if not p.get("error"))
    return {
        "factory_id": factory_id, "models": len(per_model),
        "calibration": calibration, "factor_applied": round(factor, 2),
        "attendance_basis": att,
        "total_parts_in_critical_tiers": tiers,
        "per_model": per_model,
        "how_to_use": ("先把 critical_tier 那一档整批量出来（同一天到货的那批要一起量，"
                       "只量其中一个交期不动）；量出来的数走采购/收货实测，"
                       "不要直接覆盖 materials.lead_time_days —— 那里要留出处"),
        "rule": ("摆动天数 = 把这一档的提前期换成实测量级后完工日差几天。"
                 "校准比有中位数（实测÷台账）时它是有依据的；n_materials=0 时只是量级演示，"
                 "不能拿去跟人承诺。"),
    }
