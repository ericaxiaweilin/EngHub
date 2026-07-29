"""Intent Resolver Module (MES Context)

Maps user input or operation context to intended mes operations.
Note: This is a simplified version adapted from the chatbot intent resolver,
focused on MES-specific intents rather than general conversational intents.
"""

from typing import Optional, Dict, Any


class IntentResolver:
    """Determines the intended MES operation from request context.
    
    For MES, intents are more structured - typically determined by the
    API endpoint called rather than natural language parsing. This class
    provides a placeholder that could be extended for future NLP features.
    """
    
    def resolve(self, context: Dict[str, Any]) -> Optional[str]:
        """Resolve the intent from context.
        
        Args:
            context: Request context containing operation info
            
        Returns:
            String name of resolved intent (e.g., "list_work_orders", 
            "update_status", "create_report") or None if ambiguous
        """
        # In pure MES API context, the intent is often implicit in the route/method
        # This method could be expanded with NLP if chatbot-like interface is needed
        
        op_type = context.get("op_type", "") or context.get("operation", "")
        
        intent_map = {
            "get": "list_work_orders",
            "query": "list_work_orders",
            "post_create": "create_production_report",
            "post_update": "update_work_order_status",
            "patch": "update_work_order_status",
            "put": "update_work_order_status",
        }
        
        return intent_map.get(op_type.lower())