"""ERP 集成使用示例 - Kingdee 与 SAP"""

from api.services.erp_integrations import (
    ERPConfig,
    register_erp_config,
    get_erp_instance,
    test_all_erps,
    list_registered_erps,
)


def configure_kingdee_example():
    """配置 Kingdee ERP 集成示例"""
    
    # 方案 A: API Key 认证（推荐用于 Cloud 版本）
    kingdee_config = ERPConfig(
        erp_type="kingdee",
        base_url="https://openapi.kingdee.com/api/",
        api_key="YOUR_APP_KEY",
        app_secret="YOUR_APP_SECRET",  # ERPConfig 的额外属性
        tenant_id="YOUR_TENANT_ID",
        sync_interval_minutes=5,
        enabled=True,
    )
    
    # 注册为 "kingdee_production"
    register_erp_config("kingdee_production", kingdee_config)
    print(f"✓ Kingdee production registered")


def configure_sap_example():
    """配置 SAP ERP 集成示例"""
    
    # 方案 A: 用户名/密码 + OData API（S/4HANA Gateway）
    sap_config = ERPConfig(
        erp_type="sap",
        base_url="https://sapserver.example.com/sap/opu/odata/sap/",
        username="your_username",
        password="your_password",
        client="100",  # SAP Client ID
        sync_interval_minutes=10,
        enabled=True,
    )
    
    # 注册为 "sap_production"
    register_erp_config("sap_production", sap_config)
    print(f"✓ SAP production registered")


def use_erp_instances():
    """示例：如何使用已注册的 ERP 实例"""
    
    # 获取 Kingdee 实例
    kingdee = get_erp_instance("kingdee_production")
    if kingdee and kingdee.ping():
        print("Kingdee connection OK")
        
        # 创建客户
        customer_data = {
            "external_id": "CUST001",
            "name": "ABC 有限公司",
            "city": "深圳市",
            "country_code": "CN",
            "contact": "张三",
            "phone": "13800138000",
        }
        result = kingdee.create_customer(customer_data)
        print(f"Customer created: {result}")
    else:
        print("⚠ Kingdee not available or unreachable")
    
    # 获取 SAP 实例
    sap = get_erp_instance("sap_production")
    if sap and sap.ping():
        print("SAP connection OK")
        
        # 同步销售订单
        order_data = {
            "sales_order": "SO123456",
            "items": [
                {
                    "material": "MAT001",
                    "quantity": 100,
                    "unit": "PCS"
                }
            ]
        }
        result = sap.sync_sales_order("SO123456", order_data)
        print(f"Order synced: {result}")
    else:
        print("⚠ SAP not available or unreachable")


def test_all_connections():
    """测试所有已注册的 ERP 连接"""
    results = test_all_erps()
    print("\n=== ERP 连接状态 ===")
    for status in results.items():
        status_id, test_result = status
        if isinstance(test_result, dict):
            print(f"  {status_id}: {test_result.get('error', 'Unknown error')}")
        else:
            print(f"  {status_id}: {'✅ OK' if test_result else '❌ FAILED'}")


if __name__ == "__main__":
    # 运行示例
    configure_kingdee_example()
    configure_sap_example()
    
    print(f"\n已注册 ERP 实例: {list_registered_erps()}")
    
    use_erp_instances()
    test_all_connections()
