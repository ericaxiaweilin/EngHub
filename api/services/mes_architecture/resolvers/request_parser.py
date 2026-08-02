"""Request Parser Module

Parses raw HTTP query parameters into structured criteria objects.
Separates parameter parsing/validation from business logic.
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass


@dataclass
class WorkOrderQueryCriteria:
    """Structured criteria for work order query."""
    factory_id: str = "F01"  # Default to main factory
    status: Optional[str] = None
    product_id: Optional[str] = None
    page: int = 1
    size: int = 10
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for use in repository queries."""
        return {
            "factory_id": self.factory_id,
            "status": self.status,
            "product_id": self.product_id,
            "page": self.page,
            "size": self.size,
        }


class MESRequestParser:
    """Parse incoming request parameters into structured criteria.
    
    Responsibility: Convert raw HTTP query params → structured criteria objects.
    Does NOT validate business rules (e.g., whether factory exists).
    Only handles structure and type conversion.
    """
    
    @staticmethod
    def parse_work_order_query(params: Dict[str, Any]) -> WorkOrderQueryCriteria:
        """Parse work order query parameters.
        
        Args:
            params: Dictionary of HTTP query parameters
            
        Returns:
            WorkOrderQueryCriteria with validated/converted values
        """
        # Extract and convert parameters safely
        try:
            factory_id = str(params.get("factory_id", "F01")).strip() or "F01"
        except (ValueError, AttributeError):
            factory_id = "F01"
        
        try:
            status = params.get("status")
            if status and not isinstance(status, str):
                status = None
        except (ValueError, AttributeError):
            status = None
        
        try:
            product_id = params.get("product_id")
            if product_id and not isinstance(product_id, str):
                product_id = None
        except (ValueError, AttributeError):
            product_id = None
        
        try:
            page = max(1, int(params.get("page", 1)))
        except (ValueError, TypeError):
            page = 1
        
        try:
            size = max(1, min(100, int(params.get("size", 10))))  # Cap at 100 to prevent large requests
        except (ValueError, TypeError):
            size = 10
        
        return WorkOrderQueryCriteria(
            factory_id=factory_id,
            status=status,
            product_id=product_id,
            page=page,
            size=size
        )