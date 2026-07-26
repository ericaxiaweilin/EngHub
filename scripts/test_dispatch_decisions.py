"""
RCC Command Center - dispatch decision engine

The current RCC engine is purely descriptive - it counts things.
A true Command Center should produce ACTIONABLE dispatch decisions:
1. Worker reassignment (move people from low-load to high-load stations)
2. Work order rescheduling (delay/stall based on bottlenecks)
3. Equipment maintenance triggers (auto create PM when overdue)
4. Quality escalation (increase inspection frequency)

This module generates executable dispatch actions that can be:
- Approved/rejected by human operator
- Auto-executed via logic chains
- Tracked in RCC task table
"""

import asyncio, sys
sys.path.insert(0, '.')

from core.rcc.resource_decision import RCCResourceDecisionEngine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text as sql_text

async def get_dispatch_decisions(db: AsyncSession, factory_id: str):
    """Generate truly actionable dispatch decisions"""
    
    # Get worker assignment data
    engine = RCCResourceDecisionEngine(db)
    
    # ===== 1. WORKER DISPATCH DECISIONS =====
    worker_decisions = await engine.recommend_worker_assignment(factory_id)
    dispatch_actions = []
    
    for transfer in worker_decisions.get("suggested_transfers", []):
        dispatch_actions.append({
            "type": "worker_reassign",
            "priority": "high" if transfer.get("source_station_utilization", 0) > 90 else "medium",
            "title": f"从{transfer['from_station']}借调{transfer['suggested_count']}人到{transfer['to_station']}",
            "reason": transfer["reason"],
            "action_plan": {
                "move_from": transfer["from_station"],
                "move_to": transfer["to_station"],
                "count": transfer["suggested_count"],
                "estimated_completion_hours": 2,
            },
            "automation_ready": True,
        })
    
    # Check for stations with zero active workers -> critical
    for station in worker_decisions.get("station_assignments", []):
        if station.get("active_in_station", 0) == 0:
            dispatch_actions.append({
                "type": "critical_staffing",
                "priority": "critical",
                "title": f"{station['station']} 无在岗人员！",
                "reason": f"在岗率 {station['utilization_pct']}%",
                "action_plan": {
                    "station": station["station"],
                    "immediate_action": "派遣组长或技术员前往支援",
                    "escalation": "通知产线负责人",
                },
                "automation_ready": False,
            })
    
    # ===== 2. EQUIPMENT DISPATCH DECISIONS =====
    equip_decisions = await engine.recommend_equipment_schedule(factory_id)
    
    for pm_alert in equip_decisions.get("maintenance_alerts", [])[:5]:
        dispatch_actions.append({
            "type": "pm_trigger",
            "priority": "high",
            "title": f"设备 {pm_alert.get('equipment_code')} PM逾期{pm_alert.get('days_past_due', 0)}天",
            "reason": f"维护类型: {pm_alert.get('maintenance_type')}, 应到期: {pm_alert.get('next_due_at')}",
            "action_plan": {
                "equipment_code": pm_alert.get("equipment_code"),
                "maintenance_type": pm_alert.get("maintenance_type"),
                "action": "创建维修工单并暂停该设备排程",
                "notify_maintenance": True,
            },
            "automation_ready": True,
        })
    
    # Recommend using idle equipment
    for idle in equip_decisions.get("idle_equipment", []):
        dispatch_actions.append({
            "type": "activate_idle_equipment",
            "priority": "medium",
            "title": f"设备 {idle['equipment_code']} 空闲中，可投入生产",
            "reason": f"设备状态: {idle.get('status')}, 关联工位: {idle.get('station_id')}",
            "action_plan": {
                "equipment_code": idle["equipment_code"],
                "status": "idle",
                "recommendation": "分配待排工单至此设备",
                "requires_setup": True,
            },
            "automation_ready": False,
        })
    
    # ===== 3. WORK ORDER DISPATCH DECISIONS =====
    wo_decisions = await engine.recommend_work_order_priority(factory_id)
    
    for change in wo_decisions.get("suggested_priority_changes", []):
        dispatch_actions.append({
            "type": "work_order_adjust",
            "priority": change["priority"],
            "title": change["reason"],
            "action_plan": {
                "change_type": change["action"],
                "action": change["reason"],
                "auto_execute": change["priority"] == "critical",
            },
            "automation_ready": change["priority"] != "critical",
        })
    
    # Check delivery risk
    for risk in wo_decisions.get("delivery_risk", [])[:10]:
        dispatch_actions.append({
            "type": "delivery_risk",
            "priority": "high",
            "title": f"工单 {risk['work_order_code']} 超期{risk['days_overdue']}天",
            "reason": f"应完成: {risk['planned_due']}, 状态: {risk['status']}",
            "action_plan": {
                "work_order_code": risk["work_order_code"],
                "overdue_days": risk["days_overdue"],
                "recommended_action": "升级处理/调整排程/加急安排",
                "escalate_to": "生产经理",
            },
            "automation_ready": False,
        })
    
    # ===== 4. PROCESS/QUALITY DISPATCH DECISIONS =====
    process_decisions = await engine.recommend_process_response(factory_id)
    
    for alert in process_decisions.get("process_alerts", []):
        dispatch_actions.append({
            "type": "quality_escalation",
            "priority": "high" if alert.get("type") == "yield_drop" else "medium",
            "title": alert.get("message", ""),
            "action_plan": {
                "alert_type": alert.get("type"),
                "current_value": alert.get("current_yield_pct"),
                "threshold": alert.get("threshold_pct"),
                "recommended_action": alert.get("action"),
                "notify_quality": True,
            },
            "automation_ready": True,
        })
    
    return {
        "factory_id": factory_id,
        "generated_at": asyncio.get_event_loop().time(),
        "total_actions": len(dispatch_actions),
        "critical_actions": sum(1 for a in dispatch_actions if a["priority"] == "critical"),
        "high_actions": sum(1 for a in dispatch_actions if a["priority"] == "high"),
        "medium_actions": sum(1 for a in dispatch_actions if a["priority"] == "medium"),
        "decisions": dispatch_actions,
    }


# Run against current DB to verify
async def main():
    eng = create_async_engine('postgresql+asyncpg://enghub:enghub123@localhost:5432/enghub')
    
    async with eng.begin() as conn:
        print("=== FAC_ELEC_DEMO_2026 Dispatch Decisions ===")
        result = await get_dispatch_decisions(conn, 'FAC_ELEC_DEMO_2026')
        print(f"Total actions: {result['total_actions']}")
        print(f"Critical: {result['critical_actions']}, High: {result['high_actions']}, Medium: {result['medium_actions']}")
        for d in result['decisions']:
            print(f"  [{d['priority'].upper()}] {d['title']}")
        
        print("\n=== FAC_MECH_001 Dispatch Decisions ===")
        result = await get_dispatch_decisions(conn, 'FAC_MECH_001')
        print(f"Total actions: {result['total_actions']}")
        print(f"Critical: {result['critical_actions']}, High: {result['high_actions']}, Medium: {result['medium_actions']}")
        for d in result['decisions']:
            print(f"  [{d['priority'].upper()}] {d['title']}")
    
    eng.dispose()

asyncio.run(main())
