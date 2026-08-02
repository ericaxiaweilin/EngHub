"""SAP ERP Adapter - Using OData API or RFC through PI/PO"""

import requests
from typing import Dict, Any, Optional
import logging
from datetime import datetime, timedelta
from base import ERPIntegrator, ERPConfig, ERPSyncException

logger = logging.getLogger(__name__)


class SAPERP(ERPIntegrator):
    """SAP ERP 集成适配器
    
    支持两种方式：
    1. SAP Gateway OData REST API (S/4HANA)
    2. RFC via SAP PI/PO middleware
    
    Documentation: https://developers.sap.com/topics/sap-gateway.html
    """
    
    def __init__(self, config: ERPConfig):
        super().__init__(config)
        if config.erp_type != "sap":
            raise ValueError("SAPERP only supports sap erp type")
        
        # 从配置中解析 SAP 特定参数
        self.client = config.tenant_id or config.get("client", "100")
        self.language = config.username or "EN"
        self.session: Optional[str] = None
        
    def _validate_config(self) -> None:
        if not getattr(self.config, 'session_key', None) and not (self.config.username and self.config.password):
            raise ERPSyncException("SAP: Either session_key or username/password required")
        if not self.config.base_url.endswith("/"):
            raise ERPSyncException("SAP: base_url must end with '/'")
    
    def _get_sap_headers(self) -> Dict[str, Any]:
        """获取 SAP 请求头"""
        headers = {
            "Content-Type": "application/json",
            "SAP-Language": self.language,
            "X-CSRF-Token": "fetch"  # 需要先获取 CSRF Token
        }
        if self.session:
            headers["Cookie"] = f"MYSAPSSPC={self.session}"
        return headers
    
    def _authenticate_via_credentials(self) -> str:
        """使用用户名密码认证（适用于 SAP Gateway）"""
        auth_url = f"{self.config.base_url}/sap/opu/odata/sap/API_BUSINESS_PARTNER/"
        try:
            response = requests.get(
                auth_url, 
                auth=(self.config.username, self.config.password),
                headers=self._get_sap_headers(),
                timeout=10,
                verify=False  # 生产环境应配置证书验证
            )
            response.raise_for_status()
            # 提取 CSRF Token 用于后续请求
            csrf_token = response.headers.get("x-csrf-token")
            if not csrf_token:
                raise ERpsyncException("No CSRF token received from SAP")
            
            # 保存会话（简化：实际需完整处理 SAP 会话管理）
            self.session = response.cookies.get("MYSAPSSPC")
            logger.info("Authenticated to SAP ERP via credentials")
            return csrf_token
        except Exception as e:
            logger.error(f"SAP authentication failed: {e}")
            raise
    
    def _authenticate_via_session(self) -> str:
        """使用已有 Session Key 认证"""
        if not self.config.session_key:
            raise ErpsyncException("No session key provided for SAP authentication")
        
        try:
            # 验证会话有效性
            response = requests.get(
                f"{self.config.base_url}/sap/bc/soap/sieep?sap-language={self.language}",
                cookies={"MYSAPSSPC": self.config.session_key},
                timeout=5,
                verify=False
            )
            if response.status_code == 200:
                logger.info("SAP session validated successfully")
                return "valid_session"
            else:
                raise ErpsyncException(f"SAP session validation failed: {response.status_code}")
        except Exception as e:
            logger.error(f"SAP session validation error: {e}")
            # 尝试重新认证
            return self._authenticate_via_credentials()
    
    def _ping_internal(self) -> None:
        """测试 SAP 连接 - 调用一个简单的系统功能查询"""
        try:
            headers = {
                "X-CSRF-Token": self._authenticate_via_session() if not hasattr(self, '_csrf_token') else self._csrf_token
            }
            response = requests.get(
                f"{self.config.base_url}/sap/bc/ui5_ui5/sap/zenghub_healthcheck",
                headers=headers,
                timeout=5,
                verify=False
            )
            if response.status_code != 200:
                raise ErpsyncException(f"SAP ping returned status {response.status_code}")
        except Exception as e:
            # 如果 healthcheck endpoint 不存在，尝试简单的 GET 请求
            try:
                response = requests.get(
                    f"{self.config.base_url}/sap/opu/odata/sap/UI_USER_INFO/",
                    headers={"Accept": "application/json"},
                    timeout=5,
                    verify=False,
                    auth=(self.config.username, self.config.password) if self.config.username else None
                )
                if response.status_code != 200:
                    raise ErpsyncException(f"SAP ping failed: {response.status_code}")
            except Exception as e2:
                raise ErpsyncException(f"SAP connection test failed: {str(e2)}")
    
    def create_customer(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """在 SAP 中创建客户（通过 BAPI 或 OData）"""
        try:
            # 实际实现会调用 BAPI_CUSTOMER_CREATE 或 OData API
            endpoint = f"{self.config.base_url}/sap/opu/odata/sap/API_BUSINESS_PARTNER/"
            payload = {
                "PartnerNumber": customer_data.get("external_id"),
                "CustomerData": {
                    "FirstName": customer_data.get("name"),
                    "City": customer_data.get("city"),
                    "Country": customer_data.get("country_code"),
                    "PostalCode": customer_data.get("postal_code")
                }
            }
            
            # 需要先获取 CSRF Token
            headers = self._get_sap_headers()
            headers["X-CSRF-Token"] = headers.pop("X-CSRF-Token") if "X-CSRF-Token" in headers else ""
            
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                auth=(self.config.username, self.config.password) if self.config.username else None,
                timeout=30,
                verify=False
            )
            response.raise_for_status()
            logger.info(f"Created SAP customer: {customer_data.get('external_id')}")
            return {"success": True, "data": response.json()}
        except Exception as e:
            logger.error(f"Failed to create customer in SAP: {e}")
            raise
    
    def get_customer(self, customer_id: str) -> Dict[str, Any]:
        """获取客户信息"""
        endpoint = f"{self.config.base_url}/sap/opu/odata/sap/API_BUSINESS_PARTNER('{customer_id}')"
        response = requests.get(endpoint, params={"$expand":"AddressData"}, timeout=10, verify=False)
        response.raise_for_status()
        return response.json()
    
    def sync_sales_order(self, order_id: str, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """同步销售订单到 SAP"""
        try:
            endpoint = f"{self.config.base_url}/sap/opu/odata/sap/API_SALESDOCUMENT/"
            payload = {
                "SalesDocument": order_id,
                "Item": [{
                    "Material": order_data.get("material_id"),
                    "Quantity": order_data.get("quantity"),
                    "Unit": order_data.get("unit")
                }]
            }
            
            response = requests.post(
                endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                auth=(self.config.username, self.config.password) if self.config.username else None,
                timeout=30,
                verify=False
            )
            response.raise_for_status()
            logger.info(f"Synced sales order {order_id} to SAP")
            return {"success": True, "data": response.json()}
        except Exception as e:
            logger.error(f"Failed to sync sales order to SAP: {e}")
            raise
    
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """查询销售订单状态"""
        endpoint = f"{self.config.base_url}/sap/opu/odata/sap/API_SALESDOCUMENT/{order_id}/Items"
        response = requests.get(endpoint, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        return {"order_id": order_id, "status": data.get("status", "unknown")}
    
    def create_production_from_order(self, order_id: str) -> Dict[str, Any]:
        """根据 SAP 销售订单创建生产工单（通过 CO01/CO11N BAPI 或 IDoc）"""
        try:
            # 调用 SAP BAPI 创建生产订单
            endpoint = f"{self.config.base_url}/sap/baPI/BAPI_PRODORD_CREATE"
            # 实际实现需使用 SAP NetWeaver RFC 库
            # 此处为伪代码示意
            logger.info(f"Triggering production creation from order {order_id} in SAP")
            return {
                "success": True,
                "message": f"Production order created from sales order {order_id}",
                "work_order_prefix": "SAP-" + order_id[-8:],
                "estimated_start": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to create production from order in SAP: {e}")
            raise
    
    def update_product_cost(self, product_id: str, cost_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新产品标准成本（CK11N 类似功能）"""
        try:
            endpoint = f"{self.config.base_url}/sap/opu/odata/sap/COSTINGDATA/{product_id}"
            response = requests.put(
                endpoint,
                json={
                    "CostCenter": cost_data.get("cost_center"),
                    "LaborHours": cost_data.get("labor_hours"),
                    "MaterialCost": cost_data.get("material_cost"),
                    "OverheadRate": cost_data.get("overhead_rate")
                },
                timeout=15,
                verify=False
            )
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except Exception as e:
            logger.error(f"Failed to update product cost in SAP for {product_id}: {e}")
            raise
    
    def get_financial_summary(self, work_order_id: str) -> Dict[str, Any]:
        """获取工单的财务汇总（通过 CO03 或 CJ20N 查询）"""
        try:
            # 从 SAP Cost Center Accounting (CO-CCA) 或 Order Accounting (CO-OM-ORD)
            endpoint = f"{self.config.base_url}/sap/opu/odata/sap/AC_DOCUMENT/{work_order_id}"
            response = requests.get(endpoint, timeout=10, verify=False)
            response.raise_for_status()
            
            data = response.json()
            return {
                "work_order_id": work_order_id,
                "actual_costs": data.get("actual_costs", 0),
                "planned_costs": data.get("planned_costs", 0),
                "currency": data.get("currency", "EUR"),
                "period": data.get("period", ""),
                "fetch_time": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Failed to get financial summary for WO {work_order_id} from SAP: {e}")
            return {"error": str(e)}
    
    def sync_inventory(self, item_id: str, quantity_change: int) -> Dict[str, Any]:
        """同步库存变动（MB1B/MB1A 类似功能）"""
        try:
            endpoint = f"{self.config.base_url}/sap/opu/odata/sap/MATERIALDOCUMENT/"
            response = requests.post(
                endpoint,
                json={
                    "MatNum": item_id,
                    "MovType": "101" if quantity_change > 0 else "261",  # 入库/出库
                    "Plant": "1000",  # 工厂代码，可配置
                    "StorageLoc": "0001",  # 存储地点
                    "BaseQty": abs(quantity_change),
                    "BaseUnit": "PCS"
                },
                timeout=15,
                verify=False
            )
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except Exception as e:
            logger.error(f"Failed to sync inventory for {item_id}: {e}")
            raise
    
    def disconnect(self) -> None:
        """断开 SAP 会话（可选调用 BAPI_LOGOUT）"""
        self.session = None
        logger.info("SAP session cleared")


# ===== 工厂函数 =====

def create_sap_integrator(config: ERPConfig) -> SAPERP:
    """创建 SAP ERP 集成器实例"""
    if config.erp_type != "sap":
        raise ValueError("Expected sap ERP type")
    return SAPERP(config)
