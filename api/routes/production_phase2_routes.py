"""
岗位替代 Phase 2 路由 - 订单管理 / APS 排程增强
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, List
from pydantic import BaseModel

from sqlalchemy.ext.asyncio import AsyncSession
from database.db_config import get_db
from database.models import User
from core.auth.security import get_current_user

from api.services.order_decomposition_service import OrderDecompositionService
from api.services.aps_engine import ApsEngine

router = APIRouter(prefix="/api/v1", tags=["production-phase2"])


# ==================== Request Models ====================

class SalesOrderCreate(BaseModel):
    factory_id: str
    product_id: str
    quantity: int
    customer_name: Optional[str] = None
    customer_code: Optional[str] = None
    product_name: Optional[str] = None
    delivery_date: Optional[str] = None
    priority: str = "medium"
    unit_price: Optional[float] = None
    remark: Optional[str] = None


class ScheduleRequest(BaseModel):
    factory_id: str
    algorithm: str = "EDD"
    horizon_days: int = 30


class RescheduleRequest(BaseModel):
    factory_id: str
    insert_wo_id: Optional[str] = None
    algorithm: str = "EDD"


class OrderReviewRequest(BaseModel):
    """PMC 订单评审：结论 + 承诺交期 + 风险等级 + 意见"""
    review_status: str = "approved"  # approved / conditional / rejected
    committed_delivery: Optional[str] = None
    risk_level: Optional[str] = None  # low / medium / high
    review_note: Optional[str] = None
    review_items: Optional[List[str]] = None  # 待确认事项


# ==================== 销售订单 ====================

@router.post("/orders")
async def create_sales_order(
    req: SalesOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建销售订单"""
    svc = OrderDecompositionService(db)
    result = await svc.create_sales_order(
        factory_id=req.factory_id,
        product_id=req.product_id,
        quantity=req.quantity,
        customer_name=req.customer_name,
        customer_code=req.customer_code,
        product_name=req.product_name,
        delivery_date=req.delivery_date,
        priority=req.priority,
        unit_price=req.unit_price,
        remark=req.remark,
        created_by=current_user.username,
    )
    return result


@router.get("/orders")
async def list_sales_orders(
    factory_id: str = Query(...),
    status: Optional[str] = None,
    limit: int = Query(default=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """销售订单列表（含缺料风险标记）"""
    svc = OrderDecompositionService(db)
    result = await svc.list_sales_orders(factory_id, status, limit)

    # 缺料风险：订单产品 BOM 物料中 库存可用 < 需求 的项数（PMC 联动）
    try:
        from sqlalchemy import text as _sa_text4
        items = result.get("items", result if isinstance(result, list) else [])
        if items:
            products = set(o.get("product_id") for o in items if o.get("product_id"))
            bom_res = await db.execute(
                _sa_text4("SELECT product_id, material_code, qty_per_unit FROM bom_items WHERE product_id = ANY(:pids)"),
                {"pids": list(products)},
            )
            bom_map = {}
            for r in bom_res.mappings().all():
                bom_map.setdefault(r["product_id"], []).append(dict(r))
            all_mats = set(b["material_code"] for bs in bom_map.values() for b in bs)
            inv_res = await db.execute(
                _sa_text4(
                    "SELECT material_code, SUM(available_qty) FROM inventory "
                    "WHERE factory_id = :fid AND material_code = ANY(:codes) GROUP BY material_code"
                ),
                {"fid": factory_id, "codes": list(all_mats)},
            )
            on_hand = {r[0]: int(r[1] or 0) for r in inv_res.all()}
            for o in items:
                bom = bom_map.get(o.get("product_id"), [])
                shortages = 0
                max_gap = 0
                for b in bom:
                    need = float(o.get("quantity") or 0) * float(b["qty_per_unit"] or 1)
                    avail = on_hand.get(b["material_code"], 0)
                    if avail < need:
                        shortages += 1
                        max_gap = max(max_gap, int(need - avail))
                o["material_risk"] = {"shortage_count": shortages, "max_gap": max_gap, "at_risk": shortages > 0}
        return result
    except Exception:
        return result


@router.post("/orders/{order_id}/decompose")
async def decompose_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """订单 → 工单拆分"""
    svc = OrderDecompositionService(db)
    result = await svc.decompose_order(order_id, operator=current_user.username)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/orders/{order_id}/material-check")
async def material_check(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """物料齐套检查"""
    svc = OrderDecompositionService(db)
    result = await svc.material_check(order_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/orders/{order_id}/review-pack", description="PMC 订单评审包：物料/工艺/产能交期/质量/在制负荷")
async def order_review_pack(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """组装订单评审所需的事实，供评审人决策，不直接替代人工结论。"""
    from datetime import date as _date
    from sqlalchemy import text as _sa_text

    order_result = await db.execute(
        _sa_text("SELECT * FROM sales_orders WHERE id = :oid OR order_code = :oid LIMIT 1"),
        {"oid": order_id},
    )
    order_row = order_result.mappings().first()
    if not order_row:
        raise HTTPException(status_code=404, detail="订单不存在")
    order = dict(order_row)
    factory_id = order["factory_id"]
    product_id = order["product_id"]
    quantity = int(order.get("quantity") or 0)

    # 物料齐套：按订单数量展开 BOM，再按工厂可用库存核对。
    bom_rows = [dict(r) for r in (await db.execute(
        _sa_text(
            "SELECT material_code, material_name, qty_per_unit, unit, level "
            "FROM bom_items WHERE factory_id = :fid AND product_id = :pid "
            "ORDER BY level, material_code"
        ),
        {"fid": factory_id, "pid": product_id},
    )).mappings().all()]
    material_codes = [r["material_code"] for r in bom_rows if r.get("material_code")]
    inventory_rows = []
    if material_codes:
        inventory_rows = [dict(r) for r in (await db.execute(
            _sa_text(
                "SELECT material_code, COALESCE(SUM(available_qty), 0) AS available_qty "
                "FROM inventory WHERE factory_id = :fid AND material_code = ANY(:codes) "
                "GROUP BY material_code"
            ),
            {"fid": factory_id, "codes": material_codes},
        )).mappings().all()]
    available_by_code = {r["material_code"]: float(r["available_qty"] or 0) for r in inventory_rows}
    materials = []
    for item in bom_rows:
        required = float(item.get("qty_per_unit") or 1) * quantity
        available = available_by_code.get(item.get("material_code"), 0)
        shortage = max(0, required - available)
        materials.append({
            "material_code": item.get("material_code"),
            "material_name": item.get("material_name") or item.get("material_code"),
            "required": round(required, 2),
            "available": round(available, 2),
            "shortage": round(shortage, 2),
            "unit": item.get("unit") or "pcs",
            "level": item.get("level") or 1,
            "ready": shortage == 0,
        })
    shortage_items = [m for m in materials if not m["ready"]]
    if not bom_rows:
        material_status, material_detail = "warning", "未找到该产品的工厂 BOM，无法完成物料齐套确认"
    elif shortage_items:
        material_status = "fail"
        material_detail = f"{len(shortage_items)} 项物料缺口，最大缺口 {max(m['shortage'] for m in shortage_items):g}"
    else:
        material_status, material_detail = "pass", f"{len(materials)} 项物料已按订单数量核对，库存齐套"

    # 工艺路线：优先读取当前激活路线及其工序明细。
    routing = (await db.execute(
        _sa_text(
            "SELECT id, routing_code, version, status, steps FROM routings "
            "WHERE factory_id = :fid AND product_id = :pid AND COALESCE(is_active, TRUE) = TRUE "
            "ORDER BY updated_at DESC NULLS LAST LIMIT 1"
        ),
        {"fid": factory_id, "pid": product_id},
    )).mappings().first()
    routing_steps = []
    if routing:
        routing_steps = [dict(r) for r in (await db.execute(
            _sa_text(
                "SELECT sequence, operation_name, station_id, standard_time, quality_check "
                "FROM routing_steps WHERE routing_id = :rid ORDER BY sequence"
            ),
            {"rid": routing["id"]},
        )).mappings().all()]
        if not routing_steps:
            raw_steps = routing.get("steps") or []
            if isinstance(raw_steps, dict):
                raw_steps = raw_steps.get("steps") or raw_steps.get("operations") or []
            if isinstance(raw_steps, list):
                routing_steps = raw_steps
    if routing:
        routing_status, routing_detail = "pass", f"{routing.get('routing_code') or '当前路线'} · {len(routing_steps)} 道工序"
    else:
        routing_status, routing_detail = "warning", "未找到激活工艺路线，需 IE/工程确认工艺可制造性"

    # 产能与交期：复用现有交期评估服务，并把评估依据展示给评审人。
    svc = OrderDecompositionService(db)
    try:
        delivery_estimate = await svc.estimate_delivery(factory_id, product_id, quantity)
    except Exception as exc:
        delivery_estimate = {"error": str(exc), "confidence": "unavailable"}
    capacity_row = (await db.execute(
        _sa_text(
            "SELECT COUNT(*) AS station_count, COALESCE(SUM(available_hours_per_day), 0) AS pieces_per_day, "
            "COALESCE(AVG(efficiency_rate), 0) AS efficiency_rate "
            "FROM station_capacity WHERE factory_id = :fid AND is_active = TRUE"
        ),
        {"fid": factory_id},
    )).mappings().first() or {}
    station_count = int(capacity_row.get("station_count") or 0)
    capacity_utilization = delivery_estimate.get("capacity_utilization")
    if capacity_utilization is not None:
        capacity_utilization = float(capacity_utilization)
    if station_count == 0:
        capacity_status, capacity_detail = "warning", "没有激活的工位产能数据，交期仅能作低置信度估算"
    elif capacity_utilization is not None and capacity_utilization > 100:
        capacity_status, capacity_detail = "fail", f"预计产能利用率 {capacity_utilization:g}%，超过可用产能"
    elif capacity_utilization is not None and capacity_utilization > 85:
        capacity_status, capacity_detail = "warning", f"预计产能利用率 {capacity_utilization:g}%，接近瓶颈"
    else:
        capacity_status, capacity_detail = "pass", (
            f"{station_count} 个激活工位，合计日产能 {float(capacity_row.get('pieces_per_day') or 0):g} 件/日"
            "（station_capacity 该列口径为一天可完成几件产品，不是小时）"
        )

    earliest_delivery = delivery_estimate.get("earliest_delivery")
    requested_delivery = str(order.get("delivery_date"))[:10] if order.get("delivery_date") else None
    if not requested_delivery:
        delivery_status, delivery_detail = "warning", "订单未填写客户交期，无法确认承诺日期"
    elif not earliest_delivery:
        delivery_status, delivery_detail = "warning", "当前没有可靠的最早完工日期"
    else:
        try:
            requested_day = _date.fromisoformat(requested_delivery)
            earliest_day = _date.fromisoformat(str(earliest_delivery)[:10])
            if requested_day < earliest_day:
                delivery_status = "fail"
                delivery_detail = f"客户交期 {requested_delivery} 早于估算最早完工 {str(earliest_delivery)[:10]}"
            else:
                delivery_status = "pass"
                delivery_detail = f"客户交期 {requested_delivery}，估算最早完工 {str(earliest_delivery)[:10]}"
        except ValueError:
            delivery_status, delivery_detail = "warning", "交期格式无法计算"

    # 历史质量：同工厂、同产品的检验记录只用于提示，不阻断工程判断。
    quality_row = (await db.execute(
        _sa_text(
            "SELECT COUNT(*) AS inspection_count, COALESCE(SUM(qi.sample_qty), 0) AS sample_qty, "
            "COALESCE(SUM(qi.defect_qty), 0) AS defect_qty, "
            "COUNT(*) FILTER (WHERE UPPER(qi.result) = 'FAIL') AS fail_count, "
            "MAX(qi.created_at) AS last_inspected_at "
            "FROM quality_inspections qi JOIN work_orders wo ON wo.id = qi.work_order_id "
            "WHERE qi.factory_id = :fid AND wo.product_id = :pid"
        ),
        {"fid": factory_id, "pid": product_id},
    )).mappings().first() or {}
    sample_qty = int(quality_row.get("sample_qty") or 0)
    defect_qty = int(quality_row.get("defect_qty") or 0)
    defect_rate = (defect_qty / sample_qty * 100) if sample_qty else None
    if not int(quality_row.get("inspection_count") or 0):
        quality_status, quality_detail = "warning", "暂无该产品历史检验记录，需确认质量风险基线"
    elif defect_rate is not None and defect_rate > 5:
        quality_status, quality_detail = "fail", f"历史抽检不良率 {defect_rate:.1f}%，超过 5% 关注线"
    elif defect_rate is not None and defect_rate > 2:
        quality_status, quality_detail = "warning", f"历史抽检不良率 {defect_rate:.1f}%，高于 2% 关注线"
    else:
        quality_status, quality_detail = "pass", f"{int(quality_row.get('inspection_count') or 0)} 次检验，不良 {defect_qty} 件"

    wip_row = (await db.execute(
        _sa_text(
            "SELECT COUNT(*) AS order_count, COALESCE(SUM(GREATEST(planned_qty - completed_qty, 0)), 0) AS open_qty "
            "FROM work_orders WHERE factory_id = :fid AND product_id = :pid "
            "AND status NOT IN ('completed', 'cancelled')"
        ),
        {"fid": factory_id, "pid": product_id},
    )).mappings().first() or {}

    checks = [
        {"key": "material", "label": "物料齐套", "status": material_status, "value": f"{len(shortage_items)} 项缺料", "detail": material_detail, "source": "bom_items + inventory"},
        {"key": "routing", "label": "工艺可制造性", "status": routing_status, "value": f"{len(routing_steps)} 道工序", "detail": routing_detail, "source": "routings + routing_steps"},
        {"key": "capacity", "label": "产能负荷", "status": capacity_status, "value": f"{capacity_utilization:g}%" if capacity_utilization is not None else "未计算", "detail": capacity_detail, "source": "station_capacity + 交期评估"},
        {"key": "delivery", "label": "交期可承诺性", "status": delivery_status, "value": str(earliest_delivery or "未估算")[:10], "detail": delivery_detail, "source": "订单交期 + 产能评估"},
        {"key": "quality", "label": "历史质量", "status": quality_status, "value": f"{defect_rate:.1f}%" if defect_rate is not None else "暂无基线", "detail": quality_detail, "source": "quality_inspections"},
    ]
    failed = [c for c in checks if c["status"] == "fail"]
    warnings = [c for c in checks if c["status"] == "warning"]
    if failed:
        recommended_status, recommended_risk = "rejected", "high"
    elif warnings:
        recommended_status, recommended_risk = "conditional", "medium"
    else:
        recommended_status, recommended_risk = "approved", "low"

    return {
        "order": order,
        "recommendation": {
            "review_status": recommended_status,
            "risk_level": recommended_risk,
            "reason": "存在必须处理的失败项" if failed else ("存在需要确认的风险项" if warnings else "关键评审项均通过"),
        },
        "summary": {"pass": len(checks) - len(failed) - len(warnings), "warning": len(warnings), "fail": len(failed)},
        "checks": checks,
        "materials": {"ready": bool(bom_rows) and not shortage_items, "total": len(materials), "shortage_count": len(shortage_items), "items": materials},
        "routing": {"found": bool(routing), "routing_code": routing.get("routing_code") if routing else None, "version": routing.get("version") if routing else None, "steps": routing_steps},
        "delivery": {"requested": requested_delivery, "estimate": delivery_estimate},
        # 这一列口径是"一天可完成几件产品"，键名不再叫 hours_per_day（叫错名就是这个数字被当小时用的原因）
        "capacity": {"station_count": station_count, "daily_capacity_pieces": round(float(capacity_row.get("pieces_per_day") or 0), 1), "avg_oee": float(capacity_row.get("efficiency_rate") or 0), "utilization": capacity_utilization, "capacity_unit": "件/日"},
        "quality": {"inspection_count": int(quality_row.get("inspection_count") or 0), "sample_qty": sample_qty, "defect_qty": defect_qty, "defect_rate": round(defect_rate, 2) if defect_rate is not None else None, "fail_count": int(quality_row.get("fail_count") or 0), "last_inspected_at": quality_row.get("last_inspected_at")},
        "wip": {"order_count": int(wip_row.get("order_count") or 0), "open_qty": int(wip_row.get("open_qty") or 0)},
        "recommended_items": [f"{c['label']}：{c['detail']}" for c in failed + warnings],
    }


@router.post("/orders/{order_id}/review", description="PMC 订单评审：写评审结论/承诺交期/风险等级到订单")
async def review_sales_order(
    order_id: str,
    req: OrderReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """订单评审：结论直接挂在销售订单上"""
    from sqlalchemy import text as _sa_text
    if req.review_status not in ("approved", "conditional", "rejected"):
        raise HTTPException(status_code=400, detail="review_status 必须为 approved / conditional / rejected")
    commit_date = None
    if req.committed_delivery:
        try:
            import datetime as _dt
            commit_date = _dt.date.fromisoformat(str(req.committed_delivery)[:10])
        except ValueError:
            commit_date = None
    note = req.review_note or ""
    items = req.review_items or []
    if items:
        note = (note + ("\n" if note else "") + "待确认事项：" + "；".join(items)).strip()
    result = await db.execute(
        _sa_text(
            "UPDATE sales_orders SET review_status = :rs, committed_delivery = :cd, risk_level = :rl, "
            "review_note = :rn, reviewed_by = :rb, reviewed_at = NOW() "
            "WHERE id = :oid OR order_code = :oid RETURNING *"
        ),
        {"rs": req.review_status, "cd": commit_date, "rl": req.risk_level,
         "rn": note, "rb": current_user.username, "oid": order_id},
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="订单不存在")
    return {"ok": True, "order": dict(row)}


@router.get("/orders/review-board", description="订单评审看板聚合：状态/优先级/客户/产品/交期风险分桶/评审统计")
async def sales_order_review_board(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """订单分类与评审统计（图表数据源）"""
    from sqlalchemy import text as _sa_text
    import datetime as _dt
    today = _dt.date.today()
    plus7 = today + _dt.timedelta(days=7)
    plus14 = today + _dt.timedelta(days=14)
    plus30 = today + _dt.timedelta(days=30)
    fid = factory_id

    async def _q(sql: str):
        return [dict(r) for r in (await db.execute(_sa_text(sql), {"fid": fid})).mappings().all()]

    status_breakdown = await _q("SELECT status AS name, COUNT(*) AS count, "
                                "COALESCE(SUM(total_amount),0) AS amount FROM sales_orders "
                                "WHERE factory_id=:fid GROUP BY status ORDER BY count DESC")
    priority_breakdown = await _q("SELECT priority AS name, COUNT(*) AS count, "
                                  "COALESCE(SUM(total_amount),0) AS amount FROM sales_orders "
                                  "WHERE factory_id=:fid GROUP BY priority ORDER BY count DESC")
    customer_top = await _q("SELECT COALESCE(NULLIF(customer_name,''),customer_code,'其他') AS name, "
                            "COUNT(*) AS count, COALESCE(SUM(total_amount),0) AS amount "
                            "FROM sales_orders WHERE factory_id=:fid GROUP BY 1 ORDER BY amount DESC LIMIT 6")
    product_top = await _q("SELECT COALESCE(NULLIF(product_name,''),product_id) AS name, product_id, "
                           "COUNT(*) AS count, SUM(quantity) AS qty, COALESCE(SUM(total_amount),0) AS amount "
                           "FROM sales_orders WHERE factory_id=:fid GROUP BY 1, product_id ORDER BY amount DESC LIMIT 6")
    review_breakdown = await _q("SELECT COALESCE(review_status,'pending') AS name, COUNT(*) AS count "
                                "FROM sales_orders WHERE factory_id=:fid GROUP BY 1 ORDER BY count DESC")
    risk_breakdown = await _q("SELECT COALESCE(risk_level,'-') AS name, COUNT(*) AS count "
                              "FROM sales_orders WHERE factory_id=:fid GROUP BY 1 ORDER BY count DESC")

    delivery_buckets = []
    for key, cond in (
        ("逾期未发货", "delivery_date < :a AND status NOT IN ('shipped','completed','cancelled')"),
        ("7天内到期", "delivery_date >= :a AND delivery_date <= :b AND status NOT IN ('shipped','completed','cancelled')"),
        ("7-14天", "delivery_date > :b AND delivery_date <= :c AND status NOT IN ('shipped','completed','cancelled')"),
        ("14-30天", "delivery_date > :c AND delivery_date <= :d AND status NOT IN ('shipped','completed','cancelled')"),
        ("30天后", "delivery_date > :d AND status NOT IN ('shipped','completed','cancelled')"),
    ):
        rows = [dict(r) for r in (await db.execute(
            _sa_text(f"SELECT COUNT(*) AS count, COALESCE(SUM(total_amount),0) AS amount "
                     f"FROM sales_orders WHERE factory_id=:fid AND {cond}"),
            {"fid": fid, "a": today, "b": plus7, "c": plus14, "d": plus30})).mappings().all()]
        r0 = rows[0]
        delivery_buckets.append({"name": key, "count": int(r0["count"]), "amount": float(r0["amount"])})

    totals = [dict(r) for r in (await db.execute(
        _sa_text("SELECT COUNT(*) AS total, COALESCE(SUM(total_amount),0) AS amount, "
                 "COUNT(*) FILTER (WHERE review_status IS NULL) AS pending_review, "
                 "COUNT(*) FILTER (WHERE material_ready = FALSE AND decomposed) AS material_risk "
                 "FROM sales_orders WHERE factory_id=:fid"),
        {"fid": fid})).mappings().all()][0]
    return {
        "totals": {k: (int(float(v)) if isinstance(v, (int, float)) else v) for k, v in totals.items()},
        "status": status_breakdown,
        "priority": priority_breakdown,
        "customers": customer_top,
        "products": product_top,
        "review": review_breakdown,
        "risk": risk_breakdown,
        "delivery_buckets": delivery_buckets,
    }


@router.get("/orders/delivery-estimate")
async def delivery_estimate(
    factory_id: str = Query(...),
    product_id: str = Query(...),
    quantity: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """交期评估"""
    svc = OrderDecompositionService(db)
    return await svc.estimate_delivery(factory_id, product_id, quantity)


# ==================== APS 排程增强 ====================

@router.post("/aps/schedule")
async def run_schedule(
    req: ScheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """执行有限产能排程"""
    engine = ApsEngine(db)
    result = await engine.schedule(
        factory_id=req.factory_id,
        algorithm=req.algorithm,
        horizon_days=req.horizon_days,
        created_by=current_user.username,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/aps/reschedule")
async def run_reschedule(
    req: RescheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """插单重排（锁定在制工单）"""
    engine = ApsEngine(db)
    result = await engine.reschedule(
        factory_id=req.factory_id,
        insert_wo_id=req.insert_wo_id,
        algorithm=req.algorithm,
        created_by=current_user.username,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/aps/gantt")
async def gantt_data(
    factory_id: str = Query(...),
    schedule_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """甘特图数据"""
    engine = ApsEngine(db)
    return await engine.get_gantt_data(factory_id, schedule_id)


@router.get("/aps/conflicts")
async def detect_conflicts(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """冲突检测"""
    engine = ApsEngine(db)
    return await engine.detect_conflicts(factory_id)

# ==================== 销售订单详情（含演示订单兼容） ====================

@router.get("/orders/{order_ref}", description="销售订单详情。支持按 order_code 或 id 查询；订单表无记录时自动从工单聚合（演示订单兼容），返回关联生产计划与工单。")
async def get_sales_order_detail(
    order_ref: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """销售订单详情：订单头 + 关联生产计划 + 关联工单

    数据源策略（demo 数据兼容）：
    1. 优先查 sales_orders（order_code 或 id）
    2. 查不到时，从 work_orders / plans 按 sales_order_id 聚合出订单视图
    3. 全部查不到 → 404
    """
    from sqlalchemy import text

    # 1) 订单头：sales_orders
    result = await db.execute(
        text("SELECT * FROM sales_orders WHERE order_code = :ref OR id = :ref"),
        {"ref": order_ref},
    )
    row = result.mappings().first()
    order = dict(row) if row else None
    source = "sales_orders" if order else "work_orders"

    # 2) 关联工单
    wo_result = await db.execute(
        text("SELECT * FROM work_orders WHERE sales_order_id = :ref ORDER BY created_at DESC"),
        {"ref": order_ref},
    )
    work_orders = [dict(r) for r in wo_result.mappings().all()]

    # 3) 关联生产计划
    plan_result = await db.execute(
        text("SELECT * FROM plans WHERE sales_order_id = :ref ORDER BY created_at DESC"),
        {"ref": order_ref},
    )
    plans = [dict(r) for r in plan_result.mappings().all()]

    if not order and not work_orders and not plans:
        raise HTTPException(status_code=404, detail="订单不存在")

    # 订单表无记录时，从工单聚合演示订单信息
    if not order and work_orders:
        first = work_orders[0]
        order = {
            "id": order_ref,
            "order_code": order_ref,
            "factory_id": first.get("factory_id"),
            "product_id": first.get("product_id"),
            "product_name": None,
            "customer_name": None,
            "customer_code": None,
            "quantity": sum((w.get("planned_qty") or 0) for w in work_orders),
            "unit": first.get("unit") or "pcs",
            "delivery_date": None,
            "priority": "medium",
            "status": "demo",
            "decomposed": True,
            "material_ready": None,
            "total_amount": None,
            "currency": "CNY",
            "remark": "演示订单（未在销售订单主档登记，信息由关联工单聚合）",
            "created_at": first.get("created_at"),
        }

    return {
        "order": order,
        "source": source,
        "work_orders": work_orders,
        "plans": plans,
    }
