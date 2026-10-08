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

# 仿真的 BOM 取数源（这是命中率算不对的根因之一，profile 里逐机种量出来）。
# 机种全集必须同时取两头：只从本地 bom_items 出发，镜像里那些"本地压根没有"的机种就永远不出现在
# 画像上 —— 实测本机镜像有 473 个机种，与本地 bom_items 重合的只有 1 个，而有工单的镜像机种 3 个
# 里有 2 个是本画像原先看不见的（10-07 由 bom_source 探针对撞出来）。
# 镜像侧只收"真被工单要求过"的机种，否则 473 行画像没人看。
BOM_SOURCE_SQL = """
WITH ms AS (
    SELECT DISTINCT product_id AS model FROM bom_items WHERE factory_id = :fid
    UNION
    SELECT DISTINCT e.product_model FROM enghub_bom_items e
      WHERE e.factory_id = :fid
        AND e.product_model IN (SELECT DISTINCT product_id FROM work_orders
                                 WHERE factory_id = :fid)
)
SELECT s.model,
       (SELECT COUNT(*) FROM bom_items b
         WHERE b.factory_id = :fid AND b.product_id = s.model) AS local_lines,
       (SELECT COUNT(*) FROM bom_items b
         WHERE b.factory_id = :fid AND b.product_id = s.model
           AND b.material_code ~ '^[0-9]+$') AS local_sap_lines,
       (SELECT COUNT(*) FROM bom_items b
         WHERE b.factory_id = :fid AND b.product_id = s.model
           AND b.material_code LIKE 'RM-%') AS local_synthetic_lines,
       (SELECT COUNT(*) FROM enghub_bom_items e
         WHERE e.factory_id = :fid AND e.product_model = s.model) AS mirror_lines,
       (SELECT COALESCE(MAX(e.level), 0) FROM enghub_bom_items e
         WHERE e.factory_id = :fid AND e.product_model = s.model) AS mirror_levels,
       (SELECT COUNT(DISTINCT e.part_number) FROM enghub_bom_items e
         WHERE e.factory_id = :fid AND e.product_model = s.model AND e.level = 1) AS mirror_level1_parts,
       (SELECT COUNT(*) FROM (SELECT DISTINCT e.part_number FROM enghub_bom_items e
              WHERE e.factory_id = :fid AND e.product_model = s.model AND e.level = 1) x
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
               ARRAY_AGG(w.material_code ORDER BY w.shortage_qty DESC) AS qty_rank,
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
    SELECT model, qty, most_missing, longest_lead, top_short_qty, work_order_id, qty_rank
    FROM per_order ORDER BY top_short_qty DESC
"""


async def bottleneck_agreement(db: AsyncSession, factory_id: str, *, limit: int = 120) -> Dict[str, Any]:
    """引擎选的那件料 vs 台账同一张单选的那件 —— 两种定义 + 排名重叠度一起算。

    为什么不能只比第一名：仿真的「瓶颈件」是外购缺料里提前期最长的那件（决定到货日），
    台账最直觉的「缺最多那件」是数量口径；两边就算都判对，第一名也可能不同。
    所以这里同时报：精确一致率（两种定义）、top-5 重叠率、台账第一件在引擎榜里的名次与 MRR。

    已知偏差：引擎用今天的库存与在途重算净需求，台账那行是当时算的；对下达很久的单
    名次漂移是预期内的。这一格读的是「引擎与台账看的是不是同一批料」，不是达标与否。
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
                "qty_rank": [str(l["material_code"]) for l in by_qty],
                "lead_rank": [str(l["material_code"]) for l in by_lead],
                "short_parts": len(short_buy), "source": got["source"],
                "universe": {str(c) for c in codes}, "stock": stock,
                "per_unit": {str(x["material_code"]): float(x.get("qty_per_unit") or 0)
                             for x in got["rows"]},
                "lead": {str(x["material_code"]):
                         (int(str(x["lead_time_days"]))
                          if str(x.get("lead_time_days") or "").isdigit() else -1)
                         for x in got["rows"]}}
        got = cache[key]
        led_rank = list(dict.fromkeys(str(x) for x in (r["qty_rank"] or [])))
        eng_rank = list(got["qty_rank"])
        eng_lead = list(got["lead_rank"])
        # 一致率之前先得有个共同宇宙：台账那件在引擎展开的料号里根本不存在时，
        # 第一名永远不可能对——那是 BOM 世代不同，不是模型判错，混在一个分母里会把
        # "取数源没对齐"算成"引擎不准"。
        on_universe = {
            "ledger_top_in_engine_bom": str(r["most_missing"]) in got["universe"],
            "engine_top_in_ledger_lines": bool(got["qty_top"]) and got["qty_top"] in set(led_rank),
        }

        def _rank(needle: Optional[str], pool: List[str]) -> Optional[int]:
            return (pool.index(needle) + 1) if needle and needle in pool else None

        k = 5
        inter = len(set(eng_rank[:k]) & set(led_rank[:k]))
        per_order.append({
            "work_order_id": str(r["work_order_id"]), "model": model, "units": qty,
            "engine_lead_top": got["lead_top"], "engine_qty_top": got["qty_top"],
            "ledger_longest_lead": str(r["longest_lead"]), "ledger_most_missing": str(r["most_missing"]),
            "lead_agrees": bool(got["lead_top"]) and got["lead_top"] == str(r["longest_lead"]),
            "qty_agrees": bool(got["qty_top"]) and got["qty_top"] == str(r["most_missing"]),
            "ledger_first_in_engine_top5": (k and str(r["most_missing"]) in eng_rank[:k]) or False,
            "engine_first_in_ledger_top5": (bool(got["qty_top"]) and got["qty_top"] in led_rank[:k]) or False,
            "top5_overlap": round(inter / max(1, min(k, len(eng_rank), len(led_rank) or k)), 3),
            "ledger_first_engine_rank": _rank(str(r["most_missing"]), eng_rank),
            "engine_first_ledger_rank": _rank(got["qty_top"], led_rank),
            "engine_shortage_parts": got["short_parts"],
            "ledger_shortage_parts": len(led_rank), "bom_source": got["source"],
            **on_universe,
            "shared_universe": bool(on_universe["ledger_top_in_engine_bom"]
                                    and on_universe["engine_top_in_ledger_lines"])})
    n = len(per_order)
    lead_hits = sum(1 for x in per_order if x["lead_agrees"])
    qty_hits = sum(1 for x in per_order if x["qty_agrees"])
    models = sorted({x["model"] for x in per_order})

    def _rate(flag):
        c = sum(1 for x in per_order if x.get(flag))
        return {"agree": c, "rate": round(c / n, 3) if n else None}

    def _mrr(flag):
        vals = []
        for x in per_order:
            rk = x.get(flag)
            vals.append(1.0 / rk if rk else 0.0)
        return round(sum(vals) / max(1, len(vals)), 3)

    overlaps = [x["top5_overlap"] for x in per_order if x["top5_overlap"] is not None]

    def _by_model(key_name):
        out = []
        for m in models:
            sub = [x for x in per_order if x["model"] == m]
            hits = sum(1 for x in sub if x.get(key_name))
            out.append({"model": m, "orders": len(sub), "agree": hits,
                        "rate": round(hits / max(1, len(sub)), 3)})
        return sorted(out, key=lambda v: -v["orders"])

    # 同世代对照：台账那侧还是用**它自己登记的行**，只把缺口按今天的库存重算一遍。
    # 这样两边唯一的差别就剩"怎么算瓶颈"，不再混着"那行快照是哪天打的"——
    # 一致率 0.057 里有多少是快照过期、多少是模型真判错，只有这么切才量得出来。
    order_rows: Dict[str, List[Dict[str, Any]]] = {}
    if per_order:
        for g in (await db.execute(text("""
            SELECT w.work_order_id, w.material_code, w.required_qty
            FROM work_order_materials w
            WHERE w.work_order_id = ANY(CAST(:ids AS text[])) AND w.item_type = 'buy'
        """), {"ids": [x["work_order_id"] for x in per_order]})).mappings().all():
            order_rows.setdefault(str(g["work_order_id"]), []).append(
                {"code": str(g["material_code"]), "req": float(g["required_qty"] or 0)})

    # 两边的「需求量」算法本来就不是一个口径：台账行按毛需求逐层炸开（父层有库存也照炸子层），
    # 引擎按低层码净额（父层够用就不往下炸）。同一天库存、同一批料号，第一名照样会差 ——
    # 所以先把这个算法差量出来，别把它记成"模型判错"，也别记成"快照过期"。
    paired = eq = lower = higher = eng_zero = 0
    ratios: List[float] = []
    for x in per_order:
        basis = (cache.get((x["model"], float(x["units"]))) or {}).get("per_unit") or {}
        for row in (order_rows.get(x["work_order_id"]) or []):
            if row["code"] not in basis:
                continue
            paired += 1
            eng_need = basis[row["code"]] * float(x["units"])
            led_req = row["req"]
            if abs(eng_need - led_req) < 0.001:
                eq += 1
            elif eng_need < led_req:
                lower += 1
                if eng_need <= 0.0005 and led_req > 0:
                    eng_zero += 1          # 引擎判"父层够用，这颗不用炸"，台账照炸出需求
                elif led_req > 0:
                    ratios.append(eng_need / led_req)
            else:
                higher += 1
                if led_req > 0:
                    ratios.append(eng_need / led_req)
    # 覆盖率低到底是被什么封顶的：逐单数一下台账登记了几行外购齐套行。
    # 实测 70 张里 63 张还停在旧的单层快照（中位 8 行），只有 6 张按多层展开登记过（最多 680 行、深 9 层）——
    # 那是"重跑一次登记作业"就能挪动的盖子，不是"镜像里没有子 BOM"那种源侧死账，两条出路不能混着写。
    per_order_rows = [len(order_rows.get(x["work_order_id"]) or []) for x in per_order]
    per_order_rows.sort()
    synth_orders = sum(1 for x in per_order
                       if any(str(rw["code"]).startswith("RM-")
                              for rw in (order_rows.get(x["work_order_id"]) or [])))
    buckets = {"0 行": sum(1 for v in per_order_rows if v == 0),
               "1-20 行（旧的单层快照）": sum(1 for v in per_order_rows if 1 <= v <= 20),
               "21-200 行": sum(1 for v in per_order_rows if 20 < v <= 200),
               ">200 行（已按多层登记）": sum(1 for v in per_order_rows if v > 200)}
    row_depth = {
        "buy_rows_per_order_buckets": buckets,
        "median_buy_rows": (per_order_rows[len(per_order_rows) // 2] if per_order_rows else None),
        "max_buy_rows": (per_order_rows[-1] if per_order_rows else None),
        "orders_with_synthetic_rows": synth_orders,
        "meaning": ("覆盖率是被登记世代封顶的：多数单还停在旧的单层快照（一个机种十几行），"
                    "少数单已按多层展开登记（同机种 680 行、深 9 层）。"
                    "前者重跑一次齐套登记就能对齐，不是源侧缺组件级子 BOM"),
    }

    ratios.sort()
    requirement_basis = {
        "rows_paired": paired, "required_qty_equal": eq,
        "engine_lower_than_ledger": lower, "engine_higher_than_ledger": higher,
        "engine_says_zero_ledger_asks_positive": eng_zero,
        "median_engine_over_ledger_both_positive": (
            round(ratios[len(ratios) // 2], 4) if ratios else None),
        "definition": ("引擎净需求 = 父层净事后往下炸（低层码）；台账行 = 毛需求逐层乘下来。"
                       "同一料号同一个库存，两种算法给出的净缺不一样，第一名自然常不同"),
    }

    same_gen = {"orders": 0, "qty_top_agrees": 0, "lead_top_agrees": 0,
                "no_short_now": 0, "qty_top_agree_in_shared": 0}
    for x in per_order:
        entry = cache.get((x["model"], float(x["units"]))) or {}
        stock, lead = entry.get("stock") or {}, entry.get("lead") or {}
        short_now = [(row["code"], max(0.0, row["req"] - float(stock.get(row["code"], 0.0))))
                     for row in (order_rows.get(x["work_order_id"]) or [])]
        short_now = [t for t in short_now if t[1] > 0]
        if not short_now:
            same_gen["no_short_now"] += 1
            continue
        top_qty = max(short_now, key=lambda t: t[1])[0]
        top_lead = max(short_now, key=lambda t: (int(lead.get(t[0], -1)), t[1]))[0]
        same_gen["orders"] += 1
        same_gen["qty_top_agrees"] += int(bool(x["engine_qty_top"]) and top_qty == x["engine_qty_top"])
        same_gen["lead_top_agrees"] += int(bool(x["engine_lead_top"]) and top_lead == x["engine_lead_top"])
        if x["shared_universe"]:
            same_gen["qty_top_agree_in_shared"] += int(bool(x["engine_qty_top"])
                                                       and top_qty == x["engine_qty_top"])

    # 两边点名的件各在 BOM 的第几层。这决定"点不到同一件"是不是结构性的：
    # 齐套行主要按 level-1 登记，而引擎按 bom_source 展开到多层 —— 它点的件如果在台账那侧
    # 根本没有行，第一名就永远不可能对，那是取数世代/层级的问题，不是模型判错。
    codes = {x["engine_qty_top"] for x in per_order if x["engine_qty_top"]}
    models_ = {x["model"] for x in per_order}
    level_by_part = {}
    if codes and models_:
        level_by_part = {
            (str(r["product_model"]), str(r["part_number"])): int(r["level"] or 0)
            for r in (await db.execute(text("""
                SELECT e.product_model, e.part_number, MIN(e.level) AS level
                FROM enghub_bom_items e
                WHERE e.factory_id = :fid AND e.product_model = ANY(CAST(:ms AS text[]))
                  AND e.part_number = ANY(CAST(:cs AS text[]))
                GROUP BY 1, 2
            """), {"fid": factory_id, "ms": sorted(models_), "cs": sorted(codes)})).mappings().all()}
    for x in per_order:
        x["engine_top_mirror_level"] = level_by_part.get((x["model"], x["engine_qty_top"]))

    eng_hist: Dict[int, int] = {}
    for x in per_order:
        lvl = x["engine_top_mirror_level"]
        if lvl is not None:
            eng_hist[lvl] = eng_hist.get(lvl, 0) + 1
    led_hist = {}
    if per_order:
        led_hist = {int(r["level"] or 0): int(r["n"]) for r in (await db.execute(text("""
            SELECT w.level, COUNT(*) AS n
            FROM work_order_materials w
            JOIN work_orders o ON o.id = w.work_order_id
            WHERE o.factory_id = :fid AND w.item_type = 'buy'
              AND COALESCE(w.shortage_qty, 0) > 0
              AND w.work_order_id = ANY(CAST(:ids AS text[]))
            GROUP BY 1
        """), {"fid": factory_id,
                "ids": [x["work_order_id"] for x in per_order]})).mappings().all()}

    shared = [x for x in per_order if x["shared_universe"]]
    m = len(shared)

    def _rate_on(rows_, flag):
        c = sum(1 for x in rows_ if x.get(flag))
        return {"agree": c, "of": len(rows_), "rate": round(c / len(rows_), 3) if rows_ else None}

    u_top = _rate_on(per_order, "ledger_top_in_engine_bom")
    e_top = _rate_on(per_order, "engine_top_in_ledger_lines")
    qty_rate = (round(same_gen["qty_top_agrees"] / same_gen["orders"], 3)
                if same_gen["orders"] else None)
    lead_rate = (round(same_gen["lead_top_agrees"] / same_gen["orders"], 3)
                 if same_gen["orders"] else None)
    # 这三句解释必须跟着本轮实测走。上一版把"台账 497 行与引擎展开 100% 重合"
    # "高于台账 0 行"写死在文案里；下一轮实测 engine_higher_than_ledger 变成 2,292 行时，
    # 那句"系统性偏差不是噪声"就成了报告里的假话 —— 结论只能由当轮数据拼出来。
    one_sided = requirement_basis["engine_higher_than_ledger"] == 0
    basis_wording = ("单边低 = 需求算法差（毛需求 vs 低层码净额），不是噪声"
                     if one_sided else
                     "高低两边都有 = 毛净之差之外还有别的来源（层级/登记世代/在途口径），别只归一条")

    univ_note = (
        f"三条候选解释各给一个当轮读数：① 料号宇宙 —— 台账点的第一件有 "
        f"{u_top['agree']}/{u_top['of']}（{u_top['rate']}）也在引擎本轮展开里；"
        f"② 快照过期 —— 台账行不动、缺口按今天的库存重算，第一名一致率 "
        f"{qty_rate}（数量口径）/ {lead_rate}（提前期口径）；"
        f"③ 需求算法 —— {requirement_basis['engine_lower_than_ledger']}/"
        f"{requirement_basis['rows_paired']} 行引擎更低（其中 "
        f"{requirement_basis['engine_says_zero_ledger_asks_positive']} 行引擎判 0 = 父层够用就不往下炸），"
        f"更高的 {requirement_basis['engine_higher_than_ledger']} 行：{basis_wording}。"
        "所以这一格读的是『两种需求算法点的第一名是否相同』，不是引擎准不准；"
        "要判准不准，得先把齐套行按同一算法刷一遍")

    return {
        "orders_compared": n,
        "bom_universe": {
            "note": univ_note,
            "ledger_top_in_engine_bom": u_top,
            "engine_top_in_ledger_lines": e_top,
            "shared_universe_orders": m,
            "off_universe_orders": n - m,
            "ledger_row_depth": row_depth,
            "engine_top_mirror_level_histogram": {str(k): v for k, v in sorted(eng_hist.items())},
            "ledger_short_row_level_histogram": {str(k): v for k, v in sorted(led_hist.items())},
            "lead_based_on_shared_universe": _rate_on(shared, "lead_agrees"),
            "qty_based_on_shared_universe": _rate_on(shared, "qty_agrees"),
            "same_generation": {
                "orders_recomputed": same_gen["orders"],
                "orders_with_no_shortage_today": same_gen["no_short_now"],
                "qty_top_agree": same_gen["qty_top_agrees"],
                "lead_top_agree": same_gen["lead_top_agrees"],
                "qty_top_rate": qty_rate,
                "lead_top_rate": lead_rate,
                "definition": ("台账登记的行不动，缺口按今天的库存重算（净缺 = 需求量 − 现存量），"
                               "再与引擎当轮点名的瓶颈件比第一名"),
                "requirement_basis": requirement_basis,
            },
        },
        "lead_based": {**_rate("lead_agrees"),
                       "definition": "外购缺料里提前期最长的那件（决定到货日的那件）"},
        "quantity_based": {**_rate("qty_agrees"),
                           "definition": "外购缺料里净缺口最大的那件"},
        "top5_overlap_rate": round(sum(overlaps) / max(1, len(overlaps)), 3) if overlaps else None,
        "ledger_first_found_in_engine_top5": _rate("ledger_first_in_engine_top5"),
        "engine_first_found_in_ledger_top5": _rate("engine_first_in_ledger_top5"),
        "engine_reciprocal_rank_on_ledger": _mrr("ledger_first_engine_rank"),
        "models_compared": len(models), "model_list": models,
        "per_model": _by_model("lead_agrees"),
        "per_model_by_quantity": _by_model("qty_agrees"),
        "median_shortage_parts": (sorted(x["engine_shortage_parts"] for x in per_order)[n // 2]
                                 if n else None),
        "median_ledger_parts": (sorted(x["ledger_shortage_parts"] for x in per_order)[n // 2]
                                if n else None),
        "bom_sources": sorted({str(x["bom_source"]) for x in per_order}),
        "disagreements": [x for x in per_order if not x["qty_agrees"]][:8],
        "meaning": ("第一名一致率之外再看 top-5 重叠与倒数排名：前者说明两边是不是在盯同一批料，"
                    "后者说明差多远。库存取今天而非当时快照，所以对老单名次漂移是预期内的。"),
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

    # BOM 取数源画像。600a7772 之前这里是"两套源"（仿真读本地 bom_items、台账读 engflow 镜像），
    # 现在仿真也走 bom_source 这一个入口，所以画像要回答的是另一个问题：
    # **同一个入口在这个机种上会落到哪一头**，落下去还剩几行、几层、level-1 件有没有提前期。
    # 画像是按行数预测落点的，所以再拿入口自己的返回值对撞一遍 —— 两者说得不一样就是画像过期了。
    from api.services import bom_source as bs

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
            "sim_resolves": bs.label("engflow_mirror" if int(r["mirror_lines"] or 0) > 0
                                     else "mes_bom_items"),
        })
    by_model = {b["model"]: b for b in bom_sources}
    switchable = [b for b in bom_sources if b["switchable"]]
    comparable = sorted(m for m, v in per_model.items() if v["comparable_for_bottleneck"])

    # 探针只挑判据真用得上的那几台：可比机种 + 真源有行的 + 缺口行最多的，上限 12 台
    probe_models = sorted(set(
        comparable[:5]
        + [b["model"] for b in bom_sources if b["switchable"]][:3]
        + [v["model"] for v in sorted(per_model.values(),
                                      key=lambda v: -int(v["shortage_lines"]))[:5]]))[:12]
    resolved: Dict[str, int] = {}
    mismatch: List[Dict[str, Any]] = []
    for model in probe_models:
        _, source = await bs.latest_bom_lines(db, factory_id, model)
        resolved[source] = resolved.get(source, 0) + 1
        row = by_model.get(model)
        predicted = ("engflow_mirror" if row and row["real_source_lines"] > 0 else
                     "mes_bom_items" if row and row["sim_source_lines"] > 0 else "none")
        if row is not None:
            row["probe_source"] = source
        if predicted != source:
            mismatch.append({"model": model, "entry_returns": bs.label(source),
                             "profile_predicts": bs.label(predicted)})

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
            "sim_reads": ("api/services/bom_source.latest_bom_lines() —— 镜像 level-1 优先，"
                         "没有才回落本地 bom_items（仿真、台账、领料现在同一个入口）"),
            "ledger_reads": "同一个入口 + materials 提前期",
            "sim_reads_probe": {
                "models_probed": len(probe_models),
                "model_list": probe_models,
                "resolved": {bs.label(k): v for k, v in resolved.items()},
                "mismatch_with_profile": mismatch,
                "note": ("画像是拿行数预测入口会落到哪一头，探针是直接问入口它取到了哪一头；"
                         "对不上就说明画像过期，得改画像而不是改说法"),
            },
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
