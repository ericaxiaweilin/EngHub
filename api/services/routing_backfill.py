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
from typing import Any, Dict

from sqlalchemy import text

from api.services.engine_heartbeat import record
from api.services.routing_from_family import derive_routing_for_product

logger = logging.getLogger(__name__)

BACKFILL_INTERVAL_SECONDS = 900
# 一轮最多处理几个产品：路线推导要读整个型号的 BOM 文本，批量太大既慢又难对账
BATCH_PRODUCTS = 40

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


async def backfill_missing_routings(db, *, apply: bool = True) -> Dict[str, Any]:
    """补一轮路线。返回可对账的凭据：看了几个、套上几个、回填了几张工单、为什么没套上。"""
    targets = (await db.execute(TARGET_WO_SQL, {"limit": BATCH_PRODUCTS})).mappings().all()
    receipt: Dict[str, Any] = {
        "examined": len(targets),
        "by_status": {},
        "derived": 0,
        "routed_products": 0,
        "routed_work_orders": 0,
        "rejected": [],
    }
    for row in targets:
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
    if apply:
        await db.commit()
    else:
        await db.rollback()
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
