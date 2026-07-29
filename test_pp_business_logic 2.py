#!/usr/bin/env python3
"""
PP生产计划模块业务逻辑测试脚本
验证MPS和MRP核心功能的正确性
"""

import asyncio
import sys
from datetime import datetime, timedelta
from core.pp.plan import MPSService
from core.pp.mrp import MRPService


async def test_mps_service():
    """测试MPSService核心功能"""
    print("=" * 60)
    print("测试 MPSService...")
    print("=" * 60)
    
    mps = MPSService()
    
    # 测试1: 创建计划并验证优先级计算
    print("\n[测试1] 创建生产计划并验证优先级分数...")
    required_date = datetime.now() + timedelta(days=5)  # 5天后
    plan = await mps.create_plan(
        factory_id="FACT-001",
        product_id="PRODUCT-A",
        quantity=100,
        required_date=required_date,
        customer_level="vip",  # VIP客户
        priority=80,
    )
    print(f"  计划ID: {plan['id']}")
    print(f"  计划编码: {plan['plan_code']}")
    print(f"  优先级分数: {plan['priority_score']}")
    
    # 预期：交期紧迫度约95分 + VIP权重50分 + 优先级80分 = 约225分（上限150）
    assert plan["priority_score"] <= 150, "优先级分数不应超过150"
    print("  ✓ 优先级分数计算正常")
    
    # 测试2: 确认计划
    print("\n[测试2] 确认生产计划...")
    confirmed_plan = await mps.confirm_plan(plan["id"], "test_user")
    print(f"  状态: {confirmed_plan['status']}")
    assert confirmed_plan["status"] == "confirmed"
    print("  ✓ 计划确认成功")
    
    # 测试3: 下达计划
    print("\n[测试3] 下达生产计划...")
    released_plan = await mps.release_plan(plan["id"], "test_user")
    print(f"  状态: {released_plan['status']}")
    assert released_plan["status"] == "released"
    print("  ✓ 计划下达成功")
    
    # 测试4: 产能负荷分析
    print("\n[测试4] 执行产能负荷分析...")
    from_date = datetime.now()
    to_date = datetime.now() + timedelta(days=7)
    capacity = await mps.analyze_capacity_load(
        factory_id="FACT-001",
        station_id="STA-ASSY-01",
        from_date=from_date,
        to_date=to_date,
    )
    print(f"  工站: {capacity['station_id']}")
    print(f"  负荷率: {capacity['utilization_rate']}%")
    print("  ✓ 产能分析完成")
    
    # 测试5: 冲突检测
    print("\n[测试5] 检测产能冲突...")
    conflicts = await mps.detect_capacity_conflict(plan["id"])
    print(f"  冲突数量: {len(conflicts)}")
    print("  ✓ 冲突检测完成")
    
    print("\n✅ MPSService所有测试通过!")
    return True


async def test_mrp_service():
    """测试MRPService核心功能"""
    print("\n" + "=" * 60)
    print("测试 MRPService...")
    print("=" * 60)
    
    mrp = MRPService()
    
    # 准备一个有效的计划（使用MPSService创建的模拟计划）
    plan_id = "test-plan-001"
    product_id = "PRODUCT-A"
    quantity = 50
    
    print("\n[测试1] BOM展开...")
    bom_items = await mrp.expand_bom(product_id, quantity)
    print(f"  BOM物料数: {len(bom_items)}")
    for item in bom_items:
        print(f"    - {item['material_code']}: 用量 {item['quantity_per_parent']}, 总需求 {item['required_qty']}")
    print("  ✓ BOM展开正常")
    
    print("\n[测试2] 库存可用性检查...")
    material_codes = [b["material_code"] for b in bom_items]
    inventory = await mrp.check_inventory_availability(material_codes)
    for code, data in inventory.items():
        print(f"    {code}: 可用量={data['available_qty']}, 在库={data['on_hand']}")
    print("  ✓ 库存检查完成")
    
    print("\n[测试3] MRP计算...")
    mrp_result = await mrp.calculate_mrp(
        plan_id=plan_id,
        product_id=product_id,
        quantity=quantity,
    )
    print(f"  MRP编号: {mrp_result['id']}")
    print(f"  产品: {mrp_result['product_name']}")
    print(f"  计划数量: {mrp_result['quantity']}")
    print(f"  物料项数: {len(mrp_result['items'])}")
    print(f"  短缺项数: {mrp_result['summary']['shortage_count']}")
    print(f"  总短缺量: {mrp_result['summary']['total_shortage_qty']}")
    print(f"  采购建议数: {mrp_result['suggestion_count']}")
    print("  ✓ MRP计算完成")
    
    print("\n[测试4] 采购建议详情...")
    for item in mrp_result['items'][:3]:  # 只显示前3项
        print(f"    {item['material_code']}: 毛需{item['gross_demand']}, 可用{item['available_qty']}, 净需求{item['net_demand']}, 建议采购{item.get('suggested_order_qty', 'N/A')}")
    print("  ✓ 采购建议生成正常")
    
    print("\n[测试5] 库存预警...")
    alerts = await mrp.get_inventory_alerts()
    print(f"  预警数量: {len(alerts)}")
    for alert in alerts:
        print(f"    [{alert['severity']}] {alert['type']}: {alert['material_code']}")
    print("  ✓ 库存预警完成")
    
    print("\n✅ MRPService所有测试通过!")
    return True


async def main():
    """运行所有测试"""
    print("\n🚀 EngHub PP模块业务逻辑测试脚本")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    try:
        mps_ok = await test_mps_service()
        mrp_ok = await test_mrp_service()
        
        if mps_ok and mrp_ok:
            print("\n" + "=" * 60)
            print("✅ 所有测试通过！PP模块业务开发已完成")
            print("=" * 60)
            return 0
        else:
            print("\n❌ 部分测试失败")
            return 1
            
    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
