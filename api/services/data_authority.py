"""仿真输入的唯一数据源台账：每一维只认一个权威出处，没值就说没值。

用户 10-06 的口径：**IE 数据 + HR 人力数据为准**；他口述的线产能只是参考。
仿真的"真实映射"由四件事共同维持 —— 今天多少人出勤、设备状况、排产计划、物料齐套。
这四维里任何一维拿种子数据/示例数据顶替，产出的数字就是在骗自己，
所以这个模块存在的意义就是把"谁在读哪张表、那表今天有没有真值、是不是我们自己灌的"钉成读数。

判据一律来自库里自己声明的字段（`created_by` / `source` / 日期），不是我猜的：
- `standard_operation_times` 22 行：12 行 `created_by=seed_guard`（来自
  `scripts/seed_demo_module_coverage.py`）、10 行 `created_by=virtual_factory`（引擎自己写的）
  → **零行是 IE 给的**，这一维今天等于没有；
- `stations.capacity_per_hour`：28 个工位都有值，但单位没人定义过 ——
  同一行焊接能读成 22 / 44 / 924 / 2,400 台/天，跨 100 倍，所以它**只能当对撞证据，不能当工时来源**；
- `materials.lead_time_days`：31,672 行全填，但只有 8 个不同值（12 天占 22,364 行），
  是批量灌的；供应逻辑读的其实是 `supplier_materials.lead_time_days`（全表 6 行）→ 外购交期这一维基本空；
- `production_reports`：1003 行全部 `created_by=virtual_factory*` → 仿真执行记录，
  **永远不许被当成现场实测**（这是"从报工反推工时"那个错误前提的根）。

清除动作只碰我们自己写进去的东西（`created_by` 是 virtual_factory / seed_guard 的行），
上传的 BOM、engflow 源库、厂里主档一律不动；删之前先落 CSV 备份，回执按 rowcount 计。
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 冒充 IE / 现场实测的自造来源。删它们不是删数据，是把假证据从算式里拿掉。
SYNTHETIC_IE_SOURCES = ("virtual_factory", "seed_guard")

# 容器里只有代码目录是挂载可见的，备份先落容器 /tmp，随后由部署脚本 docker cp 到宿主机备份目录。
# （宿主机 /home/eric 在容器内不可写，直接写会 PermissionError 并把删除动作一起卡在备份之后。）
BACKUP_DIR = os.getenv("DATA_AUTHORITY_BACKUP_DIR", "/tmp")

IE_TIMES_SQL = text("""
    SELECT COALESCE(created_by, '(空)') AS source, COUNT(*) AS rows_in,
           COUNT(DISTINCT product_id) AS products,
           MIN(validity_start)::date AS 起始, MAX(updated_at)::date AS 最后更新
    FROM standard_operation_times
    GROUP BY 1 ORDER BY 2 DESC
""")

ATTENDANCE_SQL = text("""
    SELECT COUNT(*) AS records,
           COUNT(*) FILTER (WHERE status = 'present') AS present,
           COUNT(DISTINCT operator_id) AS people_present,
           MAX(date::date) AS last_attended
    FROM attendance
    WHERE factory_id = :fid AND date::date BETWEEN :frm AND :to
""")

HR_SQL = text("""
    SELECT COUNT(*) AS roster,
           COUNT(*) FILTER (WHERE status = 'active') AS active,
           COUNT(*) FILTER (WHERE status = 'leave') AS on_leave,
           COUNT(DISTINCT station) AS station_labels
    FROM hr_employees WHERE factory_id = :fid
""")

EQUIPMENT_SQL = text("""
    SELECT COUNT(*) AS total,
           COUNT(*) FILTER (WHERE status IN ('running','idle')) AS usable,
           COUNT(*) FILTER (WHERE status = 'maintenance') AS maintenance,
           COUNT(*) FILTER (WHERE status = 'broken') AS broken,
           MAX(updated_at)::date AS status_updated_at
    FROM equipment WHERE factory_id = :fid
""")

PLAN_SQL = text("""
    SELECT s.schedule_code, s.status, s.optimize_for, s.created_at,
           (SELECT COUNT(*) FROM aps_schedule_tasks t WHERE t.schedule_id = s.id) AS task_rows,
           (SELECT COUNT(*) FROM aps_schedule_tasks t WHERE t.schedule_id = s.id
             AND t.duration_basis IS NOT NULL) AS with_basis,
           (SELECT COUNT(DISTINCT t.work_order_id) FROM aps_schedule_tasks t
             WHERE t.schedule_id = s.id) AS orders_covered
    FROM aps_schedules s WHERE s.is_current AND s.factory_id = :fid
""")

KIT_SQL = text("""
    SELECT COUNT(DISTINCT wo.id) AS open_orders,
           COUNT(m.id) FILTER (WHERE COALESCE(m.shortage_qty,0) > 0) AS short_lines,
           COALESCE(SUM(m.shortage_qty) FILTER (WHERE COALESCE(m.shortage_qty,0) > 0), 0) AS shortage_qty,
           COUNT(DISTINCT wo.id) FILTER (WHERE m.work_order_id IS NULL) AS orders_without_kit
    FROM work_orders wo
    LEFT JOIN work_order_materials m ON m.work_order_id = wo.id
    WHERE wo.factory_id = :fid AND wo.wo_type IN ('master','component')
      AND wo.status IN ('pending','released','in_progress')
""")

STATION_RATE_SQL = text("""
    SELECT COUNT(*) AS stations_with_rate, COUNT(DISTINCT capacity_per_hour) AS distinct_values,
           MIN(capacity_per_hour) AS min_rate, MAX(capacity_per_hour) AS max_rate
    FROM stations WHERE factory_id = :fid AND COALESCE(capacity_per_hour,0) > 0
""")

LEAD_TIME_SQL = text("""
    SELECT COUNT(*) AS material_rows,
           COUNT(*) FILTER (WHERE COALESCE(lead_time_days,0) > 0) AS with_lead_time,
           COUNT(DISTINCT lead_time_days) AS distinct_lead_values,
           (SELECT COUNT(*) FROM supplier_materials) AS supplier_binding_rows
    FROM materials
""")

TEMPLATE_HOURS_SQL = text("""
    SELECT COUNT(*) AS step_rows,
           COUNT(*) FILTER (WHERE COALESCE(st.standard_hours,0) > 0) AS with_hours,
           COUNT(DISTINCT rt.id) AS templates,
           MIN(st.created_at)::date AS first_import, MAX(st.created_at)::date AS last_import,
           string_agg(DISTINCT COALESCE(NULLIF(rt.created_by, ''), '(空)'), ', ') AS 声明来源
    FROM routing_template_steps st
    JOIN routing_templates rt ON rt.id::text = st.template_id
    WHERE rt.factory_id = :fid
""")

VIRTUAL_REPORTS_SQL = text("""
    SELECT COUNT(*) AS report_rows,
           COUNT(*) FILTER (WHERE created_by IN ('virtual_factory','virtual_factory_agent')) AS synthetic_rows,
           MAX(created_at)::date AS last_row
    FROM production_reports
""")


def classify(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把 standard_operation_times 按来源分档：IE 给的 / 我们自己造的。"""
    authoritative, synthetic = 0, 0
    by_source: Dict[str, int] = {}
    for row in rows:
        source = str(row.get("source") or "")
        n = int(row.get("rows_in") or 0)
        by_source[source] = n
        if source in SYNTHETIC_IE_SOURCES:
            synthetic += n
        else:
            authoritative += n
    return {
        "ie_rows": authoritative,
        "synthetic_rows": synthetic,
        "by_source": by_source,
        "verdict": ("IE 工时为空：这一维没有任何厂里给的数"
                    if authoritative == 0 else
                    f"IE 核定 {authoritative} 行，可作工时来源；自造 {synthetic} 行不参与计算"),
    }


def attendance_freshness(last_date: Optional[str], today) -> Dict[str, Any]:
    """考勤到今天隔了几天。今天没人打卡，就不许说"今天 1,050 人出勤"。"""
    if not last_date:
        return {"has_data": False, "stale_days": None,
                "verdict": "考勤表这一天没有记录：出勤人数只能按 HR 在册算，且要标'在册≠出勤'"}
    if hasattr(last_date, "date"):
        last_date = last_date.date()
    lag = int((today - last_date).days) if hasattr(last_date, "year") else 0
    return {
        "has_data": True,
        "last_date": str(last_date),
        "stale_days": lag,
        "verdict": ("今天有考勤，按出勤人数算" if lag <= 0 else
                    f"考勤停在 {last_date}，比今天落后 {lag} 天：出勤只能按在册估算并标注"),
    }


def dirty_inventory_row(kind: str, count: int, why: str, action: str) -> Dict[str, Any]:
    return {"kind": kind, "rows": count, "why_dirty": why, "disposition": action}


async def data_authority_report(db: AsyncSession, factory_id: str, *, as_of=None) -> Dict[str, Any]:
    """只读：仿真每一维的数据源、今天有没有值、是不是我们自己灌的。"""
    today = (as_of or datetime.utcnow()).date()
    ie_rows = [dict(r) for r in (await db.execute(IE_TIMES_SQL)).mappings().all()]
    att = (await db.execute(ATTENDANCE_SQL, {
        "fid": factory_id, "frm": today - timedelta(days=30), "to": today})).mappings().first()
    hr = (await db.execute(HR_SQL, {"fid": factory_id})).mappings().first()
    eq = (await db.execute(EQUIPMENT_SQL, {"fid": factory_id})).mappings().first()
    plan = (await db.execute(PLAN_SQL, {"fid": factory_id})).mappings().first()
    kit = (await db.execute(KIT_SQL, {"fid": factory_id})).mappings().first()
    rate = (await db.execute(STATION_RATE_SQL, {"fid": factory_id})).mappings().first()
    lead = (await db.execute(LEAD_TIME_SQL)).mappings().first()
    vrep = (await db.execute(VIRTUAL_REPORTS_SQL)).mappings().first()
    tpl = (await db.execute(TEMPLATE_HOURS_SQL, {"fid": factory_id})).mappings().first()

    ie = classify(ie_rows)
    fresh = attendance_freshness(att["last_attended"] if att else None, today)

    return {
        "status": "ok",
        "factory_id": factory_id,
        "as_of": str(today),
        "authority_rule": (
            "IE 数据 + HR 人力数据为准；用户口述的线产能降为参考；"
            "仿真执行由 出勤·设备·排产·齐套 四维共同维持，任何一维缺真值就报缺，不许拿种子数据顶"),
        "inputs": {
            "ie_standard_times": ie,
            "attendance_last_30d": {
                "records": int(att["records"] or 0) if att else 0,
                "present_rows": int(att["present"] or 0) if att else 0,
                "people_present": int(att["people_present"] or 0) if att else 0,
                **fresh,
            },
            "hr_roster": {
                "roster": int(hr["roster"] or 0) if hr else 0,
                "active": int(hr["active"] or 0) if hr else 0,
                "on_leave": int(hr["on_leave"] or 0) if hr else 0,
                "station_labels": int(hr["station_labels"] or 0) if hr else 0,
                "note": "HR 的 station 是中文叫法（焊接/组立），主档写「焊接车间」，"
                        "归一化走 idle_capacity 的同一套别名函数",
            },
            "equipment": {
                "total": int(eq["total"] or 0) if eq else 0,
                "usable": int(eq["usable"] or 0) if eq else 0,
                "maintenance": int(eq["maintenance"] or 0) if eq else 0,
                "broken": int(eq["broken"] or 0) if eq else 0,
                "status_updated_at": str(eq["status_updated_at"]) if eq and eq["status_updated_at"] else None,
            },
            "active_plan": dict(plan) if plan else {"verdict": "本厂没有生效方案（is_current=0）"},
            "material_kit": {
                "open_orders": int(kit["open_orders"] or 0) if kit else 0,
                "short_lines": int(kit["short_lines"] or 0) if kit else 0,
                "shortage_qty": float(kit["shortage_qty"] or 0) if kit else 0.0,
                "orders_without_kit_evidence": int(kit["orders_without_kit"] or 0) if kit else 0,
            },
        },
        "not_usable_as_evidence": [
            dirty_inventory_row(
                "模板工序声明工时 routing_template_steps.standard_hours",
                int(tpl["with_hours"] or 0) if tpl else 0,
                "%d 个工步有值（%d 条路线），但 %s 行都是 %s~%s 一次性导入的，"
                "created_by 写的是「%s」而代码里没有任何写这张表的路径 —— 是种子，不是 IE 量过的"
                % (int(tpl["with_hours"] or 0) if tpl else 0,
                   int(tpl["templates"] or 0) if tpl else 0,
                   int(tpl["with_hours"] or 0) if tpl else 0,
                   tpl["first_import"] if tpl else "-", tpl["last_import"] if tpl else "-",
                   tpl["声明来源"] if tpl else "-"),
                "暂时仍作 IE 列使用（它是 MES 里 IE 该维护的那一列），但在读数里标「未经 IE 复核」；"
                "IE 复核后写 standard_operation_times 就能顶掉它"),
            dirty_inventory_row(
                "工位每小时产能 stations.capacity_per_hour",
                int(rate["stations_with_rate"] or 0) if rate else 0,
                "值都在，但单位没人定义过：%d 个工位、%d 个不同取值（%s~%s/时）；"
                "同一行焊接能读成 22/44/924/2400 台/天，跨 100 倍"
                % (int(rate["stations_with_rate"] or 0) if rate else 0,
                   int(rate["distinct_values"] or 0) if rate else 0,
                   rate["min_rate"] if rate else "-", rate["max_rate"] if rate else "-"),
                "降级：只用于产能对撞报告，不再作为单件工时来源（等单位裁定，任务 #53）"),
            dirty_inventory_row(
                "物料批量提前期 materials.lead_time_days",
                int(lead["with_lead_time"] or 0) if lead else 0,
                "填得最满（%s 行里 %d 行有值），但只有 %d 个不同值 —— 批量灌的；"
                "供应逻辑实际读 supplier_materials（全表 %d 行）"
                % (int(lead["material_rows"] or 0) if lead else 0,
                   int(lead["with_lead_time"] or 0) if lead else 0,
                   int(lead["distinct_lead_values"] or 0) if lead else 0,
                   int(lead["supplier_binding_rows"] or 0) if lead else 0),
                "不删主档值（属厂内主档），但禁止作为交期依据；交期只认 PO 预计到货日"),
            dirty_inventory_row(
                "虚拟工厂自写报工 production_reports",
                int(vrep["synthetic_rows"] or 0) if vrep else 0,
                "全表 %d 行、其中仿真自写 %d 行（最后一条 %s）：0 行来自现场"
                % (int(vrep["report_rows"] or 0) if vrep else 0,
                   int(vrep["synthetic_rows"] or 0) if vrep else 0,
                   vrep["last_row"] if vrep else "-"),
                "保留（进度与完工靠它推进），但永远标为「仿真执行」，"
                "不得作为工时/产量反推的输入"),
        ],
        "dirty_action": {
            "what_we_can_clear": "standard_operation_times 里 created_by 属于 %s 的自造行（冒充 IE 工时）"
                                 % list(SYNTHETIC_IE_SOURCES),
            "what_we_never_touch": "上传的 BOM、engflow 源库、厂里主档的原始值",
        },
    }


async def purge_synthetic_ie_times(db: AsyncSession, *, apply: bool = False,
                                   factory_id: Optional[str] = None) -> Dict[str, Any]:
    """清掉我们自己造的"IE 标准工时"行；默认预演，删除前先落 CSV 备份。

    作用域是我收窄的：只删 `created_by` 是 virtual_factory / seed_guard 的行 ——
    这两类都是本仓库脚本与引擎写进去的演示数据。IE 真给的行、别的表，一概不碰。
    """
    scope = "AND factory_id = :fid" if factory_id else ""
    params = {"src": list(SYNTHETIC_IE_SOURCES)}
    if factory_id:
        params["fid"] = factory_id
    rows = [dict(r) for r in (await db.execute(text(f"""
        SELECT id, factory_id, product_id, operation_name, operation_seq, standard_time_min,
               setup_time_min, version, created_by, updated_at
        FROM standard_operation_times
        WHERE created_by = ANY(:src) {scope}
    """), params)).mappings().all()]

    out = {"status": "dry_run" if not apply else "ok", "candidates": len(rows),
           "deleted": 0, "by_source": {}, "backup_file": None}
    for r in rows:
        out["by_source"][str(r["created_by"])] = out["by_source"].get(str(r["created_by"]), 0) + 1
    if not rows:
        out["message"] = "没有自造的 IE 工时行可清"
        return out

    if not apply:
        out["message"] = (f"预演：{len(rows)} 行自造 IE 工时可清（{out['by_source']}），"
                          "置 apply=True 才真删；删除前先写 CSV 备份")
        return out

    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, f"ie_times_purged_{stamp}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: str(v) if v is not None else "" for k, v in row.items()})
    out["backup_file"] = path

    deleted = await db.execute(text(f"""
        DELETE FROM standard_operation_times
        WHERE created_by = ANY(:src) {scope}
    """), params)
    out["deleted"] = int(deleted.rowcount or 0)
    await db.commit()
    out["message"] = f"已清掉 {out['deleted']} 行自造 IE 工时（备份 {path}）"
    return out
