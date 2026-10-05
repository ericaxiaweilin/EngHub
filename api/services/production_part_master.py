"""BOM 自制件的物料主档登记（只补"有下级、没主档"的那一类）。

口径对齐行业惯例（SAP 的 FERT/HALB/ROH、Oracle 的 make-buy）：
- BOM 里**有下级**的料号 = 要自己装的半成品，必须能挂工单 → 需要产品主档 + 工艺路线；
- **没有下级**的料号 = 采购件，只要物料与采购记录，不需要工艺路线。

MRP 报"自制件缺 9,788"时，如果这些件没有主档，工单开不出来，数字就只是数字。
本服务把缺的那一半补上，**字段只用 BOM 自己写下来的值**：
料号、品名（源表 description）、单位（源表 unit）、层级。

不做的两件事，是有意为之：
- **工艺路线一律留空**：路线是工艺事实，不在 BOM 里，系统不能替工厂编一条出来；
  编出来的路线会让 APS 排出一个没人能执行的计划。
- **不给猜的单位/品名兜底**：源行没有单位就如实报 `missing_unit` 不建，
  宁可让主档缺着，也不要一条看起来完整、实际是假的物料记录。
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.bom_attributes import clean_name, is_document, is_electronic
from database.models import Product

# 半成品用单独的分类，不和"BOM 型号"（category=真实机种）混在一类里：
# 前者是整机种、后者是结构里的组件，采购/工程看的口径完全不同。
SEMIFINISHED_CATEGORY = "半成品-BOM自制件"
CREATED_BY = "bom-mirror"


async def repair_selfmade_master_names(db: AsyncSession) -> int:
    """修历史脏数据：早期版本把整串分号属性文本当品名写进了 product_name。

    幂等：只动 `created_by=bom-mirror` 且名字里还带分号的行，改完就再也匹配不上。
    """
    rows = (await db.execute(select(Product).where(
        Product.created_by == CREATED_BY,
        Product.product_name.like("%;%"),
    ))).scalars().all()
    fixed = 0
    for row in rows:
        cleaned = clean_name(row.product_name)
        if cleaned and cleaned != row.product_name:
            row.product_name = cleaned[:100]
            fixed += 1
    if fixed:
        await db.flush()
    return fixed


async def register_make_part_masters(
    db: AsyncSession,
    factory_id: str,
    product_model: str,
    items: List[Dict[str, Any]],
    *,
    apply: bool = True,
) -> Dict[str, Any]:
    """给展开结果里的自制件补产品主档；幂等，已存在的一律不动。

    `items` 是 MRP/齐套的需求行，需要 material_code / material_name / unit / level / item_type。
    返回一份可对账的凭据（建了几条、跳过几条、哪些建不了及原因），调用方要原样报出去。
    """
    make_items = [
        i for i in items
        if str(i.get("item_type") or "") == "make" and str(i.get("material_code") or "")
    ]
    codes = [str(i["material_code"]) for i in make_items]
    receipt: Dict[str, Any] = {
        "requested": len(codes),
        "created": 0,
        "existing": 0,
        "blocked": {},
        "created_codes": [],
        "product_model": product_model,
        "note": (
            "主档字段全部来自 engflow BOM 的上传行（料号/品名/单位）；"
            "工艺路线不建 —— 路线是工艺事实，BOM 里没有，系统不替工厂编。"
        ),
    }
    # 顺手把历史脏名字修回来（幂等：只有名字里还带分号的行会被改）
    receipt["repaired_names"] = await repair_selfmade_master_names(db)
    if not make_items:
        return receipt

    existing = (await db.execute(select(Product).where(
        Product.product_code.in_(codes)
    ))).scalars().all()
    by_code = {str(p.product_code): p for p in existing}

    for item in make_items:
        code = str(item["material_code"])
        if code in by_code:
            master = by_code[code]
            if str(master.factory_id) == str(factory_id):
                receipt["existing"] += 1
            else:
                # product_code 是全局唯一索引：主档在别的厂区就只能人工调拨，不能抢注
                receipt["blocked"].setdefault("master_other_factory", []).append(code)
            continue

        raw_name = str(item.get("material_name") or "")
        # 用户给的工厂口径：图纸行不是物料；PCB 上的电子元器件是外购（贴片在 PCB 厂做）。
        # 这两类都不登记半成品主档，否则下一步会给图纸开工艺路线。
        if is_document(raw_name):
            receipt["blocked"].setdefault("drawing_row", []).append(code)
            continue
        if is_electronic(raw_name):
            receipt["blocked"].setdefault("electronic_purchased", []).append(code)
            continue

        unit = str(item.get("unit") or "").strip()
        name = clean_name(raw_name)
        if not unit or not name:
            receipt["blocked"].setdefault("missing_source_fields", []).append(code)
            continue

        receipt["created"] += 1
        receipt["created_codes"].append(code)
        if apply:
            db.add(Product(
                factory_id=factory_id,
                product_code=code,
                product_name=name[:100],
                category=SEMIFINISHED_CATEGORY,
                unit=unit[:20],
                description=(
                    f"BOM 自制件登记：{product_model} 的 level {item.get('level')} 组件"
                    f"（结构里有下级）；源行属性原文：{raw_name[:300]}"
                )[:500],
                status="active",
                created_by=CREATED_BY,
            ))

    if apply and receipt["created"]:
        await db.flush()
    receipt["blocked_counts"] = {k: len(v) for k, v in receipt["blocked"].items()}
    receipt["blocked"] = {k: v[:20] for k, v in receipt["blocked"].items()}
    if not apply:
        receipt["dry_run"] = True
    return receipt
