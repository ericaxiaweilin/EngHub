

"""
v2.6 - Deterministic Logic Chain Conditions Evaluator
确定性逻辑链条件求值器
"""

from typing import Any, Dict, List, Optional


class ConditionEvaluator:
    """条件表达式求值器"""
    
    def __init__(self, db):
        self.db = db
    
    async def evaluate_conditions(self, conditions: List[Dict[str, Any]], event: Dict[str, Any]) -> bool:
        """
        评估条件列表
        
        Args:
            conditions: 条件列表 [{field, op, value}]
            event: 事件数据
        
        Returns:
            是否所有条件都满足
        """
        for condition in conditions or []:
            field_path = condition.get("field")
            operator = condition.get("op", "eq")
            expected_value = condition.get("value")
            
            # 获取字段值（支持嵌套路径，如 "event.payload.category_code"）
            actual_value = self._get_nested_value(event, field_path)
            
            if not self._compare(actual_value, operator, expected_value):
                return False
        
        return True
    
    def _get_nested_value(self, obj: Any, path: str) -> Any:
        """
        从嵌套对象中获取值
        
        支持路径格式：
        - "field" → obj["field"]
        - "payload.field" → obj["payload"]["field"]
        - "event.payload.field" → obj["event"]["payload"]["field"]
        """
        if not path or obj is None:
            return None
        
        parts = path.split(".")
        current = obj
        
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    index = int(part)
                    current = current[index] if 0 <= index < len(current) else None
                except (ValueError, IndexError):
                    current = None
            else:
                return None
            
            if current is None:
                return None
        
        return current
    
    def _compare(self, actual: Any, operator: str, expected: Any) -> bool:
        """
        比较操作符
        
        支持的操作符：
        - eq / == : 等于
        - neq / != : 不等于
        - gt / > : 大于
        - gte / >= : 大于等于
        - lt / < : 小于
        - lte / <= : 小于等于
        - in : 包含在列表中
        - contains : 字符串包含
        - startswith : 前缀匹配
        - endswith : 后缀匹配
        - regex : 正则匹配
        """
        if actual is None:
            return False
        
        try:
            if operator in ("eq", "=="):
                return str(actual).lower() == str(expected).lower()
            
            elif operator in ("neq", "!="):
                return str(actual).lower() != str(expected).lower()
            
            elif operator in ("gt", ">"):
                return float(actual) > float(expected)
            
            elif operator in ("gte", ">="):
                return float(actual) >= float(expected)
            
            elif operator in ("lt", "<"):
                return float(actual) < float(expected)
            
            elif operator in ("lte", "<="):
                return float(actual) <= float(expected)
            
            elif operator in ("in", "isin"):
                if isinstance(expected, list):
                    return actual in expected
                return False
            
            elif operator in ("contains", "icontains"):
                if isinstance(actual, str) and isinstance(expected, str):
                    return expected.lower() in actual.lower() if operator == "icontains" else expected in actual
                return False
            
            elif operator in ("startswith",):
                if isinstance(actual, str) and isinstance(expected, str):
                    return actual.startswith(expected)
                return False
            
            elif operator in ("endswith",):
                if isinstance(actual, str) and isinstance(expected, str):
                    return actual.endswith(expected)
                return False
            
            elif operator in ("regex",):
                import re
                return bool(re.search(str(expected), str(actual)))
            
            else:
                # 未知操作符，默认相等
                return str(actual).lower() == str(expected).lower()
        
        except (ValueError, TypeError):
            # 类型转换失败，尝试字符串比较
            return str(actual).lower() == str(expected).lower()
    
    async def evaluate_multiple_conditions(self, all_conditions: List[List[Dict[str, Any]]], event: Dict[str, Any]) -> bool:
        """
        评估多个条件组（AND关系）
        
        Args:
            all_conditions: [{field, op, value}, ...] 的列表，每个子列表代表一组OR条件
            event: 事件数据
        
        Returns:
            是否所有组都至少有一个条件满足
        """
        for condition_group in all_conditions:
            group_met = False
            for condition in condition_group:
                if await self.evaluate_single_condition(condition, event):
                    group_met = True
                    break
            
            if not group_met:
                return False
        
        return True
    
    async def evaluate_single_condition(self, condition: Dict[str, Any], event: Dict[str, Any]) -> bool:
        """评估单个条件"""
        field_path = condition.get("field")
        operator = condition.get("op", "eq")
        expected_value = condition.get("value")
        
        actual_value = self._get_nested_value(event, field_path)
        return self._compare(actual_value, operator, expected_value)


