"""
MES Service Layer - Production Report, Station, Routing, Equipment Services
生产报工、工位、工艺路线、设备管理服务
"""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import case, select, update, delete
from sqlalchemy.orm import selectinload

from database.models import (
    ProductionReport, 
    ProductionReportComment, 
    Station, 
    Routing, 
    Equipment,
    WorkOrder,
    Product,
    BomItem,
    Inventory,
    APSRequest
)
import asyncio
import logging

_logger = logging.getLogger(__name__)


class ProductionReportService:
    """生产报工服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_report(
        self,
        factory_id: str,
        work_order_id: str,
        station_id: str,
        good_qty: int,
        defect_qty: int = 0,
        scrap_qty: int = 0,
        report_type: str = "normal",
        shift: str = "day",
        operator_id: Optional[str] = None,
        assistant_operator_ids: Optional[List[str]] = None,
        operation_seq: Optional[int] = None,
        operation_name: Optional[str] = None,
        machine_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        quality_check_passed: Optional[bool] = None,
        remark: Optional[str] = None,
        created_by: Optional[str] = None,
        report_date: Optional[datetime] = None,
    ) -> ProductionReport:
        """创建生产报工"""
        import uuid
        
        # 生成报工单号
        report_code = f"PR{datetime.now().strftime('%Y%m%d%H%M%S')}{str(uuid.uuid4())[:4].upper()}"
        
        report = ProductionReport(
            report_code=report_code,
            factory_id=factory_id,
            work_order_id=work_order_id,
            station_id=station_id,
            good_qty=good_qty,
            defect_qty=defect_qty,
            scrap_qty=scrap_qty,
            report_type=report_type,
            shift=shift,
            operator_id=operator_id,
            assistant_operator_ids=assistant_operator_ids or [],
            operation_seq=operation_seq,
            operation_name=operation_name,
            machine_id=machine_id,
            start_time=start_time,
            end_time=end_time,
            quality_check_passed=quality_check_passed,
            remark=remark,
            created_by=created_by,
        )
        # 可选报工日期：支持补录历史报工（created_at 作为报工时间参与看板聚合）
        if report_date is not None:
            if report_date.tzinfo is not None:
                report_date = report_date.astimezone(timezone.utc).replace(tzinfo=None)
            report.created_at = report_date
        
        self.db.add(report)
        await self.db.commit()
        await self.db.refresh(report)
        
        # 更新工单的完工数量
        await self._update_work_order_qty(work_order_id)
        
        # 【新增】BOM物料反冲扣减 - 解决第4号缺陷（完工不扣BOM库存）
        # 根据良品数量反向扣减 BOM 材料用量
        # 完工入库要在扣料之前：同一批物料不能在这张单里既算产出又算消耗
        await self._record_output(self.db, work_order_id, good_qty, created_by)
        await self._backflush_materials(self.db, work_order_id, good_qty, created_by)
        
        # #11 PS事件解耦（增强版）- 将APS重算请求写入数据库队列，由消费者服务异步处理
        # 入队失败不应阻断报工主流程（报工已commit）
        if factory_id and work_order_id:
            try:
                await self._enqueue_aps_replan(work_order_id, factory_id, report.id, 'report_created', created_by or 'system')
            except Exception as e:
                _logger.warning("APS入队失败(报工创建), 不阻断主流程: %s", e)
                await self.db.rollback()
        
        return report
    
    async def _update_work_order_qty(self, work_order_id: str):
        """更新工单完工数量"""
        from sqlalchemy import func
        from sqlalchemy import func
        
        result = await self.db.execute(
            select(
                func.sum(ProductionReport.good_qty),
                func.sum(ProductionReport.defect_qty),
                func.sum(ProductionReport.scrap_qty)
            ).where(ProductionReport.work_order_id == work_order_id)
        )
        row = result.first()
        
        if row:
            completed_qty = row[0] or 0
            good_qty = row[0] or 0
            defect_qty = row[1] or 0
            
            await self.db.execute(
                update(WorkOrder)
                .where(WorkOrder.id == work_order_id)
                .values(
                    completed_qty=completed_qty,
                    good_qty=good_qty,
                    defect_qty=defect_qty,
                    partial_completion_percentage=(
                        func.least(
                            100.0,
                            completed_qty * 100.0 / func.nullif(WorkOrder.planned_qty, 0),
                        )
                    ),
                    in_progress_status=(
                        case(
                            (completed_qty >= WorkOrder.planned_qty, "completed"),
                            (completed_qty > 0, "in_progress"),
                            else_="not_started",
                        )
                    ),
                )
            )
            await self.db.commit()
    
    async def get_report_by_id(self, report_id: str) -> Optional[ProductionReport]:
        """根据 ID 获取报工"""
        result = await self.db.execute(
            select(ProductionReport)
            .options(selectinload(ProductionReport.comments))
            .where(ProductionReport.id == report_id)
        )
        return result.scalar_one_or_none()
    
    async def _backflush_materials(self, db: AsyncSession, work_order_id: str, good_qty: int, created_by: Optional[str] = None) -> bool:
        """报工扣料走唯一入口：`InventoryService.issue_materials_for_production`。

        原来这段自己 `inventory.total_qty -= deduct_qty`、把记流水那句留在注释里
        （`# await self.record_inventory_transaction(...)`），
        结果是库存变了但 `inventory_transactions` 一条不写 —— 台账无痕，
        与"单据必须过账"的基线相反；而且它自己查 `bom_items`，
        和 MRP/领料用的 `bom_source` 不是同一份来源，同一产品会扣出两套需求。

        现在：来源统一（engflow 镜像 → 本地 bom_items → 本单齐套快照），
        扣减统一（`apply_movement` 写库存 + 写流水 + 校验工单锚点），
        欠料只上报不打回报工（应领 50、实扣 40、欠 10 要照实进账）。
        """
        from api.services.wms_service import InventoryService
        from database.models import WorkOrder

        if good_qty is None or int(good_qty) <= 0:
            return False
        work_order = await db.get(WorkOrder, work_order_id)
        if work_order is None or not work_order.product_id:
            return False

        result = await InventoryService(db).issue_materials_for_production(
            factory_id=work_order.factory_id,
            work_order_id=work_order_id,
            product_code=str(work_order.product_id),
            output_qty=int(good_qty),
            created_by=created_by or "mes_backflush",
        )
        await db.commit()
        return int(result.get("issued_lines") or 0) > 0

    async def _record_output(self, db: AsyncSession, work_order_id: str, good_qty: int,
                             created_by: Optional[str] = None) -> None:
        """合格产出入库并写 `production_in` 流水。

        以前全系统没有任何地方写过这个类型（只在枚举里存在），
        所以工单完工后库存不增、父层齐套门永远等不到下级做完 —— 闭环断在最后一步。
        """
        from api.services.wms_service import InventoryService
        from database.models import WorkOrder

        if good_qty is None or int(good_qty) <= 0:
            return
        work_order = await db.get(WorkOrder, work_order_id)
        if work_order is None or not work_order.product_id:
            return
        await InventoryService(db).record_production_output(
            factory_id=work_order.factory_id,
            work_order_id=work_order_id,
            product_code=str(work_order.product_id),
            qty=int(good_qty),
            created_by=created_by or "mes_backflush",
        )
        await db.commit()

    async def _enqueue_aps_replan(self, work_order_id: str, factory_id: str, report_id: str, 
                                  source_type: str, created_by: str) -> None:
        """#11 PS事件解耦（增强版）- 将APS重算请求写入数据库队列，由消费者服务异步处理
        
        实现模式：生产者（报工服务）→ 队列表（APSRequest）→ 消费者服务 → APS引擎
        优势：解耦报工与排程逻辑、支持重试机制、防止故障扩散、可水平扩展消费者
        注意：此方法仅将请求入队，不等待 APS 计算完成
        
        Args:
            work_order_id: 关联工单ID
            factory_id: 工厂ID
            report_id: 触发报工ID
            source_type: 触发源 ('report_created', 'report_modified', 'manual')
            created_by: 操作用户ID
        """
        from uuid import uuid4
        from datetime import datetime
        
        # 插入APS调度请求到队列表
        request = APSRequest(
            id=str(uuid4()),
            factory_id=factory_id,
            mode='hybrid',
            horizon_days=7,
            optimize_for='delivery',
            source_type=source_type,
            source_id=report_id,
            status='pending',
            retry_count=0,
            max_retries=3,
            created_at=datetime.utcnow(),
        )
        
        self.db.add(request)
        await self.db.commit()
    
    async def list_reports(
        self,
        factory_id: str,
        work_order_id: Optional[str] = None,
        station_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> List[ProductionReport]:
        """获取报工列表"""
        query = select(ProductionReport).where(ProductionReport.factory_id == factory_id)
        
        if work_order_id:
            query = query.where(ProductionReport.work_order_id == work_order_id)
        if station_id:
            query = query.where(ProductionReport.station_id == station_id)
        
        query = query.order_by(ProductionReport.created_at.desc()).offset(skip).limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def add_comment(
        self,
        report_id: str,
        comment: str,
        created_by: Optional[str] = None,
    ) -> ProductionReportComment:
        """添加报工评论"""
        report_comment = ProductionReportComment(
            report_id=report_id,
            comment=comment,
            created_by=created_by,
        )
        
        self.db.add(report_comment)
        await self.db.commit()
        await self.db.refresh(report_comment)
        
        return report_comment
    
    async def modify_report(
        self,
        report_id: str,
        good_qty: Optional[int] = None,
        defect_qty: Optional[int] = None,
        scrap_qty: Optional[int] = None,
        remark: Optional[str] = None,
        modified_by: Optional[str] = None,
    ) -> Optional[ProductionReport]:
        """修改报工（需记录修改历史）"""
        report = await self.get_report_by_id(report_id)
        if not report:
            return None
        
        if good_qty is not None:
            report.good_qty = good_qty
        if defect_qty is not None:
            report.defect_qty = defect_qty
        if scrap_qty is not None:
            report.scrap_qty = scrap_qty
        if remark is not None:
            report.remark = remark
        
        report.is_modified = True
        report.modified_at = datetime.utcnow()
        report.modified_by = modified_by
        
        await self.db.commit()
        await self.db.refresh(report)
        
        # 重新计算工单数量
        await self._update_work_order_qty(report.work_order_id)
        
        # #11 PS事件解耦 - 报工修改后触发APS重新计算（入队失败不阻断报工）
        if report.factory_id and report.work_order_id:
            try:
                await self._enqueue_aps_replan(
                    report.work_order_id, report.factory_id, report.id,
                    'report_modified', report.modified_by or 'system'
                )
            except Exception as e:
                _logger.warning("APS入队失败(报工修改), 不阻断主流程: %s", e)
                await self.db.rollback()
        
        return report


class StationService:
    """工位服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_station(
        self,
        factory_id: str,
        station_code: str,
        station_name: str,
        station_type: str,
        capacity_per_hour: int = 0,
        workshop_id: Optional[str] = None,
        equipment_ids: Optional[List[str]] = None,
        created_by: Optional[str] = None,
    ) -> Station:
        """创建工位"""
        station = Station(
            station_code=station_code,
            station_name=station_name,
            factory_id=factory_id,
            station_type=station_type,
            workshop_id=workshop_id,
            capacity_per_hour=capacity_per_hour,
            equipment_ids=equipment_ids or [],
            created_by=created_by,
        )
        
        self.db.add(station)
        await self.db.commit()
        await self.db.refresh(station)
        
        return station
    
    async def get_station_by_id(self, station_id: str) -> Optional[Station]:
        """根据 ID 获取工位"""
        result = await self.db.execute(
            select(Station).where(Station.id == station_id)
        )
        return result.scalar_one_or_none()
    
    async def list_stations(
        self,
        factory_id: str,
        station_type: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Station]:
        """获取工位列表"""
        query = select(Station).where(Station.factory_id == factory_id)
        
        if station_type:
            query = query.where(Station.station_type == station_type)
        if status:
            query = query.where(Station.status == status)
        
        query = query.order_by(Station.station_code).offset(skip).limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def update_station(
        self,
        station_id: str,
        station_name: Optional[str] = None,
        station_type: Optional[str] = None,
        capacity_per_hour: Optional[int] = None,
        workshop_id: Optional[str] = None,
        equipment_ids: Optional[List[str]] = None,
        status: Optional[str] = None,
    ) -> Optional[Station]:
        """更新工位"""
        station = await self.get_station_by_id(station_id)
        if not station:
            return None
        
        if station_name:
            station.station_name = station_name
        if station_type:
            station.station_type = station_type
        if capacity_per_hour is not None:
            station.capacity_per_hour = capacity_per_hour
        if workshop_id:
            station.workshop_id = workshop_id
        if equipment_ids is not None:
            station.equipment_ids = equipment_ids
        if status:
            station.status = status
        
        await self.db.commit()
        await self.db.refresh(station)
        
        return station
    
    async def delete_station(self, station_id: str) -> bool:
        """删除工位"""
        station = await self.get_station_by_id(station_id)
        if not station:
            return False
        
        await self.db.delete(station)
        await self.db.commit()
        return True


class RoutingService:
    """工艺路线服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_routing(
        self,
        factory_id: str,
        product_id: str,
        version: str = "v1",
        steps: Optional[List[Dict[str, Any]]] = None,
        created_by: Optional[str] = None,
    ) -> Routing:
        """创建工艺路线"""
        import uuid
        routing_code = f"RT{product_id}-{version}-{str(uuid.uuid4())[:6].upper()}"
        
        routing = Routing(
            routing_code=routing_code,
            factory_id=factory_id,
            product_id=product_id,
            version=version,
            steps=steps or [],
            created_by=created_by,
        )
        
        self.db.add(routing)
        await self.db.commit()
        await self.db.refresh(routing)
        
        return routing
    
    async def get_routing_by_id(self, routing_id: str) -> Optional[Routing]:
        """根据 ID 获取工艺路线"""
        result = await self.db.execute(
            select(Routing).where(Routing.id == routing_id)
        )
        return result.scalar_one_or_none()
    
    async def get_routing_by_product(
        self, 
        factory_id: str, 
        product_id: str, 
        version: Optional[str] = None
    ) -> Optional[Routing]:
        """根据产品获取工艺路线"""
        query = select(Routing).where(
            Routing.factory_id == factory_id,
            Routing.product_id == product_id,
            Routing.is_active == True
        )
        
        if version:
            query = query.where(Routing.version == version)
        else:
            # 默认获取最新版本
            query = query.order_by(Routing.version.desc())
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def list_routings(
        self,
        factory_id: str,
        product_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Routing]:
        """获取工艺路线列表"""
        query = select(Routing).where(Routing.factory_id == factory_id)
        
        if product_id:
            query = query.where(Routing.product_id == product_id)
        
        query = query.order_by(Routing.created_at.desc()).offset(skip).limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def update_routing(
        self,
        routing_id: str,
        version: Optional[str] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Routing]:
        """更新工艺路线"""
        routing = await self.get_routing_by_id(routing_id)
        if not routing:
            return None
        
        if version:
            routing.version = version
        if steps is not None:
            routing.steps = steps
        if is_active is not None:
            routing.is_active = is_active
        
        await self.db.commit()
        await self.db.refresh(routing)
        
        return routing
    
    async def deactivate_routing(self, routing_id: str) -> bool:
        """停用工艺路线"""
        routing = await self.get_routing_by_id(routing_id)
        if not routing:
            return False
        
        routing.is_active = False
        await self.db.commit()
        return True


class EquipmentService:
    """设备管理服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_equipment(
        self,
        factory_id: str,
        equipment_code: str,
        equipment_name: str,
        equipment_type: Optional[str] = None,
        station_id: Optional[str] = None,
        spec: Optional[Dict[str, Any]] = None,
    ) -> Equipment:
        """创建设备"""
        equipment = Equipment(
            equipment_code=equipment_code,
            equipment_name=equipment_name,
            factory_id=factory_id,
            equipment_type=equipment_type,
            station_id=station_id,
            spec=spec or {},
        )
        
        self.db.add(equipment)
        await self.db.commit()
        await self.db.refresh(equipment)
        
        return equipment
    
    async def get_equipment_by_id(self, equipment_id: str) -> Optional[Equipment]:
        """根据 ID 获取设备"""
        result = await self.db.execute(
            select(Equipment).where(Equipment.id == equipment_id)
        )
        return result.scalar_one_or_none()
    
    async def list_equipment(
        self,
        factory_id: str,
        equipment_type: Optional[str] = None,
        status: Optional[str] = None,
        station_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Equipment]:
        """获取设备列表"""
        query = select(Equipment).where(Equipment.factory_id == factory_id)
        
        if equipment_type:
            query = query.where(Equipment.equipment_type == equipment_type)
        if status:
            query = query.where(Equipment.status == status)
        if station_id:
            query = query.where(Equipment.station_id == station_id)
        
        query = query.order_by(Equipment.equipment_code).offset(skip).limit(limit)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def update_equipment(
        self,
        equipment_id: str,
        equipment_name: Optional[str] = None,
        equipment_type: Optional[str] = None,
        station_id: Optional[str] = None,
        status: Optional[str] = None,
        spec: Optional[Dict[str, Any]] = None,
        last_maintenance_date: Optional[datetime] = None,
        next_maintenance_date: Optional[datetime] = None,
    ) -> Optional[Equipment]:
        """更新设备"""
        equipment = await self.get_equipment_by_id(equipment_id)
        if not equipment:
            return None
        
        if equipment_name:
            equipment.equipment_name = equipment_name
        if equipment_type:
            equipment.equipment_type = equipment_type
        if station_id:
            equipment.station_id = station_id
        if status:
            equipment.status = status
        if spec is not None:
            equipment.spec = spec
        if last_maintenance_date:
            equipment.last_maintenance_date = last_maintenance_date
        if next_maintenance_date:
            equipment.next_maintenance_date = next_maintenance_date
        
        await self.db.commit()
        await self.db.refresh(equipment)
        
        return equipment
    
    async def update_status(self, equipment_id: str, status: str) -> bool:
        """更新设备状态"""
        equipment = await self.get_equipment_by_id(equipment_id)
        if not equipment:
            return False
        
        equipment.status = status
        await self.db.commit()
        return True


__all__ = [
    "ProductionReportService",
    "StationService",
    "RoutingService",
    "EquipmentService",
]
