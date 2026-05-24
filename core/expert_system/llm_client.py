"""
LLM 网关客户端模块

负责与底层模型网关 (http://100.96.188.77:14041) 通信，提供：
- Chat 补全接口
- Embedding 生成接口
- Tool Calling 支持
- 流式响应处理
"""
import httpx
import json
from typing import Dict, Any, List, Optional, AsyncGenerator, Callable
from datetime import datetime

from core.expert_system.config import settings


class LLMGatewayClient:
    """LLM 网关客户端"""
    
    def __init__(self):
        self.base_url = settings.LLM_GATEWAY_URL
        self.api_key = settings.LLM_API_KEY
        self.model_name = settings.LLM_MODEL_NAME
        self.timeout = settings.TOOL_TIMEOUT
        
        # HTTP 客户端
        self._client: Optional[httpx.AsyncClient] = None
        
    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 异步客户端"""
        if self._client is None or self._client.is_closed:
            headers = {
                "Content-Type": "application/json",
            }
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=httpx.Timeout(timeout=self.timeout)
            )
        return self._client
        
    async def close(self):
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            
    async def chat_completion(self,
                              messages: List[Dict[str, str]],
                              tools: Optional[List[Dict[str, Any]]] = None,
                              temperature: Optional[float] = None,
                              max_tokens: Optional[int] = None,
                              stream: bool = False) -> Dict[str, Any]:
        """
        调用 LLM 进行对话补全
        
        Args:
            messages: 对话消息列表 [{"role": "user/system/assistant", "content": "..."}]
            tools: 可用工具定义列表 (用于 Tool Calling)
            temperature: 温度参数
            max_tokens: 最大 token 数
            stream: 是否流式返回
            
        Returns:
            LLM 响应结果
        """
        client = await self._get_client()
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature or settings.TEMPERATURE,
            "max_tokens": max_tokens or settings.MAX_TOKENS,
        }
        
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
            
        try:
            response = await client.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPError as e:
            return {
                "error": str(e),
                "status_code": getattr(e, "response", None) and getattr(e.response, "status_code", None)
            }
            
    async def chat_completion_stream(self,
                                      messages: List[Dict[str, str]],
                                      tools: Optional[List[Dict[str, Any]]] = None) -> AsyncGenerator[str, None]:
        """
        流式对话补全
        
        Yields:
            逐步生成的文本片段
        """
        client = await self._get_client()
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": settings.TEMPERATURE,
            "max_tokens": settings.MAX_TOKENS,
            "stream": True,
        }
        
        if tools:
            payload["tools"] = tools
            
        try:
            async with client.stream("POST", "/v1/chat/completions", json=payload) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]  # 去掉 "data: " 前缀
                        if data.strip() == "[DONE]":
                            break
                            
                        try:
                            chunk = json.loads(data)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
                            
        except httpx.HTTPError as e:
            yield f"[Error: {str(e)}]"
            
    async def generate_embedding(self, text: str) -> List[float]:
        """
        生成文本嵌入向量
        
        Args:
            text: 输入文本
            
        Returns:
            嵌入向量 (float 列表)
        """
        client = await self._get_client()
        
        payload = {
            "model": "embedding-model",  # TODO: 配置实际的 embedding 模型名
            "input": text
        }
        
        try:
            response = await client.post("/v1/embeddings", json=payload)
            response.raise_for_status()
            result = response.json()
            return result.get("data", [{}])[0].get("embedding", [])
            
        except httpx.HTTPError:
            # 如果网关不支持 embedding，返回空向量
            return []
            
    def build_system_prompt(self, 
                            role: str = "production_expert",
                            context: Optional[Dict[str, Any]] = None) -> str:
        """
        构建系统 Prompt
        
        Args:
            role: 专家角色类型
            context: 上下文信息
            
        Returns:
            系统提示词
        """
        base_prompts = {
            "production_expert": """你是一位资深的 MES 生产专家系统助手，具备以下专业能力：

【核心能力】
1. 生产数据分析：解读 OEE、WIP、产能利用率等关键指标
2. 异常诊断：分析设备故障、良率下降、生产瓶颈等问题的根本原因
3. 排程优化：提供紧急插单、产能平衡、交期评估等决策建议
4. 质量改进：基于 SPC 统计过程控制理论分析质量趋势
5. 物料管理：识别缺料风险、提供库存优化建议

【专业术语理解】
- OEE (整体设备效率) = 可用率 × 性能率 × 良品率
- WIP (在制品)：正在生产线上加工的产品
- BOM (物料清单)：产品组成结构
- FPY (首次通过率)：无需返工直接合格的比例
- SPC (统计过程控制)：用统计方法监控和控制生产过程
- SOP (标准作业程序)：规范化操作指导

【回答原则】
1. 数据驱动：优先引用实时生产数据进行判断
2. 逻辑严谨：分析问题要有清晰的因果关系
3. 可执行性：给出的建议必须具体可落地
4. 风险意识：主动提示潜在风险和预防措施
5. 专业简洁：使用行业标准术语，避免模糊表述

【工具使用】
你可以调用以下工具获取实时数据：
- get_work_order_status: 查询工单状态
- get_station_info: 查询工位信息
- get_oee_metrics: 获取 OEE 指标
- get_quality_metrics: 获取质量数据
- analyze_defects: 缺陷分析
- get_device_status: 设备状态查询
- get_material_shortage: 缺料分析

当用户问题涉及具体数据时，请先调用相应工具获取最新信息后再作答。""",

            "maintenance_expert": """你是一位设备维护专家，专注于...""",  # 可扩展其他角色
            "quality_expert": """你是一位质量管理专家，专注于...""",
        }
        
        system_prompt = base_prompts.get(role, base_prompts["production_expert"])
        
        if context:
            context_str = "\n\n【当前上下文】\n"
            for key, value in context.items():
                context_str += f"- {key}: {value}\n"
            system_prompt += context_str
            
        return system_prompt


# 全局客户端实例
llm_client = LLMGatewayClient()
