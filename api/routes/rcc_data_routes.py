"""
v2.6 - RCC Data Layer API Routes
RCC = Resource Control Center — 全局统筹人/物/工单计算

综合数据层接口：
- GET /rcc/data → 按传入或默认工厂ID返回真实基线+决策
- GET /rcc/data?mode=global → 聚合所有工厂数据（RCCDashboard默认模式）
- GET /rcc/data?factory_id=xxx → 单工厂详细视图
"""

from fastapi import APIRouter, HTTPException, Query, Body, Depends
from typing import Optional, Dict, Any

router = APIRouter(prefix="/api/v1/rcc", tags=["rcc"])


@router.get("/data", summary="综合数据层接口")
async def get_rcc_data(
    factory_id: Optional[str] = Query(None, description="工厂ID"),
    mode: str = Query("single", description="single|global"),
):
    """
    综合数据层接口：从上游业务模块直接汇总人/设备/工单/环境/工艺真实基线、
    实时产能、瓶颈预警和调度建议，供 RCCDashboard 展示。
    
    - mode=single + factory_id=指定 → 查询该工厂详细基线
    - mode=global → 聚合所有工厂数据，适合 RCC 全局视角
    - factory_id=None + mode=single（默认）→ 尝试从上下文获取默认工厂
    """
    from database.db_config import get_db
    
    db_generator = get_db()
    db = await db_generator.__anext__()
    try:
        # 1. 全量计算引擎
        from core.rcc.calculator import RCCResourceCalculator
        calc = RCCResourceCalculator(db)
        
        # 2. 资源决策引擎
        from core.rcc.resource_decision import RCCResourceDecisionEngine
        engine = RCCResourceDecisionEngine(db)
        
        # 3. 可调参数 + 逻辑链汇总
        from sqlalchemy import text as sql_text
        
        # 获取所有工厂列表
        factories_result = await db.execute(sql_text(
            "SELECT DISTINCT factory_id FROM hr_employees WHERE factory_id IS NOT NULL"
        ))
        all_factories = [r[0] for r in factories_result if r[0]]
        
        if mode == "global":
            # 全局聚合模式：遍历所有工厂，汇总人/设备/工单
            merged_people = {"active_workers": 0, "attendance_rate_pct": 0, "alerts": [], 
                           "headcount": {}, "skill_distribution": {}}
            merged_equipment = {"total": 0, "status_distribution": {}, "pm_overdue_count": 0}
            merged_work_orders = {"status": {}, "urgent_count": 0, "delivery_risk_count": 0}
            merged_environment = {"has_data": False, "warnings": [], "alert": False}
            merged_process = {"yield_baseline_30d": None, "routing_count": 0, "top_defects": []}
            
            for fid in all_factories:
                fb = await calc.full_baseline_sync(fid)
                fbl = fb.get("baseline", {})
                
                p = fbl.get("people", {})
                merged_people["active_workers"] += p.get("active_workers", 0)
                merged_people["headcount"].update(p.get("headcount", {}))
                if p.get("skills"):
                    for k, v in p["skills"].items():
                        merged_people["skill_distribution"][k] = merged_people["skill_distribution"].get(k, 0) + v
                merged_people["alerts"].extend(p.get("alerts", []))
                
                e = fbl.get("equipment", {})
                merged_equipment["total"] += e.get("total", 0)
                for k, v in e.get("statuses", {}).items():
                    merged_equipment["status_distribution"][k] = merged_equipment["status_distribution"].get(k, 0) + v
                
                w = fbl.get("work_orders", {})
                for k, v in w.get("status", {}).items():
                    merged_work_orders["status"][k] = merged_work_orders["status"].get(k, 0) + v
                merged_work_orders["urgent_count"] += w.get("urgent_count", 0)
                merged_work_orders["delivery_risk_count"] += w.get("delivery_risk_count", 0)
                
                env = fbl.get("environment", {})
                if env.get("has_data"):
                    merged_environment["has_data"] = True
                merged_environment["warnings"].extend(env.get("warnings", []))
                if env.get("alert"):
                    merged_environment["alert"] = True
            
            baseline = {
                "people": merged_people,
                "equipment": merged_equipment,
                "work_orders": merged_work_orders,
                "environment": merged_environment,
                "process": merged_process,
            }
            
            decisions = {"global_mode": True, "factories_aggregated": all_factories}
        else:
            # 单工厂模式
            effective_factory_id = factory_id or (all_factories[0] if all_factories else None)
            if not effective_factory_id:
                return {
                    "success": False,
                    "message": "没有可用的工厂数据",
                    "baseline": {},
                    "decisions": {}
                }
            
            baseline = await calc.full_baseline_sync(effective_factory_id)
            decisions = await engine.full_resource_decision(effective_factory_id)
        
        # 4. 可调参数 + 逻辑链汇总
        params_result = await db.execute(sql_text(
            "SELECT COUNT(*)::int AS total, "
            "COUNT(*) FILTER (WHERE sensitivity='high')::int AS high_sensitive "
            "FROM global_adjustable_params"
        ))
        param_summary = dict(params_result.mappings().first()) or {}
        
        chains_result = await db.execute(sql_text(
            "SELECT COUNT(*)::int AS total, "
            "COUNT(*) FILTER (WHERE enabled=true)::int AS enabled_count "
            "FROM deterministic_logic_chains"
        ))
        chain_summary = dict(chains_result.mappings().first()) or {}
        
        return {
            "success": True,
            "mode": mode,
            "factory_id": effective_factory_id if mode == "single" else None,
            "generated_at": baseline.get("synced_at") if isinstance(baseline, dict) else None,
            "params_summary": param_summary,
            "chains_summary": chain_summary,
            "baseline": baseline.get("baseline", baseline) if isinstance(baseline, dict) else baseline,
            "decisions": decisions,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        if hasattr(db_generator, 'aclose'):
            await db_generator.aclose()


@router.get("/baseline", summary="RCC全量基线概览")
async def get_full_baseline(factory_id: str = Query(..., description="工厂ID")):
    """全量RCC基线，汇总人/设备/工单/环境/工艺五维数据"""
    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db
    from sqlalchemy.ext.asyncio import AsyncSession
    
    db: AsyncSession = await get_db().__anext__()
    try:
        calc = RCCResourceCalculator(db)
        result = await calc.full_baseline_sync(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/baseline/people", summary="人力基线明细")
async def get_people_baseline(factory_id: str = Query(...)):
    """人力资源基线：编制、在岗率、技能分布、负荷预警"""
    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db
    from sqlalchemy.ext.asyncio import AsyncSession
    
    db: AsyncSession = await get_db().__anext__()
    try:
        calc = RCCResourceCalculator(db)
        result = await calc.people_baseline(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/baseline/equipment", summary="设备基线明细")
async def get_equipment_baseline(factory_id: str = Query(...)):
    """设备产能基线：状态、OEE目标、PM逾期、利用率"""
    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db
    from sqlalchemy.ext.asyncio import AsyncSession
    
    db: AsyncSession = await get_db().__anext__()
    try:
        calc = RCCResourceCalculator(db)
        result = await calc.equipment_baseline(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/baseline/work_orders", summary="工单统筹基线")
async def get_work_order_baseline(factory_id: str = Query(...)):
    """工单统筹：状态分布、急单比例、交期风险、齐套率、APS状态"""
    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db
    from sqlalchemy.ext.asyncio import AsyncSession
    
    db: AsyncSession = await get_db().__anext__()
    try:
        calc = RCCResourceCalculator(db)
        result = await calc.work_order_baseline(factory_id)
        return {"success": True, "data": result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/baseline/process", summary="工艺基线明细")
async def get_process_baseline(factory_id: str = Query(...)):
    """工艺基线：节拍时间、良品率基线、AQL级别、质量目标对标"""
    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db
    from sqlalchemy.ext.asyncio import AsyncSession
    
    db: AsyncSession = await get_db().__anext__()
    try:
        calc = RCCResourceCalculator(db)
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
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from database.models import Notification
    import uuid
    
    engine = create_async_engine("postgresql+asyncpg://enghub:enghub123@localhost:5432/enghub")
    async with engine.begin() as conn:
        calc = RCCResourceCalculator(conn)
        try:
            result = await calc.full_baseline_sync(factory_id)
            
            # 写入Notification作为计算完成通知
            modules_str = ", ".join(payload.get('modules', ['全部']))
            n = Notification(
                id=str(uuid.uuid4()),
                factory_id=factory_id,
                recipient=None,
                category="system",
                title="RCC统筹基线已更新",
                content=f"工厂{factory_id}的RCC基线已重新计算，涉及模块: {modules_str}",
                severity="info",
                source_type="rcc_baseline",
                is_read=False,
                created_at=__import__('datetime').datetime.utcnow(),
            )
            conn.add(n)
            await conn.commit()
            
            return {"success": True, "data": result}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    
    await engine.dispose()


@router.post("/sync-baseline", summary="同步DB数据到RCC基线")
async def sync_baseline(payload: Dict[str, Any] = Body(default={})):
    """
    强制同步：将当前所有真实DB数据重新汇总到RCC基线。
    适用于批量数据变更后刷新基线。
    """
    factory_id = payload.get("factory_id", "FAC_MECH_001")

    from core.rcc.calculator import RCCResourceCalculator
    from database.db_config import get_db
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    
    engine = create_async_engine("postgresql+asyncpg://enghub:enghub123@localhost:5432/enghub")
    async with engine.begin() as conn:
        calc = RCCResourceCalculator(conn)
        try:
            result = await calc.full_baseline_sync(factory_id)
            return {"success": True, "data": result}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    
    await engine.dispose()
