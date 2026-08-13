"""Evidence - 工具事实证据链（Phase 5）。

把一次请求的工具执行结果收敛为结构化 Evidence，供 Model Review 逐项
校验模型的陈述是否可以由工具事实支撑（grounded / partially / hallucinated）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Evidence:
    """一条工具事实证据。

    source_tables: 数据来源表（工具内部记录，可空）
    confidence: 工具返回数据的置信度（结构完整=1.0，错误=0）
    """

    tool_name: str
    tool_args: Dict[str, Any] = field(default_factory=dict)
    tool_result: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    source_tables: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_result": self.tool_result,
            "confidence": self.confidence,
            "source_tables": self.source_tables,
            "timestamp": self.timestamp,
        }


def confidence_for_result(result: Dict[str, Any]) -> float:
    """根据工具返回结构推断置信度：error → 0；空列表 → 0.5；有数据 → 1.0。"""
    if not isinstance(result, dict):
        return 0.0
    if result.get("error") or result.get("permission_denied"):
        return 0.0
    # 常见的载荷键：work_orders/inventory/defects/items/result/count…
    has_payload = any(
        k in result and result[k] not in (None, [], {})
        for k in ("work_orders", "inventory", "defects", "equipment", "items",
                  "result", "data", "rows", "diagrams", "success")
    )
    if has_payload:
        return 1.0
    if result.get("count") == 0:
        return 0.5
    return 0.8


def build_evidence_chain(actions: List[Any]) -> List[Evidence]:
    """从 ToolAction 列表构建证据链。

    每个 action 若未标记失败则成一条 Evidence；失败动作 confidence=0。
    """
    chain: List[Evidence] = []
    for a in actions:
        result = _action_result(a)
        chain.append(
            Evidence(
                tool_name=_action_tool(a),
                tool_args=_action_args(a),
                tool_result=result,
                confidence=confidence_for_result(result),
            )
        )
    return chain


def _action_tool(a: Any) -> str:
    if isinstance(a, dict):
        return a.get("tool", "")
    return getattr(a, "tool", "")


def _action_args(a: Any) -> Dict[str, Any]:
    if isinstance(a, dict):
        return a.get("arguments") or {}
    return getattr(a, "arguments", None) or {}


def _action_result(a: Any) -> Dict[str, Any]:
    if isinstance(a, dict):
        return a.get("result") or {}
    return getattr(a, "result", None) or {}