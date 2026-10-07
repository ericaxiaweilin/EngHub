"""PMC 工作矩阵接口。"""

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
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
from api.services.time_basis import time_basis_audit
from api.services.data_authority import data_authority_report
from api.services.attendance_model import expected_attendance
from api.services.partial_kit import partial_kit_opportunities

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
            {"key": "sim_sensitivity", "name": "建模精度×敏感度（每个输入动一档，交期/准点/钱变多少；含补数据的量化价值）",
             "path": "/api/v1/pmc/sim-sensitivity", "mode": "read_only"},
            {"key": "engine_layers", "name": "仿真引擎分层验收（五层判据+过线闸门，下层不过线上层不引用）",
             "path": "/api/v1/pmc/engine-layers", "mode": "read_only"},
            {"key": "engine_contract", "name": "引擎对外契约（三接口签名+业务词表，与模型内部无关；自检见 /engine-contract-check）",
             "path": "/api/v1/pmc/engine-contract", "mode": "read_only"},
            {"key": "sim_readiness", "name": "精度判据就绪度（可比机种、回测成对样本、缺齐套行的归因）",
             "path": "/api/v1/pmc/sim-readiness", "mode": "read_only"},
            {"key": "engine_watchdog", "name": "引擎自身故障巡检：心跳断写/崩溃越线自动挂催办，恢复自动关（默认预演）",
             "path": "/api/v1/pmc/engine-watchdog", "mode": "read_only"},
            {"key": "time_basis", "name": "预计工时出处与线/工位产能对撞（只读）",
             "path": "/api/v1/pmc/time-basis", "mode": "read_only"},
            {"key": "partial_kit", "name": "部分齐投产机会（还能先开几台，只读）",
             "path": "/api/v1/pmc/partial-kit", "mode": "read_only"},
            {"key": "data_authority", "name": "仿真输入数据源台账（IE/HR/考勤/设备/排产/齐套）",
             "path": "/api/v1/pmc/data-authority", "mode": "read_only"},
            {"key": "expected_attendance", "name": "按天气折算预计出勤（好天97%/雨92%/暴雨70%）",
             "path": "/api/v1/pmc/expected-attendance", "mode": "read_only"},
            {"key": "followup_lifecycle", "name": "缺料催办证据判定：齐套自动关闭 / 催不动升级（默认预演）",
             "path": "/api/v1/pmc/followup-lifecycle", "mode": "read_only"},
            {"key": "fake_output", "name": "虚假产出冲回：零领料却入库的半成品（默认只预演）",
             "path": "/api/v1/pmc/fake-output-revert", "mode": "read_only"},
            {"key": "position_trainer", "name": "PMC 职位训练器", "path": "/api/v1/trainer/pack?position_code=pmc", "mode": "training"},
        ],
        "note": "所有评审、ATP 和沙盘结果均不直接修改订单/MPS；下达仍由 PP/MPS 授权流程执行。"
                "APS 逐单就绪门同样默认只预演，要机器自己放行得显式打开 PLAN_COMMIT_APPLY。",
    }


@router.get("/expected-attendance", summary="按天气折算的预计出勤（只读，不写考勤表）")
async def get_expected_attendance(
    factory_id: str = Query(..., description="厂区"),
    on: Optional[date] = Query(None, description="哪一天，默认今天"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """预计到岗 = 在册人数 × 天气折算率（好天 97% / 雨 92% / 暴雨 70%，用户 10-06 标定）。

    天气有两层依据：当天用实况；仿真推进的日子没有预报，就用**北宁近 3 年逐日雨量的按月分布**
    定档 —— 同一天永远同一档（可复现），否则重排一次交期就变一套，账就没法对。
    阈值 30mm 算暴雨是我定的（北宁 3 年 1,096 天里 4.6% 达到），可用环境变量改。

    为什么算出来不写进 `attendance`：那是现场打卡表，灌生成记录就和真打卡分不开 ——
    这轮刚清掉一批"自己造的自己读"的数据。这里只出读数，天气来源、雨量、折算率、
    考勤断在哪天都随结果一起给；两层依据都拿不到就不折算，不拿 97% 冒充人到齐。
    """
    del current_user
    return await expected_attendance(db, factory_id, on=on)


@router.get("/followup-lifecycle", summary="缺料催办的证据判定（默认只预演：该关的、该升级的）")
async def get_followup_lifecycle(
    factory_id: str = Query(..., description="厂区"),
    apply: bool = Query(False, description="false=只出判定不动库；true 才真的关闭/挂升级单"),
    limit: int = Query(50, ge=1, le=200),
    closed_within_days: int = Query(7, ge=0, le=90,
                                    description="顺带复核最近几天内「已完成」的催办；0=不复核"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """催办闭环的两件事：齐套了就自己关（别继续追人），催不动就升级（别一直挂着当已处理）。

    判定一律按 `work_order_materials` 的当前缺口算，不看模型上一轮写了什么：
    缺口归零且快照有行 → 关闭；快照 0 行 → 判不了齐套，继续催并写明"没有依据"；
    缺口连续几轮一点没变小 → 升级成一条待人工裁决的单（改期/调线/外购/停线四个选项摆齐）。

    默认 `apply=false` 只报判定。要真的关单、挂升级单得显式带 `apply=true` ——
    关闭与升级都是动库的动作，先看判定准不准再让它落地。
    """
    del current_user
    from api.services.followup_lifecycle import (
        audit_false_closures, open_shortage_tasks, sync_shortage_task,
    )

    tasks = await open_shortage_tasks(db, factory_id, limit=limit)
    items = []
    for task in tasks:
        try:
            items.append(await sync_shortage_task(db, task, apply=apply))
        except Exception as exc:  # noqa: BLE001 — 一张单的判定失败不影响其余
            # 语句报错会把整个事务打成 aborted，不回滚的话后面每张单都只会报同一个错
            await db.rollback()
            items.append({"task_id": str(task.get("id")), "action": "error",
                          "note": f"{type(exc).__name__}: {exc}"})
    counts: Dict[str, int] = {}
    for item in items:
        counts[str(item.get("action"))] = counts.get(str(item.get("action")), 0) + 1
    # 关闭过的也要复核：只看未关闭的催办会把"被误判完成"的阻塞整个看不见
    closure_audit = (await audit_false_closures(db, factory_id, days=closed_within_days,
                                                limit=limit, apply=apply)
                     if closed_within_days else None)
    return {
        "factory_id": factory_id,
        "apply": apply,
        "examined": len(items),
        "action_counts": counts,
        "items": items,
        "closure_audit": closure_audit,
        "rule": ("关闭与升级都按齐套台账的缺口数判定；快照没有行的单不判齐套（空集合不等于通过）。"
                 "升级承接人从 HR 岗位台账找，找不到就把缺口写在单上等人认领，不编名字。"),
    }


@router.get("/fake-output-revert", summary="虚假产出冲回（默认只预演，动库存要显式 apply）")
async def get_fake_output_revert(
    factory_id: str = Query(..., description="厂区"),
    apply: bool = Query(False, description="false=只出清单；true 才反向过账并退单"),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """把"零投入却做出了成品"的产出冲回：反向过账、报工作废、工单退回待开工。

    判据要两条同时成立 —— ①齐套表里没有带需求量的物料行 ②这张单没有任何领料流水。
    只有①而没有②的单子是快照缺数据（镜像里没有组件级子 BOM，见 #46），
    那不是造假，不能拿冲库存去"修"一个数据缺口。

    冲回按原入库批次逐笔反向，上限是该批次当前可用量：已经被下游领走的部分**冲不回来**，
    如实写进 unrecoverable_qty，而不是记一笔负库存冒充平账。报工只标作废不删行，
    执行流水是仿真历史。apply=true 之前先把受影响行导出 CSV，写不出备份就不动库。
    """
    del current_user
    from api.services.fake_output_revert import revert, scan

    if apply:
        return await revert(db, factory_id, apply=True, limit=limit)
    report = await scan(db, factory_id, limit=limit)
    report["apply"] = False
    report["message"] = (f"候选 {report['candidates']} 张：可冲回 "
                         f"{report['counts']['revert_stock']} 张 / "
                         f"{report['totals']['revertible_qty']:g} 件；"
                         f"{report['counts']['protected_has_issues']} 张因有领料流水被保护；"
                         f"确认清单后带 apply=true 再执行。")
    return report


@router.get("/sim-tradeoffs", summary="政策×天气的权衡矩阵：帕累托前沿与跨场景稳健推荐（默认只算不写）")
async def get_sim_tradeoffs(
    factory_id: str = Query(..., description="厂区"),
    apply: bool = Query(False, description="true 才把权衡结果写进记分卡"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """引擎自己扫政策、自己评估质量：不给唯一最高分，给前沿和代价。

    天气是外生的，所以按场景分开算（好天/雨季/暴雨各一套前沿），跨场景用 minimax regret 选
    "最坏天气下后悔最小"的政策 —— 不赌天气，也不靠牺牲某一维刷分。产量不达标的解直接淘汰，
    否则"干脆不做"永远成本最优。加急和开并联线都带真实代价进目标向量。
    """
    del current_user
    from api.services.portfolio_flywheel import record_tradeoffs

    return await record_tradeoffs(db, factory_id, apply=apply)


@router.get("/data-evidence", summary="料号提前期的证据普查：台账值是不是量出来的，一调就知道")
async def get_data_evidence(
    factory_id: str = Query(..., description="厂区"),
    material_codes: str = Query("", description="逗号分隔的料号；留空则按 limit 抽样"),
    limit: int = Query(200, description="抽样/返回行数上限（组内分散度始终按全量算）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """只读普查：把 `materials.lead_time_days` 与采购实测、仓收实测、供应商声明摆在一起对。

    为什么要单独一个端点 —— 排产、交期、仿真都吃提前期这一个数，但没人说过它是量来的还是铺的。
    `verdict`：`measured`（有实测）/ `ledger_default_conflicts_with_measured`（台账比实测小一半以上）/
    `unverified_default`（同组几十~几千个料号共用同一个取值）/ `ledger_declared_only` / `no_lead_time_at_all`。
    建议值只写进 `suggested_days`，不回写台账 —— 它是"要去核对的数"，不是既成事实。
    """
    del current_user
    from core.mes.data_evidence import lead_time_evidence

    codes = [c.strip() for c in str(material_codes or "").split(",") if c.strip()]
    return await lead_time_evidence(db, factory_id, codes=codes or None, limit=max(1, int(limit)))


@router.get("/engine-layers", summary="仿真引擎分层验收：五层各自过线才算数，下层不过线上层不引用")
async def get_engine_layers(
    factory_id: str = Query(..., description="厂区"),
    n_models: int = Query(5, description="取 BOM 最完整的 n 个机种"),
    refresh: bool = Query(False, description="跳过缓存重算一遍（刚改过输入时用）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """分层验收（只读）：L1 内核 / L2A 敏感度 / L2B 准确度 / L3 决策 / L4 Agent 接口。

    每层的判据不一样，而且必须是算出来的数；样本不够或来源不存在就写 not_computable
    并点名缺哪个输入 —— 不打"0 分"，也不用别的层的数冒充。自下而上找第一个不过线的层，
    它以上的读数一律标 `reportable=false`：平行堆指标最后会变成"我们全都做得好"的自嗨报告。
    """
    del current_user
    from api.services.engine_layers import layered_acceptance
    from api.services.virtual_run import default_models

    models = await default_models(db, factory_id, n=max(1, min(8, int(n_models))))
    if not models:
        raise HTTPException(status_code=404, detail="厂区里没有可推演的机种（BOM 镜像为空？）")
    return await layered_acceptance(db, factory_id, models, use_cache=not refresh)


@router.get("/sim-sensitivity", summary="建模精度×敏感度：每个输入动一档，交期/准点/钱各变多少")
async def get_sim_sensitivity(
    factory_id: str = Query(..., description="厂区"),
    n_models: int = Query(5, description="取 BOM 最完整的 n 个机种"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """量化三段：①敏感度斜率（每档值几天、每天值多少钱）②映射精度（每项输入有多少真依据）
    ③误差传导（现在交期可信到几成、补哪项数据能压掉几天）。

    斜率只取基准两侧最近两档（局部线性）：提前期/库存那类曲线会阶跃，全局回归会把台阶抹平。
    只读：不写业务表、不改排产，也不回写任何外部系统。
    """
    del current_user
    from api.services.sim_sensitivity import report
    from api.services.virtual_run import default_models

    models = await default_models(db, factory_id, n=max(1, min(8, int(n_models))))
    if not models:
        raise HTTPException(status_code=404, detail="厂区里没有可推演的机种（BOM 镜像为空？）")
    return await report(db, factory_id, models)



async def _engine_contract_call(iface: str, db: AsyncSession, factory_id: str,
                                body: Dict[str, Any]) -> Dict[str, Any]:
    """契约调用的唯一入口：词表外的东西一律 422 并回 allowed，不静默忽略、不 500。"""
    from api.services.engine_contract import ContractError, attribution, sensitivity, simulate

    if not factory_id:
        raise HTTPException(status_code=422, detail="需要 factory_id")
    fn = {"simulate": simulate, "sensitivity": sensitivity, "attribution": attribution}[iface]
    try:
        return await fn(db, factory_id, body)
    except ContractError as exc:
        raise HTTPException(status_code=422, detail=exc.as_dict())


@router.get("/sim-readiness", summary="精度判据就绪度：L2B 那两个数为什么算不出，缺的是哪一类数据")
async def get_sim_readiness(
    factory_id: str = Query(..., description="厂区"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """只读：按机种列出 工单/齐套行/外购缺口行 与回测成对样本，再把缺口归成可行动的四类。

    这一页存在的意义是：判据说"算不出"时，得同时说清是**源侧没有**（组件级子 BOM、
    这台机种的 BOM 压根不在镜像里、出货柜这类伪产品、种子单）还是**我们跑一次就能补**。
    """
    del current_user
    from api.services.sim_backtest import readiness

    return await readiness(db, factory_id)


@router.get("/engine-watchdog", summary="引擎自身故障巡检：心跳断写/循环退出/窗口崩溃越线会挂成哪条催办")
async def get_engine_watchdog(
    factory_id: str = Query(..., description="催办挂在哪个厂区的收件箱"),
    apply: bool = Query(False, description="false=只出判定不动库；true 才真的挂/刷新/关闭"),
    include_data: bool = Query(False, description="true 时连数据缺口（台账世代/缺供应商）一起巡检"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """引擎的故障由引擎自己报，不等人去翻 /engine-layers。

    判据不另立一套：直接取分层验收 L1 那两条（心跳超过 2 个预期间隔没跳、窗口崩溃率 >1%），
    所以待办上写的数和验收页那格永远是同一个数。一条 (循环, 故障种类) 只留一条未关闭催办，
    签名没变不动库；台账恢复后自动关闭并写明恢复。一次性任务跑完退出不算故障。
    """
    del current_user
    from api.services.engine_watchdog import scan, scan_data

    out = await scan(db, factory_id, apply=apply)
    if include_data:
        out["data"] = await scan_data(db, factory_id, apply=apply)
    return out


@router.get("/engine-contract", summary="引擎对外契约：三个接口的签名与业务词表（与模型内部无关）")
async def get_engine_contract(current_user: User = Depends(get_current_user)):
    """agent 与前端只该看这一份：能问什么、每个业务输入的单位与范围、信封的不变量。

    设计约束是「接口稳定、实现隐藏」：模型内部的参数名、节点/工位标识不出现在这一层，
    引擎内部换算法、加层、重排都不用动调用方；反过来调用方也不许拿内部名当参数传。
    """
    del current_user
    from api.services.engine_contract import spec

    return spec()


@router.post("/engine-simulate", summary="契约 simulate：这些条件下几号能交、延几天、卡在哪一项")
async def post_engine_simulate(
    body: Dict[str, Any] = Body(..., description="factory_id, models?, n_models?, scope?, conditions?, inputs?"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user
    return await _engine_contract_call("simulate", db, str(body.get("factory_id") or ""), body)


@router.post("/engine-sensitivity", summary="契约 sensitivity：哪个业务输入最能动结果、值几天，答案可信到几成")
async def post_engine_sensitivity(
    body: Dict[str, Any] = Body(..., description="factory_id + 可选 models/scope/conditions"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user
    return await _engine_contract_call("sensitivity", db, str(body.get("factory_id") or ""), body)


@router.post("/engine-attribution", summary="契约 attribution：为什么是这个答案；给了 compare 就归因变更")
async def post_engine_attribution(
    body: Dict[str, Any] = Body(..., description="factory_id + inputs? + compare{baseline,alternative}?"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user
    return await _engine_contract_call("attribution", db, str(body.get("factory_id") or ""), body)


@router.get("/engine-contract-check", summary="契约自检：泄漏内部标识数 / 信封违规数 / 内部名被拒率")
async def get_engine_contract_check(
    factory_id: str = Query(..., description="厂区"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """接口是不是真的与模型无关，看三个数：内部名当键出现的次数、信封缺单位/依据的次数、
    把内部 kwarg 名当参数传进来被结构化拒绝的比例。这三条破了就说明接口和实现黏住了。
    """
    del current_user
    from api.services.engine_contract import self_check

    return await self_check(db, factory_id)


@router.post("/virtual-run", summary="沙箱执行推演：引擎自己拆单/借路线/开采购/按天推进")
async def post_virtual_run(
    body: Dict[str, Any] = Body(..., description="factory_id, targets:[{model_code,units,due_in_days}], "
                                                "attendance_rate?, expedite_lead_days?"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """给目标（机种+数量+交期），引擎在沙箱里把它跑成一条时间线：借同族路线、按线节拍补工时、
    现料够就先开一批、缺的料按 lead_time_days 开采购、按天推进出勤与产能，最后出货期、用工、钱、瓶颈件。

    只在内存里执行，不写业务表、不回写真实系统；每一步动作都留在 actions 里可核对。
    `attendance_rate` 给一条恒定到岗率（好天 0.97 / 雨 0.92 / 暴雨 0.70），
    `expedite_lead_days` 回答"把瓶颈件压到 N 天能提前几天交"。
    `line_staffing` 是 {线编码: 到岗比例}，回答"某条线整班请假/减半到岗会怎样"：
    比例 0 → 这台单改派到工艺上同样能做的线（结果里 `staffing.rerouted_from` 记从哪条挪走），
    没有可改派的线 → `status:"no_staffed_line"`，只给等待结论、不编完工日；
    0 到 1 之间 → 按人数折算这条线的班组，产能受"班组按 IE 工时做得完的台/天"约束。
    """
    del current_user
    from api.services.virtual_run import run_sandbox

    factory_id = str(body.get("factory_id") or "")
    targets = body.get("targets") or []
    if not factory_id or not targets:
        raise HTTPException(status_code=422, detail="需要 factory_id 和 targets[{model_code,units,due_in_days}]")
    rate = body.get("attendance_rate")
    curve = None if rate is None else {d: float(rate) for d in range(0, 400)}
    staffing = body.get("line_staffing")
    if staffing is not None and not isinstance(staffing, dict):
        raise HTTPException(status_code=422, detail='line_staffing 要传对象，例如 {"LINE-TREAD-01": 0.5}')
    return await run_sandbox(db, factory_id, targets,
                             attendance_curve=curve,
                             line_staffing=staffing,
                             expedite_lead_days=(int(body["expedite_lead_days"])
                                                 if body.get("expedite_lead_days") else None))


@router.get("/portfolio-flywheel", summary="跑一轮组合推演并记记分卡（默认只算不写）")
async def get_portfolio_flywheel(
    factory_id: str = Query(..., description="厂区"),
    apply: bool = Query(False, description="false=只算不写卡不发待办"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """引擎每 15 分钟自己会跑这一圈；这个端点用于当下看一轮的结果与它会写什么。

    写的是 `simulation_scorecards`（我方推演读数）和一条瓶颈待办，不动任何事实表。
    去重规则：同一天同瓶颈且分数没实质变化就不写第二张卡；同一瓶颈只留一条未关闭待办。
    """
    del current_user
    from api.services.portfolio_flywheel import run_once

    return await run_once(db, factory_id, apply=apply)


@router.post("/portfolio-sim", summary="机种组合推演（只读）：货期 · 人力利用 · 评分 · 杠杆")
async def post_portfolio_sim(
    body: Dict[str, Any] = Body(..., description="factory_id, models?, n?, units?, due_in_days?, levers?"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按现有线参数 / HR / 设备 / 库存 / 工艺路线，把 N 个机种排队上线，推出交货日期与人力利用，并打分。

    评分口径（权重随结果一起返回）：准点交付 40%、人力利用 25%、齐套 20%、设备可用 10%、依据完整 5%。
    算不出货期的单给 0 分而不是给个平均分 —— 没有依据的日期不是"乐观"，是没用。
    `levers` 会给出"改掉哪类瓶颈能涨几分"，并可用 levers 参数（extra_line / crew_bonus）在同一次调用里
    做前后对比，这就是要的飞轮：先量瓶颈，再逐条试改动，看得分怎么动。
    """
    del current_user
    from api.services.attendance_model import attendance_factor
    from api.services.portfolio_sim import simulate

    factory_id = str(body.get("factory_id") or "")
    if not factory_id:
        raise HTTPException(status_code=422, detail="缺少 factory_id")
    n = int(body.get("n") or 5)
    units = int(body.get("units") or 300)
    due_in_days = int(body.get("due_in_days") or 25)
    models = body.get("models")
    attend = (await attendance_factor(db, factory_id)).get("factor")

    base = await simulate(db, factory_id, models=models, n=n, units_default=units,
                          demand_date=date.today(), attendance_factor=attend)
    out: Dict[str, Any] = {"base": base, "attendance_factor_used": attend}
    want = body.get("levers") or {}
    if want.get("extra_line"):
        trial = await simulate(db, factory_id, models=models, n=n, units_default=units,
                               demand_date=date.today(), attendance_factor=attend, extra_line=True)
        out["lever_extra_line"] = {"portfolio_score": trial["portfolio_score"],
                                   "delta": round(trial["portfolio_score"] - base["portfolio_score"], 1),
                                   "orders": trial["orders"]}
    if want.get("crew_bonus"):
        trial = await simulate(db, factory_id, models=models, n=n, units_default=units,
                               demand_date=date.today(), attendance_factor=attend,
                               crew_bonus=float(want["crew_bonus"]))
        out["lever_crew_bonus"] = {"portfolio_score": trial["portfolio_score"],
                                   "delta": round(trial["portfolio_score"] - base["portfolio_score"], 1),
                                   "orders": trial["orders"]}
    if want.get("clear_storm"):
        trial = await simulate(db, factory_id, models=models, n=n, units_default=units,
                               demand_date=date.today(), attendance_factor=1.0)
        out["lever_full_attendance"] = {"portfolio_score": trial["portfolio_score"],
                                        "delta": round(trial["portfolio_score"] - base["portfolio_score"], 1)}
    if want.get("ie_hours_per_unit"):
        # 补上单件工时（按线节拍标定）会怎样：这是检验"卡住分数的是数据还是资源"的那一刀
        trial = await simulate(db, factory_id, models=models, n=n, units_default=units,
                               demand_date=date.today(), attendance_factor=attend,
                               ie_hours_per_unit=float(want["ie_hours_per_unit"]))
        out["lever_ie_hours"] = {"portfolio_score": trial["portfolio_score"],
                                 "delta": round(trial["portfolio_score"] - base["portfolio_score"], 1),
                                 "orders": [{"model_code": o["model_code"], "score": o["score"],
                                             "finish": o["estimated_finish"],
                                             "basis": o["time_basis"],
                                             "production_days": o["production_days"]}
                                            for o in trial["orders"]]}
    return out


@router.get("/data-authority", summary="仿真输入的数据源台账（只读）")
async def get_data_authority(
    factory_id: str = Query(..., description="厂区"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """每一维仿真输入只认一个权威出处：IE 工时、HR 人力、考勤、设备状况、生效排产、物料齐套。

    用户 10-06 定的口径：**IE 数据 + HR 人力数据为准**，口述的线产能降为参考；
    仿真由"今天多少人出勤 · 设备状况 · 排产计划 · 物料齐套"共同维持。
    所以这里逐维报：表里有多少行、今天有没有值、是不是我们自己灌的种子数据。

    三条"不能当证据"的读数也是这接口给的：工位每小时产能（单位没人定义过）、
    物料批量提前期（3 万行只有 11 个不同值）、虚拟工厂自写报工（1,005/1,017 行）。
    """
    del current_user
    return await data_authority_report(db, factory_id)


@router.get("/partial-kit", summary="部分齐投产机会（只读：还能先开几台）")
async def get_partial_kit(
    factory_id: str = Query(..., description="厂区"),
    min_units: int = Query(1, description="至少能先开几台才报，默认 1"),
    limit: int = Query(20, description="最多报几张单"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """一张单被一种料压住时，别的料可能已经够先开一批 —— 这里按台账算出台数。

    口径：能开几台 = 各领料行 (可用量 ÷ 单件用量) 取最小，封顶在"这张单还欠几台"。
    单件用量取 领料行毛需求 ÷ 计划台数；主档 qty_per_unit 只有 49/4110 行有值，
    不做主依据，但对不上的行数和单数会一起报出来（per_unit_conflicts）。

    只读：引擎不改 planned_qty、不自动拆单 —— 拆多少要看车间临时腾不腾得出人力和工位。
    """
    del current_user
    return await partial_kit_opportunities(db, factory_id, min_units=min_units, limit=limit)


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


@router.get("/time-basis", summary="预计工时的出处与产能对撞（只读）")
async def get_time_basis(
    factory_id: str = Query(..., description="厂区"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """每道工序的单件时长是从哪儿来的：工步声明 / 线产能 / 工位产能，还是根本没有依据。

    为什么单独开这一格：路线 JSON 里 430 个工步 0 个带工时，排程就落到
    "0 秒/件 + 300 秒换型"的兜底上，账面 1,180 台的单像 5 分钟做完。
    现在只认厂里声明过的产能，并把自己打自己：同一机种"线报一天 300 台"和
    "工位主档每小时 4 件"对不上时，两个数一起报给 IE 核定，引擎不取平均。

    预计完工按流水线口径（数量 ÷ 线产能 + 首件节拍），不等于排程任务行求和 ——
    排程器按一单一工位串行放置，那是批次假设。
    """
    del current_user
    return await time_basis_audit(db, factory_id)


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
