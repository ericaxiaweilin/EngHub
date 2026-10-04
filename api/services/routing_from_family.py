"""按产品族把厂区的标准工艺路线推给 BOM 型号 / 自制件。

背景：MRP 展开已经能算出"哪些件要自己做、做多少"，主档也能按 BOM 自动登记，
但 473 个 BOM 型号和 221 个自制件都**没有工艺路线**，APS 一条任务都排不出来
（`aps_service` 里 `routing_id IS NULL` 的工单直接进 unrouted 清单）。

厂区本身是清楚的：同一厂区已有跑步机标准路线（车架焊接→表面涂装→电控装配→总装→
成品检验→包装入库，每步都绑了真实工位）。所以这一步**不是凭空造路线**，
而是把"同族已有路线"套到结构上属于同族的型号上，并且要求型号自己的 BOM 文本
**认得出这些工序**才套：

- 佐证率 = 型号 BOM 文本能印证到的工序数 / 参考路线的工序数，低于 `MIN_COVERAGE` 就不套；
- 套用的工步、工位、顺序原样来自那条参考路线，不新增工序；
- 工时代码里不编：参考路线 `steps` JSON 本来就没写 `standard_time`（APS 读出来是 0、
  换线按默认 300 秒），推导出来的路线同样是"未确认工时"，这点写进 remark 和回执。

路线最终要 IE 确认才算生效基线；这里的产物是**可排程的草案 + 明确的出处**，
不是把估计数当成工艺事实。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Product, Routing

CREATED_BY = "bom-family-derived"
# 工序名 -> 该工序会在 BOM 文本里留下的关键字。BOM 用的是繁体/简体混排，
# 所以两边都列出来；这不是"猜工艺"，是拿厂区已声明的工序去核对上传文本。
STEP_KEYWORDS: Dict[str, tuple] = {
    "焊接": ("焊接", "車架", "车架", "熔接", "管材"),
    "涂装": ("烤漆", "噴漆", "喷漆", "涂装", "表面", "電鍍", "电镀"),
    "电控": ("電控", "电控", "馬達", "马达", "發電機", "发电机", "儀表", "仪表", "線材", "线材"),
    "总装": ("組立", "组立", "總裝", "总装", "装配", "組件", "总成", "總成"),
    "检验": ("檢驗", "检验", "品質", "品质", "測試", "测试"),
    "包装": ("包裝", "包装", "裝櫃", "装柜", "紙箱", "纸箱", "彩盒"),
    "机加": ("CNC", "切削", "研磨", "車削", "冲压", "沖壓"),
    "注塑": ("注塑", "成形", "成型", "塑料", "塑膠"),
}
# 至少要印证到一半工序才套用；低于这个数说明这个型号和这条路线不是一族
MIN_COVERAGE = 0.5


def _matches(operation_name: str, corpus: str) -> bool:
    for keywords in STEP_KEYWORDS.values():
        if any(k in operation_name for k in keywords):
            return any(k in corpus for k in keywords)
    return False


async def _model_corpus(db: AsyncSession, factory_id: str, product_model: str) -> str:
    """型号 BOM 行上的文本（品名 + L3 上下文），作为工序佐证的材料。

    和 `bom_source.latest_bom_lines` 同一份口径：engflow 镜像优先，镜像没有这个型号
    才用本地 `bom_items` —— 否则本地建过 BOM 的产品会被误判成"无法佐证"。
    """
    rows = (await db.execute(text("""
        SELECT description, l3_context
        FROM enghub_bom_items
        WHERE factory_id = :fid AND product_model = :pid
          AND (description IS NOT NULL OR l3_context IS NOT NULL)
        LIMIT 6000
    """), {"fid": factory_id, "pid": product_model})).mappings().all()
    corpus = " ".join(f"{r['description'] or ''} {r['l3_context'] or ''}" for r in rows)
    if corpus.strip():
        return corpus
    local = (await db.execute(text("""
        SELECT material_name
        FROM bom_items
        WHERE factory_id = :fid AND product_id = :pid AND material_name IS NOT NULL
        LIMIT 4000
    """), {"fid": factory_id, "pid": product_model})).scalars().all()
    return " ".join(str(name or "") for name in local)


async def _reference_routings(db: AsyncSession, factory_id: str) -> List[Routing]:
    # ORM 只声明了这些列：表里的 status/remark 没进模型，筛活路线用 is_active
    routings = (await db.execute(select(Routing).where(
        Routing.factory_id == factory_id,
        Routing.is_active.is_(True),
    ).order_by(Routing.created_at))).scalars().all()
    usable = []
    for route in routings:
        steps = route.steps if isinstance(route.steps, list) else []
        if len(steps) >= 3:
            usable.append(route)
    return usable


async def derive_routing_for_product(
    db: AsyncSession, factory_id: str, product_code: str
) -> Dict[str, Any]:
    """给一个型号/自制件套上同族标准路线。幂等：已有带工步的路线就不动。"""
    receipt: Dict[str, Any] = {"product_code": product_code, "status": "unknown"}
    product = (await db.execute(select(Product).where(
        Product.product_code == product_code
    ))).scalar_one_or_none()
    if product is None:
        receipt.update({"status": "no_master", "reason": "还没有产品主档，路线无处绑定"})
        return receipt
    if product.current_routing_id:
        existing = await db.get(Routing, str(product.current_routing_id))
        if existing is not None and isinstance(existing.steps, list) and existing.steps:
            receipt.update({
                "status": "existing",
                "routing_id": existing.id,
                "steps": len(existing.steps),
                "derived": str(existing.created_by or "") == CREATED_BY,
            })
            return receipt

    corpus = await _model_corpus(db, factory_id, product_code)
    if not corpus.strip():
        receipt.update({"status": "no_bom_text",
                        "reason": "镜像里没有这个型号的 BOM 行，无法佐证工序"})
        return receipt

    candidates = await _reference_routings(db, factory_id)
    if not candidates:
        receipt.update({"status": "no_reference_route",
                        "reason": "本厂区没有可参考的多工步标准路线"})
        return receipt

    best: Optional[Dict[str, Any]] = None
    for route in candidates:
        if str(route.product_id) == str(product_code):
            continue
        steps = route.steps or []
        matched = sum(1 for s in steps if _matches(str(
            (s or {}).get("name") or (s or {}).get("operation_name") or ""
        ), corpus))
        coverage = matched / len(steps)
        if best is None or coverage > best["coverage"]:
            best = {"route": route, "matched": matched, "coverage": coverage,
                    "steps": len(steps)}

    if best is None or best["coverage"] < MIN_COVERAGE:
        receipt.update({
            "status": "not_derived",
            "reason": (
                f"最相近的路线是 {best['route'].id if best else '无'}"
                f"（工序佐证 {best['matched'] if best else 0}/{best['steps'] if best else 0}"
                f"，覆盖率 {(best['coverage'] if best else 0):.0%} < {MIN_COVERAGE:.0%}）："
                "这个型号的 BOM 文本认不出那条路线的工序，硬套等于替工厂编工艺"
            ),
            "coverage": round(best["coverage"], 3) if best else 0.0,
        })
        return receipt

    ref = best["route"]
    normalized = []
    for idx, step in enumerate(ref.steps or []):
        step = step or {}
        normalized.append({
            "step_no": int(step.get("step_no") or step.get("seq") or (idx + 1) * 10),
            "name": str(step.get("name") or step.get("operation_name") or f"工序{idx + 1}"),
            "station": step.get("station") or step.get("work_center"),
            # 不写 standard_time：参考路线本来就没有确认工时，推导也不补一个数
        })
    routing_id = f"rt-bom-{product_code}"[:64]
    audit_note = (
        f"按产品族从 {ref.id}（{ref.product_id}）推导：工序与工位原样沿用同族标准路线；"
        f"型号 BOM 文本印证 {best['matched']}/{len(normalized)} 道工序"
        f"（{best['coverage']:.0%}）。标准工时未经 IE 确认，排程只能当草案。"
    )
    db.add(Routing(
        id=routing_id,
        factory_id=factory_id,
        product_id=product_code,
        routing_code=f"RT-BOM-{product_code}"[:50],
        version="CURRENT",
        status="active",
        is_active=True,
        steps=normalized,
        created_by=CREATED_BY,
        remark=audit_note,
    ))
    product.current_routing_id = routing_id
    await db.flush()
    receipt.update({
        "status": "derived",
        "routing_id": routing_id,
        "derived_from": ref.id,
        "coverage": round(best["coverage"], 3),
        "matched_steps": best["matched"],
        "steps": len(normalized),
        "note": "工时未经 IE 确认；要改成正式基线需工艺部复核 remark 里的出处",
    })
    return receipt
