"""
Copilot 智能助手 API 路由
提供聊天接口，支持业务操控
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from core.ai_copilot import get_copilot_agent
from database.db_config import get_db

router = APIRouter(prefix="/copilot", tags=["AI Copilot"])

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[dict]] = None
    user_id: Optional[int] = None

class ChatResponse(BaseModel):
    reply: str
    action_type: str  # "text", "tool_result", "form_required"
    tool_used: Optional[str] = None
    intent: Optional[str] = None
    suggested_actions: Optional[List[str]] = None

@router.post("/chat", response_model=ChatResponse)
async def chat_with_copilot(req: ChatRequest, db: Session = Depends(get_db)):
    """
    与 MES 智能助手对话
    支持自然语言查询和业务操作
    """
    agent = get_copilot_agent()
    
    try:
        result = await agent.process_request(
            user_input=req.message,
            db_session=db,
            history=req.history or []
        )
        
        # 生成建议操作
        suggested = []
        if result["intent"] == "get_work_order_status":
            suggested = ["创建报工", "查看工艺路线", "分析质量"]
        elif result["intent"] == "analyze_quality_trend":
            suggested = ["查看缺陷详情", "触发 OCAP", "导出报告"]
        elif result["intent"] == "create_production_report":
            suggested = ["查看历史记录", "修改报工", "继续报工"]
        
        return ChatResponse(
            reply=result["reply"],
            action_type=result["action_type"],
            tool_used=result.get("tool_used"),
            intent=result.get("intent"),
            suggested_actions=suggested
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Copilot 处理失败：{str(e)}")


@router.get("/tools")
async def list_available_tools():
    """列出所有可用的业务工具"""
    agent = get_copilot_agent()
    tools = agent.tool_registry.list_tools()
    return {
        "total": len(tools),
        "tools": tools
    }


@router.get("/status")
async def copilot_status():
    """检查 Copilot 状态"""
    agent = get_copilot_agent()
    return {
        "status": "online",
        "tools_registered": len(agent.tool_registry.tools),
        "version": "1.0.0"
    }
