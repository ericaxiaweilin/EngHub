"""L2B 就绪度：把"为什么算不出精度"分门别类量出来，而不是留一句"样本不够"。

两个判据（瓶颈命中率 / 回测 MAPE）都要求真实样本，而样本够不够取决于主数据。
这一层做的事：按机种把 工单数 / 齐套行 / 外购缺口行 / 可回测成对样本 一起列出来，
再把缺口**归成四类可行动的原因**（源侧没有组件级子 BOM、键在本厂镜像里根本没有 BOM 行、
出货柜这类伪产品、种子演示单），每类给单数与代表性机种 —— 这样计划员能看到该找谁补什么，
而不是看到一句"算不出"。

只读：不建 BOM、不改工单、不拿估算填历史字段。
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 仿真的 BOM 取数源（这是命中率算不对的根因之一，profile 里逐机种量出来）
BOM_SOURCE_SQL = """
WITH ms AS (SELECT DISTINCT product_id AS model FROM bom_items WHERE factory_id = :fid)
SELECT s.model,
       (SELECT COUNT(*) FROM bom_items b
         WHERE b.factory_id = :fid AND b.product_id = s.model) AS local_lines,
       (SELECT COUNT(*) FROM bom_items b
         WHERE b.factory_id = :fid AND b.product_id = s.model
           AND b.material_code ~ '^[0-9]+$') AS local_sap_lines,
       (SELECT COUNT(*) FROM bom_items b
         WHERE b.factory_id = :fid AND b.product_id = s.model
           AND b.material_code LIKE 'RM-%') AS local_synthetic_lines,
       (SELECT COUNT(*) FROM enghub_bom_items e WHERE e.product_model = s.model) AS mirror_lines,
       (SELECT COALESCE(MAX(e.level), 0) FROM enghub_bom_items e
         WHERE e.product_model = s.model) AS mirror_levels,
       (SELECT COUNT(DISTINCT e.part_number) FROM enghub_bom_items e
         WHERE e.product_model = s.model AND e.level = 1) AS mirror_level1_parts,
       (SELECT COUNT(*) FROM (SELECT DISTINCT e.part_number FROM enghub_bom_items e
              WHERE e.product_model = s.model AND e.level = 1) x
         JOIN materials m ON m.material_code = x.part_number AND m.factory_id = :fid
          WHERE m.lead_time_days IS NOT NULL) AS mirror_level1_with_lead
FROM ms s
"""

# 判线需要的最小样本（与 engine_layers.THRESHOLDS 同源，这里只是把口径写成人话）
MIN_COMPARABLE_MODELS = 5
MIN_BACKTEST_PAIRS = 10

# 在流程 = 还没尘埃落定，齐套行本该存在；cancelled 不参与（补它没有意义）
IN_FLOW = ("pending", "released", "in_progress")

READINESS_SQL = """
WITH m AS (
    SELECT DISTINCT product_id AS model FROM bom_items WHERE factory_id = :fid),
o AS (
    SELECT o.id, o.status, o.created_at::date AS cday, o.planned_start, o.planned_due,
           o.actual_complete, o.planned_qty AS qty,
           (o.parent_work_order_id IS NOT NULL) AS is_child,
           COALESCE(pp.product_code, p.product_code, o.product_id) AS model,
           o.product_id AS own_key,
           (SELECT COUNT(*) FROM bom_items b
             WHERE b.factory_id = o.factory_id AND b.product_id = o.product_id) AS own_bom_lines
    FROM work_orders o
    LEFT JOIN products p ON p.factory_id = o.factory_id
         AND (p.id::text = o.product_id OR p.product_code = o.product_id)
    LEFT JOIN work_orders par ON par.id = o.parent_work_order_id
    LEFT JOIN products pp ON pp.factory_id = par.factory_id
         AND (pp.id::text = par.product_id OR pp.product_code = par.product_id)
    WHERE o.factory_id = :fid),
k AS (
    SELECT w.work_order_id,
           COUNT(*) AS kit_lines,
           COUNT(*) FILTER (WHERE w.item_type = 'buy') AS buy_lines,
           COUNT(*) FILTER (WHERE w.item_type = 'buy' AND COALESCE(w.shortage_qty,0) > 0) AS short_lines
    FROM work_order_materials w GROUP BY 1)
SELECT o.model, o.id, o.status, o.is_child, o.own_key, o.own_bom_lines,
       COALESCE(k.kit_lines, 0) AS kit_lines, COALESCE(k.buy_lines, 0) AS buy_lines,
       COALESCE(k.short_lines, 0) AS short_lines,
       o.planned_start, o.planned_due, o.actual_complete, o.qty,
       (o.id LIKE 'wo-vf-%') AS is_seed,
       (b.model IS NOT NULL) AS model_in_bom
FROM o
LEFT JOIN k ON k.work_order_id = o.id
LEFT JOIN m b ON b.model = o.model
"""

BUCKET_LABELS = {
    "child_no_bom": "下级自制件子单：镜像里没有这一级的 BOM（源侧事实，不能由我们编）",
    "key_no_bom": "工单键在本厂 BOM 镜像里没有任何行（要么主数据缺这台，要么键归错厂）",
    "pseudo_product": "出货柜这类伪产品：BOM 只有装箱那几行，不构成产品齐套",
    "seed": "种子/演示单（id 形如 wo-vf-*）：不是真实需求，不拿来凑判据样本",
    "flow_missing_kit": "在流程单且没有齐套行，但 BOM 与键都在 —— 这类才是能补的",
    "backtest_no_planned_start": "已完工但没留计划开工日（回测没有锚点）",
    "backtest_model_no_bom": "已完工但机种在 BOM 镜像里没有行",
}


ORDER_SHORT_SQL = """
    WITH per_order AS (
        SELECT w.work_order_id, o.planned_qty AS qty,
               COALESCE(pp.product_code, p.product_code, o.product_id) AS model,
               (ARRAY_AGG(w.material_code ORDER BY w.shortage_qty DESC))[1] AS most_missing,
               (ARRAY_AGG(w.material_code ORDER BY COALESCE(m.lead_time_days, -1) DESC,
                                                    w.shortage_qty DESC))[1] AS longest_lead,
               MAX(w.shortage_qty) AS top_short_qty
        FROM work_order_materials w
        JOIN work_orders o ON o.id = w.work_order_id
        LEFT JOIN materials m ON m.material_code = w.material_code AND m.factory_id = o.factory_id
        LEFT JOIN products p ON p.factory_id = o.factory_id
             AND (p.id::text = o.product_id OR p.product_code = o.product_id)
        LEFT JOIN work_orders par ON par.id = o.parent_work_order_id
        LEFT JOIN products pp ON pp.factory_id = par.factory_id
             AND (pp.id::text = par.product_id OR pp.product_code = par.product_id)
        WHERE o.factory_id = :fid AND w.item_type = 'buy'
          AND COALESCE(w.shortage_qty, 0) > 0
          AND o.status NOT IN ('completed', 'cancelled') AND o.id NOT LIKE 'wo-vf-%'
        GROUP BY 1, 2, 3)
    SELECT model, qty, most_missing, longest_lead, top_short_qty, work_order_id
    FROM per_order ORDER BY top_short_qty DESC
"""


async def bottleneck_agreement(db: AsyncSession, factory_id: str, *, limit: int = 120) -> Dict[str, Any]:
    """引擎选的那件料 vs 台账同一张单选的那件 —— 两种定义各算一次。

    为什么必须分开算：仿真的「瓶颈件」是决定到货日的那件（外购缺料里提前期最长的），
    台账上最直觉的「缺最多那件」是数量口径。原来我拿前者比后者，得到 0/40 ——
    那个 0 是**指标定义错了**，不是引擎判错（实测样单里 `1000108191` 两边都是「缺最多那件」，
    但引擎按提前期选的是另一件）。

    已知偏差：引擎用今天的库存与在途重算净需求，台账那行是当时算的；对下达很久的单
    两边不一致是预期内的。这一格读的是「有没有对错题」，不是模型达标与否。
    """
    from api.services import virtual_run as vr

    rows = list((await db.execute(text(ORDER_SHORT_SQL), {"fid": factory_id})).mappings().all())
    rows = rows[:max(1, int(limit))]
    cache: Dict[tuple, Dict[str, Any]] = {}
    per_order: List[Dict[str, Any]] = []
    for r in rows:
        model = str(r["model"] or "")
        qty = float(r["qty"] or 0) or 1.0
        key = (model, qty)
        if key not in cache:
            got = await vr.sim_bom_lines(db, factory_id, model, qty)
            codes = [str(x["material_code"]) for x in got["rows"]]
            stock_rows = (await db.execute(
                vr.STOCK_SQL, {"fid": factory_id, "codes": codes})).mappings().all() if codes else []
            stock = {str(x["material_code"]): float(x["available"] or 0) for x in stock_rows}
            kit = vr.build_kit(got["rows"], qty, stock, start_day=0)
            short_buy = [l for l in kit.get("lines") or []
                         if str(l.get("make_or_buy")) == "外购" and float(l.get("short") or 0) > 0]
            by_qty = sorted(short_buy, key=lambda l: -float(l["short"]))
            by_lead = sorted(short_buy, key=lambda l: (
                -int(l["lead_time_days"]) if str(l.get("lead_time_days") or "").isdigit() else 1,
                -float(l["short"])))
            cache[key] = {
                "lead_top": by_lead[0]["material_code"] if by_lead else None,
                "qty_top": by_qty[0]["material_code"] if by_qty else None,
                "short_parts": len(short_buy), "source": got["source"]}
        got = cache[key]
        per_order.append({
            "work_order_id": str(r["work_order_id"]), "model": model, "units": qty,
            "engine_lead_top": got["lead_top"], "engine_qty_top": got["qty_top"],
            "ledger_longest_lead": str(r["longest_lead"]),
            "ledger_most_missing": str(r["most_missing"]),
            "lead_agrees": bool(got["lead_top"]) and got["lead_top"] == str(r["longest_lead"]),
            "qty_agrees": bool(got["qty_top"]) and got["qty_top"] == str(r["most_missing"]),
            "engine_shortage_parts": got["short_parts"], "bom_source": got["source"]})
    n = len(per_order)
    lead_hits = sum(1 for x in per_order if x["lead_agrees"])
    qty_hits = sum(1 for x in per_order if x["qty_agrees"])
    models = sorted({x["model"] for x in per_order})

    def _by_model(flag):
        out = []
        for m in models:
            sub = [x for x in per_order if x["model"] == m]
            hits = sum(1 for x in sub if x[flag])
            out.append({"model": m, "orders": len(sub), "agree": hits,
                        "rate": round(hits / max(1, len(sub)), 3)})
        return sorted(out, key=lambda v: -v["orders"])

    return {
        "orders_compared": n,
        "lead_based": {"agree": lead_hits, "rate": round(lead_hits / n, 3) if n else None,
                       "definition": "外购缺料里提前期最长的那件（决定到货日的那件）"},
        "quantity_based": {"agree": qty_hits, "rate": round(qty_hits / n, 3) if n else None,
                           "definition": "外购缺料里净缺口最大的那件"},
        "models_compared": len(models), "model_list": models,
        "per_model": _by_model("lead_agrees"),
        "per_model_by_quantity": _by_model("qty_agrees"),
        "bom_sources": sorted({str(x["bom_source"]) for x in per_order}),
        "disagreements": [x for x in per_order if not x["lead_agrees"]][:8],
        "meaning": ("这一格读的是「引擎与台账在同一张单上会不会选中同一件料」，两种定义都要看："
                    "只看数量会漏掉「缺得多但不卡日期」的件，只看提前期会漏掉「量大到必须现在下单」的件。"
                    "库存取今天而非当时快照，所以对老单不一致是预期内的。"),
    }


def classify_gap(row: Dict[str, Any]) -> str:
    """给一张没有齐套行的工单归因。顺序是讲究的：先排掉不该参与判据的（种子、伪产品），
    再看键与源侧 —— 否则会把"根本不该有行"的单算成"可补"。"""
    if row.get("is_seed"):
        return "seed"
    own = int(row.get("own_bom_lines") or 0)
    key = str(row.get("own_key") or "")
    if key.upper().startswith("VF-") or "40HQ" in key.upper() or "40HC" in key.upper():
        return "pseudo_product"
    if row.get("is_child") and own == 0:
        return "child_no_bom"
    if own == 0:
        return "key_no_bom"
    return "flow_missing_kit"


async def readiness(db: AsyncSession, factory_id: str) -> Dict[str, Any]:
    rows = (await db.execute(text(READINESS_SQL), {"fid": factory_id})).mappings().all()
    per_model: Dict[str, Dict[str, Any]] = {}
    gaps: Dict[str, Dict[str, Any]] = {}
    backtest = {"completed": 0, "pairs_ok": 0, "no_planned_start": 0, "model_no_bom": 0}
    for r in rows:
        model = str(r["model"] or "")
        slot = per_model.setdefault(model, {
            "model": model, "orders": 0, "orders_in_flow": 0, "orders_with_kit_lines": 0,
            "kit_lines": 0, "buy_lines": 0, "shortage_lines": 0,
            "comparable_for_bottleneck": False, "has_bom": bool(r["model_in_bom"]),
        })
        slot["orders"] += 1
        slot["kit_lines"] += int(r["kit_lines"] or 0)
        slot["buy_lines"] += int(r["buy_lines"] or 0)
        slot["shortage_lines"] += int(r["short_lines"] or 0)
        if int(r["kit_lines"] or 0) > 0:
            slot["orders_with_kit_lines"] += 1
        if str(r["status"] or "") in IN_FLOW:
            slot["orders_in_flow"] += 1
            if int(r["short_lines"] or 0) > 0:
                slot["comparable_for_bottleneck"] = True
        # 缺齐套行的归因只对在流程单有意义（cancelled 补它没有业务价值）
        if int(r["kit_lines"] or 0) == 0 and str(r["status"] or "") in IN_FLOW:
            bucket = classify_gap(dict(r))
            g = gaps.setdefault(bucket, {"count": 0, "models": {}})
            g["count"] += 1
            g["models"][model] = g["models"].get(model, 0) + 1
        if str(r["status"] or "") == "completed" and r["actual_complete"] is not None:
            backtest["completed"] += 1
            if not bool(r["model_in_bom"]):
                backtest["model_no_bom"] += 1
            elif r["planned_start"] is None or r["planned_due"] is None:
                backtest["no_planned_start"] += 1
            else:
                backtest["pairs_ok"] += 1

    # BOM 取数源画像：仿真现在只读本地 bom_items，而台账/领料走 engflow 真源镜像。
    # 逐机种量出两边各有多少行、真源有几层、level-1 件在 materials 里有没有提前期 ——
    # 没有这些数，"切到真源"就是一句口号；切了会不会没料可算也只有这里能看出来。
    src_rows = (await db.execute(text(BOM_SOURCE_SQL), {"fid": factory_id})).mappings().all()
    bom_sources = []
    for r in src_rows:
        bom_sources.append({
            "model": str(r["model"]),
            "sim_source_lines": int(r["local_lines"] or 0),
            "sim_source_sap_lines": int(r["local_sap_lines"] or 0),
            "sim_source_synthetic_lines": int(r["local_synthetic_lines"] or 0),
            "real_source_lines": int(r["mirror_lines"] or 0),
            "real_source_levels": int(r["mirror_levels"] or 0),
            "real_source_level1_parts": int(r["mirror_level1_parts"] or 0),
            "real_source_level1_with_lead": int(r["mirror_level1_with_lead"] or 0),
            "switchable": bool(int(r["mirror_lines"] or 0) > 0),
        })
    switchable = [b for b in bom_sources if b["switchable"]]
    comparable = sorted(m for m, v in per_model.items() if v["comparable_for_bottleneck"])
    with_bom = sorted(m for m, v in per_model.items() if v["has_bom"])
    gap_out = [{"reason": k, "label": BUCKET_LABELS.get(k, k), "orders": v["count"],
                "top_models": [f"{m}×{n}" for m, n in
                               sorted(v["models"].items(), key=lambda x: -x[1])[:4]]}
               for k, v in sorted(gaps.items(), key=lambda x: -x[1]["count"])]
    fixable = next((g["orders"] for g in gap_out if g["reason"] == "flow_missing_kit"), 0)
    return {
        "factory_id": factory_id,
        "models_in_bom_mirror": len({m for m in with_bom}),
        "models_with_orders": len(per_model),
        "bottleneck_comparable_models": len(comparable),
        "bottleneck_comparable_list": comparable,
        "bottleneck_min_models_required": MIN_COMPARABLE_MODELS,
        "bottleneck_verdict": ("可判" if len(comparable) >= MIN_COMPARABLE_MODELS else
                               f"不可判：可比机种 {len(comparable)} < {MIN_COMPARABLE_MODELS}"),
        "backtest": {**backtest, "min_pairs_required": MIN_BACKTEST_PAIRS,
                     "verdict": ("可判" if backtest["pairs_ok"] >= MIN_BACKTEST_PAIRS else
                                 f"不可判：成对样本 {backtest['pairs_ok']} < {MIN_BACKTEST_PAIRS}")},
        "bom_source": {
            "sim_reads": "bom_items（本地）",
            "ledger_reads": "enghub_bom_items（engflow 真源镜像）+ materials 提前期",
            "models_total": len(bom_sources),
            "models_with_real_source": len(switchable),
            "models_with_real_source_list": sorted(b["model"] for b in switchable),
            "verdict": (f"{len(switchable)}/{len(bom_sources)} 个机种在真源镜像里有行 —— "
                        "切取数源只能切这些；其余机种真源没有行，切过去等于没料可算"),
            "per_model": bom_sources,
        },
        "kit_gaps": gap_out,
        "fixable_by_rerun_orders": fixable,
        "per_model": sorted(per_model.values(),
                            key=lambda v: (-int(v["shortage_lines"]), -int(v["orders"])))[:20],
        "how_to_read": ("可比机种 = 有在流程单 + 有外购缺口行的机种；瓶颈位置命中率只在这些机种上才算得出对错题。"
                        "缺口归因里 child_no_bom/key_no_bom/pseudo_product/seed 四类**不是跑一次能补的**，"
                        "只有 flow_missing_kit 是；backtest 那三格说明回测缺的是工单上的计划开工日与交期。"),
    }
