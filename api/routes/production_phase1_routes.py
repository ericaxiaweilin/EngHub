"""
岗位替代 Phase 1 路由 - 报工终端 / 实时看板 / 报表中心
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession
from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user

from api.services.report_service import ReportService
from api.services.dashboard_service import DashboardService
from api.services.report_generator_service import ReportGeneratorService

router = APIRouter(prefix="/api/v1", tags=["production-phase1"])


# ==================== Request Models ====================

class QuickReportRequest(BaseModel):
    factory_id: str
    work_order_id: str
    station_id: str
    good_qty: int
    defect_qty: int = 0
    scrap_qty: int = 0
    operator_id: Optional[str] = None
    operation_seq: Optional[int] = None
    operation_name: Optional[str] = None
    machine_id: Optional[str] = None
    cycle_time_sec: Optional[float] = None
    remark: Optional[str] = None
    shift: Optional[str] = None
    report_date: Optional[datetime] = None  # 可选报工日期（补录）
    assistant_operator_ids: Optional[List[str]] = None  # 协作人员工号（小组报工）


class BatchReportItem(BaseModel):
    work_order_id: str
    station_id: str
    good_qty: int = 0
    defect_qty: int = 0
    scrap_qty: int = 0
    operator_id: Optional[str] = None
    operation_seq: Optional[int] = None
    operation_name: Optional[str] = None
    machine_id: Optional[str] = None
    cycle_time_sec: Optional[float] = None
    remark: Optional[str] = None
    report_date: Optional[datetime] = None
    assistant_operator_ids: Optional[List[str]] = None


class BatchReportRequest(BaseModel):
    factory_id: str
    items: List[BatchReportItem]
    operator_id: Optional[str] = None
    shift: Optional[str] = None
    report_date: Optional[datetime] = None  # 批量统一报工日期（可被行内 report_date 覆盖）
    assistant_operator_ids: Optional[List[str]] = None  # 批量统一协作人员（可被行内覆盖）


# ==================== 报工终端 ====================


@router.post("/reports/self-service")
async def self_service_report(
    factory_id: str = Query(...),
    work_order_code: str = Query(..., description="扫码获取的工单号"),
    good_qty: int = Query(..., ge=0),
    defect_qty: int = Query(0, ge=0),
    scrap_qty: int = Query(0, ge=0),
    station_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """操作工扫码自助报工（消除生产文员）

    操作工自己扫码→填数→提交，不需要文员转录纸质报工条。
    系统自动：校验→更新工单→判断完工→异常升级通知主管。
    """
    svc = ReportService(db)
    return await svc.self_service_report(
        factory_id=factory_id,
        work_order_code=work_order_code,
        good_qty=good_qty,
        defect_qty=defect_qty,
        scrap_qty=scrap_qty,
        station_id=station_id,
        operator_id=current_user.username if current_user else None,
    )


@router.post("/reports/quick")
async def quick_report(
    req: QuickReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """快速报工（3秒完成）"""
    svc = ReportService(db)
    result = await svc.quick_report(
        factory_id=req.factory_id,
        work_order_id=req.work_order_id,
        station_id=req.station_id,
        good_qty=req.good_qty,
        defect_qty=req.defect_qty,
        scrap_qty=req.scrap_qty,
        operator_id=req.operator_id or current_user.username,
        operation_seq=req.operation_seq,
        operation_name=req.operation_name,
        machine_id=req.machine_id,
        cycle_time_sec=req.cycle_time_sec,
        remark=req.remark,
        shift=req.shift,
        report_date=req.report_date,
        assistant_operator_ids=req.assistant_operator_ids,
    )
    return result


@router.post("/reports/batch")
async def batch_report(
    req: BatchReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批量报工"""
    svc = ReportService(db)
    items = [item.dict() for item in req.items]
    result = await svc.batch_report(
        factory_id=req.factory_id,
        items=items,
        operator_id=req.operator_id or current_user.username,
        shift=req.shift,
        report_date=req.report_date,
        assistant_operator_ids=req.assistant_operator_ids,
    )
    return result


@router.post("/reports/{report_id}/undo")
async def undo_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """撤回报工（5分钟内）"""
    svc = ReportService(db)
    result = await svc.undo_report(report_id, undone_by=current_user.username)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/reports/realtime")
async def realtime_feed(
    factory_id: str = Query(...),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """实时产出流"""
    svc = ReportService(db)
    return await svc.get_realtime_feed(factory_id, limit)


@router.get("/reports/shift-summary")
async def shift_summary(
    factory_id: str = Query(...),
    shift_date: Optional[str] = None,
    shift_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """班次汇总"""
    svc = ReportService(db)
    return await svc.get_shift_summary(factory_id, shift_date, shift_type)


# ==================== 实时看板 ====================

@router.get("/dashboard/live")
async def live_dashboard(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """实时看板主数据"""
    svc = DashboardService(db)
    return await svc.get_live_dashboard(factory_id)


@router.get("/dashboard/hourly-trend")
async def hourly_trend(
    factory_id: str = Query(...),
    target_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """小时产出趋势"""
    svc = DashboardService(db)
    return await svc.get_hourly_trend(factory_id, target_date)


@router.get("/dashboard/station-grid")
async def station_grid(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """工位状态矩阵"""
    svc = DashboardService(db)
    return await svc.get_station_grid(factory_id)


@router.get("/dashboard/top-issues")
async def top_issues(
    factory_id: str = Query(...),
    limit: int = Query(default=10),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Top 异常"""
    svc = DashboardService(db)
    return await svc.get_top_issues(factory_id, limit)


@router.post("/dashboard/alerts/{alert_id}/read")
async def mark_alert_read(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """标记预警已读"""
    svc = DashboardService(db)
    return await svc.mark_alert_read(alert_id)


@router.post("/dashboard/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """解决预警"""
    svc = DashboardService(db)
    return await svc.resolve_alert(alert_id, resolved_by=current_user.username)


# ==================== 报表中心 ====================

@router.get("/reports-center/daily")
async def daily_report(
    factory_id: str = Query(...),
    date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """日报（含异常标注）"""
    svc = ReportGeneratorService(db)
    report = await svc.generate_daily_report(factory_id, date)
    anomalies = await svc.detect_anomalies(report)
    report["anomalies"] = anomalies
    report["anomaly_count"] = len(anomalies)
    return report


@router.get("/reports-center/weekly")
async def weekly_report(
    factory_id: str = Query(...),
    week: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """周报"""
    svc = ReportGeneratorService(db)
    return await svc.generate_weekly_report(factory_id, week)


@router.get("/reports-center/monthly")
async def monthly_report(
    factory_id: str = Query(...),
    month: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """月报"""
    svc = ReportGeneratorService(db)
    return await svc.generate_monthly_report(factory_id, month)


@router.get("/reports-center/custom")
async def custom_report(
    factory_id: str = Query(...),
    start: str = Query(...),
    end: str = Query(...),
    group_by: str = Query(default="station"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """自定义查询"""
    svc = ReportGeneratorService(db)
    return await svc.custom_query(factory_id, start, end, group_by)
