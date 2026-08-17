"""PMC 工作矩阵接口。"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.security import enforce_tenant, get_current_user
from database.db_config import get_db
from database.models import User
from api.services.pmc_control_tower_service import PmcControlTowerService
from api.services.pmc_work_matrix_service import PmcWorkMatrixService

router = APIRouter(prefix="/api/v1/pmc", tags=["PMC - 工作矩阵"], dependencies=[Depends(enforce_tenant)])


PMC_DATA_CONTRACT = [
    {
        "key": "orders",
        "question": "排过多少订单",
        "source_tables": ["sales_orders", "work_orders", "aps_schedules", "aps_schedule_tasks"],
        "minimum_fields": {
            "sales_orders": ["order_code", "factory_id", "product_id", "quantity", "delivery_date", "status"],
            "work_orders": ["sales_order_id", "work_order_code", "planned_due", "actual_complete", "status"],
            "aps_schedule_tasks": ["schedule_id", "work_order_id", "planned_start", "planned_end", "status"],
        },
        "why": "订单历史、实际排程数量和交期结果必须能追溯到订单与APS任务。",
    },
    {
        "key": "materials",
        "question": "控过多少物料",
        "source_tables": ["bom_items", "work_order_materials", "inventory", "inventory_transactions"],
        "minimum_fields": {
            "bom_items": ["factory_id", "product_id", "bom_version", "material_code", "qty_per_unit"],
            "inventory_transactions": ["factory_id", "material_id", "transaction_type", "quantity", "created_at"],
        },
        "why": "主数据能说明当前控制范围，库存流水才能证明历史控制过和消耗过。",
    },
    {
        "key": "shortage",
        "question": "Shortage怎么处理",
        "source_tables": ["work_order_materials", "purchase_orders", "supplier_materials"],
        "minimum_fields": {
            "work_order_materials": ["work_order_id", "material_code", "required_qty", "available_qty", "received_qty", "shortage_qty"],
            "purchase_orders": ["material_code", "qty", "expected_date", "status"],
        },
        "why": "缺口、在途、ETA和替代供应必须在同一条物料证据链上。",
    },
    {
        "key": "inventory",
        "question": "库存怎么降",
        "source_tables": ["inventory", "inventory_transactions", "bom_items", "purchase_orders"],
        "minimum_fields": {
            "inventory": ["material_code", "total_qty", "available_qty", "reserved_qty", "unit_cost", "last_movement_at"],
            "inventory_transactions": ["material_id", "transaction_type", "quantity", "created_at"],
        },
        "why": "库存余额、消耗趋势、需求复用和在途补货缺一不可。",
    },
    {
        "key": "otd",
        "question": "OTD怎么保证",
        "source_tables": ["sales_orders", "work_orders", "aps_schedule_tasks"],
        "minimum_fields": {
            "sales_orders": ["delivery_date", "actual_ship_date", "status"],
            "work_orders": ["planned_due", "actual_complete", "status"],
        },
        "why": "有客户订单时按实际出货计算；没有客户订单才使用工单完成作为明确标注的后备口径。",
    },
    {
        "key": "capacity",
        "question": "产能怎么平衡",
        "source_tables": ["stations", "station_capacity", "routings", "aps_work_calendars", "aps_schedule_tasks"],
        "minimum_fields": {
            "station_capacity": ["factory_id", "station_id", "available_hours_per_day", "efficiency_rate", "is_active"],
            "aps_schedule_tasks": ["station_id", "planned_start", "planned_end", "status"],
        },
        "why": "工位能力、班次日历和实际任务负荷要分开记录，不能用固定12小时假设替代。",
    },
    {
        "key": "rush",
        "question": "紧急插单怎么排",
        "source_tables": ["rush_order_approvals", "rush_order_approval_logs", "aps_schedules", "aps_plan_events"],
        "minimum_fields": {
            "rush_order_approvals": ["approval_code", "quantity", "due_date", "status", "affected_orders"],
            "rush_order_approval_logs": ["approval_id", "action", "operator", "created_at"],
        },
        "why": "插单必须保留影响评估、审批、重排版本和受影响订单。",
    },
    {
        "key": "engineering_change",
        "question": "EC/BOM change怎么处理",
        "source_tables": ["engineering_changes", "bom_items", "work_orders"],
        "minimum_fields": {
            "engineering_changes": ["ecn_code", "affected_product", "old_value", "new_value", "status", "propagated_at"],
            "bom_items": ["product_id", "bom_version", "material_code", "qty_per_unit"],
        },
        "why": "要能区分变更批准、生效版本、MRP重算和未完工工单传播。",
    },
    {
        "key": "supplier_delay",
        "question": "supplier delay怎么处理",
        "source_tables": ["purchase_orders", "suppliers", "supplier_materials"],
        "minimum_fields": {
            "purchase_orders": ["po_code", "supplier_id", "material_code", "qty", "expected_date", "actual_date", "status"],
            "suppliers": ["supplier_code", "supplier_name", "on_time_rate", "avg_lead_days"],
        },
        "why": "供应商延迟必须由PO预计/实际日期和供应商主数据共同证明。",
    },
]


class PmcScenarioRequest(BaseModel):
    """预排程沙盘开关；不修改工单主数据，只改变本次评审假设。"""

    work_order_code: str = Field(..., description="主工单号")
    factory_id: str = Field(..., description="工厂ID")
    options: Dict[str, Any] = Field(default_factory=dict)


@router.get("/work-matrix", summary="获取工单 PMC 工作矩阵")
async def get_work_matrix(
    factory_id: str = Query(...),
    work_order_code: str = Query(..., description="主工单号"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回需求、RDD、UHN、可加工时间、库存齐套和下一步重点。"""
    return await PmcWorkMatrixService(db).build(factory_id, work_order_code)


@router.post("/work-matrix/scenario", summary="按 PMC 开关重算预排程沙盘")
async def recalculate_work_matrix(
    request: PmcScenarioRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """切换时间/物料/生产/出货/紧急参数后重新计算，不落库、不改变工单。"""
    return await PmcWorkMatrixService(db).build(
        request.factory_id,
        request.work_order_code,
        request.options,
    )


@router.get("/atp", summary="获取工单 ATP 交期承诺评审")
async def get_available_to_promise(
    factory_id: str = Query(...),
    work_order_code: str = Query(..., description="待承诺的主工单号"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把工作矩阵的物料、产能、RDD 证据收口为可审计的 ATP 结论。

    这是评审结论，不会修改销售订单、MPS 或工单承诺日期。
    """
    del current_user
    matrix = await PmcWorkMatrixService(db).build(factory_id, work_order_code)
    if matrix.get("error"):
        return matrix

    judgement = matrix.get("judgement") or {}
    computed = matrix.get("computed") or {}
    material_exceptions = [
        item for item in matrix.get("materials") or []
        if item.get("kit_status") != "ready"
    ]
    overall = judgement.get("overall")
    can_promise = overall == "ready_for_mps"
    conditional = overall == "conditional"
    return {
        "type": "pmc_atp",
        "factory_id": factory_id,
        "work_order": matrix.get("work_order"),
        "promise": {
            "requested_rdd": (matrix.get("work_order") or {}).get("planned_due"),
            "earliest_production_complete": computed.get("production_complete_at"),
            "fg_ready_at": computed.get("fg_ready_at"),
            "estimated_eta": computed.get("estimated_eta"),
            "can_promise": can_promise,
            "conditional": conditional,
            "decision": "可承诺" if can_promise else "条件承诺" if conditional else "暂不可承诺",
        },
        "evidence": {
            "material_ready": judgement.get("material_ready"),
            "projected_material_ready": judgement.get("projected_material_ready"),
            "capacity_feasible": judgement.get("capacity_feasible"),
            "rdd_feasible": judgement.get("rdd_feasible"),
            "calendar": matrix.get("calendar"),
            "material_exceptions": material_exceptions,
            "risk_flags": matrix.get("risk_flags") or [],
        },
        "next_focus": matrix.get("next_focus") or [],
        "note": "ATP 只读评审；正式承诺仍须按企业授权流程确认。",
    }


@router.get("/material-supply", summary="获取 PMC 物料齐套与供应证据")
async def get_material_supply(
    factory_id: str = Query(...),
    material_keyword: Optional[str] = Query(None),
    days_threshold: int = Query(180, ge=0, le=3650),
    limit: int = Query(50, ge=1, le=200),
    only_stagnant: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提供库存、在途、PO、账龄及 BOM 可复用性的一致供应口径。"""
    del current_user
    return await PmcWorkMatrixService(db).query_material_supply(
        factory_id,
        material_keyword=material_keyword,
        days_threshold=days_threshold,
        limit=limit,
        only_stagnant=only_stagnant,
    )


@router.get("/data-readiness", summary="获取 PMC 数据完整性与补数清单")
async def get_data_readiness(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回九类PMC问题的当前证据状态和可执行补数合同。"""
    del current_user
    tower = await PmcControlTowerService(db).collect(factory_id, scope="all")
    quality_by_key = {item.get("key"): item for item in tower.get("data_quality", [])}
    return {
        "factory_id": factory_id,
        "generated_at": tower.get("generated_at"),
        "sources": [
            {
                **contract,
                "current_status": quality_by_key.get(contract["key"], {}).get("status", "unknown"),
                "missing_sources": quality_by_key.get(contract["key"], {}).get("missing_sources", []),
                "current_note": quality_by_key.get(contract["key"], {}).get("note", ""),
            }
            for contract in PMC_DATA_CONTRACT
        ],
        "policy": "只接收可追溯的业务源数据；系统不会用训练数据或估算记录冒充订单、PO、出货或ECN历史。",
    }


@router.get("/delivery/countdown", summary="获取 PMC 交期倒计时")
async def get_delivery_countdown(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """订单交期红黄绿灯；与工作流分析共用同一服务，避免双口径。"""
    del current_user
    from api.services.t3_delivery_service import T3DeliveryService
    return await T3DeliveryService(db).delivery_countdown(factory_id)


@router.get("/delivery/progress", summary="获取 PMC 生产进度汇总")
async def get_delivery_progress(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """工位、部门、全厂三级进度；供 PMC 协调会使用。"""
    del current_user
    from api.services.t3_delivery_service import T3DeliveryService
    return await T3DeliveryService(db).realtime_progress(factory_id)


@router.get("/delivery/alerts", summary="获取 PMC 交期与供应异常")
async def get_delivery_alerts(
    factory_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """汇总工单超期、采购逾期和临近交付风险。"""
    del current_user
    from api.services.t3_delivery_service import T3DeliveryService
    return await T3DeliveryService(db).overdue_alerts(factory_id)


@router.get("/capabilities", summary="获取 PMC 能力与接口清单")
async def get_pmc_capabilities(
    current_user: User = Depends(get_current_user),
):
    """使页面、聊天入口和接口边界可被审计，不依赖文件名猜测能力。"""
    del current_user
    return {
        "domain": "PMC",
        "capabilities": [
            {"key": "work_matrix", "name": "工单评审矩阵", "path": "/api/v1/pmc/work-matrix", "mode": "read_only"},
            {"key": "scenario", "name": "预排程沙盘", "path": "/api/v1/pmc/work-matrix/scenario", "mode": "simulation"},
            {"key": "atp", "name": "ATP 交期承诺评审", "path": "/api/v1/pmc/atp", "mode": "read_only"},
            {"key": "material_supply", "name": "齐套与供应证据", "path": "/api/v1/pmc/material-supply", "mode": "read_only"},
            {"key": "delivery_countdown", "name": "交期倒计时", "path": "/api/v1/pmc/delivery/countdown", "mode": "read_only"},
            {"key": "delivery_progress", "name": "生产进度汇总", "path": "/api/v1/pmc/delivery/progress", "mode": "read_only"},
            {"key": "delivery_alerts", "name": "交期与供应异常", "path": "/api/v1/pmc/delivery/alerts", "mode": "read_only"},
            {"key": "data_readiness", "name": "PMC 数据完整性与补数清单", "path": "/api/v1/pmc/data-readiness", "mode": "read_only"},
            {"key": "position_trainer", "name": "PMC 职位训练器", "path": "/api/v1/trainer/pack?position_code=pmc", "mode": "training"},
        ],
        "note": "所有评审、ATP 和沙盘结果均不直接修改订单/MPS；下达仍由 PP/MPS 授权流程执行。",
    }


__all__ = ["router"]


@router.post("/backward-schedule", summary="PMC 交期倒推（五节点+物料红线+每日排产+风险分级）")
async def pmc_backward_schedule(payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    """
    交期倒推五节点：
    ① Customer Required Date → ② ETD/Cut-off → ③ FG Ready 生产完成 → ④ Material Ready → ⑤ Supplier ETA
    返回：五节点时间轴 + 物料红线 + 每日排产 + 风险 green/yellow/red
    """
    import math
    from datetime import datetime, timedelta

    fid = payload.get("factory_id") or "FAC_MECH_001"
    product_id = (payload.get("product_id") or "").strip()
    qty = float(payload.get("qty") or 0)
    delivery = (payload.get("delivery") or "").strip()
    if not product_id or qty <= 0 or not delivery:
        return {"error": "缺少 product_id/qty/delivery"}
    try:
        due = datetime.strptime(delivery, "%Y-%m-%d").date()
    except Exception:
        return {"error": f"delivery 格式应为 YYYY-MM-DD: {delivery}"}

    # 参数（可覆盖）
    sea_days = int(payload.get("sea_days") or 12)          # 海运
    cut_off_hours = int(payload.get("cut_off_hours") or 12)  # Cut-off 提前量(小时)
    pack_hours = float(payload.get("pack_hours") or 2)      # Packing+FG入库
    iqc_hours = float(payload.get("iqc_hours") or 2)        # IQC+入库+发料
    work_hours_day = float(payload.get("work_hours_day") or 10)  # 每日有效工时
    upH = float(payload.get("uph") or 0)                    # UPH

    # ① 客户交期 → ② ETD（海运倒推）—— 统一用 datetime 计算（date 不能减 hours）
    due_dt = datetime.combine(due, datetime.min.time())
    etd = due_dt - timedelta(days=sea_days)
    # ② ETD → ③ 生产完成（Cut-off 提前 + 报关装柜 1 天）
    fg_ready = etd - timedelta(days=1) - timedelta(hours=cut_off_hours / 24)
    fg_ready = fg_ready.replace(hour=18, minute=0, second=0)

    # 产能：UPH 从工艺/历史推断
    if upH <= 0:
        # UPH 优先从工艺（routing_template_steps.standard_hours 反推），兜底 12/h
        up_row = (await db.execute(text("""
            SELECT rt.standard_hours FROM routing_template_steps rt
            JOIN routing_templates r ON r.id = rt.template_id
            WHERE r.factory_id = :f AND rt.standard_hours > 0 LIMIT 1
        """), {"f": fid})).mappings().first()
        if up_row and float(up_row["standard_hours"] or 0) > 0:
            upH = 1.0 / float(up_row["standard_hours"])  # 单件工时 → UPH
        if upH <= 0:
            upH = 12.0  # 兜底 12 台/时（跑步机装配线常规）
    prod_hours = qty / upH if upH > 0 else 0
    prod_days_needed = math.ceil(prod_hours / work_hours_day) if prod_hours > 0 else 0

    # ③ 生产完成 → ④ 物料可上线（生产开始时间）
    # 生产从 fg_ready 往前推 prod_days_needed 天
    prod_start = fg_ready - timedelta(days=prod_days_needed)
    mat_ready = prod_start  # 物料最晚可上线 = 生产开始

    # ⑤ 供应商 ETA（物料可上线 - IQC 处理）
    supplier_eta_limit = mat_ready - timedelta(hours=iqc_hours)

    # 物料红线：查该产品 BOM 物料库存/在途
    mat_rows = (await db.execute(text("""
        SELECT b.material_code, b.material_name, b.qty_per_unit,
               COALESCE(i.available_qty, 0) AS available
        FROM bom_items b
        LEFT JOIN inventory i ON i.material_code = b.material_code AND i.factory_id = :f
        WHERE b.product_id = :p
        LIMIT 8
    """), {"f": fid, "p": product_id})).mappings().all()
    materials = []
    for m in mat_rows:
        need = float(m["qty_per_unit"] or 0) * qty
        avail = m["available"]
        status = "ok" if avail >= need else ("red" if avail <= 0 else "yellow")
        materials.append({
            "material_code": m["material_code"], "material_name": m["material_name"],
            "need_qty": need, "available": avail, "shortage": max(0, need - avail),
            "status": status,
            "latest_eta": str(supplier_eta_limit) if status != "ok" else None,
        })

    # 每日排产
    daily = []
    if prod_days_needed > 0:
        for i in range(prod_days_needed):
            day_start = prod_start + timedelta(days=i)
            day_plan = min(work_hours_day, max(0, prod_hours - i * work_hours_day))
            daily.append({"date": str(day_start.date()), "hours": round(day_plan, 1),
                          "qty": round(day_plan * upH) if upH > 0 else 0})

    # 风险判定
    risks = []
    has_red = False
    for m in materials:
        if m["status"] == "red":
            risks.append({"level": "red", "msg": f"{m['material_code']} 缺料{int(m['shortage'])} 且无 ETA（最危险）"})
            has_red = True
        elif m["status"] == "yellow":
            risks.append({"level": "yellow", "msg": f"{m['material_code']} 库存不足，需在 {m['latest_eta']} 前到厂（减 IQC 2h）"})
    if prod_days_needed > 2 and not has_red:
        risks.append({"level": "yellow", "msg": f"生产需 {prod_days_needed} 天，建议加班/提前开工"})
    if prod_days_needed > 4:
        risks.append({"level": "red", "msg": f"产能排不下（{prod_days_needed} 天 > 4 天窗口），需换线/加线或与客户协商"})
        has_red = True

    return {
        "product_id": product_id, "qty": qty, "delivery": str(due),
        "nodes": {
            "customer_required": str(due),
            "etd": str(etd.date()),
            "cut_off": str((etd - timedelta(days=1)).date()),
            "fg_ready": str(fg_ready.date()),
            "prod_start": str(prod_start.date()),
            "mat_ready": str(mat_ready.date()),
            "supplier_eta_limit": str(supplier_eta_limit.date()),
        },
        "capacity": {"uph": upH, "prod_hours": round(prod_hours, 1), "days_needed": prod_days_needed},
        "materials": materials,
        "daily_plan": daily,
        "risks": risks,
        "grade": "red" if has_red else ("yellow" if any(r["level"] == "yellow" for r in risks) else "green"),
    }


@router.post("/backward-to-plan", summary="交期倒推 → 生成生产计划草案")
async def pmc_backward_to_plan(payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    """倒推结果 → 建 PMB- 计划草案（确认/下达走正常流程）。"""
    fid = payload.get("factory_id") or "FAC_MECH_001"
    product_id = (payload.get("product_id") or "").strip()
    qty = float(payload.get("qty") or 0)
    due = (payload.get("delivery") or "").strip()
    if not product_id or qty <= 0 or not due:
        return {"error": "缺少 product_id/qty/delivery"}
    plan_code = f"PMB-{datetime.now().strftime('%Y%m%d%H%M')}"
    plan_id = str(uuid.uuid4())
    due_dt = datetime.strptime(due, "%Y-%m-%d")
    await db.execute(text("""
        INSERT INTO plans (id, plan_code, factory_id, product_id, quantity, required_date,
                           plan_type, customer_level, priority, status, due_date, priority_score,
                           created_at, updated_at)
        VALUES (:id, :code, :f, :p, :q, :due, 'MPS', 'A', 1, 'draft', :due, :ps, NOW(), NOW())
    """), {"id": plan_id, "code": plan_code, "f": fid, "p": product_id, "q": int(qty),
           "due": due_dt, "ps": 0.5})
    await db.commit()
    return {"success": True, "plan_id": plan_id, "plan_code": plan_code, "status": "draft",
            "message": "生产计划草案已生成，可在计划列表确认/下达"}


@router.post("/work-matrix/hammer", summary="PMC 锤子图：工单 × 开关影响矩阵（y轴工单, x轴参数开关）")
async def pmc_hammer_matrix(payload: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    """
    返回每个工单在基准 + 各开关切换下的交期偏移矩阵。
    y 轴 = 工单（默认待排/在制 TOP 12）
    x 轴 = 参数开关（时间锤/物料锤/生产锤/出货锤/紧急锤）
    单元格 = 该开关对工单交期的影响（偏移天数 + 风险等级）
    """
    from datetime import datetime, timedelta

    fid = payload.get("factory_id") or "FAC_MECH_001"
    wocodes = payload.get("work_order_codes") or []
    limit = int(payload.get("limit") or 12)

    # 1) 取工单（默认待排/在制，按交期排序）
    if not wocodes:
        wo_rows = (await db.execute(text("""
            SELECT work_order_code, product_id, planned_qty, planned_due, status, priority
            FROM work_orders
            WHERE factory_id=:f AND status IN ('pending','in_progress','released')
            ORDER BY planned_due LIMIT :lim
        """), {"f": fid, "lim": limit})).mappings().all()
    else:
        wo_rows = (await db.execute(text("""
            SELECT work_order_code, product_id, planned_qty, planned_due, status, priority
            FROM work_orders
            WHERE factory_id=:f AND work_order_code = ANY(:codes)
        """), {"f": fid, "codes": wocodes})).mappings().all()

    # 2) 开关定义（与 scenario 一致，用"切换后"语义）
    # 参数维度（表头可调）：每个维度多档，前端下拉选择
    dimensions = [
        {"key": "shift_mode", "label": "时间锤·班次",
         "options": [{"value": "single", "label": "单班(10h)", "desc": "每天 1 班 10 小时"},
                     {"value": "double", "label": "双班(20h)", "desc": "每天 2 班 20 小时"},
                     {"value": "triple", "label": "三班(24h)", "desc": "全天 3 班 24 小时"}],
         "default": "single"},
        {"key": "iqc_mode", "label": "物料锤·检验",
         "options": [{"value": "exempt", "label": "免检(0h)", "desc": "供应商免检，来料直接上线"},
                     {"value": "sampling", "label": "抽检(+4h)", "desc": "IQC 抽样检验 4 小时"},
                     {"value": "full", "label": "全检(+8h)", "desc": "IQC 全数检验 8 小时"}],
         "default": "exempt"},
        {"key": "line_occupancy", "label": "生产锤·线体",
         "options": [{"value": "exclusive", "label": "独占线", "desc": "本工单独占产线，UPH 100%"},
                     {"value": "shared_50", "label": "共享线(50%)", "desc": "与别单共享产线，UPH 减半"},
                     {"value": "shared_30", "label": "共享线(30%)", "desc": "多单挤占，UPH 只剩 30%"}],
         "default": "exclusive"},
        {"key": "yield_rate", "label": "生产锤·良率",
         "options": [{"value": 0.97, "label": "良率97%", "desc": "正常良率"},
                     {"value": 0.92, "label": "良率92%", "desc": "过程不良增多，工时放大"},
                     {"value": 0.85, "label": "良率85%", "desc": "重大异常，工时放大明显"}],
         "default": 0.97},
        {"key": "customs_mode", "label": "出货锤·海关",
         "options": [{"value": "none", "label": "免查验(0h)", "desc": "普货正常放行"},
                     {"value": "random", "label": "抽查(+24h)", "desc": "海关随机抽查 24 小时"},
                     {"value": "full", "label": "全查(+48h)", "desc": "海关全面查验 48 小时"}],
         "default": "none"},
        {"key": "enable_air_freight", "label": "紧急锤·运输",
         "options": [{"value": False, "label": "海运(12天)", "desc": "标准海运"},
                     {"value": True, "label": "空运(2天)", "desc": "紧急空运，成本高"}],
         "default": False},
    ]

    # 前端传入的参数组合（各维度当前档），未传用默认
    params = payload.get("params") or {}
    cur_opts = {d["key"]: params.get(d["key"], d["default"]) for d in dimensions}
    base_opts = {"shift_mode": "single", "iqc_mode": "exempt",
                 "line_occupancy": "exclusive", "customs_mode": "none",
                 "yield_rate": 0.97, "enable_air_freight": False}
    # 应用当前组合（保留非维度参数）
    for k, v in cur_opts.items():
        if v is not None:
            base_opts[k] = v

    # 3) 逐工单：基准 = 当前参数组合；单元格 = 各维度切到其他档的相对偏移
    from api.services.pmc_work_matrix_service import PmcWorkMatrixService
    svc = PmcWorkMatrixService(db)
    rows = []
    for wo in wo_rows:
        try:
            base = await svc.build(fid, wo["work_order_code"], base_opts)
        except Exception:
            base = {}
        base_eta = str(base.get("estimated_eta") or "")[:10]
        base_days = _date_delta(base.get("estimated_eta"), wo["planned_due"])
        if base_days is None:
            base_days = _fallback_eta_days(wo, base_opts)
            base_eta = _fallback_eta(wo, base_opts)

        cells = []
        for dim in dimensions:
            for opt in dim["options"]:
                if opt["value"] == cur_opts.get(dim["key"]):
                    continue  # 当前档不算偏移（基准）
                opts = {**base_opts, dim["key"]: opt["value"]}
                try:
                    res = await svc.build(fid, wo["work_order_code"], opts)
                except Exception:
                    res = {}
                eta = str(res.get("estimated_eta") or "")[:10]
                days = _date_delta(res.get("estimated_eta"), wo["planned_due"])
                if days is None:
                    days = _fallback_eta_days(wo, opts)
                    eta = _fallback_eta(wo, opts)
                offset = (days - base_days) if (days is not None and base_days is not None) else None
                level = "danger" if (offset or 0) > 2 else ("warning" if (offset or 0) > 0 else "ok")
                cells.append({"switch": dim["key"], "dimension": dim["label"],
                              "label": f"{dim['label']}·{opt['label']}",
                              "option_value": opt["value"], "option_label": opt["label"],
                              "offset_days": offset, "level": level, "eta": eta, "desc": opt["desc"]})

        rows.append({
            "work_order_code": wo["work_order_code"],
            "product_id": wo["product_id"],
            "qty": wo["planned_qty"],
            "due": str(wo["planned_due"])[:10],
            "status": wo["status"],
            "priority": wo["priority"],
            "base_eta": base_eta,
            "base_offset_days": base_days,
            "cells": cells,
        })

    # ── 决策推导层（AI 决策依据）：敏感工单 / 全局风险开关 / 推荐杠杆 ──
    sensitive_wos = []
    risk_switches = []
    for r in rows:
        max_off = max((c["offset_days"] or 0) for c in r["cells"]) if r["cells"] else 0
        worst = max(r["cells"], key=lambda c: c["offset_days"] or 0) if r["cells"] else None
        if max_off > 2:
            sensitive_wos.append({
                "work_order_code": r["work_order_code"],
                "priority": r["priority"],
                "due": r["due"],
                "worst_switch": worst["label"] if worst else "",
                "worst_offset_days": round(max_off, 1),
                "recommendation": _hammer_recommendation(r),
            })
    # 风险维度：某维度任一切换档位导致多工单延后 → 该维度是全局风险点
    for dim in dimensions:
        affected = [r["work_order_code"] for r in rows if any(
            c["switch"] == dim["key"] and (c["offset_days"] or 0) > 0
            for c in r["cells"])]
        if len(affected) >= max(2, len(rows) * 0.3):
            risk_switches.append({
                "label": dim["label"], "desc": "该参数切换影响多工单",
                "affected_count": len(affected), "affected_total": len(rows),
            })

    return {"success": True, "factory_id": fid, "dimensions": dimensions,
            "params": cur_opts, "rows": rows, "count": len(rows),
            "decision": {
                "sensitive_work_orders": sorted(sensitive_wos, key=lambda x: -x["worst_offset_days"]),
                "global_risk_switches": sorted(risk_switches, key=lambda x: -x["affected_count"]),
                "summary": _hammer_summary(rows),
            }}


def _date_delta(eta, due) -> Optional[float]:
    """ETA 相对交期的偏移天数（正=延后，负=提前）。None 无法计算。"""
    if not eta:
        return None
    try:
        from datetime import datetime
        eta_dt = datetime.strptime(str(eta)[:10], "%Y-%m-%d")
        due_dt = datetime.strptime(str(due)[:10], "%Y-%m-%d")
        return round((eta_dt - due_dt).total_seconds() / 86400, 1)
    except Exception:
        return None



def _fallback_production_days(wo, opts) -> float:
    """兜底生产天数：量 ÷ (UPH 12 × 每日工时 × 班次系数 × 良率)。"""
    qty = float(wo["planned_qty"] or 0)
    uph = 12.0
    hours_day = 20.0 if (opts or {}).get("shift_mode") == "double" else 10.0
    yield_rate = float((opts or {}).get("yield_rate") or 0.97)
    line_share = 0.5 if (opts or {}).get("line_occupancy") == "shared_50" else 1.0
    iqc_h = 4.0 if (opts or {}).get("iqc_mode") == "sampling" else 8.0 if (opts or {}).get("iqc_mode") == "full" else 0.0
    customs_h = 24.0 if (opts or {}).get("customs_mode") == "random" else 0.0
    if qty <= 0 or uph <= 0:
        return 0.0
    prod_h = qty / yield_rate / (uph * line_share)
    total_h = prod_h + iqc_h + customs_h
    return total_h / (hours_day * line_share) if hours_day > 0 else 1.0


def _fallback_eta_days(wo, opts) -> Optional[float]:
    """兜底 ETA 相对交期偏移（正=延后）：从今天起算生产天数 → ETA 与交期比。"""
    from datetime import datetime, date
    due = datetime.strptime(str(wo["planned_due"])[:10], "%Y-%m-%d")
    days = _fallback_production_days(wo, opts)
    eta = datetime.combine(date.today(), datetime.min.time()) + timedelta(days=days)
    return round((eta - due).total_seconds() / 86400, 1)


def _fallback_eta(wo, opts) -> str:
    from datetime import datetime, date
    days = _fallback_production_days(wo, opts)
    return str((datetime.combine(date.today(), datetime.min.time()) + timedelta(days=days)).date())



def _hammer_recommendation(r: Dict) -> str:
    """单工单推荐：找能改善的档位（负偏移）与需避免的档位。"""
    good = [c for c in r["cells"] if (c["offset_days"] or 0) < 0]
    bad = [c for c in r["cells"] if (c["offset_days"] or 0) > 2]
    parts = []
    if good:
        best = min(good, key=lambda c: c["offset_days"])
        parts.append(f"优先{best['label']}（提前{abs(round(best['offset_days'], 1))}天）")
    if bad:
        worst = max(bad, key=lambda c: c["offset_days"])
        parts.append(f"避免{worst['label']}（延后{round(worst['offset_days'], 1)}天）")
    if not parts:
        parts.append("当前排程较稳，无需大调整")
    return "；".join(parts)


def _hammer_summary(rows: List[Dict]) -> str:
    """一句话决策摘要。"""
    if not rows:
        return "无工单数据"
    urgent = [r for r in rows if r["priority"] == "urgent"]
    sensitive = [r for r in rows if max((c["offset_days"] or 0) for c in r["cells"]) > 2]
    parts = [f"{len(rows)} 个工单"]
    if urgent:
        parts.append(f"{len(urgent)} 个急单")
    if sensitive:
        parts.append(f"{len(sensitive)} 个排程敏感（需重点保障）")
    else:
        parts.append("排程稳健")
    return "，".join(parts)


@router.get("/personal-plan", summary="个人工作任务计划表：按人聚合今日工作")
async def personal_plan(
    person: str = "",
    date: str = "",
    db: AsyncSession = Depends(get_db),
):
    """按人聚合今日工作任务计划表：
    - 我的工单（assigned_to 或产线工位）
    - 我的跟进任务（followup_tasks assigned_to）
    - 待我审批（rcc_tasks approved_by 或岗位）
    - 需我跟催（采购 PO/群消息）
    """
    fid = "FAC_MECH_001"
    person = person.strip() or "eric"
    from datetime import datetime as _dt
    today = _dt.strptime(date, "%Y-%m-%d").date() if date else _dt.now().date()

    # 1) 我的工单（今天有排程/交期的）
    wos = (await db.execute(text("""
        SELECT work_order_code, product_id, planned_qty, planned_due, status, priority
        FROM work_orders
        WHERE factory_id=:f AND assigned_to=:p AND status IN ('pending','released','in_progress')
        ORDER BY planned_due LIMIT 20
    """), {"f": fid, "p": person})).mappings().all()

    # 2) 我的跟进任务
    tasks = (await db.execute(text("""
        SELECT id, title, status, progress_pct, next_follow_at
        FROM followup_tasks
        WHERE assigned_to=:p AND status NOT IN ('done','cancelled')
        ORDER BY next_follow_at LIMIT 20
    """), {"p": person})).mappings().all()

    # 3) 待我审批（RCC 调度 + 我的岗位收到的通知）
    approvals = (await db.execute(text("""
        SELECT task_code, task_type, title, status, created_at
        FROM rcc_tasks
        WHERE status='pending'
        ORDER BY created_at DESC LIMIT 10
    """), {})).mappings().all()

    # 4) 我的通知
    notifs = (await db.execute(text("""
        SELECT title, category, content, created_at, is_read
        FROM notifications
        WHERE recipient=:p AND is_read=false
        ORDER BY created_at DESC LIMIT 10
    """), {"p": person})).mappings().all()

    # 5) 今日变更（pmc_changes 影响我的）
    changes = (await db.execute(text("""
        SELECT change_type, target_code, before_value, after_value, reason, created_at
        FROM pmc_changes
        WHERE factory_id=:f AND created_at::date=:t
        ORDER BY created_at DESC LIMIT 10
    """), {"f": fid, "t": today})).mappings().all()

    return {
        "person": person, "date": str(today),
        "summary": {
            "work_orders": len(wos), "tasks": len(tasks),
            "approvals": len(approvals), "notifications": len(notifs),
            "changes_today": len(changes),
        },
        "work_orders": [{"code": w["work_order_code"], "product": w["product_id"],
                         "qty": w["planned_qty"], "due": str(w["planned_due"])[:10],
                         "status": w["status"], "priority": w["priority"]} for w in wos],
        "tasks": [{"id": t["id"], "title": t["title"], "status": t["status"],
                   "progress": str(t["progress_pct"]), "next_follow": str(t["next_follow_at"])[:16] if t["next_follow_at"] else ""} for t in tasks],
        "approvals": [{"code": a["task_code"], "type": a["task_type"], "title": a["title"],
                       "created": str(a["created_at"])[:16]} for a in approvals],
        "notifications": [{"title": n["title"], "category": n["category"],
                           "content": (n["content"] or "")[:100], "at": str(n["created_at"])[:16]} for n in notifs],
        "changes": [{"type": c["change_type"], "target": c["target_code"],
                     "change": f"{c['before_value']} → {c['after_value']}",
                     "reason": c["reason"], "at": str(c["created_at"])[:16]} for c in changes],
    }


# ═══ PO/PR 单据模板（标准采购单据，可打印/存 PDF）═══
def _doc_style() -> str:
    return """
    <style>
      body { font-family: "PingFang SC", "Microsoft YaHei", sans-serif; margin: 24px; color: #222; }
      .doc-header { display: flex; justify-content: space-between; border-bottom: 2px solid #333; padding-bottom: 12px; }
      .doc-title { font-size: 24px; font-weight: 700; }
      .doc-no { font-size: 14px; color: #555; margin-top: 4px; }
      .doc-parties { display: flex; justify-content: space-between; margin: 16px 0; }
      .party-box { width: 45%; font-size: 13px; line-height: 1.8; }
      .party-label { font-weight: 700; margin-bottom: 4px; }
      table.items { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; }
      table.items th { background: #f0f0f0; border: 1px solid #ccc; padding: 8px; text-align: left; }
      table.items td { border: 1px solid #ccc; padding: 8px; }
      table.items td.num { text-align: right; }
      .doc-meta { font-size: 13px; line-height: 2; margin: 12px 0; }
      .doc-total { text-align: right; font-size: 15px; font-weight: 700; margin: 8px 0; }
      .doc-footer { margin-top: 32px; font-size: 12px; color: #777; border-top: 1px solid #ddd; padding-top: 8px; }
      .sign-row { display: flex; justify-content: space-between; margin-top: 48px; font-size: 13px; }
      .sign-box { width: 30%; text-align: center; }
      .sign-line { border-top: 1px solid #333; margin-top: 32px; padding-top: 4px; }
    </style>
    """


@router.get("/doc-template/{doc_type}", summary="统一单据模板（注册表驱动，11类）")
async def doc_template_unified(doc_type: str, code: str = "", db: AsyncSession = Depends(get_db)):
    """统一单据生成：rfq/quotation/pr/po/gr/delivery_note/statement/invoice/work_order/picking_list/production_report。
    数据源/列/条款全部由 doc_template_service.DOC_TYPES 注册表驱动。
    """
    from sqlalchemy import text as sql_text
    from api.services.doc_template_service import DOC_TYPES, render_doc, CODE_COLUMNS
    cfg = DOC_TYPES.get(doc_type)
    if not cfg:
        return HTMLResponse(f"<h3>未知单据类型 {doc_type}，可用: {list(DOC_TYPES.keys())}</h3>", status_code=400)
    if not code:
        return HTMLResponse("<h3>缺少 code 参数</h3>", status_code=400)
    row = (await db.execute(sql_text(cfg["query"]), {"c": code})).mappings().first()
    if not row:
        return HTMLResponse(f"<h3>{doc_type.upper()} {code} 不存在</h3>", status_code=404)
    rd = dict(row)
    # 多行单据（领料单/对账函）取 items
    if doc_type in ("picking_list", "statement"):
        rows = (await db.execute(sql_text(cfg["query"]), {"c": code})).mappings().all()
        rd["_items"] = [dict(r) for r in rows]
    doc_code = rd.get(CODE_COLUMNS.get(doc_type, "")) or code
    if doc_type == "delivery_note":
        doc_code = "DN-" + str(doc_code)[:8].upper()
    if doc_type == "quotation":
        doc_code = "QT-" + str(doc_code)[:8].upper()
    doc_date = str(row["created_at"])[:10] if "created_at" in rd and rd["created_at"] else datetime.now().strftime("%Y-%m-%d")
    return HTMLResponse(render_doc(doc_type, rd, str(doc_code), doc_date))



# ==================== PR 请购审批工作流（行业标准：请购→审批→转采购） ====================

PR_AUTO_APPROVE_LIMIT = 5000.0  # 金额阈值（元）：低于自动通过，高于需人工审批


async def _ensure_pr_approval_columns(db: AsyncSession):
    """PR 审批字段补齐（幂等，逐条执行——asyncpg 不支持多语句）"""
    for stmt in (
        "ALTER TABLE purchase_requisitions ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP",
        "ALTER TABLE purchase_requisitions ADD COLUMN IF NOT EXISTS rejection_reason TEXT",
        "ALTER TABLE purchase_requisitions ADD COLUMN IF NOT EXISTS approved_comment TEXT",
    ):
        await db.execute(text(stmt))
    await db.commit()


@router.get("/purchase-requisitions/summary", summary="PR 审批队列统计")
async def pr_approval_summary(
    factory_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fid = factory_id or current_user.factory_id or "FAC_MECH_001"
    await _ensure_pr_approval_columns(db)
    rows = (await db.execute(text("""
        SELECT LOWER(status) AS st, COUNT(*)::int AS n,
               COALESCE(SUM(estimated_cost),0)::float AS amount
        FROM purchase_requisitions WHERE factory_id=:f
        GROUP BY LOWER(status)
    """), {"f": fid})).fetchall()
    dist = {r[0]: {"count": r[1], "amount": round(r[2], 2)} for r in rows}
    pending = dist.get("pending", {"count": 0, "amount": 0})
    manual = (await db.execute(text("""
        SELECT COUNT(*)::int, COALESCE(SUM(estimated_cost),0)::float
        FROM purchase_requisitions
        WHERE factory_id=:f AND LOWER(status)='pending' AND COALESCE(estimated_cost,0) > :lim
    """), {"f": fid, "lim": PR_AUTO_APPROVE_LIMIT})).fetchone()
    return {
        "factory_id": fid,
        "status_distribution": dist,
        "pending_total": pending["count"],
        "pending_amount": pending["amount"],
        "needs_manual_review": manual[0] if manual else 0,
        "needs_manual_amount": round(manual[1], 2) if manual else 0,
        "auto_approve_limit": PR_AUTO_APPROVE_LIMIT,
    }


@router.get("/purchase-requisitions", summary="PR 请购单列表（含审批状态/金额分级）")
async def list_purchase_requisitions(
    factory_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fid = factory_id or current_user.factory_id or "FAC_MECH_001"
    await _ensure_pr_approval_columns(db)
    sql = """
        SELECT id, pr_code, material_code, material_name, qty, unit, required_date,
               status, priority, estimated_cost, supplier_id, source, created_by,
               approved_by, approved_at, rejection_reason, created_at
        FROM purchase_requisitions WHERE factory_id=:f
    """
    params: Dict[str, Any] = {"f": fid, "limit": limit}
    if status:
        sql += " AND LOWER(status)=:st"
        params["st"] = status.lower()
    sql += " ORDER BY created_at DESC LIMIT :limit"
    rows = (await db.execute(text(sql), params)).fetchall()
    return {"items": [{
        "id": r[0], "pr_code": r[1], "material_code": r[2], "material_name": r[3],
        "qty": float(r[4] or 0), "unit": r[5], "required_date": str(r[6])[:10] if r[6] else None,
        "status": (r[7] or "").lower(), "priority": r[8],
        "estimated_cost": float(r[9] or 0), "supplier_id": r[10], "source": r[11],
        "created_by": r[12], "approved_by": r[13],
        "approved_at": str(r[14])[:16] if r[14] else None,
        "rejection_reason": r[15], "created_at": str(r[16])[:16],
        "needs_manual": float(r[9] or 0) > PR_AUTO_APPROVE_LIMIT,
    } for r in rows]}


@router.post("/purchase-requisitions/{pr_id}/approve", summary="审批通过 PR（可选直接转采购下单）")
async def approve_purchase_requisition(
    pr_id: str,
    action: str = Query("approve", description="approve=仅批准; approve_and_order=批准并自动下单"),
    comment: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _ensure_pr_approval_columns(db)
    row = (await db.execute(text(
        "SELECT id, pr_code, status, factory_id FROM purchase_requisitions WHERE id=:id"
    ), {"id": pr_id})).mappings().first()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="PR 不存在")
    if (row["status"] or "").lower() not in ("pending", "approved"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"PR 当前状态 {row['status']} 不可审批")
    await db.execute(text("""
        UPDATE purchase_requisitions
        SET status='approved', approved_by=:by, approved_at=NOW(),
            approved_comment=:c, auto_approved=FALSE, rejection_reason=NULL, updated_at=NOW()
        WHERE id=:id
    """), {"id": pr_id, "by": current_user.username, "c": comment or None})
    await db.commit()
    result: Dict[str, Any] = {"success": True, "pr_code": row["pr_code"], "status": "approved", "approved_by": current_user.username}
    if action == "approve_and_order":
        from api.services.procurement_service import ProcurementService
        po_result = await ProcurementService(db).auto_create_po(row["factory_id"], pr_id)
        result["order_result"] = po_result
    return result


@router.post("/purchase-requisitions/{pr_id}/reject", summary="驳回 PR")
async def reject_purchase_requisition(
    pr_id: str,
    reason: str = Query(..., min_length=2, description="驳回原因（必填）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _ensure_pr_approval_columns(db)
    row = (await db.execute(text(
        "SELECT id, pr_code, status FROM purchase_requisitions WHERE id=:id"
    ), {"id": pr_id})).mappings().first()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="PR 不存在")
    if (row["status"] or "").lower() != "pending":
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"PR 当前状态 {row['status']} 不可驳回")
    await db.execute(text("""
        UPDATE purchase_requisitions
        SET status='rejected', approved_by=:by, approved_at=NOW(), rejection_reason=:r, updated_at=NOW()
        WHERE id=:id
    """), {"id": pr_id, "by": current_user.username, "r": reason})
    await db.commit()
    return {"success": True, "pr_code": row["pr_code"], "status": "rejected", "reason": reason}

# ==================== 收货→IQC→入库放行工作流（行业标准闭环） ====================

@router.get("/goods-receipts", summary="收货单列表（含 IQC 检验状态）")
async def list_goods_receipts(
    factory_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fid = factory_id or current_user.factory_id or "FAC_MECH_001"
    await db.execute(text("ALTER TABLE goods_receipts ADD COLUMN IF NOT EXISTS inspection_task_id VARCHAR(50)"))
    await db.commit()
    sql = """
        SELECT gr.id, gr.gr_code, gr.po_id, po.po_code, gr.material_code, gr.supplier_id,
               gr.quantity, gr.qty_accepted, gr.qty_rejected, gr.iqc_status, gr.warehouse,
               gr.received_by, gr.received_at, gr.inspection_task_id, it.task_code, it.status
        FROM goods_receipts gr
        LEFT JOIN purchase_orders po ON po.id=gr.po_id
        LEFT JOIN inspection_tasks it ON it.id=gr.inspection_task_id
        WHERE gr.factory_id=:f
    """
    params: Dict[str, Any] = {"f": fid, "limit": limit}
    if status:
        sql += " AND gr.iqc_status=:st"
        params["st"] = status
    sql += " ORDER BY gr.received_at DESC NULLS LAST LIMIT :limit"
    rows = (await db.execute(text(sql), params)).fetchall()
    return {"items": [{
        "id": r[0], "gr_code": r[1], "po_id": r[2], "po_code": r[3], "material_code": r[4],
        "supplier_id": r[5], "quantity": float(r[6] or 0), "qty_accepted": float(r[7] or 0),
        "qty_rejected": float(r[8] or 0), "iqc_status": r[9], "warehouse": r[10],
        "received_by": r[11], "received_at": str(r[12])[:16] if r[12] else None,
        "inspection_task_id": r[13], "inspection_task_code": r[14], "inspection_status": r[15],
    } for r in rows]}


@router.post("/goods-receipts/{gr_id}/inspect", summary="IQC 检验结论（合格放行/拒收退供）")
async def inspect_goods_receipt(
    gr_id: str,
    result: str = Query(..., description="passed=合格放行 / conditional=让步接收 / rejected=拒收"),
    qty_accepted: Optional[float] = None,
    qty_rejected: Optional[float] = None,
    remark: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """行业闭环：收货→IQC检验→合格放行入库 / 拒收扣回并退供。"""
    from fastapi import HTTPException
    if result not in ("passed", "conditional", "rejected"):
        raise HTTPException(status_code=400, detail="result 必须是 passed/conditional/rejected")
    await db.execute(text("ALTER TABLE goods_receipts ADD COLUMN IF NOT EXISTS inspection_task_id VARCHAR(50)"))
    await db.commit()
    gr = (await db.execute(text(
        "SELECT id, gr_code, factory_id, material_code, quantity, qty_accepted, inspection_task_id "
        "FROM goods_receipts WHERE id=:id"
    ), {"id": gr_id})).mappings().first()
    if not gr:
        raise HTTPException(status_code=404, detail="收货单不存在")
    total = float(gr["quantity"] or 0)
    acc = float(qty_accepted if qty_accepted is not None else (total if result != "rejected" else 0))
    rej = float(qty_rejected if qty_rejected is not None else max(total - acc, 0))
    iqc_status = {"passed": "passed", "conditional": "conditional", "rejected": "rejected"}[result]
    await db.execute(text("""
        UPDATE goods_receipts SET iqc_status=:s, qty_accepted=:acc, qty_rejected=:rej WHERE id=:id
    """), {"s": iqc_status, "acc": acc, "rej": rej, "id": gr_id})
    # 同步关闭关联检验任务
    if gr["inspection_task_id"]:
        await db.execute(text("""
            UPDATE inspection_tasks SET status='completed', result=:r, defect_qty=:rej,
                inspector=:by, completed_at=NOW(), remark=:rm, updated_at=NOW()
            WHERE id=:t
        """), {"r": "passed" if result != "rejected" else "failed", "rej": rej,
               "by": current_user.username, "rm": remark or None, "t": gr["inspection_task_id"]})
    effects: Dict[str, Any] = {}
    if result == "rejected":
        # 拒收：已入账的合格量扣回，避免未合格库存被占用
        old_acc = float(gr["qty_accepted"] or 0)
        if old_acc > 0:
            await db.execute(text("""
                UPDATE inventory SET available_qty=GREATEST(available_qty-:q,0), total_qty=GREATEST(total_qty-:q,0)
                WHERE material_code=:m AND factory_id=:f
            """), {"q": old_acc, "m": gr["material_code"], "f": gr["factory_id"]})
            effects["inventory_rolled_back"] = old_acc
        effects["next_step"] = "建议开退供单（模板：退料单/来料异常报告）并通知供应商"
    else:
        # 合格/让步接收：放行标记库存合格状态
        await db.execute(text("""
            UPDATE inventory SET qualified_status='qualified'
            WHERE material_code=:m AND factory_id=:f AND (qualified_status IS NULL OR qualified_status='pending')
        """), {"m": gr["material_code"], "f": gr["factory_id"]})
        effects["released_to_stock"] = acc
    await db.commit()
    return {"success": True, "gr_code": gr["gr_code"], "iqc_status": iqc_status,
            "qty_accepted": acc, "qty_rejected": rej, "inspector": current_user.username,
            "effects": effects}

# ==================== PO 采购订单管理（字段补齐 + 收货闭环） ====================

PO_EXTRA_COLUMNS = (
    "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS received_qty NUMERIC DEFAULT 0",
    "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS tax_rate NUMERIC",
    "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS payment_terms VARCHAR(50)",
    "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS contract_no VARCHAR(50)",
    "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS delivery_address VARCHAR(200)",
    "ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS supplier_contact VARCHAR(80)",
)


async def _ensure_po_columns(db: AsyncSession):
    for stmt in PO_EXTRA_COLUMNS:
        await db.execute(text(stmt))
    await db.commit()


@router.get("/purchase-orders", summary="采购订单列表（收货进度/逾期/闭环状态）")
async def list_purchase_orders(
    factory_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    fid = factory_id or current_user.factory_id or "FAC_MECH_001"
    await _ensure_po_columns(db)
    sql = """
        SELECT id, po_code, pr_id, supplier_id, supplier_name, material_code, material_name,
               qty, COALESCE(received_qty,0), unit_price, total_amount, currency,
               order_date, expected_date, actual_date, status, auto_generated, tax_rate,
               payment_terms, contract_no,
               CASE WHEN expected_date < CURRENT_DATE
                     AND status NOT IN ('received','completed','cancelled','closed')
                    THEN (CURRENT_DATE - expected_date) ELSE 0 END AS overdue_days
        FROM purchase_orders WHERE factory_id=:f
    """
    params: Dict[str, Any] = {"f": fid, "limit": limit}
    if status:
        sql += " AND status=:st"
        params["st"] = status
    sql += " ORDER BY order_date DESC NULLS LAST LIMIT :limit"
    rows = (await db.execute(text(sql), params)).fetchall()
    items = []
    for r in rows:
        qty, recv = float(r[7] or 0), float(r[8] or 0)
        items.append({
            "id": r[0], "po_code": r[1], "pr_id": r[2], "supplier_id": r[3], "supplier_name": r[4],
            "material_code": r[5], "material_name": r[6], "qty": qty, "received_qty": recv,
            "receipt_pct": round(recv / qty * 100, 1) if qty else 0,
            "unit_price": float(r[9] or 0), "total_amount": float(r[10] or 0), "currency": r[11],
            "order_date": str(r[12])[:10] if r[12] else None,
            "expected_date": str(r[13])[:10] if r[13] else None,
            "actual_date": str(r[14])[:10] if r[14] else None,
            "status": r[15], "auto_generated": r[16], "tax_rate": float(r[17]) if r[17] is not None else None,
            "payment_terms": r[18], "contract_no": r[19],
            "overdue_days": int(r[20] or 0),
            "complete": qty > 0 and recv >= qty,
        })
    return {"items": items}


@router.post("/purchase-orders/{po_id}/receive", summary="PO 收货登记（累计收货量+生成GR+触发IQC）")
async def receive_purchase_order(
    po_id: str,
    quantity: float = Query(..., gt=0, description="本次收货数量"),
    warehouse: str = "MAIN",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """收货闭环：累计 received_qty → 部分收货/完全收货状态 → 生成 GR 并触发 IQC。"""
    from fastapi import HTTPException
    import uuid as _uuid
    await _ensure_po_columns(db)
    po = (await db.execute(text(
        "SELECT id, po_code, factory_id, material_code, supplier_id, qty, status, COALESCE(received_qty,0) AS recv "
        "FROM purchase_orders WHERE id=:id"
    ), {"id": po_id})).mappings().first()
    if not po:
        raise HTTPException(status_code=404, detail="PO 不存在")
    if po["status"] in ("cancelled", "closed"):
        raise HTTPException(status_code=400, detail=f"PO 状态 {po['status']} 不可收货")
    new_recv = float(po["recv"]) + quantity
    new_status = "received" if new_recv >= float(po["qty"] or 0) else "partially_received"
    gr_id, gr_code = str(_uuid.uuid4()), f"GR-{datetime.now().strftime('%Y%m%d')}-{str(_uuid.uuid4())[:6].upper()}"
    await db.execute(text("ALTER TABLE goods_receipts ADD COLUMN IF NOT EXISTS inspection_task_id VARCHAR(50)"))
    await db.execute(text("""
        INSERT INTO goods_receipts (id, gr_code, factory_id, po_id, material_code, supplier_id,
                                    quantity, qty_accepted, qty_rejected, iqc_status, warehouse, received_by, received_at)
        VALUES (:id,:code,:f,:po,:m,:sup,:q,0,0,'pending',:wh,:by,NOW())
    """), {"id": gr_id, "code": gr_code, "f": po["factory_id"], "po": po_id, "m": po["material_code"],
           "sup": po["supplier_id"], "q": quantity, "wh": warehouse, "by": current_user.username})
    await db.execute(text("""
        UPDATE purchase_orders SET received_qty=:recv, status=:st, updated_at=NOW()
        WHERE id=:id
    """), {"recv": new_recv, "st": new_status, "id": po_id})
    if new_status == "received":
        await db.execute(text(
            "UPDATE purchase_orders SET actual_date=CURRENT_DATE WHERE id=:id"
        ), {"id": po_id})
    # 触发 IQC 检验任务（收货→IQC 联动）
    iqc_code = None
    try:
        from api.services.inspection_service import InspectionService
        iqc_task = await InspectionService(db).create_task(
            factory_id=po["factory_id"], inspect_type="iqc",
            material_code=po["material_code"], batch_qty=int(quantity),
            source_type="goods_receipt", source_code=gr_code, created_by=current_user.username,
        )
        iqc_code = iqc_task.get("task_code")
        await db.execute(text(
            "UPDATE goods_receipts SET iqc_status='inspecting', inspection_task_id=:t WHERE id=:id"
        ), {"t": iqc_task.get("id"), "id": gr_id})
    except Exception as _e:
        import logging as _lg
        _lg.getLogger("pmc").warning(f"[PO收货] IQC任务生成失败(不阻塞): {_e}")
    await db.commit()
    return {"success": True, "po_code": po["po_code"], "gr_code": gr_code,
            "received_qty": new_recv, "po_status": new_status,
            "inspection_task_code": iqc_code,
            "message": f"收货 {quantity}，累计 {new_recv}/{po['qty']}，IQC单 {iqc_code or '(未生成)'} 待检"}


@router.post("/purchase-orders/{po_id}/cancel", summary="取消 PO")
async def cancel_purchase_order(
    po_id: str,
    reason: str = Query("", description="取消原因"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from fastapi import HTTPException
    await _ensure_po_columns(db)
    res = await db.execute(text("""
        UPDATE purchase_orders SET status='cancelled', updated_at=NOW()
        WHERE id=:id AND status NOT IN ('received','completed','cancelled')
    """), {"id": po_id})
    await db.commit()
    if res.rowcount == 0:
        raise HTTPException(status_code=400, detail="PO 不存在或已收货/已取消，不可取消")
    return {"success": True, "status": "cancelled", "reason": reason}


@router.post("/purchase-requisitions/backfill-costs", summary="存量 PR 成本回填（幂等：仅补空/0，估算口径：报价→库存成本→mock）")
async def backfill_pr_costs(
    factory_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from api.services.procurement_service import estimate_unit_cost
    fid = factory_id or current_user.factory_id or "FAC_MECH_001"
    rows = (await db.execute(text("""
        SELECT id, material_code, qty FROM purchase_requisitions
        WHERE factory_id=:f AND (estimated_cost IS NULL OR estimated_cost=0)
    """), {"f": fid})).fetchall()
    filled = 0
    for r in rows:
        cost = round(float(r[2] or 0) * await estimate_unit_cost(db, r[1]), 2)
        await db.execute(text(
            "UPDATE purchase_requisitions SET estimated_cost=:c, updated_at=NOW() WHERE id=:id"
        ), {"c": cost, "id": r[0]})
        filled += 1
    await db.commit()
    return {"success": True, "factory_id": fid, "backfilled": filled,
            "note": "单价口径：供应商报价 → 库存单位成本 → 确定性 mock（同物料恒价）"}
