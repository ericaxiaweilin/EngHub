"""
智能体钩子系统（Hook Chain）
============================
参考 Pi Agent 的 beforeToolCall / afterToolCall 设计：
- 模型只能"提议"动作，实际执行权在 Runtime
- 钩子链可拦截、修改、阻止任何智能体动作
- 规则引擎驱动，可配置化（不再硬编码刚性边界）

用法：
    hooks = HookChain()
    hooks.add_before("safety_check", safety_hook, priority=10)
    hooks.add_after("audit_log", audit_hook)
    
    result = await hooks.run_before(action_context)
    if result.blocked:
        # 动作被拦截，不执行
        ...
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional
from enum import Enum

_logger = logging.getLogger("agent_hooks")


class HookPhase(str, Enum):
    BEFORE = "before"
    AFTER = "after"


@dataclass
class ActionContext:
    """动作上下文（传入钩子链）"""
    agent_key: str
    factory_id: str
    action_type: str           # 动作类型：create_order / send_notification / adjust_schedule ...
    params: Dict[str, Any] = field(default_factory=dict)
    task_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HookResult:
    """钩子执行结果"""
    blocked: bool = False
    reason: str = ""
    modified_params: Optional[Dict[str, Any]] = None  # 修改后的参数（None=不修改）
    details: Dict[str, Any] = field(default_factory=dict)


# 钩子函数签名：async (context) -> HookResult
HookFn = Callable[[ActionContext], Coroutine[Any, Any, HookResult]]


@dataclass
class _HookEntry:
    name: str
    fn: HookFn
    priority: int  # 越小越先执行
    enabled: bool = True


class HookChain:
    """
    钩子链（拦截器链）
    
    设计原则：
    - before 钩子：在动作执行前运行，可阻止/修改
    - after 钩子：在动作执行后运行，可审计/补充
    - 优先级：数字越小越先执行（安全钩子 priority=1）
    - 短路：第一个 block=True 的 before 钩子立即终止链
    """

    def __init__(self):
        self._before_hooks: List[_HookEntry] = []
        self._after_hooks: List[_HookEntry] = []

    def add_before(self, name: str, fn: HookFn, priority: int = 50, enabled: bool = True):
        """注册前置钩子"""
        self._before_hooks.append(_HookEntry(name=name, fn=fn, priority=priority, enabled=enabled))
        self._before_hooks.sort(key=lambda h: h.priority)

    def add_after(self, name: str, fn: HookFn, priority: int = 50, enabled: bool = True):
        """注册后置钩子"""
        self._after_hooks.append(_HookEntry(name=name, fn=fn, priority=priority, enabled=enabled))
        self._after_hooks.sort(key=lambda h: h.priority)

    def remove(self, name: str):
        """移除钩子"""
        self._before_hooks = [h for h in self._before_hooks if h.name != name]
        self._after_hooks = [h for h in self._after_hooks if h.name != name]

    def enable(self, name: str, enabled: bool = True):
        """启用/禁用钩子"""
        for h in self._before_hooks + self._after_hooks:
            if h.name == name:
                h.enabled = enabled

    async def run_before(self, ctx: ActionContext) -> HookResult:
        """
        执行前置钩子链。
        返回第一个 block=True 的结果，或全部通过后的合并结果。
        """
        merged_details = {}
        for hook in self._before_hooks:
            if not hook.enabled:
                continue
            try:
                result = await hook.fn(ctx)
                merged_details.update(result.details)
                if result.blocked:
                    _logger.info(f"[Hook] BLOCKED by '{hook.name}': {result.reason}")
                    result.details = merged_details
                    return result
                if result.modified_params is not None:
                    ctx.params = result.modified_params
            except Exception as e:
                _logger.warning(f"[Hook] '{hook.name}' error: {e}")
                # 钩子异常不阻断执行（fail-open）
        return HookResult(blocked=False, details=merged_details)

    async def run_after(self, ctx: ActionContext, action_result: Any = None) -> HookResult:
        """执行后置钩子链（审计/通知/补充）"""
        merged_details = {}
        for hook in self._after_hooks:
            if not hook.enabled:
                continue
            try:
                ctx.metadata["action_result"] = action_result
                result = await hook.fn(ctx)
                merged_details.update(result.details)
            except Exception as e:
                _logger.warning(f"[Hook:after] '{hook.name}' error: {e}")
        return HookResult(blocked=False, details=merged_details)

    @property
    def registered_hooks(self) -> Dict[str, List[Dict]]:
        """列出所有已注册钩子"""
        return {
            "before": [{"name": h.name, "priority": h.priority, "enabled": h.enabled} for h in self._before_hooks],
            "after": [{"name": h.name, "priority": h.priority, "enabled": h.enabled} for h in self._after_hooks],
        }


# ═══════════════════════════════════════════════════════════
# 内置钩子（开箱即用）
# ═══════════════════════════════════════════════════════════

async def safety_boundary_hook(ctx: ActionContext) -> HookResult:
    """
    刚性安全边界钩子（priority=1）
    阻止高风险操作：删除工单、强制关闭质量异常等
    """
    BLOCKED_ACTIONS = {
        "delete_work_order": "禁止智能体删除工单",
        "force_close_quality_issue": "质量异常不允许自动关闭",
        "delete_inventory": "禁止智能体删除库存记录",
        "override_bom": "BOM变更需人工审批",
    }
    if ctx.action_type in BLOCKED_ACTIONS:
        return HookResult(blocked=True, reason=BLOCKED_ACTIONS[ctx.action_type])
    return HookResult(blocked=False)


async def rate_limit_hook(ctx: ActionContext) -> HookResult:
    """
    频率限制钩子（priority=5）
    防止智能体短时间内大量操作
    """
    # 简化实现：通过 metadata 中的计数器判断
    count = ctx.metadata.get("recent_action_count", 0)
    if count > 100:
        return HookResult(
            blocked=True,
            reason=f"频率限制：最近已执行{count}次操作，超过阈值100"
        )
    return HookResult(blocked=False)


async def audit_trail_hook(ctx: ActionContext) -> HookResult:
    """
    审计日志钩子（after，priority=1）
    记录每次动作到审计链
    """
    _logger.info(
        f"[Audit] agent={ctx.agent_key} action={ctx.action_type} "
        f"factory={ctx.factory_id} params_keys={list(ctx.params.keys())}"
    )
    return HookResult(blocked=False, details={"audited": True})


def create_default_hook_chain() -> HookChain:
    """创建默认钩子链（安全边界 + 频率限制 + 审计）"""
    chain = HookChain()
    chain.add_before("safety_boundary", safety_boundary_hook, priority=1)
    chain.add_before("rate_limit", rate_limit_hook, priority=5)
    chain.add_after("audit_trail", audit_trail_hook, priority=1)
    return chain
