"""
OEE 服务 - 岗位替代 Phase 5
OEE 计算 + 日快照 + 趋势分析
"""
import uuid
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


def _gen_id() -> str:
    return str(uuid.uuid4())


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
            "avail": availability, "perf": min(performance, 100), "qual": quality, "oee": oee,
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

    async def get_oee_trend(self, factory_id: str, equipment_id: Optional[str] = None, days: int = 7) -> Dict[str, Any]:
        """OEE 趋势"""
        query = """
            SELECT snapshot_date, AVG(availability) as availability, AVG(performance) as performance,
                AVG(quality) as quality, AVG(oee) as oee, SUM(downtime_minutes) as downtime
            FROM oee_daily WHERE factory_id = :fid
        """
        params: Dict[str, Any] = {"fid": factory_id}
        if equipment_id:
            query += " AND equipment_id = :eid"
            params["eid"] = equipment_id
        query += " AND snapshot_date >= CURRENT_DATE - INTERVAL ':days days' GROUP BY snapshot_date ORDER BY snapshot_date"
        query = query.replace(":days", str(days))

        result = await self.db.execute(text(query), params)
        trend = [dict(r) for r in result.mappings().all()]

        # 平均 OEE
        avg_oee = round(sum(t["oee"] for t in trend) / len(trend), 2) if trend else 0

        return {"trend": trend, "avg_oee": avg_oee, "days": days, "equipment_id": equipment_id}

    async def get_factory_oee_summary(self, factory_id: str) -> Dict[str, Any]:
        """工厂 OEE 概览（今日）"""
        result = await self.db.execute(text("""
            SELECT equipment_id, oee, availability, performance, quality, downtime_minutes
            FROM oee_daily WHERE factory_id = :fid AND snapshot_date = CURRENT_DATE
            ORDER BY oee DESC
        """), {"fid": factory_id})
        items = [dict(r) for r in result.mappings().all()]

        avg_oee = round(sum(i["oee"] for i in items) / len(items), 2) if items else 0
        worst = items[-1] if items else None

        return {
            "date": date.today().isoformat(),
            "equipment_count": len(items),
            "avg_oee": avg_oee,
            "items": items,
            "worst_equipment": worst,
            "world_class": 85,  # 世界级 OEE 标准
        }
