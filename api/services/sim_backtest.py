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
        "kit_gaps": gap_out,
        "fixable_by_rerun_orders": fixable,
        "per_model": sorted(per_model.values(),
                            key=lambda v: (-int(v["shortage_lines"]), -int(v["orders"])))[:20],
        "how_to_read": ("可比机种 = 有在流程单 + 有外购缺口行的机种；瓶颈位置命中率只在这些机种上才算得出对错题。"
                        "缺口归因里 child_no_bom/key_no_bom/pseudo_product/seed 四类**不是跑一次能补的**，"
                        "只有 flow_missing_kit 是；backtest 那三格说明回测缺的是工单上的计划开工日与交期。"),
    }
