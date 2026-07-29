#!/usr/bin/env python3
"""
Kanban看板业务流测试 - 拉动式生产管理的核心流程验证

完整的看板循环流程：创建池→创建卡片→下发接收→加工完成→回收（形成闭环）
"""

from core.ie.kanban_service import KanbanService, KanbanType, KanbanStatus


def test_kanban_full_cycle():
    """测试完整看板生命周期（循环闭合）"""
    print("=" * 70)
    print("🧪 Kanban 看板全流程测试")
    print("=" * 70)
    
    # 初始化服务
    kanban = KanbanService()
    
    print("\n[Step 1] 📋 创建看板池（定义源站→目标站的拉动物料流）")
    pool_id = "POOL-ASSY-TO_PACK"
    pool = kanban.create_kanban_pool(
        pool_id=pool_id,
        product_id="PROD-A",
        source_station="STA-ASSY-01",  # 总装工序
        target_station="STA-PACK-01",  # 包装工序
        max_capacity=5,               # 最大5张在看板
    )
    print(f"   看板池: {pool.pool_id}")
    print(f"   产品: {pool.product_id}")
    print(f"   源站→目标站: {pool.source_station} → {pool.target_station}")
    print(f"   最大容量: {pool.max_capacity}")
    
    print("\n[Step 2] 📄 创建看板卡片（初始状态=EMPTY，代表有空间可取用物料）")
    card = kanban.create_kanban_card(
        pool_id=pool_id,
        product_id="PROD-A",
        product_name="成品A",
        quantity=100,              # 每张看板对应100件
        work_order_id="WO-20260728-001",
        kanban_type=KanbanType.PRODUCTION,
    )
    print(f"   看板卡号: {card.card_id}")
    print(f"   关联工单: {card.work_order_id}")
    print(f"   初始状态: {card.status.value}")
    assert card.status == KanbanStatus.EMPTY, "初始应为 EMPTY 状态"
    
    print("\n[Step 3] 👇 下发看板（EMPTY→PENDING） - 源站发出信号请求补充")
    success = kanban.emit_card(card.id, emitted_by="OPR_PLANNER")
    print(f"   下发操作: {'成功' if success else '失败'}")
    print(f"   新状态: {card.status.value}")
    assert card.status == KanbanStatus.PENDING, "下发后应为 PENDING 状态"
    
    # 检查日志
    emit_log = card.action_log[-1]
    print(f"   操作记录: {emit_log['action']} by {emit_log['by']} at {emit_log['at']}")
    
    print("\n[Step 4] 🚚 接收物料并加工中（PENDING→IN_PROGRESS）")
    success = kanban.receive_card(card.id, received_by="OPR_ASSY")
    print(f"   接收操作: {'成功' if success else '失败'}")
    print(f"   新状态: {card.status.value}")
    assert card.status == KanbanStatus.IN_PROGRESS, "接收后应为 IN_PROGRESS 状态"
    
    receive_log = card.action_log[-1]
    print(f"   记录: {receive_log['action']} {receive_log['from_status']}→{receive_log['to_status']}")
    
    print("\n[Step 5] ✅ 加工完成（IN_PROGRESS→DONE）")
    success = kanban.complete_card(card.id, completed_by="OPR_QC")
    print(f"   完成操作: {'成功' if success else '失败'}")
    print(f"   新状态: {card.status.value}")
    assert card.status == KanbanStatus.DONE, "完成后应为 DONE 状态"
    
    complete_log = card.action_log[-1]
    print(f"   记录: {complete_log['action']}")
    
    print("\n[Step 6] 🔙 回收看板（DONE→EMPTY） - 形成闭环，源站可再次下发")
    success = kanban.collect_card(card.id, collected_by="OPR_WAREHOUSE")
    print(f"   回收操作: {'成功' if success else '失败'}")
    print(f"   新状态: {card.status.value}")
    assert card.status == KanbanStatus.EMPTY, "回收后应回到 EMPTY 状态，完成循环！"
    
    collect_log = card.action_log[-1]
    print(f"   记录: {collect_log['action']} {collect_log['from_status']}→{collect_log['to_status']}")
    
    # Step 7: 查看统计信息
    print("\n[Step 7] 📊 看板池统计概览")
    stats = kanban.get_statistics()
    print(f"   总看板数: {stats['total_cards']}")
    print(f"   状态分布: {stats['by_status']}")
    print(f"   看板池数: {stats['total_pools']}")
    
    # Step 8: 列表查询
    print("\n[Step 8] 🔍 卡片列表查询（验证过滤功能）")
    all_cards = kanban.list_cards()
    print(f"   所有卡片数: {len(all_cards)}")
    
    empty_cards = kanban.list_cards(status=KanbanStatus.EMPTY)
    print(f"   EMPTY 状态卡片数: {len(empty_cards)} - 可重新使用")
    
    done_cards = kanban.list_cards(status=KanbanStatus.DONE)
    print(f"   DONE 状态卡片数: {len(done_cards)} - 等待回收")
    
    print("\n" + "=" * 70)
    print("✅ Kanban 看板全流程测试 - 闭环成功通过!")
    print("=" * 70)
    print("""
Kanban 看板系统核心价值：

✅ 拉动式可视化 - 实时显示各工序间的在制品（WIP）状态
✅ 闭环控制 - DOWNSTREAM → UPSTREAM 自动触发补货信号
✅ 限制过量生产 - 看板数量严格控制 WIP 上限
✅ 快速识别瓶颈 - 某类看板持续积压即提示产线阻塞
✅ 标准化管理 - 统一卡片格式便于追溯和审计

典型精益应用场景：
• 装配线→包装线的成品拉动
• 加工工序→仓库的原材料补货
• 跨车间的半成品传递
• 紧急插单的快速响应通道
""")
    return True


if __name__ == "__main__":
    success = test_kanban_full_cycle()
    print(f"\n最终结果: {'SUCCESS' if success else 'FAILED'}")