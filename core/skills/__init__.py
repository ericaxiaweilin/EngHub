"""EngFlow Skills — 领域技能层。

技能是 Kernel 的能力来源（Chat V2 链路）。
- base.BaseSkill      技能接口
- registry.SkillRegistry  注册表 / 工具路由 / 自动发现
- work_order / inventory  已迁移的技能
"""

from core.skills.base import BaseSkill
from core.skills.registry import SkillRegistry, LEGACY_FALLBACK, is_legacy_fallback

__all__ = [
    "BaseSkill",
    "SkillRegistry",
    "LEGACY_FALLBACK",
    "is_legacy_fallback",
]