"""Factory Resolver Module

Resolves factory ID from various sources: request headers, user context, defaults.
This is a simple resolver for MES operations - the same pattern used in chatbot."""

from typing import Optional, Any


class FactoryResolver:
    """Determines the active factory for a given request/context.
    
    Priority order:
    1. Request header 'x-factory-id' (if provided)
    2. User's active_factory_id from session/auth
    3. User's default factory_id from user record
    4. Global default ('F01')
    """
    
    def resolve(self, http_request_object: Optional[Any] = None, 
                current_user: Optional[Any] = None) -> str:
        """Resolve the factory ID.
        
        Args:
            http_request_object: FastAPI request object (optional)
            current_user: Current authenticated user object (optional)
        
        Returns:
            The resolved factory ID string
        """
        # Check request header first (highest priority for tenant switching)
        if http_request_object is not None:
            try:
                # Try to get header from request object
                header_val = getattr(http_request_object, "headers", {}).get("x-factory-id")
                if header_val and str(header_val).strip():
                    return str(header_val).strip()
            except Exception:
                pass  # Ignore errors accessing headers
        
        # Check user's active factory
        if current_user is not None:
            try:
                # Try to access active_factory_id attribute
                if hasattr(current_user, "active_factory_id"):
                    val = current_user.active_factory_id
                    if val and str(val).strip():
                        return str(val).strip()
                # Fallback to regular factory_id attribute
                elif hasattr(current_user, "factory_id"):
                    val = current_user.factory_id
                    if val and str(val).strip():
                        return str(val).strip()
            except Exception:
                pass
        
        # Default factory
        return "F01"