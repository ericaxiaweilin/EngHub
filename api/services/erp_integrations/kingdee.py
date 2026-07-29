"""Kingdee Cloud Star (金蝶云星空) ERP 适配器"""

import requests
from typing import Dict, Any, Optional
import logging
from datetime import datetime
from base import ERPIntegrator, ERPConfig, ERPSyncException

logger = logging.getLogger(__name__)


class KingdeeERP(ERPIntegrator):
    """金云星空 ERP 集成适配器
    
    文档参考: https://openapi.kingdee.com/docs
    API 版本: v3.0
    """
    
    def __init__(self, config: ERPConfig):
        super().__init__(config)
        if config.erp_type != "kingdee":
            raise ValueError("KingdeeERP only supports kingdee erp type")
        self.auth_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        
    def _validate_config(self) -> None:
        if not self.config.api_key:
            raise ERPSyncException("Kingdee: api_key is required")
        if not self.config.base_url.endswith("/"):
            raise ERPSyncException("Kingdee: base_url must end with '/'")
        
    def _authenticate(self) -> str:
        """获取或刷新 auth token"""
        if self.auth_token and self.token_expires_at and datetime.utcnow() < self.token_expires_at:
            return self.auth_token
        
        # 重新认证
        auth_url = f"{self.config.base_url}/api/auth/login"
        payload = {
            "app_key": self.config.api_key,
            "app_secret": getattr(self.config, 'app_secret', ''),
            "timestamp": int(datetime.utcnow().timestamp()),
            "signature_method": "HMAC-SHA256",
            "signature": self._generate_signature()  # 实际实现需要签名逻辑
        }
        
        try:
            response = requests.post(auth_url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            self.auth_token = data.get("access_token")
            # 假设 token 有效期为 1 小时（实际应响应中获取）
            self.token_expires_at = datetime.utcnow() + timedelta(minutes=60)
            logger.info("Successfully authenticated with Kingdee ERP")
            return self.auth_token
        except Exception as e:
            logger.error(f"Kingdee authentication failed: {e}")
            raise ERPSyncException(f"Authentication failed: {str(e)}")
    
    def _generate_signature(self) -> str:
        """生成请求签名 - 简化版，实际需完整实现"""
        # 这里只是占位符，实际需要使用 HMAC-SHA256 按金蝶规范生成
        return "generated_signature_placeholder"
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """发送标准化请求"""
        url = f"{self.config.base_url}{endpoint.lstrip('/')}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._authenticate()}" if self.auth_token else ""
        }
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, **kwargs)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, **kwargs)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=headers, **kwargs)
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=headers, **kwargs)
            else:
                raise ERpsSyncException(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Kingdee API request failed: {e}")
            raise ERpsyncException(f"API request error: {str(e)}")
    
    def _ping_internal(self) -> None:
        """测试连接 - 调用一个简单的 API"""
        self._make_request("GET", "/api/v3/users/me")
    
    def create_customer(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """在 Kingdee ERP 中创建客户"""
        try:
            result = self._make_request("POST", "/api/v3/customers", json=customer_data)
            logger.info(f"Created Kingdee customer: {result.get('id')}")
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Failed to create customer in Kingdee: {e}")
            raise
    
    def get_customer(self, customer_id: str) -> Dict[str, Any]:
        """获取客户信息"""
        result = self._make_request("GET", f"/api/v3/customers/{customer_id}")
        return result
    
    def sync_sales_order(self, order_id: str, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """同步销售订单到 Kingdee ERP"""
        try:
            order_data["external_system_id"] = "enghub"  # 标记来源系统
            result = self._make_request("PUT", f"/api/v3/sales-orders/{order_id}", json=order_data)
            logger.info(f"Synced sales order {order_id} to Kingdee")
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Failed to sync sales order to Kingdee: {e}")
            raise
    
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """查询销售订单状态"""
        result = self._make_request("GET", f"/api/v3/sales-orders/{order_id}/status")
        return result
    
    def create_production_from_order(self, order_id: str) -> Dict[str, Any]:
        """根据 Kingdee 销售订单创建生产工单（模拟调用）"""
        # 实际业务中会调用 Kingdee 的生产计划接口
        logger.info(f"Triggering production creation from order {order_id} in Kingdee")
        return {
            "success": True,
            "message": f"Production order created from sales order {order_id}",
            "work_order_prefix": "KDG-" + order_id[-8:],
            "estimated_start": datetime.utcnow().isoformat()
        }
    
    def update_product_cost(self, product_id: str, cost_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新产品成本"""
        try:
            result = self._make_request("PUT", f"/api/v3/products/{product_id}/cost", json=cost_data)
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Failed to update product cost in Kingdee for {product_id}: {e}")
            raise
    
    def get_financial_summary(self, work_order_id: str) -> Dict[str, Any]:
        """获取工单的财务汇总（收入、成本、利润等）"""
        # 从 Kingdee 的财务模块查询相关数据
        try:
            # 先关联查找工作订单的销售订单号
            wo_data = self._make_request("GET", "/api/v3/work-orders/" + work_order_id)
            sales_order_id = wo_data.get("sales_order_id")
            if sales_order_id:
                order_data = self._make_request("GET", f"/api/v3/sales-orders/{sales_order_id}")
            else:
                order_data = {}
            
            summary = {
                "work_order_id": work_order_id,
                "sales_order_id": sales_order_id,
                "total_amount": order_data.get("amount", 0),
                "currency": order_data.get("currency", "CNY"),
                "status": order_data.get("status", ""),
                "fetch_time": datetime.utcnow().isoformat()
            }
            return summary
        except Exception as e:
            logger.error(f"Failed to get financial summary for WO {work_order_id}: {e}")
            return {"error": str(e)}
    
    def sync_inventory(self, item_id: str, quantity_change: int) -> Dict[str, Any]:
        """同步库存变动（入库/出库）"""
        try:
            result = self._make_request("POST", "/api/v3/inventory/balance", json={
                "item_id": item_id,
                "change_qty": quantity_change,
                "reason_code": "ENG_HUB_SYNC",
                "operator": "system"
            })
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Failed to sync inventory for {item_id}: {e}")
            raise
    
    def disconnect(self) -> None:
        """断开连接，清理资源（金蝶 API 无显式 logout，可可选清除 token）"""
        self.auth_token = None
        self.token_expires_at = None
        logger.info("Kingdee connection cleared")


# ===== 工厂函数 =====

def create_kingdee_integrator(config: ERPConfig) -> KingdeeERP:
    """创建 Kingdee ERP 集成器实例"""
    if config.erp_type != "kingdee":
        raise ValueError("Expected kingdee ERP type")
    return KingdeeERP(config)
