"""沙箱执行推演：引擎自己拆单、自己开购、自己按天推进，产出一条真实演变的时间线。

跟计算器的区别就在这里 —— 不是 `500 ÷ 300 = 1.7 天`，而是：

1. **没有工单就自己拆**：目标机种 + 数量 → 建一张沙箱工单（不落业务表，只在推演内存里）；
2. **没有路线就从同族借**：同前缀机种（FG-TREAD-*）已有工序序列就直接沿用，并打标
   `borrowed_route_from_family` —— 借来的是依据，不是猜，必须在结果里看得见；
3. **没有工时就用线节拍反推**：`line_profiles.hours_per_day / units_per_day` 给占用秒，打标 `takt_from_line`;
4. **料不够就开采购**：按 `materials.lead_time_days` 逐料号算到货日，自制件递归往下拆一层；
   到货日决定最早开工日 —— 于是"等料"和"生产"是两段时间，不再混成一个天数；
5. **按天推进**：每天先见到货、再看该线班组到岗（天气折算出勤）、再占产能开工、报工、完工入库；
   线空着的日子记成闲置并计价，因为人已经在岗。

输出一条动作时间线（引擎做了什么决策）+ 结果（哪天交、延几天、等料几天、用工多少、多少钱）
+ 分数（交付/人力/齐套/成本）。所有数字都带出处；确实没有依据的（比如没有单价）就明说不折算。
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from core.mes.route_resolution import route_ops_for_product
from core.mes.data_evidence import lead_flags
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_ATTENDANCE_RATE = 0.97
DEFAULT_LABOR_COST_PER_PERSON_DAY = float(os.getenv("SIM_LABOR_COST_PER_PERSON_DAY", "30"))
# 加急对价：每件每天提前一天要多付的钱（库里没有运费/加急费率，这是内置标定，结果里标明 basis）
SIM_EXPEDITE_COST_PER_UNIT_DAY = float(os.getenv("SIM_EXPEDITE_COST_PER_UNIT_DAY", "0.15"))
# 开第二条线的代价：多一套班组、多一份管理幅度。库里没有这条费率，按"整线班组×班时"标定。
SIM_LINE_ACTIVATION_COST_PER_DAY = float(os.getenv("SIM_LINE_ACTIVATION_COST_PER_DAY", "4500"))


LOAD_HEALTHY_BAND = (0.60, 0.90)


def peak_load_ratio(bottleneck_lead: int, due: date, today: date, units: float,
                    units_per_day: float, parallel_lines: int,
                    attendance_curve: Dict[int, float]) -> float:
    """要赶上交期，每天必须做多少台 ÷ 这段时间实际能做多少台。

    料要在第 N 天才齐，能用的天数就被压短；短到每天要做的台数超过线的实际产能，
    这个比值就 >1（得加班或开第二条线）。比"1/出勤率"有信息量得多，也不会让"多开线"白拿分。
    """
    if units_per_day <= 0 or units <= 0:
        return 0.0
    total_days = max(1, (due - today).days)
    usable_days = max(1, total_days - max(0, int(bottleneck_lead)))
    attend = sum(attendance_curve.get(d, 1.0) for d in range(total_days)) / max(1, total_days)
    available = units_per_day * max(1, int(parallel_lines)) * attend * usable_days
    return round(units / available, 4) if available > 0 else 99.0


def load_band_gap(ratio: float) -> float:
    """离健康区间有多远：区间内 = 0，越偏离越大。这样"多开线把人闲下来"要付分。"""
    lo, hi = LOAD_HEALTHY_BAND
    if ratio < lo:
        return round(lo - ratio, 4)
    if ratio > hi:
        return round((ratio - hi) / (1 - hi) * lo, 4)     # 超载侧按剩余缓冲折算
    return 0.0


def kit_lead_of(kit: Dict[str, Any]) -> int:
    part = kit.get("bottleneck_part") or {}
    return int(part.get("lead_time_days") or 0)
MAX_MAKE_DEPTH = int(os.getenv("SIM_MAX_MAKE_DEPTH", "2"))
IDLE_COST_WEIGHT = float(os.getenv("SIM_IDLE_COST_WEIGHT", "1.0"))

BOM_SQL = text("""
    SELECT b.material_code, b.material_name, b.unit, COALESCE(b.qty_per_unit, b.quantity, 0) AS qty_per_unit,
           b.unit_price, b.total_cost, m.make_or_buy, m.lead_time_days, m.default_supplier
    FROM bom_items b
    LEFT JOIN materials m ON m.material_code = b.material_code AND m.factory_id = b.factory_id
    WHERE b.factory_id = :fid AND b.product_id = :model
""")

BOM_ATTR_SQL = text("""
    SELECT x.code AS material_code, m.material_name, m.unit, m.make_or_buy,
           m.lead_time_days, m.default_supplier, p.unit_price
    FROM unnest(CAST(:codes AS text[])) AS x(code)
    LEFT JOIN materials m ON m.material_code = x.code AND m.factory_id = :fid
    LEFT JOIN (SELECT part_number, MAX(unit_price) AS unit_price
                 FROM enghub_bom_items WHERE factory_id = :fid GROUP BY 1) p
           ON p.part_number = x.code
""")

_ITEM_TYPE_CN = {"buy": "外购", "make": "自制"}


async def sim_bom_lines(db: AsyncSession, factory_id: str, model: str,
                        units: float) -> Dict[str, Any]:
    """BOM 取数一律经 bom_source：镜像多层 → 镜像 level-1 → 本地 bom_items。

    以前这里直接查 `bom_items`，而本厂的 `bom_items` 是 1,055 行 RM-* 合成料号
    （SAP 料号 0 行），真结构 861 行在 engflow 镜像里 —— 仿真于是拿着演示 BOM 推真实工厂，
    点名的瓶颈件永远对不上台账。回落不是错误，但必须说清用的是哪一头、镜像展开有哪些行接不上父级。
    """
    from api.services import bom_source as bs

    units = max(1e-6, float(units or 0))
    exp = await bs.explode_requirement(db, factory_id, model, units)
    lines = [r for r in ((exp or {}).get("lines") or []) if r.get("material_code")]
    source = "engflow_mirror_multi_level" if lines else None
    problems = list((exp or {}).get("problems") or [])
    if not lines:
        mirror_rows, src = await bs.latest_bom_lines(db, factory_id, model)
        if src == "engflow_mirror" and mirror_rows:
            lines = [{"material_code": r["material_code"],
                      "material_name": r.get("material_name"), "unit": r.get("unit"),
                      "required_qty": float(r.get("qty_per_unit") or 0) * units,
                      "item_type": None} for r in mirror_rows]
            source = "engflow_mirror_level1"
    if lines:
        codes = [str(r["material_code"]) for r in lines]
        attrs = {str(r["material_code"]): dict(r) for r in
                 (await db.execute(BOM_ATTR_SQL, {"fid": factory_id, "codes": codes})).mappings().all()}
        # 提前期是引擎点瓶颈件时吃的唯一数字。它要是按类别铺出来的默认值，推演就得自己说清楚，
        # 不能让"延 6 天"这种结论顶着一条没有任何实测的 12 天出场（实测：全厂外购料号只有 10 个取值）。
        flags = await lead_flags(db, factory_id, codes)
        rows = []
        for r in lines:
            code = str(r["material_code"])
            a = attrs.get(code) or {}
            kind = (_ITEM_TYPE_CN.get(str(r.get("item_type") or ""), None)
                    or str(a.get("make_or_buy") or "unknown"))
            rows.append({"material_code": code,
                         "material_name": r.get("material_name") or a.get("material_name") or code,
                         "unit": r.get("unit") or a.get("unit") or "pcs",
                         "qty_per_unit": round(float(r.get("required_qty") or 0) / units, 6),
                         "make_or_buy": kind,
                         "lead_time_days": a.get("lead_time_days"),
                         "default_supplier": a.get("default_supplier"),
                         "unit_price": (r.get("unit_price") if r.get("unit_price") is not None
                                        else a.get("unit_price")),
                         "lead_evidence": flags.get(code)})
        return {"rows": rows, "source": source, "problems": problems,
                "lead_evidence_counts": {k: sum(1 for x in rows if x.get("lead_evidence") == k)
                                         for k in set(x.get("lead_evidence") for x in rows) - {None}},
                "levels": (exp or {}).get("max_level"), "parts": (exp or {}).get("parts"),
                "buy_parts": (exp or {}).get("buy_parts"), "make_parts": (exp or {}).get("make_parts")}

    rows = [dict(r) for r in (await db.execute(
        BOM_SQL, {"fid": factory_id, "model": model})).mappings().all()]
    fb_flags = await lead_flags(db, factory_id, [str(r.get("material_code")) for r in rows])
    for r in rows:
        r["lead_evidence"] = fb_flags.get(str(r.get("material_code")))
    return {"rows": rows, "source": ("mes_bom_items" if rows else "none"),
            "problems": (["engflow 镜像与本地 bom_items 都没有这个型号的物料清单"] if not rows else []),
            "levels": None, "parts": len(rows), "buy_parts": None, "make_parts": None}


async def sim_part_lead_days(db: AsyncSession, factory_id: str, part: str) -> List[int]:
    """自制子件的到货/产出前置：同样经 bom_source，不再直查本地合成表。"""
    got = await sim_bom_lines(db, factory_id, part, 1.0)
    return [int(r["lead_time_days"]) for r in got["rows"]
            if str(r.get("lead_time_days") or "").isdigit()]

STOCK_SQL = text("""
    SELECT i.material_code, SUM(GREATEST(COALESCE(i.available_qty, 0), 0)) AS available
    FROM inventory i
    WHERE i.factory_id = :fid AND i.material_code = ANY(CAST(:codes AS text[]))
    GROUP BY i.material_code
""")

LINES_SQL = text("""
    SELECT line_code, line_group, hours_per_day, units_per_day, group_units_per_day, crew_size,
           can_make_models::text AS can_models, cannot_make_models::text AS cannot_models, default_model
    FROM line_profiles WHERE factory_id = :fid AND is_active = true ORDER BY line_code
""")

FAMILY_ROUTE_SQL = text("""
    SELECT w.product_id AS from_model, s.seq, s.operation_name, s.work_center, s.standard_hours
    FROM work_orders w
    JOIN routing_template_steps s ON s.template_id::text = w.routing_template_id::text
    WHERE w.factory_id = :fid AND w.product_id LIKE :prefix AND COALESCE(s.standard_hours, 0) > 0
    ORDER BY s.seq LIMIT 40
    """)

CALENDAR_SQL = text("""
    SELECT DISTINCT day_of_week AS weekday FROM aps_work_calendars
    WHERE (factory_id = :fid OR factory_id = 'default') AND is_active = true
""")

# 这条线已经排了多少活：能做的机种的开放工单计划量之和（按声明日产能折算占用天数）
LINE_COMMITMENT_SQL = text("""
    SELECT COALESCE(SUM(w.planned_qty), 0) AS committed_units
    FROM work_orders w
    WHERE w.factory_id = :fid AND w.wo_type = 'master'
      AND w.status IN ('pending', 'released', 'in_progress')
      AND w.product_id = ANY(CAST(:models AS text[]))
""")

# 工位级产能的两读：站点自己声明的每小时产量，与「在册人数 × 60 / IE 工时」的人数读法。
# 两个都当上界用（取下界），因为哪个是真的厂里没定过 —— 取大的就是把没定的口径当量过的
STATION_CAP_SQL = text("""
    SELECT station_code, station_name, station_type, capacity AS headcount, capacity_unit,
           capacity_per_hour
    FROM stations WHERE factory_id = :fid AND COALESCE(status, 'active') = 'active'
""")

# 标称班时=行数最多那个班次的打卡中位（与 attendance_evidence 同一口径，这里只要这一个数）
SHIFT_HOURS_SQL = text("""
    WITH top_shift AS (
        SELECT shift FROM attendance
        WHERE factory_id = :fid AND check_in IS NOT NULL AND check_out IS NOT NULL
          AND check_out > check_in
        GROUP BY 1 ORDER BY count(*) DESC LIMIT 1
    )
    SELECT percentile_cont(0.5) WITHIN GROUP (
               ORDER BY EXTRACT(EPOCH FROM (a.check_out - a.check_in)) / 3600.0) AS median_hours,
           count(*) AS n, (SELECT shift FROM top_shift) AS shift
    FROM attendance a JOIN top_shift t ON t.shift = a.shift
    WHERE a.factory_id = :fid AND a.check_in IS NOT NULL AND a.check_out IS NOT NULL
      AND a.check_out > a.check_in
""")


EQUIP_RATE_SQL = text("""
    SELECT COUNT(*) FILTER (WHERE status = 'running') AS running,
           COUNT(*) AS total
    FROM equipment WHERE factory_id = :fid
""")


def declared_models(line: Dict[str, Any]) -> List[str]:
    raw = str(line.get("can_models") or "")
    return [m.strip().strip("'").strip("\\") for m in raw.strip("{}").split(",") if m.strip()]


async def line_committed_days(db: AsyncSession, factory_id: str, line: Dict[str, Any]) -> Dict[str, Any]:
    """该线已承诺工单占掉多少天产线 —— 没有这一步，沙箱就是在一条"凭空空出来"的线上排新单。"""
    models = declared_models(line)
    if not models:
        return {"committed_units": 0.0, "busy_days": 0.0}
    row = (await db.execute(LINE_COMMITMENT_SQL,
                            {"fid": factory_id, "models": models})).mappings().first()
    units = float((row or {}).get("committed_units") or 0)
    per_day = float(line.get("units_per_day") or 0) or 1.0
    return {"committed_units": units, "busy_days": round(units / per_day, 2)}


async def equipment_rate(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """设备可用率：停着 9 台保养、1 台故障，产线就不可能按满配跑。"""
    row = (await db.execute(EQUIP_RATE_SQL, {"fid": factory_id})).mappings().first()
    total = int((row or {}).get("total") or 0)
    running = int((row or {}).get("running") or 0)
    return {"running": running, "total": total,
            "rate": round(running / total, 4) if total else 1.0}


PART_BOM_SQL = text("""
    SELECT b.material_code, COALESCE(b.qty_per_unit, b.quantity, 0) AS qty_per_unit,
           m.make_or_buy, m.lead_time_days
    FROM bom_items b
    LEFT JOIN materials m ON m.material_code = b.material_code AND m.factory_id = b.factory_id
    WHERE b.factory_id = :fid AND b.product_id = :part
""")


def family_prefix(model: str) -> str:
    """FG-TREAD-003 → FG-TREAD-%：同族机种共用工艺形状是厂里的常态。"""
    parts = str(model).split("-")
    return "-".join(parts[:2]) + "-%" if len(parts) >= 3 else f"{model}%"


# 系统里唯一的换型数字来自 APS 默认值（300 秒/次）；厂里没有换型台账，所以这是下限而不是实测。
SIM_CHANGEOVER_HOURS = float(os.getenv("SIM_CHANGEOVER_HOURS", "0.0833"))


def line_declares_cannot(line: Dict[str, Any], model: str) -> bool:
    """厂里明确写了"这条线做不了这台机"就不许再排上去 —— 负向声明优先于正向。

    `line_profiles.cannot_make_models` 是专门放这个的列（现在 3 条线都还是空 `{}`，
    所以"跑步机线不能做 bike"目前只靠正向白名单隐式表达）。以前 LINES_SQL 根本没取这列，
    于是 IE 哪怕填了也会被静默忽略：声明"不能做"和"没说"在系统里变成同一件事。
    """
    return str(model or "") in str((line or {}).get("cannot_models") or "")


def capable_lines(model: str, lines: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], str]]:
    """能接这个机种的线，按依据强弱排序：先排除厂里声明做不了的，再按 can_make_models、
    default_model、同族前缀。

    这是"能不能改派到别条线"的唯一口径 —— `pick_line` 和改派逻辑必须共用它，
    否则会出现"首选线没人在岗、改派却挑了一条工艺上做不了这台机的线"。
    """
    lines = [l for l in lines if not line_declares_cannot(l, model)]
    cands: List[Tuple[Dict[str, Any], str]] = []
    for l in lines:
        if model in str(l["can_models"]):
            cands.append((l, "line_declared_can_make" if l["default_model"] != model else "line_declared_home"))
    for l in lines:
        if str(l["default_model"] or "") == model:
            cands.append((l, "line_declared_default_model"))
    stem = str(model).split("-")[1] if "-" in str(model) else ""
    for l in lines:
        if stem and stem in str(l["line_code"]):
            cands.append((l, "line_inferred_by_family_name"))
    seen: List[str] = []
    ordered: List[Tuple[Dict[str, Any], str]] = []
    for l, basis in cands:
        code = str(l["line_code"])
        if code not in seen:
            seen.append(code)
            ordered.append((l, basis))
    return ordered


def pick_line(model: str, lines: List[Dict[str, Any]]) -> tuple:
    """取工艺上最能接这台机的线（不看人在不在岗）。返回 (线, 依据)。"""
    cands = capable_lines(model, lines)
    return cands[0] if cands else (None, "no_line")


def normalize_staffing(raw: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """把外部传来的"每条线到岗比例"收成 {线编码: 0~1}。

    越界按截断处理并记进 audit（0.5 是"一半人没来"，150 是传错了单位 —— 后者必须看得见，
    否则整盘推演会被一个手滑的输入悄悄改光）。未在线台账里的编码也留痕，不当没发生。
    """
    out: Dict[str, float] = {}
    for k, v in (raw or {}).items():
        code = str(k or "").strip()
        if not code:
            continue
        try:
            ratio = float(v)
        except (TypeError, ValueError):
            ratio = 1.0
        out[code] = max(0.0, min(1.0, ratio))
    return out


def pick_staffed_line(model: str, lines: List[Dict[str, Any]],
                      staffing: Dict[str, float]) -> Dict[str, Any]:
    """物理规则：这条线一个人都没来 → 这台机不能排在这条线上，改派到工艺上同样能做的下一条；
    所有能做的线都没人 → 只能等（不编日期）。到岗不满 1 但不为 0 的线仍然接活，
    人头的损失由 `crew` 折算进产能（见 run_target），不在这里改路由。
    """
    cands = capable_lines(model, lines)
    if not cands:
        return {"line": None, "basis": "no_line", "rerouted_from": None,
                "present_ratio": None, "candidates": []}
    known = {str(l["line_code"]) for l in lines}
    audit = {"checked_lines": sorted(known),
             "unknown_line_codes": sorted(set(staffing) - known)}
    if not staffing:
        line, basis = cands[0]
        return {"line": line, "basis": basis, "rerouted_from": None,
                "present_ratio": 1.0, "candidates": [], **audit}
    for i, (line, basis) in enumerate(cands):
        ratio = float(staffing.get(str(line["line_code"]), 1.0))
        if ratio > 0:
            return {"line": line, "basis": basis,
                    "rerouted_from": str(cands[0][0]["line_code"]) if i else None,
                    "present_ratio": ratio,
                    "candidates": [{"line_code": str(l["line_code"]),
                                    "present_ratio": float(staffing.get(str(l["line_code"]), 1.0))}
                                   for l, _ in cands],
                    **audit}
    return {"line": None, "basis": "all_capable_lines_unstaffed",
            "rerouted_from": None, "present_ratio": 0.0,
            "candidates": [{"line_code": str(l["line_code"]),
                            "present_ratio": float(staffing.get(str(l["line_code"]), 1.0))}
                           for l, _ in cands],
            **audit}


def resolve_route(route_own: List[Dict[str, Any]], family_rows: List[Dict[str, Any]]) -> tuple:
    if route_own:
        return route_own, "own_route"
    if family_rows:
        borrowed = [{"operation_name": r["operation_name"], "work_center": r["work_center"],
                     "standard_hours": float(r["standard_hours"] or 0)} for r in family_rows]
        return borrowed, "borrowed_route_from_family"
    return [], "no_route"


def hours_per_unit_from(route: List[Dict[str, Any]], line: Optional[Dict[str, Any]]) -> tuple:
    """单件占用工时：路线给的分钟优先；没有就用线节拍（一天做多少台、一天几个班时）。"""
    declared = round(sum(float(o.get("standard_hours") or 0) for o in route), 4)
    if declared > 0:
        return declared, "route_standard_hours"
    if line and float(line["units_per_day"] or 0) > 0:
        hpd = float(line["hours_per_day"] or 11) or 11.0
        return round(hpd / float(line["units_per_day"]), 4), "takt_from_line_capacity"
    return 0.0, "no_time_basis"


def build_kit(bom: List[Dict[str, Any]], units: float, stock: Dict[str, float],
              start_day: int, *, lead_multiplier: float = 1.0,
              stock_multiplier: float = 1.0) -> Dict[str, Any]:
    """齐套与到货计划：外购按提前期到料，自制件先记 needing（由子件满足）。"""
    lines: List[Dict[str, Any]] = []
    buy_arrival_days: List[int] = []
    kit_lead_max: List[Optional[int]] = [None]
    kit_bottleneck: List[Optional[Dict[str, Any]]] = [None]
    blockers: List[str] = []
    cost = 0.0
    cost_unknown = 0.0
    for row in bom:
        code = str(row["material_code"])
        need = float(row["qty_per_unit"] or 0) * float(units)
        if need <= 0:
            continue
        have = float(stock.get(code, 0.0)) * max(0.0, float(stock_multiplier))
        short = max(0.0, need - have)
        kind = str(row["make_or_buy"] or "unknown")
        lead = row["lead_time_days"]
        price = row["unit_price"]
        unit_cost = float(price) if price not in (None, "") else None
        entry = {
            "material_code": code, "need": round(need, 3), "have": round(have, 3),
            "short": round(short, 3), "make_or_buy": kind,
            "supplier": row["default_supplier"] or None,
            "lead_time_days": lead,
            "lead_evidence": row.get("lead_evidence"),
        }
        if unit_cost is not None:
            cost += unit_cost * need
        else:
            cost_unknown += 1
        if short > 0 and str(lead or "").isdigit() and kind == "外购":
            lead_days = max(0, int(round(int(lead) * max(0.0, float(lead_multiplier)))))
            if lead_days >= (kit_lead_max[0] or -1):
                kit_lead_max[0] = lead_days
                kit_bottleneck[0] = {"material_code": code, "lead_time_days": lead_days,
                                     "ledger_lead_time_days": lead,
                                     "lead_evidence": row.get("lead_evidence"),
                                     "short": round(short, 3),
                                     "supplier": row["default_supplier"] or None,
                                     "unit_price": (float(price) if price not in (None, "") else None)}
        if short > 0:
            if kind == "外购":
                if str(lead or "").isdigit() and int(lead) >= 0:
                    scaled = max(0, int(round(int(lead) * max(0.0, float(lead_multiplier)))))
                    arrival_day = start_day + scaled
                    buy_arrival_days.append(arrival_day)
                    entry["arrival_day"] = arrival_day
                    entry["action"] = f"开采购 {round(short, 3)}，{scaled} 天后到"
                else:
                    entry["action"] = "外购缺料但没有提前期 → 无法排到货日"
                    blockers.append(f"{code} 无提前期")
            elif kind == "自制":
                entry["action"] = f"拆自制子件工单 {round(short, 3)}"
            else:
                entry["action"] = "采购属性未知 → 不假设有货，列为主数据缺口"
                blockers.append(f"{code} 未标自制/外购")
        lines.append(entry)
    # "先去量哪几个件"要能回答：决定开工日的是**最长那批到货日**，并列的几个必须一起量 ——
    # 只量其中一个，second_arrival_day 还是同一天，交期一天也买不回来。
    arrival_pairs = sorted(
        [(int(l.get("arrival_day")), l) for l in lines
         if l.get("make_or_buy") == "外购" and l.get("short", 0) > 0 and l.get("arrival_day") is not None],
        key=lambda x: -x[0])
    top_arrival = arrival_pairs[0][0] if arrival_pairs else None
    critical_parts = [{"material_code": str(l["material_code"]), "arrival_day": d,
                       "lead_time_days": l.get("lead_time_days"),
                       "lead_evidence": l.get("lead_evidence"),
                       "short": l.get("short")} for d, l in arrival_pairs
                      if top_arrival is not None and d == top_arrival][:20]
    lower = [d for d, _ in arrival_pairs if top_arrival is not None and d < top_arrival]
    second_arrival = lower[0] if lower else None
    return {"lines": lines, "buy_arrival_days": buy_arrival_days,
            "arrival_critical_parts": critical_parts,
            "arrival_critical_count": sum(1 for d, _ in arrival_pairs
                                          if top_arrival is not None and d == top_arrival),
            "second_arrival_day": second_arrival,
            "bottleneck_part": kit_bottleneck[0],
            "blockers": blockers, "material_cost": round(cost, 2),
            "materials_without_price": int(cost_unknown)}


def simulate_days(units: float, hours_per_unit: float, hours_per_day: float,
                  crew: float, attendance_by_day: Dict[int, float], shift_days: set,
                  earliest_start: int, cap_per_day: float, today: date) -> Dict[str, Any]:
    """按天推进：等料 → 开工 → 每天占产能、扣班组 → 完工。等料的日子记闲置并计价。"""
    # 人是这条线的瓶颈（跑步机线 300 人配 300 台/天 = 一台一份人力），
    # 所以到岗不足时产能必须一起降：暴雨只来 7 成人，一天就不可能还是 300 台。
    # 不绑人力的装配线可以以后按线打标放开，现在按声明的 人数:台数 比例算。
    units_per_day = cap_per_day if cap_per_day > 0 else (   # cap_per_day 已经把工时上限取过 min
        max(1.0, hours_per_day / hours_per_unit) if hours_per_unit > 0 else 0.0)
    remaining = float(units)
    day = 0
    started_on: Optional[int] = None
    weekday_of = lambda d: (today + timedelta(days=d)).isoweekday()
    wait_days = 0
    work_days = 0
    person_days = 0.0
    idle_person_days = 0.0
    timeline: List[Dict[str, Any]] = []
    while day < 400 and remaining > 1e-9:
        is_shift = weekday_of(day) in shift_days
        if day < earliest_start:
            if is_shift:
                wait_days += 1
                idle_person_days += crew * attendance_by_day.get(day, 1.0)
            day += 1
            continue
        if not is_shift:
            day += 1
            continue
        if started_on is None:
            started_on = day
            timeline.append({"day": day, "action": "开工", "units_today": 0})
        present = crew * attendance_by_day.get(day, 1.0)
        capacity_today = (units_per_day * min(1.0, present / crew)) if (crew > 0 and units_per_day) else units_per_day
        if capacity_today <= 0:
            capacity_today = units_per_day or 1.0
        make = min(remaining, capacity_today)
        remaining -= make
        work_days += 1
        person_days += present
        timeline.append({"day": day, "action": "报工完工入库", "units_today": round(make, 1),
                         "people_present": round(present, 1), "remaining": round(remaining, 1)})
        day += 1
    return {"started_on_day": started_on, "finished_on_day": (day - 1) if remaining <= 1e-9 else None,
            "wait_days": wait_days, "work_days": work_days,
            "person_days": round(person_days, 1), "idle_person_days_before_start": round(idle_person_days, 1),
            "completed": remaining <= 1e-9, "timeline": timeline}


async def load_family_route(db: AsyncSession, factory_id: str, model: str) -> List[Dict[str, Any]]:
    rows = (await db.execute(FAMILY_ROUTE_SQL,
                             {"fid": factory_id, "prefix": family_prefix(model)})).mappings().all()
    seen, out = set(), []
    for r in rows:
        if r["operation_name"] in seen:
            continue
        seen.add(r["operation_name"])
        out.append(dict(r))
    return out


def staffing_clamped(raw: Optional[Dict[str, Any]], norm: Dict[str, float]) -> List[Dict[str, Any]]:
    """把被截断的输入原样列出来：0.5 是"一半人没来"，150 是传错了单位 —— 后者必须看得见，
    否则一个手滑的输入会把整盘推演悄悄改光，而结果里读不出任何异常。"""
    out: List[Dict[str, Any]] = []
    for k, v in (raw or {}).items():
        code = str(k or "").strip()
        if not code:
            continue
        try:
            ratio = float(v)
        except (TypeError, ValueError):
            out.append({"line_code": code, "raw": str(v), "applied": norm.get(code, 1.0),
                        "reason": "不是数字，按 1.0（没请假）处理"})
            continue
        if abs(ratio - norm.get(code, 1.0)) > 1e-9:
            out.append({"line_code": code, "raw": ratio, "applied": norm[code],
                        "reason": "截断到 0~1（到岗比例是分数，人数请换算成比例）"})
    return out


def staffing_crew_factor(lines: List[Dict[str, Any]], line: Dict[str, Any],
                         parallel_lines: int,
                         staffing: Dict[str, float]) -> Tuple[float, List[Dict[str, Any]]]:
    """这条线（组）真正要用到的班组里，按人数加权的平均到岗比例。

    成员取法必须与 `group_capacity` 一致（同组前 n 条），否则人数和产能按两套口径折，
    并联开线时会出现"产能按 2 条线算、人却按 1 条线扣"。没传 staffing 就是 1.0 —— 老行为一字不变。
    """
    if not staffing or not line:
        return 1.0, []
    n = max(1, int(parallel_lines))
    group = str(line.get("line_group") or "")
    if n <= 1 or not group:
        members = [line]
    else:
        members = [l for l in lines if str(l.get("line_group") or "") == group][:n] or [line]
    ratios = [{"line_code": str(l.get("line_code")),
               "crew": float(l.get("crew_size") or 0),
               "present_ratio": float(staffing.get(str(l.get("line_code")), 1.0))} for l in members]
    weight = sum(r["crew"] for r in ratios)
    if weight <= 0:
        return (sum(r["present_ratio"] for r in ratios) / len(ratios) if ratios else 1.0), ratios
    return sum(r["crew"] * r["present_ratio"] for r in ratios) / weight, ratios


async def load_station_capacity(db: AsyncSession, factory_id: str,
                                cached: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """站点档案 + 实测标称班时，一次取好给整轮推演复用（同一个 cached 字典）。"""
    cache = cached if cached is not None else {}
    if "_stations" not in cache:
        rows = (await db.execute(STATION_CAP_SQL, {"fid": factory_id})).mappings().all()
        cache["_stations"] = {str(r["station_code"]): dict(r) for r in rows}
    if "_shift_hours" not in cache:
        got = (await db.execute(SHIFT_HOURS_SQL, {"fid": factory_id})).mappings().first()
        cache["_shift_hours"] = {"hours": (round(float(got["median_hours"]), 2) if got and got["median_hours"]
                                           else None),
                                 "shift": str(got["shift"]) if got else None,
                                 "n": int(got["n"] or 0) if got else 0}
    return {"stations": cache["_stations"], "shift_hours": cache["_shift_hours"]}


def station_route_capacity(route_ops: List[Dict[str, Any]], stations: Dict[str, Dict[str, Any]],
                           hours_per_day: float) -> Dict[str, Any]:
    """按工位路线算日产能：每个站取「站点声明的每小时产量」与「在册人数×60/IE工时」的下界，
    再取整条路线最紧的那个站。

    为什么是下界：capacity_per_hour 在组立一线=110（110 人 → 像每人每件每小时），
    在焊接车间=4（218 人 → 只能是整站读数）—— 同一列在两种站里是两种口径。
    哪个是真的厂里没定过，取大的就等于替厂里把这个口径拍定了。
    """
    per_station, missing = [], []
    for op in route_ops or []:
        wc = str(op.get("work_center") or "").strip()
        if not wc:
            continue
        st = stations.get(wc)
        hours = float(op.get("standard_hours") or 0.0)
        if not st:
            missing.append(wc)
            continue
        declared = float(st.get("capacity_per_hour") or 0.0)
        headcount = float(st.get("headcount") or 0.0) if str(st.get("capacity_unit") or "") == "人" else 0.0
        people_bound = (headcount * 60.0 / hours) if (hours > 0 and headcount > 0) else 0.0
        bounds = [b for b in (declared, people_bound) if b > 0]
        if not bounds:
            missing.append(wc)
            continue
        bound = min(bounds)
        per_station.append({
            "station": wc, "station_name": st.get("station_name"), "operation": op.get("operation_name"),
            "ie_hours_per_unit": round(hours, 4), "declared_per_hour": declared,
            "headcount": headcount, "people_bound_per_hour": round(people_bound, 2),
            "used_bound_per_hour": round(bound, 2), "units_per_day": round(bound * hours_per_day, 2),
            "conflict_ratio": (round(max(bounds) / min(bounds), 1) if len(bounds) > 1 and min(bounds) > 0 else None),
            "used_read": ("declared" if bounds and bound == declared else "headcount×IE"),
        })
    total_ops = len([o for o in (route_ops or []) if str(o.get("work_center") or "").strip()])
    if not per_station:
        return {"units_per_day": None,
                "why": "路线里的工序都对不上有档案的工位 → 不给工位级产能（"
                       + (f"缺档工位：{'、'.join(sorted(set(missing)))}" if missing else "路线没有 work_center") + "）",
                "missing_stations": sorted(set(missing))}
    bottleneck = min(per_station, key=lambda x: x["units_per_day"])
    return {
        "covered_operations": f"{len(per_station)}/{total_ops} 道工序",
        "incomplete": bool(missing) or len(per_station) < total_ops,
        "units_per_day": bottleneck["units_per_day"],
        "bottleneck_station": bottleneck["station"],
        "bottleneck_headcount": bottleneck["headcount"],
        "per_station": per_station,
        "missing_stations": sorted(set(missing)),
        "hours_per_day": hours_per_day,
        "basis": ("工位级下界 = min(站点声明台/小时, 在册人数×60/IE工时) × 实测标称班时。"
                  "取下界不是因为保守，是因为「人数×IE」这一读法假设全站人数都扑在这道工序上 —— "
                  "那是理论上界，不是可达产能；两读法差多少见 two_reads_conflict"),
        "conflict_meaning": ("矛盾倍数 = 理论上界 / 站点声明。差到几千倍说明 capacity 列是车间在册总人数、"
                             "不是这道工序的占用人数 —— 所以真正卡产能的是站点自己声明的那个数"),
        "two_reads_conflict": [f"{x['station']}:{x['conflict_ratio']}×" for x in per_station
                               if (x.get("conflict_ratio") or 0) > 1.5],
    }


async def run_target(db: AsyncSession, factory_id: str, model: str, units: float,
                     due: date, today: date, attendance_curve: Dict[int, float],
                     lines: List[Dict[str, Any]], shift_days: set,
                     expedite_lead_days: Optional[int] = None, allow_partial: bool = True,
                     parallel_lines: int = 1, crew_bonus: float = 0.0,
                     cached: Optional[Dict[str, Any]] = None,
                     line_busy_days: float = 0.0, equip_rate: float = 1.0,
                     hours_multiplier: float = 1.0, lead_multiplier: float = 1.0,
                     stock_multiplier: float = 1.0, batches: int = 1,
                     changeover_hours: float = 0.0,
                     line_staffing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把一个目标跑成一条演变时间线。"""
    cache = (cached or {}).get(model)
    if not cache:
        got = await sim_bom_lines(db, factory_id, model, units)
        bom = got["rows"]
        codes = [str(r["material_code"]) for r in bom]
        stock_rows = (await db.execute(STOCK_SQL, {"fid": factory_id, "codes": codes})).mappings().all() if codes else []
        stock = {str(r["material_code"]): float(r["available"] or 0) for r in stock_rows}
        route_own = await route_ops_for_product(db, factory_id, model)
        family_rows = [] if route_own else await load_family_route(db, factory_id, model)
        cache = {"bom": bom, "stock": stock,
                 "route_own": [dict(o) for o in route_own], "family_rows": family_rows,
                 "bom_source": got["source"], "bom_problems": got["problems"],
                 "bom_levels": got["levels"], "bom_parts": got["parts"]}
    bom, stock = cache["bom"], cache["stock"]
    route_own, family_rows = cache["route_own"], cache["family_rows"]
    bom_source_label = cache.get("bom_source")
    bom_problems = cache.get("bom_problems") or []
    bom_parts = cache.get("bom_parts")
    bom_levels = cache.get("bom_levels")
    route, route_basis = resolve_route(list(route_own), family_rows)
    staffing = normalize_staffing(line_staffing)
    choice = pick_staffed_line(model, lines, staffing)
    line, line_basis = choice["line"], choice["basis"]
    hours_per_unit, hours_basis = hours_per_unit_from(route, line)
    if hours_per_unit:
        hours_per_unit = round(hours_per_unit * max(0.05, float(hours_multiplier)), 6)

    kit = build_kit(bom, units, stock, start_day=0, lead_multiplier=lead_multiplier,
                    stock_multiplier=stock_multiplier)
    if expedite_lead_days is not None and kit["bottleneck_part"]:
        kit["buy_arrival_days"] = [expedite_lead_days if d == kit["bottleneck_part"]["lead_time_days"] else d
                                   for d in kit["buy_arrival_days"]]
    arrival = max(kit["buy_arrival_days"], default=0)
    self_made_children = [l for l in kit["lines"] if l["short"] > 0 and l["make_or_buy"] == "自制"]

    # 自制件要先做出来：按同一条线排队，占的是同一段时间（递归一层，深度有上限）
    child_days = 0
    for child in self_made_children[:MAX_MAKE_DEPTH]:
        leads = await sim_part_lead_days(db, factory_id, str(child["material_code"]))
        child_days = max(child_days, (max(leads) + 1) if leads else 0)

    # 开工要排在三件事之后：料齐、子件做完、这条线手上已承诺的活干完
    earliest_start = max(arrival, child_days, int(line_busy_days))
    # 工艺上能接这台机的线全都一个人都没来 —— 这不是"厂里做不到"，是这段时间没人可做，
    # 结论只能是等：不给完工日、不给延期天数，更不许把产能摊到一条根本没人的线上。
    if line is None and staffing and choice["basis"] == "all_capable_lines_unstaffed":
        idle = "、".join(f"{c['line_code']}（到岗 {c['present_ratio']:.0%}）"
                         for c in (choice["candidates"] or []))
        return {"model_code": model, "units": units, "status": "no_staffed_line",
                "why": f"能这道工艺的线都没人在岗：{idle} → 只能等开工，不推演完工日",
                "route_basis": route_basis, "line_basis": line_basis,
                "staffing": {"requested": True, "input": staffing,
                             "clamped": staffing_clamped(line_staffing, staffing),
                             "rerouted_from": None, "candidates": choice["candidates"],
                             "checked_lines": choice["checked_lines"],
                             "unknown_line_codes": choice["unknown_line_codes"],
                             "by_line": [], "present_ratio": 0.0,
                             "action": "改线（别的线有人）或等人（都没人）—— 引擎不替厂里选放假"},
                "kit": {k: kit[k] for k in ("buy_arrival_days", "blockers", "material_cost",
                                            "materials_without_price")},
                "due": str(due)}

    if hours_basis == "no_time_basis":
        return {"model_code": model, "units": units, "status": "no_time_basis",
                "why": "既没有路线工时，也没有可归属的线节拍（线都没声明能做它）",
                "route_basis": route_basis, "line_basis": line_basis,
                "kit": {k: kit[k] for k in ("buy_arrival_days", "blockers", "material_cost",
                                            "materials_without_price")},
                "due": str(due)}

    hours_per_day = float((line or {}).get("hours_per_day") or 11)
    group_cap = group_capacity(lines, line or {}, parallel_lines)
    station_cap = None
    if line is None:
        # 没有线档案不等于算不出产能：路线上的工位有在册人数、有声明台/小时、班时是打卡量出来的
        census = await load_station_capacity(db, factory_id, cache)
        shift = census["shift_hours"]
        hours = float(shift.get("hours") or 0.0)
        if hours > 0:
            hours_per_day = hours
        station_cap = station_route_capacity(route, census["stations"], hours or hours_per_day)
        if station_cap.get("units_per_day"):
            group_cap = {"units_per_day": station_cap["units_per_day"],
                         "capacity_basis": f"station_bound({station_cap['bottleneck_station']})"}
            # crew 用工时读法里那个站的人数：到岗曲线乘的就是它，人力动作这才乘得上
            group_cap["crew"] = station_cap.get("bottleneck_headcount") or 0.0
            group_cap["note"] = (f"按工位路线取下界：{station_cap['basis']}；"
                                 f"标称班时 {hours or hours_per_day}h 是 {shift.get('shift')} "
                                 f"{shift.get('n')} 行打卡的中位（不是声明值）")
        else:
            group_cap = {**group_cap, "capacity_basis": "no_line_profile",
                         "note": ("这台机种没有任何线档案认领，路线上的工位也都对不上有档案的站"
                                  f"（{station_cap.get('why')}）→ 日产能没有被约束，"
                                  "时间线只由路线工时 + 来料日推出来；加班/借人/双班/工况扣人乘不上")}
    else:
        station_cap = None
    present, present_by_line = staffing_crew_factor(lines, line or {}, parallel_lines, staffing)
    crew = round(group_cap["crew"] * (1.0 + crew_bonus) * present, 1)
    cap_line = round(group_cap["units_per_day"] * max(0.1, min(1.0, equip_rate)), 2)  # 设备可用率折进日产能
    caps = capacity_limits(crew=crew, hours_per_day=hours_per_day, hours_per_unit=hours_per_unit,
                           line_declared=cap_line)
    cap, capacity_binding = caps["units_per_day"], caps["binding"]
    cap_hours = caps["hours_implied"]

    # 引擎的决策（不是计算器会做的事）：现料能做几台就先开几台，剩下的排在到货日之后
    coverable = []
    for l in kit["lines"]:
        per = float(l["need"] / units) if units else 0.0
        coverable.append(int(l["have"] / per) if per > 0 else int(units))
    stock_units = min(coverable, default=0)
    batch_a = min(int(units), max(0, stock_units)) if allow_partial else 0
    batch_b = int(units) - batch_a
    decision = (
        f"现料够先做 {batch_a} 台（第 0 天开工），剩余 {batch_b} 台等料"
        if batch_a and batch_b else
        f"现料够一次做完 {batch_a} 台" if batch_a and not batch_b else
        f"现料一台都开不了，整批 {int(units)} 台等到货日第 {earliest_start} 天开工")

    run_a = simulate_days(batch_a, hours_per_unit, hours_per_day, crew, attendance_curve,
                          shift_days, 0, cap, today) if batch_a else None
    a_finish = (run_a or {}).get("finished_on_day")
    start_b = max((int(a_finish) + 1) if a_finish is not None else 0, earliest_start)
    run_b = simulate_days(batch_b, hours_per_unit, hours_per_day, crew, attendance_curve,
                          shift_days, start_b, cap, today) if batch_b else None
    run = run_b or run_a
    finish_day = run["finished_on_day"]
    finish_date = today + timedelta(days=finish_day) if finish_day is not None else None
    late = (finish_day - (due - today).days) if finish_day is not None else None

    # 同一张单拆成 k 批投放：总量不变，每多一批就多一次换型（系统里唯一的换型数字是 APS 默认 300 秒）。
    # 这个模型只算换型工时，不含搬运/清线/再齐套 —— 所以它只能证伪"拆批免费"，不能证明"拆批免费"。
    extra_releases = max(0, int(batches) - 1)
    changeover_days = round(extra_releases * (float(changeover_hours) / hours_per_day), 3) \
        if (changeover_hours and hours_per_day) else 0.0
    finish_day_out = (round(finish_day + changeover_days) if finish_day is not None else None)
    finish_date_out = (today + timedelta(days=finish_day_out)) if finish_day_out is not None else None
    person_days_out = round(run["person_days"] + changeover_days * crew, 1)
    labor_cost = round(person_days_out * DEFAULT_LABOR_COST_PER_PERSON_DAY, 2)
    binding_terms = []
    if arrival >= max(int(line_busy_days), child_days) and arrival > 0:
        binding_terms.append("material_arrival")
    if int(line_busy_days) > arrival:
        binding_terms.append("group_queue")
    if capacity_binding == "ie_hours":
        binding_terms.append("work_content_hours")
    if not binding_terms:
        binding_terms.append("work_duration")

    return {
        "model_code": model, "units": units, "status": "simulated",
        "binding_terms": binding_terms,
        "bom_source": bom_source_label, "bom_parts": bom_parts, "bom_levels": bom_levels,
        "bom_problems": bom_problems,
        "route_steps": len(route), "route_basis": route_basis,
        "line": (line or {}).get("line_code"), "line_basis": line_basis,
        "staffing": {"requested": bool(staffing), "input": staffing,
                     "clamped": staffing_clamped(line_staffing, staffing),
                     "line": (line or {}).get("line_code"),
                     "present_ratio": round(present, 4),
                     "crew_before_staffing": round(group_cap["crew"] * (1.0 + crew_bonus), 1),
                     "crew_effective": crew,
                     "rerouted_from": choice.get("rerouted_from"),
                     "candidates": choice.get("candidates") or [],
                     "checked_lines": choice.get("checked_lines") or [],
                     "unknown_line_codes": choice.get("unknown_line_codes") or [],
                     "by_line": present_by_line,
                     "note": ("到岗比例按人数折算进班组，产能再取 min(线声明台/天, 班组按 IE 工时做得完的台/天)；"
                              "它与天气出勤曲线是两笔独立扣减（曲线按天、这条按线常驻缺口），会叠乘。")},
        "hours_per_unit": hours_per_unit, "hours_basis": hours_basis,
        "earliest_start_day": earliest_start,
        "material_arrival_day": arrival,
        "self_made_children_days": child_days,
        "batch_a_units": batch_a, "batch_b_units": batch_b, "batch_decision": decision,
        "batch_a_finish_day": a_finish,
        "wait_days_for_material": (run_a or {"wait_days": 0})["wait_days"] + run["wait_days"],
        "work_days": run["work_days"],
        "started_on_day": run["started_on_day"],
        "finish_day": finish_day_out, "finish_date": str(finish_date_out) if finish_date_out is not None else None,
        "raw_finish_day": finish_day, "raw_finish_date": str(finish_date) if finish_date else None,
        "batches_released": int(batches), "changeover_days_added": changeover_days,
        "changeover_hours_per_release": float(changeover_hours),
        "due_date": str(due),
        "days_late": ((finish_day_out - (due - today).days) if finish_day_out is not None else None),
        "people_present_avg": round(run["person_days"] / run["work_days"], 1) if run["work_days"] else None,
        "person_days": person_days_out,
        "idle_person_days_before_start": run["idle_person_days_before_start"],
        "labor_cost_usd": labor_cost,
        "standby_person_days_if_line_held": run["idle_person_days_before_start"],
        "standby_cost_if_line_held_usd": round(run["idle_person_days_before_start"]
                                               * DEFAULT_LABOR_COST_PER_PERSON_DAY * IDLE_COST_WEIGHT, 2),
        "bottleneck_part": kit["bottleneck_part"],
        "arrival_critical_parts": kit.get("arrival_critical_parts"),
        "arrival_critical_count": kit.get("arrival_critical_count"),
        "second_arrival_day": kit.get("second_arrival_day"),
        # 峰值负载 = 需要的相对人力。健康是 0.70~0.95：太低是养闲，太高没有缓冲。
        # 不能写成"越低越好"，否则引擎会永远多开线（那条线的代价没人付）。
        "load_band_gap": load_band_gap(peak_load_ratio(kit_lead_of(kit), due, today, units,
                                                        float((line or {}).get("units_per_day") or 0),
                                                        parallel_lines, attendance_curve)),
        "line_activation_cost_usd": (max(1, int(parallel_lines)) - 1) * SIM_LINE_ACTIVATION_COST_PER_DAY
                                    * max(1, int(run.get("work_days") or 1)),
        "expedite_cost_usd": (round(float(units) * max(0, (kit_lead_of(kit) - expedite_lead_days))
                                    * SIM_EXPEDITE_COST_PER_UNIT_DAY, 2)
                              if expedite_lead_days is not None and kit.get("bottleneck_part") else 0.0),
        "evidence": {route_basis: len(route) or 1,
                    hours_basis: len(route) or 1,
                    line_basis: 1},
        "policy": {"allow_partial": allow_partial, "parallel_lines": parallel_lines,
                   "crew_bonus": crew_bonus, "expedite_lead_days": expedite_lead_days,
                   "line_staffing": staffing},
        "line_busy_days_before_order": line_busy_days,
        "equipment_rate_applied": round(equip_rate, 4),
        "capacity_after_equipment": cap,
        "capacity_basis": group_cap["capacity_basis"],
        "station_capacity": (station_cap if (line is None and station_cap) else None),
        "capacity_binding": capacity_binding,
        "capacity_line_declared": cap_line, "capacity_hours_implied": cap_hours,
        "standby_note": ("等料那几天这条线是空的；只有把整班人守着这条线才算损失。"
                         "厂里还有几百张单没排，空档可以承接 —— 所以这笔是上限，不是必然发生的钱。"),
        "material_cost_usd": kit["material_cost"],
        "materials_without_price": kit["materials_without_price"],
        "kit_shortage_lines": sum(1 for l in kit["lines"] if l["short"] > 0),
        "kit_lines": len(kit["lines"]),
        "blockers": kit["blockers"],
        "actions": [a for a in run["timeline"]][:40],
        "po_lines": [l for l in kit["lines"] if l["short"] > 0 and l["make_or_buy"] == "外购"][:12],
    }


# 厂里真会对外承诺的交期口径：瓶颈件提前期 × 这个系数。标定可以放宽去找有信息量的区间，
# 但比承诺还宽的场景只能当诊断，不能拿它的"准点"当结论 —— 那是把题目改简单了。
PROMISE_LEAD_MARGIN = float(os.getenv("SIM_PROMISE_LEAD_MARGIN", "1.15"))
# 场景标定要落在"有信息量"的区间：全可行或全不可行都白算一轮。
FEASIBLE_BAND = (0.25, 0.90)
MARGIN_BOUNDS = (0.8, 1.6)
BATCH_BOUNDS = (2.0, 12.0)


def regret_profile(sol: Dict[str, Any]) -> Tuple[float, ...]:
    """与 pareto_eval 的择优同口径：把该解的各目标后悔从最坏到最好排成一个向量。"""
    reg = sol.get("regret_by_objective") or {}
    from api.services.pareto_eval import FIXED_ORDER
    return tuple(sorted((float(reg.get(k) or 0.0) for k in FIXED_ORDER), reverse=True))


def scenario_discrimination(res: Dict[str, Any], n_policies: int) -> Dict[str, Any]:
    """这一轮这个场景到底比出了什么 —— 判"有没有信息"，不判"分数好不好看"。

    runner_up_regret_gap 用字典序口径而不是 max_regret 之差：实测前沿只有 2~4 个点时
    每个点都在某一维全场最差，max_regret 清一色等于 1.0，做差恒为 0，
    看着像"全并列"其实是量错了。真正要比的是择优那串字典序里**第一个不相等的分量**。
    gap=0 才是真的并列（抛硬币），gap=None 是连两个可比解都没有。
    """
    pool = (res.get("frontier") or []) + (res.get("dominated") or [])
    profiles = sorted(regret_profile(s) for s in pool)
    tied = len([x for x in profiles[1:] if x == profiles[0]]) if profiles else 0
    # 并列的那些不算次优：gap 要比到第一个**真的不一样**的解，否则永远读出 0
    runner = next((x for x in profiles[1:] if x != profiles[0]), None) if len(profiles) > 1 else None
    if runner is not None:
        gap = next((round(b - a, 4) for a, b in zip(profiles[0], runner)
                    if abs(b - a) > 1e-9), 0.0)
    else:
        gap = None
    dead = res.get("non_discriminating_objectives") or []
    live = len([k for k in (res.get("objectives") or []) if k not in dead])
    feasible_ratio = round(len(pool) / max(1, int(n_policies or 1)), 2)
    in_band = FEASIBLE_BAND[0] <= feasible_ratio <= FEASIBLE_BAND[1]
    report_only = bool(res.get("report_only_comparison"))
    return {
        "recommended": (res.get("recommended") or {}).get("name"),
        "feasible": len(pool),
        "eliminated": len(res.get("eliminated") or []),
        "feasible_ratio": feasible_ratio,
        "frontier_size": len(res.get("frontier") or []),
        "live_objectives": live,
        "dead_dims": dead,
        "runner_up_regret_gap": gap,
        "tied_with_recommended": len(res.get("recommended_tied_with") or []),
        "no_feasible": bool(res.get("no_feasible_solution")),
        "report_only_comparison": report_only,
        "informative": bool(len(pool) >= 3 and in_band and gap and live >= 1 and not report_only),
    }


def promise_ceiling() -> float:
    """标定最多能放宽到哪儿 = 厂里真会承诺的交期口径。

    越过承诺去调标定等于把题目改简单再宣布"能做到" —— 那正是用户警告过的过拟合。
    放宽只到承诺口径为止；到顶还是没人能准点，就如实报"以现有提前期做不到"。
    """
    return round(min(MARGIN_BOUNDS[1], PROMISE_LEAD_MARGIN), 2)


def _tune_one(cal: Dict[str, float], disc: Dict[str, Any]) -> Optional[str]:
    """按场景调自己的标定；返回这一格做了什么调整（None = 这轮不用动）。"""
    ceiling = promise_ceiling()
    ratio = disc["feasible_ratio"]
    if disc["no_feasible"] or ratio < FEASIBLE_BAND[0]:
        # 触发原因要分清：没有任何准点解 ≠ 可行比例低（降级比较时可行比例可以是 100%）
        reason = ("没有任何准点解" if disc["no_feasible"] else f"可行比例 {ratio:.0%} 太低")
        if cal["lead_margin"] < ceiling:
            cal["lead_margin"] = round(min(ceiling, cal["lead_margin"] + 0.1), 2)
            return f"{reason} → 交期系数放宽到 {cal['lead_margin']:g}（承诺口径上限 {ceiling:g}）"
        if ratio < FEASIBLE_BAND[0] and cal["days_of_output"] > BATCH_BOUNDS[0]:
            cal["days_of_output"] = round(max(BATCH_BOUNDS[0], cal["days_of_output"] - 1.0), 2)
            return (f"交期已到承诺口径上限还几乎无解 → 批量降到 {cal['days_of_output']:g} 天线产量，"
                    f"分清是批量定大了还是以现有提前期就是做不到")
        return None     # 标定已到底：做不到就是结论，不再用调参把它调成"做得到"
    if cal["lead_margin"] > ceiling and disc["feasible"]:
        # 上一轮为了诊断放宽过，这轮有准点解就收回来：不许赖在简单模式里刷可行解
        cal["lead_margin"] = round(max(ceiling, cal["lead_margin"] - 0.1), 2)
        return (f"这一格还停在比承诺口径（{ceiling:g}）更宽的交期上、且已经有准点解 → "
                f"交期系数收回 {cal['lead_margin']:g}，不靠改题目拿可行解")
    if ratio > FEASIBLE_BAND[1]:
        # 全（或几乎全）可行不一定是坏事：目标维度还能取舍就不许再收紧交期去制造"延不延期"的假区分度
        if disc["informative"] or (disc["live_objectives"] >= 2 and disc["runner_up_regret_gap"]):
            return None
        if cal["lead_margin"] > MARGIN_BOUNDS[0]:
            cal["lead_margin"] = round(max(MARGIN_BOUNDS[0], cal["lead_margin"] - 0.1), 2)
            return (f"{ratio:.0%} 的政策都准点、且推荐解与次优解的后悔并列 "
                    f"→ 交期系数收紧到 {cal['lead_margin']:g}")
        return None
    if disc["feasible"] <= 2 or disc["live_objectives"] == 0:
        if cal["days_of_output"] > BATCH_BOUNDS[0]:
            cal["days_of_output"] = round(max(BATCH_BOUNDS[0], cal["days_of_output"] - 1.0), 2)
            return (f"可行解只有 {disc['feasible']} 个/目标维度全平 → "
                    f"批量降到 {cal['days_of_output']:g} 天线产量，找中间地带")
    return None



# "有没有人动过"要一次问全三类台账：只查 purchase_orders 会把请购/申购当成没落地，
# 而厂里催一个料通常先走请购或申购，PO 是后面的事。
FOLLOWTHROUGH_SQL = text("""
    SELECT m.material_code, m.lead_time_days AS lead_now, m.default_supplier,
           (SELECT COUNT(*) FROM purchase_orders po
             WHERE po.factory_id = :fid AND po.material_code = m.material_code
               AND po.created_at >= CAST(:since AS timestamp)
               AND UPPER(COALESCE(po.status, '')) <> 'CANCELLED') AS pos_since,
           (SELECT COUNT(*) FROM purchase_requests pr
             WHERE pr.factory_id = :fid AND pr.material_code = m.material_code
               AND pr.created_at >= CAST(:since AS timestamp)
               AND UPPER(COALESCE(pr.status, '')) NOT IN ('CANCELLED', 'REJECTED')) AS req_since,
           (SELECT COUNT(*) FROM purchase_requisitions rq
             WHERE rq.factory_id = :fid AND rq.material_code = m.material_code
               AND rq.created_at >= CAST(:since AS timestamp)
               AND UPPER(COALESCE(rq.status, '')) NOT IN ('CANCELLED', 'REJECTED')) AS requis_since
    FROM materials m
    WHERE m.factory_id = :fid AND m.material_code = ANY(CAST(:codes AS text[]))
""")


async def recommendation_followthrough(db: AsyncSession, factory_id: str,
                                       actions: List[Dict[str, Any]],
                                       *, since: Optional[datetime] = None) -> Dict[str, Any]:
    """上一轮建议的动作到底做没做 —— 引擎得能发现自己是不是一直在对空气提建议。

    只看台账里已有的证据：物料主档的提前期压到建议值没有、这段时间对这个料号开过采购单没有、
    缺供应商的料号补齐没有。查不到证据就说查不到，不猜"可能口头催过了"。
    """
    wanted = [a for a in (actions or []) if a.get("material_code")]
    codes = sorted({str(a["material_code"]) for a in wanted})
    if not codes:
        return {"checked": 0, "adopted": [], "not_acted": [],
                "note": "本轮建议没点名到料号，无复查对象"}
    until = since or (datetime.utcnow() - timedelta(days=7))
    if getattr(until, "tzinfo", None) is not None:
        until = until.replace(tzinfo=None)
    rows = (await db.execute(FOLLOWTHROUGH_SQL,
                             {"fid": factory_id, "codes": codes, "since": until})).mappings().all()
    by_code = {str(r["material_code"]): dict(r) for r in rows}
    adopted: List[Dict[str, Any]] = []
    not_acted: List[Dict[str, Any]] = []
    no_master: List[str] = []
    for a in wanted:
        code = str(a["material_code"])
        row = by_code.get(code)
        if row is None:
            no_master.append(code)
            continue
        lead_now = row.get("lead_now")
        target = int(a.get("target_lead_days") or 0)
        pos = int(row.get("pos_since") or 0)
        evidence = {"purchase_orders": pos,
                    "purchase_requests": int(row.get("req_since") or 0),
                    "purchase_requisitions": int(row.get("requisition_since") or 0)}
        raised = sum(evidence.values())
        if str(a.get("type")) == "supplier_master_missing":
            item = {"material_code": code, "check": "补供应商",
                    "default_supplier": row.get("default_supplier")}
            (adopted if row.get("default_supplier") else not_acted).append(item)
            continue
        pressed = lead_now is not None and target and int(lead_now) <= target
        (adopted if (pressed or raised > 0) else not_acted).append(
            {"material_code": code,
             "check": f"提前期压到 {target} 天，或采购/请购/申购里查到记录",
             "lead_now": lead_now, "lead_target": target,
             "evidence": evidence, "records_since": raised})
    verdict = ("建议有下落：提前期已压缩，或采购/请购/申购里查到了记录" if adopted and not not_acted else
               ("建议还没落地：主档提前期没变，采购/请购/申购三类台账都查不到记录"
                if not_acted and not adopted else
                "部分落地：见明细，未落地的部分继续挂在建议里"))
    return {"checked": len(wanted), "adopted": adopted, "not_acted": not_acted,
            "no_master_row": sorted(set(no_master)), "since": str(until),
            "verdict": verdict,
            "note": ("复查只看台账证据：materials.lead_time_days 是否压到建议值，"
                     "以及 purchase_orders / purchase_requests / purchase_requisitions 里该料号"
                     "在建议之后有没有新增单据（取消/驳回的不算）。查不到就说查不到，不猜有没有人口头催过")}


# 动作排序：先"今天就能下单/开工"的，再"要人去确认"的，最后是主数据缺口。
_ACTION_PRIORITY = {"expedite_purchase": 0, "supplier_master_missing": 1, "start_first_batch": 2,
                    "schedule_second_batch_after_arrival": 3, "activate_parallel_line": 4,
                    "extra_crew": 5, "model_data_gap": 6, "master_data_gap": 7}


def recommendation_actions(scan: Dict[str, Any], verdict: Dict[str, Any],
                           *, today: Optional[date] = None,
                           max_actions: int = 30) -> List[Dict[str, Any]]:
    """把"稳健推荐的政策"翻译成能执行的动作：催哪个料、哪天到货、先开哪一批、开哪条线。

    政策名不是动作 —— 人要的是"找谁、买多少、几号到"。三条诚实规矩：
    ① 缺口料号没有供应商主数据就不许编一个供应商，改成补数据动作（卡住交付的是数据不是产能）；
    ② 开并联线要说清人手从哪来，技能矩阵还是 0 行就标 crew_verified=false，不假装人能调；
    ③ 动作只落在沙箱建议里（sandbox_only），不写 MES/WMS，也不自动生成采购单。
    依据取"该政策最紧的那个天气场景"：按好天的到货日下单，暴雨天就直接失约。
    """
    today = today or date.today()
    robust = ((verdict or {}).get("robust_recommendation") or {}).get("policy")
    if not robust:
        return []
    binding: Dict[str, Dict[str, Any]] = {}     # model -> 该模型最紧场景的 detail + 政策
    for name, block in (scan.get("by_scenario") or {}).items():
        for sol in (block.get("solutions") or []):
            if str(sol.get("name")) != str(robust):
                continue
            for d in (sol.get("detail") or []):
                m = str(d.get("model_code"))
                score = (int(d.get("days_late") or 0), int(d.get("material_arrival_day") or 0))
                cur = binding.get(m)
                if cur is None or score > (int(cur.get("days_late") or 0),
                                           int(cur.get("material_arrival_day") or 0)):
                    entry = dict(d)
                    entry["_scenario"] = name
                    entry["_policy"] = sol.get("policy") or {}
                    binding[m] = entry

    out: List[Dict[str, Any]] = []
    for m, d in sorted(binding.items()):
        pol = d.get("_policy") or {}
        scen = d.get("_scenario")
        due = d.get("due_date")
        base = {"model_code": m, "scenario": scen, "due_date": due,
                "planned_finish_date": d.get("finish_date"), "sandbox_only": True}
        if d.get("status") and str(d.get("status")) != "simulated":
            # 这台机种从比较里摘掉了：不是厂里做不到，是模型没有能算工时的依据 —— 要补的是数据
            out.append({**base, "type": "model_data_gap", "units_excluded": d.get("units"),
                        "detail": f"{m}：{d.get('status')} — {d.get('why')}",
                        "note": "它不进产量底线也不进这轮推荐；补上工时依据（IE 标准工时或线声明节拍）才能推演"})
            continue
        if int(pol.get("parallel_lines") or 1) > 1:
            out.append({**base, "type": "activate_parallel_line", "line": d.get("line"),
                        "capacity_basis": d.get("capacity_basis"), "crew_verified": False,
                        "note": ("开第二条线按组内声明的合并产能算（不是单线×线数）；"
                                 "要的人手没有技能矩阵佐证，先按'能开'算钱、按'待确认'报人")})
        if float(pol.get("crew_bonus") or 0) > 0:
            # 词表里只有 extra_crew / add_overtime 两个动作名；引擎这一档是"产能乘一个系数"，
            # 到底是加人/双班还是加班，是厂里的决定，模型不能替它选（写成 authorize_overtime
            # 会让约束层、决策台账、采纳回查三处都认不出这个动作）。
            out.append({**base, "type": "extra_crew",
                        "capacity_share": round(float(pol["crew_bonus"]), 3),
                        "basis": "capacity_multiplier",
                        "could_be": ["extra_crew", "add_overtime"],
                        "note": (f"这一档把日产能乘 {1 + float(pol['crew_bonus']):.2f}"
                                 "（成本已计入人工口径）。落地要选一种：加人/双班，还是加班——"
                                 "加班受厂规上限与现场实测约束，双班要有夜班人手，这个选择引擎不替做")})
        bp = d.get("bottleneck_part") or {}
        if pol.get("expedite_lead_days") is not None and bp and float(bp.get("short") or 0) > 0:
            target = int(pol["expedite_lead_days"])
            cur_lead = int(bp.get("lead_time_days") or 0)
            arrival = int(d.get("material_arrival_day") or 0)
            pull = max(0, cur_lead - target)
            # arrival 已经是加急之后的到货日（run_target 里换过一遍），不能再减一次 pull：
            # 那样催购要到的日期会比第二批开工的日期还早，两张动作自相矛盾。
            act = {**base, "material_code": bp.get("material_code"),
                   "qty_short": round(float(bp.get("short") or 0), 3),
                   "current_lead_days": cur_lead, "target_lead_days": target,
                   "order_by_date": str(today),
                   "required_arrival_date": str(today + timedelta(days=arrival)),
                   "pulled_in_days": pull,
                   "arrival_note": f"按 {target} 天提前期推演的到货日；不催的话要到 {today + timedelta(days=arrival + pull)}"}
            if bp.get("supplier"):
                act.update({"type": "expedite_purchase", "supplier": bp["supplier"],
                            "note": f"向 {bp['supplier']} 把 {cur_lead} 天提前期压到 {target} 天；"
                                    f"下单每晚一天，出货日就晚一天"})
            else:
                act.update({"type": "supplier_master_missing",
                            "note": ("这个缺口料号在物料主档里没有默认供应商 —— 催购没有对象。"
                                     "卡住交付的是数据不是产能：先补料号供应商，再谈加急价")})
            out.append(act)
        a = float(d.get("batch_a_units") or 0)
        b = float(d.get("batch_b_units") or 0)
        if a > 0:
            out.append({**base, "type": "start_first_batch", "units": round(a, 3),
                        "start_date": str(today),
                        "note": f"现料够先做 {a:g} 台，不等齐套；这批可以马上进排产预排"})
        if b > 0:
            out.append({**base, "type": "schedule_second_batch_after_arrival",
                        "units": round(b, 3),
                        "not_before": str(today + timedelta(days=int(d.get("material_arrival_day") or 0))),
                        "note": "第二批卡在到货日，提前开工只会做出做不完的半成品"})
        for gap in (d.get("blockers") or []):
            out.append({**base, "type": "master_data_gap", "detail": str(gap),
                        "note": "齐套算不下去的缺口在这里：不是产能，也不是人手"})

    # 同一个主数据缺口会在多台单上重复出现：合成一条并列出受影响的机种，
    # 否则动作清单被重复行占满，真正要催的那条反而看不见
    merged: Dict[Tuple, Dict[str, Any]] = {}
    order: List[Tuple] = []
    for a in out:
        ident = str(a.get("material_code") or a.get("detail") or "")
        # 没有"料号/缺口"身份的动作（分批、开线）每台单都是独立的一条，
        # 不能拿空身份当 key —— 那样第二台单的分批建议会被当成重复项吃掉
        key = (a["type"], ident) if ident else (a["type"], str(a.get("model_code") or ""), len(order))
        if key[1] and a["type"] in ("master_data_gap", "supplier_master_missing"):
            if key not in merged:
                merged[key] = dict(a, models=[])
                order.append(key)
            merged[key]["models"].append(a["model_code"])
            merged[key].pop("model_code", None)
            continue
        if key not in merged:
            merged[key] = a
            order.append(key)
    # 能花钱/能开工的动作排在前面，主数据缺口垫底：待办正文只放得下前几条，
    # 让"今天该给谁下单"占位、"哪个料号没标自制外购"占位是两种完全不同的损失
    ranked = sorted((merged[k] for k in order),
                    key=lambda a: (_ACTION_PRIORITY.get(str(a.get("type")), 9),
                                   str(a.get("model_code") or "")))
    return ranked[:max(1, int(max_actions))]


def _seed_calibration(seed: Optional[Dict[str, Any]], days_of_output: float,
                     lead_margin: float) -> Dict[str, Dict[str, float]]:
    """每 15 分钟一轮，标定不能每轮从 1.15 重新摸索一遍 —— 那等于每轮都把已知的
    "哪个天气场景该多紧"重新忘掉，既白算也永远收敛不到中间地带。"""
    calib = {s["name"]: {"days_of_output": round(float(days_of_output), 2),
                         "lead_margin": round(float(lead_margin), 2)} for s in WEATHER_SCENARIOS}
    for name, val in (seed or {}).items():
        if name not in calib or not isinstance(val, dict):
            continue
        try:
            batch = float(val.get("days_of_output"))
            margin = float(val.get("lead_margin"))
        except (TypeError, ValueError):
            continue
        if batch > 0 and margin > 0:
            # 历史标定若越出承诺口径（上一版允许放宽到 1.6 时留下的），热启动就收回来
            calib[name] = {"days_of_output": min(BATCH_BOUNDS[1], max(BATCH_BOUNDS[0], batch)),
                           "lead_margin": min(promise_ceiling(), max(MARGIN_BOUNDS[0], margin))}
    return calib


async def auto_tune(db: AsyncSession, factory_id: str, models: List[str], *, rounds: int = 3,
                    days_of_output: float = 6.0, lead_margin: float = 1.15,
                    calibration: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """自己**按每个天气场景**标定 → 扫 → 看哪里白算 → 改标定 → 再扫。

    标定从全局改成按场景，是上一轮自审抓出来的洞：可行度按场景分布，标定却是全局的 ——
    暴雨一收紧，好天场景就退化成"13 个政策全可行、0 个淘汰"，那一轮同样没有信息量；
    反过来全局放宽，暴雨又全不可行，还是比不出东西。

    每格调的是什么，判据是"这一轮有没有区分度"，不是分数好不好看：
    ① 可行比例 < 0.25（几乎没人能准点）⇒ 先放宽该场景交期系数；到上限再降批量，
       分清是"量定大了"还是"以现有提前期就是做不到"（后者是结论，不是失败）；
    ② 可行比例 > 0.90 且推荐解与次优解的后悔并列 ⇒ 收紧该场景交期系数；
       若目标维度还能取舍（人力/加急/开线/负载比不一样），就**不许**再收紧 ——
       准点这维本来就是空的，硬造"延不延期"的区分度是自欺；
    ③ 可行解 ≤2 或目标维度全平 ⇒ 该场景批量降一档，去看中间地带。
    """
    calib = _seed_calibration(calibration, days_of_output, lead_margin)
    seeded = bool(calibration)
    trajectory: List[Dict[str, Any]] = []
    grid_extra: List[Dict[str, Any]] = []
    extreme_added = False
    final: Dict[str, Any] = {}
    targets: List[Dict[str, Any]] = []
    for rnd in range(max(1, int(rounds))):
        targets_by_scenario: Dict[str, List[Dict[str, Any]]] = {}
        for name, cal in calib.items():
            targets_by_scenario[name] = await derive_targets(
                db, factory_id, models, days_of_output=cal["days_of_output"],
                lead_margin=cal["lead_margin"])
        targets = targets_by_scenario[WEATHER_SCENARIOS[0]["name"]]
        grid = await build_policy_grid(db, factory_id, targets)
        for extra in grid_extra:
            if extra["name"] not in {g["name"] for g in grid}:
                grid.append(extra)
        scan = await scan_policies(db, factory_id, targets, policies=grid,
                                   targets_by_scenario=targets_by_scenario)
        from api.services.pareto_eval import evaluate_by_scenario
        # 标定已放宽到超过承诺系数的场景只作诊断，不参与跨场景稳健推荐
        within_promise = [n for n, c in calib.items()
                          if c["lead_margin"] <= PROMISE_LEAD_MARGIN + 1e-9]
        verdict = evaluate_by_scenario(scan["by_scenario"], scan["demand_by_scenario"],
                                       robust_scenarios=within_promise or None)
        per: Dict[str, Any] = {}
        tweaks: List[str] = []
        for scen in WEATHER_SCENARIOS:
            name = scen["name"]
            res = (verdict.get("by_scenario") or {}).get(name) or {}
            disc = scenario_discrimination(res, len(grid))
            cal = calib[name]
            tweak = _tune_one(cal, disc)
            if tweak:
                tweaks.append(f"{name}：{tweak}")
            # 交期这个旋钮已经拧到承诺口径上限，再没有"把题目改简单"的余地：
            # 这时还没准点解就该去试极限杠杆，而不是先看批量降到多小
            ceiling_reached = cal["lead_margin"] >= promise_ceiling()
            # 触发条件不能只看可行比例：降级比较时可行比例可以高达 92%（全都算进来了），
            # 而真相是本场景没有任何准点解 —— 那才是"补极限加急/报做不到"的信号
            if (disc["no_feasible"] or disc["feasible_ratio"] < FEASIBLE_BAND[0]) and ceiling_reached:
                if not extreme_added:
                    grid_extra.append({"name": "极限加急（提前期压到 2 天）+ 并联开满",
                                       "expedite_lead_days": 2, "parallel_lines": 2})
                    extreme_added = True
                    tweaks.append(f"{name}：标定已到边界仍无准点解 → 补一档极限加急政策试试")
                else:
                    disc["verdict"] = ("以现有供应商提前期，这个天气场景做不到准点交付 —— "
                                       "这是结论。标定不再往里压，避免把'做不到'调成'做得到'")
            elif tweak is None:
                # 每格都要有自己的说法，不能留 None 让人去猜这一轮到底算不算数
                if disc["report_only_comparison"]:
                    disc["verdict"] = "没有解达到产量底线：这一轮只摆数据，不择优"
                elif disc["no_feasible"]:
                    disc["verdict"] = ("本场景没有任何准点解（含放宽后的口径）：已降级按延误天数比较，"
                                       "这是结论不是失败")
                elif disc["feasible_ratio"] > FEASIBLE_BAND[1]:
                    disc["verdict"] = (f"{disc['feasible_ratio']:.0%} 的政策都能准点：准点这维在本场景是空的，"
                                       f"政策靠目标维度取舍（推荐解赢次优解的后悔差 "
                                       f"{disc['runner_up_regret_gap']}）")
                elif disc["tied_with_recommended"]:
                    disc["verdict"] = (f"推荐解与 {disc['tied_with_recommended']} 个政策的后悔向量每一位都相同："
                                       f"本轮只筛掉了明显更差的，没说哪个最好 —— 要分高下得给目标定优先级")
                elif disc["runner_up_regret_gap"] in (0.0, None):
                    disc["verdict"] = "没有一个可比解与推荐解的后悔不同：本轮等于抛硬币，不能当结论"
                else:
                    disc["verdict"] = "落在有信息量的区间：可行比例在带内，推荐解与次优解有后悔差"
            blocked = {(b.get("model_code"), str(b.get("status")))
                       for s in ((scan["by_scenario"].get(name) or {}).get("solutions") or [])
                       for b in (s.get("blocked_models") or [])}
            disc["beyond_promise"] = cal["lead_margin"] > PROMISE_LEAD_MARGIN + 1e-9
            if disc["beyond_promise"]:
                disc["diagnostic_only"] = (
                    f"这一格把交期放宽到提前期 ×{cal['lead_margin']:g}（承诺口径是 ×"
                    f"{PROMISE_LEAD_MARGIN:g}）：只用来判断'做不到是政策不够还是交期本身不可能'，"
                    f"它的准点不算交付承诺，也不参与跨场景稳健推荐")
            per[name] = {"calibration": dict(cal),
                         "demand_units": scan["demand_by_scenario"].get(name),
                         "blocked_models": [{"model_code": mc, "status": st} for mc, st in sorted(blocked)],
                         "recommended_objectives": (res.get("recommended") or {}).get("objectives"),
                         "recommended_off_frontier": res.get("recommended_off_frontier"),
                         **disc}
        row = {
            "round": rnd,
            # 兼容老的记分卡字段（单场景标定字符串），同时给出按场景的完整标定
            "calibration": "；".join(
                f"{s['name']}：批量 {calib[s['name']]['days_of_output']:g} 天线产量、"
                f"交期系数 {calib[s['name']]['lead_margin']:g}" for s in WEATHER_SCENARIOS),
            "calibration_by_scenario": {k: dict(v) for k, v in calib.items()},
            "per_scenario": per,
            "robust": (verdict.get("robust_recommendation") or {}).get("policy"),
            "robust_pool": verdict.get("robust_scenario_pool") or [],
            "diagnostic_only_scenarios": verdict.get("diagnostic_only_scenarios") or [],
            "promise_margin": PROMISE_LEAD_MARGIN,
            "robust_why": (verdict.get("robust_recommendation") or {}).get("why"),
            "robust_tied_with": (verdict.get("robust_recommendation") or {}).get("tied_with") or [],
            "policies_tried": len(grid),
            "notes": [n for r in (verdict.get("by_scenario") or {}).values()
                      for n in (r.get("notes") or [])],
            "scenario_divergence": verdict.get("scenario_divergence") or {},
            "diagnosis": ("；".join(tweaks) if tweaks else (
                "各场景都有区分度：可行比例在带内、推荐解与次优解有后悔差，本轮前沿与后悔比较可用"
                if all(p.get("informative") for p in per.values()) else
                "标定已到承诺口径上限（×%g），各场景仍在降级比较（没有准点解）："
                "本轮只按延误天数排先后，不宣称谁能准点" % PROMISE_LEAD_MARGIN)),
            "next_tweak": tweaks[0] if tweaks else None,
            "tweaks": tweaks,
        }
        trajectory.append(row)
        final = row
        if not tweaks:
            break
    all_beyond = all((c["lead_margin"] > PROMISE_LEAD_MARGIN + 1e-9) for c in calib.values())
    final_per = (trajectory[-1].get("per_scenario") or {}) if trajectory else {}
    conclusion = None
    if final_per and all(p.get("no_feasible") for p in final_per.values()):
        worst = max(int(((p.get("recommended_objectives") or {}).get("days_late_worst")) or 0)
                    for p in final_per.values())
        conclusion = (f"以承诺交期（瓶颈提前期 ×{PROMISE_LEAD_MARGIN:g}、批量 "
                      f"{calib[WEATHER_SCENARIOS[0]['name']]['days_of_output']:g} 天线产量）"
                      f"这 {len(models)} 台做不到准点：连后悔最小的政策也要延 {worst} 天。"
                      f"要兑现得压提前期/加急或改承诺交期 —— 而不是把标定放宽，那只是把题目改简单。")
    elif all_beyond:
        conclusion = (f"以承诺交期（瓶颈提前期 ×{PROMISE_LEAD_MARGIN:g}）这 {len(models)} 台做不到准点；"
                      f"要准点得压提前期/加急，或把交期改成 ×{min(c['lead_margin'] for c in calib.values()):g} 以上 —— "
                      f"本轮放宽之后的推荐只说明'交期这么定就行'，不说明现有承诺能兑现")
    return {"factory_id": factory_id, "rounds": len(trajectory), "warm_started": seeded,
            "all_scenarios_beyond_promise": all_beyond,
            "nothing_on_time_at_promise": bool(final_per) and all(
                p.get("no_feasible") for p in final_per.values()),
            "conclusion": conclusion,
            "targets": targets, "final": final, "trajectory": trajectory,
            "final_scan": scan, "final_verdict": verdict,
            "calibration_by_scenario": {k: dict(v) for k, v in calib.items()},
            "rule": ("标定按天气场景各调各的，目标是每一轮都有区分度：可行比例落在 "
                     f"{FEASIBLE_BAND[0]:.0%}~{FEASIBLE_BAND[1]:.0%}，且推荐解与次优解的后悔不相等。"
                     "调参只为了让比较有意义，不为把分数调高 —— 调到底还做不到的场景如实报做不到。")}



async def measured_attendance(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """没人给到岗曲线时用台账算出来的缺勤率，不用写死的 0.97。

    0.97 是当初拍脑袋的常数；attendance 表里有真打卡记录（缺勤=status='leave' 的行/排班人次），
    两个厂的差据还很大（机械厂 4.33%、电子厂 0.05%）。查不到台账时才退回声明值，并把退回写进读数。
    """
    from core.mes.data_evidence import absence_baseline

    declared = {"present_ratio": DEFAULT_ATTENDANCE_RATE, "source": "declared_default",
                "basis": f"没有台账基线 → 退回声明默认 {DEFAULT_ATTENDANCE_RATE:g}（这是常数，不是量出来的）"}
    try:
        ledger = await absence_baseline(db, factory_id)
    except Exception as exc:  # noqa: BLE001  查不到不能编一个数，但要说明为什么退回常数
        return {**declared, "lookup_error": f"{type(exc).__name__}: {exc}"[:160]}
    if not ledger.get("available") or ledger.get("rate") is None:
        return {**declared, "why": ledger.get("why") or "该厂区没有可引用的缺勤率"}
    rate = float(ledger["rate"])
    return {"present_ratio": round(1.0 - rate, 4), "source": "attendance_ledger",
            "absence_rate": round(rate, 4), "basis": ledger.get("basis"),
            "daily_band_flat": ledger.get("daily_band_flat"),
            "reading": (f"到岗 {round((1.0 - rate) * 100, 2)}%（台账实测缺勤 {round(rate * 100, 2)}%）")}


async def run_sandbox(db: AsyncSession, factory_id: str, targets: List[Dict[str, Any]],
                      *, today: Optional[date] = None,
                      attendance_curve: Optional[Dict[int, float]] = None,
                      expedite_lead_days: Optional[int] = None,
                      line_staffing: Optional[Dict[str, Any]] = None,
                      working_conditions: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """跑一批目标（每台一个时间线），并汇总组合结果。targets: [{model_code, units, due_in_days}]

    `line_staffing` 是 {线编码: 到岗比例}：0 = 整班没来（改派到工艺上同样能做的线，无路可改则等），
    0.5 = 半数到岗（班组人数按比例折，产能随之受班组可完成量约束）。不给就是 1.0，与老行为一致。
    """
    today = today or date.today()
    lines = [dict(r) for r in (await db.execute(LINES_SQL, {"fid": factory_id})).mappings().all()]
    shift_days = {int(r["weekday"]) + 1 for r in
                  (await db.execute(CALENDAR_SQL, {"fid": factory_id})).mappings().all()} or {1, 2, 3, 4, 5, 6}
    att = None if (attendance_curve or working_conditions) else await measured_attendance(db, factory_id)
    curve = attendance_curve or ({d: att["present_ratio"] for d in range(0, 400)} if att
                                 else {d: DEFAULT_ATTENDANCE_RATE for d in range(0, 200)})
    conditions_basis = None
    if working_conditions and attendance_curve is None:
        # 工况的缺勤率扣的是可用人头，不是效率折扣：产能曲线按到岗比例降，效率另算
        from core.mes.data_evidence import workforce_presence_under_conditions

        conditions_basis = await workforce_presence_under_conditions(
            db, factory_id,
            temperature_c=float(working_conditions.get("temperature_c")),
            humidity_percent=float(working_conditions.get("humidity_percent") or 60.0),
            task_type=str(working_conditions.get("task_type") or "assembly"))
        if conditions_basis.get("present_ratio") is None:
            return {"factory_id": factory_id, "status": "no_attendance_baseline",
                    "working_conditions": conditions_basis,
                    "why": (f"这条工况算不出到岗比例：{conditions_basis.get('why')} —— "
                            "不拿默认缺勤率把沙箱跑成一个看起来对的交期"),
                    "hint": "传 factory_id 对应厂区（该厂要有 attendance 打卡行），或直接给 attendance_rate"}
        curve = {d: float(conditions_basis["present_ratio"]) for d in range(0, 400)}

    runs = []
    for t in targets:
        due = today + timedelta(days=int(t.get("due_in_days") or 25))
        run = await run_target(db, factory_id, str(t["model_code"]), float(t.get("units") or 0),
                               due, today, curve, lines, shift_days, line_staffing=line_staffing)
        if expedite_lead_days is not None and run.get("bottleneck_part"):
            alt = await run_target(db, factory_id, str(t["model_code"]), float(t.get("units") or 0),
                                   due, today, curve, lines, shift_days,
                                   expedite_lead_days=expedite_lead_days, line_staffing=line_staffing)
            run["expedite_whatif"] = {
                "to_lead_days": expedite_lead_days,
                "finish_date": alt.get("finish_date"), "finish_day": alt.get("finish_day"),
                "days_pulled_in": (int(run.get("finish_day") or 0) - int(alt.get("finish_day") or 0))
                                  if alt.get("finish_day") is not None else None,
                "standby_days_saved": (float(run.get("standby_person_days_if_line_held") or 0)
                                       - float(alt.get("standby_person_days_if_line_held") or 0)),
            }
        runs.append(run)
    try:
        # 沙箱是一次人交互的调用，值得把"这些动作厂里有没有规则支撑"一起端出来
        constraints = await constraint_overlay(db, factory_id, targets,
                                               [{"name": "本次沙箱参数"}], lines)
    except Exception as exc:  # noqa: BLE001  约束层查不到不能让沙箱整体失败，但必须写出来
        constraints = {"enforced": False, "error": f"{type(exc).__name__}: {exc}"[:200],
                       "note": "约束层本轮没跑成 —— 这不代表这些动作都有规则支撑"}
    ok = [r for r in runs if r["status"] == "simulated"]
    waiting = [r for r in runs if r["status"] == "no_staffed_line"]
    total_late = sum(max(0, int(r["days_late"] or 0)) for r in ok)
    on_time = sum(1 for r in ok if (r["days_late"] or 0) <= 0)
    return {
        "factory_id": factory_id, "today": str(today), "targets": len(runs),
        "simulated": len(ok), "no_basis": len(runs) - len(ok),
        "waiting_for_manpower": len(waiting),
        "on_time_orders": on_time, "total_days_late": total_late,
        "person_days_total": round(sum(float(r["person_days"] or 0) for r in ok), 1),
        "standby_person_days_total": round(sum(float(r["standby_person_days_if_line_held"] or 0) for r in ok), 1),
        "material_cost_usd": round(sum(float(r["material_cost_usd"] or 0) for r in ok), 2),
        "labor_cost_usd": round(sum(float(r["labor_cost_usd"] or 0) for r in ok), 2),
        "standby_cost_total_usd": round(sum(float(r["standby_cost_if_line_held_usd"] or 0) for r in ok), 2),
        "runs": runs, "constraints": constraints,
        "attendance_basis": att,
        "working_conditions": conditions_basis,
        "assumptions": {
            "attendance_curve": (
                f"到岗基线：{att.get('basis') or att.get('why') or att.get('source')}" if att else
                ("工况反推：WBGT " + str((conditions_basis or {}).get("wbgt_c")) + "℃ → 到岗 "
                 + str((conditions_basis or {}).get("present_ratio"))
                 + "（台账基线 + 热侧缺勤增量；斜率是"
                 + str((conditions_basis or {}).get("slope_status")) + "）")
                if conditions_basis else
                f"按天到岗率常数 {DEFAULT_ATTENDANCE_RATE:g}（调用方直接给了曲线）"
                if attendance_curve else
                f"退回声明常数 {DEFAULT_ATTENDANCE_RATE:g}：这座厂没有可引用的缺勤台账"),
            "labor_cost_per_person_day": DEFAULT_LABOR_COST_PER_PERSON_DAY,
            "labor_cost_basis": "default_calibration（库里没有薪资列，钱只到量级）",
            "material_price_source": "bom_items.unit_price（缺价就单列 materials_without_price，不折算）",
            "lead_time_source": "materials.lead_time_days（外购全部有值）",
        },
    }

async def build_policy_grid(db: AsyncSession, factory_id: str,
                            targets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """政策档位从库里长出来，不写死：加急到几天、能并联几条线、能加多少人，都由现有数据决定。"""
    lines = [dict(r) for r in (await db.execute(LINES_SQL, {"fid": factory_id})).mappings().all()]
    grid: List[Dict[str, Any]] = [{"name": "现况（分批开工）", "allow_partial": True},
                                  {"name": "等齐套才开工（不分批）", "allow_partial": False}]
    leads = set()
    for t in targets:
        bom = (await sim_bom_lines(db, factory_id, str(t["model_code"]),
                                   float(t.get("units") or 1) or 1.0))["rows"]
        for r in bom:
            lead = str(r.get("lead_time_days") or "")
            if lead.isdigit() and int(lead) > 2:
                leads.add(int(lead))
    for lead in sorted(leads, reverse=True)[:3]:
        for factor, label in ((2, "减半"), (4, "压到 1/4")):
            value = max(1, lead // factor)
            grid.append({"name": f"瓶颈件提前期 {lead} 天 → {value} 天（{label}）",
                         "expedite_lead_days": value})
    groups: Dict[str, int] = {}
    for l in lines:
        groups[str(l.get("line_group") or l["line_code"])] = groups.get(
            str(l.get("line_group") or l["line_code"]), 0) + 1
    for grp, n in groups.items():
        if n >= 2:
            grid.append({"name": f"同组并联开满（{grp}={n} 条线）", "parallel_lines": n})
    grid.append({"name": "加班加人 15%", "crew_bonus": 0.15})
    grid.append({"name": "加班加人 30%", "crew_bonus": 0.30})
    # 这不是产能，是把已经答应该做的活往后推：必须点名"插单"，并且默认不许靠它宣布准点
    grid.append({"name": "插单（抢占已在排的活）", "ignore_backlog": True,
                 "displaces_committed_work": True})
    grid.append({"name": "加急 1/4 + 并联开满", "expedite_lead_days": (
        max(1, sorted(leads, reverse=True)[0] // 4) if leads else 5), "parallel_lines": 2})
    return grid


def capacity_limits(*, crew: float, hours_per_day: float, hours_per_unit: float,
                    line_declared: float) -> Dict[str, Any]:
    """日产能取两个上限的较小值：线组声明的台/天，和班组按单件工时做得完的台/天。

    原来只要有声明产能就完全不看工时 —— 实测 IE 工时 ±40% 对交期 0 影响，
    模型对着映射的数据不动，推演就退化成了日历器。两边都给不出 → 0（这台单没法排时）。
    """
    hours_implied = (round(crew * hours_per_day / hours_per_unit, 2)
                     if hours_per_unit and hours_per_unit > 0 and crew > 0 else 0.0)
    options = [x for x in (float(line_declared or 0), hours_implied) if x > 0]
    if not options:
        return {"units_per_day": 0.0, "binding": "no_capacity",
                "line_declared": float(line_declared or 0), "hours_implied": 0.0}
    binding = ("ie_hours" if hours_implied and hours_implied <= float(line_declared or 0)
               else "line_declared")
    return {"units_per_day": round(min(options), 2), "binding": binding,
            "line_declared": float(line_declared or 0), "hours_implied": hours_implied}


def group_capacity(lines: List[Dict[str, Any]], line: Dict[str, Any],
                   parallel_lines: int) -> Dict[str, Any]:
    """并联产能只能按线组声明的合并产能算 —— 跑步机线 11h/300 台、bike 单线 400 台但
    **两线合并 700 不是 800**（用户 10-06 第三次口述定稿）。按 n×单线乘出来的产能会凭空多出 14% 富余，
    而这 14% 正好会改变"缺料能不能靠另一条线追回"的结论。"""
    single = float(line.get("units_per_day") or 0)
    group = str(line.get("line_group") or "")
    n = max(1, int(parallel_lines))
    if n <= 1 or not group:
        return {"units_per_day": single, "capacity_basis": "single_line",
                "crew": float(line.get("crew_size") or 0)}
    members = [l for l in lines if str(l.get("line_group") or "") == group]
    group_total = float((members[0] if members else {}).get("group_units_per_day") or 0)
    crew_total = sum(float(l.get("crew_size") or 0) for l in members[:n]) if members else float(
        line.get("crew_size") or 0) * n
    if group_total > 0:
        # 合并产能是厂里声明的上限，最多用到它，不许按线数乘出来
        return {"units_per_day": round(min(single * n, group_total), 2),
                "capacity_basis": f"group_declared({group}={group_total:g}/天)",
                "crew": round(crew_total, 1)}
    return {"units_per_day": single * n, "capacity_basis": f"multiplied({n} lines, 组内未声明合并产能)",
            "crew": round(crew_total, 1)}


async def default_models(db: AsyncSession, factory_id: str, n: int = 2) -> List[str]:
    """默认取 BOM 最完整的 n 个机种，不从代码里写死机种名。"""
    rows = (await db.execute(text("""
        SELECT product_id FROM bom_items WHERE factory_id = :fid
        GROUP BY product_id HAVING count(*) >= 8 ORDER BY count(*) DESC LIMIT :n
    """), {"fid": factory_id, "n": n})).scalars().all()
    return [str(r) for r in rows]


async def derive_targets(db: AsyncSession, factory_id: str, models: List[str],
                         *, days_of_output: float = 6.0, lead_margin: float = 1.15
                         ) -> List[Dict[str, Any]]:
    """场景自己标定，不拍脑袋。

    批量 = 该线若干天的产量（少到 1 天就能做完的话，产能/人力/线这些维度全都没区分度）；
    交期 = 瓶颈件提前期 × 系数（比提前期还宽的话，所有政策都准点，准点这维也是废的）。
    这是上一轮自己发现的偏差：300 台配 30 天交期，12 个政策全部"准点 1.00"，比较不出任何东西。
    """
    lines = [dict(r) for r in (await db.execute(LINES_SQL, {"fid": factory_id})).mappings().all()]
    targets: List[Dict[str, Any]] = []
    for model in models:
        line, line_basis = pick_line(model, lines)
        per_day = float((line or {}).get("units_per_day") or 0)
        bom = (await sim_bom_lines(db, factory_id, model, 1.0))["rows"]
        codes = [str(r["material_code"]) for r in bom]
        lead_rows = (await db.execute(text("""
            SELECT MAX(COALESCE(m.lead_time_days, 0)) AS max_lead
            FROM materials m WHERE m.factory_id = :fid AND m.material_code = ANY(CAST(:codes AS text[]))
        """), {"fid": factory_id, "codes": codes})).mappings().first() if codes else None
        max_lead = int((lead_rows or {}).get("max_lead") or 0)
        units = int(per_day * days_of_output) if per_day > 0 else 300
        due_in_days = int(max(1, round(max(1, max_lead) * lead_margin)))
        targets.append({"model_code": model, "units": units, "due_in_days": due_in_days,
                        "calibration": f"批量={days_of_output:g} 天线产量（线 {per_day:g} 台/天）；"
                                       f"交期={max_lead} 天瓶颈提前期 × {lead_margin:g}"})
    return targets


# 可控政策（引擎能决定的事）与环境场景（只能接受的事）分开：
# 把天气当成"可选政策"放进同一个前沿比后悔是错的 —— 厂里没人能选天气。
POLICIES: List[Dict[str, Any]] = [
    {"name": "现况（分批开工·正常出勤）", "allow_partial": True},
    {"name": "等齐套才开工（不分批）", "allow_partial": False},
    {"name": "瓶颈件加急到 10 天", "expedite_lead_days": 10},
    {"name": "瓶颈件加急到 5 天", "expedite_lead_days": 5},
    {"name": "开并联第二条线", "parallel_lines": 2},
    {"name": "加班加人 15%", "crew_bonus": 0.15},
    {"name": "加急 10 天 + 开并联线", "expedite_lead_days": 10, "parallel_lines": 2},
    {"name": "开并联线 + 加班 15%", "parallel_lines": 2, "crew_bonus": 0.15},
]

WEATHER_SCENARIOS: List[Dict[str, Any]] = [
    {"name": "好天（到岗 0.97）", "attendance": 0.97},
    {"name": "雨季（到岗 0.92）", "attendance": 0.92},
    {"name": "暴雨（到岗 0.70）", "attendance": 0.70},
]


def _objectives(run: Dict[str, Any], demand_units: float, due_day: int) -> Dict[str, Any]:
    finish = run.get("finish_day")
    late = max(0, int(finish) - int(due_day)) if finish is not None else max(0, due_day)
    made = float(run.get("units") or 0) if finish is not None else 0.0
    on_time = 1.0 if finish is not None and finish <= due_day else 0.0
    conf = {
        "route_standard_hours": 1.0, "own_route": 1.0,
        "line_declared_can_make": 1.0, "line_declared_home": 1.0, "line_declared_default_model": 1.0,
        "borrowed_route_from_family": 0.4, "takt_from_line_capacity": 0.35,
        "line_inferred_by_family_name": 0.5, "assumed_ie_hours": 0.3, "no_route": 0.0,
        "no_time_basis": 0.0, "no_line": 0.0,
    }

    def _c(v: Optional[str]) -> float:
        return conf.get(str(v), 0.6)
    weights = [_c(run.get("route_basis")), _c(run.get("hours_basis")), _c(run.get("line_basis"))]
    return {
        "on_time_rate": on_time,
        "throughput_units": made,
        "labor_cost_usd": float(run.get("labor_cost_usd") or 0),
        "expedite_cost_usd": float(run.get("expedite_cost_usd") or 0),
        "standby_person_days": float(run.get("standby_person_days_if_line_held") or 0),
        "data_confidence": round(sum(weights) / len(weights), 4),
        "load_band_gap": float(run.get("load_band_gap") or 0),
        "days_late": late,
        "finish_date": run.get("finish_date"),
    }


def _blocked_note(blocked: List[Dict[str, Any]]) -> str:
    """阻塞原因要说清是"没人"还是"没依据" —— 前者是等，后者是模型代表不了，处置完全不同。"""
    label = {"no_staffed_line": "能做的线都没人在岗（只能等开工，不推演完工日）",
             "no_time_basis": "缺工时/缺可归属线（模型还没代表得了这台机）"}
    kinds = sorted({str(b.get("status")) for b in blocked})
    return "本轮不产出解：" + "；".join(label.get(k, k) for k in kinds)


async def declared_forbidden_policies(db: AsyncSession, factory_id: str,
                                      lines: List[Dict[str, Any]],
                                      policies: List[Dict[str, Any]]) -> List[str]:
    """返回被厂里声明"不许做"的政策名。只有 declared/validated 的 forbidden 才拦，candidate 不拦。"""
    from core.mes.action_constraints import ACTIONS, policy_actions
    from core.mes.factory_rules import binding_rules

    declared = await binding_rules(db, factory_id)
    hard = {k for k, v in declared.items()
            if str(v.get("verdict")) == "forbidden" and k.split(":")[0] in ACTIONS}
    if not hard:
        return []
    out: List[str] = []
    for pol in policies:
        acts = set(policy_actions(pol))
        if acts & hard:
            out.append(str(pol.get("name") or ""))
    return out


async def constraint_overlay(db: AsyncSession, factory_id: str,
                             targets: List[Dict[str, Any]],
                             policies: List[Dict[str, Any]],
                             lines: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把这一轮政策用到的动作送去约束层过一遍，读数随结论一起出门。

    默认没人看得到这层的话，引擎就会继续推荐厂里根本没声明过的动作。
    `enforce_constraints=False` 时只报不删（政策照跑）；True 时被规则判死的政策整条摘掉。
    拦不拦都留下读数：几条规则在生效、挡了哪几条政策、多少个动作没有依据 —— 不挡也要能看见没挡。
    """
    from core.mes.action_constraints import action_constraints, policy_actions

    per_model: List[Dict[str, Any]] = []
    for t in targets[:3]:
        model = str(t.get("model_code") or "")
        line = pick_line(model, lines)[0] or {}
        c = await action_constraints(db, factory_id, model=model,
                                     line_code=(line or {}).get("line_code"))
        per_model.append({"model": model, "line": (line or {}).get("line_code"),
                          "declared": {a["action"]: (a.get("binding_rule") or {})
                                       for a in c["actions"] if a.get("binding_rule")},
                          "verdicts": {a["action"]: a["verdict"] for a in c["actions"]},
                          "why": {a["action"]: a["why"] for a in c["actions"]
                                  if a["verdict"] not in ("allowed_bounded",)},
                          "constraint_gaps": c["constraint_gaps"]})
    per_policy: List[Dict[str, Any]] = []
    blocked: List[str] = []
    # 人力杠杆能买多少产能，要拿"标称班时 + 声明的加班上限"算，不能只看政策名字里的百分比
    try:
        from core.mes.data_evidence import attendance_evidence

        att = await attendance_evidence(db, factory_id)
    except Exception:  # noqa: BLE001  查不动时不折算，标注成无从判断
        att = {}
    norm = (att.get("shift_norm") or {}).get("norm_hours") if att.get("available") else None
    ot_cap = None
    for m in per_model:
        cap = ((m.get("declared") or {}).get("add_overtime") or {}).get("params")
        if isinstance(cap, str):
            try:
                cap = json.loads(cap or "{}")
            except (TypeError, ValueError):
                cap = {}
        if isinstance(cap, dict) and cap.get("max_hours_per_day") is not None:
            ot_cap = float(cap["max_hours_per_day"])
            break
    ds_days = int(((att.get("double_shift") or {}).get("observed_person_days")) or 0)

    def _workforce_feasibility(pol: Dict[str, Any]) -> Dict[str, Any]:
        share = float(pol.get("crew_bonus") or 0)
        if share <= 0:
            return {}
        out = {"crew_share": round(share, 3), "norm_hours": norm, "declared_ot_cap_hours": ot_cap,
               "observed_double_shift_person_days": ds_days}
        if norm and ot_cap is not None:
            ot_max_share = ot_cap / float(norm)
            out["ot_only_max_share"] = round(ot_max_share, 3)
            out["ot_hours_implied"] = round(share * float(norm), 2)
            out["achievable_by_overtime_only"] = bool(share <= ot_max_share + 1e-9)
            out["note"] = (
                f"{share:.0%} 折成每人日额外 {share * float(norm):.2f}h，"
                + (f"在厂规 {ot_cap:g}h 上限之内" if out["achievable_by_overtime_only"]
                   else f"超出厂规 {ot_cap:g}h 上限 —— 超出部分只能靠加人/双班"
                       f"（本厂实测两班倒 {ds_days} 人次，见 attendance_observed）"
                       "，引擎不许把它当成加班就能做到的事"))
        elif not norm:
            out["note"] = "没有到岗实测（attendance 读不到），这一档买多少产能无从判断"
        return out

    for pol in policies:
        acts = policy_actions(pol)
        unsupported = {m["model"]: [a for a in acts
                                    if str((m["verdicts"] or {}).get(a) or "").startswith(("undeclared", "forbidden"))]
                       for m in per_model}
        # forbidden 且来自人声明的规则 → 这个政策不再进候选集（"不能胡来"由规则负责）
        hard = [a for a in acts if any(str(v["verdicts"].get(a) or "") == "forbidden"
                                       and (v.get("declared") or {}).get(a) for v in per_model)]
        name = str(pol.get("name") or "")
        if hard:
            blocked.append(name)
        per_policy.append({"policy": name, "actions": acts, "blocked_by_rule": hard,
                           "workforce_feasibility": _workforce_feasibility(pol),
                           "unsupported": {k: v for k, v in unsupported.items() if v}})
    wf = [p.get("workforce_feasibility") or {} for p in per_policy]
    wf = [x for x in wf if x]
    return {"enforced": bool(blocked),
            "policies_blocked": len(blocked),
            "workforce_levers": len(wf),
            "workforce_levers_beyond_ot_cap": sum(1 for x in wf
                                                  if x.get("achievable_by_overtime_only") is False),
            "rules_in_effect": sorted({a for m in per_model for a in (m.get("declared") or {})}),
            "actions_unsupported_marks": sum(len(v or []) for p in per_policy
                                             for v in (p.get("unsupported") or {}).values()),
            "blocked_policies": blocked,
            "rule": ("只报不删：政策照跑，但每个动作有没有厂里的规则支撑要跟着结论出门。"
                     "要真拦下来得由 IE 先把规则填实，再由用户点一次开关。"),
            "per_model": per_model, "per_policy": per_policy}


async def scan_policies(db: AsyncSession, factory_id: str, targets: List[Dict[str, Any]],
                        *, today: Optional[date] = None,
                        policies: Optional[List[Dict[str, Any]]] = None,
                        scenarios: Optional[List[Dict[str, Any]]] = None,
                        targets_by_scenario: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                        perturb: Optional[Dict[str, float]] = None,
                        with_constraints: bool = False,
                        enforce_constraints: bool = True) -> Dict[str, Any]:
    """让引擎自己扫政策组合：同一批目标在多种产能/出勤/采购/分批政策下的多目标结果。

    这里刻意不给"唯一总分"。每个政策产出一个目标向量，交给 pareto_eval 判前沿与平衡解 ——
    工厂是取舍，不是考试。
    """
    today = today or date.today()
    lines = [dict(r) for r in (await db.execute(LINES_SQL, {"fid": factory_id})).mappings().all()]
    shift_days = {int(r["weekday"]) + 1 for r in
                  (await db.execute(CALENDAR_SQL, {"fid": factory_id})).mappings().all()} or {1, 2, 3, 4, 5, 6}
    policies = policies or await build_policy_grid(db, factory_id, targets)
    scenarios = scenarios or WEATHER_SCENARIOS
    demand_units = sum(float(t.get("units") or 0) for t in targets)
    demand_by_scenario: Dict[str, float] = {}

    equip = await equipment_rate(db, factory_id)
    busy_by_line: Dict[str, Dict[str, Any]] = {}
    for l in lines:
        busy_by_line[l["line_code"]] = await line_committed_days(db, factory_id, l)
    # 同组线共享已承诺量：一条线排着的活，并联时也占同一批人力/同一组产能
    group_busy: Dict[str, float] = {}
    for l in lines:
        grp = str(l.get("line_group") or l["line_code"])
        group_busy[grp] = max(group_busy.get(grp, 0.0),
                              float(busy_by_line[l["line_code"]]["busy_days"]))
    cache: Dict[str, Any] = {}
    grouped: Dict[str, Any] = {}
    # 天气档的比例是**声明的压力测试值**；台账量出来的常态到岗是另一个数。
    # 不重标定任何一档（标定是围绕可行率做的），但要把两者的差写进读数，
    # 否则"好天 0.97"会被当成实测到岗读走。
    measured = await measured_attendance(db, factory_id)
    for scen in scenarios:
      curve = {d: float(scen.get("attendance", DEFAULT_ATTENDANCE_RATE)) for d in range(0, 400)}
      # 每个天气场景可以用自己标定的目标（批量/交期系数），全局值兜底
      scen_targets = (targets_by_scenario or {}).get(scen["name"]) or targets
      demand_by_scenario[scen["name"]] = 0.0   # 逐政策算，只算"能推演的那部分需求"
      solutions: List[Dict[str, Any]] = []
      for pol in policies:
        per_run: List[Dict[str, Any]] = []
        # 本轮模拟出来的单也要排队：同一条线组的产能是它们一起占的。以前每台单只吃
        # "真实已承诺量"，于是三台跑步机机种各占 GROUP-TREAD 十几天却互不遮挡，
        # 交期普遍算得偏乐观 —— 而"谁先做"本来是引擎要做的决定，不是背景假设。
        # 人声明过禁止的动作所在的政策先挡掉，再进推演与择优 —— 规则负责"不能胡来"
        if enforce_constraints:
            _blocked = await declared_forbidden_policies(db, factory_id, lines, [pol])
            if _blocked:
                continue
        allocated: Dict[str, float] = {} if pol.get("ignore_backlog") else dict(group_busy)
        # 按线到岗是"这一轮政策"的属性：改派之后占用的是**改派后那条线**的队列，
        # 所以排队口径必须与 run_target 用同一个解析函数，不能在这里另算一遍。
        pol_staffing = normalize_staffing(pol.get("line_staffing"))
        ordered = sorted(scen_targets, key=lambda x: (int(x.get("due_in_days") or 999),
                                                      str(x.get("model_code"))))
        for t in ordered:
            due_day = int(t.get("due_in_days") or 30)
            line_of_t = pick_staffed_line(str(t["model_code"]), lines, pol_staffing)["line"] or {}
            grp = str(line_of_t.get("line_group") or line_of_t.get("line_code") or "")
            busy = float(allocated.get(grp, 0.0) or 0.0)
            run = await run_target(db, factory_id, str(t["model_code"]), float(t.get("units") or 0),
                                   today + timedelta(days=due_day), today, curve, lines, shift_days,
                                   expedite_lead_days=pol.get("expedite_lead_days"),
                                   allow_partial=bool(pol.get("allow_partial", True)),
                                   parallel_lines=int(pol.get("parallel_lines", 1)),
                                   crew_bonus=float(pol.get("crew_bonus", 0.0)),
                                   line_staffing=pol.get("line_staffing"),
                                   cached=cache, line_busy_days=(0.0 if pol.get("ignore_backlog") else busy),
                                   equip_rate=float((perturb or {}).get("equip_rate")
                                                    or equip.get("rate") or 1.0),
                                   hours_multiplier=float((perturb or {}).get("hours_multiplier", 1.0)),
                                   lead_multiplier=float((perturb or {}).get("lead_multiplier", 1.0)),
                                   stock_multiplier=float((perturb or {}).get("stock_multiplier", 1.0)),
                                   batches=int((perturb or {}).get("batches", 1)),
                                   changeover_hours=float((perturb or {}).get("changeover_hours",
                                                                              SIM_CHANGEOVER_HOURS)))
            # 排队要推进到这一台真正做完的那天。只累加 work_days 会让"到货日 > 排队"的那些台
            # 永远看不到队列 —— 实测 4 台 TREAD 都从第 20 天并行开工 = 同一条线被占用 4 次。
            allocated[grp] = max(busy, float(run.get("finish_day") or busy),
                                 busy + float(run.get("work_days") or 0))
            per_run.append({"run": run, "due_day": due_day, "units": float(t.get("units") or 0)})
        # 没有工时依据/没有可归属线的机种不算"厂里做不到"，是模型还代表不了它 —— 缺的是数据。
        # 把它们留在需求量里，每个政策都会卡产量底线，整轮扫描退化成"全都不可行"（实测踩过）。
        work = [x for x in per_run if x["run"].get("status") == "simulated"]
        blocked = [{"model_code": x["run"].get("model_code"), "units": x["units"],
                    "status": x["run"].get("status"), "why": x["run"].get("why")}
                   for x in per_run if x["run"].get("status") != "simulated"]
        if not work:
            solutions.append({"id": f"{scen['name']}-pol{len(solutions)}", "name": pol["name"],
                              "scenario": scen["name"],
                              "attendance": float(scen.get("attendance", 0.97)),
                              "policy": pol, "objectives": {}, "evidence": {},
                              "blocked_models": blocked, "detail": [],
                              "displaces_committed_work": bool(pol.get("ignore_backlog")),
                              "note": _blocked_note(blocked)})
            continue
        demand_by_scenario[scen["name"]] = round(sum(float(x["units"] or 0) for x in work), 2)
        worst_late = max(_objectives(x["run"], x["units"], x["due_day"])["days_late"] for x in work)
        on_time_n = sum(1 for x in work
                        if _objectives(x["run"], x["units"], x["due_day"])["on_time_rate"] >= 1.0)
        made = sum(_objectives(x["run"], x["units"], x["due_day"])["throughput_units"] for x in work)
        objs = {
            "on_time_rate": round(on_time_n / max(1, len(work)), 4),
            "throughput_units": round(made, 2),
            "labor_cost_usd": round(sum(float(x["run"].get("labor_cost_usd") or 0) for x in work), 2),
            "expedite_cost_usd": round(sum(float(x["run"].get("expedite_cost_usd") or 0)
                                           for x in work), 2),
            "standby_person_days": round(sum(float(x["run"].get("standby_person_days_if_line_held") or 0)
                                             for x in work), 1),
            "data_confidence": round(sum(_objectives(x["run"], x["units"], x["due_day"])["data_confidence"]
                                         for x in work) / max(1, len(work)), 4),
            "load_band_gap": round(sum(_objectives(x["run"], x["units"], x["due_day"])["load_band_gap"]
                                       for x in work) / max(1, len(work)), 4),  # 区间外才扣分
            "line_activation_cost_usd": round(sum(float(x["run"].get("line_activation_cost_usd") or 0)
                                                  for x in work), 2),
            # 连续延误天数：0/1 准点率会让"延 1 天"和"延 20 天"在后悔值上一样重
            "days_late_worst": worst_late,
        }
        solutions.append({
            "id": f"{scen['name']}-pol{len(solutions)}", "name": pol["name"],
            "scenario": scen["name"], "attendance": float(scen.get("attendance", 0.97)),
            "policy": pol,
            "objectives": objs,
            "blocked_models": blocked,
            "displaces_committed_work": bool(pol.get("ignore_backlog")),
            "sequencing": ("同一线组按交期先后排队（EDD）：每台单占用它自己的工时天数，"
                           "后面的单要等前面的做完才能上；"
                           "'插单'政策放开的是真实已排的活，默认不参与择优（见 pareto_eval）"),
            "evidence": {str(x["run"].get("route_basis")): 1 for x in work}
                        | {str(x["run"].get("hours_basis")): 1 for x in work}
                        | {str(x["run"].get("line_basis")): 1 for x in work},
            "detail": [{"model_code": x["run"].get("model_code"),
                        "units": x["run"].get("units"), "finish_date": x["run"].get("finish_date"),
                        "due_date": x["run"].get("due_date"), "days_late": x["run"].get("days_late"),
                        "status": x["run"].get("status"), "line": x["run"].get("line"),
                        "staffing": x["run"].get("staffing"),
                        "why": x["run"].get("why"),
                        "binding_terms": x["run"].get("binding_terms"),
                        "bom_source": x["run"].get("bom_source"),
                        "bom_parts": x["run"].get("bom_parts"),
                        "bom_levels": x["run"].get("bom_levels"),
                        "bom_problems": (x["run"].get("bom_problems") or [])[:3],
                        "batches_released": x["run"].get("batches_released"),
                        "changeover_days_added": x["run"].get("changeover_days_added"),
                        "queue_days_before_this_order": x["run"].get("line_busy_days_before_order"),
                        "capacity_basis": x["run"].get("capacity_basis"),
                        "capacity_binding": x["run"].get("capacity_binding"),
                        "work_days": x["run"].get("work_days"),
                        "started_on_day": x["run"].get("started_on_day"),
                        "earliest_start_day": x["run"].get("earliest_start_day"),
                        "hours_per_unit": x["run"].get("hours_per_unit"),
                        "hours_basis": x["run"].get("hours_basis"),
                        "wait_days_for_material": x["run"].get("wait_days_for_material"),
                        "capacity_line_declared": x["run"].get("capacity_line_declared"),
                        "capacity_hours_implied": x["run"].get("capacity_hours_implied"),
                        "material_arrival_day": x["run"].get("material_arrival_day"),
                        "batch_a_units": x["run"].get("batch_a_units"),
                        "batch_b_units": x["run"].get("batch_b_units"),
                        "batch_decision": x["run"].get("batch_decision"),
                        "blockers": x["run"].get("blockers"),
                        "po_lines": x["run"].get("po_lines"),
                        "bottleneck_part": x["run"].get("bottleneck_part")} for x in per_run],
        })
      ratio = float(scen.get("attendance", DEFAULT_ATTENDANCE_RATE))
      grouped[scen["name"]] = {"attendance": ratio, "solutions": solutions,
                               "attendance_kind": "declared_weather_stress",
                               "measured_attendance": (measured.get("present_ratio")
                                                       if measured.get("source") == "attendance_ledger"
                                                       else None),
                               "attendance_note": (
                                   f"这一档 {ratio:g} 是声明的天气压力值，不是量出来的常态到岗；"
                                   f"台账实测常态 {measured['present_ratio']:g}"
                                   f"（差 {round((measured['present_ratio'] - ratio) * 100, 2)} 个百分点）"
                                   if measured.get("source") == "attendance_ledger" else
                                   f"这一档 {ratio:g} 是声明值；这座厂没有台账缺勤率可对照"
                                   f"（退回常数 {DEFAULT_ATTENDANCE_RATE:g}）")}
    total = sum(len(v["solutions"]) for v in grouped.values())
    overlay = (await constraint_overlay(db, factory_id, targets, policies, lines)
               if with_constraints else None)
    return {"factory_id": factory_id, "today": str(today), "demand_units": demand_units,
            "demand_by_scenario": demand_by_scenario,
            "policies_tried": total, "scenarios": list(grouped),
            "by_scenario": grouped,
            "constraints": overlay,
            "note": ("前沿在每个天气场景内部各算一次：天气不是可选政策。"
                     "跨场景的推荐按'各场景推荐解里后悔向量最稳的那个'给。")}

