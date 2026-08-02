"""Vision Fallback Executor.

Handles recovery when vision-capable models fail during image processing.
Strategy: Strip all images from messages, fall back to text-only model, retry.
"""

from typing import Dict, Any
from api.services.chat_architecture.recovery.base import MesRecoveryStrategy, RecoveryResult


class VisionFallbackExecutor(MesRecoveryStrategy):
    """Recover from vision model failure by stripping images and retrying with text model."""
    
    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries
    
    def get_strategy_name(self) -> str:
        return "vision_fallback"
    
    def should_apply(self, context: Dict[str, Any]) -> bool:
        # Trigger when we have image records AND previous attempt failed with vision error
        has_images = context.get("image_records", []) is not None and len(context.get("image_records", [])) > 0
        vision_error = context.get("error", "") and ("vision" in context.get("error", "").lower() or "image" in context.get("error", "").lower())
        attempt = context.get("attempt", 0) < self.max_retries
        
        return has_images and vision_error and attempt
    
    def execute(self, context: Dict[str, Any]) -> RecoveryResult:
        # Create modified context without images
        new_context = context.copy()
        
        # Strip images from messages (simplified)
        messages = new_context.get("payload", {}).get("messages", [])
        filtered_messages = []
        for msg in messages:
            if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                # Keep only text content parts
                text_parts = [c for c in msg["content"] if c.get("type") != "image_url"]
                if text_parts:
                    msg["content"] = text_parts
                    filtered_messages.append(msg)
                else:
                    continue  # Skip message that had only images
            else:
                filtered_messages.append(msg)
        
        new_context["payload"]["messages"] = filtered_messages
        new_context["vision_dropped"] = True
        new_context["attempt"] = context.get("attempt", 0) + 1
        
        return RecoveryResult(
            strategy_name=self.get_strategy_name(),
            applied=True,
            context=new_context,
            message=f"视觉模型失败，已剥离图片重试 ({new_context['attempt']}/{self.max_retries})"
        )