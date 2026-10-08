"""
OEE 服务 - 岗位替代 Phase 5
OEE 计算 + 日快照 + 趋势分析
"""
import uuid
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List


def _as_date(value: Any) -> date:
    """snapshot_date 可能是 date、datetime 或字符串（psycopg 给的不止一种）：比较前先归一成 date。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


def _gen_id() -> str:
    return str(uuid.uuid4())


def as_percent(value: Any) -> Optional[float]:
    """列里存的是 0~1 的小数；显示一律换百分数。取不到就返回 None，不当 0。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v * 100.0, 2)


def to_fraction(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v / 100.0, 6) if v > 1.5 else round(v, 6)


def detect_scale(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """这批 OEE 行是什么尺度：0~1 的小数，还是 0~100 的百分数，还是两种混着。

    混着时必须说出来而不是挑一种解读 —— 上一版就是写入函数存百分数、
    台账里的历史行是小数，两个读数接口照单平均，于是"平均 OEE 0.74"对"世界级 85"。
    """
    vals = [float(r["oee"]) for r in rows if r.get("oee") not in (None, "")]
    if not vals:
        return {"scale": "unknown", "unit": None, "mixed": False,
                "basis": "这批行没有 oee 值可读"}
    lo, hi = min(vals), max(vals)
    if hi <= 1.5:
        scale, unit = "fraction", "0~1 小数"
    elif lo >= 1.0:
        scale, unit = "percent", "0~100 百分数"
    else:
        scale, unit = "mixed", "同一列里既有 ≤1 也有 >1.5 的值"
    return {"scale": scale, "unit": unit, "mixed": scale == "mixed",
            "min_value": round(lo, 4), "max_value": round(hi, 4),
            "basis": ("列内观测区间 " + f"{round(lo, 4)}~{round(hi, 4)}"
                      + ("；读侧按小数换算成百分数显示" if scale == "fraction" else
                         "；两种尺度混存，平均数不可解释，先统一写入口径（本服务已改为只存小数）"
                         if scale == "mixed" else "；按百分数读"))}


def ledger_profile(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """这批行是怎么来的：几个写入时间戳、覆盖哪几天。一个时间戳=批量生成的快照，不是逐日累计。"""
    stamps = {str(r.get("created_at")) for r in rows if r.get("created_at")}
    days = sorted({str(r.get("snapshot_date")) for r in rows if r.get("snapshot_date")})
    one_shot = bool(rows) and len(stamps) <= 1      # 没行时不算"批量生成"，那是另一种情况
    return {
        "rows": len(rows), "write_events": len(stamps),
        "window": [days[0], days[-1]] if days else [],
        "generated_in_one_batch": one_shot,
        "provenance_note": (
            f"{len(rows)} 行集中在 {len(stamps) or 0} 个写入时间戳"
            + ("→ 这是批量生成的快照，不是设备逐日累计上来的读数" if one_shot and rows else "")
            if rows else "台账里没有这个厂区的 OEE 行"),
    }


class OeeService:
    """OEE 综合设备效率"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def calculate_daily_oee(
        self, factory_id: str, equipment_id: str, snapshot_date: Optional[str] = None,
        planned_minutes: float = 960,  # 默认16h
        actual_run_minutes: Optional[float] = None,
        planned_output: int = 0,
        actual_output: int = 0,
        good_output: int = 0,
        ideal_cycle_minutes: float = 1.0,
    ) -> Dict[str, Any]:
        """计算并保存日 OEE"""
        target_date = date.fromisoformat(snapshot_date) if snapshot_date else date.today()

        # 获取停机时间
        downtime_result = await self.db.execute(text("""
            SELECT COALESCE(SUM(EXTRACT(EPOCH FROM (COALESCE(end_time, NOW()) - start_time)) / 60), 0) as total_min,
                COALESCE(SUM(CASE WHEN reason_category = 'breakdown' THEN EXTRACT(EPOCH FROM (COALESCE(end_time, NOW()) - start_time)) / 60 ELSE 0 END), 0) as breakdown_min,
                COALESCE(SUM(CASE WHEN reason_category = 'setup' THEN EXTRACT(EPOCH FROM (COALESCE(end_time, NOW()) - start_time)) / 60 ELSE 0 END), 0) as setup_min
            FROM equipment_downtime
            WHERE factory_id = :fid AND equipment_id = :eid
                AND start_time::date = :dt
        """), {"fid": factory_id, "eid": equipment_id, "dt": target_date})
        dt_stats = downtime_result.mappings().first()

        downtime_min = dt_stats["total_min"] if dt_stats else 0
        breakdown_min = dt_stats["breakdown_min"] if dt_stats else 0
        setup_min = dt_stats["setup_min"] if dt_stats else 0
        idle_min = max(0, downtime_min - breakdown_min - setup_min)

        if actual_run_minutes is None:
            actual_run_minutes = max(0, planned_minutes - downtime_min)

        # 三大率计算
        availability = round(actual_run_minutes / planned_minutes * 100, 2) if planned_minutes > 0 else 0
        performance = round((actual_output * ideal_cycle_minutes) / actual_run_minutes * 100, 2) if actual_run_minutes > 0 else 0
        quality = round(good_output / actual_output * 100, 2) if actual_output > 0 else 100
        oee = round(availability * performance * quality / 10000, 2)

        # 保存
        await self.db.execute(text("""
            INSERT INTO oee_daily (id, factory_id, equipment_id, snapshot_date,
                planned_production_minutes, actual_run_minutes, downtime_minutes,
                availability, performance, quality, oee,
                planned_output, actual_output, good_output,
                breakdown_minutes, setup_minutes, idle_minutes, created_at)
            VALUES (:id, :fid, :eid, :dt, :planned, :run, :down,
                :avail, :perf, :qual, :oee, :po, :ao, :go, :bd, :su, :idle, :now)
            ON CONFLICT (factory_id, equipment_id, snapshot_date) DO UPDATE SET
                planned_production_minutes = :planned, actual_run_minutes = :run,
                downtime_minutes = :down, availability = :avail, performance = :perf,
                quality = :qual, oee = :oee, planned_output = :po, actual_output = :ao,
                good_output = :go, breakdown_minutes = :bd, setup_minutes = :su, idle_minutes = :idle
        """), {
            "id": _gen_id(), "fid": factory_id, "eid": equipment_id, "dt": target_date,
            "planned": planned_minutes, "run": actual_run_minutes, "down": downtime_min,
            # 库里只存 0~1 的小数：原来这里写百分数（74.13），而两个读数接口直接把列值当
            # 百分数平均、又拿 85 当世界级门槛比 —— 同一列两种尺度，谁先读谁出错。
            "avail": availability / 100.0, "perf": min(performance, 100) / 100.0,
            "qual": quality / 100.0, "oee": oee / 100.0,
            "po": planned_output, "ao": actual_output, "go": good_output,
            "bd": breakdown_min, "su": setup_min, "idle": idle_min, "now": datetime.utcnow(),
        })
        await self.db.commit()

        return {
            "equipment_id": equipment_id,
            "date": target_date.isoformat(),
            "availability": availability,
            "performance": min(performance, 100),
            "quality": quality,
            "oee": oee,
            "downtime_minutes": round(downtime_min, 1),
        }

    async def _all_rows(self, factory_id: str, equipment_id: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = """
            SELECT snapshot_date, equipment_id, availability, performance, quality, oee,
                   downtime_minutes, created_at
            FROM oee_daily WHERE factory_id = :fid
        """
        params: Dict[str, Any] = {"fid": factory_id}
        if equipment_id:
            sql += " AND equipment_id = :eid"
            params["eid"] = equipment_id
        sql += " ORDER BY snapshot_date"
        return [dict(r) for r in (await self.db.execute(text(sql), params)).mappings().all()]

    async def get_oee_trend(self, factory_id: str, equipment_id: Optional[str] = None, days: int = 7) -> Dict[str, Any]:
        """OEE 趋势：窗口锚在**台账里最后一天**，不是"今天"。

        两个读数的老写法都把窗口钉在 CURRENT_DATE 上，而这个厂的 oee_daily 只有
        2026-08-01~08-07 一批生成的行 —— 今天没有行不等于 OEE 是 0，
        报 0 会被当成"这台设备今天没效率"，那是把空集合念成了事实。
        """
        rows = await self._all_rows(factory_id, equipment_id)
        scale, prof = detect_scale(rows), ledger_profile(rows)
        dates = sorted({str(r.get("snapshot_date")) for r in rows if r.get("snapshot_date")})
        if not rows:
            return {"trend": [], "avg_oee": None, "days": days, "equipment_id": equipment_id,
                    "data_status": "no_rows", "ledger": prof, "scale": scale,
                    "why": f"{factory_id} 在 oee_daily 里没有任何行 → 趋势算不出，不给 0"}
        last = datetime.strptime(dates[-1], "%Y-%m-%d").date()
        start = last - timedelta(days=max(1, int(days)) - 1)
        kept = [r for r in rows if start <= _as_date(r.get("snapshot_date")) <= last]
        by_day: Dict[str, List[Dict[str, Any]]] = {}
        for r in kept:
            by_day.setdefault(str(r.get("snapshot_date")), []).append(r)

        def pct(v: Any) -> Optional[float]:
            return None if v is None else (round(float(v) * 100, 2) if scale["scale"] == "fraction"
                                           else round(float(v), 2))

        trend = [{"snapshot_date": d,
                  "availability": pct(sum(float(x["availability"] or 0) for x in g) / len(g)),
                  "performance": pct(sum(float(x["performance"] or 0) for x in g) / len(g)),
                  "quality": pct(sum(float(x["quality"] or 0) for x in g) / len(g)),
                  "oee": pct(sum(float(x["oee"] or 0) for x in g) / len(g)),
                  "equipment_count": len(g),
                  "downtime_minutes": round(sum(float(x["downtime_minutes"] or 0) for x in g), 1)}
                 for d, g in sorted(by_day.items())]
        vals = [t["oee"] for t in trend if t["oee"] is not None]
        return {
            "trend": trend,
            "avg_oee": (round(sum(vals) / len(vals), 2) if vals else None),
            "unit": "percent",
            "days": days, "equipment_id": equipment_id,
            "window": [str(start), str(last)],
            "window_basis": (f"台账最后一天 {dates[-1]} 往前 {days} 天（今天没有行不等于 OEE 是 0）"
                             if dates[-1] != str(date.today()) else
                             f"{days} 天窗口，锚在当天"),
            "ledger": prof, "scale": scale,
            "data_status": "ready" if trend else "no_rows_in_window",
            "note": ("这批行是批量生成的快照时，趋势只能当历史情景读，不能当设备逐日实测；"
                     "见 ledger.provenance_note"),
        }

    async def get_factory_oee_summary(self, factory_id: str,
                                      snapshot_date: Optional[str] = None) -> Dict[str, Any]:
        """工厂 OEE 概览：默认取台账里最后一天，不是"今天"；没有行就不给平均数。"""
        rows = await self._all_rows(factory_id)
        scale, prof = detect_scale(rows), ledger_profile(rows)
        dates = sorted({str(r.get("snapshot_date")) for r in rows if r.get("snapshot_date")})
        wanted = str(snapshot_date)[:10] if snapshot_date else (dates[-1] if dates else None)
        if not wanted:
            return {"factory_id": factory_id, "date": None, "equipment_count": 0, "avg_oee": None,
                    "items": [], "worst_equipment": None, "world_class_pct": 85,
                    "data_status": "no_rows", "ledger": prof, "scale": scale,
                    "why": (f"{factory_id} 在 oee_daily 里没有任何行 → 这台概览算不出，"
                            "报 0 会被读成「今天 OEE 是零」"),
                    "note": "OEE 要么由设备逐日累计，要么由 IE 填报并标出处；批量生成的快照行不算实测"}
        kept = [r for r in rows if str(r.get("snapshot_date"))[:10] == wanted]

        def pct(v: Any) -> Optional[float]:
            return None if v is None else (round(float(v) * 100, 2) if scale["scale"] == "fraction"
                                           else round(float(v), 2))

        items = sorted([{
            "equipment_id": str(r.get("equipment_id")),
            "oee": pct(r.get("oee")), "availability": pct(r.get("availability")),
            "performance": pct(r.get("performance")), "quality": pct(r.get("quality")),
            "downtime_minutes": (round(float(r.get("downtime_minutes") or 0), 1)
                                 if r.get("downtime_minutes") is not None else None),
        } for r in kept], key=lambda x: (x["oee"] is None, -(x["oee"] or 0)))
        vals = [i["oee"] for i in items if i["oee"] is not None]
        return {
            "factory_id": factory_id,
            "date": wanted,
            "date_basis": ("调用方点名的那天" if snapshot_date else "台账里最后一天（今天没有行）"),
            "equipment_count": len(items),
            "avg_oee": (round(sum(vals) / len(vals), 2) if vals else None),
            "unit": "percent",
            "items": items,
            "worst_equipment": items[-1] if items else None,
            "world_class_pct": 85,      # 世界级 OEE 门槛，按百分数比
            "ledger": prof, "scale": scale,
            "data_status": "ready" if items else "no_rows_on_that_date",
            "note": ("这批行由同一个写入时间戳生成时（见 ledger.generated_in_one_batch），"
                     "对外只能说「批量快照」，不能说「本厂实测 OEE」"),
        }
