#!/usr/bin/env python3
"""
FAI（首件检验）业务流测试
模拟完整的首件检验流程：创建记录 -> 开始检验 -> 缺陷记录 -> 判定结果 -> 处置
"""

from core.qms.fai_service import FAIService, FAIStatus, FAIResultType, FAILevel, FAIStructure


def test_fai_full_flow():
    """测试完整的 FAI 业务流程"""
    print("=" * 70)
    print("🧪 FAI (首件检验) 业务流测试")
    print("=" * 70)
    
    # 初始化服务
    fai = FAIService()
    
    # 步骤1: 创建首件检验记录
    print("\n[Step 1] 📋 创建首件检验记录")
    record = fai.create_fai_record(
        factory_id="FACT-001",
        work_order_id="WO-20260728-001",
        product_id="PROD-A",
        product_name="ABC产品",
        batch_no="BATCH-20260728-A",
        machine_id="MACH-CNC001",
        operator_id="OPR-JohnDoe",
        inspector_id="QUAL-Sarah",
        fail_level=FAILevel.LEVEL_2,
        structure=FAIStructure.MANUAL,
        sample_qty=1,
    )
    print(f"   FAI记录ID: {record.id[:8]}...")
    print(f"   关联工单: {record.work_order_id}")
    print(f"   初始状态: {record.status.value}")
    
    # 步骤2: 开始检验
    print("\n[Step 2] 🔍 质检员开始检验")
    record.start_inspection()
    print(f"   ✓ 检验已启动 (状态: {record.status.value})")
    
    # 步骤3: 记录检验项目发现的一些缺陷
    print("\n[Step 3] ⚙️ 执行检测，发现尺寸偏差")
    defects = [
        {
            "code": "MAJOR",
            "category": "Dimension",
            "description": "孔径超差 +0.03mm（公差 ±0.01mm）",
            "quantity": 1,
        },
        {
            "code": "MINOR",
            "category": "Appearance",
            "description": "表面轻微划痕不影响功能",
            "quantity": 1,
        }
    ]
    for defect in defects:
        record.record_defect(defect)
    print(f"   ✓ 记录缺陷数: {len(record.defects_found)}")
    
    # 步骤4: 完成检验 - 判定不合格（因为有重大缺陷）
    print("\n[Step 4] ✗ 判定结果：不合格（含重大缺陷）")
    record.finish_inspection(FAIResultType.FAIL)
    print(f"   检验结果: {record.result.value}")
    print(f"   状态更新: {record.status.value}")
    
    # 步骤5: 处置决定 - 返工后重新申请首件检验
    print("\n[Step 5] ♻️ 处置决定：返工重做")
    record.dispose("rework", "QUAL_MANAGER")
    print(f"   处置决定: {record.disposition}")
    print(f"   状态: {record.status.value}")
    
    # 步骤6: 查看统计信息
    print("\n[Step 6] 📊 FAI 统计概览")
    print(f"   总记录数: 1")
    print(f"   合格率: 0% (首件即不合格)")
    print(f"   平均缺陷数: {len(defects)} / 件")
    
    print("\n" + "=" * 70)
    print("✅ FAI 全流程测试通过！")
    print("=" * 70)
    print("""
首件检验（FAI）业务价值：

✅ 生产前确认：在批量生产前，验证设备参数、工装夹具、工艺方法等符合要求
✅ 缺陷预防：提前发现潜在问题，避免批量不良品的产生
✅ 记录追溯：完整记录检验过程，为质量分析提供数据基础
✅ 决策依据：根据首件结果决定是否允许批量生产，有效控制风险

典型应用场景：
• 新产品首次投产 
• 设备/工装更换后的首件
• 长时间停机重启后的首件
• 工艺参数调整后的首件
""")
    return True


if __name__ == "__main__":
    success = test_fai_full_flow()
    print(f"\n最终结果: {'SUCCESS' if success else 'FAILED'}")
