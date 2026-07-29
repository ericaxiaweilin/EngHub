"""
生产看板服务 - 岗位替代 Phase 1: 实时生产看板
给主管/车间主任看的实时数据大屏
"""
import uuid
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case

from database.models import (
    ProductionReport, WorkOrder, Station, Equipment,
    ShiftSummary, ProductionAlert, HourlyOutputSnapshot,
)


def _gen_id() -> str:
    return str(uuid.uuid4())


class DashboardService:
    """实时生产看板服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_live_dashboard(self, factory_id: str) -> Dict[str, Any]:
        """实时看板主数据"""
        today = date.today()

        # 今日产出汇总
        stmt = select(
            func.coalesce(func.sum(ProductionReport.good_qty + ProductionReport.defect_qty + ProductionReport.scrap_qty), 0),
            func.coalesce(func.sum(ProductionReport.good_qty), 0),
            func.coalesce(func.sum(ProductionReport.defect_qty + ProductionReport.scrap_qty), 0),
            func.count(ProductionReport.id),
        ).where(
            and_(
                ProductionReport.factory_id == factory_id,
                ProductionReport.is_undone == False,
                func.date(ProductionReport.created_at) == today,
            )
        )
        result = await self.db.execute(stmt)
        row = result.one()
        total_output, good_qty, defect_qty, report_count = row

        yield_rate = (good_qty / total_output * 100) if total_output > 0 else 0

        # 在制工单数
        wip_stmt = select(func.count(WorkOrder.id)).where(
            and_(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status.in_(["released", "in_progress"]),
            )
        )
        wip_result = await self.db.execute(wip_stmt)
        wip_count = wip_result.scalar() or 0

        # 今日目标（从 shift_summaries 的 target 汇总，或默认值）
        target_stmt = select(func.coalesce(func.sum(ShiftSummary.target_output), 0)).where(
            and_(
                ShiftSummary.factory_id == factory_id,
                ShiftSummary.shift_date == today,
            )
        )
        target_result = await self.db.execute(target_stmt)
        target_output = target_result.scalar() or 0

        achievement_rate = (total_output / target_output * 100) if target_output > 0 else 0

        # 未读预警数
        alert_stmt = select(func.count(ProductionAlert.id)).where(
            and_(
                ProductionAlert.factory_id == factory_id,
                ProductionAlert.is_read == False,
                func.date(ProductionAlert.triggered_at) == today,
            )
        )
        alert_result = await self.db.execute(alert_stmt)
        unread_alerts = alert_result.scalar() or 0

        return {
            "date": today.isoformat(),
            "total_output": total_output,
            "good_qty": good_qty,
            "defect_qty": defect_qty,
            "yield_rate": round(yield_rate, 2),
            "report_count": report_count,
            "wip_count": wip_count,
            "target_output": target_output,
            "achievement_rate": round(achievement_rate, 2),
            "unread_alerts": unread_alerts,
            "updated_at": datetime.utcnow().isoformat(),
        }

    async def get_hourly_trend(self, factory_id: str, target_date: Optional[str] = None) -> Dict[str, Any]:
        """小时产出趋势（今日 vs 昨日）"""
        today = date.fromisoformat(target_date) if target_date else date.today()
        yesterday = today - timedelta(days=1)

        async def _get_hourly(d: date) -> List[Dict]:
            stmt = select(
                HourlyOutputSnapshot.snapshot_hour,
                func.sum(HourlyOutputSnapshot.output_qty),
                func.sum(HourlyOutputSnapshot.good_qty),
                func.sum(HourlyOutputSnapshot.defect_qty),
            ).where(
                and_(
                    HourlyOutputSnapshot.factory_id == factory_id,
                    HourlyOutputSnapshot.snapshot_date == d,
                )
            ).group_by(HourlyOutputSnapshot.snapshot_hour).order_by(HourlyOutputSnapshot.snapshot_hour)

            result = await self.db.execute(stmt)
            rows = result.all()
            return [{"hour": r[0], "output": r[1] or 0, "good": r[2] or 0, "defect": r[3] or 0} for r in rows]

        today_data = await _get_hourly(today)
        yesterday_data = await _get_hourly(yesterday)

        return {
            "date": today.isoformat(),
            "today": today_data,
            "yesterday": yesterday_data,
        }

    async def get_station_grid(self, factory_id: str) -> Dict[str, Any]:
        """工位状态矩阵"""
        # 获取所有工位
        station_stmt = select(Station).where(Station.factory_id == factory_id)
        station_result = await self.db.execute(station_stmt)
        stations = station_result.scalars().all()

        # 获取设备状态
        equip_stmt = select(Equipment).where(Equipment.factory_id == factory_id)
        equip_result = await self.db.execute(equip_stmt)
        equipments = equip_result.scalars().all()
        equip_status_map = {e.id: e.status for e in equipments}

        # 最近30分钟有报工 → 运行中
        threshold = datetime.utcnow() - timedelta(minutes=30)
        active_stmt = select(ProductionReport.station_id).where(
            and_(
                ProductionReport.factory_id == factory_id,
                ProductionReport.created_at >= threshold,
                ProductionReport.is_undone == False,
            )
        ).distinct()
        active_result = await self.db.execute(active_stmt)
        active_stations = {r[0] for r in active_result.all()}

        grid = []
        for s in stations:
            # 判断状态
            if s.id in active_stations:
                status = "running"
            elif s.id in equip_status_map and equip_status_map[s.id] == "maintenance":
                status = "maintenance"
            elif s.id in equip_status_map and equip_status_map[s.id] == "breakdown":
                status = "breakdown"
            else:
                status = "idle"

            grid.append({
                "station_id": s.id,
                "station_name": getattr(s, "name", s.id),
                "status": status,
                "equipment_status": equip_status_map.get(s.id, "unknown"),
            })

        # 统计
        status_counts = {}
        for item in grid:
            st = item["status"]
            status_counts[st] = status_counts.get(st, 0) + 1

        return {
            "stations": grid,
            "summary": status_counts,
            "total": len(grid),
        }

    async def get_top_issues(self, factory_id: str, limit: int = 10) -> Dict[str, Any]:
        """当前 Top 异常"""
        stmt = (
            select(ProductionAlert)
            .where(
                and_(
                    ProductionAlert.factory_id == factory_id,
                    ProductionAlert.is_resolved == False,
                )
            )
            .order_by(
                case(
                    (ProductionAlert.severity == "critical", 0),
                    (ProductionAlert.severity == "warning", 1),
                    else_=2,
                ),
                ProductionAlert.triggered_at.desc(),
            )
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        alerts = result.scalars().all()

        return {
            "items": [{
                "id": a.id,
                "type": a.alert_type,
                "severity": a.severity,
                "title": a.title,
                "message": a.message,
                "source_type": a.source_type,
                "source_id": a.source_id,
                "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
            } for a in alerts],
        }

    async def mark_alert_read(self, alert_id: str) -> Dict[str, Any]:
        """标记预警已读"""
        alert = await self.db.get(ProductionAlert, alert_id)
        if not alert:
            return {"error": "预警不存在"}
        alert.is_read = True
        await self.db.commit()
        return {"success": True}

    async def resolve_alert(self, alert_id: str, resolved_by: str) -> Dict[str, Any]:
        """解决预警"""
        alert = await self.db.get(ProductionAlert, alert_id)
        if not alert:
            return {"error": "预警不存在"}
        alert.is_resolved = True
        alert.is_read = True
        alert.resolved_by = resolved_by
        alert.resolved_at = datetime.utcnow()
        await self.db.commit()
        return {"success": True}
