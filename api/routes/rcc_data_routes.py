"""
v2.6 - RCC Data Layer API Routes
RCC = Resource Control Center — 全局统筹人/物/工单计算
不是UI面板，而是给上游系统（SchedulingAgent, WarehouseAgent, AlertIntelligence）提供数据基线。

新增端点：
- GET /rcc/baseline → 全量RCC基线概览
- GET /rcc/baseline/people → 人力基线
- GET /rcc/baseline/equipment → 设备基线
- GET /rcc/baseline/work_orders → 工单统筹基线
- GET /rcc/baseline/process → 工艺基线
- POST /rcc/calculate → 触发统筹计算并返回完整基线
- POST /rcc/sync-baseline → 同步最新DB数据到RCC基线
"""

from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional, Dict, Any

router = APIRouter(prefix="/api/v1/rcc", tags=["rcc"])


@router.get("/baseline", summary="RCC全量基线概览")
async def get_full_baseline(factory_id: str = Query(..., description="工厂ID")):
    """全量RCC基线，汇总人/设备/工单/环境/工艺五维数据"""
    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db

    db = next(get_db())
    calc = RCCResourceCalculator(db)
    try:
        result = await calc.full_baseline_sync(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/baseline/people", summary="人力基线明细")
async def get_people_baseline(factory_id: str = Query(...)):
    """人力资源基线：编制、在岗率、技能分布、负荷预警"""
    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db

    db = next(get_db())
    calc = RCCResourceCalculator(db)
    try:
        result = await calc.people_baseline(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/baseline/equipment", summary="设备基线明细")
async def get_equipment_baseline(factory_id: str = Query(...)):
    """设备产能基线：状态、OEE目标、PM逾期、利用率"""
    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db

    db = next(get_db())
    calc = RCCResourceCalculator(db)
    try:
        result = await calc.equipment_baseline(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/baseline/work_orders", summary="工单统筹基线")
async def get_work_order_baseline(factory_id: str = Query(...)):
    """工单统筹：状态分布、急单比例、交期风险、齐套率、APS状态"""
    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db

    db = next(get_db())
    calc = RCCResourceCalculator(db)
    try:
        result = await calc.work_order_baseline(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/baseline/process", summary="工艺基线明细")
async def get_process_baseline(factory_id: str = Query(...)):
    """工艺基线：节拍时间、良品率基线、AQL级别、质量目标对标"""
    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db

    db = next(get_db())
    calc = RCCResourceCalculator(db)
    try:
        result = await calc.process_baseline(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/calculate", summary="触发RCC统筹计算")
async def trigger_calculation(payload: Dict[str, Any] = Body(default={})):
    """
    触发全量RCC统筹计算。
    payload可选：
    {
        "factory_id": "FAC_MECH_001",     // 必填或从token获取
        "modules": ["people","equipment","work_orders","environment","process"],
        "force_sync": true                 // true则先同步再计算
    }
    """
    factory_id = payload.get("factory_id", "FAC_MECH_001")

    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db

    db = next(get_db())
    calc = RCCResourceCalculator(db)
    try:
        if payload.get("force_sync"):
            result = await calc.full_baseline_sync(factory_id)
        else:
            result = await calc.full_baseline_sync(factory_id)
        # 也写入Notification作为计算完成通知
        from database.models import Notification as NotificationModel
        import uuid
        n = NotificationModel(
            id=str(uuid.uuid4()),
            factory_id=factory_id,
            recipient=None,
            category="system",
            title="RCC统筹基线已更新",
            content=f"工厂{factory_id}的RCC基线已重新计算，涉及模块: {', '.join(payload.get('modules', ['全部']))}",
            severity="info",
            source_type="rcc_baseline",
            is_read=False,
            created_at=__import__('datetime').datetime.utcnow(),
        )
        db.add(n)
        await db.commit()
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/sync-baseline", summary="同步DB数据到RCC基线")
async def sync_baseline(payload: Dict[str, Any] = Body(default={})):
    """
    强制同步：将当前所有真实DB数据重新汇总到RCC基线。
    适用于批量数据变更后刷新基线。
    """
    factory_id = payload.get("factory_id", "FAC_MECH_001")

    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db

    db = next(get_db())
    calc = RCCResourceCalculator(db)
    try:
        result = await calc.full_baseline_sync(factory_id)
        # 记录参数调整审计为同步操作
        from sqlalchemy import text as sql_text
        await db.execute(sql_text("""
            INSERT INTO parameter_change_audit (id, param_id, from_value, to_value, changed_by, changed_at, reason, approval_status, source)
            SELECT gen_random_uuid(), id, current_value, current_value, 'rcc_sync'::varchar(50), NOW(), :reason::text, 'auto_approved'::varchar(20), 'rcc_base_sync'::varchar(20)
            FROM global_adjustable_params g
            WHERE g.factory_id = :fid AND EXISTS (
                SELECT 1 FROM global_adjustable_params p WHERE p.param_code = 'rcc_last_sync_version' AND p.factory_id = :fid
            )
        """), {"fid": factory_id, "reason": f"RCC基线同步于{__import__('datetime').datetime.utcnow().isoformat()}"})
        await db.commit()
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
