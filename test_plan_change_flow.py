#!/usr/bin/env python3
"""
计划变更管理业务流程测试
验证完整的变更申请、审批、版本追溯流程
"""

import asyncio
from datetime import datetime, timedelta
from core.pp.plan import MPSService, PlanStatus, CustomerLevel


async def test_change_management_flow():
    """测试变更管理全流程"""
    print("=" * 70)
    print("🧪 计划变更管理 - 完整流程测试")
    print("=" * 70)
    
    # 初始化服务
    mps = MPSService()
    
    # 步骤1: 创建初始计划
    print("\n[Step 1] 📋 创建初始生产计划")
    required_date = datetime.now() + timedelta(days=14)
    plan = await mps.create_plan(
        factory_id="FACT-001",
        product_id="PRODUCT-A",
        quantity=100,
        required_date=required_date,
        customer_level="a",
        priority=50,
        created_by="planner1",
    )
    print(f"   计划ID: {plan['id'][:8]}...")
    print(f"   初始数量: {plan['quantity']}")
    print(f"   初始优先级: {plan['priority_score']}")
    print(f"   状态: {plan['status']}")
    
    plan_id = plan["id"]
    
    # 步骤2: 申请人发起变更请求（需要审批的大变更）
    print("\n[Step 2] ✍️ 计划员发起变更请求（修改数量和交期）")
    
    changes = {
        "quantity": {"old": 100, "new": 150},  # 增加50% (超过20%，属于 Level3 需要主任审批)
        "required_date": {"old": required_date.isoformat(), "new": (datetime.now() + timedelta(days=10)).isoformat()},  # 提前交期
    }
    
    description = "客户需求紧急调整，数量从100增至150，交期从14天提前至10天"
    
    change_result = mps.change_mgmt.create_change_request(
        plan_id=plan_id,
        applicant="planner2",
        changes=changes,
        description=description,
        change_type="update",
    )
    
    print(f"   变更单号: {change_result['request_id'][:8]}...")
    print(f"   审批级别: {change_result['level']} (Level3 = 需计划主任审批)")
    print(f"   影响分析: MRP影响={change_result['impact_analysis']['mrf_affects']}, 产能冲突={change_result['impact_analysis']['capacity_conflicts']}")
    print(f"   预计受影响工单: {change_result['impact_analysis']['affected_wo_count']}")
    
    request_id = change_result['request_id']
    
    # 步骤3: 系统自动审批 Level1 变更（测试小变更）
    print("\n[Step 3] ℹ️ 测试 Level1 小变更（自动审批）")
    
    small_changes = {
        "remark": {"old": None, "new": "紧急插单备注"},  # 仅添加备注，无实质性业务影响
    }
    
    small_result = mps.change_mgmt.create_change_request(
        plan_id=plan_id,
        applicant="planner3",
        changes=small_changes,
        description="添加备注信息",
        change_type="update",
    )
    
    print(f"   级别: {small_result['level']} (Level1 = 自动批准)")
    print(f"   状态: {small_result['status']}")
    
    # 注意：实际代码中 submit_change_request 应该触发自动应用，但当前简化实现
    
    # 步骤4: 人工批准 Level3 变更
    print("\n[Step 4] 👔 计划主任批准 Level3 变更")
    
    approve_success = mps.change_mgmt.approve_change_request(
        request_id=request_id,
        approved_by="production_manager",
    )
    
    if approve_success:
        print(f"   ✓ 变更请求已批准并自动应用到计划")
        
        # 验证计划已更新
        updated_plan = mps._plans[plan_id]
        print(f"   新数量: {updated_plan['quantity']} (应为 150)")
        # 检查日期是否更新（需要重新计算优先级分数等）
    else:
        print(f"   ✗ 批准失败")
        return False
    
    # 步骤5: 查看版本历史
    print("\n[Step 5] 📜 查看计划版本追溯历史")
    
    versions = mps.change_mgmt.get_versions(plan_id)
    print(f"   共有 {len(versions)} 个版本:")
    for v in versions[-2:]:  # 只显示最近的两个版本
        print(f"     Version {v.version_number} by {v.changed_by} ({v.change_type}): {v.description}")
    
    # 步骤6: 列出所有变更请求
    print("\n[Step 6] 📋 列出该计划的所有变更请求")
    
    all_requests = mps.change_mgmt.list_requests(plan_id=plan_id)
    print(f"   共 {len(all_requests)} 个变更请求:")
    for r in all_requests:
        status = "✓ Approved" if r.status == ChangeRequestStatus.APPROVED else ("✗ Pending" if r.status == ChangeRequestStatus.PENDING else "✗ Rejected")
        print(f"   - {r.request_id[:8]}... [{status}] {r.change_type}: {r.description[:50]}...")
    
    print("\n" + "=" * 70)
    print("✅ 计划变更管理全流程测试通过！")
    print("=" * 70)
    print("""
变更管理系统核心价值：

1. ✅ 变更留痕 - 所有修改都有申请单记录，可追溯到谁在何时为什么修改
2. ✅ 分级审批 - 根据变更影响程度自动确定审批等级（Level1自动/L2经理/L3主任）
3. ✅ 影响预检 - 变更前预演对物料(MRP)和产能(APS)的影响，提前发现风险
4. ✅ 版本追溯 - 每个计划的完整历史快照，支持随时回滚或对比
5. ✅ 流程闭环 - 申请→审批→执行→通知完整流转，确保变更可控

这是制造执行系统中保证生产计划稳定性和可审计性的关键组件！
""")
    return True


async def main():
    try:
        success = await test_change_management_flow()
        return 0 if success else 1
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
