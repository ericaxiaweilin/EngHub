"""催购动作 → 请购草稿：给推演一个"人能点一下"的落点。

为什么要这一份（#63）：引擎每轮都能算出"向谁催哪个料、催到几天、要多少件"，
但这些数只活在待办正文的一句话里 —— 现场要采纳得有人照抄进采购单。
10-09 实测：近 30 天被点名的 4 个瓶颈料号（RM-ELEC-036/068/101/110）在
purchase_orders / purchase_requests / purchase_requisitions 里 **0 条记录**，
所以"这个动作想过 63 次、没人做过"不是推测，是查出来的。

两条硬规矩（不遵守就等于自己给自己造证据）：
1. 草稿一律 `source='simulation_recommendation'`、`created_by='virtual_factory'`、
   `auto_approved=FALSE`、`status='pending'` —— 它是**等人批的申请**，不是采购单，
   也不会被任何后台任务转成 PO（`auto-po` 只接受显式传入的 pr_id，没有批处理）。
2. 引擎自己落的草稿**不能算进"有人动过"的证据**。`virtual_run.FOLLOWTHROUGH_SQL`
   原来按料号数 requisition，不分成因 —— 加了这一类草稿后若不排除，
   引擎写一批草稿就把自己上一轮"建议没落地"的判词刷成"建议有下落"。
   那份 SQL 里配套写了排除条件，并把草稿数单列成一个字段给人看。

只写新增行，不改不删已有采购数据；apply=False 时只回报"会写什么"。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Dict, List

# 一次最多落几张：瓶颈件通常 4~5 个，20 张足够覆盖，又防止一轮把请购表灌满。
MAX_DRAFTS_PER_RUN = 20
DRAFT_SOURCE = "simulation_recommendation"
DRAFT_ACTOR = "virtual_factory"

# 这些状态还"活着"：同一条推荐重跑时不重复开草稿（幂等的依据就是这一句）。
ACTIVE_SQL_STATUSES = ("pending", "approved", "ordered", "converted")

# source_id 那一列是 varchar(50)，而推荐的 task_key 是"政策名|指纹|料号清单"，能到一两百字。
# 所以草稿上写的是它的**短引用**（sha1 前 12 位），幂等靠主键（同一(推荐,料号)永远同一个 id）
# 而不是靠这个串；要从草稿跳回推荐卡，看的是卡正文里列出的单号。
def short_ref(task_key: str) -> str:
    return hashlib.sha1(str(task_key or "").encode("utf-8")).hexdigest()[:12]


def plan_drafts(actions: List[Dict[str, Any]], *, existing_keys: List[str],
                master: Dict[str, Dict[str, Any]], task_key: str,
                limit: int = MAX_DRAFTS_PER_RUN) -> Dict[str, Any]:
    ref = short_ref(task_key)
    """纯函数：从一轮推荐的动作里算出"该开哪几张草稿"，以及每条被跳过的原因。

    判据全部摊在这里，不动库，好测：
    · 只给催购动作开（分批/加人那些动作的落点不是采购）；
    · 没有供应商就不开 —— 催购没有对象，那条动作本来就该是"补主数据"；
    · 主档查不到这个料号也不开 —— 采购员拿到单子也没法发；
    · 同一条推荐（task_key）+ 同一个料号已经有一张活着的草稿就不再开。
    """
    rows: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    seen_here: set = set()
    for a in actions or []:
        if str(a.get("type") or "") != "expedite_purchase":
            continue
        code = str(a.get("material_code") or "").strip()
        qty = float(a.get("qty_short") or 0)
        supplier = str(a.get("supplier") or "").strip()
        key = f"{ref}|{code}"
        if not code:
            continue
        if key in seen_here:
            # 同一条推荐里同一个料号被多个场景点名，也只开一张（草稿不是场景维度的东西）
            skipped.append({"material_code": code, "why": "本轮同一个料号已排过一张"})
            continue
        seen_here.add(key)
        if key in set(existing_keys or []):
            skipped.append({"material_code": code, "why": "这条推荐已有活着的草稿，不重复开"})
            continue
        if qty <= 0:
            skipped.append({"material_code": code, "why": "缺口件数不是正数"})
            continue
        if not supplier:
            skipped.append({"material_code": code,
                            "why": "没有供应商：催购没有对象（该走补主数据）"})
            continue
        m = master.get(code)
        if m is None:
            skipped.append({"material_code": code, "why": "materials 里没有这个料号的主档"})
            continue
        if len(rows) >= limit:
            skipped.append({"material_code": code, "why": f"单轮上限 {limit} 张"})
            continue
        rows.append({
            "material_code": code,
            "material_name": str(m.get("material_name") or ""),
            "material_id": str(m.get("id")) if m.get("id") else None,
            "qty": int(qty),
            "required_date": _date_of(a),
            "lead_time_days": int(a.get("target_lead_days") or 0) or None,
            "supplier_name": supplier,
            "priority": "URGENT" if "暴雨" in str(a.get("scenario") or "") else "HIGH",
            "source_id": key,
            "recommendation_ref": ref,
            # 依据旗标跟着草稿走：采购员看单子时要知道"这个提前期是台账说的还是实测的"
            "evidence_flags": a.get("evidence_flags") or [],
            "model_code": str(a.get("model_code") or ""),
            "scenario": str(a.get("scenario") or ""),
            "order_by_date": str(a.get("order_by_date") or ""),
        })
    return {"rows": rows, "skipped": skipped,
            "would_write": len(rows), "skipped_count": len(skipped)}


def _date_of(action: Dict[str, Any]):
    """到货目标日：优先用动作自己给的，缺了就按下单日 + 目标提前期推。"""
    for field in ("required_arrival_date", "due_date"):
        raw = str(action.get(field) or "").strip()
        if raw:
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                continue
    lead = int(action.get("target_lead_days") or 0)
    order_by = str(action.get("order_by_date") or "").strip()
    if lead and order_by:
        try:
            from datetime import timedelta

            return date.fromisoformat(order_by[:10]) + timedelta(days=lead)
        except ValueError:
            return None
    return None


def draft_ids(task_key: str, material_code: str) -> tuple:
    """(主键, 单号)：都由 (推荐, 料号) 决定 —— 同一条推荐重跑同一个料号永远撞在同一个
    主键上，于是幂等是数据库保证的（ON CONFLICT DO NOTHING），不是"先查后写"赌出来的。"""
    tail = hashlib.sha1(f"{task_key}|{material_code}".encode("utf-8")).hexdigest()
    return f"sim-{tail[:24]}", f"PR-SIM-{tail[:8].upper()}"


async def sync_drafts(db, factory_id: str, *, task_key: str,
                      actions: List[Dict[str, Any]], apply: bool = False,
                      limit: int = MAX_DRAFTS_PER_RUN) -> Dict[str, Any]:
    """把一轮推荐里的催购动作落成请购草稿。apply=False 只回报"会写什么"。"""
    from sqlalchemy import text

    codes = sorted({str(a.get("material_code") or "")
                    for a in (actions or [])
                    if str(a.get("type") or "") == "expedite_purchase"})
    codes = [c for c in codes if c]
    if not codes:
        return {"would_write": 0, "written": 0, "skipped": [], "skipped_count": 0,
                "apply": apply, "task_key": task_key, "existing_drafts": 0,
                "note": "本轮推荐没有点名到催购料号，没有可落的草稿"}

    existing = (await db.execute(text("""
        SELECT source_id FROM purchase_requisitions
        WHERE factory_id = :fid AND source = :src
          AND material_code = ANY(CAST(:codes AS text[]))
          AND LOWER(COALESCE(status, '')) = ANY(CAST(:st AS text[]))
    """), {"fid": factory_id, "src": DRAFT_SOURCE, "codes": codes,
           "st": list(ACTIVE_SQL_STATUSES)})).scalars().all()
    # 只把"同一料号上活着的草稿"的 source_id 交给判据：判据按 {短引用}|{料号} 整串比对，
    # 别的推荐开的草稿引用不同，不会把这一轮的幂等判成"已经有了"。
    keys = [str(k) for k in existing]

    masters = (await db.execute(text("""
        SELECT id, material_code, material_name
        FROM materials WHERE factory_id = :fid AND material_code = ANY(CAST(:codes AS text[]))
    """), {"fid": factory_id, "codes": codes})).mappings().all()
    master = {str(r["material_code"]): dict(r) for r in masters}

    plan = plan_drafts(actions, existing_keys=keys, master=master,
                       task_key=task_key, limit=limit)
    out = {"would_write": plan["would_write"], "written": 0,
           "skipped": plan["skipped"], "skipped_count": plan["skipped_count"],
           "existing_drafts": len(keys), "apply": apply, "task_key": task_key}
    if not apply or not plan["rows"]:
        out["rows"] = plan["rows"]
        out["already_there"] = 0
        out["note"] = ("apply=false，只算不写" if not apply
                       else "本轮没有可落的草稿：每条催购都被上面的原因挡下了")
        return out

    inserted = 0
    for r in plan["rows"]:
        pr_id, pr_code = draft_ids(task_key, r["material_code"])
        res = await db.execute(text("""
            INSERT INTO purchase_requisitions
              (id, factory_id, pr_code, source, source_id, material_code, material_name,
               material_id, qty, unit, required_date, status, auto_approved,
               shortage_qty, priority, lead_time_days, created_by, created_at, updated_at)
            VALUES (:id, :fid, :code, :src, :sid, :mc, :mn, :mid, :qty, 'PCS', :rd,
                    'pending', FALSE, :shortage, :prio, :lead, :by, NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
        """), {
            "id": pr_id, "fid": factory_id, "code": pr_code,
            "src": DRAFT_SOURCE, "sid": r["source_id"], "mc": r["material_code"],
            "mn": r["material_name"], "mid": r["material_id"], "qty": r["qty"],
            # asyncpg 按用法推参数类型：numeric 的 qty 和 integer 的 shortage_qty 不能共用一个
            # 绑定名（实测报 inconsistent types deduced for parameter），分开绑。
            "shortage": r["qty"],
            "rd": r["required_date"], "prio": r["priority"], "lead": r["lead_time_days"],
            "by": DRAFT_ACTOR,
        })
        inserted += int(res.rowcount or 0)
    await db.commit()
    out["written"] = inserted
    # 撞了主键 = 这条推荐的这张草稿本来就在，不是失败；如实分开报，别把"已存在"记成"新写"
    out["already_there"] = plan["would_write"] - inserted
    out["drafts"] = [{"pr_code": draft_ids(task_key, r["material_code"])[1],
                      "material_code": r["material_code"], "qty": r["qty"],
                      "evidence_flags": r["evidence_flags"]} for r in plan["rows"]]
    return out


def decision_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把草稿按"人表态了没有"分堆：等人批 / 人已批 / 人已拒 / 已转单。

    批与拒必须由**人的账号**写出来才算表态：`auto_approved=TRUE` 或
    approved_by 落在机器账号里的（system / pending_manual / virtual_factory…）
    都不算 —— 那是系统在收尾，不是厂里对引擎的态度（与 L3 采纳率同一把尺）。
    """
    machine = {"system", "virtual_factory", "virtual_factory_scenario", "pending_manual",
               "night-watch", "ai_assistant", "procurement_agent"}
    buckets: Dict[str, Any] = {"waiting": 0, "adopted_by_human": 0,
                               "rejected_by_human": 0, "closed_by_machine": 0}
    detail: List[Dict[str, Any]] = []
    for r in rows or []:
        status = str(r.get("status") or "").lower()
        actor = str(r.get("approved_by") or "").strip()
        if status == "pending":
            buckets["waiting"] += 1
            label = "等人批"
        elif status in ("rejected", "cancelled"):
            if actor and actor not in machine:
                buckets["rejected_by_human"] += 1
                label = "人已拒"
            else:
                buckets["closed_by_machine"] += 1
                label = "机器关掉（没人表态）"
        else:
            if actor and actor not in machine and not bool(r.get("auto_approved")):
                buckets["adopted_by_human"] += 1
                label = "人已批"
            else:
                buckets["closed_by_machine"] += 1
                label = "系统自己转的（没人表态）"
        detail.append({"pr_code": r.get("pr_code"), "material_code": r.get("material_code"),
                       "status": status, "actor": actor or None, "reads_as": label})
    return {**buckets, "total": len(rows or []), "detail": detail[:20]}
