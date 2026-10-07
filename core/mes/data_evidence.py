"""料号字段的"证据从哪来"普查：把悄悄生效的默认值变成看得见、可质疑的数据。

为什么要这一层：机械厂 31,452 个外购料号的 `lead_time_days` 只有 10 个不同取值
（3~20，均值 9.9），`make` 类 7,007 行全是 4 天，RM-ALUM-* 111 行全是 12 天 —— 这是按类别
铺出来的默认值，不是量出来的。而同期 65 单真采购的下单→到货实测均值 54 天、最长 123 天。
仿真引擎点瓶颈件、算最早开工日吃的就是这个字段；它要是默认值，推演再精细也是在替假数字背书。

这个模块**只读**：不回填 `materials`，不改任何事实表。它做三件事 ——
1. 逐字段说清出处（台账默认 / 采购实测 / 收货实测 / 供应商声明），并给出证据条数；
2. 冲突要摊开：台账 12 天、实测中位 78 天 → 报 `conflict`，而不是取其中一个当真相；
3. 普查必须自报"到底查了多少对象"，否则空结果分不清是"没问题"还是"没检查"。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 一个组里 n 个料号却只有极少数几个提前期取值 → 判定为"按类别铺的默认值"
DEFAULT_SUSPECT_MAX_DISTINCT = 15
DEFAULT_SUSPECT_MIN_PARTS = 50

MATERIAL_SQL = text("""
    SELECT material_code, material_name, material_type, make_or_buy,
           lead_time_days, default_supplier
    FROM materials WHERE factory_id = :fid
    ORDER BY material_code LIMIT :limit
""")

MATERIAL_BY_CODE_SQL = text("""
    SELECT material_code, material_name, material_type, make_or_buy,
           lead_time_days, default_supplier
    FROM materials WHERE factory_id = :fid AND material_code = ANY(:codes)
    ORDER BY material_code
""")

# 组内取值分散度用 SQL 聚合算全量（普查时不能只看返回的那几行）
GROUP_SHAPE_SQL = text("""
    SELECT make_or_buy, material_type, count(*) AS n_parts,
           count(DISTINCT lead_time_days) AS distinct_values,
           min(lead_time_days) AS min_days, max(lead_time_days) AS max_days,
           mode() WITHIN GROUP (ORDER BY lead_time_days) AS modal_days,
           array_agg(DISTINCT lead_time_days ORDER BY lead_time_days) AS values
    FROM materials WHERE factory_id = :fid AND lead_time_days IS NOT NULL
    GROUP BY 1,2 ORDER BY 3 DESC
""")

# 采购实测：下单 → 实际到货。actual < order 的脏行单独计数，不当"0 天"混进中位数
PO_MEASURED_SQL = text("""
    SELECT material_code, max(material_name) AS material_name,
           count(*) FILTER (WHERE actual_date >= order_date) AS n,
           count(*) FILTER (WHERE actual_date < order_date) AS n_bad_dates,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY (actual_date::date - order_date::date))
             FILTER (WHERE actual_date >= order_date) AS median_days,
           percentile_cont(0.9) WITHIN GROUP (ORDER BY (actual_date::date - order_date::date))
             FILTER (WHERE actual_date >= order_date) AS p90_days,
           min((actual_date::date - order_date::date)) FILTER (WHERE actual_date >= order_date) AS min_days,
           max((actual_date::date - order_date::date)) FILTER (WHERE actual_date >= order_date) AS max_days,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY GREATEST(0, expected_date::date - order_date::date))
             FILTER (WHERE expected_date IS NOT NULL) AS promised_median_days
    FROM purchase_orders
    WHERE factory_id = :fid AND order_date IS NOT NULL AND actual_date IS NOT NULL
    GROUP BY material_code
""")

# 收货实测：下单 → 仓收（比 PO 的 actual_date 更贴"什么时候能用"，是独立第二来源）
RECEIPT_MEASURED_SQL = text("""
    SELECT COALESCE(NULLIF(gr.material_code, ''), po.material_code) AS material_code,
           count(*) AS n,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY (gr.received_at::date - po.order_date::date)) AS median_days,
           max((gr.received_at::date - po.order_date::date)) AS max_days
    FROM goods_receipts gr
    JOIN purchase_orders po ON po.id = gr.po_id
    WHERE gr.factory_id = :fid AND gr.received_at IS NOT NULL AND po.order_date IS NOT NULL
    GROUP BY 1
""")

SUPPLIER_SQL = text("""
    SELECT supplier_code, supplier_name, avg_lead_days, lead_time_days, on_time_rate
    FROM suppliers WHERE factory_id = :fid
""")

# 自制/外购在两列上互相矛盾：`make_or_buy` 说外购、`material_type` 说 make（或反之）。
# 下游各读一列 —— 排产按 make_or_buy 判要不要买，齐套/成本按 material_type 判要不要自制，
# 于是同一个件在一处是"等 4 天到货"、在另一处是"线上自己做"。
CONTRADICTION_SQL = text("""
    SELECT make_or_buy, material_type, count(*) AS n,
           count(DISTINCT lead_time_days) AS distinct_lead,
           mode() WITHIN GROUP (ORDER BY lead_time_days) AS modal_days,
           min(lead_time_days) AS min_days, max(lead_time_days) AS max_days
    FROM materials
    WHERE factory_id = :fid
      AND ((make_or_buy = '外购' AND material_type = 'make')
        OR (make_or_buy = '自制' AND material_type IN ('purchased', 'raw')))
    GROUP BY 1,2 ORDER BY n DESC
""")


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


FLAG_SQL = text("""
    WITH g AS (
        SELECT make_or_buy, material_type, count(*) AS n,
               count(DISTINCT lead_time_days) AS distinct_values,
               mode() WITHIN GROUP (ORDER BY lead_time_days) AS modal_days
        FROM materials WHERE factory_id = :fid AND lead_time_days IS NOT NULL
        GROUP BY 1,2)
    SELECT m.material_code,
           CASE WHEN g.n >= :min_parts AND g.distinct_values <= :max_distinct
                     AND m.lead_time_days = g.modal_days
                THEN 'unverified_default' ELSE 'ledger_declared' END AS lead_evidence,
           m.lead_time_days
    FROM materials m
    JOIN g ON g.make_or_buy = m.make_or_buy AND g.material_type = m.material_type
    WHERE m.factory_id = :fid AND m.material_code = ANY(:codes)
""")

FLAG_MEASURED_SQL = text("""
    SELECT DISTINCT material_code FROM purchase_orders
    WHERE factory_id = :fid AND material_code = ANY(:codes)
      AND order_date IS NOT NULL AND actual_date IS NOT NULL AND actual_date >= order_date
""")


async def lead_flags(db: AsyncSession, factory_id: str, codes: List[str]) -> Dict[str, str]:
    """给一批料号各打一个提前期出处标签 —— 单表两条查询，供推演/接口逐行贴标，不做逐件查询。

    值：`unverified_default`（同组几十~几千个件共用同一个众数取值）/ `ledger_declared`（台账给了个不一样的值）/
    `measured`（这个号在本厂采购历史里真有下单→到货）/ `no_ledger_row`（台账压根没有这个号）。
    """
    codes = [str(c) for c in codes if c]
    if not codes:
        return {}
    rows = (await db.execute(FLAG_SQL, {"fid": factory_id, "codes": codes,
                                        "min_parts": DEFAULT_SUSPECT_MIN_PARTS,
                                        "max_distinct": DEFAULT_SUSPECT_MAX_DISTINCT})).mappings().all()
    out = {str(r["material_code"]): str(r["lead_evidence"]) for r in rows}
    for r in (await db.execute(FLAG_MEASURED_SQL, {"fid": factory_id, "codes": codes})).mappings().all():
        out[str(r["material_code"])] = "measured"
    for c in codes:
        out.setdefault(str(c), "no_ledger_row")
    return out


def _group_stats(rows: List[Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        key = f"{r['make_or_buy'] or ''}|{r['material_type'] or ''}"
        out[key] = {"make_or_buy": r["make_or_buy"], "material_type": r["material_type"],
                    "n_parts": int(r["n_parts"]), "distinct_values": int(r["distinct_values"]),
                    "min_days": r["min_days"], "max_days": r["max_days"], "modal_days": r["modal_days"],
                    "values": [int(v) for v in (r["values"] or [])][:20]}
    return out


async def lead_time_evidence(db: AsyncSession, factory_id: str,
                             codes: Optional[List[str]] = None,
                             limit: int = 200) -> Dict[str, Any]:
    """逐料号给出提前期的出处与冲突。`codes` 给了就只普查这些料号（引擎点名的瓶颈件），
    不给就按 `limit` 抽样 —— 组内分散度始终按全量算，不然抽样会把默认值看不出来。
    """
    params: Dict[str, Any] = {"fid": factory_id}
    if codes:
        rows = (await db.execute(MATERIAL_BY_CODE_SQL,
                                 dict(params, codes=[str(c) for c in codes]))).mappings().all()
    else:
        rows = (await db.execute(MATERIAL_SQL, dict(params, limit=int(limit)))).mappings().all()
    stats = _group_stats(list((await db.execute(GROUP_SHAPE_SQL, params)).mappings().all()))
    contra = [dict(r) for r in
              (await db.execute(CONTRADICTION_SQL, params)).mappings().all()]
    po_measured = {str(r["material_code"]): dict(r) for r in
                   (await db.execute(PO_MEASURED_SQL, params)).mappings().all()}
    receipts = {str(r["material_code"]): dict(r) for r in
                (await db.execute(RECEIPT_MEASURED_SQL, params)).mappings().all()}
    suppliers = {str(r["supplier_code"]): dict(r) for r in
                 (await db.execute(SUPPLIER_SQL, params)).mappings().all()}
    # 料号体系不同源是这里的常态（台账 SAP 号 vs 采购演示 RM-* 号），按品名精确桥一次；
    # 一品多码就不桥 —— 宁可 no_evidence，也不能把别人的到货天数安到这个件上。
    by_name: Dict[str, List[str]] = {}
    for code, m in po_measured.items():
        name = str(m.get("material_name") or "").strip()
        if name:
            by_name.setdefault(name, []).append(code)
    unique_name_bridge = {n: c for n, c in by_name.items() if len(c) == 1}
    ambiguous_names = sorted(n for n, c in by_name.items() if len(c) > 1)

    out_rows: List[Dict[str, Any]] = []
    for r in rows:
        code = str(r["material_code"])
        name = str(r.get("material_name") or "").strip()
        g = stats.get(f"{r.get('make_or_buy') or ''}|{r.get('material_type') or ''}") or {}
        lead = r.get("lead_time_days")
        po = po_measured.get(code)
        bridge_code = None
        if po is None and name and name in unique_name_bridge:
            bridge_code = unique_name_bridge[name]
            po = po_measured.get(bridge_code)
        rc = receipts.get(code) or (receipts.get(bridge_code) if bridge_code else None)
        sup_code = str(r.get("default_supplier") or "").strip()
        sup = suppliers.get(sup_code) if sup_code else None
        measured_median = _f((po or {}).get("median_days")) if (po or {}).get("n") else None

        suspect = bool(lead is not None
                       and int(g.get("n_parts") or 0) >= DEFAULT_SUSPECT_MIN_PARTS
                       and int(g.get("distinct_values") or 99) <= DEFAULT_SUSPECT_MAX_DISTINCT
                       and g.get("modal_days") is not None and int(lead) == int(g["modal_days"]))
        evidence = [x for x in (
            f"po_history(n={po['n']})" if po and po.get("n") else None,
            f"goods_receipt(n={rc['n']})" if rc and rc.get("n") else None,
            (f"supplier_declared({sup['supplier_code']}={sup.get('avg_lead_days')}d)"
             if sup and sup.get("avg_lead_days") else None)) if x]
        if measured_median:
            verdict = "ledger_default_conflicts_with_measured" if (
                lead is not None and measured_median >= 2 * max(1.0, float(lead))) else (
                "measured_over_default" if suspect else "measured")
        elif suspect:
            verdict = "unverified_default"
        elif lead is not None:
            verdict = "ledger_declared_only"
        else:
            verdict = "no_lead_time_at_all"
        out_rows.append({
            "material_code": code, "material_name": name or None,
            "make_or_buy": r.get("make_or_buy"), "material_type": r.get("material_type"),
            "ledger_days": lead,
            "group_shape": ({"n_parts": g["n_parts"], "distinct_values": g["distinct_values"],
                             "modal_days": g["modal_days"], "values": g["values"]} if g else None),
            "measured": ({"n": int(po["n"]), "median_days": round(measured_median, 1),
                          "p90_days": (round(_f(po["p90_days"]), 1) if po.get("p90_days") is not None else None),
                          "min_days": po.get("min_days"), "max_days": po.get("max_days"),
                          "promised_median_days": (round(_f(po["promised_median_days"]), 1)
                                                   if po.get("promised_median_days") is not None else None),
                          "n_bad_dates": int(po.get("n_bad_dates") or 0),
                          "bridged_from_code": bridge_code}
                         if po and po.get("n") and measured_median else None),
            "receipt_measured": ({"n": int(rc["n"]), "median_days": round(_f(rc["median_days"]) or 0, 1),
                                  "max_days": rc.get("max_days")} if rc and rc.get("n") else None),
            "supplier": ({"supplier_code": sup_code, "avg_lead_days": sup.get("avg_lead_days"),
                          "on_time_rate": sup.get("on_time_rate")} if sup else None),
            "verdict": verdict, "evidence": evidence,
            # 建议值只进这个字段，绝不回填台账：它是"要去核对的数"，不是"事实"
            "suggested_days": round(measured_median) if measured_median else None,
        })

    by_verdict: Dict[str, int] = {}
    for o in out_rows:
        by_verdict[o["verdict"]] = by_verdict.get(o["verdict"], 0) + 1
    conflicts = [o for o in out_rows if o["verdict"] == "ledger_default_conflicts_with_measured"]
    factory_verdicts: Dict[str, int] = {}
    for key, g in stats.items():
        # 全厂视角：整组只有一个取值 = 这一类件根本没分供应商/分规格量过
        if int(g["n_parts"]) >= DEFAULT_SUSPECT_MIN_PARTS and int(g["distinct_values"]) <= 3:
            factory_verdicts["flat_group:" + key] = int(g["n_parts"])
    return {
        "factory_id": factory_id,
        # 空结果必须能区分"没问题"和"没数据"：这个厂 materials 台账 0 行时，
        # verdict_counts 也是空的，读的人很容易当成"提前期都查过了"。
        "empty_reason": (None if rows else
                         f"厂区 {factory_id} 在 materials 台账里没有行（scanned_materials=0）—— "
                         "这是缺主数据，不是提前期都被验证过；本普查不代填，只说明无从核对"),
        "checked": {"scanned_materials": len(rows), "groups_computed": len(stats),
                    "po_evidence_materials": len(po_measured),
                    "receipt_evidence_materials": len(receipts), "suppliers": len(suppliers),
                    "contradiction_groups": len(contra),
                    "returned_rows": len(out_rows)},
        "coverage": {"with_measured_po": sum(1 for o in out_rows if o["measured"]),
                     "with_default_supplier": sum(1 for o in out_rows if o["supplier"]),
                     "unverified_default": by_verdict.get("unverified_default", 0),
                     "no_lead_time": by_verdict.get("no_lead_time_at_all", 0),
                     "flat_groups_all_factory": factory_verdicts},
        "lead_time_shape_by_group": stats,
        "make_or_buy_contradiction": {
            "groups": contra, "rows_affected": sum(int(c["n"]) for c in contra),
            "note": ("同一个件在 make_or_buy 与 material_type 上说法相反；排产读前者、"
                     "齐套/成本读后者时会得出两个不同的动作（买 vs 自制）。这是主数据决定，"
                     "本普查不改数据，只点名影响多少行。")},
        "verdict_counts": by_verdict,
        "name_bridge": {"bridged": sum(1 for o in out_rows
                                       if (o.get("measured") or {}).get("bridged_from_code")),
                        "ambiguous_names": ambiguous_names,
                        "note": "只在品名唯一对应时桥；一对多一律不桥"},
        "conflict_examples": sorted(conflicts, key=lambda o: -((o["measured"] or {}).get("median_days") or 0))[:20],
        "rows": out_rows,
        "basis": ("ledger=materials.lead_time_days；measured=purchase_orders.order_date→actual_date；"
                  "receipt=goods_receipts.received_at−purchase_orders.order_date；"
                  "supplier=suppliers.avg_lead_days（要 default_supplier 有值才接得上）。"
                  f"unverified_default 判据：同组料号≥{DEFAULT_SUSPECT_MIN_PARTS} 且该组提前期取值≤"
                  f"{DEFAULT_SUSPECT_MAX_DISTINCT} 个，本件取值==该组众数。"),
    }

# ── 到岗/加班普查：把 attendance 变成引擎能引用的现场边界 ────────────────────
# 动作约束那一层一直只能说"没人声明过"：加班、双班、缺勤其实现场天天在发生，
# 只是没人往规则表里写。这几张表有一万一千多行真实打卡，够把"没声明"换成"实测是多少"，
# 让引擎在缺规则时引用观测值而不是凭空假设（观测仍是候选，不当 binding）。
OT_FLOOR_HOURS = 10.2      # 超过标称班时 0.2h 以上才算加了班（打卡分钟抖动作不算）
DOUBLE_SHIFT_FLOOR_HOURS = 19.0


ATT_SUMMARY_SQL = text("""
    SELECT count(*) AS rows, count(DISTINCT operator_id) AS people, count(DISTINCT date) AS days,
           min(date)::text AS from_day, max(date)::text AS to_day,
           count(*) FILTER (WHERE status = 'leave') AS leave_rows,
           count(*) FILTER (WHERE status = 'late') AS late_rows,
           count(*) FILTER (WHERE status = 'present') AS present_rows,
           count(*) FILTER (WHERE check_in IS NULL OR check_out IS NULL) AS missing_clock
    FROM attendance WHERE factory_id = :fid
""")

ATT_SHIFTS_SQL = text("""
    WITH h AS (
        SELECT shift, EXTRACT(EPOCH FROM (check_out - check_in)) / 3600.0 AS hours
        FROM attendance
        WHERE factory_id = :fid AND check_in IS NOT NULL AND check_out IS NOT NULL
    )
    SELECT shift, count(*) AS rows,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY hours) AS median_hours,
           max(hours) AS max_hours,
           count(*) FILTER (WHERE hours > :dbl) AS double_shift,
           count(*) FILTER (WHERE hours > :ot AND hours <= :dbl) AS over_norm
    FROM h GROUP BY shift ORDER BY count(*) DESC
""")

# 段级归属：attendance.operator_id → operators → hr_employees.station（实测机械厂 100% 接得上）
ATT_SECTIONS_SQL = text("""
    WITH j AS (
        SELECT h.station, a.status,
               EXTRACT(EPOCH FROM (a.check_out - a.check_in)) / 3600.0 AS hours
        FROM attendance a
        JOIN operators o ON o.id = a.operator_id
        JOIN hr_employees h ON h.factory_id = o.factory_id
             AND (h.employee_code = o.employee_id OR h.id::text = o.employee_id)
        WHERE a.factory_id = :fid
    )
    SELECT station, count(*) AS rows,
           count(*) FILTER (WHERE status = 'leave') AS leave_rows,
           (count(*) FILTER (WHERE status = 'leave'))::numeric / nullif(count(*), 0) AS leave_rate,
           count(*) FILTER (WHERE status = 'late') AS late_rows,
           count(*) FILTER (WHERE hours > :dbl) AS double_shift,
           count(*) FILTER (WHERE hours > :ot AND hours <= :dbl) AS over_norm,
           max(hours) FILTER (WHERE hours <= :dbl) AS max_single_shift_hours
    FROM j GROUP BY station ORDER BY (count(*) FILTER (WHERE status = 'leave'))::numeric
         / nullif(count(*), 0) DESC NULLS LAST, count(*) DESC
""")

ATT_WORST_SECTION_DAY_SQL = text("""
    WITH j AS (
        SELECT a.date, h.station, count(*) AS n,
               count(*) FILTER (WHERE a.status = 'leave') AS lv
        FROM attendance a
        JOIN operators o ON o.id = a.operator_id
        JOIN hr_employees h ON h.factory_id = o.factory_id
             AND (h.employee_code = o.employee_id OR h.id::text = o.employee_id)
        WHERE a.factory_id = :fid
        GROUP BY a.date, h.station
    )
    SELECT date::text AS day, station, n AS headcount, lv AS absent,
           lv::numeric / nullif(n, 0) AS absence_rate
    FROM j WHERE n >= 4 ORDER BY lv::numeric / nullif(n, 0) DESC NULLS LAST LIMIT 8
""")

ATT_ATTRIBUTION_SQL = text("""
    SELECT count(*) AS rows,
           count(*) FILTER (WHERE h.station IS NOT NULL) AS attributed
    FROM attendance a
    JOIN operators o ON o.id = a.operator_id
    LEFT JOIN hr_employees h ON h.factory_id = o.factory_id
         AND (h.employee_code = o.employee_id OR h.id::text = o.employee_id)
    WHERE a.factory_id = :fid
""")

# 一个人在窗口里是否换过段：换过才谈得上"跨线调人有先例"
ATT_CROSS_STATION_SQL = text("""
    WITH p AS (
        SELECT a.operator_id, count(DISTINCT h.station) AS s
        FROM attendance a
        JOIN operators o ON o.id = a.operator_id
        JOIN hr_employees h ON h.factory_id = o.factory_id
             AND (h.employee_code = o.employee_id OR h.id::text = o.employee_id)
        WHERE a.factory_id = :fid
        GROUP BY a.operator_id
    )
    SELECT count(*) FILTER (WHERE s > 1) AS people_changed_station, count(*) AS people
    FROM p
""")


async def attendance_evidence(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    """到岗/加班只读普查：标称班时、加班实例、双班实例、段级缺勤率、最坏段-日。

    取不到的东西一律写进 checked/empty_reason，不折算成假设值：缺 check_out 的行不参与班时
    统计（另报 missing_clock），接不上人的行不参与段级统计（报 attributed）。
    """
    sm = dict((await db.execute(ATT_SUMMARY_SQL, {"fid": factory_id})).mappings().first() or {})
    if int(sm.get("rows") or 0) == 0:
        return {
            "factory_id": factory_id, "available": False,
            "empty_reason": (f"厂区 {factory_id} 在 attendance 里 0 行 —— 到岗/加班没有任何现场观测，"
                             "引擎不许把缺勤率当已知量用，只能等人声明或换厂区"),
            "checked": {"attendance_rows": 0},
        }

    floors = {"fid": factory_id, "ot": OT_FLOOR_HOURS, "dbl": DOUBLE_SHIFT_FLOOR_HOURS}
    shifts = [dict(r) for r in (await db.execute(ATT_SHIFTS_SQL, floors)).mappings().all()]
    sections = [dict(r) for r in (await db.execute(ATT_SECTIONS_SQL, floors)).mappings().all()]
    worst = [dict(r) for r in (await db.execute(ATT_WORST_SECTION_DAY_SQL, {"fid": factory_id})).mappings().all()]
    attr = dict((await db.execute(ATT_ATTRIBUTION_SQL, {"fid": factory_id})).mappings().first() or {})
    cross = dict((await db.execute(ATT_CROSS_STATION_SQL, {"fid": factory_id})).mappings().first() or {})

    # 标称班时取行数最多那个班次（最大班）的中位：加班/双班都相对它算，不在下游再设常数
    norm = _f(shifts[0]["median_hours"]) if shifts else None
    over = sum(int(s.get("over_norm") or 0) for s in shifts)
    dbl = sum(int(s.get("double_shift") or 0) for s in shifts)
    singles = [_f(s.get("max_single_shift_hours")) for s in sections
               if _f(s.get("max_single_shift_hours")) is not None]
    max_single = max(singles) if singles else None
    leave_rows = int(sm.get("leave_rows") or 0)
    clocked = int(sm.get("rows") or 0) - int(sm.get("missing_clock") or 0)
    extra = (round(max_single - norm, 2) if norm and max_single is not None else None)

    out_sections = [{
        "section": str(s.get("station") or ""), "rows": int(s.get("rows") or 0),
        "absent_rows": int(s.get("leave_rows") or 0),
        "absence_rate": round(_f(s.get("leave_rate")) or 0, 4),
        "late_rows": int(s.get("late_rows") or 0),
        "double_shift_person_days": int(s.get("double_shift") or 0),
        "overtime_person_days": int(s.get("over_norm") or 0),
        "max_single_shift_hours": (round(_f(s.get("max_single_shift_hours")), 2)
                                   if s.get("max_single_shift_hours") is not None else None),
    } for s in sections]
    worst_section = out_sections[0] if out_sections else None

    return {
        "factory_id": factory_id, "available": True,
        "window": {"from_day": sm.get("from_day"), "to_day": sm.get("to_day"),
                   "days": int(sm.get("days") or 0), "people": int(sm.get("people") or 0)},
        "checked": {"attendance_rows": int(sm.get("rows") or 0), "clocked_rows": clocked,
                    "missing_clock_rows": int(sm.get("missing_clock") or 0),
                    "attributed_rows": int(attr.get("attributed") or 0),
                    "sections_computed": len(out_sections),
                    "sections_with_absent": sum(1 for o in out_sections if o["absent_rows"])},
        "shift_norm": {"norm_hours": norm,
                       "by_shift": [{"shift": str(s.get("shift") or ""),
                                     "rows": int(s.get("rows") or 0),
                                     "median_hours": _f(s.get("median_hours")),
                                     "max_hours": _f(s.get("max_hours")),
                                     "double_shift": int(s.get("double_shift") or 0),
                                     "overtime": int(s.get("over_norm") or 0)} for s in shifts]},
        "overtime": {
            "observed_person_days": over,
            "max_observed_hours": round(max_single, 2) if max_single is not None else None,
            "max_observed_extra_hours": extra,
            "reading": (f"加班 {over} 人次，单人单日额外最长 {extra}h"
                        if over and extra is not None else
                        f"窗口内没有超过 {norm}h 标称班的打卡（加班 0 人次）")},
        "double_shift": {
            "observed_person_days": dbl,
            "top_sections": [{"section": o["section"], "person_days": o["double_shift_person_days"]}
                             for o in sorted(out_sections, key=lambda x: -x["double_shift_person_days"])[:5]],
            "reading": (f"两班倒 {dbl} 人次（打卡 ≥{DOUBLE_SHIFT_FLOOR_HOURS:.0f}h）—— "
                        "这是本店真用过的产能动作，不是假设" if dbl else
                        f"窗口内没有 ≥{DOUBLE_SHIFT_FLOOR_HOURS:.0f}h 的双班打卡")},
        "absence": {
            "overall_rate": (round(leave_rows / clocked, 4) if clocked else None),
            "absent_rows": leave_rows, "late_rows": int(sm.get("late_rows") or 0),
            "by_section": out_sections,
            "worst_section_days": [{"day": w.get("day"), "section": w.get("station"),
                                    "headcount": int(w.get("headcount") or 0),
                                    "absent": int(w.get("absent") or 0),
                                    "absence_rate": round(_f(w.get("absence_rate")) or 0, 4)}
                                   for w in worst],
            "reading": (f"段级缺勤最高 {worst_section['section']} "
                        f"{round(worst_section['absence_rate'] * 100, 1)}%"
                        if worst_section else "无段级数据")},
        "observability": {
            "people_changed_section": int(cross.get("people_changed_station") or 0),
            "people_tracked": int(cross.get("people") or 0),
            "note": ("每人在这几张表里静态归属一段，窗口内换段的有 "
                     f"{int(cross.get('people_changed_station') or 0)} 人 —— 0 说明「跨线调人」在打卡里"
                     "看不出来（不是没发生，是这张表记不了），引擎不许把它当成「从没调过人」的证据")},
        "basis": ("attendance(factory_id,date,operator_id,check_in,check_out,shift,status)；"
                  "段归属=operators.id→operator_id，再按 employee_code/employee_id 接 "
                  "hr_employees.station；标称班时=行数最多班次的打卡中位；"
                  f"加班=打卡 >{OT_FLOOR_HOURS}h 且 ≤{DOUBLE_SHIFT_FLOOR_HOURS:.0f}h，"
                  f"双班=打卡 >{DOUBLE_SHIFT_FLOOR_HOURS:.0f}h；缺勤=status='leave'。"
                  "本普查只读数，不写回任何表。"),
    }
