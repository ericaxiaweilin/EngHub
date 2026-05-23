"""
MES 生产专家系统核心模块
"""
from .config import settings
from .knowledge import KnowledgeBase
from .tools import ToolRegistry, tool_registry
from .llm_client import LLMGatewayClient, llm_client


class ExpertEngine:
    """
    生产专家系统引擎
    
    负责：
    - 接收用户查询
    - 调用 RAG 检索相关知识
    - 构建 Prompt 上下文
    - 调用 LLM 生成专业回答
    - 执行工具调用 (Tool Calling)
    """
    
    def __init__(self):
        self.settings = settings
        self.knowledge_base: KnowledgeBase = None
        self.tool_registry: ToolRegistry = None
        self.llm_client: LLMGatewayClient = None
        self.is_initialized = False
        
    async def initialize(self):
        """初始化专家引擎"""
        if self.is_initialized:
            return
            
        self.knowledge_base = KnowledgeBase()
        self.tool_registry = ToolRegistry()
        self.llm_client = LLMGatewayClient()
        
        await self.knowledge_base.load()
        self.is_initialized = True
        
    async def chat(self, query: str, context: dict = None) -> dict:
        """
        处理生产专家咨询
        
        Args:
            query: 用户问题
            context: 上下文信息 (工位 ID、工单号等)
            
        Returns:
            专家回答及建议
        """
        if not self.is_initialized:
            await self.initialize()
            
        # Step 1: 检索相关知识
        knowledge_results = await self.knowledge_base.search(query, top_k=3)
        
        # Step 2: 构建系统 Prompt
        system_prompt = self.llm_client.build_system_prompt(
            role="production_expert",
            context=context
        )
        
        # Step 3: 添加工具定义
        tools_definition = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": info["description"],
                    "parameters": self._get_tool_parameters(name)
                }
            }
            for name, info in self.tool_registry.tools.items()
        ]
        
        # Step 4: 构建消息历史
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
        
        # Step 5: 如果有相关知识，添加到用户消息中
        if knowledge_results:
            knowledge_context = "\n\n【相关知识参考】\n"
            for i, result in enumerate(knowledge_results, 1):
                knowledge_context += f"{i}. [{result.get('source', 'unknown')}] {result['content'][:200]}...\n"
            messages[1]["content"] += knowledge_context
        
        # Step 6: 调用 LLM
        response = await self.llm_client.chat_completion(
            messages=messages,
            tools=tools_definition if settings.ENABLE_TOOL_CALLING else None,
            temperature=self.settings.TEMPERATURE,
            max_tokens=self.settings.MAX_TOKENS
        )
        
        # Step 7: 处理响应
        if "error" in response:
            return {
                "answer": f"系统错误：{response['error']}",
                "confidence": 0.0,
                "sources": [],
                "suggested_actions": []
            }
            
        # 检查是否需要调用工具
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        
        if "tool_calls" in message and settings.ENABLE_TOOL_CALLING:
            # 执行工具调用
            tool_results = await self._execute_tool_calls(message["tool_calls"])
            
            # 将工具结果添加回对话
            messages.append(message)
            for tool_result in tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_result["tool_call_id"],
                    "content": str(tool_result["result"])
                })
            
            # 再次调用 LLM 获取最终回答
            final_response = await self.llm_client.chat_completion(
                messages=messages,
                temperature=self.settings.TEMPERATURE,
                max_tokens=self.settings.MAX_TOKENS
            )
            
            if "error" not in final_response:
                choice = final_response.get("choices", [{}])[0]
                message = choice.get("message", {})
        
        # Step 8: 提取回答和建议
        answer = message.get("content", "抱歉，我无法回答这个问题。")
        
        # 从知识库结果中提取来源
        sources = list(set([r.get("source", "") for r in knowledge_results if r.get("source")]))
        
        # 生成建议行动 (可以从回答中解析，或基于工具结果生成)
        suggested_actions = self._extract_suggested_actions(answer)
        
        return {
            "answer": answer,
            "confidence": self._calculate_confidence(knowledge_results, choice),
            "sources": sources,
            "suggested_actions": suggested_actions,
            "tool_calls_executed": len(tool_results) if 'tool_results' in dir() else 0
        }
        
    async def _execute_tool_calls(self, tool_calls: list) -> list:
        """执行工具调用"""
        results = []
        
        for tool_call in tool_calls:
            function = tool_call.get("function", {})
            tool_name = function.get("name")
            args_str = function.get("arguments", "{}")
            
            try:
                import json
                args = json.loads(args_str)
                
                tool_info = self.tool_registry.get_tool(tool_name)
                if tool_info:
                    result = await tool_info["function"](**args)
                    results.append({
                        "tool_call_id": tool_call.get("id"),
                        "tool_name": tool_name,
                        "result": result
                    })
                else:
                    results.append({
                        "tool_call_id": tool_call.get("id"),
                        "tool_name": tool_name,
                        "result": {"error": f"Unknown tool: {tool_name}"}
                    })
            except Exception as e:
                results.append({
                    "tool_call_id": tool_call.get("id"),
                    "tool_name": tool_name,
                    "result": {"error": str(e)}
                })
                
        return results
        
    def _get_tool_parameters(self, tool_name: str) -> dict:
        """获取工具的参数定义 (简化版，实际应更详细)"""
        param_schemas = {
            "get_work_order_status": {
                "type": "object",
                "properties": {
                    "work_order_id": {"type": "string", "description": "工单编号"}
                },
                "required": ["work_order_id"]
            },
            "get_station_info": {
                "type": "object",
                "properties": {
                    "station_id": {"type": "string", "description": "工位编号"}
                },
                "required": ["station_id"]
            },
            "get_oee_metrics": {
                "type": "object",
                "properties": {
                    "station_id": {"type": "string", "description": "工位/设备编号"},
                    "time_range": {"type": "string", "description": "时间范围 (24h/7d/30d)", "default": "24h"}
                },
                "required": ["station_id"]
            },
            "get_quality_metrics": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "产品 ID"},
                    "time_range": {"type": "string", "description": "时间范围 (24h/7d/30d)", "default": "24h"}
                }
            },
            "analyze_defects": {
                "type": "object",
                "properties": {
                    "defect_type": {"type": "string", "description": "缺陷类型"},
                    "time_range": {"type": "string", "description": "时间范围", "default": "24h"}
                },
                "required": ["defect_type"]
            },
            "get_device_status": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "设备编号"}
                },
                "required": ["device_id"]
            },
            "get_inventory_level": {
                "type": "object",
                "properties": {
                    "material_id": {"type": "string", "description": "物料编号"}
                },
                "required": ["material_id"]
            },
            "get_material_shortage": {
                "type": "object",
                "properties": {
                    "work_order_id": {"type": "string", "description": "可选的工单筛选"}
                }
            },
            "get_production_data": {
                "type": "object",
                "properties": {
                    "start_time": {"type": "string", "description": "开始时间 (ISO 格式)"},
                    "end_time": {"type": "string", "description": "结束时间 (ISO 格式)"},
                    "station_id": {"type": "string", "description": "可选的工位筛选"}
                },
                "required": ["start_time", "end_time"]
            }
        }
        
        return param_schemas.get(tool_name, {
            "type": "object",
            "properties": {}
        })
        
    def _extract_suggested_actions(self, answer: str) -> list:
        """从回答中提取建议行动"""
        actions = []
        
        # 简单关键词匹配提取行动项
        action_keywords = ["建议", "应该", "需要", "请", "立即", "安排", "检查", "验证"]
        
        lines = answer.split("\n")
        for line in lines:
            line = line.strip()
            if any(keyword in line for keyword in action_keywords):
                if line.startswith("-") or line.startswith("*") or line.startswith("•"):
                    line = line[1:].strip()
                if line and len(line) > 5:
                    actions.append(line)
                    
        return actions[:5]  # 最多返回 5 条建议
        
    def _calculate_confidence(self, knowledge_results: list, choice: dict) -> float:
        """计算回答置信度"""
        confidence = 0.5  # 基础置信度
        
        # 有相关知识支持则提高置信度
        if knowledge_results:
            confidence += 0.2 * min(len(knowledge_results), 3) / 3
            
        # 回答长度适中且无错误提示
        content = choice.get("message", {}).get("content", "")
        if content and len(content) > 50 and "抱歉" not in content and "无法" not in content:
            confidence += 0.2
            
        # 执行了工具调用获取实时数据
        if "tool_calls" in choice.get("message", {}):
            confidence += 0.1
            
        return min(confidence, 1.0)
        
    async def close(self):
        """关闭引擎资源"""
        if self.llm_client:
            await self.llm_client.close()


__all__ = ["settings", "ExpertEngine", "KnowledgeBase", "ToolRegistry", "tool_registry", "llm_client"]
