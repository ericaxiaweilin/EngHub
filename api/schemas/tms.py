"""
TMS API Schemas - Pydantic 请求/响应模型
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============== Task Schemas ==============

class TaskCreate(BaseModel):
    """创建任务请求"""
    title: str = Field(..., max_length=200, description="任务标题")
    description: Optional[str] = Field(None, description="任务描述")
    task_type: str = Field(default="custom", description="任务类型: ecn_release, ecr_approval, inspection, custom")
    priority: str = Field(default="medium", description="优先级: low, medium, high, urgent")
    points: int = Field(default=0, ge=0, description="积分")
    required_skills: List[str] = Field(default_factory=list, description="所需技能")
    required_roles: List[str] = Field(default_factory=list, description="所需角色")
    deadline: Optional[datetime] = Field(None, description="截止日期")
    distribution_strategy: Optional[str] = Field(None, description="分发策略")
    related_work_order_id: Optional[str] = Field(None, description="关联工单ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class TaskUpdate(BaseModel):
    """更新任务请求"""
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    points: Optional[int] = None
    required_skills: Optional[List[str]] = None
    deadline: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


class TaskResponse(BaseModel):
    """任务响应"""
    id: str
    task_code: str
    title: str
    description: Optional[str]
    task_type: str
    source: str
    priority: str
    points: int
    status: str
    distribution_strategy: Optional[str]
    assigned_to: Optional[str]
    assigned_by: Optional[str]
    candidate_pool: List[Dict[str, Any]]
    required_skills: List[str]
    required_roles: List[str]
    deadline: Optional[datetime]
    approval_flow_id: Optional[str]
    agent_context: Dict[str, Any]
    metadata: Dict[str, Any]
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    """任务列表响应"""
    items: List[TaskResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TaskDistributeRequest(BaseModel):
    """任务分发请求"""
    strategy: str = Field(default="skill_match", description="分发策略")
    mode: str = Field(default="direct", description="分发模式: direct, pool, agent")
    target_user_id: Optional[str] = Field(None, description="手动指定分配对象")


class TaskClaimRequest(BaseModel):
    """任务认领请求"""
    user_id: str = Field(..., description="认领人ID")


# ============== Approval Schemas ==============

class ApprovalFlowCreate(BaseModel):
    """创建审批流请求"""
    task_id: str = Field(..., description="关联任务ID")
    flow_type: str = Field(default="sequential", description="流类型: sequential, parallel, conditional")
    steps: Optional[List[Dict[str, Any]]] = Field(None, description="审批步骤定义")


class ApprovalActionRequest(BaseModel):
    """审批操作请求"""
    approver_id: str = Field(..., description="审批人ID")
    comment: Optional[str] = Field(None, description="审批意见")


class ApprovalDelegateRequest(BaseModel):
    """委托审批请求"""
    from_user_id: str = Field(..., description="委托人ID")
    to_user_id: str = Field(..., description="被委托人ID")


class ApprovalEscalateRequest(BaseModel):
    """升级审批请求"""
    reason: str = Field(..., description="升级原因")


class ApprovalFlowResponse(BaseModel):
    """审批流响应"""
    flow_id: str
    flow_code: str
    task_id: str
    flow_type: str
    status: str
    current_step: int
    total_steps: int
    steps: List[Dict[str, Any]]
    records: List[Dict[str, Any]]


class PendingApprovalItem(BaseModel):
    """待审批项"""
    flow_id: str
    flow_code: str
    task_id: str
    task_code: str
    task_title: str
    task_type: str
    priority: str
    current_step: int
    step_name: str
    initiated_by: Optional[str]
    created_at: Optional[str]


# ============== Agent Schemas ==============

class AgentCommandRequest(BaseModel):
    """Agent 命令请求"""
    agent_id: str = Field(..., description="Agent 标识")
    command: str = Field(..., description="命令名称")
    params: Dict[str, Any] = Field(default_factory=dict, description="命令参数")
    idempotency_key: Optional[str] = Field(None, description="幂等键")


class AgentCommandResponse(BaseModel):
    """Agent 命令响应"""
    success: bool
    command: str
    data: Dict[str, Any]
    message: str
    requires_confirmation: bool = False
    confirmation_id: Optional[str] = None
    action_id: Optional[str] = None


class AgentConfirmRequest(BaseModel):
    """Agent 操作确认请求"""
    action_id: str = Field(..., description="待确认操作ID")
    confirmed_by: str = Field(..., description="确认人ID")
    approved: bool = Field(default=True, description="是否批准")


class AgentRegisterRequest(BaseModel):
    """Agent 注册请求"""
    agent_id: str = Field(..., description="Agent 标识")
    permission_level: int = Field(default=1, ge=1, le=3, description="权限等级 1-3")
    whitelisted: bool = Field(default=False, description="是否加入白名单")


class WebhookRegisterRequest(BaseModel):
    """Webhook 注册请求"""
    agent_id: str = Field(..., description="Agent 标识")
    event_types: List[str] = Field(..., description="订阅事件类型列表")
    webhook_url: str = Field(..., description="Webhook URL")
    secret: Optional[str] = Field(None, description="签名密钥")


# ============== Distribution Schemas ==============

class DistributionLogResponse(BaseModel):
    """分发日志响应"""
    id: str
    task_id: str
    strategy: str
    candidate_scores: Dict[str, Any]
    selected_user_id: Optional[str]
    reason: Optional[str]
    triggered_by: str
    created_at: datetime


class DistributionStatsResponse(BaseModel):
    """分发统计响应"""
    status_distribution: Dict[str, int]
    strategy_usage: Dict[str, int]
    total_distributions: int


# ============== Dashboard Schemas ==============

class TMSDashboardStats(BaseModel):
    """TMS 仪表盘统计"""
    pending_distribution: int = 0
    distributed: int = 0
    claimed: int = 0
    in_progress: int = 0
    pending_approval: int = 0
    completed: int = 0
    rejected: int = 0
    total: int = 0
    weekly_points: int = 0
    sla_rate: float = 0.0


class TaskCardItem(BaseModel):
    """任务卡片项（前端展示用）"""
    task_id: str
    task_code: str
    title: str
    task_type: str
    priority: str
    points: int
    status: str
    assigned_to_name: Optional[str]
    deadline: Optional[str]
    required_skills: List[str]
    ai_recommendation: Optional[str] = None
    risk_alert: Optional[str] = None
