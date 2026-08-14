"""Compatibility Skill — the single boundary for legacy business executors.

All existing Chatbot tools are registered in the new SkillRegistry.  Domain
skills override the tools they have already migrated; the remaining tools use
this explicit compatibility boundary so Kernel no longer has a second hidden
``legacy_execute_tool`` route.  The executor implementation remains unchanged
until each domain is moved into its own Skill.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.skills.base import BaseSkill


class CompatibilitySkill(BaseSkill):
    """Register and execute the not-yet-split tool catalog."""

    @property
    def name(self) -> str:
        return "compatibility"

    @property
    def module(self) -> str:
        return "compatibility"

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        from api.services.chat_tools_service import TOOL_DEFINITIONS

        return list(TOOL_DEFINITIONS)

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
        from api.services.chat_tools_service import execute_tool

        return await execute_tool(
            db,
            tool_name,
            args,
            operator=operator,
            factory_id=factory_id,
        )


SKILL = CompatibilitySkill()


def build_skill() -> BaseSkill:
    return CompatibilitySkill()
