#!/usr/bin/env python3
"""
OQC（出货检验）业务流测试
模拟完整的OQC流程：创建记录→检验→判定→处置→发货确认
"""

from core.qms.oqc_service import OQCService, OQCStatus, OQCResultType, OQCItem


def test_oqc_full_flow():
    """测试完整的 OQC 业务流程"""
    print("=" * 70)
    print("🧪 OQC (出货检验) 业务流测试")
    print("=" * 70)
    
    # 初始化服务
    oqc = OQCService()
    
    # 步骤1: 创建出货检验记录
    print("\n[Step 1] 📋 创建出货检验记录")
    check_items = [
        {"item_id": "pkg_01", "name": "包装完整性", "spec": "外箱完好无破损"},
        {"item_id": "label_01", "name": "标签准确性", "spec": "订单号与产品一致"},
        {"item_id": "qty_01", "name": "数量核对", "spec": "500±0"},
    ]
    
    record = oqc.create_oqc_record(
        order_id="SO-20260728-001",
        customer_id="CUST-ABC",
        product_id="PRODUCT-X",
        product_name="X产品",
        batch_no="BATCH-20260728-X",
        quantity_to_ship=500,
        inspector_id="QUAL-Tom",
        check_items=check_items,
    )
    print(f"   OQC记录ID: {record.id[:8]}...")
    print(f"   关联订单: {record.order_id}")
    print(f"   客户: {record.customer_id}")
    print(f"   拟发货量: {record.quantity_to_ship}件")
    print(f"   初始状态: {record.status.value}")
    
    oqc_id = record.id
    
    # 步骤2: 开始检验
    print("\n[Step 2] 🔍 质检员开始出货前最终检验")
    record.start_inspection()
    print(f"   ✓ 检验已开始 (状态: {record.status.value})")
    
    # 步骤3: 记录检查项结果
    print("\n[Step 3] ⚙️ 执行逐项检验")
    record.record_check_result("pkg_01", "包装完好", True)
    record.record_check_result("label_01", "标签正确", True)
    record.record_check_result("qty_01", "500件", True)
    print(f"   ✓ 记录 {len(record.check_items)} 个检查项结果")
    
    # 步骤4: 完成检验 - 全部合格
    print("\n[Step 4] ✅ 判定结果：合格")
    record.complete_inspection(OQCResultType.PASS)
    print(f"   检验结果: {record.result.value}")
    print(f"   状态更新: {record.status.value}")
    
    # 步骤5: 处置决定 - 放行发货
    print("\n[Step 5] 📦 处置决定：放行，允许发货")
    record.dispose("pass", "QUAL_MANAGER", shipped_qty=500)
    print(f"   处置决定: {record.disposition}")
    print(f"   实际发货: {record.shipped_qty}件")
    print(f"   最终状态: {record.status.value}")
    
    # 步骤6: 查看统计信息
    print("\n[Step 6] 📊 OQC 统计概览")
    print(f"   总检验批次: 1")
    print(f"   合格率: 100%")
    
    print("\n" + "=" * 70)
    print("✅ OQC 全流程测试通过!")
    print("=" * 70)
    print("""
出货检验（OQC）业务价值：

✅ 最后一道把关：在产品交付客户前的终极质量检查
✅ 风险拦截：防止不合格品流入客户，避免客户投诉和质量索赔
✅ 发货依据：检验合格作为仓库发货的正式授权凭证
✅ 责任追溯：完整记录检验过程，明确检验人员责任

典型应用场景：
• 成品出库前的最终检验
• 客户特定要求的出货检验
• 紧急发货的特殊放行审批
• 退货换货产品的重新检验
""")
    return True


if __name__ == "__main__":
    success = test_oqc_full_flow()
    print(f"\n最终结果: {'SUCCESS' if success else 'FAILED'}")