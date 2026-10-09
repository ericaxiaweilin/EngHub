"""安全库存这句话到底是谁说的：两处声明、四条尺，先验依据再报缺口。

实测（FAC_MECH_001，2026-10-09）不是"算不出告警"，是**算得出四个互相矛盾的告警数**：

* `inventory.safety_stock` 有 47 个取值、众数 **2**（10,624/11,228 = 94.6%）；
* `materials.safety_stock` 有 7 个取值、众数 **100**（18,998/31,672 = 60%），且没有一条是 0 或空；
* 两条声明在 11,184 个共有料号上**每一条都不一致**（最狠的一批 SAP 料号是 2 vs 500，差 250 倍）；
* 于是同一句"低于安全库存"按不同出处给出 476（补货触发线）/ 645（inventory 侧）/
  4,666（materials 侧）三个数，而 `safety_stock_config` 那张专门的配置表是 **0 行**。

这个模块做的不是"挑一条算"，而是把每条尺的口径、依据等级、以及"引擎不能替厂里选哪张表"
这件事一起报出去。判模板值的那把尺与 `lead_time_days`（31,452 行只有 10 个取值）用的是同一条：
**取值个数少 + 众数占比高 = 模板铺的默认值，不是逐料号的决定。**
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 判"模板值"的线：绝大多数料号共用同一个数，就是模板铺的，不是逐料号决定的。
# 众数占比单独成立（inventory 侧 47 个取值但 95.7% 都是 2 —— 取值个数并不少，可它就是模板）；
# 取值极多是次级信号（materials 侧那种 7~10 个值），两条任一成立即判 template/coarse。
TEMPLATE_MIN_MODE_SHARE = 0.30
TEMPLATE_MAX_DISTINCT = 20

INV_CENSUS_SQL = """
    SELECT count(*) AS rows_total,
           count(DISTINCT safety_stock) AS distinct_values,
           mode() WITHIN GROUP (ORDER BY safety_stock) AS mode_value,
           count(*) FILTER (WHERE safety_stock IS NULL)::int AS nulls,
           count(*) FILTER (WHERE safety_stock = 0)::int AS zeros
    FROM inventory WHERE factory_id = :fid
"""

MAT_CENSUS_SQL = """
    SELECT count(*) AS rows_total,
           count(DISTINCT safety_stock) AS distinct_values,
           mode() WITHIN GROUP (ORDER BY safety_stock::numeric) AS mode_value,
           count(*) FILTER (WHERE safety_stock IS NULL)::int AS nulls,
           count(*) FILTER (WHERE safety_stock::numeric = 0)::int AS zeros
    FROM materials WHERE factory_id = :fid
"""

MODE_SHARE_SQL = """
    SELECT safety_stock::numeric AS value, count(*) AS n
    FROM {table}
    WHERE factory_id = :fid AND safety_stock IS NOT NULL
    GROUP BY 1 ORDER BY 2 DESC LIMIT 5
"""

DISAGREE_SQL = """
WITH inv AS (
    SELECT material_code, min(safety_stock) AS inv_ss, sum(available_qty) AS available
    FROM inventory WHERE factory_id = :fid
    GROUP BY material_code),
mat AS (
    SELECT material_code, safety_stock::numeric AS mat_ss
    FROM materials WHERE factory_id = :fid AND safety_stock IS NOT NULL)
SELECT count(*) AS joined_materials,
       count(*) FILTER (WHERE inv.inv_ss <> mat.mat_ss) AS disagree,
       count(*) FILTER (WHERE inv.material_code IS NULL) AS only_in_materials,
       count(*) FILTER (WHERE mat.material_code IS NULL) AS only_in_inventory,
       count(*) FILTER (WHERE inv.material_code IS NOT NULL
                              AND mat.material_code IS NOT NULL) AS in_both,
       count(*) FILTER (WHERE inv.available < inv.inv_ss) AS below_by_inventory,
       count(*) FILTER (WHERE inv.available < mat.mat_ss) AS below_by_materials,
       round(sum(GREATEST(mat.mat_ss - inv.available, 0)) FILTER (WHERE inv.available < mat.mat_ss), 1)
           AS shortfall_by_materials,
       round(sum(GREATEST(inv.inv_ss - inv.available, 0)) FILTER (WHERE inv.available < inv.inv_ss), 1)
           AS shortfall_by_inventory
FROM inv FULL JOIN mat ON mat.material_code = inv.material_code
"""

# 触发线那一把尺：与 warehouse_agent_service.on_stock_below_safety 用的是同一个条件，
# 这里只复算它的口径，不改它、也不替它兜底
TRIGGER_SQL = """
    SELECT count(*) AS below_trigger_line,
           count(*) FILTER (WHERE reorder_qty IS NULL OR reorder_qty = 0) AS no_reorder_qty,
           count(*) FILTER (WHERE reorder_point IS NULL) AS no_reorder_point,
           count(*) FILTER (WHERE safety_stock IS NULL) AS no_inventory_safety
    FROM inventory
    WHERE factory_id = :fid AND available_qty >= 0
      AND available_qty <= COALESCE(reorder_point, safety_stock, 10)
"""

CONFIG_TABLE_SQL = "SELECT count(*) AS n FROM safety_stock_config WHERE factory_id = :fid"

TOP_GAP_SQL = """
WITH inv AS (SELECT material_code, min(safety_stock) AS inv_ss, sum(available_qty) AS available
             FROM inventory WHERE factory_id = :fid GROUP BY 1),
mat AS (SELECT material_code, safety_stock::numeric AS mat_ss
        FROM materials WHERE factory_id = :fid AND safety_stock IS NOT NULL)
SELECT inv.material_code, inv.inv_ss AS by_inventory, mat.mat_ss AS by_materials,
       round(inv.available, 1) AS available, abs(inv.inv_ss - mat.mat_ss) AS gap
FROM inv JOIN mat ON mat.material_code = inv.material_code
WHERE inv.inv_ss <> mat.mat_ss
ORDER BY abs(inv.inv_ss - mat.mat_ss) DESC, inv.material_code LIMIT :limit
"""


def classify_source(name: str, row: Dict[str, Any], mode_share: float) -> Dict[str, Any]:
    """一处声明一个判定：取值少 + 众数扎堆 = 模板铺的，不是逐料号决定的。"""
    distinct = int(row.get("distinct_values") or 0)
    rows_total = int(row.get("rows_total") or 0)
    template = mode_share >= TEMPLATE_MIN_MODE_SHARE
    coarse = (not template) and 0 < distinct <= TEMPLATE_MAX_DISTINCT
    return {
        "source": name,
        "rows": rows_total,
        "distinct_values": distinct,
        "mode_value": (float(row["mode_value"]) if row.get("mode_value") is not None else None),
        "mode_share": round(mode_share, 3),
        "nulls": int(row.get("nulls") or 0),
        "zeros": int(row.get("zeros") or 0),
        "verdict": ("template_default" if template else
                    ("coarse_default" if coarse else "declared_per_item")),
        "why": (f"{rows_total} 行、{distinct} 个取值、众数 {row.get('mode_value')} 占 {mode_share:.1%} —— "
                + ("绝大多数料号共用同一个数，这是模板铺的默认值，不是逐料号决定的安全库存；"
                   "拿它报警就是把模板当事实" if template else
                   ("取值只有几个，等于按档铺的粗默认值，同样不能逐料号使用" if coarse else
                    "分布不支持『模板铺的』这个判断，可按声明使用"))),
    }


async def _mode_share(db: AsyncSession, table: str, fid: str) -> float:
    """众数占比：只在白名单表名里拼字符串，别把外部输入接到 SQL 上。"""
    if table not in ("inventory", "materials"):
        raise ValueError(f"unknown safety-stock source table: {table}")
    rows = (await db.execute(text(MODE_SHARE_SQL.format(table=table)),
                             {"fid": fid})).mappings().all()
    if not rows:
        return 0.0
    total = sum(int(r["n"]) for r in rows)
    top = sum(int(r["n"]) for r in rows[:1])
    return (top / total) if total else 0.0


async def safety_stock_authority(db: Optional[AsyncSession], factory_id: str, *,
                                 examples: int = 5) -> Dict[str, Any]:
    """两处声明 + 四条尺的实测对照，结论是"该拍哪条"，不是一个假告警数。"""
    if db is None:
        return {"status": "no_session",
                "reading": ["没有数据库会话：两处声明谁作准、各把尺报多少都算不出"]}

    inv = dict((await db.execute(text(INV_CENSUS_SQL), {"fid": factory_id})).mappings().first() or {})
    mat = dict((await db.execute(text(MAT_CENSUS_SQL), {"fid": factory_id})).mappings().first() or {})
    sources = [
        classify_source("inventory.safety_stock", inv, await _mode_share(db, "inventory", factory_id)),
        classify_source("materials.safety_stock", mat, await _mode_share(db, "materials", factory_id)),
    ]

    joined = dict((await db.execute(text(DISAGREE_SQL), {"fid": factory_id})).mappings().first() or {})
    trigger = dict((await db.execute(text(TRIGGER_SQL), {"fid": factory_id})).mappings().first() or {})
    config_rows = int((await db.execute(text(CONFIG_TABLE_SQL), {"fid": factory_id})).scalar() or 0)
    # 每一格都转成 float：SQL 回来的 Decimal 进不了 chat_messages 的 jsonb，
    # 一落库就 500 —— 答复文案已经生成好也白搭（实测过一次）
    samples = [{"material_code": str(r["material_code"]),
                "by_inventory": float(r["by_inventory"] or 0),
                "by_materials": float(r["by_materials"] or 0),
                "available": float(r["available"] or 0),
                "gap": float(r["gap"] or 0)}
               for r in (await db.execute(text(TOP_GAP_SQL), {"fid": factory_id, "limit": max(1, examples)}))
               .mappings().all()]

    rulers = [
        {"ruler": "补货触发线（warehouse_agent 用的那条）", "grain": "行级（一个仓一行）",
         "condition": "available_qty <= COALESCE(reorder_point, safety_stock, 10)",
         "alerts": int(trigger.get("below_trigger_line") or 0),
         "basis": "inventory.reorder_point（缺时退 inventory.safety_stock，再缺退硬编码 10 —— "
                  "本厂两类空值各有几条见 trigger_fallbacks）"},
        {"ruler": "按 inventory.safety_stock 比（料号级）", "grain": "料号级",
         "condition": "sum(available_qty) < min(inventory.safety_stock) 跨该料号的各仓",
         "alerts": int(joined.get("below_by_inventory") or 0),
         "basis": f"inventory.safety_stock（众数 {sources[0]['mode_value']:g}，"
                  f"判定 {sources[0]['verdict']}）"},
        {"ruler": "按 materials.safety_stock 比（料号级）", "grain": "料号级",
         "condition": "sum(available_qty) < materials.safety_stock",
         "alerts": int(joined.get("below_by_materials") or 0),
         "basis": f"materials.safety_stock（众数 {sources[1]['mode_value']:g}，"
                  f"判定 {sources[1]['verdict']}）"},
        {"ruler": "safety_stock_config 那张专用配置表", "grain": "配置表",
         "condition": "safety_stock_config（stock_alert_service 读它）",
         "alerts": 0,
         "basis": f"本厂 {config_rows} 行 —— 空表不等于『没有要补的料』，"
                  "而是这条链根本没接上主数据"},
    ]

    disagree = int(joined.get("disagree") or 0)
    both = int(joined.get("in_both") or 0)
    counts = [r["alerts"] for r in rulers[:3]]
    spread = (round(max(counts) / min([c for c in counts if c > 0]), 2)
              if any(c > 0 for c in counts) else None)

    out = {
        "status": "ok", "factory_id": factory_id, "sources": sources, "rulers": rulers,
        "disagreement": {"materials_in_both": both,
                         "only_in_inventory": int(joined.get("only_in_inventory") or 0),
                         "only_in_materials": int(joined.get("only_in_materials") or 0),
                         "disagree": disagree,
                         "disagree_share": round(disagree / both, 4) if both else None,
                         "widest_examples": samples},
        "config_table_rows": config_rows,
        "trigger_fallbacks": {
            "no_reorder_point": int(trigger.get("no_reorder_point") or 0),
            "no_inventory_safety": int(trigger.get("no_inventory_safety") or 0),
            "no_reorder_qty": int(trigger.get("no_reorder_qty") or 0)},
        "shortfall_units": {"by_inventory": (float(joined.get("shortfall_by_inventory") or 0)),
                            "by_materials": (float(joined.get("shortfall_by_materials") or 0))},
        "ruler_spread_x": spread,
        "reading": [], "claim_guard": "",
    }

    out["reading"] = [
        f"同一句『低于安全库存』按不同出处给出 {rulers[0]['alerts']} / {rulers[1]['alerts']} / "
        f"{rulers[2]['alerts']} 条（配置表那条：safety_stock_config 本厂 {config_rows} 行，报 0 条不是"
        "『都健康』，是这张表根本没被填）"
        + (f"；最大最小差 {spread:g} 倍" if spread else ""),
        "两处声明的模板判定：" + "；".join(
            f"{s['source']} 有 {s['rows']} 行 / {s['distinct_values']} 个取值、众数 "
            f"{s['mode_value']:g} 占 {s['mode_share']:.1%} → {s['verdict']}" for s in sources),
        (f"两表都有的 {both} 个料号里 {disagree} 个声明不一致"
         f"（{out['disagreement']['disagree_share']:.1%}）—— 最宽的几例：" + "、".join(
             f"{s['material_code']} inventory {s['by_inventory']:g} vs materials {s['by_materials']:g}"
             f"（当前可用 {s['available']:g}）" for s in samples[:3])
         if both else "没有两表都覆盖到的料号可比"),
        ("引擎不替厂里选哪张表作准：选 inventory 还是 materials 会让告警数从 "
         f"{min(counts) if counts else 0} 跳到 {max(counts) if counts else 0}，"
         "这不是精度问题而是口径问题。已挂成 /pmc/open-rule-questions 的 "
         "safety_stock_authority 待回答；要落成 stock_alerts 的动作也等这个口径拍定。"),
    ]
    if all(str(s["verdict"]) == "template_default" for s in sources):
        out["reading"].append(
            "两边都是模板值时，任何一边的告警清单都不能当补货依据 —— "
            "先让厂里对最紧的那批料号逐料号写一个数，比调阈值有用")
    out["claim_guard"] = ("缺口件数按各自的声明算，不合并成一个『总缺口』；"
                          "模板值不冒充逐料号决定；空配置表不冒充『库存正常』")
    return out


async def safety_stock_question(db: AsyncSession, factory_id: str) -> Optional[Dict[str, Any]]:
    """把"哪张表作准"挂成待回答的问题；已经拍定（declared）就不再问。"""
    from core.mes.factory_rules import binding_rules

    auth = await safety_stock_authority(db, factory_id)
    if auth.get("status") != "ok":
        return None
    declared = (await binding_rules(db, factory_id)).get("safety_stock_authority")
    if declared:
        return {"declared": {"verdict": declared.get("verdict"), "status": declared.get("status"),
                             "statement": declared.get("statement")}}
    disagree = auth["disagreement"]
    rulers = auth["rulers"]
    return {
        "question": {
            "topic": "safety_stock_authority",
            "question": (f"『安全库存』这两处声明哪个作准 —— inventory.safety_stock"
                         f"（众数 {auth['sources'][0]['mode_value']:g}）还是 materials.safety_stock"
                         f"（众数 {auth['sources'][1]['mode_value']:g}）？"
                         f"两表都有的 {disagree['materials_in_both']} 个料号里 "
                         f"{disagree['disagree']} 个不一致。"),
            "what_records_say": [
                {"ruler": r["ruler"], "alerts": r["alerts"], "condition": r["condition"],
                 "basis": r["basis"]} for r in rulers],
            "widest_examples": disagree["widest_examples"],
            "why_it_matters": (f"同一句『低于安全库存』现在按出处给出 "
                               f"{rulers[0]['alerts']}/{rulers[1]['alerts']}/{rulers[2]['alerts']} 条，"
                               "差到十几倍；自动补货那条链（warehouse_agent）用的是 inventory 侧与 "
                               "reorder_point，而物料主数据那句在 materials 侧 —— 两边的数已经在互相"
                               "否证。`safety_stock_config` 那张本该作准的配置表是 0 行。"),
            "expected_answer": ("① 以 inventory.safety_stock 作准（补货链现有实现就是读它），"
                                "并把 materials 侧的值改成同一条口径；② 以 materials.safety_stock 作准，"
                                "则补货触发线要改读它；③ 逐料号重写（先重写决定开工那一档的件）；"
                                "三条都要落到 line 之外的字段级决定，不是调阈值。"),
            "record_as": {"subject": "safety_stock_authority",
                          "verdict": "inventory|materials|per_item_rewritten",
                          "status": "declared", "source": "chat"},
        }
    }
