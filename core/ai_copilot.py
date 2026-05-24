"""
EngHub MES AI Copilot - 智能业务助手核心引擎
支持意图识别、工具调用、业务操控
"""
import re
import json
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime

class MESToolRegistry:
    """MES 业务工具注册中心"""
    
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._register_builtin_tools()
    
    def _register_builtin_tools(self):
        """注册内置业务工具"""
        
        # 1. 工单查询
        self.register(
            name="get_work_order_status",
            description="查询工单状态、进度、数量信息",
            func=self._tool_get_wo_status,
            params=["wo_no"]
        )
        
        # 2. 生产报工
        self.register(
            name="create_production_report",
            description="执行生产报工操作（录入良品/不良品）",
            func=self._tool_create_report,
            params=["station_code", "good_qty", "defect_qty", "wo_no"]
        )
        
        # 3. 质量分析
        self.register(
            name="analyze_quality_trend",
            description="分析近期质量趋势、良率、缺陷分布",
            func=self._tool_analyze_quality,
            params=["days"]
        )
        
        # 4. 库存查询
        self.register(
            name="get_inventory_status",
            description="查询仓库库存、预警信息",
            func=self._tool_get_inventory,
            params=["warehouse_code"]
        )
        
        # 5. 设备状态
        self.register(
            name="get_device_status",
            description="查询设备运行状态、故障信息",
            func=self._tool_get_device,
            params=["device_code"]
        )
    
    def register(self, name: str, description: str, func: Callable, params: List[str]):
        """注册工具"""
        self.tools[name] = {
            "name": name,
            "description": description,
            "func": func,
            "params": params
        }
    
    def list_tools(self) -> List[Dict]:
        """列出所有可用工具"""
        return [
            {"name": t["name"], "description": t["description"], "params": t["params"]}
            for t in self.tools.values()
        ]
    
    def execute(self, name: str, db_session: Any, **kwargs) -> str:
        """执行工具"""
        if name not in self.tools:
            return f"错误：未知工具 {name}"
        
        try:
            tool = self.tools[name]
            result = tool["func"](db_session, **kwargs)
            return result
        except Exception as e:
            return f"执行失败：{str(e)}"
    
    # === 工具实现 ===
    
    def _tool_get_wo_status(self, db: Any, wo_no: Optional[str] = None) -> str:
        """查询工单"""
        # 实际实现会查询数据库
        if wo_no:
            return f"工单 {wo_no}: 状态=RUNNING, 计划=500, 已完成=120, 进度=24%"
        return "请提供工单号，例如：'查询工单 WO-2024-001'"
    
    def _tool_create_report(self, db: Any, station_code: str, good_qty: int, defect_qty: int, wo_no: Optional[str] = None) -> str:
        """创建报工"""
        # 实际实现会写入数据库
        total = good_qty + defect_qty
        return f"✅ 报工成功！工位:{station_code}, 总数:{total}, 良品:{good_qty}, 不良:{defect_qty}"
    
    def _tool_analyze_quality(self, db: Any, days: int = 7) -> str:
        """质量分析"""
        return f"📊 近{days}天质量报告:\n- 平均良率：98.2%\n- 主要缺陷：划痕(45%), 尺寸偏差(30%)\n- 建议：加强进料检验"
    
    def _tool_get_inventory(self, db: Any, warehouse_code: Optional[str] = None) -> str:
        """库存查询"""
        return f"📦 库存状态:\n- 原材料仓：使用率 85% (预警)\n- 成品仓：使用率 62%\n- 待出库：12 单"
    
    def _tool_get_device(self, db: Any, device_code: Optional[str] = None) -> str:
        """设备状态"""
        if device_code:
            return f"⚙️ 设备 {device_code}: 运行中，温度 45°C, 负载 78%, 下次维护：3 天后"
        return "请提供设备编号"


class MESCopilotAgent:
    """MES 智能助手 Agent"""
    
    def __init__(self):
        self.tool_registry = MESToolRegistry()
        self.intent_patterns = self._build_intent_patterns()
    
    def _build_intent_patterns(self) -> Dict[str, List[str]]:
        """构建意图识别规则"""
        return {
            "get_work_order_status": [
                r"工单",
                r"WO[-_]\d+",
                r"进度.*工单"
            ],
            "create_production_report": [
                r"报工",
                r"工位.*录入",
                r"良品.*\d+.*个"
            ],
            "analyze_quality_trend": [
                r"质量.*情况",
                r"质量.*怎么样",
                r"今天.*质量"
            ],
            "get_inventory_status": [
                r"库存.*多少",
                r"原材料仓",
                r"还有多少.*库存"
            ],
            "get_device_status": [
                r"设备.*运行",
                r"设备.*正常",
                r"EQ[-_]\d+"
            ]
        }
    
    def analyze_intent(self, user_input: str) -> Dict[str, Any]:
        """分析用户意图"""
        input_lower = user_input.lower()
        
        # 提取关键参数
        extracted_params = self._extract_params(user_input)
        
        # 匹配意图
        for tool_name, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, input_lower, re.IGNORECASE):
                    return {
                        "intent": tool_name,
                        "confidence": 0.9,
                        "tool_calls": [tool_name],
                        "params": extracted_params,
                        "original_input": user_input
                    }
        
        # 默认返回通用意图
        return {
            "intent": "general_chat",
            "confidence": 0.5,
            "tool_calls": [],
            "params": {},
            "original_input": user_input
        }
    
    def _extract_params(self, text: str) -> Dict[str, Any]:
        """提取参数"""
        params = {}
        
        # 提取工单号
        wo_match = re.search(r"WO[-_]\d{4}[-_]\d+", text, re.IGNORECASE)
        if wo_match:
            params["wo_no"] = wo_match.group()
        
        # 提取工位号
        station_match = re.search(r"[A-Z]{3,5}-\d+", text)
        if station_match:
            params["station_code"] = station_match.group()
        
        # 提取数字（数量）
        qty_matches = re.findall(r"(\d+)\s*(?:个|件|pcs)", text)
        if len(qty_matches) >= 1:
            params["good_qty"] = int(qty_matches[0])
        if len(qty_matches) >= 2:
            params["defect_qty"] = int(qty_matches[1])
        
        # 提取时间
        days_match = re.search(r"(\d+)\s*(?:天|日)", text)
        if days_match:
            params["days"] = int(days_match.group())
        
        return params
    
    async def process_request(self, user_input: str, db_session: Any, history: List[Dict] = None) -> Dict[str, Any]:
        """处理用户请求"""
        # 1. 意图识别
        intent_result = self.analyze_intent(user_input)
        
        # 2. 如果有明确意图，调用工具
        if intent_result["tool_calls"]:
            tool_name = intent_result["tool_calls"][0]
            params = intent_result["params"]
            
            # 执行工具
            result = self.tool_registry.execute(tool_name, db_session, **params)
            
            return {
                "reply": result,
                "action_type": "tool_result",
                "tool_used": tool_name,
                "intent": intent_result["intent"]
            }
        
        # 3. 通用对话（需调用模型网关）
        return {
            "reply": f"收到：'{user_input}'。我是 MES 智能助手，可以帮您查询工单、报工、分析质量等。请告诉我具体需求。",
            "action_type": "text",
            "intent": "general_chat"
        }


# 单例模式
_copilot_instance: Optional[MESCopilotAgent] = None

def get_copilot_agent() -> MESCopilotAgent:
    global _copilot_instance
    if _copilot_instance is None:
        _copilot_instance = MESCopilotAgent()
    return _copilot_instance
