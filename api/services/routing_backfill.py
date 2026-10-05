"""引擎循环：把没有工艺路线的在制工单补到能排程。

链路上这是最后一段自动活：MRP 多层展开算出要做什么 → 半成品主档按 BOM 自动登记 →
工艺路线按产品族推导（要 BOM 文本佐证才套）。三段里前两段已经在计划下达时做了，
但**历史工单**是在主档/路线还没有的时候建起来的，`routing_id` 为空，
APS 每次都把它们列进 unrouted 清单，永远排不动（实测厂区 65 张未关闭主工单里 64 张如此）。

这个循环每轮：
1. 找若干张「主工单 + 未关闭 + routing_id IS NULL」的 (厂区, 产品)；
2. 逐个走 `derive_routing_for_product`（同族路线 + BOM 文本佐证率 ≥ 50% 才套）；
3. 套上了（或产品本来就有带工步的路线）才回填工单的 `routing_id`，
   **只动 routing_id IS NULL 的行**，不覆盖人工指定过的路线，也不碰已完成/取消的工单；
4. 逐轮写心跳，把 examined/derived/routed_work_orders 和拒绝原因都报出来 ——
   没人看界面猜"引擎在干活吗"，心跳里就是这一轮干了多少。

回填之后排产本身仍由 `periodic-scheduler` 的 APS 轮次负责：这个循环不排程、不下发，
只把"排不动"变成"能排"。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List

from sqlalchemy import bindparam, text

from api.services.engine_heartbeat import record
from api.services.component_orders import expand_ready_components
from api.services.snapshot_supply import refresh_snapshot_supply
from api.services.routing_from_family import (
    derive_routing_for_component,
    derive_routing_for_product,
)

logger = logging.getLogger(__name__)

BACKFILL_INTERVAL_SECONDS = 900
# 开发/测试阶段的规模闸门（用户 10-04 定的口径：从小到大，别一把推成全量）：
# - 一轮只看几个产品；
# - 推导出来的路线总数有预算，用完就停，要继续得显式改环境变量。
#   没有预算的话这个循环会在后台一路把 473 个型号全推一遍。
BATCH_PRODUCTS = max(1, int(os.getenv("ROUTING_BACKFILL_BATCH", "5")))
MAX_DERIVED_ROUTES = max(0, int(os.getenv("ROUTING_BACKFILL_MAX_ROUTES", "20")))

COUNT_DERIVED_SQL = text("""
    SELECT count(*) FROM routings WHERE created_by = 'bom-family-derived'
""")

# 回填只针对"还没排动"的主工单；子工单/已完工/已取消一概不动
TARGET_WO_SQL = text("""
    SELECT DISTINCT wo.factory_id, wo.product_id
    FROM work_orders wo
    WHERE wo.wo_type = 'master'
      AND wo.status NOT IN ('completed', 'cancelled')
      AND wo.routing_id IS NULL
      AND wo.product_id IS NOT NULL
    ORDER BY wo.factory_id, wo.product_id
    LIMIT :limit
""")

BIND_WO_SQL = text("""
    UPDATE work_orders
    SET routing_id = :routing_id, updated_at = NOW()
    WHERE wo_type = 'master'
      AND status NOT IN ('completed', 'cancelled')
      AND routing_id IS NULL
      AND factory_id = :fid AND product_id = :pid
""")

# 半成品级：只看已经有整机型路线、且齐套快照带层级的主工单
COMPONENT_WO_SQL = text("""
    SELECT wo.id, wo.factory_id, wo.product_id
    FROM work_orders wo
    WHERE wo.wo_type = 'master'
      AND wo.status NOT IN ('completed', 'cancelled')
      AND wo.routing_id IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM work_order_materials m
          WHERE m.work_order_id = wo.id AND m.item_type = 'make' AND m.parent_code IS NOT NULL
      )
    ORDER BY wo.created_at DESC
    LIMIT :limit
""")

COMPONENT_ROWS_SQL = text("""
    SELECT material_code, material_name, item_type, level, parent_code
    FROM work_order_materials
    WHERE work_order_id = :wo_id
""")

ROUTED_CODES_SQL = text("""
    SELECT p.product_code
    FROM products p
    JOIN routings r ON r.id = p.current_routing_id
    WHERE p.product_code = ANY(:codes)
      AND r.steps IS NOT NULL AND COALESCE(jsonb_array_length(r.steps::jsonb), 0) > 0
""")

COMPONENT_BATCH = max(1, int(os.getenv("ROUTING_BACKFILL_WOS_PER_TICK", "2")))


async def _subtree_corpus(rows: List[Any], root_code: str) -> str:
    """从齐套快照的 parent_code 链取某个半成品的整棵子树文本。

    半成品自己的下层就在同一份 BOM 里（用户 10-05 的口径：L3 即半成品），
    所以子件不用再传一次 BOM —— 子件行写的"烤漆/鹽浴滲氮/45#"就是工序佐证材料。
    """
    children: Dict[str, List[Any]] = {}
    for row in rows:
        parent = str(row["parent_code"] or "")
        children.setdefault(parent, []).append(row)

    texts: List[str] = []
    stack = list(children.get(root_code, []))
    seen = set()
    while stack:
        node = stack.pop()
        code = str(node["material_code"] or "")
        if code and code not in seen:
            seen.add(code)
            texts.append(str(node["material_name"] or ""))
            stack.extend(children.get(code, []))
    return " ".join(t for t in texts if t)


async def backfill_component_routes(
    db, *, limit: int = COMPONENT_BATCH, budget_left: int, apply: bool = True
) -> Dict[str, Any]:
    """给已下达到、有层级快照的自制半成品补工艺路线（同一道佐证门）。"""
    receipt: Dict[str, Any] = {
        "examined": 0, "derived": 0, "existing": 0, "not_derived": 0,
        "no_master": 0, "no_bom_text": 0, "rejected": [],
    }
    if budget_left <= 0:
        receipt["status"] = "budget_exhausted"
        return receipt

    wos = (await db.execute(COMPONENT_WO_SQL, {"limit": limit})).mappings().all()
    for wo in wos:
        fid = str(wo["factory_id"])
        rows = (await db.execute(COMPONENT_ROWS_SQL, {"wo_id": wo["id"]})).mappings().all()
        made = [r for r in rows if str(r["item_type"] or "") == "make"]
        receipt["examined"] += len(made)
        routed = {str(c) for c in (await db.execute(ROUTED_CODES_SQL, {
            "codes": [str(r["material_code"]) for r in made] or ["__none__"]
        })).scalars().all()}
        for row in made:
            if receipt["derived"] >= budget_left:
                receipt["status"] = "budget_reached"
                return receipt
            code = str(row["material_code"])
            if code in routed:
                receipt["existing"] += 1
                continue
            corpus = await _subtree_corpus(rows, code)
            result = await derive_routing_for_component(
                db, fid, code, corpus, level=row["level"]
            )
            status = str(result.get("status"))
            receipt[status] = receipt.get(status, 0) + 1
            if status in ("not_derived", "no_bom_text") and len(receipt["rejected"]) < 5:
                receipt["rejected"].append({
                    "material_code": code, "status": status,
                    "reason": result.get("reason"), "coverage": result.get("coverage"),
                })
        if apply:
            await db.commit()
        receipt["status"] = receipt.get("status", "ok")
    receipt.setdefault("status", "ok")
    return receipt


async def backfill_missing_routings(db, *, apply: bool = True) -> Dict[str, Any]:
    """补一轮路线。返回可对账的凭据：看了几个、套上几个、回填了几张工单、为什么没套上。"""
    already_derived = int((await db.execute(COUNT_DERIVED_SQL)).scalar() or 0)
    receipt: Dict[str, Any] = {
        "examined": 0,
        "by_status": {},
        "derived": 0,
        "routed_products": 0,
        "routed_work_orders": 0,
        "rejected": [],
        "derived_routes_in_db": already_derived,
        "route_budget": MAX_DERIVED_ROUTES,
    }
    if already_derived >= MAX_DERIVED_ROUTES:
        # 预算用完了就停手，并把"为什么这轮没干活"写进心跳，别让人以为循环挂了
        receipt["status"] = "budget_exhausted"
        return receipt

    targets = (await db.execute(
        TARGET_WO_SQL, {"limit": BATCH_PRODUCTS}
    )).mappings().all()
    receipt["examined"] = len(targets)
    for row in targets:
        if already_derived + receipt["derived"] >= MAX_DERIVED_ROUTES:
            receipt["status"] = "budget_reached"
            break
        fid = str(row["factory_id"])
        product_code = str(row["product_id"])
        result = await derive_routing_for_product(db, fid, product_code)
        status = str(result.get("status") or "unknown")
        receipt["by_status"][status] = receipt["by_status"].get(status, 0) + 1
        if status in ("derived", "existing"):
            receipt["derived"] += status == "derived"
            receipt["routed_products"] += 1
            if apply and result.get("routing_id"):
                updated = await db.execute(BIND_WO_SQL, {
                    "routing_id": result["routing_id"], "fid": fid, "pid": product_code,
                })
                receipt["routed_work_orders"] += int(updated.rowcount or 0)
        elif len(receipt["rejected"]) < 5:
            # 拒绝要说得出原因，否则下一轮还是同样一批排不动，也没人知道差什么
            receipt["rejected"].append({
                "product_code": product_code,
                "status": status,
                "reason": result.get("reason"),
                "coverage": result.get("coverage"),
            })
    receipt.setdefault("status", "ok")
    if apply:
        await db.commit()
    else:
        await db.rollback()

    # 型号级之后再看半成品级：同一份预算里继续往下推，仍受佐证率那道门管
    budget_left = max(0, MAX_DERIVED_ROUTES - already_derived - receipt["derived"])
    components = await backfill_component_routes(
            db, budget_left=budget_left, apply=apply)
    receipt["components"] = components
    # 路线推出来后，把 ready 的半成品拆成子工单：这是"无人"真正能落任务的那一步
    if apply:
        await db.commit()
    orders = await expand_ready_components(db, apply=apply)
    receipt["component_orders"] = orders
    if apply:
        await db.commit()
    # 最后把主快照的缺口按当前台账刷一遍：下级完工入库后，父层齐套门才会自己放行
    receipt["supply_refresh"] = await refresh_snapshot_supply(db, apply=apply)
    receipt["dry_run"] = not apply
    return receipt


async def routing_backfill_loop() -> None:
    """引擎循环主体：自己报逐轮心跳，异常也如实记 failed 再退避。"""
    from database.db_config import db_config

    while True:
        try:
            async with db_config.session_factory() as db:
                receipt = await backfill_missing_routings(db)
            await record("routing-backfill", "tick", detail=receipt,
                         interval_seconds=BACKFILL_INTERVAL_SECONDS)
            if receipt.get("routed_work_orders"):
                logger.info("[routing-backfill] 回填 %s 张工单的工艺路线：%s",
                            receipt["routed_work_orders"], receipt["by_status"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("[routing-backfill] 本轮失败: %s", exc)
            await record("routing-backfill", "failed",
                         error=f"{type(exc).__name__}: {exc}",
                         interval_seconds=BACKFILL_INTERVAL_SECONDS)
        await asyncio.sleep(BACKFILL_INTERVAL_SECONDS)
