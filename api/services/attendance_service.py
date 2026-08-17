"""
考勤自动生成服务 —— 保障 RCC 资源可用指数每日可用

背景：资源可用指数的人力/工时维度读当日 attendance，此前考勤仅由种子脚本
一次性生成，过了当天就 0/0 → 指数归零报"危险"。

设计（幂等 + 确定性）：
- 当日已有考勤记录 → 直接跳过（重复调用零副作用）
- 花名册 hr_employees 为准：leave→请假、rest→休息、其余 present
- 班次继承本人昨日班次，新员工默认白班
- 迟到判定用 md5(工号+日期) 确定性伪随机（同一人同一天恒同，重跑不抖动）
"""
import hashlib
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logging.getLogger("attendance_service")

SHIFT_START_HOUR = {"白班": 8, "夜班": 20, "两班倒": 8, "早班": 8, "中班": 12, "晚班": 16}


def _det_late(operator_id: str, date_str: str) -> bool:
    """确定性迟到判定：约 4% 概率，同一人同一天恒定。"""
    h = int(hashlib.md5(f"{operator_id}:{date_str}".encode()).hexdigest()[:8], 16)
    return h % 25 == 0


async def ensure_attendance(db: AsyncSession, factory_id: str,
                            date_str: Optional[str] = None) -> Dict[str, Any]:
    """确保指定日期（默认今日）考勤存在；已存在则跳过。"""
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")

    existing = (await db.execute(text(
        "SELECT COUNT(*) FROM attendance WHERE factory_id=:f AND date=:d"
    ), {"f": factory_id, "d": date_str})).scalar_one()
    if existing:
        return {"factory_id": factory_id, "date": date_str, "created": 0, "skipped": True}

    # 编制口径：operators 表（attendance.operator_id 外键指向它，1044 人与历史考勤编制一致）
    employees = (await db.execute(text(
        "SELECT id, status FROM operators WHERE factory_id=:f"
    ), {"f": factory_id})).fetchall()
    if not employees:
        return {"factory_id": factory_id, "date": date_str, "created": 0, "skipped": True,
                "note": "花名册为空"}

    # 昨日班次继承
    yesterday = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    prev_shift = {r[0]: r[1] for r in (await db.execute(text(
        "SELECT operator_id, shift FROM attendance WHERE factory_id=:f AND date=:d"
    ), {"f": factory_id, "d": yesterday})).fetchall()}

    rows = []
    for emp_id, emp_status in [(r[0], r[1]) for r in employees]:
        shift = prev_shift.get(emp_id, "白班")
        if emp_status == "leave":
            status = "leave"
        elif emp_status == "rest":
            status = "rest"
        elif _det_late(emp_id, date_str):
            status = "late"
        else:
            status = "present"

        check_in = None
        check_out = None
        if status in ("present", "late"):
            base_hour = SHIFT_START_HOUR.get(shift, 8)
            base = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=base_hour)
            late_offset = 12 if status == "late" else 0
            check_in = base + timedelta(minutes=late_offset)
            dur = 20 if shift == "两班倒" else 10 if shift in ("白班", "夜班") else 8
            check_out = check_in + timedelta(hours=dur)

        rows.append({
            "id": str(uuid.uuid4()), "f": factory_id, "op": emp_id, "d": date_str,
            "ci": check_in, "co": check_out, "shift": shift, "status": status,
            "now": datetime.now(),
        })

    # 分批插入（防长事务）
    for i in range(0, len(rows), 500):
        batch = rows[i:i + 500]
        await db.execute(text("""
            INSERT INTO attendance (id, factory_id, operator_id, date, check_in, check_out,
                                    shift, status, created_at)
            VALUES (:id, :f, :op, :d, :ci, :co, :shift, :status, :now)
        """), batch)
    await db.commit()

    present = sum(1 for r in rows if r["status"] in ("present", "late"))
    _logger.info("[attendance] %s %s 生成 %s 条考勤（在岗 %s）", factory_id, date_str, len(rows), present)
    return {"factory_id": factory_id, "date": date_str, "created": len(rows),
            "present": present, "skipped": False}
