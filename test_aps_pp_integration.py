#!/usr/bin/env python3
"""
PP与APS业务集成测试（改进版）
验证计划创建→MRP计算→APS排程的完整业务流
修正了原测试中不存在的方法调用问题
"""

import asyncio
import sys
from datetime import datetime, timedelta
from core.pp.plan import MPSService
from core.pp.mrp import MRPService
from api.services.aps_service import ApsService
from database.db_config import db_config


async def test_pp_aps_integration():
    """端到端的业务流测试"""
    print("=" * 70)
    print("🧪 PP + APS 业务集成测试（改进版）")
    print("=" * 70)
    
    # 1. 初始化服务
    mps = MPSService()
    mrp = MRPService()
    
    # 获取数据库会话工厂
    from database.db_config import db_config
    session_factory = db_config.session_factory  # property 返回 async_sessionmaker
    async with session_factory() as session:
        aps_service = ApsService(session)
    
    try:
        # ========================
        # 步骤1: 创建MPS计划（生产计划员操作）
        # ========================
        print("\n[步骤1] 创建主生产计划(MPS)...")
        required_date = datetime.now() + timedelta(days=10)
        
        plan = await mps.create_plan(
            factory_id="FACT-001",
            product_id="PRODUCT-A",
            quantity=100,
            required_date=required_date,
            customer_level="vip",
            priority=80,
        )
        print(f"  → 计划ID: {plan['id']}")
        print(f"  → 计划编码: {plan['plan_code']}")
        print(f"  → 数量: {plan['quantity']}台")
        print(f"  → 优先级分: {plan['priority_score']}")
        print(f"  ✓ MPS计划创建完成")
        assert plan['status'] == 'draft'
        
        # ========================
        # 步骤2: 确认计划（审核流程）
        # ========================
        print("\n[步骤2] 确认生产计划...")
        confirmed_plan = await mps.confirm_plan(plan["id"], "production_manager")
        assert confirmed_plan["status"] == "confirmed"
        print(f"  → 状态已转为: {confirmed_plan['status']}")
        print(f"  ✓ 计划已确认")
        
        # ========================
        # 步骤3: MR物料需求运算（计划员手动/自动触发）
        # ========================
        print("\n[步骤3] 执行MRP物料需求计算...")
        mrp_result = await mrp.calculate_mrp(
            plan_id=plan["id"],
            product_id=plan["product_id"],
            quantity=plan["quantity"],
        )
        print(f"  → MRP编号: {mrp_result.get('id', 'N/A')}")
        print(f"  → BOM展开物料数: {mrp_result.get('bom_expanded_count', 0)}")
        print(f"  → 短缺项数: {mrp_result['summary']['shortage_count']}")
        print(f"  ✓ MRP计算完成")
        
        # ========================
        # 步骤4: 下达计划并生成MES工单
        # ========================
        print("\n[步骤4] 下达生产计划...")
        released_plan = await mps.release_plan(plan["id"], "production_manager")
        print(f"  → 计划状态: {released_plan['status']}")
        print(f"  → 生成工单ID: {released_plan.get('work_order_id', 'N/A')}")
        assert released_plan['status'] == 'released'
        print(f"  ✓ 计划已下达")
        
        # ========================
        # 步骤5: 触发APS排程
        # ========================
        print("\n[步骤5] 触发APS排程...")
        from core.pp.aps_integration import PPAPSLinker
        linker = PPAPSLinker(session)
        aps_result = await linker.trigger_aps_after_mrp(
            plan_id=plan["id"],
            horizon_days=7,
            optimize_for="delivery",
            auto_confirm=False,
            notify_user="system",
        )
        print(f"  → APS结果: {aps_result}")
        print(f"  ✓ APS排程触发完成")
        
        # ========================
        # 验证结果
        # ========================
        print("\n" + "=" * 70)
        print("✅ 业务集成测试通过！")
        print("=" * 70)
        print(f"链路验证: MPS创建(✓) → 确认(✓) → MRP计算(✓) → 下达(✓) → APS触发(✓)")
        return True
        
    except Exception as e:
        print(f"\n❌ 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    # 会话由 async with 自动管理，无需手动关闭


async def main():
    """运行集成测试"""
    print("\n⏳ 启动PP+APS业务集成测试...")
    success = await test_pp_aps_integration()
    
    if success:
        print("\n" + "=" * 70)
        print("🎉 恭喜！PP与APS业务集成验证成功！")
        print("=" * 70)
        return 0
    else:
        print("\n❌ 集成测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))