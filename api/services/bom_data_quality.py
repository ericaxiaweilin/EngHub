"""BOM 数据质量自检：把"这版 BOM 哪里脏、该提哪条 ECR"变成系统自己能报的清单。

动机（用户 10-05）：BOM 命名不规范是常态，正常要经过 ECR 把命名改好；无人工厂必须
**自己把问题反馈出来**，而不是靠人肉查库或让系统悄悄"猜对"。

三条规矩：
1. 这里只读，不改任何 BOM 数据 —— 判据拿不准时我们标问题，不动原始行；
2. 每条都带 `affected_shortage_qty`：脏数据影响多少缺口，决定先改哪条（不按条数排优先级）；
3. 每条都给 `action`：工程/PMC 收到就能动手，不是一句"数据质量差"。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from sqlalchemy import text

from api.services.bom_attributes import clean_name, is_document
from api.services.bom_source import LEVEL_ROWS_SQL, build_tree

ROWS_SQL = text("""
    SELECT part_number AS material_code, description AS material_name, unit, level,
           quantity AS qty_per_unit, unit_price, component_type, material_family,
           source_file, original_row_number, vendor_name
    FROM enghub_bom_items
    WHERE factory_id = :fid AND product_model = :pid
    ORDER BY source_file NULLS FIRST, original_row_number
""")
SHORTAGE_SQL = text("""
    SELECT m.material_code, COALESCE(SUM(m.shortage_qty), 0) AS shortage
    FROM work_order_materials m JOIN work_orders w ON w.id = m.work_order_id
    WHERE w.wo_type = 'master' AND w.factory_id = :fid
      AND m.material_code = ANY(:codes)
    GROUP BY 1
""")

# 名称只有 1-2 个字时，人读不出这是什么件（实测 `管`、`板`、`鐵片` 这类）
GENERIC_NAME_MAX_LEN = 2


def _rows_by_code(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        out[str(row.get("material_code") or "")].append(row)
    return out


def _shortage_of(shortage: Dict[str, float], codes) -> float:
    return round(sum(shortage.get(str(code), 0.0) for code in set(codes)), 2)


def evaluate(rows: List[Dict[str, Any]], shortage: Dict[str, float]) -> List[Dict[str, Any]]:
    """按规则算一遍；返回按影响缺口排序的问题清单。"""
    by_code = _rows_by_code(rows)
    codes = set(by_code) - {""}
    findings: List[Dict[str, Any]] = []

    def add(rule: str, name: str, severity: str, why: str, action: str, hit_codes, samples=None):
        hit_codes = sorted(set(hit_codes))
        if not hit_codes:
            return
        findings.append({
            "rule": rule, "name": name, "severity": severity,
            "codes": len(hit_codes), "rows": sum(len(by_code[c]) for c in hit_codes),
            "affected_shortage_qty": _shortage_of(shortage, hit_codes),
            "sample_codes": (samples if samples is not None else hit_codes)[:5],
            "why": why, "action": action,
        })

    named_as_code, generic, no_unit, no_class, price_bad, drawings = [], [], [], [], [], []
    for code, group in by_code.items():
        names = [clean_name(g.get("material_name")) for g in group]
        if code and all(n == code or not n for n in names):
            named_as_code.append(code)
        elif any(0 < len(n or "") <= GENERIC_NAME_MAX_LEN for n in names):
            generic.append(code)
        # 判据收紧：整颗料号一处都没带才算问题。
        # 按"任一行缺"去报，会把 681 个料号全报成脏数据（实测就差点这么干），
        # 那样清单没有优先级，也没人会去看。
        if all(not str(g.get("unit") or "").strip() for g in group):
            no_unit.append(code)
        if all(str(g.get("component_type") or "").strip().lower() in ("", "unknown") for g in group):
            no_class.append(code)
        prices = {float(g["unit_price"]) for g in group if g.get("unit_price")}
        if len(prices) > 1:
            price_bad.append(code)
        if any(is_document(n) for n in names) and any(float(g.get("qty_per_unit") or 0) > 0 for g in group):
            drawings.append(code)

    add("name_equals_code", "名称就是料号", "high",
        "上传行只有料号没有品名，人和下游系统都无法判断这是什么件；自制/采购与工序佐证也因此失去文本依据。",
        "ECR：补品名与规格欄（廠內命名規範：名稱;位置;規格;材料;表面處理;尺寸;圖號）。", named_as_code)
    add("generic_name", "名称过于笼统", "medium",
        f"品名只有 {GENERIC_NAME_MAX_LEN} 个字以内（如「管」「板」），同厂多种料号共用一个词，追溯与替代料判断都会串号。",
        "ECR：在品名后补结构位置或规格（例：前腳管 Φ25xT1.5）。", generic)
    add("missing_classification", "缺物料分类", "high",
        "part_master 里没有该料号或 component_type=unknown，自制/采购只能靠结构与工序字样推导，政策无法用源声明校正。",
        "工程/PMC：在 part_master 补 component_type 与 material_family（分类源也要一并标 classification_source）。",
        no_class)
    add("missing_unit", "缺计量单位", "medium",
        "单位为空时领料与库存换算没有依据，齐套数量会按猜的单位算。",
        "ECR：补单位与单件净重/包装数量。", no_unit)
    add("price_shape_anomaly", "单价形状异常", "low",
        "同一料号在一份 BOM 里出现多个不同的非零单价，说明该列不是单价（或混进了金额/总价），任何成本口径都不能用它。",
        "确认该列含义并在导入映射里改名；成本分析要用带单位的价源。", price_bad)
    add("drawing_row_as_material", "图纸行当物料", "medium",
        "名称以「圖/图」结尾的行按物料带数量进入齐套，会被算成采购或自制需求（我们已排除其进主档与路线，但需求行仍在）。",
        "ECR：把图纸行从 BOM 物料段移出，或标记为文档类不计数。", drawings)

    nodes, problems = build_tree([dict(r) for r in rows])
    parents: Dict[str, set] = defaultdict(set)
    for node in nodes:
        if node.get("parent_code"):
            parents[str(node["material_code"])].add(str(node["parent_code"]))
    multi_parent = [c for c, ps in parents.items() if len(ps) > 1]
    add("multi_parent", "同料号挂在多个父级下", "info",
        "结构上合法（共用件），但齐套表按料号合并且只留一个 parent_code，子树证据与低层码冲抵都要小心处理。",
        "确认是否应拆号或在工程 BOM 里分列；系统侧已按每一处出现分别取证据。", multi_parent)

    files = {str(r.get("source_file")) for r in rows if r.get("source_file")}
    if len(files) > 1:
        findings.append({
            "rule": "multi_file_model", "name": "型号跨多个上传文件", "severity": "high",
            "codes": len(codes), "rows": len(rows),
            "affected_shortage_qty": _shortage_of(shortage, codes),
            "sample_codes": sorted(files)[:5],
            "why": "行序只在同一个文件内连续，跨文件拼不成一棵树，多层展开只能退回单层口径。",
            "action": "ECR/导入规范：一个型号一个文件，或给出文件间的装配层级关系。",
        })
    if problems:
        findings.append({
            "rule": "tree_break", "name": "层级缩进断链", "severity": "high",
            "codes": 0, "rows": len(problems),
            "affected_shortage_qty": 0.0, "sample_codes": problems[:5],
            "why": "这些行的层深一次跳了 ≥2 层，中间缺父级；系统不会猜父级，会退回单层并如实报出来。",
            "action": "ECR：补齐缺失的上级装配件行（或修正该行的 level）。",
        })
    return sorted(findings, key=lambda f: (-f["affected_shortage_qty"], f["severity"] != "high"))


async def scan(db: Any, factory_id: str, product_model: str) -> Dict[str, Any]:
    """扫一个机种的 BOM 质量。只读，不产生任何写库。"""
    rows = [dict(r) for r in (await db.execute(
        ROWS_SQL, {"fid": factory_id, "pid": product_model})).mappings().all()]
    if not rows:
        return {"product_model": product_model, "rows": 0, "findings": [],
                "note": "镜像里没有这个机种的 BOM 行，无质量数据可判。"}
    codes = sorted({str(r.get("material_code") or "") for r in rows} - {""})
    shortage = {str(r["material_code"]): float(r["shortage"] or 0)
                for r in (await db.execute(
                    SHORTAGE_SQL, {"fid": factory_id, "codes": codes})).mappings().all()}
    findings = evaluate(rows, shortage)
    return {
        "product_model": product_model, "factory_id": factory_id,
        "rows": len(rows), "codes": len(codes),
        "codes_with_shortage": len(shortage),
        "findings": findings,
        "rule_count": len(findings),
        "total_affected_shortage_qty": round(max(
            [f["affected_shortage_qty"] for f in findings] or [0]), 2),
        "note": "只读自检：不改 BOM 原始数据；每条问题都带影响缺口，按缺口从大到小排，先改最挡生产的。",
    }
