"""SkillRegistry - 技能注册表。

- 注册：register(skill) / register_many
- 发现：get(name) / get_skill_for_tool(tool_name) / all_tool_definitions
- 执行：execute(tool_name, args, *, db, operator, factory_id, ctx)
  按工具名路由到所属 Skill，未找到返回 {"error": "未知工具"}。
- 兼容边界：所有尚未拆分的工具由 compatibility Skill 显式注册，
  不再由 Kernel 隐式持有第二条 legacy 执行路径。
- 自动发现：autodiscover() 扫描 core/skills/<dir>/skill.py
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.skills.base import BaseSkill

_logger = logging.getLogger("engflow_skills")

# 旧技能在拆分期间仍可返回此哨兵；新入口会把它视为明确的迁移缺口。
LEGACY_FALLBACK = {"_legacy_fallback": True}


def is_legacy_fallback(result: Dict[str, Any]) -> bool:
    return bool(result and result.get("_legacy_fallback"))


class SkillRegistry:
    """全局技能注册表（单例）。

    用法:
        registry = SkillRegistry.get_instance()
        registry.register(WorkOrderSkill())
        registry.autodiscover()
    """

    _instance: Optional["SkillRegistry"] = None

    def __init__(self) -> None:
        self._skills: Dict[str, BaseSkill] = {}
        self._tool_to_skill: Dict[str, str] = {}

    @classmethod
    def get_instance(cls) -> "SkillRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── 注册 ──

    def register(self, skill: BaseSkill) -> None:
        if not isinstance(skill, BaseSkill):
            raise TypeError("skill 必须是 BaseSkill 子类实例")
        name = skill.name
        existing = self._skills.get(name)
        if existing is not None and existing is not skill:
            _logger.warning("skill %s 被覆盖注册", name)
        self._skills[name] = skill
        for tool in skill.tool_names():
            self._tool_to_skill[tool] = name

    def register_many(self, skills: List[BaseSkill]) -> None:
        for skill in skills:
            self.register(skill)

    # ── 查询 ──

    def get(self, name: str) -> Optional[BaseSkill]:
        return self._skills.get(name)

    def get_skill_for_tool(self, tool_name: str) -> Optional[BaseSkill]:
        skill_name = self._tool_to_skill.get(tool_name)
        return self._skills.get(skill_name) if skill_name else None

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._tool_to_skill

    def has_skill(self, name: str) -> bool:
        return name in self._skills

    def get_all(self) -> List[BaseSkill]:
        return list(self._skills.values())

    def all_tool_definitions(self) -> List[Dict[str, Any]]:
        """聚合所有技能的 OpenAI 工具定义并按工具名去重。

        Compatibility Skill 先注册完整目录，已迁移领域 Skill 后注册并
        覆盖执行映射；工具描述也以最后注册的 Skill 为准。
        """
        by_name: Dict[str, Dict[str, Any]] = {}
        for skill in self._skills.values():
            for definition in skill.get_tool_definitions():
                name = (definition.get("function") or {}).get("name")
                if name:
                    by_name[name] = definition
        return list(by_name.values())

    # ── 执行 ──

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
        """执行工具。skill 返回 LEGACY_FALLBACK 哨兵时原样透出，由调用方回退。"""
        skill = self.get_skill_for_tool(tool_name)
        if skill is None:
            return {"error": f"未知工具：{tool_name}"}
        try:
            return await skill.execute(
                tool_name, args,
                db=db, operator=operator, factory_id=factory_id, ctx=ctx,
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": f"工具执行失败：{type(exc).__name__}: {exc}"}

    # ── 发现 ──

    def autodiscover(self, base_path: Optional[str] = None) -> int:
        """扫描并注册 core/skills/<dir>/skill.py 中的模块级 SKILL 变量。

        Returns:
            成功注册的技能数。
        """
        base = Path(base_path) if base_path else Path(__file__).resolve().parent
        if not base.is_dir():
            return 0

        imported = 0
        for child in sorted(base.iterdir()):
            skill_module = child / "skill.py"
            if not skill_module.is_file():
                continue
            try:
                self._import_skill_package(child.name)
                imported += 1
            except Exception as exc:  # noqa: BLE001
                _logger.warning("自动发现技能 %s 失败: %s", child.name, exc)
        return imported

    def _import_skill_package(self, package_name: str) -> Optional[BaseSkill]:
        """import core.skills.<package_name>.skill，取模块级 SKILL 实例。"""
        module = importlib.import_module(f"core.skills.{package_name}.skill")
        skill = getattr(module, "SKILL", None)
        if isinstance(skill, BaseSkill):
            self.register(skill)
            return skill
        build = getattr(module, "build_skill", None)
        if callable(build):
            skill = build()
            if isinstance(skill, BaseSkill):
                self.register(skill)
                return skill
        return None

    @classmethod
    def reset(cls) -> None:
        """仅测试用：清空全部注册。"""
        inst = cls._instance
        if inst is not None:
            inst._skills.clear()
            inst._tool_to_skill.clear()
