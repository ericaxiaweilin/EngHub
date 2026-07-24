"""
报表生成服务 - 岗位替代 Phase 1: 自动日报/周报/月报
替代统计员的核心工作：数据汇总 + 报表生成
"""
import uuid
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, extract

from database.models import (
    ProductionReport, WorkOrder, ShiftSummary,
    ProductionAlert, EquipmentDowntime, Station,
)


class ReportGeneratorService:
    """自动报表生成服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_daily_report(self, factory_id: str, report_date: Optional[str] = None) -> Dict[str, Any]:
        """生成日报"""
        target_date = date.fromisoformat(report_date) if report_date else date.today()

        # 1. 产出汇总
        output_stmt = select(
            func.coalesce(func.sum(ProductionReport.good_qty), 0),
            func.coalesce(func.sum(ProductionReport.defect_qty), 0),
            func.coalesce(func.sum(ProductionReport.scrap_qty), 0),
            func.count(ProductionReport.id),
        ).where(
            and_(
                ProductionReport.factory_id == factory_id,
                func.date(ProductionReport.created_at) == target_date,
                ProductionReport.is_undone == False,
            )
        )
        result = await self.db.execute(output_stmt)
        row = result.one()
        good, defect, scrap, reports = row
        total = good + defect + scrap
        yield_rate = (good / total * 100) if total > 0 else 0

        # 2. 按工单汇总
        wo_stmt = select(
            ProductionReport.work_order_id,
            func.sum(ProductionReport.good_qty + ProductionReport.defect_qty + ProductionReport.scrap_qty),
            func.sum(ProductionReport.good_qty),
            func.sum(ProductionReport.defect_qty + ProductionReport.scrap_qty),
        ).where(
            and_(
                ProductionReport.factory_id == factory_id,
                func.date(ProductionReport.created_at) == target_date,
                ProductionReport.is_undone == False,
            )
        ).group_by(ProductionReport.work_order_id)
        wo_result = await self.db.execute(wo_stmt)
        wo_rows = wo_result.all()

        # 获取工单信息
        wo_details = []
        for wo_id, wo_total, wo_good, wo_defect in wo_rows:
            wo = await self.db.get(WorkOrder, wo_id)
            wo_details.append({
                "work_order_id": wo_id,
                "work_order_code": wo.work_order_code if wo else wo_id,
                "product_id": wo.product_id if wo else "unknown",
                "planned_qty": wo.planned_qty if wo else 0,
                "today_output": wo_total or 0,
                "today_good": wo_good or 0,
                "today_defect": wo_defect or 0,
                "completed_qty": wo.completed_qty if wo else 0,
                "achievement": round((wo.completed_qty / wo.planned_qty * 100), 1) if wo and wo.planned_qty else 0,
            })
        wo_details.sort(key=lambda x: x["today_output"], reverse=True)

        # 3. 按工位汇总
        station_stmt = select(
            ProductionReport.station_id,
            func.sum(ProductionReport.good_qty + ProductionReport.defect_qty + ProductionReport.scrap_qty),
            func.sum(ProductionReport.good_qty),
            func.count(ProductionReport.id),
        ).where(
            and_(
                ProductionReport.factory_id == factory_id,
                func.date(ProductionReport.created_at) == target_date,
                ProductionReport.is_undone == False,
            )
        ).group_by(ProductionReport.station_id).order_by(
            func.sum(ProductionReport.good_qty + ProductionReport.defect_qty + ProductionReport.scrap_qty).desc()
        )
        station_result = await self.db.execute(station_stmt)
        station_rows = station_result.all()
        station_ranking = [{
            "station_id": r[0],
            "output": r[1] or 0,
            "good": r[2] or 0,
            "reports": r[3] or 0,
            "yield_rate": round((r[2] / r[1] * 100), 1) if r[1] else 0,
        } for r in station_rows]

        # 4. 异常事件
        alert_stmt = select(ProductionAlert).where(
            and_(
                ProductionAlert.factory_id == factory_id,
                func.date(ProductionAlert.triggered_at) == target_date,
            )
        ).order_by(ProductionAlert.triggered_at.desc())
        alert_result = await self.db.execute(alert_stmt)
        alerts = alert_result.scalars().all()
        alert_list = [{
            "type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
        } for a in alerts]

        # 5. 停机统计
        downtime_stmt = select(
            func.count(EquipmentDowntime.id),
            func.coalesce(func.sum(EquipmentDowntime.duration_minutes), 0),
        ).where(
            and_(
                EquipmentDowntime.factory_id == factory_id,
                func.date(EquipmentDowntime.start_time) == target_date,
            )
        )
        dt_result = await self.db.execute(downtime_stmt)
        dt_row = dt_result.one()
        downtime_count, downtime_minutes = dt_row

        # 6. 明日计划（状态为 released 的工单）
        tomorrow_stmt = select(WorkOrder).where(
            and_(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status.in_(["released", "pending"]),
            )
        ).limit(10)
        tomorrow_result = await self.db.execute(tomorrow_stmt)
        tomorrow_orders = tomorrow_result.scalars().all()
        tomorrow_plan = [{
            "work_order_code": wo.work_order_code,
            "product_id": wo.product_id,
            "planned_qty": wo.planned_qty,
            "remaining": max(0, wo.planned_qty - (wo.completed_qty or 0)),
            "priority": wo.priority,
        } for wo in tomorrow_orders]

        return {
            "report_type": "daily",
            "date": target_date.isoformat(),
            "factory_id": factory_id,
            "summary": {
                "total_output": total,
                "good_qty": good,
                "defect_qty": defect + scrap,
                "yield_rate": round(yield_rate, 2),
                "report_count": reports,
                "downtime_count": downtime_count,
                "downtime_minutes": round(downtime_minutes, 1),
                "alert_count": len(alerts),
            },
            "work_orders": wo_details,
            "station_ranking": station_ranking,
            "alerts": alert_list,
            "tomorrow_plan": tomorrow_plan,
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def generate_weekly_report(self, factory_id: str, week: Optional[str] = None) -> Dict[str, Any]:
        """生成周报"""
        if week:
            # 解析 ISO 周格式 2026-W30
            year, week_num = week.split("-W")
            target_date = date.fromisocalendar(int(year), int(week_num), 1)
        else:
            target_date = date.today() - timedelta(days=date.today().weekday())

        week_start = target_date
        week_end = target_date + timedelta(days=6)

        # 按天汇总
        daily_stmt = select(
            func.date(ProductionReport.created_at),
            func.sum(ProductionReport.good_qty + ProductionReport.defect_qty + ProductionReport.scrap_qty),
            func.sum(ProductionReport.good_qty),
            func.sum(ProductionReport.defect_qty + ProductionReport.scrap_qty),
        ).where(
            and_(
                ProductionReport.factory_id == factory_id,
                func.date(ProductionReport.created_at) >= week_start,
                func.date(ProductionReport.created_at) <= week_end,
                ProductionReport.is_undone == False,
            )
        ).group_by(func.date(ProductionReport.created_at)).order_by(func.date(ProductionReport.created_at))

        result = await self.db.execute(daily_stmt)
        daily_rows = result.all()

        daily_data = [{
            "date": str(r[0]),
            "output": r[1] or 0,
            "good": r[2] or 0,
            "defect": r[3] or 0,
            "yield_rate": round((r[2] / r[1] * 100), 1) if r[1] else 0,
        } for r in daily_rows]

        total_output = sum(d["output"] for d in daily_data)
        total_good = sum(d["good"] for d in daily_data)
        total_defect = sum(d["defect"] for d in daily_data)
        avg_yield = (total_good / total_output * 100) if total_output > 0 else 0

        return {
            "report_type": "weekly",
            "week": f"{week_start.isocalendar()[0]}-W{week_start.isocalendar()[1]:02d}",
            "period": f"{week_start.isoformat()} ~ {week_end.isoformat()}",
            "factory_id": factory_id,
            "summary": {
                "total_output": total_output,
                "good_qty": total_good,
                "defect_qty": total_defect,
                "avg_yield_rate": round(avg_yield, 2),
                "working_days": len(daily_data),
                "avg_daily_output": round(total_output / max(len(daily_data), 1)),
            },
            "daily_trend": daily_data,
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def generate_monthly_report(self, factory_id: str, month: Optional[str] = None) -> Dict[str, Any]:
        """生成月报"""
        if month:
            year, mon = month.split("-")
            target_year, target_month = int(year), int(mon)
        else:
            today = date.today()
            target_year, target_month = today.year, today.month

        month_start = date(target_year, target_month, 1)
        if target_month == 12:
            month_end = date(target_year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(target_year, target_month + 1, 1) - timedelta(days=1)

        # 按周汇总
        weekly_stmt = select(
            extract("week", ProductionReport.created_at),
            func.sum(ProductionReport.good_qty + ProductionReport.defect_qty + ProductionReport.scrap_qty),
            func.sum(ProductionReport.good_qty),
            func.sum(ProductionReport.defect_qty + ProductionReport.scrap_qty),
        ).where(
            and_(
                ProductionReport.factory_id == factory_id,
                func.date(ProductionReport.created_at) >= month_start,
                func.date(ProductionReport.created_at) <= month_end,
                ProductionReport.is_undone == False,
            )
        ).group_by(extract("week", ProductionReport.created_at)).order_by(extract("week", ProductionReport.created_at))

        result = await self.db.execute(weekly_stmt)
        weekly_rows = result.all()

        weekly_data = [{
            "week": int(r[0]),
            "output": r[1] or 0,
            "good": r[2] or 0,
            "defect": r[3] or 0,
            "yield_rate": round((r[2] / r[1] * 100), 1) if r[1] else 0,
        } for r in weekly_rows]

        total_output = sum(w["output"] for w in weekly_data)
        total_good = sum(w["good"] for w in weekly_data)
        total_defect = sum(w["defect"] for w in weekly_data)
        avg_yield = (total_good / total_output * 100) if total_output > 0 else 0

        # 工单完成情况
        wo_stmt = select(
            WorkOrder.status,
            func.count(WorkOrder.id),
        ).where(
            and_(
                WorkOrder.factory_id == factory_id,
                WorkOrder.created_at >= datetime.combine(month_start, datetime.min.time()),
                WorkOrder.created_at <= datetime.combine(month_end, datetime.max.time()),
            )
        ).group_by(WorkOrder.status)
        wo_result = await self.db.execute(wo_stmt)
        wo_status = {r[0]: r[1] for r in wo_result.all()}

        return {
            "report_type": "monthly",
            "month": f"{target_year}-{target_month:02d}",
            "period": f"{month_start.isoformat()} ~ {month_end.isoformat()}",
            "factory_id": factory_id,
            "summary": {
                "total_output": total_output,
                "good_qty": total_good,
                "defect_qty": total_defect,
                "avg_yield_rate": round(avg_yield, 2),
                "weeks": len(weekly_data),
            },
            "weekly_trend": weekly_data,
            "work_order_stats": wo_status,
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def custom_query(
        self,
        factory_id: str,
        start_date: str,
        end_date: str,
        group_by: str = "station",  # station/work_order/product/operator
    ) -> Dict[str, Any]:
        """自定义查询"""
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)

        group_col = {
            "station": ProductionReport.station_id,
            "work_order": ProductionReport.work_order_id,
            "operator": ProductionReport.operator_id,
        }.get(group_by, ProductionReport.station_id)

        stmt = select(
            group_col,
            func.sum(ProductionReport.good_qty + ProductionReport.defect_qty + ProductionReport.scrap_qty),
            func.sum(ProductionReport.good_qty),
            func.sum(ProductionReport.defect_qty + ProductionReport.scrap_qty),
            func.count(ProductionReport.id),
        ).where(
            and_(
                ProductionReport.factory_id == factory_id,
                func.date(ProductionReport.created_at) >= start,
                func.date(ProductionReport.created_at) <= end,
                ProductionReport.is_undone == False,
            )
        ).group_by(group_col).order_by(
            func.sum(ProductionReport.good_qty + ProductionReport.defect_qty + ProductionReport.scrap_qty).desc()
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return {
            "query": {
                "factory_id": factory_id,
                "start_date": start_date,
                "end_date": end_date,
                "group_by": group_by,
            },
            "results": [{
                "group_key": r[0] or "unknown",
                "total_output": r[1] or 0,
                "good_qty": r[2] or 0,
                "defect_qty": r[3] or 0,
                "yield_rate": round((r[2] / r[1] * 100), 1) if r[1] else 0,
                "report_count": r[4] or 0,
            } for r in rows],
            "generated_at": datetime.utcnow().isoformat(),
        }
