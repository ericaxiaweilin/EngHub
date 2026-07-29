"""
QMS API Routes
检验管理、不良品管理 — 真实 DB 查询
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List, Dict
from pydantic import BaseModel
from datetime import datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User, QualityInspection, DefectRecord, Qms8dReport
from api.services.qms_service import QMSService as QmsService

router = APIRouter(prefix="/api/v1", tags=["qms"])


# --- Inspection Endpoints ---


@router.get("/inspections")
async def list_inspections(
    factory_id: str,
    inspection_type: Optional[str] = None,
    status: Optional[str] = None,
    work_order_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取检验单列表"""
    query = select(QualityInspection).where(QualityInspection.factory_id == factory_id)
    
    # NOTE: 软删除过滤 - 待数据库迁移后生效 (需给 QualityInspection 添加 is_deleted BOOLEAN DEFAULT false 列)
    # query = query.where(QualityInspection.is_deleted == False)

    if inspection_type:
        query = query.where(QualityInspection.inspect_type == inspection_type.upper())
    if status:
        query = query.where(QualityInspection.result == status.upper())
    if work_order_id:
        query = query.where(QualityInspection.work_order_id == work_order_id)

    # 总数
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # 分页
    query = query.order_by(QualityInspection.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    return {
        "items": [
            {
                "id": r.id,
                "inspection_code": f"INS-{r.inspect_type}-{r.id[:8]}",
                "inspection_type": r.inspect_type.lower(),
                "work_order_id": r.work_order_id,
                "routing_step_id": r.routing_step_id,
                "inspector_id": r.inspector_id,
                "sample_size": r.sample_qty,
                "batch_size": r.sample_qty,
                "defect_qty": r.defect_qty,
                "good_qty": r.sample_qty - r.defect_qty,
                "status": r.result.lower(),
                "overall_result": r.result,
                "defect_details": r.defect_details,
                "remark": r.remark,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
    }


@router.get("/inspections/{inspection_id}")
async def get_inspection(
    inspection_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取检验单详情"""
    r = await db.get(QualityInspection, inspection_id)
    if not r:
        raise HTTPException(status_code=404, detail="检验单不存在")
    return {
        "id": r.id,
        "inspection_code": f"INS-{r.inspect_type}-{r.id[:8]}",
        "inspection_type": r.inspect_type.lower(),
        "factory_id": r.factory_id,
        "work_order_id": r.work_order_id,
        "routing_step_id": r.routing_step_id,
        "inspector_id": r.inspector_id,
        "sample_size": r.sample_qty,
        "batch_size": r.sample_qty,
        "defect_qty": r.defect_qty,
        "good_qty": r.sample_qty - r.defect_qty,
        "status": r.result.lower(),
        "overall_result": r.result,
        "defect_details": r.defect_details,
        "remark": r.remark,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


# --- Defect Endpoints ---


class DispositionSubmit(BaseModel):
    disposition: str  # rework, repair, scrap, concession, return
    disposition_qty: Optional[int] = None
    remark: Optional[str] = None


@router.get("/defects")
async def list_defects(
    factory_id: str,
    status: Optional[str] = None,
    defect_type: Optional[str] = None,
    severity: Optional[str] = None,
    work_order_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取不良品列表"""
    query = select(DefectRecord).where(DefectRecord.factory_id == factory_id)
    
    # NOTE: 软删除过滤 - 待数据库迁移后生效 (需给 DefectRecord 添加 is_deleted BOOLEAN DEFAULT false 列)
    # query = query.where(DefectRecord.is_deleted == False)

    if defect_type:
        query = query.where(DefectRecord.defect_type == defect_type)
    if severity:
        query = query.where(DefectRecord.severity == severity)
    if work_order_id:
        query = query.where(DefectRecord.work_order_id == work_order_id)
    if status:
        # status 映射: open=未处置, resolved=已处置
        if status == "open":
            query = query.where(DefectRecord.disposition.is_(None))
        elif status == "resolved":
            query = query.where(DefectRecord.disposition.isnot(None))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(DefectRecord.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    return {
        "items": [_serialize_defect(r) for r in rows],
        "total": total,
    }


@router.get("/defects/statistics")
async def get_defect_statistics(
    factory_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """不良品统计"""
    query = select(DefectRecord).where(DefectRecord.factory_id == factory_id)
    result = await db.execute(query)
    rows = list(result.scalars().all())

    by_type: dict = {}
    by_station: dict = {}
    total_qty = 0
    for r in rows:
        total_qty += r.quantity
        by_type[r.defect_type] = by_type.get(r.defect_type, 0) + r.quantity
        sid = r.station_id or "unknown"
        by_station[sid] = by_station.get(sid, 0) + r.quantity

    return {
        "total_defects": len(rows),
        "total_defect_qty": total_qty,
        "by_type": by_type,
        "by_station": by_station,
    }


@router.get("/defects/{defect_id}")
async def get_defect(
    defect_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取不良品详情"""
    r = await db.get(DefectRecord, defect_id)
    if not r:
        raise HTTPException(status_code=404, detail="不良品记录不存在")
    return _serialize_defect(r)


@router.post("/defects/{defect_id}/disposition")
async def submit_disposition(
    defect_id: str,
    disposition: DispositionSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交处置方案"""
    r = await db.get(DefectRecord, defect_id)
    if not r:
        raise HTTPException(status_code=404, detail="不良品记录不存在")

    r.disposition = disposition.disposition
    r.disposition_by = current_user.username if current_user else "system"
    r.disposition_at = datetime.utcnow()
    r.disposition_remark = disposition.remark
    r.is_finalized = True
    r.updated_at = datetime.utcnow()
    await db.commit()

    return _serialize_defect(r)


@router.post("/defects/{defect_id}/process")
async def process_defect(
    defect_id: str,
    disposition: DispositionSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """处理不良品（兼容前端 process 接口）"""
    return await submit_disposition(defect_id, disposition, db, current_user)


@router.patch("/defects/{defect_id}")
async def update_defect_ocap(
    defect_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新缺陷OCAP信息 - 前端 OcapDetail 调用"""
    r = await db.get(DefectRecord, defect_id)
    if not r:
        raise HTTPException(status_code=404, detail="不良品记录不存在")
    
    # OCAP 字段更新
    ocap_fields = [
        "ocap_status", "ocap_trigger_reason", "root_cause",
        "corrective_action", "preventive_action", "responsible_dept",
        "severity", "defect_type", "description"
    ]
    for field in ocap_fields:
        if field in data and data[field] is not None:
            setattr(r, field, data[field])
    
    r.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(r)
    
    return _serialize_defect(r)


# ============== DELETE Endpoints (Soft Delete) ==============


@router.delete("/defects/{defect_id}")
async def delete_defect(
    defect_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """软删除缺陷记录（标记为已删除，逻辑过滤查询）"""
    from api.services.qms_service import QMSService
    
    try:
        qms = QMSService(db)
        result = await qms.soft_delete_defect(defect_id, current_user.username if current_user else "system")
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result["message"])
        return {"message": result["message"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"缺陷删除失败: {str(e)}")


@router.delete("/inspections/{inspection_id}")
async def delete_inspection(
    inspection_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """软删除检验记录（标记为已删除，逻辑过滤查询）"""
    from api.services.qms_service import QMSService
    
    try:
        qms = QMSService(db)
        result = await qms.soft_delete_inspection(inspection_id, current_user.username if current_user else "system")
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result["message"])
        return {"message": result["message"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检验删除失败: {str(e)}")


def _serialize_defect(r: DefectRecord) -> dict:
    """序列化缺陷记录，字段对齐前端 Defect 接口 + 完整品质追溯"""
    return {
        "id": r.id,
        "defect_code": r.record_code,
        "record_code": r.record_code,
        "factory_id": r.factory_id,
        "work_order_id": r.work_order_id,
        "production_report_id": r.production_report_id,
        "product_id": r.product_id,
        "material_id": r.material_id,
        "batch_code": r.batch_code,
        "station_id": r.station_id,
        "equipment_id": r.equipment_id,
        "defect_type": r.defect_type,
        "severity": r.severity,
        "quantity": r.quantity,
        "defect_qty": r.quantity,
        # 品质追溯
        "defect_source": r.defect_source,
        "root_cause_category": r.root_cause_category,
        "root_cause": r.root_cause,
        "responsible_dept": r.responsible_dept,
        "discovery_stage": r.discovery_stage,
        "discovery_time": r.discovery_time.isoformat() if r.discovery_time else None,
        "defect_location": r.defect_location,
        "inspection_id": r.inspection_id,
        "process_step": r.process_step,
        # 处置
        "disposition": r.disposition,
        "disposition_by": r.disposition_by,
        "disposition_at": r.disposition_at.isoformat() if r.disposition_at else None,
        "disposition_remark": r.disposition_remark,
        "corrective_action": r.corrective_action,
        "preventive_action": r.preventive_action,
        # 评审/状态
        "ocap_status": r.ocap_status,
        "review_status": r.review_status,
        "reviewed_by": r.reviewed_by,
        "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
        "description": r.description,
        "status": "resolved" if r.disposition else "open",
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


__all__ = ["router"]


# ============== 增强端点（019）==============


class InspectionItemCreate(BaseModel):
    item_name: str
    item_code: Optional[str] = None
    spec_lower: Optional[float] = None
    spec_upper: Optional[float] = None
    target_value: Optional[float] = None
    measurement_method: Optional[str] = None
    remark: Optional[str] = None


class InspectionCreate(BaseModel):
    factory_id: str
    work_order_id: str
    inspect_type: str  # IQC/IPQC/FQC/OQC
    routing_step_id: str = "general"
    inspection_phase: Optional[str] = None
    sample_qty: int = 5
    sampling_method: Optional[str] = None
    check_tool_id: Optional[str] = None
    items: List[InspectionItemCreate] = []
    remark: Optional[str] = None


class InspectionItemResult(BaseModel):
    item_id: str
    measured_value: Optional[float] = None
    result: Optional[str] = None


class InspectionSubmit(BaseModel):
    items_result: List[InspectionItemResult]
    defect_qty: int = 0


class SpcPointCreate(BaseModel):
    factory_id: str
    characteristic_code: str
    measured_value: float
    characteristic_name: Optional[str] = None
    work_order_id: Optional[str] = None
    station_id: Optional[str] = None
    sample_group: Optional[int] = None
    control_chart_type: str = "xbar"
    calculation_method: str = "three_sigma"
    subgroup_count: Optional[int] = None


class EightDCreate(BaseModel):
    factory_id: str
    title: str
    defect_record_id: Optional[str] = None
    severity: str = "major"


class EightDUpdate(BaseModel):
    step: str  # d1-d8
    content: str


@router.post("/inspections")
async def create_inspection(
    req: InspectionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建检验单"""
    svc = QmsService(db)
    result = await svc.create_inspection(
        factory_id=req.factory_id,
        work_order_id=req.work_order_id,
        routing_step_id=req.routing_step_id,
        inspect_type=req.inspect_type,
        inspection_phase=req.inspection_phase,
        inspector_id=current_user.username,
        sample_qty=req.sample_qty,
        sampling_method=req.sampling_method,
        check_tool_id=req.check_tool_id,
        items=[i.dict() for i in req.items],
        remark=req.remark,
    )
    return result


@router.post("/inspections/{inspection_id}/submit")
async def submit_inspection(
    inspection_id: str,
    req: InspectionSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交检验结果"""
    svc = QmsService(db)
    result = await svc.submit_inspection_result(
        inspection_id=inspection_id,
        items_result=[i.dict() for i in req.items_result],
        defect_qty=req.defect_qty,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.get("/qms/spc")
async def get_spc_chart(
    factory_id: str,
    characteristic_code: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SPC 控制图数据"""
    svc = QmsService(db)
    return await svc.get_spc_chart(factory_id, characteristic_code, limit)


@router.post("/qms/spc")
async def record_spc_point(
    req: SpcPointCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录 SPC 数据点"""
    svc = QmsService(db)
    return await svc.record_spc_point(
        factory_id=req.factory_id,
        characteristic_code=req.characteristic_code,
        measured_value=req.measured_value,
        characteristic_name=req.characteristic_name,
        work_order_id=req.work_order_id,
        station_id=req.station_id,
        sample_group=req.sample_group,
        control_chart_type=req.control_chart_type,
        calculation_method=req.calculation_method,
        subgroup_count=req.subgroup_count,
        measured_by=current_user.username,
    )


@router.get("/qms/8d")
async def list_8d_reports(
    factory_id: str,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """8D 报告列表"""
    query = select(Qms8dReport).where(Qms8dReport.factory_id == factory_id)
    if status:
        query = query.where(Qms8dReport.status == status)
    query = query.order_by(Qms8dReport.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    reports = result.scalars().all()

    return {
        "total": total,
        "items": [
            {
                "id": r.id, "report_code": r.report_code, "title": r.title,
                "severity": r.severity, "status": r.status,
                "defect_record_id": r.defect_record_id,
                "d1_team": r.d1_team, "d2_problem_description": r.d2_problem_description,
                "d3_containment_action": r.d3_containment_action,
                "d4_root_cause": r.d4_root_cause,
                "d5_corrective_action": r.d5_corrective_action,
                "d6_implementation": r.d6_implementation,
                "d7_preventive_action": r.d7_preventive_action,
                "d8_congratulations": r.d8_congratulations,
                "opened_by": r.opened_by, "closed_by": r.closed_by,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
    }


@router.post("/qms/8d")
async def create_8d_report(
    req: EightDCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建 8D 报告"""
    svc = QmsService(db)
    return await svc.create_8d(
        factory_id=req.factory_id,
        title=req.title,
        defect_record_id=req.defect_record_id,
        severity=req.severity,
        opened_by=current_user.username,
    )


@router.put("/qms/8d/{report_id}")
async def update_8d_report(
    report_id: str,
    req: EightDUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新 8D 步骤"""
    svc = QmsService(db)
    result = await svc.update_8d_step(report_id, req.step, req.content)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.post("/qms/8d/{report_id}/close")
async def close_8d_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """关闭 8D 报告"""
    svc = QmsService(db)
    result = await svc.close_8d(report_id, closed_by=current_user.username)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.get("/qms/dashboard")
async def quality_dashboard(
    factory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """质量看板"""
    svc = QmsService(db)
    return await svc.get_quality_dashboard(factory_id)


# ============== 质量目标 (ERPNext 参考) ==============


@router.get("/qms/goals")
async def list_quality_goals(
    factory_id: str,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """质量目标列表"""
    from database.models import QualityGoal
    stmt = select(QualityGoal).where(QualityGoal.factory_id == factory_id)
    if status:
        stmt = stmt.where(QualityGoal.status == status)
    stmt = stmt.order_by(QualityGoal.created_at.desc())
    result = await db.execute(stmt)
    goals = result.scalars().all()
    return {"items": [{
        "id": g.id, "goal_code": g.goal_code, "goal_name": g.goal_name,
        "metric_type": g.metric_type, "target_value": g.target_value,
        "current_value": g.current_value, "unit": g.unit, "period": g.period,
        "responsible": g.responsible, "status": g.status,
        "last_reviewed_at": g.last_reviewed_at.isoformat() if g.last_reviewed_at else None,
    } for g in goals]}


@router.post("/qms/goals")
async def create_quality_goal(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建质量目标"""
    import uuid
    from datetime import datetime, timedelta
    from database.models import QualityGoal
    goal = QualityGoal(
        id=str(uuid.uuid4()),
        factory_id=body.get("factory_id", "F001"),
        goal_code=f"QG-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:4].upper()}",
        goal_name=body["goal_name"],
        metric_type=body["metric_type"],
        target_value=float(body["target_value"]),
        unit=body.get("unit", "%"),
        period=body.get("period", "monthly"),
        responsible=body.get("responsible"),
        review_frequency_days=body.get("review_frequency_days", 30),
        next_review_at=datetime.utcnow() + timedelta(days=body.get("review_frequency_days", 30)),
    )
    db.add(goal)
    await db.commit()
    return {"success": True, "id": goal.id, "goal_code": goal.goal_code}


@router.post("/qms/goals/{goal_id}/review")
async def review_quality_goal(
    goal_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """评审质量目标"""
    goal = await db.get(QualityGoal, goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="质量目标不存在")
    goal.status = "reviewed"
    goal.reviewed_at = datetime.utcnow()
    goal.reviewed_by = current_user.username if current_user else "system"
    await db.commit()
    return {"success": True, "message": "质量目标已评审"}


# --- IQC 来料检验专属接口 ---

class IQCCreateRequest(BaseModel):
    """IQ C 创建请求体"""
    inbound_order_id: str
    factory_id: str
    supplier_id: str
    product_id: str
    product_name: str
    quantity_received: int
    batch_no: str
    inspector_id: str
    sample_size: Optional[int] = None


class IQCStartRequest(BaseModel):
    """开始检验请求"""
    inspector_id: str


class IQCCompleteRequest(BaseModel):
    """完成检验请求"""
    result: str  # PASS or FAIL
    sample_inspected: int
    defects: Optional[List[Dict]] = None


class IQCDIsposalRequest(BaseModel):
    """处置请求"""
    disposition: str  # accept, reject, use_as_is
    by: str


@router.post("/iqc/create")
async def create_iqc_request(
    body: IQCCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建IQ C记录（收货后触发）"""
    from api.services.qms_service import QMSService
    qms = QMSService()
    
    try:
        record = await qms.create_iqc_record(
            inbound_order_id=body.inbound_order_id,
            factory_id=body.factory_id,
            supplier_id=body.supplier_id,
            product_id=body.product_id,
            product_name=body.product_name,
            quantity_received=body.quantity_received,
            batch_no=body.batch_no,
            inspector_id=body.inspector_id,
            sample_size=body.sample_size,
        )
        return {"success": True, "data": record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/iqc/{inspection_id}/start")
async def start_iqc_inspection(
    inspection_id: str,
    body: IQCStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """开始IQ C检验"""
    from api.services.qms_service import QMSService
    qms = QMSService()
    
    success = await qms.start_iqc_inspection(inspection_id, body.inspector_id)
    if not success:
        raise HTTPException(status_code=400, detail="无法开始检验：检验不存在或状态不正确")
    
    return {"success": True, "message": "检验已开始"}

@router.put("/iqc/{inspection_id}/complete")
async def complete_iqc_inspection(
    inspection_id: str,
    body: IQCCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """完成IQ C检验并记录结果"""
    from api.services.qms_service import QMSService
    qms = QMSService()
    
    success = await qms.complete_iqc_inspection(
        inspection_id=inspection_id,
        result=body.result,
        sample_inspected=body.sample_inspected,
        defects=body.defects,
    )
    if not success:
        raise HTTPException(status_code=400, detail="无法完成检验：检验不存在或状态不正确")
    
    return {"success": True, "message": "检验已完成", "result": body.result}

@router.post("/iqc/{inspection_id}/dispose")
async def dispose_iqc_record(
    inspection_id: str,
    body: IQCDIsposalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """处置IQ C记录"""
    from api.services.qms_service import QMSService
    qms = QMSService()
    
    success = await qms.dispose_iqc_record(
        inspection_id=inspection_id,
        disposition=body.disposition,
        by=body.by,
    )
    if not success:
        raise HTTPException(status_code=400, detail="无法处置：检验未完成")
    
    return {"success": True, "message": "处置完成", "disposition": body.disposition}

@router.get("/iqc/stats")
async def get_iqc_stats(
    factory_id: str = Query(..., description="工厂ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取IQ C统计信息"""
    from api.services.qms_service import QMSService
    qms = QMSService()
    
    stats = await qms.get_iqc_statistics(factory_id)
    return {"success": True, "data": stats}


# --- FAI 首件检验专属接口 ---

class FAICreateRequest(BaseModel):
    """FAI 创建请求体"""
    work_order_id: str
    factory_id: str
    product_id: str
    product_name: str
    batch_no: str
    machine_id: str
    operator_id: str
    inspector_id: str
    fail_level: str = "level2"
    structure: str = "manual"
    sample_qty: int = 1


@router.post("/fai/create")
async def create_fai_request(
    body: FAICreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建首件检验记录"""
    from api.services.qms_service import QMSService
    qms = QMSService(db)  # 传递db会话
    
    try:
        record = await qms.create_fai_record(
            work_order_id=body.work_order_id,
            factory_id=body.factory_id,
            product_id=body.product_id,
            product_name=body.product_name,
            batch_no=body.batch_no,
            machine_id=body.machine_id,
            operator_id=body.operator_id,
            inspector_id=body.inspector_id,
            fail_level=body.fail_level,
            structure=body.structure,
            sample_qty=body.sample_qty,
        )
        return {"success": True, "data": record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fai/list")
async def list_fai_records(
    factory_id: str = Query(..., description="工厂ID"),
    work_order_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出首件检验记录列表"""
    from api.services.qms_service import QMSService
    qms = QMSService(db)
    
    records = await qms.list_fai_records(factory_id, work_order_id, status)  # 需要实现该方法
    return {"success": True, "data": records}


@router.get("/fai/{fai_id}")
async def get_fai_record(fai_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取首件检验详情"""
    from api.services.qms_service import QMSService
    qms = QMSService(db)
    
    record = await qms.get_fai_record(fai_id)
    if not record:
        raise HTTPException(status_code=404, detail="FAI记录不存在")
    return {"success": True, "data": record}


# --- IPC 制程巡检专属接口 ---

class IPCCreateRequest(BaseModel):
    """IPC 创建请求体"""
    work_order_id: str
    factory_id: str
    product_id: str
    process_stage: str
    frequency_type: str = "time_based"
    frequency_value: int = 60
    operator_id: str = ""
    inspector_id: str = ""
    check_items: Optional[List[Dict]] = None


@router.post("/ipc/create")
async def create_ipc_request(
    body: IPCCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建IPC巡检记录"""
    from api.services.qms_service import QMSService
    qms = QMSService()
    
    try:
        record = await qms.create_ipc_record(
            work_order_id=body.work_order_id,
            factory_id=body.factory_id,
            product_id=body.product_id,
            process_stage=body.process_stage,
            frequency_type=body.frequency_type,
            frequency_value=body.frequency_value,
            operator_id=body.operator_id,
            inspector_id=body.inspector_id,
            check_items=body.check_items,
        )
        return {"success": True, "data": record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ipc/list")
async def list_ipc_records(
    factory_id: str = Query(..., description="工厂ID"),
    work_order_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出IPC巡检记录列表"""
    from api.services.qms_service import QMSService
    qms = QMSService()
    
    records = await qms.list_ipc_records(factory_id, limit=50)
    return {"success": True, "data": records}


@router.get("/ipc/{ipc_id}")
async def get_ipc_record(ipc_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取IPC检验详情"""
    from api.services.qms_service import QMSService
    qms = QMSService(db)
    
    record = await qms.get_ipc_record(ipc_id)  # 需要实现该方法
    if not record:
        raise HTTPException(status_code=404, detail="IPC记录不存在")
    return {"success": True, "data": record}


# --- OQC 出货检验专属接口 ---

class OQCCreateRequest(BaseModel):
    """OQC 创建请求体"""
    order_id: str
    customer_id: str
    product_id: str
    product_name: str
    batch_no: str
    quantity_to_ship: int
    inspector_id: str
    check_items: Optional[List[Dict]] = None


@router.post("/oqc/create")
async def create_oqc_request(
    body: OQCCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建出货检验记录"""
    from api.services.qms_service import QMSService
    qms = QMSService()
    
    try:
        record = await qms.create_oqc_record(
            order_id=body.order_id,
            customer_id=body.customer_id,
            product_id=body.product_id,
            product_name=body.product_name,
            batch_no=body.batch_no,
            quantity_to_ship=body.quantity_to_ship,
            inspector_id=body.inspector_id,
            check_items=body.check_items,
        )
        return {"success": True, "data": record}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/oqc/list")
async def list_oqc_records(
    customer_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出出货检验记录列表"""
    from api.services.qms_service import QMSService
    qms = QMSService(db)
    
    records = await qms.list_oqc_records(customer_id)
    return {"success": True, "data": records}


# --- CAPA 纠正预防措施专属接口 ---

class CAPACreateRequest(BaseModel):
    """CAPA创建请求体"""
    title: str
    severity: str  # critical/major/minor
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    creator: str = "system"


@router.post("/capa/create")
async def create_capa_request(
    body: CAPACreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建CAPA案件"""
    from api.services.qms_service import QMSService
    qms = QMSService()
    
    try:
        case = await qms.create_capa_case(
            title=body.title,
            severity=body.severity,
            source_type=body.source_type,
            source_id=body.source_id,
            creator=current_user.username if current_user else body.creator,
        )
        return {"success": True, "data": case}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cases/{case_id}")
async def get_capa_case(case_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取CAPA案件详情"""
    from api.services.qms_service import QMSService
    qms = QMSService(db)
    
    case = qms.get_capa_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="CAPA案件不存在")
    return {"success": True, "data": case}

@router.get("/cases/list")
async def list_capa_cases(
    factory_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出CAPA案件列表"""
    from api.services.qms_service import QMSService
    qms = QMSService(db)
    
    cases = qms.list_capa_cases(factory_id, status)
    return {"success": True, "data": cases}
