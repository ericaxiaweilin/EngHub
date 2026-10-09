"""库存报警落库：让"报过什么警、谁处理的、什么时候消的"成为可回读的对象。

现状（10-09 实测 FAC_MECH_001）：`stock_alerts` **0 行** —— 报警是
`WmsService.get_stock_alerts()` 每次实时算的，算完就丢，所以永远回答不了
"上次那条缺料告警谁处理的、多久处理的"。

而且实时算法本身有两把尺并存，这里**不合并、不选边**，各按各的名字落库：
· `below_reorder_point` —— 按行自己声明的补货点：11,228 行里 **94.7% 的补货点是 1**，
  等于"用到零才算缺"，只有 111 行会报；
· `low_stock_legacy_below_10` —— 代码里写死的 `available_qty < 10`：会报 1,260 行。
同一句"低于安全库存"在这套数据里本来就有三套说法（见 `core/mes/safety_stock_authority.py`
量的 476 / 406 / 4,666，差 11.49 倍），那个"该用哪条线"的问题已经挂给厂里了，
这一格只负责把两种判据各自的结果如实存下来，不代替厂里选一个数。

对账式写入的规矩（这是最容易出事的地方）：**只关本轮真的评估过、且条件已消失的那些**。
本轮没评估到的类型/来源的告警一律不碰 —— 否则一次局部重算会把别人开的告警整批关掉。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

# 报警类型 → 判它的尺是什么（写进 severity/basis，读的人不用猜）
ALERT_KINDS: Tuple[Tuple[str, str, str], ...] = (
    ("zero_stock", "critical", "total_qty <= 0：台账说这个料一件都不剩"),
    ("below_reorder_point", "warning", "available_qty < 行上声明的 reorder_point（该值 94.7% 是 1）"),
    ("low_stock_legacy_below_10", "info", "available_qty < 10：代码里写死的旧阈值，不是厂里声明的"),
    ("available_below_reserved", "critical", "available_qty < reserved_qty：预留比可用还多，账自己矛盾"),
)

KIND_SQL: Dict[str, str] = {
    "zero_stock": """
        SELECT material_id, material_code, batch_code, warehouse_id,
               total_qty AS current_qty, 0 AS threshold_qty, NULL::varchar AS material_name
        FROM inventory WHERE factory_id = :fid AND COALESCE(total_qty,0) <= 0
          AND UPPER(COALESCE(material_code,'')) NOT IN ('NAN','NULL','NONE','NA')""",
    "below_reorder_point": """
        SELECT material_id, material_code, batch_code, warehouse_id,
               available_qty AS current_qty, reorder_point AS threshold_qty
        FROM inventory WHERE factory_id = :fid AND COALESCE(reorder_point,0) > 0
          AND available_qty < reorder_point
          AND UPPER(COALESCE(material_code,'')) NOT IN ('NAN','NULL','NONE','NA')""",
    "low_stock_legacy_below_10": """
        SELECT material_id, material_code, batch_code, warehouse_id,
               available_qty AS current_qty, 10 AS threshold_qty
        FROM inventory WHERE factory_id = :fid AND available_qty > 0 AND available_qty < 10
          AND UPPER(COALESCE(material_code,'')) NOT IN ('NAN','NULL','NONE','NA')""",
    "available_below_reserved": """
        SELECT material_id, material_code, batch_code, warehouse_id,
               available_qty AS current_qty, reserved_qty AS threshold_qty
        FROM inventory WHERE factory_id = :fid
          AND available_qty < COALESCE(reserved_qty,0)""",
}


def _key(kind: str, row: Dict[str, Any]) -> Tuple[Any, ...]:
    """告警的身份 = (类型, 料号, 仓)。

    `stock_alerts` 这张表没有 batch_code 列 —— 所以**同一料号的不同批次会并成一条告警**。
    这是表的限制，不是判据的选择：要按批次报警得先给这张表加列（那要人点头）。
    """
    return (kind, str(row.get("material_id") or ""), str(row.get("warehouse_id") or ""))


def merge_alerts(firing: Dict[str, List[Dict[str, Any]]],
                 open_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """纯函数：把"本轮算出来的告警"和"库里还开着的告警"对一遍，分成新增/续期/关闭。

    关闭只发生在**本轮评估过的类型**里：某类型本轮没跑（查不动、被跳过），
    它已有的告警一条都不许关 —— 一次局部重算不能把别人开的警整批抹掉。
    """
    firing_keys = {_key(k, a) for k, items in (firing or {}).items() for a in items}
    open_keys = {_key(str(r.get("alert_type") or ""), r)
                 for r in (open_rows or []) if str(r.get("status") or "") == "open"}
    evaluated = set((firing or {}).keys())
    new = sorted(firing_keys - open_keys)
    renewed = sorted(firing_keys & open_keys)
    closing = sorted({k for k in (open_keys - firing_keys) if k[0] in evaluated})
    untouched = sorted({k for k in (open_keys - firing_keys) if k[0] not in evaluated})
    return {"to_create": [dict(_payload(k, firing)) for k in new],
            "to_create_count": len(new), "renewed_count": len(renewed),
            "to_close": [{"alert_type": k[0], "material_id": k[1],
                          "warehouse_id": k[2]} for k in closing],
            "to_close_count": len(closing),
            "left_alone_count": len(untouched),
            "note": ("关闭只发生在本轮评估过的类型里；没评估到的类型一条不关"
                     f"（本轮留了 {len(untouched)} 条没碰）")}


def _payload(key: Tuple[Any, ...], firing: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    kind, material_id, warehouse = key
    for a in firing.get(kind, []):
        if _key(kind, a) == key:
            return {"alert_type": kind, "material_id": material_id,
                    "material_code": a.get("material_code"),
                    "material_name": a.get("material_name"),
                    "warehouse_id": warehouse or None,
                    "current_qty": a.get("current_qty"), "threshold_qty": a.get("threshold_qty"),
                    "batch_code": a.get("batch_code"),
                    "severity": dict((k, sev) for k, sev, _b in ALERT_KINDS).get(kind, "warning")}
    return {"alert_type": kind, "material_id": material_id, "warehouse_id": warehouse or None}



def foreign_kinds(seen: Iterable[str]) -> List[str]:
    """表里出现过、但不属于本轮这几把尺的 alert_type —— 有第二把尺在写同一张表的信号。

    为什么要单独探这一件事：`api/services/stock_alert_service.py` 的 `run_alert_check`
    往**同一张** `stock_alerts` 写 `below_safety` / `above_max` / `dead_stock`，
    而它按 material 聚合（不按 material+warehouse）。本服务的收口规矩是
    "只关本轮评估过的类型"，所以那些类型一旦落了库就**永远关不掉** ——
    同一条缺料被两把尺各报一遍，其中一遍没人收口。
    10-09 实测：那三格都挂在 `safety_stock_config`（0 行）上，`if not config: continue`
    直接跳过，所以目前表里只有我这四类（这是巧合活着，不是设计如此）。
    """
    mine = {k for k, _sev, _basis in ALERT_KINDS}
    out = {str(s).strip() for s in (seen or []) if str(s or "").strip()}
    return sorted(out - mine)

async def evaluate(db, factory_id: str) -> Dict[str, Any]:
    """按四把尺各算一遍当前告警。某一格查不动就少这一格，不牵连别的格。"""
    from sqlalchemy import text

    firing: Dict[str, List[Dict[str, Any]]] = {}
    failed: Dict[str, str] = {}
    for kind, _sev, _basis in ALERT_KINDS:
        try:
            rows = (await db.execute(text(KIND_SQL[kind]), {"fid": factory_id})).mappings().all()
            firing[kind] = [dict(r) for r in rows]
        except Exception as exc:  # noqa: BLE001  查不动的格不进 evaluated 集合，也就不会关任何警
            await db.rollback()
            failed[kind] = f"{type(exc).__name__}: {str(exc)[:70]}"
    return {"firing": firing, "counts": {k: len(v) for k, v in firing.items()},
            "failed": failed,
            "basis": {k: b for k, _s, b in ALERT_KINDS}}


async def sync_alerts(db, factory_id: str, *, apply: bool = False) -> Dict[str, Any]:
    """算一遍、和库里开着的对账，然后落库。apply=false 只回报会新增/关闭多少。"""
    from sqlalchemy import text

    ev = await evaluate(db, factory_id)
    open_rows = (await db.execute(text("""
        SELECT alert_type, material_id, warehouse_id, status
        FROM stock_alerts WHERE factory_id = :fid AND LOWER(status) = 'open'"""),
        {"fid": factory_id})).mappings().all()
    plan = merge_alerts(ev["firing"], [dict(r) for r in open_rows])
    out = {"factory_id": factory_id, "counts": ev["counts"], "failed": ev["failed"],
           "basis": ev["basis"], "to_create_count": plan["to_create_count"],
           "to_close_count": plan["to_close_count"], "renewed_count": plan["renewed_count"],
           "left_alone_count": plan["left_alone_count"], "apply": apply, "note": plan["note"]}
    if not apply:
        out["sample_create"] = plan["to_create"][:6]
        return out

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for p in plan["to_create"]:
        await db.execute(text("""
            INSERT INTO stock_alerts (id, factory_id, alert_type, material_id, material_code,
                                      material_name, warehouse_id, current_qty, threshold_qty,
                                      severity, status, remark, created_at)
            VALUES (:id, :fid, :type, :mid, :mc, :mn, :wh, :cur, :thr, :sev, 'open', :rm, :now)
        """), {"id": str(uuid.uuid4()),      # 这张表的 id 是 varchar(36) NOT NULL 且没有默认值
               "fid": factory_id, "type": p["alert_type"], "mid": p["material_id"],
               "mc": p.get("material_code"), "mn": p.get("material_name"),
               "wh": p.get("warehouse_id"),
               "cur": p.get("current_qty"), "thr": p.get("threshold_qty"),
               "sev": p.get("severity"), "now": now,
               "rm": (f"判据：{out['basis'].get(p['alert_type'], '')}"
                      + (f"；涉及批次 {p['batch_code']}" if p.get("batch_code") else ""))})
    for c in plan["to_close"]:
        # 条件消失 ≠ 人处理过：resolved_by 写清是谁关的，采纳率/处理时长才不会被系统收尾冒充人
        await db.execute(text("""
            UPDATE stock_alerts
               SET status = 'resolved', resolved_by = 'system:re-evaluated', resolved_at = :now,
                   remark = COALESCE(remark,'') || ' | 本轮重算条件已不成立，自动消警'
             WHERE factory_id = :fid AND LOWER(status) = 'open'
               AND alert_type = :type
               AND COALESCE(material_id,'') = :mid
               AND COALESCE(warehouse_id,'') = :wh"""),
            {"now": now, "fid": factory_id, "type": c["alert_type"],
             "mid": c["material_id"], "wh": c["warehouse_id"] or ""})
    await db.commit()
    out["created"] = plan["to_create_count"]
    out["closed"] = plan["to_close_count"]
    return out


async def alert_summary(db, factory_id: str) -> Dict[str, Any]:
    """落库后的告警分布：开着多少、按类型/严重度怎么分、谁处理的、多久处理的。"""
    from sqlalchemy import text

    rows = (await db.execute(text("""
        SELECT alert_type, severity,
               COUNT(*) FILTER (WHERE LOWER(status)='open') AS 开着,
               COUNT(*) FILTER (WHERE LOWER(status)='resolved') AS 已消,
               COUNT(*) FILTER (WHERE LOWER(status)='resolved'
                                AND COALESCE(resolved_by,'') NOT LIKE 'system:%') AS 人处理的
        FROM stock_alerts WHERE factory_id = :fid
        GROUP BY 1,2 ORDER BY 1,2"""), {"fid": factory_id})).mappings().all()
    return {"by_kind": [dict(r) for r in rows],
            "note": ("已消里区分'人处理的'与系统重算自动消的：把自动消警读成'人已处理'"
                     "是这台机器最容易自证的地方（与催购草稿那条同源）")}
