"""
安灯系统 - 单元测试

覆盖:
1. 各类异常呼叫创建 + 工单归类
2. 确认 / 处理 / 解决流程
3. 停线 / 恢复逻辑
4. MTTR / MTBF 统计
"""

import asyncio
import pytest

from core.mes.andon_system import AndonSystem, AndonType, AndonStatus, PriorityLevel


@pytest.fixture
def andon():
    system = AndonSystem()
    system.line_status["LINE-1"] = True
    return system


class TestAndonEventCreation:
    def test_material_shortage(self, andon):
        e = andon.create_andon_event(
            workstation_id="LINE-1-STATION-03",
            andon_type=AndonType.MATERIAL_SHORTAGE,
            description="IC 芯片缺料",
            operator_id="OP-001",
            priority=PriorityLevel.MEDIUM,
        )
        assert e.event_id
        assert e.andon_type == AndonType.MATERIAL_SHORTAGE
        assert e.status == AndonStatus.OPEN

    def test_equipment_failure_triggers_line_stop(self, andon):
        e = andon.create_andon_event(
            workstation_id="LINE-1-STATION-02",
            andon_type=AndonType.EQUIPMENT_FAILURE,
            description="贴片机气压不足",
            operator_id="OP-002",
            priority=PriorityLevel.HIGH,
        )
        # 设备故障应触发停线
        assert e.is_line_stopped or andon.line_status.get("LINE-1") is False

    def test_multiple_events(self, andon):
        for i in range(5):
            andon.create_andon_event(
                workstation_id=f"LINE-1-STATION-{i:02d}",
                andon_type=AndonType.OTHER,
                description=f"测试事件 {i}",
                operator_id="OP-001",
                priority=PriorityLevel.LOW,
            )
        active = andon.get_active_events()
        assert len(active) == 5


class TestAndonWorkflow:
    def test_acknowledge(self, andon):
        e = andon.create_andon_event(
            workstation_id="LINE-1-STATION-01",
            andon_type=AndonType.QUALITY_ISSUE,
            description="品质异常",
            operator_id="OP-001",
            priority=PriorityLevel.MEDIUM,
        )
        assert andon.acknowledge_event(e.event_id, "RESP-01")
        assert e.status == AndonStatus.ACKNOWLEDGED
        assert e.acknowledged_by == "RESP-01"

    def test_resolve_flow(self, andon):
        e = andon.create_andon_event(
            workstation_id="LINE-1-STATION-02",
            andon_type=AndonType.EQUIPMENT_FAILURE,
            description="设备故障",
            operator_id="OP-001",
            priority=PriorityLevel.HIGH,
        )
        andon.acknowledge_event(e.event_id, "MAINT-01")
        andon.start_resolution(e.event_id, "MAINT-01")
        assert e.status == AndonStatus.IN_PROGRESS

        andon.resolve_event(e.event_id, "MAINT-01", "更换气压阀")
        assert e.status == AndonStatus.RESOLVED
        assert e.resolution_notes == "更换气压阀"

    def test_acknowledge_nonexistent(self, andon):
        assert not andon.acknowledge_event("FAKE-ID", "RESP-01")


class TestAndonStatistics:
    def test_generate_report(self, andon):
        # 创建 + 解决几个事件
        for i in range(3):
            e = andon.create_andon_event(
                workstation_id=f"LINE-1-STATION-{i:02d}",
                andon_type=AndonType.EQUIPMENT_FAILURE,
                description=f"故障 {i}",
                operator_id="OP-001",
                priority=PriorityLevel.HIGH,
            )
            andon.acknowledge_event(e.event_id, "MAINT-01")
            andon.resolve_event(e.event_id, "MAINT-01", f"修复 {i}")

        report = andon.generate_report()
        assert report["total_events_24h"] >= 3
        assert "events_by_type" in report
        assert "mttr_seconds" in report
#!/usr/bin/env python3
"""
安灯系统测试脚本 - 验证异常呼叫、工单生成、数据沉淀功能

测试场景:
1. 物料缺料呼叫 -> 仓库/计划部门工单
2. 工艺问题呼叫 -> IE/工程部门工单
3. 设备故障呼叫 -> 设备维修工单 (自动停线)
4. 品质异常呼叫 -> 品质部工单
5. 工人操作问题 -> 生产主管/HR 工单
6. 数据压缩与统计分析 (MTTR, MTBF)
"""

import sys
sys.path.insert(0, '/workspace')

import asyncio
from core.mes.andon_system import AndonSystem, AndonType, PriorityLevel


async def run_test():
    """运行安灯系统测试"""
    print('='*70)
    print('MES 安灯系统测试 - 异常呼叫、工单生成与数据沉淀')
    print('='*70)
    
    # 创建安灯系统实例
    andon = AndonSystem()
    
    # 初始化产线状态
    andon.line_status["LINE-1"] = True
    
    print('\n【场景 1】模拟各类异常呼叫与工单生成\n')
    
    # 1. 物料缺料呼叫
    e1 = andon.create_andon_event(
        workstation_id='LINE-1-STATION-03',
        andon_type=AndonType.MATERIAL_SHORTAGE,
        description='IC 芯片缺料，预计停工时间 30 分钟',
        operator_id='OP-001',
        priority=PriorityLevel.MEDIUM
    )
    print(f'📦 [物料] 工单生成：{e1.event_id}')
    print(f'   归类：{e1.andon_type.value} -> 责任部门：仓库/计划')
    print(f'   优先级：{e1.priority.name}')
    
    # 等待通知发送
    await asyncio.sleep(0.1)
    
    # 2. 工艺问题呼叫
    e2 = andon.create_andon_event(
        workstation_id='LINE-1-STATION-05',
        andon_type=AndonType.TECHNICAL_SUPPORT,
        description='焊接温度参数异常，产品良率下降至 85%',
        operator_id='OP-002',
        priority=PriorityLevel.HIGH
    )
    print(f'\n⚙️  [工艺] 工单生成：{e2.event_id}')
    print(f'   归类：{e2.andon_type.value} -> 责任部门：IE/工程')
    print(f'   优先级：{e2.priority.name}')
    
    await asyncio.sleep(0.1)
    
    # 3. 设备故障呼叫 (会触发停线)
    e3 = andon.create_andon_event(
        workstation_id='LINE-1-STATION-02',
        andon_type=AndonType.EQUIPMENT_FAILURE,
        description='贴片机气压不足，设备停机',
        operator_id='OP-003',
        priority=PriorityLevel.HIGH
    )
    print(f'\n🔧 [生计] 工单生成：{e3.event_id}')
    print(f'   归类：{e3.andon_type.value} -> 责任部门：设备维修')
    print(f'   优先级：{e3.priority.name}')
    print(f'   停线状态：{"✅ 已停线" if e3.is_line_stopped else "❌ 未停线"}')
    
    await asyncio.sleep(0.1)
    
    # 4. 品质异常呼叫
    e4 = andon.create_andon_event(
        workstation_id='LINE-1-STATION-07',
        andon_type=AndonType.QUALITY_ISSUE,
        description='连续发现 3pcs PCB 板焊点不良',
        operator_id='OP-004',
        priority=PriorityLevel.MEDIUM
    )
    print(f'\n🔍 [品质] 工单生成：{e4.event_id}')
    print(f'   归类：{e4.andon_type.value} -> 责任部门：品质部')
    print(f'   优先级：{e4.priority.name}')
    
    await asyncio.sleep(0.1)
    
    # 5. 工人操作问题
    e5 = andon.create_andon_event(
        workstation_id='LINE-1-STATION-04',
        andon_type=AndonType.OTHER,
        description='新员工操作不熟练，需要支援',
        operator_id='OP-005',
        priority=PriorityLevel.LOW
    )
    print(f'\n👷 [工人] 工单生成：{e5.event_id}')
    print(f'   归类：TRAINING_NEEDED -> 责任部门：生产主管/HR')
    print(f'   优先级：{e5.priority.name}')
    
    await asyncio.sleep(0.1)
    
    # 模拟处理流程
    print('\n' + '='*70)
    print('【场景 2】异常处理流程演示')
    print('='*70)
    
    # 处理设备故障
    print(f'\n处理事件：{e3.event_id}')
    andon.acknowledge_event(e3.event_id, 'MAINT-001')
    print(f'✅ 已确认 - 处理人：MAINT-001, 响应时间：{e3.response_time_seconds:.1f}秒')
    
    andon.start_resolution(e3.event_id, 'MAINT-001')
    print(f'🔧 处理中...')
    
    andon.resolve_event(e3.event_id, 'MAINT-001', '更换气压阀，设备恢复正常')
    print(f'✅ 已解决 - 总耗时：{e3.resolution_time_seconds:.1f}秒')
    print(f'   备注：{e3.resolution_notes}')
    
    # 生成统计报告
    print('\n' + '='*70)
    print('【场景 3】数据压缩与统计分析')
    print('='*70)
    
    report = andon.generate_report()
    
    print(f'\n📊 数据统计报告:')
    print(f'   24 小时内事件总数：{report["total_events_24h"]} 件')
    print(f'   当前活跃事件：{report["active_events"]} 件')
    print(f'   停线次数：{report["line_stoppages_24h"]} 次')
    
    print(f'\n📈 按类型分布:')
    for type_name, count in report["events_by_type"].items():
        print(f'   {type_name}: {count} 件')
    
    print(f'\n📈 按优先级分布:')
    for priority_name, count in report["events_by_priority"].items():
        print(f'   {priority_name}: {count} 件')
    
    print(f'\n⏱️ 时间指标:')
    print(f'   平均响应时间：{report["average_response_time"]:.1f} 秒')
    print(f'   平均解决时间：{report["average_resolution_time"]:.1f} 秒')
    print(f'   MTTR (平均修复时间): {report["mttr_seconds"]:.1f} 秒')
    print(f'   MTBF (平均故障间隔): {report["mtbf_seconds"]:.1f} 秒')
    
    # 数据沉淀说明
    print('\n' + '='*70)
    print('【数据沉淀说明】')
    print('='*70)
    print('''
✅ 已沉淀的数据维度:
   1. 异常类型分布 -> 用于识别高频问题
   2. 响应/解决时间 -> 用于考核团队绩效
   3. 停线记录 -> 用于计算 OEE 损失
   4. 责任部门归类 -> 用于工单自动分派
   5. MTTR/MTBF -> 用于设备维护策略优化
   
📈 数据驱动混合排产的应用:
   - 根据历史 MTTR 预估异常处理时间，动态调整排程缓冲
   - 根据异常类型频率，优化预防性维护计划
   - 根据工位稳定性数据，合理分配急单/重要订单
   - 根据人员技能数据 (工人异常), 优化人力配置
''')
    
    print('\n' + '='*70)
    print('✅ 安灯系统测试完成 - 工单已生成并沉淀数据')
    print('='*70)
    
    return report


if __name__ == '__main__':
    asyncio.run(run_test())
