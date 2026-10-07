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
