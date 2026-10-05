"""把就绪的自制半成品拆成可执行的下级工单（无人链路的最后一段）。

链路现状：多层 BOM 展开算出每层需求 → 半成品主档按 BOM 自动登记 → 同族路线按子树佐证推导。
到这一步，`ready` 的半成品有主档、有路线，但**还没有工单**——
主工单的齐套表把它当成一行缺料数字，车间无从开工，APS 也只排主工单那一条线。

行业做法（SAP 的 planned order→production order 逐层下达、Oracle/NetSuite 的
build-in-bom 子装配件工单）是：**按 BOM 层级拆出子工单，子工单挂 parent、
吃自己那层物料的齐套**。这里照这个口径做，并守三条边界：

1. **只拆 `ready` 的半成品**：主档 + 路线 + 工步齐全才开工单；
   `no_routing/empty_routing/missing_master` 的一律不拆，原因照常报（不给没路线的东西造任务）。
2. **数量来自 MRP 已有的层级结果**，不重新估：子工单 planned_qty = 主工单快照里这个半成品的
   毛需求（已按父层净需求逐层算过）；子工单的物料行 = 快照里 `parent_code` 指向它的那些行。
   不新算用量、不补系数。
3. **规模有闸**（开发/测试阶段，用户 10-05 明确不跑全量）：一轮最多拆
   `COMPONENT_ORDER_BATCH` 张，全厂累计不超过 `COMPONENT_ORDER_MAX_TOTAL` 张，
   用完在心跳里写 `budget_reached`，不静默停。

幂等：子工单编码固定为 `主工单号-料号`（`work_orders.work_order_code` 是唯一索引），
重跑只会 skip 不会重复造单。
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.bom_source import production_readiness
from database.models import WorkOrder, WorkOrderMaterial

COMPONENT_WO_TYPE = "component"
CREATED_BY = "component_expand"

# 开发尺度：一轮拆几张、总共允许拆多少张（可环境变量抬级，默认小）
COMPONENT_ORDER_BATCH = max(1, int(os.getenv("COMPONENT_ORDER_BATCH", "10")))
COMPONENT_ORDER_MAX_TOTAL = max(0, int(os.getenv("COMPONENT_ORDER_MAX_TOTAL", "60")))

MASTER_WO_SQL = text("""
    SELECT wo.id, wo.factory_id, wo.work_order_code, wo.source_plan_id,
           wo.planned_due, wo.priority, wo.unit
    FROM work_orders wo
    WHERE wo.wo_type = 'master'
      AND wo.status NOT IN ('completed', 'cancelled')
      AND EXISTS (
          SELECT 1 FROM work_order_materials m
          WHERE m.work_order_id = wo.id AND m.item_type = 'make'
      )
    ORDER BY wo.created_at DESC
    LIMIT :limit
""")

SNAPSHOT_SQL = text("""
    SELECT material_code, material_name, item_type, level, parent_code,
           required_qty, available_qty, allocated_qty, shortage_qty, unit
    FROM work_order_materials
    WHERE work_order_id = :wo_id
    ORDER BY level NULLS LAST, material_code
""")

COUNT_COMPONENT_WOS_SQL = text("""
    SELECT count(*) FROM work_orders
    WHERE wo_type = 'component'
      AND status NOT IN ('completed', 'cancelled')
""")


def component_order_code(master_code: str, material_code: str) -> str:
    """子工单号必须稳定且短：work_order_code 是 varchar(50) 唯一索引。

    原来拼 `主工单号-料号`：现在这些编码 42 字符、还没被截断，但主工单号一长
    （加厂区/日期前缀的变体）就会顶到 varchar(50) 被切齐，不同料号撞成同一个键，
    幂等判断随之失效。改成固定前缀 + 主从组合 12 位散列：同输入同编码、长度恒定，
    换主工单必然换编码。
    """
    digest = hashlib.sha1(f"{master_code}|{material_code}".encode()).hexdigest()[:12]
    return f"WO-CMP-{digest}"


async def expand_ready_components(
    db: AsyncSession, *, factory_id: Optional[str] = None,
    limit: int = COMPONENT_ORDER_BATCH, apply: bool = True,
) -> Dict[str, Any]:
    """把就绪半成品拆成子工单，物料行取自主工单快照的同一层结构。"""
    existing_total = int((await db.execute(COUNT_COMPONENT_WOS_SQL)).scalar() or 0)
    receipt: Dict[str, Any] = {
        "factory_id": factory_id or "全部在制主工单",
        "component_work_orders_in_db": existing_total,
        "order_budget": COMPONENT_ORDER_MAX_TOTAL,
        "examined_masters": 0,
        "examined_components": 0,
        "created": 0,
        "existing": 0,
        "skipped_not_ready": {},
        "material_lines": 0,
        "created_codes": [],
    }
    if existing_total >= COMPONENT_ORDER_MAX_TOTAL:
        receipt["status"] = "budget_exhausted"
        return receipt

    masters = (await db.execute(
        MASTER_WO_SQL, {"limit": max(1, limit)}
    )).mappings().all()
    receipt["examined_masters"] = len(masters)

    for master in masters:
        rows = [dict(r) for r in (await db.execute(
            SNAPSHOT_SQL, {"wo_id": master["id"]}
        )).mappings().all()]
        make_rows = [r for r in rows if str(r.get("item_type") or "") == "make"]
        readiness = await production_readiness(
            db, str(master["factory_id"]), [str(r["material_code"]) for r in make_rows]
        )
        children_by_parent: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            children_by_parent.setdefault(str(row.get("parent_code") or ""), []).append(row)

        for row in make_rows:
            if existing_total + receipt["created"] >= COMPONENT_ORDER_MAX_TOTAL:
                receipt["status"] = "budget_reached"
                break
            if len(receipt["created_codes"]) >= limit:
                break
            code = str(row["material_code"])
            status = readiness.get(code) or "missing_master"
            if status != "ready":
                receipt["skipped_not_ready"][status] = \
                    receipt["skipped_not_ready"].get(status, 0) + 1
                continue
            receipt["examined_components"] += 1

            wo_code = component_order_code(str(master["work_order_code"]), code)
            # 幂等键是 (父工单, 料号) 而不是工单编码：编码格式换过一次（旧的是
            # `主工单号-料号`，会被 varchar(50) 截断），只按编码查就会把旧格式已建的单
            # 当成新单再建一遍 —— 实测这样重复了 10 张。
            existing_stmt = select(WorkOrder).where(
                WorkOrder.parent_work_order_id == str(master["id"]),
                WorkOrder.product_id == code,
                WorkOrder.wo_type == COMPONENT_WO_TYPE,
                WorkOrder.status != "cancelled",
            )
            already = (await db.execute(existing_stmt)).scalar_one_or_none()
            if already is not None:
                receipt["existing"] += 1
                continue

            code_stmt = select(WorkOrder).where(WorkOrder.work_order_code == wo_code)
            if (await db.execute(code_stmt)).scalar_one_or_none() is not None:
                # 同编码已被别的单占用（散列撞车或历史遗留）：跳过而不是覆盖
                receipt["skipped_not_ready"]["code_taken"] = \
                    receipt["skipped_not_ready"].get("code_taken", 0) + 1
                continue

            qty = int(row.get("required_qty") or 0)
            if qty <= 0:
                # 没有需求量的半成品不开工单：那是结构行，不是这批要造的东西
                receipt["skipped_not_ready"]["zero_requirement"] = \
                    receipt["skipped_not_ready"].get("zero_requirement", 0) + 1
                continue

            master_route = (await db.execute(text(
                "SELECT current_routing_id FROM products WHERE product_code = :code"
            ), {"code": code})).scalar()
            child = WorkOrder(
                id=str(uuid.uuid4()),
                work_order_code=wo_code,
                factory_id=str(master["factory_id"]),
                source_plan_id=master["source_plan_id"],
                product_id=code,
                routing_id=str(master_route) if master_route else None,
                planned_qty=qty,
                unit=str(row.get("unit") or master["unit"] or "pcs"),
                completed_qty=0, good_qty=0, defect_qty=0, scrap_qty=0,
                status="pending",
                priority=str(master["priority"] or "normal"),
                planned_due=master["planned_due"],
                parent_work_order_id=str(master["id"]),
                wo_type=COMPONENT_WO_TYPE,
                current_routing_step=0,
                created_by=CREATED_BY,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                remark=(
                    f"由主工单 {master['work_order_code']} 按 BOM 层级拆出："
                    f"{row.get('material_name') or code}（L{row.get('level')}，"
                    f"数量取自主工单齐套快照，路线为同族推导草案）"
                ),
            )
            if apply:
                db.add(child)

            # 子工单吃自己那一层的物料：快照里 parent_code 指向它的行原样带下去。
            # 需求为 0 的行是结构占位，不是领料需求，抄进去只会让齐套表多假行。
            for line in children_by_parent.get(code, []):
                if int(line.get("required_qty") or 0) <= 0:
                    receipt["material_lines_skipped"] = \
                        receipt.get("material_lines_skipped", 0) + 1
                    continue
                if apply:
                    db.add(WorkOrderMaterial(
                        id=str(uuid.uuid4()),
                        work_order_id=child.id,
                        material_id=line["material_code"],
                        material_code=line["material_code"],
                        material_name=line.get("material_name"),
                        required_qty=int(line.get("required_qty") or 0),
                        available_qty=int(line.get("available_qty") or 0),
                        received_qty=int(line.get("available_qty") or 0),
                        shortage_qty=int(line.get("shortage_qty") or 0),
                        unit=line.get("unit"),
                        level=int(line.get("level") or 0) - int(row.get("level") or 0),
                        parent_code=None,
                        allocated_qty=int(line.get("allocated_qty") or 0),
                        item_type=line.get("item_type"),
                    ))
                receipt["material_lines"] += 1
            receipt["created"] += 1
            receipt["created_codes"].append(wo_code)

        if receipt.get("status") == "budget_reached":
            break

    if apply and (receipt["created"] or receipt["material_lines"]):
        await db.flush()
    receipt.setdefault("status", "ok")
    receipt["dry_run"] = not apply
    return receipt
