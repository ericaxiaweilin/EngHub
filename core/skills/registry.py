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
    """分层技能注册表（单例，DSH ScopedLayers 对齐）。

    - 分层：global 层 + 每个 scope 一层（scope 用 factory_id / agent_key）。
      注册调用可指定 scope，默认落入 global 层。
    - nearest-wins：读取时按 scope 链从最近层向外找，最近层同名覆盖外层；
      同一层内仍按注册顺序覆盖（最后注册的 Skill 生效）。
      跨层不做 rank 池化，保证组合行为由作者决定。
    - 缓存：按 scope 链 + revision 计数键控（跨会话 recompose 可见）。

    用法:
        registry = SkillRegistry.get_instance()
        registry.register(WorkOrderSkill())            # global 层
        registry.register(factory_skill, scope="F02")  # factory 层
        registry.autodiscover()
    """

    _instance: Optional["SkillRegistry"] = None
    GLOBAL = ""  # scope key 约定：空串 = global 层

    def __init__(self) -> None:
        # scope_key -> {skill_name: skill}
        self._layers: Dict[str, Dict[str, BaseSkill]] = {self.GLOBAL: {}}
        # scope_key -> {tool_name: skill_name}
        self._tool_to_skill: Dict[str, Dict[str, str]] = {self.GLOBAL: {}}
        self._revision = 0
        self._cache: Dict[str, Any] = {}

    @classmethod
    def get_instance(cls) -> "SkillRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── 注册 ──

    def register(self, skill: BaseSkill, *, scope: Optional[str] = None) -> None:
        """把技能注册到指定层（默认 global）。同层内按注册顺序覆盖。"""
        if not isinstance(skill, BaseSkill):
            raise TypeError("skill 必须是 BaseSkill 子类实例")
        layer = self._scope_key(scope)
        layer_skills = self._layers.setdefault(layer, {})
        layer_tools = self._tool_to_skill.setdefault(layer, {})
        name = skill.name
        existing = layer_skills.get(name)
        if existing is not None and existing is not skill:
            # 跨层 shadowing 静默；同层内 loser 记日志（DSH 约定）
            _logger.warning("skill %s 在同一层被覆盖注册", name)
        layer_skills[name] = skill
        for tool in skill.tool_names():
            layer_tools[tool] = name
        self._revision += 1
        self._cache.clear()

    def register_many(self, skills: List[BaseSkill], *, scope: Optional[str] = None) -> None:
        for skill in skills:
            self.register(skill, scope=scope)

    def _scope_key(self, scope: Optional[str]) -> str:
        key = (scope or "").strip()
        return key if key else self.GLOBAL

    # ── 查询（按 scope 链 nearest-wins）──

    def _visible_scope_keys(self, scope: Optional[str] = None) -> List[str]:
        """scope 链：最近层在前，global 层殿后（去重）。"""
        keys: List[str] = []
        key = self._scope_key(scope)
        if key != self.GLOBAL and key not in keys:
            keys.append(key)
        if self.GLOBAL not in keys:
            keys.append(self.GLOBAL)
        return keys

    def get(self, name: str, *, scope: Optional[str] = None) -> Optional[BaseSkill]:
        for key in self._visible_scope_keys(scope):
            skill = self._layers.get(key, {}).get(name)
            if skill is not None:
                return skill
        return None

    def get_skill_for_tool(self, tool_name: str, *, scope: Optional[str] = None) -> Optional[BaseSkill]:
        for key in self._visible_scope_keys(scope):
            skill_name = self._tool_to_skill.get(key, {}).get(tool_name)
            if skill_name:
                skill = self._layers.get(key, {}).get(skill_name)
                if skill is not None:
                    return skill
        return None

    def has_tool(self, tool_name: str, *, scope: Optional[str] = None) -> bool:
        return any(
            tool_name in self._tool_to_skill.get(key, {})
            for key in self._visible_scope_keys(scope)
        )

    def has_skill(self, name: str, *, scope: Optional[str] = None) -> bool:
        return self.get(name, scope=scope) is not None

    def get_all(self, *, scope: Optional[str] = None) -> List[BaseSkill]:
        seen: Dict[str, BaseSkill] = {}
        for key in reversed(self._visible_scope_keys(scope)):
            seen.update(self._layers.get(key, {}))
        return list(seen.values())

    def all_tool_definitions(self, *, scope: Optional[str] = None) -> List[Dict[str, Any]]:
        """聚合可见层的 OpenAI 工具定义并按工具名去重（最近层覆盖外层）。

        Compatibility Skill 先注册完整目录，已迁移领域 Skill 后注册并
        覆盖执行映射；工具描述以最近层 Skill 为准。
        """
        by_name: Dict[str, Dict[str, Any]] = {}
        # 从最外层向最近层填充：近层覆盖远层
        for key in reversed(self._visible_scope_keys(scope)):
            for skill in self._layers.get(key, {}).values():
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
        """执行工具（scope 由调用方以 factory_id 给出）。skill 返回
        LEGACY_FALLBACK 哨兵时原样透出，由调用方回退。"""
        skill = self.get_skill_for_tool(tool_name, scope=factory_id)
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

    def autodiscover(self, base_path: Optional[str] = None, *, scope: Optional[str] = None) -> int:
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
                self._import_skill_package(child.name, scope=scope)
                imported += 1
            except Exception as exc:  # noqa: BLE001
                _logger.warning("自动发现技能 %s 失败: %s", child.name, exc)
        return imported

    def _import_skill_package(self, package_name: str, *, scope: Optional[str] = None) -> Optional[BaseSkill]:
        """import core.skills.<package_name>.skill，取模块级 SKILL 实例。"""
        module = importlib.import_module(f"core.skills.{package_name}.skill")
        skill = getattr(module, "SKILL", None)
        if isinstance(skill, BaseSkill):
            self.register(skill, scope=scope)
            return skill
        build = getattr(module, "build_skill", None)
        if callable(build):
            skill = build()
            if isinstance(skill, BaseSkill):
                self.register(skill, scope=scope)
                return skill
        return None

    @classmethod
    def reset(cls) -> None:
        """仅测试用：清空全部注册。"""
        inst = cls._instance
        if inst is not None:
            inst._layers = {cls.GLOBAL: {}}
            inst._tool_to_skill = {cls.GLOBAL: {}}
            inst._revision = 0
            inst._cache.clear()
