"""
生产专家系统 API 端点

提供 RESTful 接口供前端调用专家系统功能
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

from core.expert_system import ExpertEngine

router = APIRouter(prefix="/expert", tags=["生产专家系统"])

# 全局专家引擎实例 (延迟初始化)
_expert_engine: Optional[ExpertEngine] = None


def get_expert_engine() -> ExpertEngine:
    """获取专家引擎实例"""
    global _expert_engine
    if _expert_engine is None:
        _expert_engine = ExpertEngine()
    return _expert_engine


# ========== 请求/响应模型 ==========

class ChatRequest(BaseModel):
    """聊天请求"""
    query: str = Field(..., description="用户问题", min_length=1, max_length=2000)
    context: Optional[Dict[str, Any]] = Field(None, description="上下文信息")
    

class ChatResponse(BaseModel):
    """聊天响应"""
    answer: str = Field(..., description="专家回答")
    confidence: float = Field(..., description="置信度 (0-1)")
    sources: List[str] = Field(default_factory=list, description="知识来源")
    suggested_actions: List[str] = Field(default_factory=list, description="建议行动")
    tool_calls_executed: int = Field(default=0, description="执行的工具调用数")


class ToolInfo(BaseModel):
    """工具信息"""
    name: str
    description: str


class ToolsResponse(BaseModel):
    """可用工具列表响应"""
    tools: List[ToolInfo]


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    initialized: bool
    knowledge_base_loaded: bool


# ========== API 端点 ==========

@router.get("/health", response_model=HealthResponse)
async def health_check(engine: ExpertEngine = Depends(get_expert_engine)):
    """
    健康检查
    
    返回专家系统当前状态
    """
    return HealthResponse(
        status="healthy" if engine.is_initialized else "initializing",
        initialized=engine.is_initialized,
        knowledge_base_loaded=engine.knowledge_base.is_loaded if engine.knowledge_base else False
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    engine: ExpertEngine = Depends(get_expert_engine)
):
    """
    与生产专家对话
    
    输入生产相关问题，获取专业分析和建议
    
    **示例问题:**
    - "工单 WO-2025-0115-001 的进度如何？"
    - "SMT-01 工位的 OEE 是多少？"
    - "最近良率下降的原因是什么？"
    - "有哪些缺料风险？"
    - "设备 PM-500 需要维护吗？"
    """
    try:
        result = await engine.chat(
            query=request.query,
            context=request.context
        )
        
        return ChatResponse(**result)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"专家系统处理失败：{str(e)}"
        )


@router.get("/tools", response_model=ToolsResponse)
async def list_tools(engine: ExpertEngine = Depends(get_expert_engine)):
    """
    列出专家系统可用的工具
    
    返回所有可调用的数据查询和分析工具
    """
    if not engine.is_initialized:
        await engine.initialize()
        
    tools = engine.tool_registry.list_tools()
    return ToolsResponse(
        tools=[ToolInfo(**tool) for tool in tools]
    )


@router.post("/initialize")
async def initialize_engine(engine: ExpertEngine = Depends(get_expert_engine)):
    """
    手动初始化专家引擎
    
    通常在首次启动时自动初始化，此端点用于重新加载知识库
    """
    try:
        await engine.initialize()
        return {
            "status": "success",
            "message": "专家系统初始化完成",
            "knowledge_chunks": len(engine.knowledge_base.chunks) if engine.knowledge_base else 0
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"初始化失败：{str(e)}"
        )


@router.get("/knowledge/stats")
async def knowledge_stats(engine: ExpertEngine = Depends(get_expert_engine)):
    """
    获取知识库统计信息
    """
    if not engine.knowledge_base:
        return {
            "chunks": 0,
            "sources": []
        }
        
    # 统计知识源
    sources = {}
    for chunk in engine.knowledge_base.chunks:
        source = chunk.get("source", "unknown")
        sources[source] = sources.get(source, 0) + 1
        
    return {
        "chunks": len(engine.knowledge_base.chunks),
        "sources": list(sources.keys()),
        "source_stats": sources
    }
