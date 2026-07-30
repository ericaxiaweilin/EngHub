"""Intent Resolver for Chatbot.

Maps user input messages to known tool intents via keyword matching.
Simple NLU prototype suitable for domain-specific factory queries.
"""

from typing import Optional, Dict, Any


class IntentResolver:
    """Resolve natural language input to specific tool intent names."""
    
    # Mapping from intent name to associated keywords/phrases
    _INTENT_KEYWORDS = {
        "query_inventory": ["库存", "inventory", "stock", "存货", "库存量"],
        "get_production_summary": ["产量", "production", "产量总结", "今日产量", "良品率"],
        "query_work_orders": ["工单", "work order", "工单列表", "生产工单", "在制工单"],
        "query_defects": ["不良", "defect", "不良品", "缺陷", "报废"],
        "query_equipment": ["设备", "equipment", "状态", "稼停", "OEE"],
    }
    
    def resolve(self, message_text: str) -> Optional[str]:
        """Parse text and return the most likely intent name.
        
        Args:
            message_text: User's input message content
            
        Returns:
            Intent name (e.g., "query_inventory") if recognized, else None
        """
        if not message_text or not isinstance(message_text, str):
            return None
        
        text_lower = message_text.lower()
        
        # Check each intent's keywords against the message
        for intent, keywords in self._INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    return intent
        
        return None  # No intent matched — falls back to free-form conversation
    
    def extract_parameters(self, intent: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Extract relevant parameters from context for a given intent.
        
        This is a placeholder implementation that would be expanded
        with more sophisticated extraction logic in production.
        """
        params = {}
        
        if intent == "query_inventory":
            params["factory_id"] = context.get("factory_id", "F01")
            # Would extract material_keyword from message text if available
        
        elif intent == "get_production_summary":
            params["factory_id"] = context.get("factory_id", "F01")
        
        elif intent == "query_work_orders":
            params["factory_id"] = context.get("factory_id", "F01")
            params["status"] = context.get("status", "in_progress")
        
        return params