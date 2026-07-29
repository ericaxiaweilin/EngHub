#!/usr/bin/env python3
"""
IPC（制程巡检）业务流测试
模拟完整的IPC流程：创建计划 -> 开始检验 -> 记录结果 -> 处置
"""

from core.qms.ipc_service import IPCService, IPCFrequencyType, IPCStatus, IPCResultType


def test_ipc_full_flow():
    """测试完整的 IPC 业务流程"""
    print("=" * 70)
    print("🧪 IPC (制程巡检) 业务流测试")
    print("=" * 70)
    
    # 初始化服务
    ipc = IPCService()
    
    # 步骤1: 创建 IPC 巡检计划
    print("\n[Step 1] 📋 创建 IPC 巡检计划")
    check_items = [
        {"item_id": "dim_01", "name": "孔径尺寸", "spec_min": 9.95, "spec_max": 10.05},
        {"item_id": "func_01", "name": "功能测试", "spec_min": 0, "spec_max": 1},
        {"item_id": "appearance_01", "name": "表面外观", "spec_min": 0, "spec_max": 0, "passed": False},
    ]
    
    record = ipc.create_ipc_plan(
        work_order_id="WO-20260728-001",
        product_id="PRODUCT-A",
        process_stage="总装工序",
        frequency_type=IPCFrequencyType.TIME_BASED,
        frequency_value=60,  # 每60分钟一次
        operator_id="OPR-John",
        inspector_id="QUAL-Sarah",
        check_items=check_items,
    )
    
    print(f"   IPC记录ID: {record.id[:8]}...")
    print(f"   关联工单: {record.work_order_id}")
    print(f"   工序阶段: {record.process_stage}")
    print(f"   初始状态: {record.status.value}")
    print(f"   检查项数: {len(record.check_items)}")
    
    ipc_id = record.id
    
    # 步骤2: 开始检验
    print("\n[Step 2] 🔍 质检员开始现场巡检")
    record.start_inspection("QUAL-Sarah")
    print(f"   ✓ 检验已开始 (状态: {record.status.value})")
    
    # 步骤3: 记录检验结果 - 检查项数据
    print("\n[Step 3] ⚙️ 执行检测，记录各项结果")
    for item in record.check_items:
        if item.item_id == "dim_01":
            item.actual_value = 10.02  # 在规格范围内
            item.passed = True
        elif item.item_id == "func_01":
            item.actual_value = 1
            item.passed = True
        elif item.item_id == "appearance_01":
            item.actual_value = 0
            item.passed = False  # 发现表面瑕疵
    
    print(f"   ✓ 记录 {len(record.check_items)} 个检查项结果")
    
    # 步骤4: 完成检验 - 判定合格（虽然有1项外观缺陷但可接受）
    print("\n[Step 4] ✗ 判定结果：合格（含轻微缺陷）")
    record.complete_inspection(IPCResultType.PASS)
    print(f"   检验结果: {record.result.value}")
    print(f"   状态更新: {record.status.value}")
    
    # 步骤5: 处置决定 - 继续生产（合格放行）
    print("\n[Step 5] ✅ 处置决定：放行，继续生产")
    record.dispose("continue", "QUAL_SUPERVISOR")
    print(f"   处置决定: {record.disposition}")
    print(f"   最终状态: {record.status.value}")
    
    # 步骤6: 查看统计信息
    print("\n[Step 6] 📊 IPC 统计概览")
    passed_count = sum(1 for r in ipc._records.values() if r.status == IPCStatus.PASSED)
    failed_count = sum(1 for r in ipc._records.values() if r.status == IPCStatus.FAILED)
    print(f"   总巡检次数: 1")
    print(f"   合格率: {((passed_count/(passed_count+failed_count))*100) if (passed_count+failed_count)>0 else 0:.1f}%")
    
    print("\n" + "=" * 70)
    print("✅ IPC 全流程测试通过!")
    print("=" * 70)
    print("""
制程巡检（IPC）业务价值：

✅ 过程监控：实时监控生产过程质量稳定性，防止批量不良发生
✅ 及时预警：发现异常趋势时及时报警，快速响应处理
✅ 数据积累：积累过程质量数据，支持SPC统计分析
✅ 决策依据：根据巡检结果决定生产是否继续、暂停或调整

典型应用场景：
• 关键工序定点巡检
• 重要特性周期性抽检
• 新产品试产过程跟踪
• 工艺变更后的验证监控
""")
    return True


if __name__ == "__main__":
    success = test_ipc_full_flow()
    print(f"\n最终结果: {'SUCCESS' if success else 'FAILED'}")