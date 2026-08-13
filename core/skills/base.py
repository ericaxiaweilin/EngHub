"""BaseSkill - 领域技能接口。

一个 Skill 是某个业务域（工单 / 库存 / 质量 ...）的一组工具 + 执行逻辑的最小单元。
- 提供 OpenAI function-calling 格式的工具定义
- 提供工具执行入口，接收 db + 调用上下文
- 提供权限钩子（Phase 4 扩展 ACL）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseSkill(ABC):
    """领域技能基类。

    子类需要提供:
    - name: 技能名（注册键），如 "work_order"
    - module: 所属模块，如 "work_order" | "inventory" | "quality"
    - get_tool_definitions: 本技能的工具定义列表
    - execute: 执行单个工具
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def module(self) -> str:
        return self.name

    @abstractmethod
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """本技能的全部工具定义（OpenAI function-calling 格式）。"""

    @abstractmethod
    async def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        db: Any = None,
        operator: str = "ai_assistant",
        factory_id: Optional[str] = None,
        ctx: Any = None,
    ) -> Dict[str, Any]:
        """执行本技能下的一个工具。

        返回:
            结构化结果 dict。失败时返回 {"error": ...}。
        """

    def tool_names(self) -> List[str]:
        """本技能负责的所有工具名。"""
        return [
            (td.get("function") or {}).get("name")
            for td in self.get_tool_definitions()
            if td.get("function", {}).get("name")
        ]

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in set(self.tool_names())

    def has_permission(self, ctx: Any = None) -> bool:
        """Phase 4 扩展为角色 → 工具 ACL。当前默认放行。"""
        return True