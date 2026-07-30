"""ERP 集成框架 - 基础抽象类与接口定义"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ERPConfig:
    """ERP 系统配置类"""
    
    def __init__(self, 
                 erp_type: str,  # "kingdee" or "sap"
                 base_url: str,
                 api_key: Optional[str] = None,
                 username: Optional[str] = None,
                 password: Optional[str] = None,
                 tenant_id: Optional[str] = None,
                 sync_interval_minutes: int = 5,
                 enabled: bool = True):
        self.erp_type = erp_type
        self.base_url = base_url
        self.api_key = api_key
        self.username = username
        self.password = password
        self.tenant_id = tenant_id
        self.sync_interval_minutes = sync_interval_minutes
        self.enabled = enabled
        
    def is_authenticated(self) -> bool:
        """检查是否已认证"""
        return bool(self.api_key) or (bool(self.username) and bool(self.password))


class ERPSyncException(Exception):
    """ERP 同步异常"""
    pass


class ERPIntegrator(ABC):
    """ERP 集成器抽象基类 - 所有具体适配器必须继承此类"""
    
    def __init__(self, config: ERPConfig):
        self.config = config
        self._validate_config()
        
    @abstractmethod
    def _validate_config(self) -> None:
        """验证配置完整性"""
        pass
    
    @abstractmethod
    def create_customer(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """在 ERP 中创建客户"""
        pass
    
    @abstractmethod
    def get_customer(self, customer_id: str) -> Dict[str, Any]:
        """获取客户信息"""
        pass
    
    @abstractmethod
    def sync_sales_order(self, order_id: str, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """同步销售订单到 ERP"""
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """查询订单状态"""
        pass
    
    @abstractmethod
    def create_production_from_order(self, order_id: str) -> Dict[str, Any]:
        """根据订单创建生产工单"""
        pass
    
    @abstractmethod
    def update_product_cost(self, product_id: str, cost_data: Dict[str, Any]) -> Dict[str, Any]:
        """更新产品成本"""
        pass
    
    @abstractmethod
    def get_financial_summary(self, work_order_id: str) -> Dict[str, Any]:
        """获取工单财务汇总"""
        pass
    
    @abstractmethod
    def sync_inventory(self, item_id: str, quantity_change: int) -> Dict[str, Any]:
        """同步库存变动"""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """断开连接，清理资源"""
        pass
    
    def ping(self) -> bool:
        """测试 ERP 连接是否正常"""
        try:
            # 执行一个简单的健康检查
            self._ping_internal()
            return True
        except Exception as e:
            logger.error(f"ERP ping failed: {e}")
            return False
    
    @abstractmethod
    def _ping_internal(self) -> None:
        """内部 ping 方法，由子类实现"""
        pass


class ERPIntegrationService:
    """ERP 集成服务管理器 - 负责注册和管理多个 ERP 集成器"""
    
    _instances: Dict[str, ERPIntegrator] = {}
    
    @classmethod
    def register(cls, integration_id: str, integrator: ERPIntegrator) -> None:
        """注册 ERP 集成器实例"""
        cls._instances[integration_id] = integrator
        logger.info(f"Registered ERP integration: {integration_id} ({integrator.config.erp_type})")
    
    @classmethod
    def get(cls, integration_id: str) -> Optional[ERPIntegrator]:
        """获取指定 ID 的 ERP 集成器"""
        return cls._instances.get(integration_id)
    
    @classmethod
    def list_all(cls) -> List[str]:
        """列出所有注册的 ERP 集成器"""
        return list(cls._instances.keys())
    
    @classmethod
    def sync_all(cls) -> Dict[str, Any]:
        """同步所有已注册的 ERP 集成器"""
        results = {}
        for instance_id, integrator in cls._instances.items():
            try:
                results[instance_id] = integrator.ping()
            except Exception as e:
                results[instance_id] = {"error": str(e)}
        return results
