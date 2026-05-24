"""
业务数据加载器
负责从 MES 各业务模块加载数据并转换为统一 SearchDocument 格式
"""

from datetime import datetime, timedelta
from typing import Optional
import random

from .models import (
    SearchDocument, SearchEntityType, SearchResultLink,
    SearchAction, RelatedContext, ROUTE_MAPPING
)


class BusinessDataLoader:
    """业务数据加载器"""
    
    def __init__(self, base_url: str = "http://localhost:3000"):
        self.base_url = base_url
    
    def create_work_order_document(
        self,
        work_order_id: str,
        title: str,
        product_name: str,
        quantity: int,
        status: str,
        priority: str,
        station_id: Optional[str] = None,
        station_name: Optional[str] = None,
        owner_id: Optional[str] = None,
        owner_name: Optional[str] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> SearchDocument:
        """创建工单搜索文档"""
        now = datetime.now()
        
        content = f"""
        工单编号：{work_order_id}
        产品名称：{product_name}
        计划数量：{quantity}
        当前状态：{status}
        优先级：{priority}
        工位：{station_name or '未分配'}
        负责人：{owner_name or '未分配'}
        {description or ''}
        """
        
        summary = f"{product_name} x{quantity} - {status}"
        
        link = SearchResultLink(
            entity_type=SearchEntityType.WORK_ORDER,
            entity_id=work_order_id,
            route_path=f"/work-orders/{work_order_id}",
            permalink=f"{self.base_url}/work-orders/{work_order_id}",
            breadcrumb=["生产", "工单管理", work_order_id]
        )
        
        actions = [
            SearchAction(
                action_type="view",
                label="查看详情",
                url=f"/api/v1/work-orders/{work_order_id}",
                icon="eye"
            ),
        ]
        
        if status == 'pending':
            actions.append(SearchAction(
                action_type="start",
                label="开始生产",
                url=f"/api/v1/work-orders/{work_order_id}/start",
                method="POST",
                requires_confirmation=True,
                icon="play"
            ))
        elif status == 'in_progress':
            actions.append(SearchAction(
                action_type="report",
                label="报工",
                url=f"/api/v1/work-orders/{work_order_id}/report",
                method="POST",
                icon="check"
            ))
        
        # 关联上下文
        related_context = []
        if station_id:
            related_context.append(RelatedContext(
                type="related",
                entity_type=SearchEntityType.STATION,
                entity_id=station_id,
                title=station_name or f"工位 {station_id}",
                summary=f"当前工位",
                link=SearchResultLink(
                    entity_type=SearchEntityType.STATION,
                    entity_id=station_id,
                    route_path=f"/stations/{station_id}",
                    permalink=f"{self.base_url}/stations/{station_id}",
                    breadcrumb=["生产", "工位管理", station_id]
                )
            ))
        
        return SearchDocument(
            id=f"work_order:{work_order_id}",
            entity_type=SearchEntityType.WORK_ORDER,
            title=f"{work_order_id} - {title}",
            content=content.strip(),
            summary=summary,
            created_at=created_at or now - timedelta(days=random.randint(1, 30)),
            updated_at=updated_at or now,
            owner_id=owner_id,
            owner_name=owner_name,
            status=status,
            priority=priority,
            tags=tags or [product_name, status],
            category="production",
            link=link,
            actions=actions,
            related_context=related_context,
            required_permissions=["work_order:view"],
            acl_roles=["operator", "supervisor", "manager"],
            metadata={
                "product_name": product_name,
                "quantity": quantity,
                "station_id": station_id,
            },
            search_boost=1.2 if priority == "high" else 1.0
        )
    
    def create_device_document(
        self,
        device_id: str,
        name: str,
        model: str,
        status: str,
        location: str,
        oee: Optional[float] = None,
        last_maintenance: Optional[datetime] = None,
        next_maintenance: Optional[datetime] = None,
        description: Optional[str] = None,
    ) -> SearchDocument:
        """创建设备搜索文档"""
        now = datetime.now()
        
        content = f"""
        设备编号：{device_id}
        设备名称：{name}
        型号：{model}
        当前位置：{location}
        运行状态：{status}
        OEE: {oee or 'N/A'}%
        上次维护：{last_maintenance.strftime('%Y-%m-%d') if last_maintenance else '无记录'}
        下次维护：{next_maintenance.strftime('%Y-%m-%d') if next_maintenance else '未计划'}
        {description or ''}
        """
        
        summary = f"{name} ({model}) - {status}"
        if oee:
            summary += f" - OEE: {oee:.1f}%"
        
        link = SearchResultLink(
            entity_type=SearchEntityType.DEVICE,
            entity_id=device_id,
            route_path=f"/devices/{device_id}",
            permalink=f"{self.base_url}/devices/{device_id}",
            breadcrumb=["设备", "设备管理", device_id]
        )
        
        actions = [
            SearchAction(
                action_type="view",
                label="查看详情",
                url=f"/api/v1/devices/{device_id}",
                icon="eye"
            ),
        ]
        
        if status == 'running':
            actions.append(SearchAction(
                action_type="stop",
                label="停止设备",
                url=f"/api/v1/devices/{device_id}/stop",
                method="POST",
                requires_confirmation=True,
                icon="stop"
            ))
        elif status == 'stopped':
            actions.append(SearchAction(
                action_type="start",
                label="启动设备",
                url=f"/api/v1/devices/{device_id}/start",
                method="POST",
                icon="play"
            ))
        
        return SearchDocument(
            id=f"device:{device_id}",
            entity_type=SearchEntityType.DEVICE,
            title=f"{device_id} - {name}",
            content=content.strip(),
            summary=summary,
            created_at=now - timedelta(days=365),
            updated_at=now,
            status=status,
            tags=[model, location, status],
            category="equipment",
            link=link,
            actions=actions,
            required_permissions=["device:view"],
            acl_roles=["operator", "maintenance", "supervisor", "manager"],
            metadata={
                "model": model,
                "location": location,
                "oee": oee,
                "last_maintenance": last_maintenance.isoformat() if last_maintenance else None,
                "next_maintenance": next_maintenance.isoformat() if next_maintenance else None,
            },
            search_boost=1.3 if status == 'fault' else 1.0
        )
    
    def create_sop_document(
        self,
        sop_id: str,
        title: str,
        category: str,
        version: str,
        status: str,
        content_text: str,
        author: Optional[str] = None,
        effective_date: Optional[datetime] = None,
    ) -> SearchDocument:
        """创建 SOP 搜索文档"""
        now = datetime.now()
        
        link = SearchResultLink(
            entity_type=SearchEntityType.SOP,
            entity_id=sop_id,
            route_path=f"/sop/{sop_id}",
            permalink=f"{self.base_url}/sop/{sop_id}",
            breadcrumb=["知识", "SOP", sop_id]
        )
        
        return SearchDocument(
            id=f"sop:{sop_id}",
            entity_type=SearchEntityType.SOP,
            title=f"[{version}] {title}",
            content=f"SOP 编号：{sop_id}\n分类：{category}\n版本：{version}\n\n{content_text}",
            summary=f"{category} - {version} - {status}",
            created_at=effective_date or now - timedelta(days=60),
            updated_at=now,
            owner_name=author,
            status=status,
            tags=[category, version],
            category=category,
            link=link,
            actions=[
                SearchAction(
                    action_type="view",
                    label="查看 SOP",
                    url=f"/api/v1/sop/{sop_id}",
                    icon="document"
                ),
            ],
            required_permissions=["sop:view"],
            acl_roles=["operator", "supervisor", "manager", "qa"],
            metadata={
                "version": version,
                "category": category,
                "effective_date": effective_date.isoformat() if effective_date else None,
            }
        )
    
    def create_quality_report_document(
        self,
        report_id: str,
        title: str,
        report_type: str,
        status: str,
        defect_count: int,
        yield_rate: float,
        work_order_id: Optional[str] = None,
        inspector: Optional[str] = None,
        description: Optional[str] = None,
    ) -> SearchDocument:
        """创建质量报告搜索文档"""
        now = datetime.now()
        
        content = f"""
        报告编号：{report_id}
        报告类型：{report_type}
        检验状态：{status}
        缺陷数量：{defect_count}
        良率：{yield_rate:.2f}%
        关联工单：{work_order_id or '无'}
        检验员：{inspector or '未指定'}
        {description or ''}
        """
        
        link = SearchResultLink(
            entity_type=SearchEntityType.QUALITY_REPORT,
            entity_id=report_id,
            route_path=f"/quality/{report_id}",
            permalink=f"{self.base_url}/quality/{report_id}",
            breadcrumb=["质量", "检验报告", report_id]
        )
        
        related_context = []
        if work_order_id:
            related_context.append(RelatedContext(
                type="parent",
                entity_type=SearchEntityType.WORK_ORDER,
                entity_id=work_order_id,
                title=f"工单 {work_order_id}",
                summary="关联工单",
                link=SearchResultLink(
                    entity_type=SearchEntityType.WORK_ORDER,
                    entity_id=work_order_id,
                    route_path=f"/work-orders/{work_order_id}",
                    permalink=f"{self.base_url}/work-orders/{work_order_id}",
                    breadcrumb=["生产", "工单管理", work_order_id]
                )
            ))
        
        return SearchDocument(
            id=f"quality:{report_id}",
            entity_type=SearchEntityType.QUALITY_REPORT,
            title=f"{report_id} - {title}",
            content=content.strip(),
            summary=f"{report_type} - 良率{yield_rate:.1f}% - {defect_count}缺陷",
            created_at=now - timedelta(days=random.randint(1, 7)),
            updated_at=now,
            owner_name=inspector,
            status=status,
            tags=[report_type, status],
            category="quality",
            link=link,
            related_context=related_context,
            required_permissions=["quality:view"],
            acl_roles=["qa", "supervisor", "manager"],
            metadata={
                "report_type": report_type,
                "defect_count": defect_count,
                "yield_rate": yield_rate,
                "work_order_id": work_order_id,
            },
            search_boost=1.5 if yield_rate < 95 else 1.0
        )
    
    def create_material_document(
        self,
        material_id: str,
        name: str,
        spec: str,
        quantity: int,
        unit: str,
        location: str,
        status: str,
        supplier: Optional[str] = None,
        expiry_date: Optional[datetime] = None,
    ) -> SearchDocument:
        """创建物料搜索文档"""
        now = datetime.now()
        
        content = f"""
        物料编号：{material_id}
        物料名称：{name}
        规格：{spec}
        库存数量：{quantity} {unit}
        库位：{location}
        状态：{status}
        供应商：{supplier or '未指定'}
        有效期：{expiry_date.strftime('%Y-%m-%d') if expiry_date else '无限制'}
        """
        
        summary = f"{name} - {quantity}{unit} @ {location}"
        
        link = SearchResultLink(
            entity_type=SearchEntityType.MATERIAL,
            entity_id=material_id,
            route_path=f"/materials/{material_id}",
            permalink=f"{self.base_url}/materials/{material_id}",
            breadcrumb=["仓库", "物料管理", material_id]
        )
        
        is_expiring_soon = expiry_date and (expiry_date - now).days < 30
        
        return SearchDocument(
            id=f"material:{material_id}",
            entity_type=SearchEntityType.MATERIAL,
            title=f"{material_id} - {name}",
            content=content.strip(),
            summary=summary,
            created_at=now - timedelta(days=90),
            updated_at=now,
            status=status,
            tags=[spec, supplier] if supplier else [spec],
            category="inventory",
            link=link,
            actions=[
                SearchAction(
                    action_type="view",
                    label="查看库存",
                    url=f"/api/v1/materials/{material_id}",
                    icon="eye"
                ),
            ],
            required_permissions=["material:view"],
            acl_roles=["warehouse", "operator", "supervisor", "manager"],
            metadata={
                "spec": spec,
                "quantity": quantity,
                "unit": unit,
                "location": location,
                "supplier": supplier,
                "expiry_date": expiry_date.isoformat() if expiry_date else None,
            },
            search_boost=1.5 if is_expiring_soon else 1.0
        )


# 全局加载器实例
_loader: Optional[BusinessDataLoader] = None


def get_data_loader(base_url: str = "http://localhost:3000") -> BusinessDataLoader:
    """获取数据加载器单例"""
    global _loader
    if _loader is None:
        _loader = BusinessDataLoader(base_url)
    return _loader
