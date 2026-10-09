"""库位对象化：把 `inventory.location_code` 那串字符变成可挂东西的对象。

为什么这是 WMS 的第一格（10-09 实测）：`locations` 表 **0 行**，而库存台账里
11,232 行有 11,025 行写着库位号（1,165 个不同库位）。也就是说仓库知道自己"在哪个格子"，
但那个格子不是一个对象 —— 没有归属仓库的行、没有容量、没有占用状态、`inventory.location_id`
全空。后果是一串功能整体落不了地：上架没有目标、移库没有 from/to、盘点没有范围、
库位容量校验没有对象，`wms_transfer_requests`/`inventory_counts` 这些表因此永远是 0 行。

口径（三条都不许含糊）：
· 只从**已有台账**派生，不造库位：源是 `inventory` 的 (warehouse_id, location_code) 去重；
· 容量/区域/排层**没声明就留 NULL** —— 库位号 `LOC-LG-100048` 里没有排层信息，
  硬解析出来的是我编的货架结构，不是厂里的（宁可空着，等真档案）；
· 幂等：同一个 (仓库, 库位号) 只有一行；重跑只补新出现的号。
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List

# 一次最多登记多少个库位：1,165 个号，默认 2,000 够一轮跟完，又防异常膨胀写爆。
MAX_LOCATIONS_PER_RUN = 2000

# 非规范值：pandas 的 NaN 一路穿过导入、镜像、落库，最后变成一个"库位"。
# 10-09 实测到 `LOC-LG-NAN` 挂着 35,583,657 件 = 全厂台账件数的 50.1%
# （料号也叫 nan、批次叫 B-LG-NAN）。这种号**不登记成对象** —— 登记等于替脏数据转正，
# 之后所有按库位聚合的读数都会把它当一个真格子。跳过它，并在读数里点名。
def is_sentinel(code: str) -> bool:
    c = str(code or "").strip().upper()
    if not c:
        return True
    parts = [x for x in c.replace("-", "_").split("_") if x]
    return any(p in ("NAN", "NULL", "NONE", "NA") for p in parts)

LEDGER_SQL = """
    SELECT i.warehouse_id, i.location_code,
           COUNT(*) AS line_count,
           COUNT(DISTINCT i.material_code) AS material_count,
           COALESCE(SUM(i.total_qty), 0) AS total_qty
    FROM inventory i
    WHERE i.factory_id = :fid
      AND COALESCE(i.location_code, '') <> ''
      AND i.warehouse_id IS NOT NULL
    GROUP BY 1,2
    ORDER BY line_count DESC
"""


def plan_locations(ledger: List[Dict[str, Any]], *, existing_codes: List[str],
                   warehouse_names: Dict[str, str],
                   limit: int = MAX_LOCATIONS_PER_RUN) -> Dict[str, Any]:
    """纯函数：从台账聚合行算出"该登记哪些库位"，以及被跳过的原因。"""
    rows: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    seen: set = set()
    have = set(existing_codes or [])
    for item in ledger or []:
        code = str(item.get("location_code") or "").strip()
        wid = str(item.get("warehouse_id") or "").strip()
        if not code:
            continue
        if is_sentinel(code):
            skipped.append({"location_code": code,
                            "why": "非规范库位号（NaN/NULL 一类），登记等于把脏数据转正"})
            continue
        key = f"{wid}|{code}"
        if key in have:
            skipped.append({"location_code": code, "why": "已登记，不重复开"})
            continue
        if key in seen:
            continue
        seen.add(key)
        if len(rows) >= limit:
            skipped.append({"location_code": code, "why": f"单轮上限 {limit} 个"})
            continue
        rows.append({
            "key": key,
            # 主键用哈希：warehouse uuid(36) + "|" + 库位号 拼起来截断会撞号（1165 个号里
            # 前 56 字符完全可能重复），哈希就不撞，而且同一个 (仓库,号) 永远同一个 id。
            "id": "loc-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:24],
            "location_code": code,
            "location_name": code,          # 厂里没给过名字，就不替他起一个
            "warehouse_id": wid,
            "warehouse_name": warehouse_names.get(wid),
            "location_type": "rack",        # 由"库存挂在这个号上"这一事实推出来的最保守归类
            "zone": None, "aisle": None, "rack": None, "level": None,
            "capacity": None,               # 容量没人声明过 —— 留空，不编
            "status": "active",
            "line_count": int(item.get("line_count") or 0),
            "material_count": int(item.get("material_count") or 0),
            "total_qty": float(item.get("total_qty") or 0),
        })
    return {"rows": rows, "skipped": skipped, "would_create": len(rows),
            "skipped_count": len(skipped)}


async def sync_locations(db, factory_id: str, *, apply: bool = False,
                         limit: int = MAX_LOCATIONS_PER_RUN) -> Dict[str, Any]:
    """把台账里出现过的库位登记成对象，并把 `inventory.location_id` 接上。

    apply=False 只回报"会建哪些、多少行会挂上"。只新增，不改不删已有库位档案。
    """
    from sqlalchemy import text

    ledger = (await db.execute(text(LEDGER_SQL), {"fid": factory_id})).mappings().all()
    existing = (await db.execute(text("""
        SELECT warehouse_id, location_code FROM locations
        WHERE warehouse_id IN (SELECT DISTINCT warehouse_id FROM inventory WHERE factory_id = :fid)
    """), {"fid": factory_id})).mappings().all()
    names = (await db.execute(text("""
        SELECT id, warehouse_name FROM warehouses WHERE factory_id = :fid
    """), {"fid": factory_id})).mappings().all()
    plan = plan_locations(
        [dict(r) for r in ledger],
        existing_codes=[f"{r['warehouse_id']}|{r['location_code']}" for r in existing],
        warehouse_names={str(n["id"]): str(n["warehouse_name"]) for n in names},
        limit=limit)

    out: Dict[str, Any] = {"would_create": plan["would_create"], "created": 0,
                           "skipped": plan["skipped"][:8], "skipped_count": plan["skipped_count"],
                           "ledger_location_codes": len(ledger),
                           "already_registered": len(existing), "apply": apply}
    if not apply or not plan["rows"]:
        out["rows"] = plan["rows"][:20]
        out["note"] = ("apply=false，只算不写" if not apply else "没有新库位要登记")
        return out

    for r in plan["rows"]:
        await db.execute(text("""
            INSERT INTO locations (id, location_code, location_name, warehouse_id,
                                   location_type, status, created_at, updated_at)
            VALUES (:id, :code, :name, :wid, :ltype, 'active', NOW(), NOW())
            ON CONFLICT DO NOTHING
        """), {"id": r["id"], "code": r["location_code"],
               "name": r["location_name"], "wid": r["warehouse_id"],
               "ltype": r["location_type"]})
        out["created"] += 1

    # 把台账行的 location_id 接上（现在 0/11232 有值）：库位从"字符串"变成可 JOIN 的对象
    linked = await db.execute(text("""
        UPDATE inventory i
           SET location_id = l.id
          FROM locations l
         WHERE l.location_code = i.location_code
           AND l.warehouse_id = i.warehouse_id
           AND i.factory_id = :fid
           AND COALESCE(i.location_code, '') <> ''
           AND i.location_id IS DISTINCT FROM l.id
    """), {"fid": factory_id})
    await db.commit()
    out["ledger_rows_linked"] = int(linked.rowcount or 0)
    return out


async def location_occupancy(db, factory_id: str, *, limit: int = 12) -> Dict[str, Any]:
    """库位占用读数：每个库位挂了多少料/多少件，以及"有号但没对象"的差额。"""
    from sqlalchemy import text

    rows = (await db.execute(text("""
        SELECT l.location_code, l.warehouse_id,
               COUNT(i.id) AS 行数,
               COUNT(DISTINCT i.material_code) AS 料号数,
               COALESCE(SUM(i.total_qty), 0) AS 件数
        FROM locations l
        LEFT JOIN inventory i ON i.location_id = l.id
        GROUP BY 1,2
        ORDER BY 件数 DESC LIMIT :lim"""),
        {"fid": factory_id, "lim": max(1, min(50, int(limit)))})).mappings().all()
    orphans = (await db.execute(text("""
        SELECT COUNT(*) AS 有库位号但没对象, COUNT(DISTINCT location_code) AS 涉及号
        FROM inventory WHERE factory_id = :fid AND COALESCE(location_code,'') <> ''
          AND location_id IS NULL"""), {"fid": factory_id})).mappings().first()
    return {"top": [dict(r) for r in rows],
            "unlinked": dict(orphans or {}),
            "note": "占用=挂在这个库位上的台账行；没对象=号写了但 locations 里没有行（同步会补）"}
