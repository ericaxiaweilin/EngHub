"""
岗位替代路由 - 调度员/采购员/工艺员
核心理念：这些岗位可以被系统替代，只有例外才需要人
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any, List

from database.db_config import get_db
from core.auth.security import get_current_user
from database.models import User

router = APIRouter(prefix="/api/v1", tags=["role-elimination"])


# ==================== 调度员/车间主任替代 ====================


@router.post("/dispatch/auto-assign")
async def auto_dispatch(
    factory_id: str = Query(...),
    station_id: Optional[str] = Query(None, description="指定工位（空=全部空闲工位）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """事件驱动自派发（替代调度员手动派工）

    系统自动将最高优先级工单分配到空闲工位。
    调度员岗位替代：不需要人盯着看哪个工位空了。
    """
    from api.services.dispatch_service import auto_dispatch_station
    return await auto_dispatch_station(db, factory_id, station_id)


@router.post("/dispatch/exception-reschedule")
async def exception_reschedule(
    factory_id: str = Query(...),
    equipment_id: str = Query(..., description="故障设备ID"),
    reason: str = Query("设备故障", description="原因"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """设备异常自动重排（替代调度员电话调单）

    设备故障 → 自动释放受影响工单 → 重新派发到可用工位。
    """
    from api.services.dispatch_service import exception_reschedule as _reschedule
    return await _reschedule(db, factory_id, equipment_id, reason)


@router.get("/dispatch/shift-handover")
async def shift_handover(
    factory_id: str = Query(...),
    shift: str = Query("day", description="day/night"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """交接班自动报告（替代调度员写交接记录）"""
    from api.services.dispatch_service import shift_handover_report
    return await shift_handover_report(db, factory_id, shift)


@router.get("/dispatch/line-balance")
async def line_balance(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """产线平衡分析（替代车间主任看瓶颈）"""
    from api.services.dispatch_service import line_balance as _lb
    return await _lb(db, factory_id)


# ==================== 采购员替代 ====================


@router.post("/procurement/auto-pr")
async def auto_pr_from_mrp(
    factory_id: str = Query(...),
    mrp_results: List[Dict[str, Any]] = [],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """MRP→自动生成采购申请（替代采购员手动填PR）"""
    from api.services.procurement_service import ProcurementService
    svc = ProcurementService(db)
    return await svc.auto_pr_from_mrp(factory_id, mrp_results)


@router.get("/procurement/compare-suppliers")
async def compare_suppliers(
    material_code: str = Query(...),
    qty: float = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """自动比价（替代采购员打电话问价）

    权重：价格50% + 交期30% + 评分20%
    """
    from api.services.procurement_service import ProcurementService
    svc = ProcurementService(db)
    return await svc.compare_suppliers(material_code, qty)


@router.post("/procurement/auto-po")
async def auto_create_po(
    factory_id: str = Query(...),
    pr_id: str = Query(..., description="采购申请ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """PR→自动比价→自动下单（替代采购员选供应商+下PO）

    金额<5000 且 有合格供应商 → 全自动
    金额≥5000 → 推荐供应商，待人工确认
    """
    from api.services.procurement_service import ProcurementService
    svc = ProcurementService(db)
    return await svc.auto_create_po(factory_id, pr_id)


@router.get("/procurement/overdue")
async def procurement_overdue(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """到货跟催（替代采购员记着打电话催货）"""
    from api.services.procurement_service import ProcurementService
    svc = ProcurementService(db)
    return await svc.overdue_tracking(factory_id)


@router.get("/procurement/supplier-scorecard")
async def supplier_scorecard(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """供应商绩效自动评分（替代采购员做评估表）"""
    from api.services.procurement_service import ProcurementService
    svc = ProcurementService(db)
    return await svc.supplier_scorecard(factory_id)


# ==================== 工艺员替代 ====================


@router.get("/process/auto-match-routing")
async def auto_match_routing(
    factory_id: str = Query(...),
    product_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """产品→自动匹配工艺路线（替代工艺员翻模板库）"""
    from api.services.process_engineering_service import ProcessEngineeringService
    svc = ProcessEngineeringService(db)
    return await svc.auto_match_routing(factory_id, product_id)


@router.get("/process/recommend-params")
async def recommend_params(
    material_type: str = Query(..., description="材料类型（aluminum/steel/plastic）"),
    process_type: str = Query(..., description="工序类型（cnc/injection/reflow）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """材料+工序→推荐加工参数（替代工艺员翻手册）"""
    from api.services.process_engineering_service import ProcessEngineeringService
    svc = ProcessEngineeringService(db)
    return await svc.recommend_parameters(material_type, process_type)


@router.post("/process/ecn")
async def create_ecn(
    factory_id: str = Query(...),
    title: str = Query(...),
    change_type: str = Query("process", description="process/material/parameter/design"),
    affected_product: str = Query(...),
    description: str = Query(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建工程变更单ECN"""
    from api.services.process_engineering_service import ProcessEngineeringService
    svc = ProcessEngineeringService(db)
    return await svc.create_ecn(factory_id, title, change_type, affected_product, description,
                                created_by=current_user.username if current_user else "system")


@router.post("/process/ecn/{ecn_id}/propagate")
async def propagate_ecn(
    ecn_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """ECN自动传播到在制工单（替代工艺员逐个通知车间）"""
    from api.services.process_engineering_service import ProcessEngineeringService
    svc = ProcessEngineeringService(db)
    return await svc.propagate_ecn(ecn_id)


@router.post("/process/suggest-routing")
async def suggest_routing(
    factory_id: str = Query(...),
    product_features: Dict[str, Any] = {},
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """根据产品特征推荐工艺路线（替代工艺员从零编制）"""
    from api.services.process_engineering_service import ProcessEngineeringService
    svc = ProcessEngineeringService(db)
    return await svc.suggest_routing(factory_id, product_features)


# ==================== 跟单文员/销售文员完全消除 ====================


@router.get("/order-tracking/track")
async def track_order(
    factory_id: str = Query(...),
    order_code: str = Query(..., description="销售订单号"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """订单全链路进度追踪（替代跟单员查系统→回复客户）

    客户/销售问“我的货到哪了” → 系统自动回答。
    """
    from api.services.order_tracking_service import OrderTrackingService
    svc = OrderTrackingService(db)
    return await svc.track_order(factory_id, order_code)


@router.get("/order-tracking/delivery-alerts")
async def delivery_alerts(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """交期预警自动扫描（替代跟单员记着哪个单快到期）"""
    from api.services.order_tracking_service import OrderTrackingService
    svc = OrderTrackingService(db)
    return await svc.delivery_alert_scan(factory_id)


# ==================== 异常处理引擎（岗位消除安全网） ====================


@router.post("/exception/raise")
async def raise_exception(
    factory_id: str = Query(...),
    scenario_key: str = Query(..., description="异常场景key"),
    source_id: Optional[str] = Query(None),
    context: Dict[str, Any] = {},
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """触发异常事件（自动分级+升级+SOP）"""
    from api.services.exception_engine_service import ExceptionEngine
    engine = ExceptionEngine(db)
    return await engine.raise_exception(factory_id, scenario_key, context, source_id)


@router.get("/exception/dashboard")
async def exception_dashboard(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """异常看板：未处理+历史统计"""
    from api.services.exception_engine_service import ExceptionEngine
    engine = ExceptionEngine(db)
    return await engine.exception_dashboard(factory_id)


@router.get("/exception/scenarios")
async def list_scenarios(
    current_user: User = Depends(get_current_user),
):
    """查看所有异常场景定义（各岗位消除后的异常处理SOP）"""
    from api.services.exception_engine_service import EXCEPTION_SCENARIOS
    return {
        "total": len(EXCEPTION_SCENARIOS),
        "scenarios": [
            {"key": k, **v}
            for k, v in EXCEPTION_SCENARIOS.items()
        ],
    }
