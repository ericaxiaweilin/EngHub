"""虚假产出冲回：没有领料依据却入了库的半成品，按原凭证一对一反向过账。

判据是两条同时成立，缺一条都不算（这是关键，不然会把数据缺口当成造假来冲）：
① 齐套表里没有任何带需求量的物料行（`no_kit_evidence`，与就绪门同一判据）；
② 这张单**没有任何领料流水**（production_out）—— 也就是它投入为零。

两条同时成立却有良品报工、还有完工入库，就是"从没有过的料做出了成品"。
这些半成品入库后会让父件"看起来已被覆盖"，把真实缺口藏起来（10-05 已清过一次 948 件）。

三条边界写死在这里：
- **有领料流水的单绝不碰**：实测 6 张 master（WO-VF-0809-*）没有齐套行但确实领了料，
  那是快照缺行（#46 的数据缺口），不是造假 —— 按①就冲会把数据问题冲成经营问题。
- **只冲还在那儿的部分**：按原 production_in 逐笔反向，冲到该批次当前可用量为止；
  差额如实写"已被下游领走 N 件，冲不回"，不拿负库存冒充平账。
- **报工不删只标作废**（is_undone + undone_by/at）：执行流水是仿真历史，
  删了就没人知道当初为什么认为它完工了。

默认只出预演清单（`apply=false`）；真要动库存得显式带 apply，并且先把受影响行导出 CSV。
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.wms_architecture.movements import apply_movement
from core.wms.inventory import TransactionType

_logger = logging.getLogger(__name__)

BACKUP_DIR = os.getenv("FAKE_OUTPUT_BACKUP_DIR", "/tmp")
OPERATOR = os.getenv("FAKE_OUTPUT_OPERATOR", "qoder-agent")

# 候选单：有良品报工、没有带需求量的齐套行、也没有任何领料流水
SCOPE_SQL = text("""
    WITH produced AS (
        SELECT pr.work_order_id, sum(COALESCE(pr.good_qty, 0)) AS good_qty, count(*) AS reports
        FROM production_reports pr
        WHERE COALESCE(pr.is_undone, false) = false
        GROUP BY pr.work_order_id
    ), issued AS (
        SELECT t.work_order_id, count(*) AS issue_lines,
               COALESCE(sum(t.quantity), 0) AS issued_qty
        FROM inventory_transactions t
        WHERE t.transaction_type = 'production_out' AND t.work_order_id IS NOT NULL
        GROUP BY t.work_order_id
    ), kit AS (
        SELECT m.work_order_id,
               count(*) FILTER (WHERE COALESCE(m.required_qty, 0) > 0) AS req_lines
        FROM work_order_materials m GROUP BY m.work_order_id
    )
    SELECT w.id AS work_order_id, w.work_order_code, w.wo_type, w.status,
           w.product_id, w.planned_qty, w.completed_qty, w.good_qty, w.created_by,
           p.good_qty AS reported_good, p.reports AS report_lines,
           COALESCE(k.req_lines, 0) AS kit_req_lines,
           COALESCE(i.issue_lines, 0) AS issue_lines, COALESCE(i.issued_qty, 0) AS issued_qty
    FROM work_orders w
    JOIN produced p ON p.work_order_id = w.id
    LEFT JOIN kit k ON k.work_order_id = w.id
    LEFT JOIN issued i ON i.work_order_id = w.id
    WHERE w.factory_id = :fid
      AND w.status IN ('completed', 'in_progress')
      AND p.good_qty > 0
      AND COALESCE(k.req_lines, 0) = 0
    ORDER BY w.status = 'completed' DESC, p.good_qty DESC, w.work_order_code
    LIMIT :lim
""")

# 这张单当初入库了哪些批次、各多少件（冲回按这一笔一笔反着记）
INBOUND_SQL = text("""
    SELECT t.id AS txn_id, t.inventory_id, t.material_id, t.batch_code,
           t.quantity, t.created_at, i.material_code, i.factory_id,
           COALESCE(i.available_qty, 0) AS now_available, COALESCE(i.total_qty, 0) AS now_total
    FROM inventory_transactions t
    LEFT JOIN inventory i ON i.id = t.inventory_id
    WHERE t.work_order_id = :wo_id AND t.transaction_type = 'production_in'
    ORDER BY t.created_at
""")

# 缺口只由权威刷新（snapshot_supply，单份冲抵）算，这里不另写一份分配模型。
# 要看"虚假件藏了多少缺口"，就用刷新前后的差值量出来，不是推出来。
SHORTAGE_VIEW_SQL = text("""
    SELECT COALESCE(ROUND(SUM(GREATEST(COALESCE(m.shortage_qty,0),0))::numeric, 3), 0) AS shortage_qty,
           count(*) FILTER (WHERE GREATEST(COALESCE(m.shortage_qty,0),0) > 0) AS short_rows,
           count(*) AS lines
    FROM work_order_materials m
    JOIN work_orders w ON w.id = m.work_order_id
    WHERE w.factory_id = :fid AND w.wo_type = 'master' AND COALESCE(m.required_qty, 0) > 0
      AND m.material_code = ANY(CAST(:codes AS text[]))
""")


async def shortage_view(db: AsyncSession, factory_id: str, codes: List[str]) -> Dict[str, Any]:
    """这批料号在主工单齐套表上的缺口读数（由 snapshot_supply 维护，这里只读）。"""
    if not codes:
        return {"shortage_qty": 0.0, "short_rows": 0, "lines": 0}
    row = (await db.execute(SHORTAGE_VIEW_SQL,
                            {"fid": factory_id, "codes": list(codes)})).mappings().first()
    return dict(row or {"shortage_qty": 0.0, "short_rows": 0, "lines": 0})


def classify(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """分成"该冲的"和"绝不碰的"，判据全部来自 SQL 已带回的计数，不在这里再猜。"""
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "revert_stock": [],        # 零领料 + 有入库 → 反向过账 + 退单
        "revert_status_only": [],  # 零领料 + 无入库 + 已标完工 → 只退状态与报工
        "execution_history": [],   # 零领料 + 无入库 + 仍在制 → 只列不动（仿真执行史）
        "protected_has_issues": [],  # 有领料流水：快照缺行 ≠ 造假，绝不冲
    }
    for r in rows:
        if int(r.get("issue_lines") or 0) > 0:
            buckets["protected_has_issues"].append(r)
        elif int(r.get("inbound_lines") or 0) > 0:
            buckets["revert_stock"].append(r)
        elif str(r.get("status")) == "completed":
            buckets["revert_status_only"].append(r)
        else:
            buckets["execution_history"].append(r)
    return buckets


async def scan(db: AsyncSession, factory_id: str, *, limit: int = 200) -> Dict[str, Any]:
    """列出候选单与各自该走哪条路，附冲回会影响到的父层行。"""
    rows = [dict(r) for r in (await db.execute(
        SCOPE_SQL, {"fid": factory_id, "lim": limit})).mappings().all()]
    for r in rows:
        inbound = [dict(x) for x in (await db.execute(
            INBOUND_SQL, {"wo_id": str(r["work_order_id"])})).mappings().all()]
        r["inbound_lines"] = len(inbound)
        r["inbound_qty"] = round(sum(float(x["quantity"] or 0) for x in inbound), 3)
        r["revertible_qty"] = round(sum(min(float(x["quantity"] or 0),
                                            float(x["now_available"] or 0)) for x in inbound), 3)
        r["inbound"] = inbound

    buckets = classify(rows)
    codes = sorted({str(x["material_code"]) for r in buckets["revert_stock"]
                    for x in r["inbound"] if x.get("material_code")})

    return {
        "factory_id": factory_id,
        "candidates": len(rows),
        "counts": {k: len(v) for k, v in buckets.items()},
        "totals": {
            "reported_good": round(sum(float(r["reported_good"] or 0) for r in rows), 3),
            "inbound_qty": round(sum(float(r["inbound_qty"] or 0) for r in buckets["revert_stock"]), 3),
            "revertible_qty": round(sum(float(r["revertible_qty"] or 0)
                                        for r in buckets["revert_stock"]), 3),
        },
        "affected_material_codes": codes,
        "shortage_now": await shortage_view(db, factory_id, codes),
        "orders": buckets,
        "criterion": ("同时满足 ①齐套表没有带需求量的物料行 ②这张单没有任何领料流水 才算虚假产出；"
                      "只有①有②没有的单子是快照缺数据（#46），一律不冲。"),
        "note": ("冲回只动还在那儿的部分（按原入库批次逐笔反向、上限为该批次当前可用量）；"
                 "差额如实报「已被下游领走，冲不回」，不记负库存。"
                 "冲完后由 snapshot_supply 重算缺口，被掩盖的缺口以刷新前后的差值为准 —— "
                 "这里不另写一份库存分配模型。"),
    }


def _write_backup(path: str, rows: List[Dict[str, Any]]) -> str:
    fields = ["work_order_code", "work_order_id", "status", "wo_type", "product_id",
              "reported_good", "inbound_qty", "revertible_qty", "txn_id", "inventory_id",
              "batch_code", "quantity", "now_available"]
    try:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return path
    except OSError as exc:  # 备份写不出去就别动库
        raise RuntimeError(f"备份写入失败，已中止冲回：{exc}") from exc


async def revert(db: AsyncSession, factory_id: str, *, apply: bool = False,
                 limit: int = 200) -> Dict[str, Any]:
    """按 scan 的判定执行冲回；apply=false 只把计划算出来。"""
    report = await scan(db, factory_id, limit=limit)
    targets = report["orders"]["revert_stock"] + report["orders"]["revert_status_only"]
    receipt: Dict[str, Any] = {
        "factory_id": factory_id, "apply": apply,
        "planned_orders": len(targets),
        "planned_stock_moves": report["counts"]["revert_stock"],
        "planned_qty": report["totals"]["revertible_qty"],
        "protected_orders": report["counts"]["protected_has_issues"],
        "execution_history_untouched": report["counts"]["execution_history"],
        "backup": None, "reverted": [], "errors": [],
        "criterion": report["criterion"],
    }
    if not apply:
        receipt["status"] = "preview_only"
        receipt["shortage_now"] = report["shortage_now"]
        receipt["message"] = (f"预演：{receipt['planned_orders']} 张单、"
                              f"{receipt['planned_qty']:g} 件半成品可冲回；"
                              f"另有 {receipt['protected_orders']} 张有领料流水的单被保护住。"
                              f"要动库存得显式带 apply=true。")
        return receipt

    flat: List[Dict[str, Any]] = []
    for order in targets:
        for txn in order["inbound"] or [{}]:
            flat.append({**{k: order[k] for k in (
                "work_order_code", "work_order_id", "status", "wo_type", "product_id",
                "reported_good", "inbound_qty", "revertible_qty")}, **txn})
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    receipt["backup"] = _write_backup(
        os.path.join(BACKUP_DIR, f"fake_output_revert_{factory_id}_{stamp}.csv"), flat)

    from database.models import Inventory

    for order in targets:
        moves: List[Dict[str, Any]] = []
        for txn in order["inbound"]:
            qty = float(txn["quantity"] or 0)
            if qty <= 0:
                continue
            inv = await db.get(Inventory, str(txn["inventory_id"]))
            if inv is None:
                receipt["errors"].append({"work_order_code": order["work_order_code"],
                                          "error": f"库存行 {txn['inventory_id']} 已不存在"})
                continue
            take = min(qty, float(inv.available_qty or 0), float(inv.total_qty or 0))
            if take <= 0:
                moves.append({"batch": txn["batch_code"], "wanted": qty, "reversed": 0.0,
                              "unrecoverable": qty,
                              "reason": "该批次已被下游领走或清空，冲不回"})
                continue
            try:
                await apply_movement(
                    db, inventory=inv,
                    transaction_type=TransactionType.ADJUSTMENT_OUT.value,
                    quantity=int(round(take)),
                    reference_type="work_order", reference_id=str(order["work_order_id"]),
                    reference_doc_no=f"REVERT-{order['work_order_code']}"[:50],
                    work_order_id=str(order["work_order_id"]), operator=OPERATOR,
                    remark=(f"虚假产出冲回：该单齐套表无带需求量的物料行、且无任何领料流水"
                            f"（零投入却入库 {qty:g} 件）。原入库凭证 {txn['txn_id']}。"),
                )
            except Exception as exc:  # noqa: BLE001 — 单据级失败不影响其他单
                receipt["errors"].append({"work_order_code": order["work_order_code"],
                                          "error": f"{type(exc).__name__}: {exc}"})
                continue
            moves.append({"batch": txn["batch_code"], "wanted": qty, "reversed": round(take, 3),
                          "unrecoverable": round(qty - take, 3)})

        undone = (await db.execute(text("""
            UPDATE production_reports
            SET is_undone = true, undone_at = NOW(), undone_by = :by,
                remark = COALESCE(remark, '') || ' ｜ 虚假产出作废：无领料依据（零投入产出）'
            WHERE work_order_id = :id AND COALESCE(is_undone, false) = false
        """), {"by": OPERATOR, "id": str(order["work_order_id"])})).rowcount

        status_back = (await db.execute(text("""
            UPDATE work_orders
            SET status = 'pending', completed_qty = 0, good_qty = 0, completed_by = NULL,
                updated_at = NOW()
            WHERE id = :id AND status IN ('completed', 'in_progress')
        """), {"id": str(order["work_order_id"])})).rowcount

        receipt["reverted"].append({
            "work_order_code": order["work_order_code"], "wo_type": order["wo_type"],
            "from_status": order["status"], "product_id": order["product_id"],
            "reported_good": order["reported_good"], "moves": moves,
            "reversed_qty": round(sum(m["reversed"] for m in moves), 3),
            "unrecoverable_qty": round(sum(m.get("unrecoverable", 0) or 0
                                           for m in moves), 3),
            "reports_undone": int(undone or 0), "order_reopened": int(status_back or 0),
        })

    await db.commit()

    codes = report["affected_material_codes"]
    shortage_before = await shortage_view(db, factory_id, codes)

    # 缺口要立刻回到父层快照上，不然冲完库存、齐套表还按旧可用量报"已覆盖"
    from api.services.snapshot_supply import refresh_snapshot_supply

    refresh = await refresh_snapshot_supply(db, factory_id=factory_id)
    shortage_after = await shortage_view(db, factory_id, codes)
    revealed = round(float(shortage_after["shortage_qty"]) - float(shortage_before["shortage_qty"]), 3)

    receipt["status"] = "applied"
    receipt["kit_refresh"] = refresh
    receipt["shortage_before"] = shortage_before
    receipt["shortage_after"] = shortage_after
    receipt["revealed_gap_qty"] = revealed
    receipt["message"] = (f"已冲回 {len(receipt['reverted'])} 张单、"
                          f"{sum(r['reversed_qty'] for r in receipt['reverted']):g} 件半成品；"
                          f"冲不回（已被下游用掉）{sum(r['unrecoverable_qty'] for r in receipt['reverted']):g} 件；"
                          f"重算后父层缺口从 {shortage_before['shortage_qty']:g} 件变成 "
                          f"{shortage_after['shortage_qty']:g} 件（被虚假库存藏起来的 {revealed:g} 件）；"
                          f"备份 {receipt['backup']}")
    return receipt
