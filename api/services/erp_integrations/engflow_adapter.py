"""EngFlow Project Adapter - Generic HTTP/REST Integration"""

import requests
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime, timedelta
from base import ERPIntegrator, ERPConfig, ERPSyncException
import base64

logger = logging.getLogger(__name__)


class EngFlowAdapter(ERPIntegrator):
    """EngFlow 项目系统适配器
    
    这是一个通用的 RESTful HTTP 适配器，适用于任何支持 JSON API 的项目管理系统。
    您可以根据实际的 API 文档修改具体的端点路径和认证方式。
    
    假设的 EngFlow API:
      GET    /api/v1/projects         - 获取项目列表
      GET    /api/v1/projects/{id}    - 获取单个项目
      POST   /api/v1/bom              - 获取物料清单
      GET    /api/v1/bom/{item_id}    - 获取特定物料的 BOM
      PUT    /api/v1/work-orders/{id}/sync - 同步工单到 EngFlow
    """
    
    def __init__(self, config: ERPConfig):
        super().__init__(config)
        if config.erp_type != "engflow":
            raise ValueError("EngFlowAdapter only supports engflow type")
        
        self.timeout = getattr(config, 'timeout', 30)
        self.verify_ssl = getattr(config, 'verify_ssl', True)
        
    def _validate_config(self) -> None:
        if not self.config.base_url.endswith("/"):
            raise ERPSyncException("EngFlow: base_url must end with '/'")
        if not hasattr(self.config, 'token') and not (self.config.username and self.config.password):
            raise ERPSyncException("EngFlow: Either token or username/password required")
    
    def _get_auth_headers(self) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        
        if hasattr(self.config, 'token') and self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        elif self.config.username and self.config.password:
            credentials = f"{self.config.username}:{self.config.password}"
            headers["Authorization"] = f"Basic {base64.b64encode(credentials.encode()).decode()}"
        
        return headers
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.config.base_url}{endpoint.lstrip('/')}"
        headers = self._get_auth_headers()
        kwargs.setdefault('headers', {})
        kwargs['headers'].update(headers)
        kwargs.setdefault('timeout', self.timeout)
        kwargs.setdefault('verify', self.verify_ssl)
        
        try:
            response = requests.request(method, url, **kwargs)
            response.raise_for_status()
            
            try:
                return response.json()
            except:
                return {"raw": response.text, "status_code": response.status_code}
        except requests.exceptions.RequestException as e:
            logger.error(f"EngFlow API request failed: {e}")
            raise ERPSyncException(f"API request error: {str(e)}")
    
    def _ping_internal(self) -> None:
        try:
            result = self._make_request("GET", "/api/v1/projects")
            if not isinstance(result, list):
                raise ERPSyncException("Unexpected response format from EngFlow")
        except Exception as e:
            try:
                result = self._make_request("HEAD", "/api/ping")
            except:
                self._make_request("GET", "/")
    
    def get_project_list(self) -> List[Dict[str, Any]]:
        try:
            return self._make_request("GET", "/api/v1/projects")
        except ERPSyncException as e:
            logger.error("Failed to get project list from EngFlow")
            raise
    
    def get_project_details(self, project_id: str) -> Dict[str, Any]:
        try:
            return self._make_request("GET", f"/api/v1/projects/{project_id}")
        except ERPSyncException as e:
            logger.error(f"Failed to get project details for {project_id}")
            raise
    
    def get_bom_for_product(self, product_id: str) -> Dict[str, Any]:
        try:
            return self._make_request("GET", f"/api/v1/bom/{product_id}")
        except ERPSyncException as e:
            logger.error(f"Failed to get BOM for product {product_id}")
            raise
    
    def sync_work_order_to_engflow(self, work_order_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self._make_request("POST", "/api/v1/work-orders/sync", json=work_order_data)
        except ERPSyncException as e:
            logger.error("Failed to sync work order to EngFlow")
            raise
    
    # ERPIntegrator 接口实现
    def create_customer(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._make_request("POST", "/api/v1/customers", json=customer_data)
    
    def get_customer(self, customer_id: str) -> Dict[str, Any]:
        return self._make_request("GET", f"/api/v1/customers/{customer_id}")
    
    def sync_sales_order(self, order_id: str, order_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._make_request("PUT", f"/api/v1/sales-orders/{order_id}", json=order_data)
    
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        return self._make_request("GET", f"/api/v1/sales-orders/{order_id}/status")
    
    def create_production_from_order(self, order_id: str) -> Dict[str, Any]:
        return self._make_request("POST", f"/api/v1/orders/{order_id}/production")
    
    def update_product_cost(self, product_id: str, cost_data: Dict[str, Any]) -> Dict[str, Any]:
        return self._make_request("PUT", f"/api/v1/products/{product_id}/cost", json=cost_data)
    
    def get_financial_summary(self, work_order_id: str) -> Dict[str, Any]:
        try:
            return self._make_request("GET", f"/api/v1/work-orders/{work_order_id}/financial")
        except:
            return {"error": "Financial data not available in EngFlow"}
    
    def sync_inventory(self, item_id: str, quantity_change: int) -> Dict[str, Any]:
        return self._make_request("POST", "/api/v1/inventory/update", json={
            "item_id": item_id,
            "change_qty": quantity_change
        })
    
    def disconnect(self) -> None:
        logger.info("EngFlow connection cleared")


def create_engflow_adapter(config: ERPConfig) -> EngFlowAdapter:
    if config.erp_type != "engflow":
        raise ValueError("Expected engflow ERP type")
    return EngFlowAdapter(config)