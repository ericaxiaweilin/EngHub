"""
TMS Unit Tests - 任务管理系统单元测试

测试覆盖：
- 事件总线
- 分发引擎
- 审批工作流
- Agent 接口
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# ============== Event Bus Tests ==============

class TestTMSEventBus:
    """事件总线测试"""

    def test_event_bus_init(self):
        """测试事件总线初始化"""
        from core.tms.events import TMSEventBus
        bus = TMSEventBus()
        assert bus._handlers == {}
        assert bus._webhook_subscriptions == []
        assert bus._event_history == []

    def test_subscribe(self):
        """测试事件订阅"""
        from core.tms.events import TMSEventBus
        bus = TMSEventBus()
        
        handler = MagicMock()
        bus.subscribe("task.created", handler)
        
        assert "task.created" in bus._handlers
        assert handler in bus._handlers["task.created"]

    def test_unsubscribe(self):
        """测试取消订阅"""
        from core.tms.events import TMSEventBus
        bus = TMSEventBus()
        
        handler = MagicMock()
        bus.subscribe("task.created", handler)
        bus.unsubscribe("task.created", handler)
        
        assert handler not in bus._handlers.get("task.created", [])

    @pytest.mark.asyncio
    async def test_publish_event(self):
        """测试发布事件"""
        from core.tms.events import TMSEventBus, TMSEventType
        bus = TMSEventBus()
        
        received_events = []
        
        async def handler(event):
            received_events.append(event)
        
        bus.subscribe(TMSEventType.TASK_CREATED.value, handler)
        
        event = await bus.publish(
            TMSEventType.TASK_CREATED.value,
            {"task_id": "123", "task_code": "TASK-001"}
        )
        
        assert event.event_type == TMSEventType.TASK_CREATED.value
        assert event.payload["task_id"] == "123"
        assert len(received_events) == 1

    def test_register_webhook(self):
        """测试注册 Webhook"""
        from core.tms.events import TMSEventBus
        bus = TMSEventBus()
        
        sub = bus.register_webhook(
            agent_id="test-agent",
            event_types=["task.created", "task.completed"],
            webhook_url="https://example.com/webhook",
            secret="secret123"
        )
        
        assert sub.agent_id == "test-agent"
        assert len(bus._webhook_subscriptions) == 1

    def test_unregister_webhook(self):
        """测试注销 Webhook"""
        from core.tms.events import TMSEventBus
        bus = TMSEventBus()
        
        bus.register_webhook("agent1", ["task.created"], "https://a.com")
        bus.register_webhook("agent2", ["task.completed"], "https://b.com")
        
        removed = bus.unregister_webhook("agent1")
        
        assert removed == 1
        assert len(bus._webhook_subscriptions) == 1

    def test_get_event_history(self):
        """测试获取事件历史"""
        from core.tms.events import TMSEventBus, TMSEvent
        bus = TMSEventBus()
        
        # 手动添加历史
        bus._event_history = [
            TMSEvent(event_type="task.created", payload={"id": 1}),
            TMSEvent(event_type="task.completed", payload={"id": 2}),
            TMSEvent(event_type="task.created", payload={"id": 3}),
        ]
        
        history = bus.get_event_history("task.created")
        assert len(history) == 2


# ============== Distribution Engine Tests ==============

class TestDistributionEngine:
    """分发引擎测试"""

    def test_distribution_strategy_enum(self):
        """测试分发策略枚举"""
        from core.tms.distribution_engine import DistributionStrategy
        
        assert DistributionStrategy.SKILL_MATCH.value == "skill_match"
        assert DistributionStrategy.LOAD_BALANCE.value == "load_balance"
        assert DistributionStrategy.ROUND_ROBIN.value == "round_robin"
        assert DistributionStrategy.AGENT_DECIDE.value == "agent_decide"

    def test_distribution_mode_enum(self):
        """测试分发模式枚举"""
        from core.tms.distribution_engine import DistributionMode
        
        assert DistributionMode.DIRECT.value == "direct"
        assert DistributionMode.POOL.value == "pool"
        assert DistributionMode.AGENT.value == "agent"

    def test_candidate_score_dataclass(self):
        """测试候选人评分数据类"""
        from core.tms.distribution_engine import CandidateScore
        
        score = CandidateScore(
            user_id="user-123",
            username="zhangwei",
            full_name="张伟",
            total_score=0.85,
            skill_score=0.35,
            load_score=0.20,
            history_score=0.18,
            response_score=0.12,
            reasons=["技能高度匹配", "负载较低"]
        )
        
        assert score.user_id == "user-123"
        assert score.total_score == 0.85
        assert len(score.reasons) == 2

    def test_distribution_result_dataclass(self):
        """测试分发结果数据类"""
        from core.tms.distribution_engine import DistributionResult
        
        result = DistributionResult(
            success=True,
            task_id="task-123",
            strategy="skill_match",
            mode="direct",
            assigned_to="user-456",
            assigned_to_name="李工",
            reason="技能匹配度最高",
            message="任务已分配给李工"
        )
        
        assert result.success is True
        assert result.assigned_to == "user-456"

    def test_weights_configuration(self):
        """测试评分权重配置"""
        from core.tms.distribution_engine import DistributionEngine
        
        # 验证权重总和为 1
        weights = DistributionEngine.WEIGHTS
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01


# ============== Approval Workflow Tests ==============

class TestApprovalWorkflow:
    """审批工作流测试"""

    def test_flow_type_enum(self):
        """测试审批流类型枚举"""
        from core.tms.approval_workflow import FlowType
        
        assert FlowType.SEQUENTIAL.value == "sequential"
        assert FlowType.PARALLEL.value == "parallel"
        assert FlowType.CONDITIONAL.value == "conditional"

    def test_flow_status_enum(self):
        """测试审批流状态枚举"""
        from core.tms.approval_workflow import FlowStatus
        
        assert FlowStatus.ACTIVE.value == "active"
        assert FlowStatus.APPROVED.value == "approved"
        assert FlowStatus.REJECTED.value == "rejected"
        assert FlowStatus.CANCELLED.value == "cancelled"

    def test_approval_action_enum(self):
        """测试审批动作枚举"""
        from core.tms.approval_workflow import ApprovalAction
        
        assert ApprovalAction.APPROVE.value == "approve"
        assert ApprovalAction.REJECT.value == "reject"
        assert ApprovalAction.DELEGATE.value == "delegate"
        assert ApprovalAction.ESCALATE.value == "escalate"

    def test_flow_step_dataclass(self):
        """测试审批步骤数据类"""
        from core.tms.approval_workflow import FlowStep
        
        step = FlowStep(
            step_index=0,
            step_name="EE 审批",
            approver_role="engineer",
            approval_type="or",
            allow_agent=True
        )
        
        assert step.step_index == 0
        assert step.allow_agent is True

    def test_flow_result_dataclass(self):
        """测试审批结果数据类"""
        from core.tms.approval_workflow import FlowResult
        
        result = FlowResult(
            success=True,
            flow_id="flow-123",
            flow_status="approved",
            current_step=2,
            action="approve",
            message="审批全部通过"
        )
        
        assert result.success is True
        assert result.flow_status == "approved"

    def test_default_steps_generation(self):
        """测试默认审批步骤生成"""
        from core.tms.approval_workflow import ApprovalWorkflowEngine
        
        # 创建 mock db
        mock_db = MagicMock()
        engine = ApprovalWorkflowEngine(mock_db)
        
        # ECN 发布默认步骤
        ecn_steps = engine._get_default_steps("ecn_release")
        assert len(ecn_steps) == 3
        assert ecn_steps[0]["step_name"] == "EE 审批"
        
        # ECR 审批默认步骤
        ecr_steps = engine._get_default_steps("ecr_approval")
        assert len(ecr_steps) == 2
        
        # 未知类型默认步骤
        unknown_steps = engine._get_default_steps("unknown_type")
        assert len(unknown_steps) == 1


# ============== Agent Interface Tests ==============

class TestAgentInterface:
    """Agent 接口测试"""

    def test_agent_permission_level_enum(self):
        """测试 Agent 权限等级枚举"""
        from core.tms.agent_interface import AgentPermissionLevel
        
        assert AgentPermissionLevel.LEVEL_1.value == 1
        assert AgentPermissionLevel.LEVEL_2.value == 2
        assert AgentPermissionLevel.LEVEL_3.value == 3

    def test_agent_command_enum(self):
        """测试 Agent 命令枚举"""
        from core.tms.agent_interface import AgentCommand
        
        assert AgentCommand.QUERY_TASKS.value == "query_tasks"
        assert AgentCommand.ASSIGN_TASK.value == "assign_task"
        assert AgentCommand.APPROVE_TASK.value == "approve_task"
        assert AgentCommand.BATCH_DISTRIBUTE.value == "batch_distribute"

    def test_command_permissions_mapping(self):
        """测试命令权限映射"""
        from core.tms.agent_interface import (
            COMMAND_PERMISSIONS,
            AgentCommand,
            AgentPermissionLevel
        )
        
        # LEVEL 1 命令
        assert COMMAND_PERMISSIONS[AgentCommand.QUERY_TASKS] == AgentPermissionLevel.LEVEL_1
        assert COMMAND_PERMISSIONS[AgentCommand.GET_RECOMMENDATION] == AgentPermissionLevel.LEVEL_1
        
        # LEVEL 2 命令
        assert COMMAND_PERMISSIONS[AgentCommand.ASSIGN_TASK] == AgentPermissionLevel.LEVEL_2
        assert COMMAND_PERMISSIONS[AgentCommand.CREATE_TASK] == AgentPermissionLevel.LEVEL_2
        
        # LEVEL 3 命令
        assert COMMAND_PERMISSIONS[AgentCommand.APPROVE_TASK] == AgentPermissionLevel.LEVEL_3
        assert COMMAND_PERMISSIONS[AgentCommand.BATCH_DISTRIBUTE] == AgentPermissionLevel.LEVEL_3

    def test_requires_confirmation_set(self):
        """测试需要确认的命令集合"""
        from core.tms.agent_interface import REQUIRES_CONFIRMATION, AgentCommand
        
        assert AgentCommand.REASSIGN_TASK in REQUIRES_CONFIRMATION
        assert AgentCommand.APPROVE_TASK in REQUIRES_CONFIRMATION
        assert AgentCommand.REJECT_TASK in REQUIRES_CONFIRMATION
        assert AgentCommand.BATCH_DISTRIBUTE in REQUIRES_CONFIRMATION
        
        # 这些不需要确认
        assert AgentCommand.QUERY_TASKS not in REQUIRES_CONFIRMATION
        assert AgentCommand.ASSIGN_TASK not in REQUIRES_CONFIRMATION

    def test_agent_command_request_dataclass(self):
        """测试 Agent 命令请求数据类"""
        from core.tms.agent_interface import AgentCommandRequest
        
        request = AgentCommandRequest(
            agent_id="chatbot-01",
            command="assign_task",
            params={"task_id": "123", "assign_to": "user:zhangwei"},
            idempotency_key="unique-key-123"
        )
        
        assert request.agent_id == "chatbot-01"
        assert request.command == "assign_task"
        assert request.params["task_id"] == "123"

    def test_agent_command_response_dataclass(self):
        """测试 Agent 命令响应数据类"""
        from core.tms.agent_interface import AgentCommandResponse
        
        response = AgentCommandResponse(
            success=True,
            command="assign_task",
            data={"assigned_to": "user:zhangwei"},
            message="任务已分配",
            requires_confirmation=False
        )
        
        assert response.success is True
        assert response.requires_confirmation is False

    def test_agent_registration(self):
        """测试 Agent 注册"""
        from core.tms.agent_interface import AgentInterface
        
        mock_db = MagicMock()
        interface = AgentInterface(mock_db)
        
        # 注册 Agent
        interface.register_agent("test-agent", permission_level=2, whitelisted=True)
        
        assert interface.get_agent_permission("test-agent") == 2
        assert "test-agent" in interface._agent_whitelist

    def test_agent_permission_default(self):
        """测试 Agent 默认权限"""
        from core.tms.agent_interface import AgentInterface
        
        mock_db = MagicMock()
        interface = AgentInterface(mock_db)
        
        # 未注册的 Agent 默认 LEVEL 1
        assert interface.get_agent_permission("unknown-agent") == 1


# ============== Database Models Tests ==============

class TestTMSModels:
    """TMS 数据模型测试"""

    def test_tms_task_model_exists(self):
        """测试 TMSTask 模型存在"""
        from database.models import TMSTask
        assert TMSTask.__tablename__ == "tms_tasks"

    def test_tms_approval_flow_model_exists(self):
        """测试 TMSApprovalFlow 模型存在"""
        from database.models import TMSApprovalFlow
        assert TMSApprovalFlow.__tablename__ == "tms_approval_flows"

    def test_tms_approval_record_model_exists(self):
        """测试 TMSApprovalRecord 模型存在"""
        from database.models import TMSApprovalRecord
        assert TMSApprovalRecord.__tablename__ == "tms_approval_records"

    def test_tms_distribution_log_model_exists(self):
        """测试 TMSDistributionLog 模型存在"""
        from database.models import TMSDistributionLog
        assert TMSDistributionLog.__tablename__ == "tms_distribution_logs"

    def test_tms_agent_action_model_exists(self):
        """测试 TMSAgentAction 模型存在"""
        from database.models import TMSAgentAction
        assert TMSAgentAction.__tablename__ == "tms_agent_actions"

    def test_tms_webhook_subscription_model_exists(self):
        """测试 TMSWebhookSubscription 模型存在"""
        from database.models import TMSWebhookSubscription
        assert TMSWebhookSubscription.__tablename__ == "tms_webhook_subscriptions"


# ============== API Schemas Tests ==============

class TestTMSSchemas:
    """TMS API Schemas 测试"""

    def test_task_create_schema(self):
        """测试任务创建 Schema"""
        from api.schemas.tms import TaskCreate
        
        task = TaskCreate(
            title="测试任务",
            task_type="ecn_release",
            priority="high",
            points=100,
            required_skills=["EE", "PCB"]
        )
        
        assert task.title == "测试任务"
        assert task.task_type == "ecn_release"
        assert task.points == 100

    def test_agent_command_request_schema(self):
        """测试 Agent 命令请求 Schema"""
        from api.schemas.tms import AgentCommandRequest
        
        request = AgentCommandRequest(
            agent_id="chatbot-01",
            command="query_tasks",
            params={"status": "pending"}
        )
        
        assert request.agent_id == "chatbot-01"
        assert request.command == "query_tasks"

    def test_dashboard_stats_schema(self):
        """测试仪表盘统计 Schema"""
        from api.schemas.tms import TMSDashboardStats
        
        stats = TMSDashboardStats(
            pending_distribution=5,
            in_progress=10,
            completed=100,
            weekly_points=500,
            sla_rate=95.5
        )
        
        assert stats.pending_distribution == 5
        assert stats.sla_rate == 95.5


# ============== Integration Tests ==============

class TestTMSIntegration:
    """TMS 集成测试"""

    def test_module_imports(self):
        """测试模块导入"""
        from core.tms import (
            DistributionEngine,
            ApprovalWorkflowEngine,
            AgentInterface,
            TMSEventBus,
            tms_event_bus,
        )
        
        assert DistributionEngine is not None
        assert ApprovalWorkflowEngine is not None
        assert AgentInterface is not None
        assert tms_event_bus is not None

    def test_event_types_complete(self):
        """测试事件类型完整性"""
        from core.tms.events import TMSEventType
        
        # 任务事件
        assert hasattr(TMSEventType, 'TASK_CREATED')
        assert hasattr(TMSEventType, 'TASK_DISTRIBUTED')
        assert hasattr(TMSEventType, 'TASK_CLAIMED')
        assert hasattr(TMSEventType, 'TASK_COMPLETED')
        
        # 审批事件
        assert hasattr(TMSEventType, 'APPROVAL_INITIATED')
        assert hasattr(TMSEventType, 'APPROVAL_PENDING')
        assert hasattr(TMSEventType, 'APPROVAL_APPROVED')
        assert hasattr(TMSEventType, 'APPROVAL_REJECTED')
        
        # Agent 事件
        assert hasattr(TMSEventType, 'AGENT_COMMAND_RECEIVED')
        assert hasattr(TMSEventType, 'AGENT_ACTION_COMPLETED')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
