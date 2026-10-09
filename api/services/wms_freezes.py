"""质量冻结：让"这批料不许动"成为有对象、有原因、有到期、且**领料真的领不到**的事。

为什么要单独一格（10-09 实测）：`inventory_freezes` 0 行，而且更关键的是 ——
`inventory.status / lock_reason / qualified_status` 这三列**在整个读取侧没有任何一处用到**
（grep 全仓只有两处写入 `status="available"`，没有一处按它过滤）。
也就是说：现在给一批待检料"标记冻结"，领料照样能把它领走 —— 那是装饰品，不是控制。
所以这一格分两半：冻结要有对象，分配路径要真的把它挡在外面。

三态必须分清（和引擎别处同一套语义）：
· active   正在挡领料；
· released 人主动解的（写清谁、为什么放行）；
· expired  到期由系统自动放的 —— 自动放和人工放不能混成一个数，
  否则"质量放行"这件事会被系统的到期动作冒充。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ACTIVE_STATUSES = ("active",)

# 领料/出库分配时用的排除条件：只认 active 且（没到期 或 还没过期）的冻结
BLOCKING_SQL = """
    SELECT f.inventory_id, i.material_id, i.batch_code, i.warehouse_id,
           i.available_qty, f.reason_code, f.reason_text, f.freeze_until, f.frozen_by
    FROM inventory_freezes f
    JOIN inventory i ON i.id = f.inventory_id
    WHERE f.factory_id = :fid
      AND LOWER(f.status) = 'active'
      AND (f.freeze_until IS NULL OR f.freeze_until > :now)
      AND (CAST(:mid AS text) IS NULL OR f.material_id = CAST(:mid AS text))
      AND (CAST(:wid AS text) IS NULL OR i.warehouse_id = CAST(:wid AS text))
"""


def partition_by_status(rows: Sequence[Any]) -> Dict[str, Any]:
    """按行自己说的 status 分"能分配"与"被冻着" —— 不查库。

    为什么分配路径用这个而不是 `blocked_rows`（查 inventory_freezes）：
    · 和写入原语认的是同一件事（`movements.frozen_stock_error` 看 status），
      两处判据必须同形，否则会出现"分配放过了、过账却拒"或反过来；
    · 分配路径本来就把行加载进来了，`status / lock_reason` 就在行上，
      再绕一次 DB 是第二次量同一件事（同名两把尺就是这么长出来的），
      而且现有单测钉住了每条写入路径的查询次数；
    · `freeze()`/`release()` 两边都同步写记录表和行上的锁，对账见 `sync_check`。
    """
    ok: List[Any] = []
    held: List[Any] = []
    held_qty = 0
    reasons: List[str] = []
    for row in rows or []:
        status = str((row.get("status") if isinstance(row, dict)
                      else getattr(row, "status", None)) or "").strip().lower()
        if status == "locked":
            held.append(row)
            held_qty += int((row.get("available_qty") if isinstance(row, dict)
                             else getattr(row, "available_qty", None)) or 0)
            reason = str((row.get("lock_reason") if isinstance(row, dict)
                          else getattr(row, "lock_reason", None)) or "").strip()
            reasons.append(reason or "未填原因码")
        else:
            ok.append(row)
    return {"allocatable": ok, "held": held, "held_rows": len(held), "held_qty": held_qty,
            "held_reasons": sorted(set(reasons))}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def blocked_rows(db, factory_id: str, *, material_id: Optional[str] = None,
                       warehouse_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """当前正在挡领料的库存行（含原因，供调用方把"为什么领不到"说出去）。"""
    from sqlalchemy import text

    rows = (await db.execute(text(BLOCKING_SQL), {
        "fid": factory_id, "now": _now(), "mid": material_id, "wid": warehouse_id})).mappings().all()
    return [dict(r) for r in rows]


async def freeze(db, factory_id: str, inventory_ids: List[str], *, reason_code: str,
                 reason_text: str = "", until: Optional[datetime] = None,
                 actor: str = "system", auto_unfreeze: bool = False,
                 apply: bool = False) -> Dict[str, Any]:
    """冻结若干库存行。apply=false 只回报会冻哪些、已经冻着哪些。"""
    from sqlalchemy import text

    ids = [str(x) for x in (inventory_ids or []) if str(x).strip()]
    if not ids:
        return {"frozen": 0, "already_frozen": 0, "note": "没点名要冻结的库存行"}
    if not (reason_code or "").strip():
        return {"error": "冻结必须有原因码（待检/不合格/事故封存…），否则事后没人知道为什么锁着"}

    existing = {str(r["inventory_id"]) for r in (await db.execute(text("""
        SELECT inventory_id FROM inventory_freezes
        WHERE factory_id = :fid AND LOWER(status) = 'active'
          AND inventory_id = ANY(CAST(:ids AS text[]))"""),
        {"fid": factory_id, "ids": ids})).mappings().all()}
    to_do = [i for i in ids if i not in existing]
    out = {"factory_id": factory_id, "requested": len(ids), "frozen": 0,
           "already_frozen": len(existing), "reason_code": reason_code,
           "apply": apply, "targets": to_do[:20]}
    if not apply or not to_do:
        out["note"] = ("apply=false，只算不写" if not apply
                       else "这些行本来就冻着，不重复冻")
        return out

    now = _now()
    for iid in to_do:
        await db.execute(text("""
            INSERT INTO inventory_freezes (id, factory_id, inventory_id, material_id,
                                           material_code, batch_code, reason_code, reason_text,
                                           freeze_until, status, frozen_by, auto_unfreeze,
                                           prior_status, created_at)
            SELECT gen_random_uuid()::text, :fid, i.id, i.material_id, i.material_code,
                   i.batch_code, :rc, :rt, :until, 'active', :by, :auto,
                   COALESCE(i.status, ''), :now
              FROM inventory i WHERE i.id = :iid
        """), {"fid": factory_id, "rc": reason_code, "rt": reason_text, "until": until,
               "by": actor, "auto": bool(auto_unfreeze), "now": now, "iid": iid})
        # 同时把行本身标上锁：读取侧靠 inventory_freezes 挡分配，
        # 这一列是给界面/报表看的"这行为什么不能动"，两者必须同步（见 status 那格）
        await db.execute(text("""
            UPDATE inventory SET status = 'locked', lock_reason = :rc, locked_at = :now,
                                 updated_at = :now WHERE id = :iid
        """), {"rc": reason_code, "now": now, "iid": iid})
        out["frozen"] += 1
    await db.commit()
    return out


async def release(db, factory_id: str, *, freeze_id: Optional[str] = None,
                  inventory_id: Optional[str] = None, actor: str = "system",
                  note: str = "", kind: str = "released",
                  apply: bool = False) -> Dict[str, Any]:
    """解冻。`kind` 分 released（人放的）/ expired（到期系统放的）—— 两个数不许混。"""
    from sqlalchemy import text

    where = " AND ".join(filter(None, [
        "LOWER(f.status) = 'active'", "f.factory_id = :fid",
        "f.id = :fzid" if freeze_id else None,
        "f.inventory_id = :iid" if inventory_id else None]))
    if not (freeze_id or inventory_id):
        return {"error": "解冻必须点名是哪条冻结或哪个库存行"}
    hits = (await db.execute(text(f"""
        SELECT f.id, f.inventory_id FROM inventory_freezes f WHERE {where}"""),
        {"fid": factory_id, "fzid": freeze_id, "iid": inventory_id})).mappings().all()
    out = {"released": 0, "restored": 0, "status_left_as_is": 0,
           "candidates": len(hits), "kind": kind, "apply": apply}
    if not apply or not hits:
        out["note"] = "apply=false，只算不写" if not apply else "没有活动中的冻结可解"
        return out
    now = _now()
    for h in hits:
        await db.execute(text("""
            UPDATE inventory_freezes
               SET status = :kind, unfrozen_by = :by, unfrozen_at = :now,
                   reason_text = COALESCE(reason_text,'') || :note
             WHERE id = :id"""),
            {"kind": kind, "by": actor, "now": now,
             "note": f" | {kind} by {actor}: {note}" if note else "", "id": h["id"]})
        # 只有这行不再被任何活动冻结挡住时，才把行状态放回 available
        still = (await db.execute(text("""
            SELECT COUNT(*) n FROM inventory_freezes
            WHERE inventory_id = :iid AND LOWER(status) = 'active'"""),
            {"iid": h["inventory_id"]})).scalar()
        if not int(still or 0):
            # 放回它被冻之前那个词；prior_status 为空（这列上线前的老记录）就**不动 status**，
            # 只清锁标记，并把"判不出该放成什么"的条数报出去 —— 不替厂里选词表。
            prior = str((await db.execute(text(
                "SELECT prior_status FROM inventory_freezes WHERE id=:id"),
                {"id": h["id"]})).scalar() or "").strip()
            if prior:
                await db.execute(text("""
                    UPDATE inventory SET status = :ps, lock_reason = NULL,
                           locked_at = NULL, updated_at = :now WHERE id = :iid"""),
                    {"ps": prior, "now": now, "iid": h["inventory_id"]})
                out["restored"] += 1
            else:
                await db.execute(text("""
                    UPDATE inventory SET lock_reason = NULL, locked_at = NULL,
                           updated_at = :now
                     WHERE id = :iid AND LOWER(COALESCE(status,'')) = 'locked'"""),
                    {"now": now, "iid": h["inventory_id"]})
                out["status_left_as_is"] += 1
        out["released"] += 1
    await db.commit()
    return out


async def expire_due(db, factory_id: str, *, apply: bool = False) -> Dict[str, Any]:
    """到期自动放行 —— 只放明确勾了 auto_unfreeze 的，其余继续挡着。"""
    from sqlalchemy import text

    due = (await db.execute(text("""
        SELECT id FROM inventory_freezes
        WHERE factory_id = :fid AND LOWER(status) = 'active' AND auto_unfreeze
          AND freeze_until IS NOT NULL AND freeze_until <= :now"""),
        {"fid": factory_id, "now": _now()})).mappings().all()
    out = {"due": len(due), "expired": 0, "apply": apply}
    if not apply or not due:
        return out
    for d in due:
        await release(db, factory_id, freeze_id=str(d["id"]), actor="system:expiry",
                      note="到期自动放行", kind="expired", apply=True)
        out["expired"] += 1
    return out


# 守卫放在写入原语（movements.frozen_stock_error）里，认的是 inventory.status；
# 所以 freeze/release 必须同时写"冻结记录"和"行上的锁"，两者不同步就是装饰品换了个形式。
# 审计格数的就是这两笔账对不对得上："有活动冻结记录、行却没锁"（领料照样走得掉）
# 与"行锁着、却没有冻结记录"（不知道被谁冻的、什么时候该放）。
def sync_check(active_records: int, locked_rows: int) -> Dict[str, Any]:
    a, l = int(active_records or 0), int(locked_rows or 0)
    return {"active_records": a, "locked_rows": l, "in_sync": a == l,
            "note": ("对得上：每条活动冻结都把行锁住了，没有只锁不记，也没有只记不锁"
                     if a == l else
                     f"对不上：冻结记录 {a} 条 vs 行上锁 {l} 行（差 {l - a}）—— "
                     "要么有人绕过接口直接改了 status，要么写入侧两笔账有一边没写全")}


async def freeze_status(db, factory_id: str) -> Dict[str, Any]:
    from sqlalchemy import text

    rows = (await db.execute(text("""
        SELECT LOWER(COALESCE(status,'')) s, COUNT(*) n,
               COUNT(*) FILTER (WHERE auto_unfreeze) AS 可自动放
        FROM inventory_freezes WHERE factory_id = :fid GROUP BY 1 ORDER BY 1"""),
        {"fid": factory_id})).mappings().all()
    held = await blocked_rows(db, factory_id)
    return {"by_status": [dict(r) for r in rows],
            "currently_blocking": len(held),
            "blocking_qty": sum(int(h.get("available_qty") or 0) for h in held),
            "held": [{"inventory_id": str(h.get("inventory_id")),
                      "material_id": str(h.get("material_id") or ""),
                      "available_qty": int(h.get("available_qty") or 0),
                      "reason_code": str(h.get("reason_code") or ""),
                      "frozen_by": str(h.get("frozen_by") or "")} for h in held[:20]]}
