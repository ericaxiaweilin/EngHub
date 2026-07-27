"""ERP 集成模块 - 统一入口"""

from .base import (
    ERPConfig,
    ERPSyncException,
    ERPIntegrator,
    ERPIntegrationService,
)

# 工厂函数
from .kingdee import create_kingdee_integrator
from .sap import create_sap_integrator

# 注册表 - 用于动态加载
ERP_CREATORS = {
    "kingdee": create_kingdee_integrator,
    "sap": create_sap_integrator,
}


def register_erp_config(erp_id: str, config: ERPConfig) -> None:
    """
    注册一个 ERP 系统配置
    
    参数:
        erp_id: 这个 ERP 实例的唯一标识符（如 "kingdee_prod", "sap_dev"）
        config: ERPConfig 实例
    """
    if config.erp_type not in ERP_CREATORS:
        raise ValueError(f"Unsupported ERP type: {config.erp_type}")
    
    integrator = ERP_CREATORS[config.erp_type](config)
    ERPIntegrationService.register(erp_id, integrator)
    logger.info(f"Registered ERP instance '{erp_id}' ({config.erp_type})")


def get_erp_instance(erp_id: str) -> Optional[ERPIntegrator]:
    """
    获取已注册的 ERP 集成器实例
    
    参数:
        erp_id: ERP 实例的 ID
        
    返回:
        ERPIntegrator 实例或 None（如果未找到）
    """
    return ERPIntegrationService.get(erp_id)


def list_registered_erps() -> List[str]:
    """列出所有已注册的 ERP 实例 ID"""
    return ERPIntegrationService.list_all()


def test_all_erps() -> Dict[str, Any]:"""
    测试所有已注册的 ERP 连接状态
    
    返回:
        字典，key 为 ERP ID，value 为测试结果（True/False 或错误信息）
    """
    return ERPIntegrationService.sync_all()
