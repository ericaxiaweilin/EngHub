"""
AI 服务集成层
负责与外部模型网关 (Model Gateway) 和 Chatbot 进行通信
"""
import httpx
import logging
from typing import Optional, Dict, Any, List
from core.config import settings

logger = logging.getLogger(__name__)


class AIService:
    """AI 服务客户端"""
    
    def __init__(self):
        self.model_gateway_url = settings.MODEL_GATEWAY_URL
        self.chatbot_url = settings.CHATBOT_URL
        self.timeout = 30.0  # 秒
        
    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """通用请求方法"""
        url = f"{self.model_gateway_url.rstrip('/')}/{endpoint.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if method == "GET":
                    response = await client.get(url)
                elif method == "POST":
                    response = await client.post(url, json=data)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.warning(f"AI Gateway error: {response.status_code} - {response.text}")
                    return None
        except httpx.RequestError as e:
            logger.error(f"Failed to connect to AI Gateway: {e}")
            return None

    # ================= 生产优化相关 =================
    
    async def optimize_schedule(self, work_orders: List[Dict], constraints: Dict) -> Optional[Dict]:
        """
        调用模型网关进行生产排程优化
        :param work_orders: 工单列表
        :param constraints: 约束条件 (产能/物料/人员等)
        :return: 优化后的排程结果
        """
        payload = {
            "task": "schedule_optimization",
            "data": {
                "work_orders": work_orders,
                "constraints": constraints
            }
        }
        return await self._request("POST", "/api/v1/optimize", payload)

    async def predict_defects(self, process_params: Dict) -> Optional[Dict]:
        """
        预测不良品率
        :param process_params: 工艺参数
        :return: 预测结果 (不良率/主要缺陷类型)
        """
        payload = {
            "task": "defect_prediction",
            "data": process_params
        }
        return await self._request("POST", "/api/v1/predict", payload)

    async def analyze_quality_trend(self, inspection_data: List[Dict]) -> Optional[Dict]:
        """
        质量趋势分析
        :param inspection_data: 检验数据列表
        :return: 趋势分析报告
        """
        payload = {
            "task": "quality_analysis",
            "data": inspection_data
        }
        return await self._request("POST", "/api/v1/analyze", payload)

    async def get_chat_response(self, user_id: str, message: str, context: Optional[Dict] = None) -> Optional[Dict]:
        """
        获取 Chatbot 回复 (如果网关支持聊天 API)
        :param user_id: 用户 ID
        :param message: 用户消息
        :param context: 上下文信息
        :return: Chatbot 回复
        """
        payload = {
            "user_id": user_id,
            "message": message,
            "context": context or {}
        }
        return await self._request("POST", "/api/v1/chat", payload)

    async def health_check(self) -> bool:
        """检查模型网关是否可用"""
        result = await self._request("GET", "/health")
        return result is not None and result.get("status") == "ok"


# 全局实例
ai_service = AIService()
