"""Tool Fallback Executor.

Handles recovery when gateway does not support tool calling mode.
Strategy: Remove tools/tool_choice from payload, retry in free-text mode.
"""

from typing import Dict, Any
from api.services.chat_architecture.recovery.base import MesRecoveryStrategy, RecoveryResult


class ToolFallbackExecutor(MesRecoveryStrategy):
    """Recover from tool-support failure by disabling tool mode and retrying as plain conversation."""
    
    def get_strategy_name(self) -> str:
        return "tool_fallback"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        # Trigger when gateway returned error about lacking tool support
        has_tool_mode = context.get("payload", {}).get("tools") is not None and len(context.get("payload", {}).get("tools", [])) > 0
        tool_error = context.get("error", "") and ("tool" in context.get("error", "").lower() or "function" in context.get("error", "").lower())
        
        return has_tool_mode and tool_error
    
    def execute(self, context: Dict[str, Any]) -> RecoveryResult:
        new_context = context.copy()
        
        # Remove tools and tool_choice from payload
        payload = new_context.setdefault("payload", {})
        payload.pop("tools", None)
        payload.pop("tool_choice", None)
        
        new_context["tool_mode_disabled"] = True
        
        return RecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=True,
            context=new_context,
            message="工具模式不被支持，已切换为纯文本对话模式"
        )