"""数据流节点剖面：一座厂的推演到底流经多少节点，规模变大时要多到多少。

分三层数，全部实测，不写死：

* **台账层** —— 引擎能读到的行数/实体数（工单、用料行、BOM 镜像行、物料、库存、考勤、工位、线、排程）；
* **展开层** —— 一台机一次推演真展开多少 BOM 行、几层、多少道工序、几个工作中心；
* **推演层** —— 一次 `run_target` 经过的取数与事件节点（齐套行、缺口行、PO 行、按天动作、到货关键件）。

缩放那一格是**外推的"需要多少节点"**（按吞吐系数放大现有节点），它只回答"这座 5000 人的厂
要多少台账行才推得动"，绝不回填事实表 —— 数据流节点数不是厂里的事实，是我们的需求估算。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 每个节点的 scaling 归类：heads=随人头动；volume=随订单/产量体积动；fixed=与规模无关的结构
LEDGER_NODES: List[Dict[str, Any]] = [
    {"label": "工单", "scales": "volume",
     "sql": "SELECT count(*) FROM work_orders WHERE factory_id = :f"},
    {"label": "工单用料行", "scales": "volume",
     "sql": """SELECT count(*) FROM work_order_materials m JOIN work_orders w ON w.id = m.work_order_id
                WHERE w.factory_id = :f"""},
    {"label": "镜像多层 BOM 行", "scales": "volume",
     "sql": "SELECT count(*) FROM enghub_bom_items WHERE factory_id = :f"},
    {"label": "本地 BOM 行", "scales": "volume",
     "sql": "SELECT count(*) FROM bom_items WHERE factory_id = :f"},
    {"label": "物料主档", "scales": "fixed",
     "sql": "SELECT count(*) FROM materials WHERE factory_id = :f"},
    {"label": "库存行", "scales": "fixed",
     "sql": "SELECT count(*) FROM inventory WHERE factory_id = :f"},
    {"label": "库存流水", "scales": "volume",
     "sql": "SELECT count(*) FROM inventory_transactions WHERE factory_id = :f"},
    {"label": "考勤行", "scales": "heads",
     "sql": "SELECT count(*) FROM attendance WHERE factory_id = :f"},
    {"label": "考勤在册人头", "scales": "heads",
     "sql": "SELECT count(DISTINCT operator_id) FROM attendance WHERE factory_id = :f"},
    {"label": "考勤覆盖天数", "scales": "fixed",
     "sql": "SELECT count(DISTINCT date) FROM attendance WHERE factory_id = :f"},
    {"label": "工位档案", "scales": "fixed",
     "sql": "SELECT count(*) FROM stations WHERE factory_id = :f AND COALESCE(status,'active')='active'"},
    {"label": "工位产能行", "scales": "fixed",
     "sql": "SELECT count(*) FROM station_capacity WHERE factory_id = :f"},
    {"label": "在册产线", "scales": "fixed",
     "sql": "SELECT count(*) FROM line_profiles WHERE factory_id = :f AND is_active"},
    {"label": "排程任务行", "scales": "volume",
     "sql": """SELECT count(*) FROM aps_schedule_tasks t JOIN aps_schedules a ON a.id = t.schedule_id
                WHERE a.factory_id = :f"""},
    {"label": "采购单", "scales": "volume",
     "sql": "SELECT count(*) FROM purchase_orders WHERE factory_id = :f"},
    {"label": "请购单", "scales": "volume",
     "sql": "SELECT count(*) FROM purchase_requests WHERE factory_id = :f"},
    {"label": "报工记录", "scales": "volume",
     "sql": "SELECT count(*) FROM production_reports WHERE factory_id = :f"},
    {"label": "产品主档", "scales": "fixed",
     "sql": "SELECT count(*) FROM products WHERE factory_id = :f"},
]

# 图结构本身：表与外键边是全库口径，与厂区无关
GRAPH_SQL = {
    "public 表数": """SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname='public' AND c.relkind='r'""",
    "有数据的表": """SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                      WHERE n.nspname='public' AND c.relkind='r' AND c.reltuples > 0""",
    "外键边（表→表）": """SELECT count(*) FROM information_schema.table_constraints tc
                            JOIN information_schema.key_column_usage k ON k.constraint_name = tc.constraint_name
                            WHERE tc.constraint_schema='public' AND tc.constraint_type='FOREIGN KEY'""",
}

RUN_NODE_KEYS = {
    "bom_parts": "展开到的料号数", "kit_lines": "齐套检查行", "kit_shortage_lines": "缺口行",
    "po_lines": "需下采购行", "arrival_critical_parts": "关键到货件", "route_steps": "路线工序",
    "work_days": "推进的班次日", "materials_without_price": "无价料号",
}


async def ledger_nodes(db: AsyncSession, factory_id: str) -> List[Dict[str, Any]]:
    """台账层节点：逐个查，查不到就点名缺哪张表（不静默跳过）。"""
    rows: List[Dict[str, Any]] = []
    for node in LEDGER_NODES:
        try:
            value = (await db.execute(text(node["sql"]), {"f": factory_id})).scalar()
            rows.append({"node": node["label"], "rows": int(value or 0), "scales": node["scales"],
                         "status": "ok"})
        except Exception as exc:      # 表缺失/列改名都要看得见，不是"少一行"
            await db.rollback()
            rows.append({"node": node["label"], "rows": None, "scales": node["scales"],
                         "status": "unreadable", "why": f"{type(exc).__name__}: {str(exc)[:90]}"})
    return rows


async def graph_shape(db: AsyncSession) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for label, sql in GRAPH_SQL.items():
        out[label] = int((await db.execute(text(sql))).scalar() or 0)
    return out


async def expansion_nodes(db: AsyncSession, factory_id: str, model: str,
                          units: float = 1000.0) -> Dict[str, Any]:
    """展开层：一台机一次推演真展开多少 BOM 行 / 几层 / 几道工序 / 几个工作中心。"""
    from api.services import bom_source as bs
    from core.mes.route_resolution import route_ops_for_product

    exp = await bs.explode_requirement(db, factory_id, model, units)
    lines = [r for r in ((exp or {}).get("lines") or []) if r.get("material_code")]
    ops = await route_ops_for_product(db, factory_id, model)
    levels = sorted({int(r.get("level") or 0) for r in lines})
    return {
        "model_code": model, "bom_lines": len(lines),
        "distinct_parts": len({str(r.get("material_code")) for r in lines}),
        "levels": levels, "deepest_level": (levels[-1] if levels else None),
        # 镜像自己数的节点/料号/层数一并留下：两套数对不上时，看的是这条而不是我算的那条
        "mirror_nodes": (exp or {}).get("nodes"), "mirror_parts": (exp or {}).get("parts"),
        "mirror_max_level": (exp or {}).get("max_level"),
        "orphan_or_problem_lines": len((exp or {}).get("problems") or []),
        "mirror_returned": exp is not None,
        "route_operations": len(ops),
        "work_centers": len({str(o.get("work_center")) for o in ops if o.get("work_center")}),
    }


async def run_nodes(db: AsyncSession, factory_id: str, model: str, units: float,
                    due_in_days: int = 23) -> Dict[str, Any]:
    """推演层：真跑一次，数这次经过的取数与事件节点。"""
    from datetime import date, timedelta

    from api.services.virtual_run import (CALENDAR_SQL, LINES_SQL, equipment_rate,
                                          measured_attendance, run_target)

    lines = [dict(r) for r in (await db.execute(LINES_SQL, {"fid": factory_id})).mappings().all()]
    shift = {int(r["weekday"]) + 1 for r in
             (await db.execute(CALENDAR_SQL, {"fid": factory_id})).mappings().all()} or set(range(1, 7))
    att = await measured_attendance(db, factory_id)
    eq = await equipment_rate(db, factory_id)
    today = date.today()
    run = await run_target(db, factory_id, model, float(units),
                           today + timedelta(days=int(due_in_days)), today,
                           {d: float(att["present_ratio"]) for d in range(0, 400)},
                           lines, shift, line_busy_days=0.0,
                           equip_rate=float(eq.get("rate") or 1.0))
    actions = run.get("actions") or []
    counts = {key: run.get(key) for key in RUN_NODE_KEYS}
    return {
        "model_code": model, "units": float(units), "status": run.get("status"),
        "bom_source": run.get("bom_source"),
        "action_events": len(actions),
        "action_kinds": sorted({str(a.get("action")) for a in actions}),
        "day_steps": sum(1 for a in actions if a.get("day") is not None),
        "nodes": {k: v for k, v in counts.items() if v is not None},
        "node_meanings": RUN_NODE_KEYS,
    }


def scaled_node_need(profile_rows: List[Dict[str, Any]], *, factor: float) -> List[Dict[str, Any]]:
    """按吞吐系数外推"这座规模的厂要多少节点"，并标清哪一类根本不该等比。"""
    out: List[Dict[str, Any]] = []
    for row in profile_rows:
        if row.get("status") != "ok" or row.get("rows") is None:
            continue
        kind = str(row.get("scales"))
        cur = int(row["rows"])
        if kind == "volume":
            out.append({"node": row["node"], "now": cur, "needed_at_scale": int(round(cur * factor)),
                        "basis": "derived", "why": ("按吞吐等比外推的需求估算：这是『推得动这座厂需要多少行台账』"
                                                    "，不是厂里已有的事实，绝不回填事实表")})
        elif kind == "heads":
            out.append({"node": row["node"], "now": cur, "needed_at_scale": int(round(cur * factor)),
                        "basis": "heads", "why": "人头类：缩放模型唯一真的会变的量（考勤/在岗人日）"})
        else:
            out.append({"node": row["node"], "now": cur, "needed_at_scale": cur,
                        "basis": "fixed", "why": "与人数无关的结构（主档/线/工位/日历），等比放大它等于编数据"})
    return out


async def data_flow_profile(db: AsyncSession, factory_id: str, *, headcount: Optional[float] = None,
                             sample_models: int = 2, run_sample: bool = True) -> Dict[str, Any]:
    """这座厂的数据流节点剖面；给 headcount 时附"那个规模要多少节点"的外推。"""
    from core.mes.plant_architecture import plant_shape

    rows = await ledger_nodes(db, factory_id)
    graph = await graph_shape(db)
    shape = await plant_shape(db, factory_id)
    readable = [r for r in rows if r.get("status") == "ok"]
    unreadable = [r for r in rows if r.get("status") != "ok"]
    ledger_total = sum(int(r["rows"] or 0) for r in readable)

    from api.services.virtual_run import default_models

    models = await default_models(db, factory_id, n=max(1, min(4, int(sample_models))))
    expansions = [await expansion_nodes(db, factory_id, m) for m in models] if models else []
    runs = []
    if run_sample and models:
        runs = [await run_nodes(db, factory_id, m, 1800.0) for m in models[:1]]

    out: Dict[str, Any] = {
        "factory_id": factory_id, "graph": graph,
        "ledger": {"nodes": rows, "readable": len(readable), "unreadable": [r["node"] for r in unreadable],
                   "total_rows": ledger_total,
                   "biggest": sorted(readable, key=lambda r: -int(r["rows"] or 0))[:5]},
        "expansion": expansions, "run": (runs[0] if runs else None),
        "node_totals": {"ledger_rows": ledger_total, "expansion_models": len(expansions),
                        "run_action_events": (runs[0]["action_events"] if runs else 0)},
        "reading": [
            f"台账层：{len(readable)}/{len(rows)} 类节点读到数，合计 {ledger_total:,} 行；"
            f"最大的一块是 {sorted(readable, key=lambda r: -int(r['rows'] or 0))[0]['node'] if readable else '—'}"
            f"（{max((int(r['rows'] or 0) for r in readable), default=0):,} 行）",
            f"图结构：public 表 {graph.get('public 表数')} 张、有数据 {graph.get('有数据的表')} 张、"
            f"外键边 {graph.get('外键边（表→表）')} 条 —— 节点之间的边就是这个数",
        ],
    }
    if unreadable:
        out["reading"].append("读不到的节点：" + "、".join(unreadable) + "（不是没有，是这张库没这张表/列）")
    for e in expansions:
        out["reading"].append(
            f"展开层 {e['model_code']}：一次推演展开 {e['bom_lines']} 行 BOM、{e['distinct_parts']} 个料号"
            + (f"（镜像自报 {e['mirror_nodes']} 个节点、最深 {e['mirror_max_level']} 层）"
               if e.get("mirror_nodes") else "")
            + f" / {e['route_operations']} 道工序 / {e['work_centers']} 个工作中心"
            + (f" ｜ 这台机在镜像里没有多层结构 → 推演时回落到本地 bom_items"
               if not e["bom_lines"] else ""))
    if runs:
        r = runs[0]
        out["reading"].append(
            f"推演层 {r['model_code']}：这次经过 {r['nodes'].get('bom_parts', '—')} 个料号节点、"
            f"{r['nodes'].get('kit_lines', '—')} 行齐套、{r['nodes'].get('kit_shortage_lines', '—')} 行缺口、"
            f"{r['action_events']} 个按天动作事件、{r['nodes'].get('work_days', '—')} 个班次日推进"
            f"（BOM 取数 {r['bom_source']}）")
    if headcount:
        base_people = float(shape.get("people_per_day") or 0)
        if base_people > 0:
            factor = float(headcount) / base_people
            vol_now = sum(int(n["rows"] or 0) for n in rows
                          if n.get("status") == "ok" and n.get("scales") == "volume")
            vol_need = int(round(vol_now * factor))
            out["scale"] = {"headcount": int(headcount), "reference_people": base_people,
                            "factor": round(factor, 4),
                            "nodes_needed": scaled_node_need(rows, factor=factor),
                            "note": ("volume 类按吞吐等比外推＝『这座规模要多少台账行才推得动』的需求估算，"
                                     "不回填事实表；heads 类是真会变的；fixed 类等比放大就是编数据")}
            heads = next((n for n in out["scale"]["nodes_needed"] if n["node"] == "考勤在册人头"), None)
            need_vol = sum(n["needed_at_scale"] - n["now"] for n in out["scale"]["nodes_needed"]
                           if n["basis"] == "derived")
            if need_vol > 0:
                vol_note = f"volume 类节点要再多 {need_vol:,} 行才推得动（现在 {vol_now:,} 行 → 约 {vol_need:,} 行）"
            elif need_vol < 0:
                vol_note = (f"这座规模比参照厂小，等比会少 {-need_vol:,} 行 —— 是需求变小，"
                            f"不是要删谁的台账（现有 {vol_now:,} 行照用）")
            else:
                vol_note = "volume 类节点不用增减（规模与参照厂同级）"
            out["reading"].append(
                f"规模层：{int(headcount)} 人（等比 {factor:g}）—— "
                + (f"人头类节点 {heads['now']:,} → {heads['needed_at_scale']:,}；" if heads else "")
                + vol_note)
    return out
