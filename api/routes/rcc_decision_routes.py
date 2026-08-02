"""
v2.6 - RCC Resource Decision API Routes
RCC = Resource Control Center — 资源决策API

新增端点：
- GET /rcc/decision/people-assignment → 人力分配建议
- GET /rcc/decision/equipment-schedule → 设备调度建议
- GET /rcc/decision/work-order-priority → 工单优先级建议
- GET /rcc/decision/bottleneck-resolution → 瓶颈解决方案
- GET /rcc/decision/environment-response → 环境异常响应
- GET /rcc/decision/process-response → 工艺异常响应
- GET /rcc/decision/full → 全量资源决策报告

这些API基于RCC基线数据，给系统/Chatbot提供可执行决策建议。
"""

from fastapi import APIRouter, HTTPException, Query, Body, Depends
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/rcc/decision", tags=["rcc-decision"])


@router.get("/people-assignment", summary="人力分配建议")
async def get_worker_assignment_decision(factory_id: str = Query(...)):
    """人力分配决策：按工位缺勤率排序，推荐人员调配方案"""
    from core.rcc.resource_decision import RCCResourceDecisionEngine
    from database.db_config import get_db

    db_generator = get_db()
    db: AsyncSession = await db_generator.__anext__()
    try:
        engine = RCCResourceDecisionEngine(db)
        result = await engine.recommend_worker_assignment(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if hasattr(db_generator, 'aclose'):
            await db_generator.aclose()


@router.get("/equipment-schedule", summary="设备调度建议")
async def get_equipment_schedule_decision(factory_id: str = Query(...)):
    """设备调度决策：空闲设备分配、PM逾期预警、影响评估"""
    from core.rcc.resource_decision import RCCResourceDecisionEngine
    from database.db_config import get_db

    db_generator = get_db()
    db: AsyncSession = await db_generator.__anext__()
    try:
        engine = RCCResourceDecisionEngine(db)
        result = await engine.recommend_equipment_schedule(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if hasattr(db_generator, 'aclose'):
            await db_generator.aclose()


@router.get("/work-order-priority", summary="工单优先级建议")
async def get_work_order_priority_decision(factory_id: str = Query(...)):
    """工单优先级决策：交期紧迫度+产能约束，生成排序和插单建议"""
    from core.rcc.resource_decision import RCCResourceDecisionEngine
    from database.db_config import get_db

    db_generator = get_db()
    db: AsyncSession = await db_generator.__anext__()
    try:
        engine = RCCResourceDecisionEngine(db)
        result = await engine.recommend_work_order_priority(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if hasattr(db_generator, 'aclose'):
            await db_generator.aclose()


@router.get("/bottleneck-resolution", summary="产能瓶颈解决方案")
async def get_bottleneck_resolution_decision(factory_id: str = Query(...)):
    """产能瓶颈决策：识别高负载工位，推荐平衡方案"""
    from core.rcc.resource_decision import RCCResourceDecisionEngine
    from database.db_config import get_db

    db_generator = get_db()
    db: AsyncSession = await db_generator.__anext__()
    try:
        engine = RCCResourceDecisionEngine(db)
        result = await engine.recommend_bottleneck_resolution(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if hasattr(db_generator, 'aclose'):
            await db_generator.aclose()


@router.get("/environment-response", summary="环境异常响应建议")
async def get_environment_response_decision(factory_id: str = Query(...)):
    """环境异常决策：温湿度/粉尘/噪声超标时的响应建议"""
    from core.rcc.resource_decision import RCCResourceDecisionEngine
    from database.db_config import get_db

    db_generator = get_db()
    db: AsyncSession = await db_generator.__anext__()
    try:
        engine = RCCResourceDecisionEngine(db)
        result = await engine.recommend_environment_response(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if hasattr(db_generator, 'aclose'):
            await db_generator.aclose()


@router.get("/process-response", summary="工艺异常响应建议")
async def get_process_response_decision(factory_id: str = Query(...)):
    """工艺异常决策：良品率下降/节拍超标时的响应建议"""
    from core.rcc.resource_decision import RCCResourceDecisionEngine
    from database.db_config import get_db

    db_generator = get_db()
    db: AsyncSession = await db_generator.__anext__()
    try:
        engine = RCCResourceDecisionEngine(db)
        result = await engine.recommend_process_response(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if hasattr(db_generator, 'aclose'):
            await db_generator.aclose()


@router.get("/full", summary="全量资源决策报告")
async def get_full_resource_decision(factory_id: str = Query(...)):
    """全量资源决策：综合人/设备/工单/环境/工艺所有决策"""
    from core.rcc.resource_decision import RCCResourceDecisionEngine
    from database.db_config import get_db

    db_generator = get_db()
    db: AsyncSession = await db_generator.__anext__()
    try:
        engine = RCCResourceDecisionEngine(db)
        result = await engine.full_resource_decision(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if hasattr(db_generator, 'aclose'):
            await db_generator.aclose()
