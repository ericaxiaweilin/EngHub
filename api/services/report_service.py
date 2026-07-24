"""
报工服务 - 岗位替代 Phase 1: 消灭统计员
快速报工 / 批量报工 / 撤回 / 班次汇总 / 异常预警
"""
import uuid
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.models import (
    ProductionReport, WorkOrder, Station, ShiftSummary,
    ProductionAlert, HourlyOutputSnapshot, Equipment,
)


def _gen_id() -> str:
    return str(uuid.uuid4())


def _gen_report_code(factory_id: str) -> str:
    """生成报工编码: RPT-{工厂前3位}-{日期}-{4位随机}"""
    prefix = factory_id[:3].upper() if factory_id else "FAC"
    ts = datetime.now().strftime("%m%d%H%M")
    suffix = uuid.uuid4().hex[:4].upper()
    return f"RPT-{prefix}-{ts}-{suffix}"


def _detect_shift() -> str:
    """根据当前时间自动判断班次"""
    hour = datetime.now().hour
    if 6 <= hour < 14:
        return "day"
    elif 14 <= hour < 22:
        return "middle"
    else:
        return "night"


class ReportService:
    """生产报工服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== 快速报工 ====================

    async def quick_report(
        self,
        factory_id: str,
        work_order_id: str,
        station_id: str,
        good_qty: int,
        defect_qty: int = 0,
        scrap_qty: int = 0,
        operator_id: Optional[str] = None,
        operation_seq: Optional[int] = None,
        operation_name: Optional[str] = None,
        machine_id: Optional[str] = None,
        cycle_time_sec: Optional[float] = None,
        remark: Optional[str] = None,
        shift: Optional[str] = None,
    ) -> Dict[str, Any]:
        """快速报工 - 3秒完成"""
        shift = shift or _detect_shift()
        now = datetime.utcnow()

        report = ProductionReport(
            id=_gen_id(),
            report_code=_gen_report_code(factory_id),
            factory_id=factory_id,
            work_order_id=work_order_id,
            station_id=station_id,
            good_qty=good_qty,
            defect_qty=defect_qty,
            scrap_qty=scrap_qty,
            report_type="quick",
            shift=shift,
            operator_id=operator_id,
            operation_seq=operation_seq,
            operation_name=operation_name,
            machine_id=machine_id,
            start_time=now,
            end_time=now,
            cycle_time_sec=cycle_time_sec,
            remark=remark,
            created_by=operator_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(report)

        # 更新工单完成数量
        wo = await self.db.get(WorkOrder, work_order_id)
        if wo:
            wo.completed_qty = (wo.completed_qty or 0) + good_qty + defect_qty + scrap_qty
            wo.good_qty = (wo.good_qty or 0) + good_qty
            wo.defect_qty = (wo.defect_qty or 0) + defect_qty
            wo.scrap_qty = (wo.scrap_qty or 0) + scrap_qty
            wo.updated_at = now

        await self.db.flush()

        # 异步更新班次汇总 + 小时快照
        await self._update_shift_summary(factory_id, shift, station_id, work_order_id,
                                         good_qty, defect_qty, scrap_qty, cycle_time_sec, operator_id)
        await self._update_hourly_snapshot(factory_id, station_id, good_qty + defect_qty + scrap_qty,
                                           good_qty, defect_qty)

        # 检查是否触发预警
        await self._check_alerts(factory_id, station_id, work_order_id, good_qty, defect_qty, scrap_qty)

        await self.db.commit()

        return {
            "id": report.id,
            "report_code": report.report_code,
            "good_qty": good_qty,
            "defect_qty": defect_qty,
            "scrap_qty": scrap_qty,
            "shift": shift,
            "created_at": now.isoformat(),
        }

    # ==================== 批量报工 ====================

    async def batch_report(
        self,
        factory_id: str,
        items: List[Dict[str, Any]],
        operator_id: Optional[str] = None,
        shift: Optional[str] = None,
    ) -> Dict[str, Any]:
        """批量报工 - 一次报多个工序/工单"""
        shift = shift or _detect_shift()
        results = []
        total_good = 0
        total_defect = 0

        for item in items:
            result = await self.quick_report(
                factory_id=factory_id,
                work_order_id=item["work_order_id"],
                station_id=item["station_id"],
                good_qty=item.get("good_qty", 0),
                defect_qty=item.get("defect_qty", 0),
                scrap_qty=item.get("scrap_qty", 0),
                operator_id=operator_id or item.get("operator_id"),
                operation_seq=item.get("operation_seq"),
                operation_name=item.get("operation_name"),
                machine_id=item.get("machine_id"),
                cycle_time_sec=item.get("cycle_time_sec"),
                remark=item.get("remark"),
                shift=shift,
            )
            results.append(result)
            total_good += item.get("good_qty", 0)
            total_defect += item.get("defect_qty", 0) + item.get("scrap_qty", 0)

        return {
            "count": len(results),
            "total_good": total_good,
            "total_defect": total_defect,
            "shift": shift,
            "items": results,
        }

    # ==================== 报工撤回 ====================

    async def undo_report(self, report_id: str, undone_by: str) -> Dict[str, Any]:
        """撤回报工（5分钟内可撤）"""
        report = await self.db.get(ProductionReport, report_id)
        if not report:
            return {"error": "报工记录不存在"}

        if report.is_undone:
            return {"error": "该报工已撤回"}

        # 检查时间窗口（5分钟）
        elapsed = (datetime.utcnow() - report.created_at).total_seconds()
        if elapsed > 300:
            return {"error": "超过5分钟，无法撤回"}

        now = datetime.utcnow()
        report.is_undone = True
        report.undone_at = now
        report.undone_by = undone_by

        # 回滚工单数量
        wo = await self.db.get(WorkOrder, report.work_order_id)
        if wo:
            total = report.good_qty + report.defect_qty + report.scrap_qty
            wo.completed_qty = max(0, (wo.completed_qty or 0) - total)
            wo.good_qty = max(0, (wo.good_qty or 0) - report.good_qty)
            wo.defect_qty = max(0, (wo.defect_qty or 0) - report.defect_qty)
            wo.scrap_qty = max(0, (wo.scrap_qty or 0) - report.scrap_qty)

        await self.db.commit()
        return {"success": True, "report_code": report.report_code, "undone_at": now.isoformat()}

    # ==================== 班次汇总 ====================

    async def get_shift_summary(
        self,
        factory_id: str,
        shift_date: Optional[str] = None,
        shift_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取班次汇总数据"""
        target_date = date.fromisoformat(shift_date) if shift_date else date.today()
        target_shift = shift_type or _detect_shift()

        stmt = select(ShiftSummary).where(
            and_(
                ShiftSummary.factory_id == factory_id,
                ShiftSummary.shift_date == target_date,
                ShiftSummary.shift_type == target_shift,
            )
        )
        result = await self.db.execute(stmt)
        summaries = result.scalars().all()

        total_output = sum(s.total_output for s in summaries)
        total_good = sum(s.good_qty for s in summaries)
        total_defect = sum(s.defect_qty for s in summaries)
        total_scrap = sum(s.scrap_qty for s in summaries)
        yield_rate = (total_good / total_output * 100) if total_output > 0 else 0

        # 按工位分组
        by_station = {}
        for s in summaries:
            key = s.station_id or "unknown"
            if key not in by_station:
                by_station[key] = {"output": 0, "good": 0, "defect": 0, "reports": 0}
            by_station[key]["output"] += s.total_output
            by_station[key]["good"] += s.good_qty
            by_station[key]["defect"] += s.defect_qty + s.scrap_qty
            by_station[key]["reports"] += s.report_count

        return {
            "date": target_date.isoformat(),
            "shift": target_shift,
            "total_output": total_output,
            "good_qty": total_good,
            "defect_qty": total_defect + total_scrap,
            "yield_rate": round(yield_rate, 2),
            "report_count": sum(s.report_count for s in summaries),
            "stations": by_station,
            "details": [{
                "station_id": s.station_id,
                "work_order_id": s.work_order_id,
                "product_id": s.product_id,
                "output": s.total_output,
                "good": s.good_qty,
                "defect": s.defect_qty,
                "yield_rate": s.yield_rate,
                "achievement_rate": s.achievement_rate,
            } for s in summaries],
        }

    # ==================== 实时产出流 ====================

    async def get_realtime_feed(
        self,
        factory_id: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """实时产出流（最近N条报工）"""
        stmt = (
            select(ProductionReport)
            .where(
                and_(
                    ProductionReport.factory_id == factory_id,
                    ProductionReport.is_undone == False,
                )
            )
            .order_by(ProductionReport.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        reports = result.scalars().all()

        return {
            "items": [{
                "id": r.id,
                "report_code": r.report_code,
                "work_order_id": r.work_order_id,
                "station_id": r.station_id,
                "good_qty": r.good_qty,
                "defect_qty": r.defect_qty,
                "scrap_qty": r.scrap_qty,
                "operator_id": r.operator_id,
                "shift": r.shift,
                "operation_name": r.operation_name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            } for r in reports],
        }

    # ==================== 内部方法 ====================

    async def _update_shift_summary(
        self, factory_id, shift_type, station_id, work_order_id,
        good_qty, defect_qty, scrap_qty, cycle_time_sec, operator_id
    ):
        """更新班次汇总表（UPSERT）"""
        today = date.today()
        total = good_qty + defect_qty + scrap_qty
        yield_rate = (good_qty / total * 100) if total > 0 else 0

        # 查找现有记录
        stmt = select(ShiftSummary).where(
            and_(
                ShiftSummary.factory_id == factory_id,
                ShiftSummary.shift_date == today,
                ShiftSummary.shift_type == shift_type,
                ShiftSummary.station_id == station_id,
                ShiftSummary.work_order_id == work_order_id,
            )
        )
        result = await self.db.execute(stmt)
        summary = result.scalar_one_or_none()

        if summary:
            summary.total_output += total
            summary.good_qty += good_qty
            summary.defect_qty += defect_qty
            summary.scrap_qty += scrap_qty
            summary.total_output = summary.good_qty + summary.defect_qty + summary.scrap_qty
            summary.yield_rate = (summary.good_qty / summary.total_output * 100) if summary.total_output > 0 else 0
            summary.report_count += 1
            summary.total_cycle_time += (cycle_time_sec or 0)
            summary.updated_at = datetime.utcnow()
        else:
            summary = ShiftSummary(
                id=_gen_id(),
                factory_id=factory_id,
                shift_date=today,
                shift_type=shift_type,
                station_id=station_id,
                work_order_id=work_order_id,
                total_output=total,
                good_qty=good_qty,
                defect_qty=defect_qty,
                scrap_qty=scrap_qty,
                yield_rate=yield_rate,
                report_count=1,
                total_cycle_time=cycle_time_sec or 0,
                operator_count=1,
            )
            self.db.add(summary)

    async def _update_hourly_snapshot(self, factory_id, station_id, output_qty, good_qty, defect_qty):
        """更新小时产出快照"""
        now = datetime.utcnow()
        today = now.date()
        hour = now.hour

        stmt = select(HourlyOutputSnapshot).where(
            and_(
                HourlyOutputSnapshot.factory_id == factory_id,
                HourlyOutputSnapshot.snapshot_date == today,
                HourlyOutputSnapshot.snapshot_hour == hour,
                HourlyOutputSnapshot.station_id == station_id,
            )
        )
        result = await self.db.execute(stmt)
        snapshot = result.scalar_one_or_none()

        if snapshot:
            snapshot.output_qty += output_qty
            snapshot.good_qty += good_qty
            snapshot.defect_qty += defect_qty
        else:
            snapshot = HourlyOutputSnapshot(
                id=_gen_id(),
                factory_id=factory_id,
                snapshot_date=today,
                snapshot_hour=hour,
                station_id=station_id,
                output_qty=output_qty,
                good_qty=good_qty,
                defect_qty=defect_qty,
            )
            self.db.add(snapshot)

    async def _check_alerts(self, factory_id, station_id, work_order_id, good_qty, defect_qty, scrap_qty):
        """检查是否触发预警"""
        total = good_qty + defect_qty + scrap_qty
        if total == 0:
            return

        # 良品率低于 90% 触发预警
        yield_rate = good_qty / total * 100
        if yield_rate < 90 and total >= 5:  # 至少5件才有统计意义
            alert = ProductionAlert(
                id=_gen_id(),
                factory_id=factory_id,
                alert_type="yield_drop",
                severity="warning" if yield_rate >= 80 else "critical",
                title=f"良品率异常: {yield_rate:.1f}%",
                message=f"工位 {station_id} 本次报工良品率 {yield_rate:.1f}%（{good_qty}/{total}），低于阈值 90%",
                source_type="station",
                source_id=station_id,
                metric_value=yield_rate,
                threshold_value=90.0,
            )
            self.db.add(alert)
