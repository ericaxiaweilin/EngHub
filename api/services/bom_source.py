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

只展开 `level=1` 的直接组件。多层 rolled-up 展开还没做（镜像里 18 层数据已经齐了），
所以调用方必须把 `expansion="level-1"` 说出去，别让人把"一层件"读成"全部物料"。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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
