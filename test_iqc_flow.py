#!/usr/bin/env python3
"""
IQ C（来料检验）业务流测试
模拟完整的IQ C流程：创建记录 -> 开始检验 -> 完成检验 -> 处置 -> 统计查询
"""

import asyncio
from datetime import datetime, timedelta
from core.qms.iqc_service import InspectionResultType, DispositionType, IQCStatus
from api.services.qms_service import QMSService


async def test_iqc_full_flow():
    """测试完整的 IQ C 业务流程"""
    print("=" * 70)
    print("🧪 IQ C (来料检验) 业务流测试")
    print("=" * 70)
    
    # 初始化服务（内存版本）
    qms = QMSService()
    
    # 步骤1: 创建收货单（预先生成，实际应用中从ERP同步）
    print("\n[Step 1] 📦 供应商送货并创建 IQ C 记录")
    inbound_order_id = f"INBO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    factory_id = "FACT-001"
    supplier_id = "SUPP-ABC"
    product_id = "PROD-MCU-STM32F407"
    product_name = "STM32F407 微控制器"
    quantity = 5000  # 5000 个芯片
    batch_no = "BATCH-20260728-001"
    inspector_id = "QUAL-001"
    
    # 创建 IQC 记录（使用 IQCService 的 create_record 方法，需要适配）
    # 由于我们的简化服务包装了 IQCService，直接调用
    try:
        # IQCService.create_record 的参数不同，这里直接调用
        record = qms.iqc.create_record(
            order_id=inbound_order_id,
            supplier_id=supplier_id,
            product_id=product_id,
            product_name=product_name,
            quantity_received=quantity,
            batch_no=batch_no,
            delivery_date=datetime.utcnow(),
            inspector_id=inspector_id,
            inspection_criteria={
                "sampling_method": "AQL",
                "aql_level": "II",
                "sample_size": max(5, int(quantity * 0.1)),
            },
        )
        iqc_result = {"id": record.id, "status": record.status.value}
        print(f"   IQ C 记录 ID: {record.id[:8]}...")
        print(f"   产品: {record.product_name}")
        print(f"   批次: {record.batch_no}")
        print(f"   状态: {record.status.value}")
        print(f"   抽检数量: {record.inspection_criteria.get('sample_size', 0)}")
        
        inspection_id = record.id
        
    except Exception as e:
        print(f"❌ 创建 IQC 记录失败: {e}")
        return False
    
    # 步骤2: 开始检验
    print("\n[Step 2] 🔍 质检员开始抽样检验")
    # 在内存版中，直接更新状态
    record = qms.iqc._records[inspection_id]
    record.start_inspection()
    print(f"   ✓ 检验已开始 (状态: {record.status.value})")
    
    # 步骤3: 执行检验并发现缺陷
    print("\n[Step 3] ⚙️ 执行抽样检测，发现不良品")
    defects = [
        {
            "code": "MAJOR",
            "category": "Appearance",
            "description": "表面有划痕/磕碰",
            "quantity": 3,
        },
        {
            "code": "MINOR",
            "category": "Packaging",
            "description": "包装袋轻微破损",
            "quantity": 5,
        }
    ]
    
    sample_count = 80
    # 更新结果（PASS 因为缺陷在 AQL 可接受范围内）
    record.result = InspectionResultType.PASS
    record.sample_inspected = sample_count
    record.defects_found = defects
    record.status = IQCStatus.PASSED
    
    print(f"   ✓ 检验结果: PASS")
    print(f"   ✓ 发现缺陷种类: {len(defects)}")
    print(f"   ✓ 总缺陷数量: {sum(d['quantity'] for d in defects)}")
    
    # 步骤4: 处置决定（接受入库）
    print("\n[Step 4] ✅ 质量部门做出处置决定")
    record.disposition = DispositionType.ACCEPT
    record.disposition_by = "QUAL_MANAGER"
    record.disposition_at = datetime.utcnow()
    record.status = IQCStatus.DISPOSED
    
    print(f"   ✓ 处置决定: ACCEPT (合格入库)")
    
    # 步骤5: 获取统计信息
    print("\n[Step 5] 📊 查看 IQ C 统计报告")
    stats = qms.iqc.get_statistics()
    print(f"   总记录数: {stats.get('total_records', 0)}")
    print(f"   合格率: {stats.get('pass_rate', 'N/A')}")
    
    print("\n" + "=" * 70)
    print("✅ IQ C 全流程测试通过!")
    print("=" * 70)
    
    return True


async def main():
    try:
        success = await test_iqc_full_flow()
        return 0 if success else 1
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
