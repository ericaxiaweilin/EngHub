"""
MES 企业级统一搜索架构 (对标 Atlassian Rovo)

核心设计理念:
1. Unified Index - 全域数据统一索引协议
2. Context-Aware - 深度上下文感知与关联
3. Action-Oriented - 结果即入口，支持直接操作
4. Permission-Aware - 动态权限过滤
5. Real-time Sync - 实时数据同步机制
"""

from pydantic import BaseModel, Field
from typing import Optional, Any, Union
from datetime import datetime
from enum import Enum


class SearchEntityType(str, Enum):
    """支持的实体类型"""
    WORK_ORDER = "work_order"
    STATION = "station"
    DEVICE = "device"
    MATERIAL = "material"
    SOP = "sop"
    QUALITY_REPORT = "quality_report"
    MAINTENANCE_PLAN = "maintenance_plan"
    USER = "user"
    ALERT = "alert"


class SearchAction(BaseModel):
    """搜索结果可执行的操作"""
    action_type: str = Field(..., description="操作类型：view/edit/approve/reject/create")
    label: str = Field(..., description="操作显示文本")
    url: str = Field(..., description="操作 API 端点或前端路由")
    method: str = Field(default="GET", description="HTTP 方法")
    requires_confirmation: bool = Field(default=False, description="是否需要确认")
    icon: Optional[str] = Field(None, description="操作图标")


class SearchResultLink(BaseModel):
    """深度链接信息"""
    entity_type: SearchEntityType
    entity_id: str
    route_path: str  # 前端路由路径 e.g., "/work-orders/WO-2024-001"
    permalink: str  # 完整 URL
    breadcrumb: list[str]  # 面包屑导航


class RelatedContext(BaseModel):
    """关联上下文信息"""
    type: str  # parent/child/related/sibling
    entity_type: SearchEntityType
    entity_id: str
    title: str
    summary: str
    link: SearchResultLink


class SearchDocument(BaseModel):
    """
    统一搜索文档协议
    所有业务数据必须转换为此格式进行索引
    """
    id: str = Field(..., description="唯一标识符")
    entity_type: SearchEntityType = Field(..., description="实体类型")
    
    # 核心内容
    title: str = Field(..., description="标题/名称")
    content: str = Field(..., description="全文内容 (用于全文检索)")
    summary: str = Field(..., description="摘要 (用于结果展示)")
    
    # 元数据
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    owner_id: Optional[str] = Field(None, description="所有者 ID")
    owner_name: Optional[str] = Field(None, description="所有者姓名")
    status: Optional[str] = Field(None, description="状态")
    priority: Optional[str] = Field(None, description="优先级")
    
    # 分类标签
    tags: list[str] = Field(default_factory=list, description="标签列表")
    category: Optional[str] = Field(None, description="分类")
    
    # 深度链接
    link: SearchResultLink = Field(..., description="点击跳转链接")
    
    # 可执行操作
    actions: list[SearchAction] = Field(default_factory=list, description="可执行操作列表")
    
    # 关联上下文 (用于 Rovo 式卡片展示)
    related_context: list[RelatedContext] = Field(default_factory=list, description="关联信息")
    
    # 权限控制
    required_permissions: list[str] = Field(default_factory=list, description="查看所需权限")
    acl_roles: list[str] = Field(default_factory=list, description="允许访问的角色")
    
    # 扩展字段 (存储原始数据快照)
    metadata: dict[str, Any] = Field(default_factory=dict, description="原始数据快照")
    
    # 搜索优化
    search_boost: float = Field(default=1.0, description="搜索权重提升因子")
    keywords: list[str] = Field(default_factory=list, description="提取的关键词")


class SearchQuery(BaseModel):
    """搜索查询参数"""
    query: str = Field(..., description="搜索关键词")
    entity_types: Optional[list[SearchEntityType]] = Field(None, description="限定实体类型")
    filters: dict[str, Any] = Field(default_factory=dict, description="过滤条件")
    
    # 分页
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")
    
    # 排序
    sort_by: str = Field(default="relevance", description="排序字段：relevance/date/title")
    sort_order: str = Field(default="desc", description="排序方向：asc/desc")
    
    # 高级选项
    include_related: bool = Field(default=True, description="是否包含关联信息")
    highlight_enabled: bool = Field(default=True, description="是否启用高亮")
    fuzzy_search: bool = Field(default=False, description="是否启用模糊搜索")
    
    # 上下文感知
    context_user_id: Optional[str] = Field(None, description="当前用户 ID (用于权限过滤)")
    context_station_id: Optional[str] = Field(None, description="当前工位 ID (用于相关性提升)")


class SearchHit(BaseModel):
    """单条搜索结果"""
    document: SearchDocument
    score: float = Field(..., description="相关性分数")
    highlights: dict[str, list[str]] = Field(default_factory=dict, description="高亮片段")
    explanation: Optional[str] = Field(None, description="匹配原因解释")


class SearchResponse(BaseModel):
    """搜索响应"""
    query: str
    total_hits: int
    page: int
    page_size: int
    total_pages: int
    hits: list[SearchHit]
    
    # 聚合统计 (用于侧边栏过滤器)
    aggregations: dict[str, dict[str, int]] = Field(default_factory=dict, description="分面统计")
    
    # 建议查询
    suggestions: list[str] = Field(default_factory=list, description="相关搜索建议")
    
    # 性能指标
    took_ms: int = Field(..., description="查询耗时 (毫秒)")


class IndexOperation(BaseModel):
    """索引操作"""
    operation: str = Field(..., description="操作类型：index/update/delete")
    entity_type: SearchEntityType
    entity_id: str
    document: Optional[SearchDocument] = None  # delete 时不需要


# 预定义的路由映射表
ROUTE_MAPPING = {
    SearchEntityType.WORK_ORDER: "/work-orders/{id}",
    SearchEntityType.STATION: "/stations/{id}",
    SearchEntityType.DEVICE: "/devices/{id}",
    SearchEntityType.MATERIAL: "/materials/{id}",
    SearchEntityType.SOP: "/sop/{id}",
    SearchEntityType.QUALITY_REPORT: "/quality/{id}",
    SearchEntityType.MAINTENANCE_PLAN: "/maintenance/{id}",
    SearchEntityType.USER: "/users/{id}",
    SearchEntityType.ALERT: "/alerts/{id}",
}

# 预定义的权限映射
PERMISSION_MAPPING = {
    SearchEntityType.WORK_ORDER: ["work_order:view"],
    SearchEntityType.STATION: ["station:view"],
    SearchEntityType.DEVICE: ["device:view"],
    SearchEntityType.MATERIAL: ["material:view"],
    SearchEntityType.SOP: ["sop:view"],
    SearchEntityType.QUALITY_REPORT: ["quality:view"],
    SearchEntityType.MAINTENANCE_PLAN: ["maintenance:view"],
    SearchEntityType.USER: ["user:view"],
    SearchEntityType.ALERT: ["alert:view"],
}
