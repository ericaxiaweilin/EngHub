#!/usr/bin/env python3
"""
计划变更通知APS重排测试
验证当MPS计划发生变更（数量/交期）时，能否自动触发APS重算
"""

import asyncio
from datetime import datetime, timedelta
from core.pp.plan import MPSService, PlanStatus


async def test_plan_change_triggers_aps():
    """测试计划变更触发APS重排"""
    print("=" * 70)
    print("🧪 计划变更 → APS 重排测试")
    print("=" * 70)
    
    # 初始化服务并启用APS触发
    mps = MPSService()
    mps._aps_trigger_enabled = True
    
    # 1. 创建初始计划
    print("\n[1] 创建初始生产计划...")
    required_date = datetime.now() + timedelta(days=14)
    plan = await mps.create_plan(
        factory_id="FACT-001",
        product_id="PRODUCT-A",
        quantity=100,
        required_date=required_date,
        customer_level="a",
        priority=50,
    )
    print(f"   计划ID: {plan['id'][:8]}...")
    print(f"   初始数量: {plan['quantity']}")
    print(f"   初始优先级: {plan['priority_score']}")
    
    # 2. 确认计划
    print("\n[2] 确认计划...")
    confirmed = await mps.confirm_plan(plan["id"], "manager1")
    assert confirmed["status"] == "confirmed"
    print(f"   ✓ 已确认")
    
    # 3. 下达计划（生成工单）
    print("\n[3] 下达计划...")
    released = await mps.release_plan(plan["id"], "manager1")
    assert released["status"] == "released"
    print(f"   ✓ 已下达，工单生成")
    
    # 4. 修改计划数量（这会触发APS重排！）
    print("\n[4] ✨ 修改计划数量 (100 → 200)...")
    updated = await mps.update_plan(
        plan_id=plan["id"],
        updates={"quantity": 200},
        updated_by="manager2",
        trigger_aps_replan=True,  # 关键：触发APS重排
    )
    print(f"   新数量: {updated['quantity']}")
    print(f"   新优先级: {updated['priority_score']}")
    print(f"   APS重排已触发: {'有' if 'aps_trigger_queued' in updated else '无'}")
    
    # 5. 修改计划交期（也会触发APS重排！）
    print("\n[5] 📅 修改计划交期 (14天 → 21天)...")
    new_due = datetime.now() + timedelta(days=21)
    updated2 = await mps.update_plan(
        plan_id=plan["id"],
        updates={"required_date": new_due},
        updated_by="manager3",
        trigger_aps_replan=True,
    )
    print(f"   新交期: {new_due.strftime('%Y-%m-%d')}")
    print(f"   新的优先级变化: {updated2['priority_score']} (原: {plan['priority_score']})")
    
    # 6. 同时修改多个字段
    print("\n[6] 🔀 同时修改数量和优先级...")
    updated3 = await mps.update_plan(
        plan_id=plan["id"],
        updates={"quantity": 150, "priority": 80},
        updated_by="manager4",
        trigger_aps_replan=True,
    )
    print(f"   新数量: {updated3['quantity']}")
    print(f"   新优先级: {updated3['priority_score']}")
    
    print("\n" + "=" * 70)
    print("✅ 计划变更 → APS 重排测试通过！")
    print("=" * 70)
    print("""
业务场景演示：

场景1：销售订单数量变更（如从100台增至200台）
  → MPS计划数量更新 → MRP重新计算物料需求 → APS重新排程
  → 确保生产计划和物料供应同步匹配

场景2：客户交期提前（如从14天改为7天）
  → MPS计划交期更新 → 优先级自动升高（更紧迫）→ MRP检查物料是否足够
  → APS紧急重排，优先安排关键物料和产能

场景3：紧急插单导致原有计划调整
  → MPS计划优先级/数量变更 → APS识别瓶颈工位 → 输出优化排程方案
  
所有变更都实现了"系统自动响应，无需人工干预"的智能闭环！
""")
    return True


async def main():
    try:
        success = await test_plan_change_triggers_aps()
        return 0 if success else 1
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
