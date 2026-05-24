"""
AI 服务 API 路由
提供与模型网关和 Chatbot 的集成接口
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any, List
from pydantic import BaseModel

from database.db_config import get_db
from core.ai_service import ai_service

router = APIRouter(prefix="/api/v1/ai", tags=["AI Services"])


class ScheduleOptimizationRequest(BaseModel):
    work_orders: List[Dict[str, Any]]
    constraints: Dict[str, Any]


class DefectPredictionRequest(BaseModel):
    process_params: Dict[str, Any]


class QualityAnalysisRequest(BaseModel):
    inspection_data: List[Dict[str, Any]]


class ChatRequest(BaseModel):
    message: str
    context: Optional[Dict[str, Any]] = None


@router.get("/health")
async def ai_health_check():
    """检查 AI 服务网关是否可用"""
    is_healthy = await ai_service.health_check()
    if not is_healthy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI Gateway is not available"
        )
    return {
        "status": "healthy",
        "gateway_url": ai_service.model_gateway_url,
        "chatbot_url": ai_service.chatbot_url
    }


@router.post("/optimize/schedule")
async def optimize_production_schedule(
    request: ScheduleOptimizationRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    生产排程优化
    调用模型网关进行智能排程
    """
    result = await ai_service.optimize_schedule(
        work_orders=request.work_orders,
        constraints=request.constraints
    )
    
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to get optimization result from AI Gateway"
        )
    
    return result


@router.post("/predict/defects")
async def predict_defect_rate(
    request: DefectPredictionRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    不良品率预测
    基于工艺参数预测质量风险
    """
    result = await ai_service.predict_defects(
        process_params=request.process_params
    )
    
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to get prediction result from AI Gateway"
        )
    
    return result


@router.post("/analyze/quality")
async def analyze_quality_trends(
    request: QualityAnalysisRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    质量趋势分析
    分析检验数据，识别质量趋势
    """
    result = await ai_service.analyze_quality_trend(
        inspection_data=request.inspection_data
    )
    
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to get analysis result from AI Gateway"
        )
    
    return result


@router.post("/chat")
async def chat_with_assistant(
    request: ChatRequest,
    current_user_id: str = "anonymous",  # 实际应从 JWT token 获取
    db: AsyncSession = Depends(get_db)
):
    """
    与智能助手对话
    支持自然语言查询和操作指导
    """
    result = await ai_service.get_chat_response(
        user_id=current_user_id,
        message=request.message,
        context=request.context
    )
    
    if result is None:
        # 如果网关不可用，返回友好提示
        return {
            "response": f"我收到了您的问题：'{request.message}'。目前 AI 服务暂时不可用，请稍后再试。",
            "fallback": True,
            "chatbot_url": ai_service.chatbot_url
        }
    
    return result
