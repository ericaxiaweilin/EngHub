"""Factory Resolver for Chatbot.

Determines the factory context for a chat request, checking:
1. Request header x-factory-id (highest priority for tenant switching)
2. User's active_factory_id attribute
3. User's factory_id attribute  
4. Default F01
"""


class FactoryResolver:
    """Resolve factory ID from various sources with configurable priority."""
    
    def resolve(self, http_request=None, current_user=None) -> str:
        """Resolve the effective factory ID for this request/user combination.
        
        Args:
            http_request: FastAPI request object (optional, for header access)
            current_user: Current authenticated user object (optional)
            
        Returns:
            Factory ID string (e.g., "F01", "FAC_MECH_001")
        """
        # Check request header first (tenant switching has highest priority)
        if http_request is not None:
            try:
                headers = getattr(http_request, "headers", {})
                header_val = headers.get("x-factory-id", "")
                if header_val and str(header_val).strip():
                    return str(header_val).strip()
            except Exception:
                pass  # Ignore errors accessing headers
        
        # Check user's active factory
        if current_user is not None:
            try:
                if hasattr(current_user, "active_factory_id"):
                    val = current_user.active_factory_id
                    if val and str(val).strip():
                        return str(val).strip()
                elif hasattr(current_user, "factory_id"):
                    val = current_user.factory_id
                    if val and str(val).strip():
                        return str(val).strip()
            except Exception:
                pass
        
        # Default factory
        return "F01"