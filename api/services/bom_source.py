"""BOM 读数的唯一入口：先 engflow 上传的 BOM（本地镜像），再本地 MES `bom_items`。

为什么单独一个模块：领料、MRP 展开、齐套检查都要回答"这个产品用什么料、每件用多少"。
这三处以前各查各的表 —— MRP 端点只查 `bom_items`、领料只查 engflow 镜像、
还有一个 MRPService 类读的是代码里硬编码的 PRODUCT-A/B 演示字典 ——
同一个问题三个答案，而只有镜像那份是用户上传的真结构。

口径：
- 默认第一来源 `enghub_bom_items`（engflow `bom_intelligence.bom_items` 的镜像），
  `product_model` 就是 EngHub 的产品编码，`quantity` 是父层单耗；
- 镜像没有这个型号才回落本地 `bom_items`（该产品最新一版单层 BOM）；
- 显式指定 `version` 时只在本地 `bom_items` 里取该版本（镜像表不分版本）；
- 两处都没有就返回 ([], "none")：**由调用方决定拒绝还是如实说明，绝不按系数编需求量**。

只展开 `level=1` 的直接组件，**不是暂时没做多层展开，是这份数据做不了**：
engflow 481,557 行 BOM 里 `parent_sap`（直接父级）**全为空**，473 个型号一个都没有，
只有 `level` 与 `l2_parent_group` 这种粗分组 —— 没有父子链就没法把单耗沿层连乘，
硬要 roll-up 等于替用户编造产品结构。要支持真正的多层 MRP，得由 engflow 导入侧
把父级保留下来（源 Excel 的层级缩进解析成 parent_sap），不是在这里猜。

所以调用方必须把 `bom_expansion="level-1"` 与 `bom_rollup` 的原因说出去，
并且用 `subassembly_suspect` 标出那些"在一层出现、在同型号更深层也出现"的件 ——
它们很可能是装配件而不是原料，按一层净需求直接下采购单会买错东西。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import math
from typing import Tuple
from sqlalchemy import text

MIRROR_SQL = text("""
    SELECT part_number AS material_code, description AS material_name,
           quantity AS qty_per_unit, unit, vendor_code, vendor_name
    FROM enghub_bom_items
    WHERE factory_id = :fid AND product_model = :pid AND level = 1
      AND quantity IS NOT NULL
    ORDER BY part_number
""")

LOCAL_SQL = text("""
    SELECT material_code, material_name, qty_per_unit, unit, vendor_code, vendor_name
    FROM bom_items
    WHERE factory_id = :fid AND product_id = :pid AND level = 1
      AND bom_version = :version
    ORDER BY material_code
""")

LOCAL_LATEST_SQL = text("""
    SELECT material_code, material_name, qty_per_unit, unit, vendor_code, vendor_name
    FROM bom_items
    WHERE factory_id = :fid AND product_id = :pid AND level = 1
      AND bom_version = (
          SELECT bom_version FROM bom_items
          WHERE factory_id = :fid AND product_id = :pid AND level = 1
          GROUP BY bom_version
          ORDER BY max(created_at) DESC
          LIMIT 1
      )
    ORDER BY material_code
""")

SOURCE_LABELS = {
    "engflow_mirror": "engflow 上传的 BOM（镜像表 enghub_bom_items）",
    "mes_bom_items": "本地 MES bom_items",
    "none": "engflow 镜像和本地 bom_items 里都没有这个产品的物料清单",
}

EXPANSION_LABEL = "level-1"


def label(source: str) -> str:
    return SOURCE_LABELS.get(source, source or "未知来源")


async def rollup_status(db: Any, factory_id: str, product_code: str) -> Dict[str, Any]:
    """这个型号能不能做多层展开 —— 判据是"行序能否重建成一棵树"，不是有没有 parent_sap。

    我最初只看 parent_sap 全空就判成"做不了"，那是错的：层级 BOM 的结构本来就
    写在缩进顺序里，(source_file, original_row_number) 前序遍历就能还原父子。
    """
    levels = (await db.execute(text("""
        SELECT level, count(*) AS rows
        FROM enghub_bom_items
        WHERE factory_id = :fid AND product_model = :pid
        GROUP BY level ORDER BY level
    """), {"fid": factory_id, "pid": product_code})).mappings().all()
    summary = (await db.execute(text("""
        SELECT count(*) AS rows_total,
               count(*) FILTER (WHERE original_row_number IS NULL) AS rows_without_order,
               count(*) FILTER (WHERE quantity IS NULL) AS rows_without_qty,
               count(DISTINCT source_file) AS files
        FROM enghub_bom_items
        WHERE factory_id = :fid AND product_model = :pid
    """), {"fid": factory_id, "pid": product_code})).mappings().first() or {}
    rows_total = int(summary.get("rows_total") or 0)
    problems: List[str] = []
    if not rows_total:
        problems.append("镜像里没有这个型号的 BOM 行（本次用的是本地 bom_items，它只有一层）")
    if int(summary.get("rows_without_order") or 0):
        problems.append(f"{summary['rows_without_order']} 行没有行号，缩进顺序不可靠")
    if int(summary.get("rows_without_qty") or 0):
        problems.append(f"{summary['rows_without_qty']} 行没有单件用量，无法连乘")
    if int(summary.get("files") or 0) > 1:
        problems.append(f"该型号的 BOM 来自 {summary['files']} 个上传文件，顺序拼不成一棵树")

    return {
        "levels": {int(r["level"]): int(r["rows"]) for r in levels},
        "max_level": max([int(r["level"]) for r in levels], default=0),
        "rows_total": rows_total,
        "reconstructed_from": "前序行序 (source_file, original_row_number)，不依赖 parent_sap",
        "possible": bool(rows_total) and not problems,
        "reason": "; ".join(problems) or None,
    }


async def subassembly_suspects(
    db: Any, factory_id: str, product_code: str, material_codes: List[str]
) -> set:
    """一层出现、同型号更深层也出现的料号：像装配件，不像原料。"""
    codes = [c for c in material_codes if c]
    if not codes:
        return set()
    return set((await db.execute(text("""
        SELECT DISTINCT part_number FROM enghub_bom_items
        WHERE factory_id = :fid AND product_model = :pid AND level > 1
          AND part_number = ANY(:codes)
    """), {"fid": factory_id, "pid": product_code, "codes": codes})).scalars().all())


# ── 多层展开：父子链从行序重建 ────────────────────────────────────────
#
# engflow 不写 parent_sap，但层级 BOM 的结构本来就在缩进顺序里：
# 按 (source_file, original_row_number) 排好后，层深每次最多 +1，
# 于是"某行的直接父级 = 它前面最近的一条 level 恰好小 1 的行"。
# 这不是猜 —— 全局 481,557 行里破坏该性质的只有 62 行，A-50-04-F 的 861 行为 0。
# 破坏性质的行一律如实报出来，不静默补父级。

LEVEL_ROWS_SQL = text("""
    SELECT part_number AS material_code, description AS material_name,
           quantity AS qty_per_unit, unit, level, original_row_number,
           source_file, vendor_code, vendor_name
    FROM enghub_bom_items
    WHERE factory_id = :fid AND product_model = :pid
      AND original_row_number IS NOT NULL AND quantity IS NOT NULL
    ORDER BY source_file NULLS FIRST, original_row_number
""")


def build_tree(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """把前序行还原成带 parent/per_unit 的节点列表。

    返回 (节点, 问题清单)。问题非空时调用方应当退回单层口径，
    因为结构不完整时算出来的净需求比不算更容易误导采购。
    """
    nodes: List[Dict[str, Any]] = []
    problems: List[str] = []
    stack: List[Dict[str, Any]] = []  # stack[level-1] = 该层当前父节点

    for row in rows:
        try:
            level = int(row["level"])
        except (TypeError, ValueError):
            problems.append(f"行 {row.get('original_row_number')} 的 level 不是整数")
            continue
        if level < 1:
            problems.append(f"行 {row.get('original_row_number')} 的 level={level} 非法")
            continue

        parent = None
        if level > 1:
            parent = stack[level - 2] if len(stack) >= level - 1 else None
            if parent is None:
                problems.append(
                    f"行 {row.get('original_row_number')}（level={level}）找不到上一层父级，"
                    f"缩进顺序在这里断了"
                )
                continue

        per_unit = float(row["qty_per_unit"] or 0) * (
            float(parent["per_unit_qty"]) if parent else 1.0
        )
        node = {
            "_index": len(nodes),
            "_parent_index": parent["_index"] if parent else None,
            "material_code": str(row["material_code"] or ""),
            "material_name": row.get("material_name"),
            "unit": row.get("unit"),
            "level": level,
            "qty_per_parent": float(row["qty_per_unit"] or 0),
            "per_unit_qty": per_unit,
            "parent_code": parent["material_code"] if parent else None,
            "row_number": row.get("original_row_number"),
            "vendor_code": row.get("vendor_code"),
        }
        nodes.append(node)
        del stack[level:]
        if len(stack) < level:
            stack.extend([None] * (level - len(stack)))
        stack[level - 1] = node

    return nodes, problems


async def stock_and_supply(
    db: Any, factory_id: str, material_codes: List[str], target_date=None
) -> Dict[str, Dict[str, float]]:
    """一次查完在库可用与在途（口径与 MRP 端点一致：只算 confirmed/shipped 且交期不晚于目标日）。"""
    codes = [c for c in dict.fromkeys(material_codes) if c]
    if not codes:
        return {}
    out: Dict[str, Dict[str, float]] = {c: {"on_hand": 0.0, "on_order": 0.0} for c in codes}

    inv = (await db.execute(text("""
        SELECT material_code, COALESCE(SUM(available_qty), 0) AS avail
        FROM inventory
        WHERE factory_id = :fid AND material_code = ANY(:codes)
        GROUP BY material_code
    """), {"fid": factory_id, "codes": codes})).mappings().all()
    for r in inv:
        out.setdefault(str(r["material_code"]), {"on_hand": 0.0, "on_order": 0.0})["on_hand"] = float(r["avail"] or 0)

    po = (await db.execute(text("""
        SELECT material_code, COALESCE(SUM(qty), 0) AS on_order
        FROM purchase_orders
        WHERE factory_id = :fid
          AND material_code = ANY(:codes)
          AND status IN ('confirmed', 'shipped')
          AND expected_date IS NOT NULL
          AND expected_date <= COALESCE(:target_date, CURRENT_DATE)
        GROUP BY material_code
    """), {"fid": factory_id, "codes": codes, "target_date": target_date})).mappings().all()
    for r in po:
        out.setdefault(str(r["material_code"]), {"on_hand": 0.0, "on_order": 0.0})["on_order"] = float(r["on_order"] or 0)

    return out


async def explode_requirement(
    db: Any,
    factory_id: str,
    product_code: str,
    plan_quantity: float,
    target_date=None,
) -> Optional[Dict[str, Any]]:
    """按重建出来的父子链做逐层净需求（低层码：父层够用就不炸开子层）。

    返回 None 表示这个型号没有可用的层级镜像（调用方回落到单层口径并说明）。
    """
    rows = (await db.execute(
        LEVEL_ROWS_SQL, {"fid": factory_id, "pid": product_code}
    )).mappings().all()
    if not rows:
        return None

    # 行序只在同一个上传文件内连续；型号跨文件时把两份顺序拼一起会拼出假树
    files = {str(r["source_file"]) for r in rows if r.get("source_file")}
    if len(files) > 1:
        return {
            "lines": [], "nodes": 0, "parts": 0, "max_level": 0,
            "problems": [
                f"该型号的 BOM 来自 {len(files)} 个上传文件，行序不能拼成一棵树；"
                "需要按文件分别建模（或人工指定生效版本）后才做多级展开"
            ],
        }

    nodes, problems = build_tree([dict(r) for r in rows])
    if not nodes:
        return {"lines": [], "problems": problems or ["没有解析出任何 BOM 行"], "nodes": 0}

    supply = await stock_and_supply(db, factory_id, [n["material_code"] for n in nodes], target_date)
    # 供应只能花一次：同一料号在多处出现时，若每个节点都按全量在库去扣，
    # 净需求会被重复冲抵算少，采购就会漏单。所以按层浅->深处理，边处理边消耗。
    remaining: Dict[str, float] = {
        code: float(v["on_hand"]) + float(v["on_order"]) for code, v in supply.items()
    }
    on_hand_by_code: Dict[str, float] = {
        code: float(v["on_hand"]) for code, v in supply.items()
    }
    on_order_by_code: Dict[str, float] = {
        code: float(v["on_order"]) for code, v in supply.items()
    }

    net_by_row: Dict[int, float] = {}
    for node in sorted(nodes, key=lambda n: (n["level"], n["_index"])):
        parent_net = plan_quantity if node["_parent_index"] is None else net_by_row[node["_parent_index"]]
        gross = float(node["qty_per_parent"]) * float(parent_net)
        code = node["material_code"]
        usable = min(gross, remaining.get(code, 0.0))
        remaining[code] = remaining.get(code, 0.0) - usable
        node["gross_qty"] = gross
        node["allocated_qty"] = usable          # 真正冲抵掉的供应（不是全量库存）
        node["on_hand_qty"] = on_hand_by_code.get(code, 0.0)
        node["on_order_qty"] = on_order_by_code.get(code, 0.0)
        node["net_qty"] = gross - usable
        net_by_row[node["_index"]] = node["net_qty"]

    # 同一料号可能出现在多个位置：按料号汇总毛/净需求，保留最浅层级作为代表
    merged: Dict[str, Dict[str, Any]] = {}
    for node in nodes:
        key = node["material_code"]
        row = merged.get(key)
        if row is None:
            merged[key] = {
                "material_id": key,
                "material_code": key,
                "material_name": node.get("material_name") or key,
                "unit": node.get("unit") or "pcs",
                "qty_per_unit": node["qty_per_parent"],
                "level": node["level"],
                "parent_code": node["parent_code"],
                "required_qty": math.ceil(node["gross_qty"]),
                "on_hand_qty": int(node["on_hand_qty"]),
                "on_order_qty": int(node["on_order_qty"]),
                "allocated_qty": int(round(node["allocated_qty"])),
                "net_qty": int(math.ceil(node["net_qty"])),
                "supplier": node.get("vendor_code") or "",
            }
        else:
            # 同一料号的多个位置：毛需求与净需求分别累加，供应已按节点逐个冲抵，不会重算
            row["required_qty"] += math.ceil(node["gross_qty"])
            row["net_qty"] += int(math.ceil(node["net_qty"]))
            row["allocated_qty"] += int(round(node["allocated_qty"]))
            row["level"] = min(row["level"], node["level"])

    return {
        "lines": sorted(merged.values(), key=lambda r: (r["level"], r["material_code"])),
        "nodes": len(nodes),
        "parts": len(merged),
        "max_level": max(n["level"] for n in nodes),
        "problems": problems,
    }


async def latest_bom_lines(
    db: Any,
    factory_id: str,
    product_code: str,
    version: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """返回 (单层需求行, 来源)。需求行键固定为
    material_code / material_name / qty_per_unit / unit / vendor_code / vendor_name
    （vendor 两列只是"来源单子上写的供应商"，不是采购承诺）。"""
    params = {"fid": factory_id, "pid": product_code}

    # 点名要某个版本时只能查本地表：镜像按 engflow 的行原样存，没有版本概念
    if version:
        local = (await db.execute(
            LOCAL_SQL, {**params, "version": version}
        )).mappings().all()
        return [dict(r) for r in local], ("mes_bom_items" if local else "none")

    mirror = (await db.execute(MIRROR_SQL, params)).mappings().all()
    if mirror:
        return [dict(r) for r in mirror], "engflow_mirror"

    local = (await db.execute(LOCAL_LATEST_SQL, params)).mappings().all()
    return [dict(r) for r in local], ("mes_bom_items" if local else "none")
