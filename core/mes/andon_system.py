"""
MES 安灯系统 (Andon) 与异常管理模块

功能：
1. 异常呼叫：工位一键呼叫（缺料、设备故障、品质异常、技术支援）
2. 响应机制：班组长/维修工接单、处理记录、升级机制
3. 停线逻辑：关键工位异常自动触发停线或跳站
4. 数据统计：MTTR (平均修复时间)、MTBF (平均故障间隔) 分析
5. 消息推送：短信/邮件/APP 推送通知

作者：MES Development Team
日期：2026-05-24
"""

import asyncio
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
import uuid
import json

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AndonType(Enum):
    """安灯类型"""
    MATERIAL_SHORTAGE = "MATERIAL_SHORTAGE"  # 缺料
    EQUIPMENT_FAILURE = "EQUIPMENT_FAILURE"  # 设备故障
    QUALITY_ISSUE = "QUALITY_ISSUE"  # 品质异常
    TECHNICAL_SUPPORT = "TECHNICAL_SUPPORT"  # 技术支援
    SAFETY_INCIDENT = "SAFETY_INCIDENT"  # 安全事故
    OTHER = "OTHER"  # 其他


class AndonStatus(Enum):
    """安灯状态"""
    OPEN = "OPEN"  # 未处理
    ACKNOWLEDGED = "ACKNOWLEDGED"  # 已确认
    IN_PROGRESS = "IN_PROGRESS"  # 处理中
    RESOLVED = "RESOLVED"  # 已解决
    ESCALATED = "ESCALATED"  # 已升级
    CLOSED = "CLOSED"  # 已关闭


class PriorityLevel(Enum):
    """优先级"""
    LOW = 1  # 低
    MEDIUM = 2  # 中
    HIGH = 3  # 高
    CRITICAL = 4  # 紧急


@dataclass
class AndonEvent:
    """安灯事件"""
    event_id: str
    workstation_id: str
    andon_type: AndonType
    priority: PriorityLevel
    description: str
    created_at: datetime
    created_by: str  # 操作员 ID
    status: AndonStatus = AndonStatus.OPEN
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolution_notes: str = ""
    escalated_at: Optional[datetime] = None
    escalated_to: Optional[str] = None
    response_time_seconds: float = 0.0
    resolution_time_seconds: float = 0.0
    is_line_stopped: bool = False
    
    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "workstation_id": self.workstation_id,
            "andon_type": self.andon_type.value,
            "priority": self.priority.value,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "status": self.status.value,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "acknowledged_by": self.acknowledged_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_notes": self.resolution_notes,
            "response_time_seconds": self.response_time_seconds,
            "resolution_time_seconds": self.resolution_time_seconds,
            "is_line_stopped": self.is_line_stopped
        }


@dataclass
class EscalationRule:
    """升级规则"""
    andon_type: AndonType
    timeout_minutes: int
    escalate_to: str  # 角色或人员 ID
    auto_stop_line: bool = False


class NotificationService:
    """消息通知服务"""
    
    def __init__(self):
        self.handlers: List[Callable] = []
    
    def register_handler(self, handler: Callable):
        """注册通知处理器"""
        self.handlers.append(handler)
    
    async def send_notification(self, event: AndonEvent, recipient: str, message: str):
        """发送通知"""
        notification = {
            "event_id": event.event_id,
            "recipient": recipient,
            "message": message,
            "priority": event.priority.value,
            "timestamp": datetime.now().isoformat()
        }
        
        logger.info(f"📱 发送通知给 {recipient}: {message}")
        
        for handler in self.handlers:
            try:
                await handler(notification)
            except Exception as e:
                logger.error(f"通知处理器执行失败: {e}")
    
    async def sms_handler(self, notification: dict):
        """短信通知处理器（模拟）"""
        if notification["priority"] >= PriorityLevel.HIGH.value:
            logger.info(f"   📩 [SMS] 发送给 {notification['recipient']}: {notification['message']}")
    
    async def email_handler(self, notification: dict):
        """邮件通知处理器（模拟）"""
        logger.info(f"   📧 [Email] 发送给 {notification['recipient']}: {notification['message']}")
    
    async def app_push_handler(self, notification: dict):
        """APP 推送处理器（模拟）"""
        logger.info(f"   🔔 [APP Push] 发送给 {notification['recipient']}: {notification['message']}")


class AndonSystem:
    """安灯系统核心类"""
    
    def __init__(self):
        self.events: Dict[str, AndonEvent] = {}
        self.active_events: List[str] = []
        self.notification_service = NotificationService()
        self.escalation_rules: List[EscalationRule] = []
        self.line_status: Dict[str, bool] = {}  # 产线状态：True=运行，False=停止
        self.workstation_assignments: Dict[str, str] = {}  # 工位 - 责任人映射
        self._setup_default_rules()
        self._setup_notifications()
    
    def _setup_default_rules(self):
        """设置默认升级规则"""
        self.escalation_rules = [
            EscalationRule(AndonType.EQUIPMENT_FAILURE, 5, "maintenance_lead", auto_stop_line=True),
            EscalationRule(AndonType.MATERIAL_SHORTAGE, 10, "warehouse_supervisor"),
            EscalationRule(AndonType.QUALITY_ISSUE, 15, "quality_manager"),
            EscalationRule(AndonType.SAFETY_INCIDENT, 2, "safety_officer", auto_stop_line=True),
            EscalationRule(AndonType.TECHNICAL_SUPPORT, 20, "engineering_lead"),
        ]
    
    def _setup_notifications(self):
        """设置通知处理器"""
        self.notification_service.register_handler(self.notification_service.sms_handler)
        self.notification_service.register_handler(self.notification_service.email_handler)
        self.notification_service.register_handler(self.notification_service.app_push_handler)
    
    def create_andon_event(
        self,
        workstation_id: str,
        andon_type: AndonType,
        description: str,
        operator_id: str,
        priority: Optional[PriorityLevel] = None
    ) -> AndonEvent:
        """创建安灯事件"""
        if priority is None:
            priority = self._determine_priority(andon_type)
        
        event_id = f"ANDON-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
        
        event = AndonEvent(
            event_id=event_id,
            workstation_id=workstation_id,
            andon_type=andon_type,
            priority=priority,
            description=description,
            created_at=datetime.now(),
            created_by=operator_id
        )
        
        self.events[event_id] = event
        self.active_events.append(event_id)
        
        # 检查是否需要停线
        line_id = self._get_line_id(workstation_id)
        rule = self._get_escalation_rule(andon_type)
        if rule and rule.auto_stop_line:
            event.is_line_stopped = True
            self.stop_production_line(line_id, event_id)
        
        logger.info(f"🚨 安灯事件创建: {event_id}")
        logger.info(f"   工位：{workstation_id}, 类型：{andon_type.value}, 优先级：{priority.name}")
        logger.info(f"   描述：{description}")
        if event.is_line_stopped:
            logger.warning(f"   ⛔ 产线 {line_id} 已停止")
        
        # 异步发送通知
        asyncio.create_task(self._notify_responders(event))
        
        return event
    
    def _determine_priority(self, andon_type: AndonType) -> PriorityLevel:
        """根据类型确定默认优先级"""
        priority_map = {
            AndonType.SAFETY_INCIDENT: PriorityLevel.CRITICAL,
            AndonType.EQUIPMENT_FAILURE: PriorityLevel.HIGH,
            AndonType.QUALITY_ISSUE: PriorityLevel.MEDIUM,
            AndonType.MATERIAL_SHORTAGE: PriorityLevel.MEDIUM,
            AndonType.TECHNICAL_SUPPORT: PriorityLevel.LOW,
            AndonType.OTHER: PriorityLevel.LOW,
        }
        return priority_map.get(andon_type, PriorityLevel.LOW)
    
    def _get_escalation_rule(self, andon_type: AndonType) -> Optional[EscalationRule]:
        """获取升级规则"""
        for rule in self.escalation_rules:
            if rule.andon_type == andon_type:
                return rule
        return None
    
    def _get_line_id(self, workstation_id: str) -> str:
        """获取工位所属产线"""
        parts = workstation_id.split("-")
        return parts[0] if len(parts) > 1 else "LINE-1"
    
    async def _notify_responders(self, event: AndonEvent):
        """通知责任人"""
        rule = self._get_escalation_rule(event.andon_type)
        if rule:
            message = (
                f"【安灯警报】{event.andon_type.value}\n"
                f"工位：{event.workstation_id}\n"
                f"优先级：{event.priority.name}\n"
                f"描述：{event.description}\n"
                f"时间：{event.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            await self.notification_service.send_notification(event, rule.escalate_to, message)
    
    def acknowledge_event(self, event_id: str, responder_id: str) -> bool:
        """确认安灯事件"""
        if event_id not in self.events:
            logger.error(f"事件 {event_id} 不存在")
            return False
        
        event = self.events[event_id]
        if event.status != AndonStatus.OPEN:
            logger.warning(f"事件 {event_id} 状态为 {event.status.value}, 无法确认")
            return False
        
        event.status = AndonStatus.ACKNOWLEDGED
        event.acknowledged_at = datetime.now()
        event.acknowledged_by = responder_id
        event.response_time_seconds = (event.acknowledged_at - event.created_at).total_seconds()
        
        logger.info(f"✅ 事件 {event_id} 已被 {responder_id} 确认")
        logger.info(f"   响应时间：{event.response_time_seconds:.1f}秒")
        
        return True
    
    def start_resolution(self, event_id: str, responder_id: str) -> bool:
        """开始处理安灯事件"""
        if event_id not in self.events:
            return False
        
        event = self.events[event_id]
        if event.status not in [AndonStatus.OPEN, AndonStatus.ACKNOWLEDGED]:
            return False
        
        event.status = AndonStatus.IN_PROGRESS
        logger.info(f"🔧 事件 {event_id} 开始处理，处理人：{responder_id}")
        
        return True
    
    def resolve_event(
        self,
        event_id: str,
        resolver_id: str,
        resolution_notes: str = ""
    ) -> bool:
        """解决安灯事件"""
        if event_id not in self.events:
            return False
        
        event = self.events[event_id]
        if event.status not in [AndonStatus.ACKNOWLEDGED, AndonStatus.IN_PROGRESS]:
            logger.warning(f"事件 {event_id} 状态为 {event.status.value}, 无法解决")
            return False
        
        event.status = AndonStatus.RESOLVED
        event.resolved_at = datetime.now()
        event.resolved_by = resolver_id
        event.resolution_notes = resolution_notes
        event.resolution_time_seconds = (event.resolved_at - event.created_at).total_seconds()
        
        # 如果之前停线了，现在恢复
        if event.is_line_stopped:
            line_id = self._get_line_id(event.workstation_id)
            self.resume_production_line(line_id, event_id)
        
        # 从活跃列表移除
        if event_id in self.active_events:
            self.active_events.remove(event_id)
        
        logger.info(f"✅ 事件 {event_id} 已解决")
        logger.info(f"   解决人：{resolver_id}")
        logger.info(f"   总耗时：{event.resolution_time_seconds:.1f}秒")
        logger.info(f"   备注：{resolution_notes}")
        
        return True
    
    def stop_production_line(self, line_id: str, reason_event_id: str):
        """停止产线"""
        self.line_status[line_id] = False
        logger.warning(f"⛔ 产线 {line_id} 已停止，原因事件：{reason_event_id}")
    
    def resume_production_line(self, line_id: str, resolved_event_id: str):
        """恢复产线"""
        self.line_status[line_id] = True
        logger.info(f"▶️ 产线 {line_id} 已恢复，事件 {resolved_event_id} 已解决")
    
    def escalate_event(self, event_id: str, escalate_to: str) -> bool:
        """升级安灯事件"""
        if event_id not in self.events:
            return False
        
        event = self.events[event_id]
        event.status = AndonStatus.ESCALATED
        event.escalated_at = datetime.now()
        event.escalated_to = escalate_to
        
        logger.warning(f"⬆️ 事件 {event_id} 已升级至 {escalate_to}")
        
        # 发送升级通知
        message = f"【安灯升级】事件 {event_id} 已升级至您处理\n类型：{event.andon_type.value}\n工位：{event.workstation_id}"
        asyncio.create_task(
            self.notification_service.send_notification(event, escalate_to, message)
        )
        
        return True
    
    def get_active_events(self) -> List[AndonEvent]:
        """获取所有活跃事件"""
        return [self.events[eid] for eid in self.active_events]
    
    def calculate_mttr(self, time_range_hours: int = 24) -> float:
        """计算平均修复时间 (MTTR)"""
        cutoff_time = datetime.now() - timedelta(hours=time_range_hours)
        resolved_events = [
            e for e in self.events.values()
            if e.status in [AndonStatus.RESOLVED, AndonStatus.CLOSED]
            and e.resolved_at and e.resolved_at > cutoff_time
        ]
        
        if not resolved_events:
            return 0.0
        
        total_time = sum(e.resolution_time_seconds for e in resolved_events)
        return total_time / len(resolved_events)
    
    def calculate_mtbf(self, time_range_hours: int = 24) -> float:
        """计算平均故障间隔 (MTBF) - 简化版"""
        cutoff_time = datetime.now() - timedelta(hours=time_range_hours)
        failure_events = [
            e for e in self.events.values()
            if e.andon_type == AndonType.EQUIPMENT_FAILURE
            and e.created_at > cutoff_time
        ]
        
        if len(failure_events) < 2:
            return float('inf')
        
        failure_events.sort(key=lambda e: e.created_at)
        intervals = []
        for i in range(1, len(failure_events)):
            interval = (failure_events[i].created_at - failure_events[i-1].created_at).total_seconds()
            intervals.append(interval)
        
        return sum(intervals) / len(intervals) if intervals else float('inf')
    
    def generate_report(self) -> dict:
        """生成安灯系统报告"""
        now = datetime.now()
        last_24h = now - timedelta(hours=24)
        
        recent_events = [e for e in self.events.values() if e.created_at > last_24h]
        
        report = {
            "report_time": now.isoformat(),
            "total_events_24h": len(recent_events),
            "active_events": len(self.active_events),
            "events_by_type": {},
            "events_by_priority": {},
            "mttr_seconds": self.calculate_mttr(),
            "mtbf_seconds": self.calculate_mtbf(),
            "line_stoppages_24h": sum(1 for e in recent_events if e.is_line_stopped),
            "average_response_time": 0.0,
            "average_resolution_time": 0.0
        }
        
        # 按类型统计
        for event in recent_events:
            type_key = event.andon_type.value
            report["events_by_type"][type_key] = report["events_by_type"].get(type_key, 0) + 1
            
            priority_key = event.priority.name
            report["events_by_priority"][priority_key] = report["events_by_priority"].get(priority_key, 0) + 1
        
        # 计算平均时间
        responded_events = [e for e in recent_events if e.acknowledged_at]
        resolved_events = [e for e in recent_events if e.resolved_at]
        
        if responded_events:
            report["average_response_time"] = sum(e.response_time_seconds for e in responded_events) / len(responded_events)
        
        if resolved_events:
            report["average_resolution_time"] = sum(e.resolution_time_seconds for e in resolved_events) / len(resolved_events)
        
        return report


async def demonstrate_andon_system():
    """演示安灯系统功能"""
    print("=" * 80)
    print("MES 安灯系统与异常管理演示")
    print("=" * 80)
    
    andon_system = AndonSystem()
    
    # 初始化产线状态
    andon_system.line_status["LINE-1"] = True
    andon_system.line_status["LINE-2"] = True
    
    print("\n📊 初始产线状态:")
    for line_id, status in andon_system.line_status.items():
        print(f"   {line_id}: {'运行中 ▶️' if status else '已停止 ⛔'}")
    
    # 场景 1: 设备故障（高优先级，自动停线）
    print("\n" + "-" * 80)
    print("场景 1: 设备故障 - 烧录工站 PLC 通信失败")
    print("-" * 80)
    
    event1 = andon_system.create_andon_event(
        workstation_id="LINE-1-STATION-03",
        andon_type=AndonType.EQUIPMENT_FAILURE,
        description="烧录器 PLC 通信失败，无法读取设备 ID",
        operator_id="OP-007"
    )
    
    await asyncio.sleep(0.5)
    
    # 班组长确认
    andon_system.acknowledge_event(event1.event_id, "TEAM_LEAD-001")
    
    # 开始处理
    andon_system.start_resolution(event1.event_id, "MAINT-002")
    
    await asyncio.sleep(0.5)
    
    # 解决问题
    andon_system.resolve_event(
        event1.event_id,
        "MAINT-002",
        "更换 PLC 通信线缆，重新建立连接，测试正常"
    )
    
    # 场景 2: 缺料（中优先级）
    print("\n" + "-" * 80)
    print("场景 2: 缺料 - 包装工站缺少外箱")
    print("-" * 80)
    
    event2 = andon_system.create_andon_event(
        workstation_id="LINE-1-STATION-08",
        andon_type=AndonType.MATERIAL_SHORTAGE,
        description="TM-X500 跑步机外箱库存不足，需要补货",
        operator_id="OP-012",
        priority=PriorityLevel.MEDIUM
    )
    
    await asyncio.sleep(0.5)
    
    # 仓库主管确认并解决
    andon_system.acknowledge_event(event2.event_id, "WAREHOUSE-SUP-001")
    andon_system.start_resolution(event2.event_id, "WAREHOUSE-SUP-001")
    andon_system.resolve_event(
        event2.event_id,
        "WAREHOUSE-SUP-001",
        "已从仓库调拨 50 个外箱至线边仓"
    )
    
    # 场景 3: 品质异常
    print("\n" + "-" * 80)
    print("场景 3: 品质异常 - FCT 测试不良率超标")
    print("-" * 80)
    
    event3 = andon_system.create_andon_event(
        workstation_id="LINE-2-STATION-05",
        andon_type=AndonType.QUALITY_ISSUE,
        description="连续 3 台跑步机蓝牙模块测试失败，不良率超过 5%",
        operator_id="OP-025",
        priority=PriorityLevel.HIGH
    )
    
    await asyncio.sleep(0.5)
    
    # 质量工程师处理
    andon_system.acknowledge_event(event3.event_id, "QE-003")
    andon_system.start_resolution(event3.event_id, "QE-003")
    andon_system.resolve_event(
        event3.event_id,
        "QE-003",
        "确认为蓝牙模块批次问题，已隔离该批次物料，切换至备用供应商"
    )
    
    # 场景 4: 安全事故（紧急，自动停线）
    print("\n" + "-" * 80)
    print("场景 4: 安全事故 - 员工受伤")
    print("-" * 80)
    
    event4 = andon_system.create_andon_event(
        workstation_id="LINE-2-STATION-02",
        andon_type=AndonType.SAFETY_INCIDENT,
        description="操作员手指被传送带夹伤，需要紧急医疗救助",
        operator_id="OP-019"
    )
    
    await asyncio.sleep(0.5)
    
    # 安全官快速响应
    andon_system.acknowledge_event(event4.event_id, "SAFETY-OFFICER-001")
    andon_system.start_resolution(event4.event_id, "SAFETY-OFFICER-001")
    andon_system.resolve_event(
        event4.event_id,
        "SAFETY-OFFICER-001",
        "已送医治疗，伤情稳定。已对传送带加装防护罩"
    )
    
    # 生成报告
    print("\n" + "=" * 80)
    print("📈 安灯系统运行报告")
    print("=" * 80)
    
    report = andon_system.generate_report()
    
    print(f"\n报告时间：{report['report_time']}")
    print(f"24 小时事件总数：{report['total_events_24h']}")
    print(f"当前活跃事件：{report['active_events']}")
    print(f"产线停线次数：{report['line_stoppages_24h']}")
    print(f"平均响应时间：{report['average_response_time']:.1f}秒")
    print(f"平均解决时间：{report['average_resolution_time']:.1f}秒")
    print(f"MTTR (平均修复时间): {report['mttr_seconds']:.1f}秒")
    print(f"MTBF (平均故障间隔): {report['mtbf_seconds']:.1f}秒" if report['mtbf_seconds'] != float('inf') else "MTBF: 数据不足")
    
    print("\n事件类型分布:")
    for type_name, count in report['events_by_type'].items():
        print(f"   {type_name}: {count}")
    
    print("\n优先级分布:")
    for priority, count in report['events_by_priority'].items():
        print(f"   {priority}: {count}")
    
    print("\n最终产线状态:")
    for line_id, status in andon_system.line_status.items():
        print(f"   {line_id}: {'运行中 ▶️' if status else '已停止 ⛔'}")
    
    print("\n" + "=" * 80)
    print("安灯系统演示完成")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(demonstrate_andon_system())
