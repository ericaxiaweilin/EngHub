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
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.bom_attributes import PROCESS_TOKENS, families_in
from database.models import Product, Routing

CREATED_BY = "bom-family-derived"
# 至少要印证到一半工序才套用；低于这个数说明这个型号和这条路线不是一族
MIN_COVERAGE = 0.5
# 半成品只取被它自己子树佐证的工序；少于 2 道就不算一条路线（一道工序的"路线"没意义）
MIN_COMPONENT_STEPS = 2


def _step_name(step: Any) -> str:
    step = step or {}
    return str(step.get("name") or step.get("operation_name") or "")


def _step_station(step: Any) -> str:
    step = step or {}
    return str(step.get("station") or step.get("work_center") or "")


def _matches(operation_name: str, corpus: str) -> bool:
    """这道工序算不算被 BOM 文本佐证：工序所属的族要在文本里出现。

    工序词表只在 `bom_attributes.PROCESS_TOKENS` 一份（原来这里另写了一份，
    同一个件在路线和缺口两条路上会被判成不同工艺）。10-05 起把"車架/管材"这类
    代用字也去掉了：**要 BOM 里真写了"焊接/烤漆/電鍍"才算佐证**，
    看到车架就推断要焊接，等于替工厂编工艺。
    """
    return bool(set(families_in(operation_name)) & set(families_in(corpus)))


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
        # 自己推出来的路线不能当参考：否则 A 半成品的草案会被套到 B 半成品上，
        # 一道工序的出处追到第三层，覆盖率还算得特别好看（4 步路线 2 命中=50%）。
        if str(route.created_by or "") == CREATED_BY:
            continue
        steps = route.steps if isinstance(route.steps, list) else []
        if len(steps) >= 3:
            usable.append(route)
    return usable


async def _factory_stations(db: AsyncSession, factory_id: str) -> List[Any]:
    """本厂登记的工位（含站名自己声明的产能单位）。"""
    return list((await db.execute(text("""
        SELECT station_code, station_name, capacity_unit
        FROM stations WHERE factory_id = :fid
        ORDER BY station_code
    """), {"fid": factory_id})).mappings().all())


async def _station_homes(
    db: AsyncSession, factory_id: str, references: List[Routing]
) -> Dict[str, Dict[str, Tuple[str, str]]]:
    """给每道工序找到本厂真正能干它的工位，并记下这个结论是从哪个事实来的。

    优先级（每一级都是厂区自己声明过的数据，不是我按工序名猜的）：
    1. 厂区已有路线把**这道同名工序**绑在哪个工位 —— 最强的事实，照抄；
    2. 站名自己声明了这个工序族（"注塑车间"就是注塑的家）；有人力配置的车间优先于
       单台设备，一台 1 套/天的试模机撑不住批量半成品；
    3. 没有站名认领的族，才退回"同族工序在哪儿干过"（出现最多的那个）。
       —— 顺序不能反：10-05 实测把"滚轮成型"的工位当成了整个注塑族的家，
          ABS 端蓋就被派去滚轮车间了。
    """
    stations = await _factory_stations(db, factory_id)
    known = {str(row["station_code"]): row for row in stations}

    by_operation: Dict[str, Tuple[str, str]] = {}
    paired: Dict[str, List[str]] = {}
    in_use: set = set()
    for route in references:
        for step in (route.steps or []):
            code = _step_station(step)
            name = _step_name(step)
            if not code or code not in known or not name:
                continue
            in_use.add(code)
            by_operation.setdefault(
                name, (code, f"厂区已有路线把工序「{name}」绑在 {code}"))
            for family in families_in(name):
                paired.setdefault(family, []).append(code)

    def named_home(family: str) -> Optional[Tuple[str, str]]:
        """站名声明了这一族工序的工位；厂区已经在用的、有人力配置的排前面。

        "哑铃组装线""滚轮车间"这种带着具体产品名的工位不配当一个工序族的家：
        10-05 实测就是它把整条装配工序派去了哑铃线。厂区路线真用过的工位先赢。
        """
        picked = [row for row in stations if family in families_in(str(row["station_name"] or ""))]
        if not picked:
            return None
        picked.sort(key=lambda row: (
            0 if str(row["station_code"]) in in_use else 1,
            0 if str(row["capacity_unit"] or "") == "人" else 1,
            str(row["station_code"]),
        ))
        return (
            str(picked[0]["station_code"]),
            f"工位「{picked[0]['station_name']}」按站名认领了「{family}」工序",
        )

    by_family: Dict[str, Tuple[str, str]] = {}
    for family in PROCESS_TOKENS:
        home = named_home(family)
        if home is None and paired.get(family):
            best = sorted(Counter(paired[family]).items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            home = (best, f"厂区已有路线把「{family}」这一族工序绑在 {best}")
        if home:
            by_family[family] = home
    return {"by_operation": by_operation, "by_family": by_family, "stations": known}

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
    result = await _derive_from_corpus(db, factory_id, product_code, corpus,
                                       source="整机型 BOM")
    if result.get("status") in ("derived", "existing") and product is not None:
        product.current_routing_id = result.get("routing_id") or product.current_routing_id
        await db.flush()
    return result


async def derive_routing_for_component(
    db: AsyncSession, factory_id: str, code: str, corpus: str, *, level: Optional[int] = None
) -> Dict[str, Any]:
    """给一个自制半成品推路线。

    用户 10-05 给的工厂口径：BOM 里 **L3 就是半成品**，而且半成品的下层就在同一个
    上传文件里 —— 所以子件不用另外传 BOM，拿它自己子树的属性文本就能佐证工序
    （車架組的子件写著"烤漆" → 表面涂装这道工序有出处；導桿写"鹽浴滲氮/45#" → 机加）。
    `corpus` 由调用方传入：`bom_source.subtree_evidence` 给的**镜像子树原文**
    （含材料/表面處理），齐套快照那份清洗过的品名只作兜底。门槛与型号级路径一样。
    """
    receipt: Dict[str, Any] = {"product_code": code, "status": "unknown"}
    product = (await db.execute(select(Product).where(
        Product.product_code == code
    ))).scalar_one_or_none()
    if product is None:
        receipt.update({"status": "no_master",
                        "reason": "半成品还没有主档，先按计划下达登记"})
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
    if not (corpus or "").strip():
        receipt.update({"status": "no_bom_text",
                        "reason": "这个半成品在 BOM 里没有下层行，拿不到佐证材料"})
        return receipt
    result = await _derive_from_corpus(
        db, factory_id, code, corpus,
        source=f"L{level} 半成品子树" if level else "半成品子树",
        component_subset=True,
    )
    if result.get("status") == "derived":
        product.current_routing_id = result.get("routing_id")
        await db.flush()
    return result


def _place_step(
    step: Any, idx: int, homes: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """把参考路线上的一道工序落到本厂的工位；落不了的就摘出去。

    参考路线有两种写法：种子路线写了 `station` 编码，厂里的模具线那种工序只写了
    `station_type`（cnc/injection/…）没有编码。**没有编码不等于这道工序不该存在**，
    按工序族把工位解析出来才能排；解析不出来就摘除这道工序 ——
    留一个本厂不存在的工位编码，APS 只会把它列进"跨厂借用"告警。
    """
    name = _step_name(step)
    step_no = int((step or {}).get("step_no") or (step or {}).get("seq") or (idx + 1) * 10)
    code = _step_station(step)
    if code and code in homes["stations"]:
        return ({"step_no": step_no, "name": name, "station": code,
                 "station_basis": f"沿用参考路线上的工位 {code}"}, None)
    suffix = "" if not code else f"（参考路线写的 {code} 不在本厂）"
    exact = homes["by_operation"].get(name) if name else None
    if exact:
        station, basis = exact
        return ({"step_no": step_no, "name": name, "station": station,
                 "station_basis": basis + suffix}, None)
    for family in families_in(name):
        hit = homes["by_family"].get(family)
        if hit:
            station, basis = hit
            return ({"step_no": step_no, "name": name, "station": station,
                     "station_basis": basis + suffix}, None)
    return None, name or f"工序{step_no}"


async def _corroborated_route(
    db: AsyncSession, factory_id: str, corpus: str, *, component_subset: bool,
    exclude_product: Optional[str] = None,
) -> Dict[str, Any]:
    """在同厂参考路线里找一条，并把工序落到本厂工位上、用 BOM 文本佐证。

    返回 `{"status": "ok"|"blocked", "best": ..., "receipt": ...}`：
    blocked 时 `receipt` 已经写好拒绝原因，调用方原样转出去就行。
    """
    receipt: Dict[str, Any] = {"status": "unknown"}
    candidates = await _reference_routings(db, factory_id)
    if not candidates:
        receipt.update({"status": "no_reference_route",
                        "reason": "本厂区没有可参考的多工步标准路线"})
        return {"status": "blocked", "receipt": receipt}
    stations = await _factory_stations(db, factory_id)
    if not stations:
        receipt.update({"status": "no_station_master",
                        "reason": "本厂区一个工位都没登记：路线推出来也没地方干活，先补工位主数据"})
        return {"status": "blocked", "receipt": receipt}
    homes = await _station_homes(db, factory_id, candidates)

    best: Optional[Dict[str, Any]] = None
    for route in candidates:
        if str(route.product_id) == str(exclude_product or ""):
            continue
        placed: List[Dict[str, Any]] = []
        dropped: List[str] = []
        for idx, step in enumerate(route.steps or []):
            item, unplaceable = _place_step(step, idx, homes)
            if item is not None:
                placed.append(item)
            elif unplaceable:
                dropped.append(unplaceable)
        if not placed:
            continue
        hits = [item for item in placed if _matches(item["name"], corpus)]
        coverage = len(hits) / len(placed)
        score = len(hits) if component_subset else coverage
        if best is None or score > best["score"]:
            best = {"route": route, "placed": placed, "hits": hits, "dropped": dropped,
                    "matched": len(hits), "coverage": coverage, "steps": len(placed),
                    "score": score}

    if best is None:
        receipt.update({"status": "not_derived",
                        "reason": "本厂参考路线上的工序都落不到现有工位，推不出能执行的路线"})
        return {"status": "blocked", "receipt": receipt}
    return {"status": "ok", "best": best, "receipt": receipt}


async def _derive_from_corpus(
    db: AsyncSession, factory_id: str, code: str, corpus: str, *, source: str,
    component_subset: bool = False,
) -> Dict[str, Any]:
    """共用的那道门：同厂参考路线 + 工序能落到本厂工位 + BOM 文本佐证，三者齐了才套。

    型号级：要覆盖参考路线至少 `MIN_COVERAGE` 的工序（整机要走完产线）。
    半成品级（`component_subset`）：**只保留它自己子树能佐证的工序**，并且至少 2 道
        —— 車架組 只需焊接+涂装，不該被塞進"電控装配/總裝/包裝"；
    套整条产线反而会给子件排出根本不存在的工作，所以这里按子集建路线。
    """
    found = await _corroborated_route(
        db, factory_id, corpus,
        component_subset=component_subset, exclude_product=code,
    )
    receipt = found["receipt"]
    if found["status"] != "ok":
        return receipt
    best = found["best"]

    if component_subset:
        accepted = len(best["hits"]) >= MIN_COMPONENT_STEPS
        reject_reason = (
            f"子树只能佐证 {best['matched']}/{best['steps']} 道工序"
            f"（不足 {MIN_COMPONENT_STEPS} 道）：再多就是替工厂编工艺"
        )
    else:
        accepted = best["coverage"] >= MIN_COVERAGE
        reject_reason = (
            f"最相近的路线是 {best['route'].id}"
            f"（工序佐证 {best['matched']}/{best['steps']}，覆盖率 {best['coverage']:.0%}"
            f" < {MIN_COVERAGE:.0%}）：{source}的文本认不出那条路线的工序，硬套等于替工厂编工艺"
        )
    if not accepted:
        receipt.update({
            "status": "not_derived",
            "reason": reject_reason,
            "coverage": round(best["coverage"], 3),
            "reference_steps_unplaceable": len(best["dropped"]),
        })
        return receipt

    ref = best["route"]
    chosen = best["hits"] if component_subset else best["placed"]
    normalized = [{k: v for k, v in item.items() if k != "station_basis"}
                  for item in chosen]
    station_sources = sorted({item["station_basis"] for item in chosen})
    routing_id = f"rt-bom-{code}"[:64]
    parts = [
        f"按产品族从 {ref.id}（{ref.product_id}）推导：工序沿用同族标准路线；",
        f"工位解析：" + "；".join(station_sources) + "；",
        f"佐证材料={source}，印证 {best['matched']}/{len(normalized)} 道工序"
        f"（{best['coverage']:.0%}）。",
    ]
    if best["dropped"]:
        parts.append(
            f"参考路线上有 {len(best['dropped'])} 道工序本厂没有对应工位，已摘除："
            + "、".join(best["dropped"]) + "。"
        )
    parts.append("标准工时未经 IE 确认，排程只能当草案。")
    audit_note = "".join(parts)

    already = await db.get(Routing, routing_id)
    if already is None:
        db.add(Routing(
            id=routing_id,
            factory_id=factory_id,
            product_id=code,
            routing_code=f"RT-BOM-{code}"[:50],
            version="CURRENT",
            status="active",
            is_active=True,
            steps=normalized,
            created_by=CREATED_BY,
            remark=audit_note,
        ))
    await db.flush()
    receipt.update({
        "status": "derived",
        "routing_id": routing_id,
        "derived_from": ref.id,
        "coverage": round(best["coverage"], 3),
        "matched_steps": best["matched"],
        "steps": len(normalized),
        "corroborated_by": source,
        "stations_resolved": len({item["station"] for item in normalized if item.get("station")}),
        "reference_steps_unplaceable": len(best["dropped"]),
        "station_sources": station_sources,
        "note": "工时未经 IE 确认；要转成正式基线需工艺部复核 remark 里的出处",
    })
    return receipt


async def corroborated_component_subset(
    db: AsyncSession, factory_id: str, corpus: str, *, exclude_product: Optional[str] = None
) -> Dict[str, Any]:
    """只读地算出"这个半成品被佐证的工序集合"，给路线收窄用（不落库、不改主档）。"""
    found = await _corroborated_route(
        db, factory_id, corpus, component_subset=True, exclude_product=exclude_product)
    if found["status"] != "ok":
        return found["receipt"]
    best = found["best"]
    receipt = dict(found["receipt"])
    receipt.update({
        "steps": [{k: v for k, v in item.items() if k != "station_basis"}
                  for item in best["hits"]],
        "matched_steps": best["matched"],
        "coverage": round(best["coverage"], 3),
        "derived_from": best["route"].id,
        "reference_steps_unplaceable": len(best["dropped"]),
        "station_sources": sorted({item["station_basis"] for item in best["hits"]}),
    })
    return receipt
