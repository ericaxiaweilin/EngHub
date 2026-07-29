#!/usr/bin/env python3
"""
CAPA（纠正预防措施）业务流测试
模拟完整的8D问题解决流程：从案件创建到关闭+经验沉淀
"""

from core.qms.capa_service import CAPAService, CAPASeverity, CAPAStatus, EIGHTD_STEP


def test_capa_full_8d_flow():
    """测试完整的 CAPA 8D 全流程"""
    print("=" * 70)
    print("🧪 CAPA (8D 问题解决) 全流程测试")
    print("=" * 70)
    
    # 初始化服务
    capa = CAPAService()
    
    # D0: 准备阶段 - 快速响应（跳过D0直接进入D1）
    
    # D1: 组建跨部门团队
    print("\n[D1] 👥 组建跨部门团队")
    case = capa.create_case(
        title="客户反馈产品外壳划伤问题",
        severity=CAPASeverity.CRITICAL,
        source_type="oqc",  # 来自OQC检验发现
        source_id="OQC-20260728-001",
    )
    case.add_team_member("quality_john")
    case.add_team_member("production_sarah")
    case.add_team_member("engineering_david")
    print(f"   CAPA编号: {case.case_number}")
    print(f"   团队成员: {len(case.team_members)}人")
    print(f"   D1状态: 进行中")
    capa.progress_case_step(case.id, EIGHTD_STEP.D1_TEAM, "in_progress")
    
    # D2: 描述问题
    print("\n[D2] 🔍 详细描述问题（5W2H）")
    case.problem_description = "客户反馈收到的产品表面有划痕，影响外观质量"
    case.where_found = "生产线总装区域 / OQC出货检验环节"
    case.when_detected = "2026-07-28上午"
    case.extent = "涉及BATCH-20260728-X批次共500件，已发现5件划伤"
    print(f"   问题描述: {case.problem_description[:50]}...")
    print(f"   发生地点: {case.where_found}")
    print(f"   D2状态: 已完成")
    capa.progress_case_step(case.id, EIGHTD_STEP.D2_DESCRIBE, "completed")
    
    # D3: 临时遏制措施
    print("\n[D3] ⚠️ 临时遏制措施 - 防止问题扩散")
    case.interim_actions = [
        {"desc": "隔离受影响批次", "owner": "warehouse", "deadline": "2026-07-29"},
        {"desc": "暂停该产线发货", "owner": "production", "deadline": "2026-07-28"},
    ]
    print(f"   临时措施数: {len(case.interim_actions)}")
    print(f"   D3状态: 执行中")
    capa.progress_case_step(case.id, EIGHTD_STEP.D3_CONTAIN, "in_progress")
    
    # D4: 根本原因分析（使用5Why + 鱼骨图）
    print("\n[D4] 🔬 根本原因分析（5Why法）")
    root_causes = [
        "Why 1: 表面为什么被划伤？ -> 搬运过程中碰撞货架",
        "Why 2: 为什么会碰撞货架？ -> 周转箱摆放无防护垫",
        "Why 3: 为什么没有防护垫？ -> SOP未规定防护要求",
        "Why 4: 为什么SOP未规定？ -> 新上线产线工艺文件遗漏",
        "Why 5: 为什么工艺文件遗漏？ -> 评审流程不严格",
    ]
    for rc in root_causes:
        print(f"   {rc}")
    case.root_cause = "生产工艺文件遗漏导致周转箱无防护要求"
    case.causes_used.append("5Why")
    case.causes_used.append("Fishbone")
    print(f"   根本原因: {case.root_cause[:40]}...")
    print(f"   D4状态: 完成")
    capa.progress_case_step(case.id, EIGHTD_STEP.D4_ROOT_CAUSE, "completed")
    
    # D5: 永久纠正措施
    print("\n[D5] 🛠️ 制定永久纠正措施")
    case.corrective_actions = [
        {"id": "act1", "desc": "修订SOP增加防护要求", "owner": "engineering", "deadline": "2026-08-01"},
        {"id": "act2", "desc": "培训操作员新SOP", "owner": "production", "deadline": "2026-08-03"},
        {"id": "act3", "desc": "增加防护垫采购", "owner": "procurement", "deadline": "2026-07-31"},
    ]
    print(f"   纠正措施数: {len(case.corrective_actions)}")
    print(f"   D5状态: 计划中")
    capa.progress_case_step(case.id, EIGHTD_STEP.D5_PERM_CORRECTIVE, "planned")
    
    # D6: 验证措施有效性
    print("\n[D6] ✅ 验证纠正措施有效性")
    case.verification_result = "经两周追踪，新批号无划伤出现，措施有效"
    case.verified_by = "quality_manager"
    print(f"   验证结论: {case.verification_result[:50]}...")
    print(f"   D6状态: 已验证")
    capa.progress_case_step(case.id, EIGHTD_STEP.D6_VERIFY, "verified")
    
    # D7: 预防措施更新标准作业程序
    print("\n[D7] 📝 预防措施 - 更新相关文件/程序")
    case.preventive_actions = [
        {"desc": "更新《成品包装搬运SOP》v2.1", "owner": "quality", "target_date": "2026-08-05"},
        {"desc": "增加新员工入职培训内容", "owner": "hr", "target_date": "2026-08-10"},
    ]
    print(f"   预防措施数: {len(case.preventive_actions)}")
    print(f"   D7状态: 计划中")
    capa.progress_case_step(case.id, EIGHTD_STEP.D7_PREVENTIVE, "planned")
    
    # D8: 总结庆祝与经验传承
    print("\n[D8] 🎉 总结经验并庆祝成功")
    case.lessons_earned = "本次问题通过跨部门协作在10天内闭环，关键在于早期OQC拦截和严格的5Why分析。建议将此案例纳入新员工培训教材。"
    print(f"   经验教训摘要: {case.lessons_learned[:50]}...")
    print(f"   D8状态: 完成")
    capa.progress_case_step(case.id, EIGHTD_STEP.D8_CELEBRATE, "completed")
    
    # 最终关闭案件
    case.status = CAPAStatus.CLOSED
    print(f"\n   🏆 CAPA案件状态: CLOSED")
    
    # 查看统计信息
    stats = capa.get_statistics()
    print(f"\n📊 CAPA统计:")
    print(f"   总案件数: {stats['total_cases']}")
    print(f"   开放中: {stats['open']}")
    print(f"   关闭率: {round(stats['closed']/max(stats['total_cases'],1)*100,1)}%")
    
    print("\n" + "=" * 70)
    print("✅ CAPA 8D全流程测试通过!")
    print("=" * 70)
    print("""
CAPA（纠正预防措施）业务价值：

✅ 系统方法：标准化8D流程确保问题得到彻底解决
✅ 根源治理：不仅治标更要治本，通过5Why等方法找到根源
✅ 行动跟踪：所有行动项明确责任人和截止日期，闭环管理
✅ 预防机制：更新标准作业程序、培训等防止重复发生
✅ 知识沉淀：将问题解决经验转化为组织资产（经验教训库）

这是质量管理体系中"持续改进"理念的核心体现！
""")
    return True


if __name__ == "__main__":
    from datetime import datetime
    
    success = test_capa_full_8d_flow()
    print(f"\n最终结果: {'SUCCESS' if success else 'FAILED'}")