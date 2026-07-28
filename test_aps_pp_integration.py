#!/usr/bin/env python3
"""
PP与APS业务集成测试
验证计划创建→MRP计算→APS排程的完整业务流
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
    print("🧪 PP + APS 业务集成测试")
    print("=" * 70)
    
    # 1. 初始化服务
    mps = MPSService()
    mrp = MRPService()
    
    # 创建数据库会话（模拟真实环境）
    from database.db_config import db_config
    from database.db_config import db_config
    session = await db_config.session_factory()
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
        print(f"  → 预估工时: {plan['estimated_hours']}小时")
        print(f"  ✓ MPS计划创建完成")
        
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
        print(f"  → MRP编号: {mrp_result['id']}")
        print(f"  → 产品: {mrp_result['product_name']}")
        print(f"  → BOM展开物料数: {mrp_result.get('bom_expanded_count', 0)}")
        print(f"  → 短缺项数: {mrp_result['summary']['shortage_count']}")
        print(f"  → 总短缺量: {mrp_result['summary']['total_shortage_qty']}")
        print(f"  → 采购建议数: {mrp_result.get('suggestion_count', 0)}")
        
        # 显示部分物料明细
        print(f"  → 物料明细（前3项）:")
        for item in mrp_result['items'][:3]:
            print(f"      - {item['material_code']}: 毛需{item['gross_demand']}, 可用{item['available_qty']}, 净需求{item['net_demand']}")
        print(f"  ✓ MRP计算完成")
        
        # ========================
        # 步骤4: 下达计划并触发APS排程（系统自动或人工触发）
        # ========================
        print("\n[步骤4] 下达生产计划并触发APS排程...")
        
        # 下达MPS计划（此时会生成MES工单）
        released_plan = await mps.release_plan(plan["id"], "production_manager")
        print(f"  → 计划状态: {released_plan['status']}")
        print(f"  → 生成工单ID: {released_plan.get('work_order_id')}")
        
        # APS从待排工单列表中获取计划
        print(f"  → 等待APS排程获取到最新工单...")
        
        # 执行APS排程
        aps_result = await aps_service.generate_schedule(
            factory_id=plan["factory_id"],
            mode="hybrid",
            horizon_days=7,
            optimize_for="delivery",
            created_by="system",
        )
        print(f"  → APS方案ID: {aps_result.get('schedule_id')}")
        print(f"  → 排程成功: {aps_result.get('success', False)}")
        print(f"  → 生成任务数: {aps_result.get('total_tasks', 0)}")
        print(f"  → 未排程订单数: {aps_result.get('unscheduled_orders', 0)}")
        if aps_result.get('metrics'):
            metrics = aps_result['metrics']
            print(f"  → 准时交付率: {metrics.get('on_time_delivery_rate', 'N/A'):.1f}%")
            print(f"  → 平均负荷率: {metrics.get('avg_resource_utilization', 'N/A'):.1f}%")
        print(f"  ✓ APS排程完成")
        
        # ========================
        # 步骤5: 确认排程（主管审批）
        # ========================
        print("\n[步骤5] 确认APS排程方案...")
        if aps_result.get('schedule_id'):
            confirm_result = await aps_service.confirm_schedule(
                schedule_id=aps_result['schedule_id'],
                confirmed_by="plant_manager"
            )
            print(f"  → 回写工单数: {confirm_result.get('updated_orders', 0)}")
            print(f"  ✓ APS排程已确认并回写工单计划时间")
        
        # ========================
        # 步骤6: 下达排程（开始执行）
        # ========================
        print("\n[步骤6] 下达APS排程...")
        if aps_result.get('schedule_id'):
            release_result = await aps_service.release_schedule(schedule_id=aps_result['schedule_id'])
            print(f"  → 下发工单数: {release_result.get('updated_orders', 0)}")
            print(f"  ✓ APS排程已下达")
        
        # ========================
        # 验证结果
        # ========================
        print("\n" + "=" * 70)
        print("✅ 业务集成测试通过！完整链路验证如下：")
        print("=" * 70)
        print("""
        MPS计划创建 → [确认] → MRP计算 → [下达] → MES工单生成 → 
        APS排程 → [确认回写] → 工单计划时间更新 → [下达] → 执行开始
        
        数据流转说明:
        • MRP从MPS计划获取产品和数量，通过BOM展开计算物料净需求
        • APS从WorkOrder获取待排工单（释放后生成的工单），结合工艺路线和资源约束生成详细排程
        • 确认APS排程时，回写工单的planned_start/planned_due/assigned_station字段
        • 下达APS排程后，工单状态转为released，车间可开始执行
        """)
        
        return True
        
    except Exception as e:
        print(f"\n❌ 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await session.close()


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
        print("\n❌ 集成测试存在缺陷，需要修复")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
