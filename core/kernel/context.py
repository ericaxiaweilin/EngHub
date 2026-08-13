"""KernelContext - 请求上下文载体。

Phase 1: 最小可运行骨架。
汇聚一次 Chat V2 请求的全部输入与执行期状态，供 Agent Loop / Permission /
Checkpoint / Telemetry 等 Kernel 组件读取与写入。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class KernelContext:
    """一次 Chat V2 请求的不可变输入 + 可变执行期状态。

    - 输入侧（构造时写入，不修改）：factory_id / user / messages / attachments /
      model route / 权限集 / 会话id
    - 执行期中可变：actions / tool_results / messages 增长
    """

    # ── 输入侧 ──
    request_id: str
    factory_id: str
    user: Any
    messages: List[Dict[str, Any]]
    model_route: Dict[str, Any]

    # ── 可选输入 ──
    session_id: Optional[str] = None
    attachments: Optional[List[Any]] = None
    enable_tools: bool = True
    agent_key: Optional[str] = None
    temperature: float = 0.3
    permissions: set = field(default_factory=set)
    operator: str = ""

    # ── 执行期中可变（Agent Loop 填充）──
    actions: List[Any] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    checkpoint_key: Optional[str] = None

    # ── 元数据（Telemetry / hooks 可写）──
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def last_user_content(self) -> str:
        """取最后一条用户纯文本（仅 content 为 str 时）。"""
        for msg in reversed(self.messages):
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                text = "".join(texts)
                if text:
                    return text
        return ""

    def snapshot(self) -> Dict[str, Any]:
        """当前上下文的可序列化快照（Checkpoint 用）。"""
        return {
            "request_id": self.request_id,
            "factory_id": self.factory_id,
            "session_id": self.session_id,
            "operator": self.operator,
            "agent_key": self.agent_key,
            "enable_tools": self.enable_tools,
            "temperature": self.temperature,
            "message_count": len(self.messages),
            "actions_count": len(self.actions),
            "tool_calls_executed": [a.tool for a in self.actions],
            "model_route": {
                "task_id": self.model_route.get("task_id"),
                "provider": self.model_route.get("provider"),
                "gateway_model": self.model_route.get("gateway_model"),
            },
            "metadata": dict(self.metadata),
        }