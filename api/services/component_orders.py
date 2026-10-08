"""把就绪的自制半成品拆成可执行的下级工单（无人链路的最后一段）。

链路现状：多层 BOM 展开算出每层需求 → 半成品主档按 BOM 自动登记 → 同族路线按子树佐证推导。
到这一步，`ready` 的半成品有主档、有路线，但**还没有工单**——
主工单的齐套表把它当成一行缺料数字，车间无从开工，APS 也只排主工单那一条线。

行业做法（SAP 的 planned order→production order 逐层下达、Oracle/NetSuite 的
build-in-bom 子装配件工单）是：**按 BOM 层级拆出子工单，子工单挂 parent、
吃自己那层物料的齐套**。这里照这个口径做，并守四条边界：

1. **只拆 `ready` 的半成品**：主档 + 路线 + 工步齐全才开工单；
   `no_routing/empty_routing/missing_master` 的一律不拆，原因照常报（不给没路线的东西造任务）。
2. **只拆净缺口 > 0 的半成品，数量按净缺口开**：毛需求 > 0 但库存已经覆盖（净缺口 0）
   不是"要造的东西"。原来只看 required_qty，实测 621 张子工单里 197 张开在净缺口 0 上
   —— 它们既没有下层需求（低层码不炸父层已够的子层）也永远等不到齐套，只灌池子、
   占排程任务行、占催办。净缺口才是任务量，planned_qty 也按净缺口写，
   不然多造的那部分就是下一次"虚假库存"的来源（10-05 已经清过一次 948 件）。
3. **子工单的物料行按它自己的 BOM 展开算**（`explode_requirement`），不再从父单快照往下抄：
   父层净需求当时是 0 时低层码就不炸子层，抄下来的 required 全是 0，
   实测 289 张子单因此没有自己的物料行、引擎判"没有依据"既不投产也不催料。
   展开只在这台组件的镜像拼不出树时回落到父快照，并且报回落了几张（不静默换口径）。
4. **规模有闸**（开发/测试阶段，用户 10-05 明确不跑全量）：一轮最多拆
   `COMPONENT_ORDER_BATCH` 张，全厂累计不超过 `COMPONENT_ORDER_MAX_TOTAL` 张，
   用完在心跳里写 `budget_reached`，不静默停。

幂等：子工单编码由 `主工单号|料号` 散列成固定长度（见 `component_order_code`），
且真正查的是 (父工单, 料号) —— 重跑只会 skip，不会重复造单。
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.bom_source import explode_requirement, production_readiness
from database.models import WorkOrder, WorkOrderMaterial

COMPONENT_WO_TYPE = "component"
CREATED_BY = "component_expand"

# 开发尺度：一轮拆几张、总共允许拆多少张（可环境变量抬级，默认小）
COMPONENT_ORDER_BATCH = max(1, int(os.getenv("COMPONENT_ORDER_BATCH", "10")))
COMPONENT_ORDER_MAX_TOTAL = max(0, int(os.getenv("COMPONENT_ORDER_MAX_TOTAL", "60")))

# 引擎承认自己开错单/放错行是要改状态的，不能因为"代码里有个函数"就自动发生
# （用户 10-05：破坏性作用域要显式开关）。取消净缺口为 0 的子单、补写领料行、
# 就绪门收回误放行，三格共用 ENGINE_RECONCILE_APPLY 这一个开关，默认只预演报数字。
RECONCILE_APPLY = os.getenv("ENGINE_RECONCILE_APPLY", "false").strip().lower() in ("1", "true", "yes", "on")

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


def _from_explosion(own: Optional[Dict[str, Any]], *, exclude_code: str) -> List[Dict[str, Any]]:
    """把 explode_requirement 的行归一成齐套表口径。

    展开用的是 MRP 的字段名（on_hand_qty/net_qty），齐套表用的是另一套
    （available_qty/shortage_qty）—— 两张表必须一一对应，否则子单看起来"不缺料"
    而主单看着缺一堆，同一批料在两套视图里互相矛盾。
    展开的 level 以这台组件自己为 L1，落进子单的齐套表时要下移一层（直接下层=1）。
    """
    out: List[Dict[str, Any]] = []
    for line in (own or {}).get("lines") or []:
        code = str(line.get("material_code") or "")
        if not code or code == exclude_code:
            # 组件自己的料号会作为根行出现在镜像里，但它不是自己的物料
            continue
        out.append({
            "material_code": code,
            "material_name": line.get("material_name") or code,
            "unit": line.get("unit"),
            "required_qty": float(line.get("required_qty") or 0),
            "available_qty": float(line.get("on_hand_qty") or 0),
            "allocated_qty": float(line.get("allocated_qty") or 0),
            "shortage_qty": float(line.get("net_qty") or 0),
            "level": max(1, int(line.get("level") or 1) - 1),
            "item_type": line.get("item_type"),
        })
    return out


def _from_snapshot(children: List[Dict[str, Any]], *, base_level: int) -> List[Dict[str, Any]]:
    """父单快照回落：字段名本来就与齐套表一致，只要把层级基准挪到这台组件下面。"""
    return [{
        "material_code": str(c["material_code"]),
        "material_name": c.get("material_name"),
        "unit": c.get("unit"),
        "required_qty": float(c.get("required_qty") or 0),
        "available_qty": float(c.get("available_qty") or 0),
        "allocated_qty": float(c.get("allocated_qty") or 0),
        "shortage_qty": float(c.get("shortage_qty") or 0),
        "level": int(c.get("level") or 0) - base_level,
        "item_type": c.get("item_type"),
    } for c in children]


async def _write_kit_lines(db: AsyncSession, *, child_id: str, kit_lines: List[Dict[str, Any]],
                           apply: bool, receipt: Dict[str, Any]) -> int:
    """把算好的领料行落到工单齐套表 —— 拆新单和补老单共用这一条写路径。

    需求为 0 的行不写：那是结构占位，写进去只会让齐套表多一行假"不缺料"。
    """
    written = 0
    for line in kit_lines:
        if float(line.get("required_qty") or 0) <= 0:
            receipt["material_lines_skipped"] = \
                receipt.get("material_lines_skipped", 0) + 1
            continue
        if apply:
            db.add(WorkOrderMaterial(
                id=str(uuid.uuid4()),
                work_order_id=child_id,
                material_id=line["material_code"],
                material_code=line["material_code"],
                material_name=line.get("material_name"),
                required_qty=line["required_qty"],
                available_qty=line["available_qty"],
                received_qty=line["available_qty"],
                shortage_qty=line["shortage_qty"],
                unit=line.get("unit"),
                level=line["level"],
                parent_code=None,
                allocated_qty=line["allocated_qty"],
                item_type=line.get("item_type"),
            ))
        written += 1
    return written


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
        # 齐套依据的来源必须分开报：一张子单的材料行是自己展开的还是抄父快照的，
        # 口径不同（后者可能全是 0），混在一起就看不出低层码的问题修没修好。
        "kits_from_own_explosion": 0,
        "kits_from_parent_snapshot": 0,
        "reopened": 0,
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
            qty = int(row.get("required_qty") or 0)          # 毛需求（快照口径）
            gap = int(row.get("shortage_qty") or 0)          # 净缺口 = 真正要造的量
            if qty <= 0:
                # 没有需求量的半成品不开工单：那是结构行，不是这批要造的东西
                receipt["skipped_not_ready"]["zero_requirement"] = \
                    receipt["skipped_not_ready"].get("zero_requirement", 0) + 1
                continue
            if gap <= 0:
                # 库存/在途已经把父件这一行盖住了，这张单永远等不到"齐套"，也不该开工
                receipt["skipped_not_ready"]["covered_by_stock"] = \
                    receipt["skipped_not_ready"].get("covered_by_stock", 0) + 1
                continue

            # 幂等键是 (父工单, 料号)，而且**含已取消的那张**：一台组件在一个父单下
            # 只该有一张工单，编码又是这两者的散列 —— 跳过被取消的去找新单必然撞编码。
            # 上一轮因净缺口为 0 被引擎取消、这一轮父件又真的要它了（库存被别的单吃掉），
            # 就把同一张单重新打开，而不是留一张 cancelled 挡路、再让本轮报 code_taken。
            existing_stmt = select(WorkOrder).where(
                WorkOrder.parent_work_order_id == str(master["id"]),
                WorkOrder.product_id == code,
                WorkOrder.wo_type == COMPONENT_WO_TYPE,
            ).order_by(WorkOrder.status != "cancelled").limit(1)
            already = (await db.execute(existing_stmt)).scalar()
            if already is not None:
                if str(already.status) != "cancelled":
                    receipt["existing"] += 1
                    continue
                reopened = await db.execute(text("""
                    UPDATE work_orders
                    SET status = 'pending', planned_qty = :qty,
                        remark = COALESCE(remark, '') || :note,
                        updated_at = NOW()
                    WHERE id = :wid AND status = 'cancelled'
                      AND created_by = 'component_expand'
                """), {"wid": str(already.id), "qty": gap,
                       "note": f"；引擎重开：父件净缺口回到 {gap}，这批要造了"})
                receipt["reopened"] += int(reopened.rowcount or 0)
                continue

            code_stmt = select(WorkOrder).where(WorkOrder.work_order_code == wo_code)
            if (await db.execute(code_stmt)).scalar_one_or_none() is not None:
                # 同编码已被别的父单占用（散列撞车或历史遗留）：跳过而不是覆盖
                receipt["skipped_not_ready"]["code_taken"] = \
                    receipt["skipped_not_ready"].get("code_taken", 0) + 1
                continue

            master_route = (await db.execute(text(
                "SELECT current_routing_id FROM products WHERE product_code = :code"
            ), {"code": code})).scalar()

            # 子工单的物料行 = 这台组件自己的逐层净需求（低层码），不再从父单快照往下抄：
            # 父层当时净缺口为 0 就不炸子层，抄下来全是 0（实测 289 张因此"没有依据"）。
            kit_lines: List[Dict[str, Any]] = []
            problems: List[str] = []
            try:
                own = await explode_requirement(db, str(master["factory_id"]), code, gap)
                problems = list((own or {}).get("problems") or [])
                kit_lines = _from_explosion(own, exclude_code=code)
            except Exception as exc:  # noqa: BLE001 - 展开失败要回落，但原因必须报出来
                problems = [f"展开异常：{type(exc).__name__}: {exc}"]
            from_own_bom = any(float(l["required_qty"]) > 0 for l in kit_lines)
            if not from_own_bom:
                # 这台组件在镜像里没有自己的 BOM（或树拼不出）：只能用父单快照里
                # 指向它的那些行，并如实记下用了回落 —— 两种口径的层级基准不同。
                kit_lines = _from_snapshot(children_by_parent.get(code, []),
                                           base_level=int(row.get("level") or 0))
                if problems:
                    receipt.setdefault("kit_problems", []).append(
                        {"work_order_code": wo_code, "problems": problems[:3]})
            if not any(float(l["required_qty"]) > 0 for l in kit_lines):
                # 两种口径都给不出一行领料需求 = 厂里不知道这台半成品是用什么做的。
                # 开一张没有依据的单只会把它变成"永远等不到齐套"的在制负担（实测 74 张），
                # 所以在这里停手，并把它作为 BOM 缺失报出去。
                receipt["skipped_not_ready"]["no_kit_source"] = \
                    receipt["skipped_not_ready"].get("no_kit_source", 0) + 1
                receipt.setdefault("missing_bom_parts", []).append(code)
                continue
            if from_own_bom:
                receipt["kits_from_own_explosion"] += 1
            else:
                receipt["kits_from_parent_snapshot"] += 1

            child = WorkOrder(
                id=str(uuid.uuid4()),
                work_order_code=wo_code,
                factory_id=str(master["factory_id"]),
                source_plan_id=master["source_plan_id"],
                product_id=code,
                routing_id=str(master_route) if master_route else None,
                planned_qty=gap,
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
                    f"毛需求 {qty}、净缺口 {gap}，工单量按净缺口；"
                    "数量取自主工单齐套快照，路线为同族推导草案）"
                ),
            )
            if apply:
                db.add(child)

            receipt["material_lines"] += await _write_kit_lines(
                db, child_id=child.id, kit_lines=kit_lines, apply=apply, receipt=receipt)
            receipt["created"] += 1
            receipt["created_codes"].append(wo_code)

        if receipt.get("status") == "budget_reached":
            break

    if apply and (receipt["created"] or receipt["material_lines"]):
        await db.flush()
    receipt.setdefault("status", "ok")
    receipt["dry_run"] = not apply
    return receipt


COVERED_CHILDREN_SQL = text("""
    SELECT c.id AS work_order_id, c.work_order_code, c.product_id,
           c.planned_qty, p.required_qty AS parent_required,
           p.shortage_qty AS parent_shortage, p.available_qty AS parent_available
    FROM work_orders c
    JOIN work_order_materials p
      ON p.work_order_id = c.parent_work_order_id AND p.material_code = c.product_id
    WHERE (CAST(:fid AS varchar) IS NULL OR c.factory_id = CAST(:fid AS varchar))
      AND c.wo_type = 'component'
      AND c.created_by = 'component_expand'          -- 只收引擎自己开的单，人工建的不动
      AND c.status IN ('pending', 'released')        -- 被误放行的也要收：净缺口 0 没有可开工的东西
      AND COALESCE(c.completed_qty, 0) = 0
      AND NOT EXISTS (SELECT 1 FROM production_reports pr WHERE pr.work_order_id = c.id)
      AND COALESCE(p.required_qty, 0) > 0            -- 父层确实需要这个组件
      AND COALESCE(p.shortage_qty, 0) <= 0           -- 但库存/在途已经盖住了
    ORDER BY c.work_order_code
""")

STALE_FOLLOWUPS_SQL = text("""
    SELECT count(*) FROM followup_tasks
    WHERE payload->>'work_order_id' IN :ids
      AND status NOT IN ('done', 'cancelled')
""").bindparams(bindparam("ids", expanding=True))


async def retire_covered_child_orders(
    db: AsyncSession, factory_id: Optional[str] = None, *,
    apply: Optional[bool] = None, limit: int = 200,
) -> Dict[str, Any]:
    """收掉"父件本已被库存/在途盖住"却开出来的子工单。

    判据和拆单用的是同一句话：净缺口 > 0 才是要造的东西。这类单子永远等不到齐套，
    只会占排程任务行、占催办、把在制池子灌水。四条护栏：只动引擎自己开的
    （`created_by='component_expand'`）、只动 pending、没产出、没报过工的；
    取消原因写进工单备注（不是删行，留得回查）。
    默认只预演 —— 批量取消是在删东西，要显式开 `ENGINE_RECONCILE_APPLY=true`。
    """
    rows = (await db.execute(
        COVERED_CHILDREN_SQL, {"fid": factory_id}
    )).mappings().all()
    # 环境开关在读函数时才生效：调用方没显式表态时默认预演，
    # 显式传 True/False 才绕过它（跑一次性清理时用）。
    if apply is None:
        apply = RECONCILE_APPLY
    receipt: Dict[str, Any] = {
        "factory_id": factory_id,
        "apply": apply,
        "dry_run": not apply,
        "covered_children_found": len(rows),
        "cancelled": 0,
        "schedule_tasks_cancelled": 0,
        "examples": [dict(r) for r in rows[:5]],
    }
    if not rows:
        receipt["status"] = "nothing_to_retire"
        return receipt

    ids = [str(r["work_order_id"]) for r in rows][:limit]
    receipt["stale_followup_tasks"] = int((await db.execute(
        STALE_FOLLOWUPS_SQL, {"ids": ids}
    )).scalar() or 0)
    if not apply:
        receipt["status"] = "dry_run"
        receipt["message"] = (f"预演：{len(rows)} 张子工单开在净缺口为 0 的父件上，"
                             f"可取消（本轮最多 {limit} 张）；"
                             "确认后置 ENGINE_RECONCILE_APPLY=true 才真取消")
        return receipt

    for r in rows:
        if str(r["work_order_id"]) not in ids:
            continue
        cancelled = await db.execute(text("""
            UPDATE work_orders
            SET status = 'cancelled',
                remark = COALESCE(remark, '') || :note,
                updated_at = NOW()
            WHERE id = :wid AND status IN ('pending', 'released')
              AND COALESCE(completed_qty, 0) = 0
              AND created_by = 'component_expand'
        """), {
            "wid": r["work_order_id"],
            "note": (f"；引擎取消：父件 {r['product_id']} 净缺口为 0"
                     f"（毛需求 {float(r['parent_required'] or 0):g}、"
                     f"可用 {float(r['parent_available'] or 0):g}），这批不用造"),
        })
        # 报的是真改了几张，不是"打算改几张"：状态在两步之间被别人改过就要露出来
        receipt["cancelled"] += int(cancelled.rowcount or 0)
        # 排程任务行跟着一起停：留着草案里指向已取消工单的任务，
        # 就绪门和 chat 就会数出根本不存在的活。已完工/已下达的不动。
        updated = await db.execute(text("""
            UPDATE aps_schedule_tasks SET status = 'cancelled'
            WHERE work_order_id = :wid
              AND COALESCE(status, '') NOT IN ('completed', 'released', 'cancelled')
        """), {"wid": r["work_order_id"]})
        receipt["schedule_tasks_cancelled"] += int(updated.rowcount or 0)

    await db.commit()
    receipt["status"] = "ok"
    receipt["message"] = (f"已取消 {receipt['cancelled']} 张净缺口为 0 的子工单，"
                          f"同时停掉 {receipt['schedule_tasks_cancelled']} 条排程任务行")
    return receipt


NEEDS_KIT_SQL = text("""
    SELECT c.id, c.factory_id, c.work_order_code, c.product_id, c.planned_qty,
           c.parent_work_order_id, c.status,
           p.level AS parent_level, p.required_qty AS parent_required,
           p.shortage_qty AS parent_shortage
    FROM work_orders c
    JOIN work_order_materials p
      ON p.work_order_id = c.parent_work_order_id AND p.material_code = c.product_id
    WHERE (CAST(:fid AS varchar) IS NULL OR c.factory_id = CAST(:fid AS varchar))
      AND c.wo_type = 'component'
      AND c.created_by = 'component_expand'
      AND c.status IN ('pending', 'released')
      AND COALESCE(p.shortage_qty, 0) > 0                  -- 父件确实还要它，才值得补依据
      AND NOT EXISTS (SELECT 1 FROM work_order_materials m
                      WHERE m.work_order_id = c.id AND COALESCE(m.required_qty, 0) > 0)
    ORDER BY c.work_order_code
    LIMIT :limit
""")


async def rebuild_missing_component_kits(
    db: AsyncSession, factory_id: Optional[str] = None, *,
    apply: Optional[bool] = None, limit: int = 50,
) -> Dict[str, Any]:
    """给"被需要、但齐套表里一行领料需求都没有"的自制组件补上依据。

    用的是和拆新单完全相同的算法与写路径：先按这台组件自己的 BOM 逐层展开，
    展不出来再回落到父单快照里 `parent_code` 指向它的行。
    两种都给不出需求的，留在原样并如实报 `still_no_evidence` —— 那是 BOM 缺数据，
    该走工程变更那条线，不该由引擎编一行数量出来。
    删除只针对该工单里 required<=0 的派生行（拆单时抄来的 0），原始 BOM 与 MRP 结果不碰。
    """
    if apply is None:
        apply = RECONCILE_APPLY
    rows = (await db.execute(
        NEEDS_KIT_SQL, {"fid": factory_id, "limit": max(1, limit)}
    )).mappings().all()
    receipt: Dict[str, Any] = {
        "factory_id": factory_id or "全部厂区", "apply": apply, "dry_run": not apply,
        "orders_needing_kit": len(rows), "rebuilt": 0, "material_lines": 0,
        "zero_rows_removed": 0, "still_no_evidence": 0,
        "kits_from_own_explosion": 0, "kits_from_parent_snapshot": 0,
        "parts": [],
    }
    if not rows:
        receipt["status"] = "nothing_to_rebuild"
        return receipt

    for row in rows:
        code = str(row["product_id"])
        kit: List[Dict[str, Any]] = []
        from_own_bom = False
        try:
            own = await explode_requirement(
                db, str(row["factory_id"]), code, int(row["planned_qty"] or 0))
            kit = _from_explosion(own, exclude_code=code)
            from_own_bom = any(float(l["required_qty"]) > 0 for l in kit)
        except Exception:  # noqa: BLE001 - 展开失败照旧回落，报数不报假齐套
            from_own_bom = False
        if not from_own_bom:
            snap = (await db.execute(
                SNAPSHOT_SQL, {"wo_id": str(row["parent_work_order_id"])}
            )).mappings().all()
            kids = [dict(s) for s in snap if str(s.get("parent_code") or "") == code]
            kit = _from_snapshot(kids, base_level=int(row["parent_level"] or 0))
        if not any(float(l["required_qty"]) > 0 for l in kit):
            receipt["still_no_evidence"] += 1
            if len(receipt["parts"]) < 10:
                receipt["parts"].append({
                    "work_order_code": str(row["work_order_code"]), "product_id": code,
                    "reason": "这台组件在 BOM 镜像里没有下层结构（缺数据，不是不缺料）",
                })
            continue
        if from_own_bom:
            receipt["kits_from_own_explosion"] += 1
        else:
            receipt["kits_from_parent_snapshot"] += 1
        if apply:
            deleted = await db.execute(text("""
                DELETE FROM work_order_materials
                WHERE work_order_id = :wid AND COALESCE(required_qty, 0) <= 0
            """), {"wid": str(row["id"])})
            receipt["zero_rows_removed"] += int(deleted.rowcount or 0)
        receipt["material_lines"] += await _write_kit_lines(
            db, child_id=str(row["id"]), kit_lines=kit, apply=apply, receipt=receipt)
        receipt["rebuilt"] += 1

    if apply:
        await db.commit()
    else:
        await db.rollback()
    receipt["status"] = "ok"
    receipt["message"] = (
        f"{'补写' if apply else '预演补写'} {receipt['rebuilt']} 张组件单的领料行"
        f"（{receipt['material_lines']} 行，其中 {receipt['kits_from_own_explosion']} 张来自自己的 BOM、"
        f"{receipt['kits_from_parent_snapshot']} 张来自父单快照）；"
        f"{receipt['still_no_evidence']} 张厂里根本没有它的下层结构，按 BOM 缺失报出")
    return receipt

STALE_KIT_SQL = """
WITH o AS (
    SELECT w.id, w.work_order_code, w.product_id, w.planned_qty,
           COALESCE(pp.product_code, p.product_code, w.product_id) AS model,
           -- 选单闸数的是**外购行**：覆盖率、登记深度分档、L2B 说的都是外购缺口那一堆行，
           -- 这里若数全部行（含自制），一张"外购只登记 150 行、自制登记 600 行"的单
           -- 会被当成"已登记到位"永久跳过 —— 实测就是这样卡住了 45 张单。
           COUNT(wm.id) FILTER (WHERE wm.item_type = 'buy') AS kit_lines,
           COALESCE(SUM(wm.shortage_qty) FILTER (WHERE COALESCE(wm.shortage_qty,0) > 0), 0) AS shortage_now
    FROM work_orders w
    LEFT JOIN work_order_materials wm ON wm.work_order_id = w.id
    LEFT JOIN products p ON p.factory_id = w.factory_id
         AND (p.id::text = w.product_id OR p.product_code = w.product_id)
    LEFT JOIN work_orders par ON par.id = w.parent_work_order_id
    LEFT JOIN products pp ON pp.factory_id = par.factory_id
         AND (pp.id::text = par.product_id OR pp.product_code = par.product_id)
    WHERE w.factory_id = :fid AND w.status IN ('pending', 'released', 'in_progress')
      AND w.id NOT LIKE 'wo-vf-%'
    GROUP BY 1, 2, 3, 4, 5
)
SELECT o.id, o.work_order_code, o.model, o.planned_qty, o.kit_lines, o.shortage_now
FROM o
WHERE o.kit_lines <= :max_lines
  -- 零行的单只要有镜像行就补（哪怕只有一层）：它现在的状态是"连一行领料需求都没有"，
  -- 门按 no_kit_evidence 挡着、催料连料号都拿不到 —— 一层结构也比没有强。
  -- 已经有行的单才要求镜像里有 >1 层：那才是"停在旧登记世代"，补的是深度。
  AND EXISTS (SELECT 1 FROM enghub_bom_items e
               WHERE e.factory_id = :fid AND e.product_model = o.model)
  AND (o.kit_lines = 0
       OR EXISTS (SELECT 1 FROM enghub_bom_items e2
                   WHERE e2.factory_id = :fid AND e2.product_model = o.model AND e2.level > 1))
ORDER BY o.kit_lines ASC
LIMIT :limit
"""

EXISTING_CODES_SQL = """
    SELECT DISTINCT material_code FROM work_order_materials WHERE work_order_id = :wid
"""

KIT_REUPGRADE_APPLY = os.getenv("ENGINE_KIT_REUPGRADE_APPLY", "false").strip().lower() in ("1", "true", "yes", "on")
KIT_REUPGRADE_MAX_LINES = 400


def _kind_of(ledger_rows: int) -> str:
    """这张单的补登属于哪种：一行都没有=从零登记，有但不够=补到多层。

    分开的理由：一行都没有的单现在被 `no_kit_evidence` 挡在门外，催料连料号都拿不到；
    它和"登记了一半"的单需要同步做，但读的人得知道补的是哪种。
    """
    return "从零登记" if int(ledger_rows or 0) == 0 else "补到多层"


async def reupgrade_stale_kit_lines(
    db: AsyncSession, factory_id: str, *, apply: Optional[bool] = None, limit: int = 20,
    max_lines: int = 400,
) -> Dict[str, Any]:
    """把齐套表登记不足的工单**补到多层结构**，一行老的都不动。

    候选=外购需求行数 ≤ `max_lines` 的在流程单（含一行都没有的那批）。

    为什么要补：70 张可比单里 64 张的领料行还停在 1-20 行（同机种按多层展开登记过的能到 680 行、
    深 9 层）。齐套表只看得到一小截结构，`台账缺口行覆盖率` 与瓶颈件一致率就被封顶 —— 判据读起来像
    "引擎不准"，实际是台账没跟上。

    `max_lines` 是选单的那道闸：20（默认）只捞"停在旧世代"的薄单；放到 80 就同时捞
    "看见了结构、但只登记了一小截"的单 —— 10-08 实测覆盖率 0.30（引擎 967 件缺口 vs 台账 290 行）
    差的就是这一档。写入规则一模一样，还是只加不改不删。

    三条硬规矩：
    ① **只加不改不删**：已有的料号一律跳过（不重写 required/shortage），所以缺料只会因为看见更多行
       而变多、不会因为这次补登而变少 —— 齐套门不会因为这次写入而放松；
    ② 数量口径沿用 `_from_explosion` 那一条（required=毛需求、shortage=低层码净需求），
       不在这里另发明一套；毛/净之争要改的是原口径，不是这次补登；
    ③ 每张单最多补 `KIT_REUPGRADE_MAX_LINES` 行（磁盘寿命），默认只预演，
       落库要显式开 ENGINE_KIT_REUPGRADE_APPLY=true 或调用时传 apply=True。
    """
    if apply is None:
        apply = KIT_REUPGRADE_APPLY
    rows = (await db.execute(text(STALE_KIT_SQL), {
        "fid": factory_id, "limit": max(1, int(limit)),
        "max_lines": max(1, min(800, int(max_lines)))})).mappings().all()
    receipt: Dict[str, Any] = {
        "factory_id": factory_id, "apply": apply, "dry_run": not apply,
        "orders_stale": len(rows), "orders_upgraded": 0, "orders_from_zero": 0,
        "lines_added": 0,
        "lines_skipped_existing": 0, "lines_skipped_zero": 0, "orders_no_structure": 0,
        "codes_before_total": 0, "codes_after_total": 0, "parts": [],
    }
    for row in rows:
        wid = str(row["id"])
        model = str(row["model"] or "")
        units = int(row["planned_qty"] or 0) or 1
        have = {str(c["material_code"]) for c in (await db.execute(
            text(EXISTING_CODES_SQL), {"wid": wid})).mappings().all()}
        codes_before = len(have)
        receipt["codes_before_total"] += codes_before
        try:
            own = await explode_requirement(db, factory_id, model, units)
        except Exception:  # noqa: BLE001 - 展开失败就报缺依据，不落半行数据
            own = None
        new_lines: List[Dict[str, Any]] = []
        for line in ((own or {}).get("lines") or []):
            code = str(line.get("material_code") or "")
            if not code or code == model:
                continue
            if float(line.get("required_qty") or 0) <= 0:
                receipt["lines_skipped_zero"] += 1
                continue
            if code in have:
                receipt["lines_skipped_existing"] += 1
                continue
            have.add(code)
            new_lines.append({
                "material_code": code,
                "material_name": line.get("material_name") or code,
                "unit": line.get("unit"),
                "required_qty": float(line.get("required_qty") or 0),
                "available_qty": float(line.get("on_hand_qty") or 0),
                "allocated_qty": float(line.get("allocated_qty") or 0),
                "shortage_qty": float(line.get("net_qty") or 0),
                "level": max(1, int(line.get("level") or 1)),
                "item_type": line.get("item_type"),
            })
            if len(new_lines) >= KIT_REUPGRADE_MAX_LINES:
                break
        if not new_lines:
            receipt["orders_no_structure"] += 1
            continue
        written = await _write_kit_lines(db, child_id=wid, kit_lines=new_lines,
                                        apply=apply, receipt=receipt)
        receipt["lines_added"] += written
        receipt["orders_upgraded"] += 1
        receipt["orders_from_zero"] += int(_kind_of(int(row["kit_lines"] or 0)) == "从零登记")
        receipt["codes_after_total"] += codes_before + written
        if len(receipt["parts"]) < 8:
            receipt["parts"].append({"work_order_code": str(row["work_order_code"]),
                                     "model": model, "lines_before": len(have) - written,
                                     "lines_added": written})
    if apply:
        await db.commit()
    else:
        await db.rollback()
    receipt["status"] = "ok"
    receipt["message"] = (
        f"{'补登' if apply else '预演补登'} {receipt['orders_upgraded']}/{receipt['orders_stale']} 张"
        f"（其中 {receipt['orders_from_zero']} 张原本一行外购需求都没有）"
        f"，新增 {receipt['lines_added']} 行"
        f"（跳过已在表里的 {receipt['lines_skipped_existing']} 行、需求为 0 的 {receipt['lines_skipped_zero']} 行）；"
        "只加不改不删 —— 齐套门不会因为补登而放松")
    return receipt
