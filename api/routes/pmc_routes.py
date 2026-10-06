"""PMC 工作矩阵接口。"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.security import get_current_user
from database.db_config import get_db
from database.models import User
from api.services.pmc_control_tower_service import PmcControlTowerService
from api.services.bom_data_quality import scan as scan_bom_quality
from api.services.pmc_work_matrix_service import PmcWorkMatrixService
from api.services.plan_commit_gate import (
    MAX_ORDERS as PLAN_COMMIT_MAX_ORDERS,
    evaluate_commit_gate,
)
from api.services.aps_draft_prune import plan_prune
from api.services.chain_convergence import report as convergence_report
from api.services.idle_capacity import idle_capacity_report
from api.services.option_simulator import compare_options

router = APIRouter(prefix="/api/v1/pmc", tags=["PMC - 工作矩阵"])


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
            "work_order_materials": ["work_order_id", "material_code", "required_qty", "available_qty", "received_qty", "shortage_qty", "level", "parent_code", "item_type"],
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


@router.get("/delivery/risk", summary="获取交期风险（按实际生产速度推算）")
async def get_delivery_risk(
    factory_id: str = Query(...),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """在制工单按已完成量的实际速度推算，预计晚于 planned_due 即为交期风险。

    与 `/delivery/countdown` 的日历红黄绿灯是两件事：那边看距交期还有几天，
    这里看按当前速度来不来得及。chatbot、PMC 控制塔、交期智能体共用同一实现。
    """
    del current_user
    from api.services.pmc_control_tower_service import PmcControlTowerService
    return await PmcControlTowerService(db).delivery_risk(factory_id, limit=limit)


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
            {"key": "delivery_risk", "name": "交期风险（按实际速度推算，与智能体同源）", "path": "/api/v1/pmc/delivery/risk", "mode": "read_only"},
            {"key": "data_readiness", "name": "PMC 数据完整性与补数清单", "path": "/api/v1/pmc/data-readiness", "mode": "read_only"},
            {"key": "bom_quality", "name": "BOM 数据质量自检（命名/分类/断链，带影响缺口）",
             "path": "/api/v1/pmc/bom-quality", "mode": "read_only"},
            {"key": "plan_commit_gate", "name": "计划逐单下达就绪门（哪些单真能开工、差哪条门）",
             "path": "/api/v1/pmc/plan-commit-gate", "mode": "read_only"},
            {"key": "aps_draft_prune", "name": "旧排产草案回收预演（keep-last-N，只读）",
             "path": "/api/v1/pmc/aps-draft_prune", "mode": "read_only"},
            {"key": "chain_convergence", "name": "链条收敛自检（有没有真的往前走）",
             "path": "/api/v1/pmc/chain-convergence", "mode": "read_only"},
            {"key": "idle_capacity", "name": "闲置产能台账（人·小时，成本判断的底）",
             "path": "/api/v1/pmc/idle-capacity", "mode": "read_only"},
            {"key": "production_options", "name": "缺料时的生产选择推演（多策略比较）",
             "path": "/api/v1/pmc/production-options", "mode": "read_only"},
            {"key": "position_trainer", "name": "PMC 职位训练器", "path": "/api/v1/trainer/pack?position_code=pmc", "mode": "training"},
        ],
        "note": "所有评审、ATP 和沙盘结果均不直接修改订单/MPS；下达仍由 PP/MPS 授权流程执行。"
                "APS 逐单就绪门同样默认只预演，要机器自己放行得显式打开 PLAN_COMMIT_APPLY。",
    }


@router.get("/bom-quality", summary="BOM 数据质量自检（只读，按影响缺口排序）")
async def get_bom_quality(
    product_model: str = Query(..., description="要扫的机种（= BOM 的 model_name）"),
    factory_id: str = Query(..., description="厂区；不给默认值，免得拿一个厂的结果回答另一个厂的问题"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """无人工厂自己报 BOM 脏数据：命名不规范、缺分类、缺单位、单价形状异常、图纸行当物料、
    层级断链、同料号多父级 —— 每条带**影响多少缺口**，先改最挡生产的那条。

    只读：不修 BOM、不改原始行；改数据是工程/PMC 走 ECR 的事。
    """
    del current_user
    return await scan_bom_quality(db, factory_id, product_model)


@router.get("/plan-commit-gate", summary="计划逐单下达就绪门（只读预演）")
async def get_plan_commit_gate(
    factory_id: str = Query(..., description="厂区；不给默认值，免得拿一个厂的计划回答另一个厂"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """这一版排程里哪些工单真的可以开工，差在哪一条门上。

    判据只有四条，全部来自库里的事实：排进本版本、工序排齐（任务行数=路线工序数）、
    任务行齐套、首道工序的工位编码能在本厂 stations 映射到。这里**只读**：不改工单状态、
    不下达；要机器自己放行得打开 PLAN_COMMIT_APPLY，每轮上限 PLAN_COMMIT_MAX_ORDERS 张。
    """
    del current_user
    gate = await evaluate_commit_gate(db, factory_id)
    gate["next_batch_limit"] = min(int(gate.get("ready_count") or 0), PLAN_COMMIT_MAX_ORDERS)
    return gate


@router.get("/aps-draft-prune", summary="旧排产草案回收预演（只读）")
async def get_aps_draft_prune(
    factory_id: str = Query("", description="留空=全部厂区"),
    keep: int = Query(3, ge=1, le=20, description="每厂区保留最近几版草案"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """回收窗口外还有哪些旧草案、各带多少行、哪几份因为压着锁定工序必须留下。

    只读预演：这里不删任何东西。真正删除只在引擎循环里发生，且需要显式打开
    `APS_DRAFT_PRUNE_ENABLED`。确认过/下达过/归档的方案一律不在候选集合里。
    """
    del current_user
    return await plan_prune(db, factory_id=factory_id, keep=keep)


@router.get("/production-options", summary="缺料时的生产选择推演（只读，多策略比较）")
async def get_production_options(
    factory_id: str = Query(..., description="厂区"),
    objective: str = Query("labor_first", description="目标：labor_first/delivery_first/total_cost/balanced"),
    days: int = Query(30, ge=3, le=180, description="推演天数（按仿真日历）"),
    order_codes: str = Query("", description="只推演这几张工单，逗号分隔；留空=全部在制单"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """同一份现状跑四条路：等料 / 能干就先干（部分投产）/ 按交期重排 / 调人补线。

    为什么不是"欠料就卡住不排产"：现实里工厂的目标是能赚钱、能省钱、能维持人力利用，
    这几条经常互相冲突，所以要给的是**每条路的后果比较**，不是一个"能不能开工"的是非题。
    假设与模型边界随结果一起报出（assumptions / transfer_note），只读，不改任何工单或库存。
    """
    del current_user
    codes = [c.strip() for c in order_codes.split(",") if c.strip()] or None
    return await compare_options(db, factory_id, objective=objective, days=days, order_codes=codes)


@router.get("/idle-capacity", summary="闲置产能台账（只读，按工位报人·小时）")
async def get_idle_capacity(
    factory_id: str = Query(..., description="厂区"),
    objective: str = Query("labor_first",
                           description="目标：labor_first / delivery_first / total_cost / balanced"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """这一版方案覆盖的几天里：每个工位排了多少工时、其中多少属于开不了工的缺料单、
    真闲置多少、以及"有没有齐套却没排的单能就地填满"。

    成本判断的形状：人力在岗即付（缺料 3 天且没别的单可做就是确定损失），
    设备全款则停着只是折旧 —— 所以"要不要调线"看的是人，不是机器。

    单价库里确实没有（hr_employees 1,747 人 0 个薪资列、equipment 无原值），
    所以钱是按**内置默认标定**乘出来的，每项在 cost_basis 里标 default_calibration / override+来源；
    换一个 objective（人力优先 / 交期优先 / 总成本）就换一套权重和排序，答案本身随目标变。
    """
    del current_user
    return await idle_capacity_report(db, factory_id, objective=objective)


@router.get("/chain-convergence", summary="无人链条收敛自检（只读）")
async def get_chain_convergence(
    factory_id: str = Query(..., description="厂区"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """这一轮工厂有没有往前走：完工、放行、缺口三个数与上一轮心跳对撞。

    无人跑的系统最怕"心跳一直 tick、工厂一步不动"。这里把判定规则连同来源一起报出来：
    `advancing / diverging / stalled`，以及"本厂 24 小时内有没有真实报工输入"——
    没有报工时缺料单不可能自己清零，这条必须写在原因里，不能被读成"算法没干活"。
    """
    del current_user
    return await convergence_report(db, factory_id)


__all__ = ["router"]
