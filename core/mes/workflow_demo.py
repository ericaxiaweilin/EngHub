"""
MES Work Order Fulfillment Workflow
工单履约场景工作流演示

场景：一张工单从创建到完成的完整生命周期
1. 工单创建 (Work Order Creation)
2. 工艺路线验证 (Routing Validation)
3. 产能检查 (Capacity Check)
4. 设备状态检查 (Equipment Status Check)
5. 工单下达 (Work Order Release)
6. 生产报工 (Production Reporting)
7. 过程检验 (IPQC Inspection)
8. 完工检验 (FQC Inspection)
9. 工单完成 (Work Order Completion)
10. 入库 (Inbound to Warehouse)
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum


# ==================== 数据模型 ====================

class WorkOrderStatus(str, Enum):
    PENDING = "pending"
    RELEASED = "released"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"


class InspectionType(str, Enum):
    IQC = "iqc"
    IPQC = "ipqc"
    FQC = "fqc"
    OQC = "oqc"


class InspectionStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class EquipmentStatus(str, Enum):
    RUNNING = "running"
    IDLE = "idle"
    FAULT = "fault"
    MAINTENANCE = "maintenance"


# ==================== 模拟数据库 ====================

class MockDatabase:
    """模拟数据库存储"""
    
    def __init__(self):
        self.work_orders = {}
        self.routings = {}
        self.stations = {}
        self.equipment = {}
        self.production_reports = []
        self.inspections = []
        self.inventory = {}
        self.warehouses = {}
        
    async def save_work_order(self, wo: Dict[str, Any]):
        self.work_orders[wo["id"]] = wo
        
    async def get_work_order(self, wo_id: str) -> Optional[Dict[str, Any]]:
        return self.work_orders.get(wo_id)
    
    async def save_routing(self, routing: Dict[str, Any]):
        self.routings[routing["id"]] = routing
        
    async def get_routing(self, routing_id: str) -> Optional[Dict[str, Any]]:
        return self.routings.get(routing_id)
    
    async def save_station(self, station: Dict[str, Any]):
        self.stations[station["id"]] = station
        
    async def get_station(self, station_id: str) -> Optional[Dict[str, Any]]:
        return self.stations.get(station_id)
    
    async def save_equipment(self, eq: Dict[str, Any]):
        self.equipment[eq["id"]] = eq
        
    async def get_equipment(self, eq_id: str) -> Optional[Dict[str, Any]]:
        return self.equipment.get(eq_id)
    
    async def save_production_report(self, report: Dict[str, Any]):
        self.production_reports.append(report)
        
    async def save_inspection(self, inspection: Dict[str, Any]):
        self.inspections.append(inspection)
        
    async def update_inventory(self, material_id: str, qty: int, warehouse_id: str):
        key = f"{material_id}_{warehouse_id}"
        if key not in self.inventory:
            self.inventory[key] = {"material_id": material_id, "warehouse_id": warehouse_id, "qty": 0}
        self.inventory[key]["qty"] += qty


# ==================== 服务类 ====================

class RoutingService:
    """工艺路线服务"""
    
    def __init__(self, db: MockDatabase):
        self.db = db
    
    async def create_routing(self, factory_id: str, product_id: str, steps: List[Dict]) -> Dict[str, Any]:
        routing_id = str(uuid.uuid4())
        routing = {
            "id": routing_id,
            "factory_id": factory_id,
            "product_id": product_id,
            "version": "v1",
            "steps": steps,
            "status": "active",
            "created_at": datetime.now(),
        }
        await self.db.save_routing(routing)
        print(f"  [工艺路线] 创建成功：{routing_id[:8]}... 产品:{product_id}, 工序数:{len(steps)}")
        return routing
    
    async def get_routing_for_product(self, product_id: str) -> Optional[Dict[str, Any]]:
        for routing in self.db.routings.values():
            if routing["product_id"] == product_id and routing["status"] == "active":
                return routing
        return None
    
    async def validate_routing(self, routing_id: str) -> Dict[str, Any]:
        routing = await self.db.get_routing(routing_id)
        if not routing:
            return {"valid": False, "errors": ["工艺路线不存在"]}
        
        errors = []
        warnings = []
        
        # 验证工序完整性
        if not routing["steps"]:
            errors.append("工艺路线没有定义工序")
        
        # 验证每个工序
        for i, step in enumerate(routing["steps"]):
            if "operation_name" not in step:
                errors.append(f"工序{i+1}缺少操作名称")
            if "station_id" not in step:
                errors.append(f"工序{i+1}缺少工位信息")
            if "standard_time" not in step:
                warnings.append(f"工序{i+1}未定义标准工时")
        
        is_valid = len(errors) == 0
        result = {"valid": is_valid, "errors": errors, "warnings": warnings}
        
        if is_valid:
            print(f"  [工艺路线] 验证通过：{routing_id[:8]}...")
        else:
            print(f"  [工艺路线] 验证失败：{errors}")
        
        return result


class StationService:
    """工位服务"""
    
    def __init__(self, db: MockDatabase):
        self.db = db
    
    async def create_station(self, factory_id: str, station_code: str, station_name: str, 
                            station_type: str = "production", capacity: int = 100) -> Dict[str, Any]:
        station_id = str(uuid.uuid4())
        station = {
            "id": station_id,
            "factory_id": factory_id,
            "station_code": station_code,
            "station_name": station_name,
            "station_type": station_type,
            "capacity_per_hour": capacity,
            "status": "active",
            "equipment_ids": [],
            "created_at": datetime.now(),
        }
        await self.db.save_station(station)
        print(f"  [工位] 创建成功：{station_code} - {station_name}")
        return station
    
    async def check_station_available(self, station_id: str) -> Dict[str, Any]:
        station = await self.db.get_station(station_id)
        if not station:
            return {"available": False, "reason": "工位不存在"}
        
        if station["status"] != "active":
            return {"available": False, "reason": f"工位状态异常：{station['status']}"}
        
        # 检查关联设备
        equipment_status = "normal"
        for eq_id in station.get("equipment_ids", []):
            eq = await self.db.get_equipment(eq_id)
            if eq and eq["status"] not in ["running", "idle"]:
                equipment_status = f"设备故障：{eq['status']}"
                break
        
        available = equipment_status == "normal"
        result = {
            "available": available,
            "station_id": station_id,
            "station_code": station.get("station_code"),
            "equipment_status": equipment_status,
        }
        
        if available:
            print(f"  [工位检查] {station.get('station_code')} 可用")
        else:
            print(f"  [工位检查] {station.get('station_code')} 不可用：{equipment_status}")
        
        return result


class EquipmentService:
    """设备服务"""
    
    def __init__(self, db: MockDatabase):
        self.db = db
    
    async def create_equipment(self, factory_id: str, station_id: str, 
                              equipment_code: str, equipment_name: str) -> Dict[str, Any]:
        eq_id = str(uuid.uuid4())
        equipment = {
            "id": eq_id,
            "factory_id": factory_id,
            "station_id": station_id,
            "equipment_code": equipment_code,
            "equipment_name": equipment_name,
            "status": EquipmentStatus.RUNNING.value,
            "created_at": datetime.now(),
        }
        await self.db.save_equipment(equipment)
        
        # 更新工位的设备列表
        station = await self.db.get_station(station_id)
        if station:
            station["equipment_ids"].append(eq_id)
            await self.db.save_station(station)
        
        print(f"  [设备] 创建成功：{equipment_code} - {equipment_name}")
        return equipment
    
    async def set_equipment_status(self, equipment_id: str, status: str) -> Dict[str, Any]:
        equipment = await self.db.get_equipment(equipment_id)
        if equipment:
            old_status = equipment["status"]
            equipment["status"] = status
            await self.db.save_equipment(equipment)
            print(f"  [设备状态] {equipment['equipment_code']}: {old_status} -> {status}")
        return equipment or {}
    
    async def check_equipment_for_production(self, station_id: str) -> Dict[str, Any]:
        station = await self.db.get_station(station_id)
        if not station:
            return {"can_proceed": False, "reason": "工位不存在"}
        
        equipment_ids = station.get("equipment_ids", [])
        if not equipment_ids:
            return {"can_proceed": True, "reason": "无关联设备"}
        
        faulty_equipment = []
        for eq_id in equipment_ids:
            eq = await self.db.get_equipment(eq_id)
            if eq and eq["status"] in [EquipmentStatus.FAULT.value, EquipmentStatus.MAINTENANCE.value]:
                faulty_equipment.append(eq["equipment_code"])
        
        can_proceed = len(faulty_equipment) == 0
        result = {
            "can_proceed": can_proceed,
            "station_id": station_id,
            "faulty_equipment": faulty_equipment,
        }
        
        if can_proceed:
            print(f"  [设备检查] 工位{station.get('station_code')} 设备正常")
        else:
            print(f"  [设备检查] 工位{station.get('station_code')} 设备故障：{faulty_equipment}")
        
        return result


class WorkOrderService:
    """工单服务"""
    
    VALID_STATUS_TRANSITIONS = {
        WorkOrderStatus.PENDING.value: [WorkOrderStatus.RELEASED.value, WorkOrderStatus.CANCELLED.value],
        WorkOrderStatus.RELEASED.value: [WorkOrderStatus.IN_PROGRESS.value, WorkOrderStatus.ON_HOLD.value],
        WorkOrderStatus.IN_PROGRESS.value: [WorkOrderStatus.COMPLETED.value, WorkOrderStatus.ON_HOLD.value],
        WorkOrderStatus.ON_HOLD.value: [WorkOrderStatus.IN_PROGRESS.value, WorkOrderStatus.CANCELLED.value],
    }
    
    def __init__(self, db: MockDatabase):
        self.db = db
    
    def generate_wo_code(self, factory_code: str) -> str:
        today = datetime.now().strftime("%Y%m%d")
        sequence = str(uuid.uuid4())[:6].upper()
        return f"WO-{factory_code}-{today}-{sequence}"
    
    async def create_work_order(self, factory_id: str, product_id: str, planned_qty: int,
                               sales_order_id: Optional[str] = None, 
                               routing_id: Optional[str] = None,
                               priority: str = "medium",
                               planned_start: Optional[datetime] = None,
                               planned_due: Optional[datetime] = None,
                               assigned_station_id: Optional[str] = None,
                               created_by: str = "system") -> Dict[str, Any]:
        wo_id = str(uuid.uuid4())
        wo_code = self.generate_wo_code(factory_id[:3].upper())
        
        work_order = {
            "id": wo_id,
            "work_order_code": wo_code,
            "factory_id": factory_id,
            "sales_order_id": sales_order_id,
            "product_id": product_id,
            "routing_id": routing_id,
            "planned_qty": planned_qty,
            "unit": "pcs",
            "completed_qty": 0,
            "good_qty": 0,
            "defect_qty": 0,
            "scrap_qty": 0,
            "status": WorkOrderStatus.PENDING.value,
            "priority": priority,
            "planned_start": planned_start,
            "planned_due": planned_due,
            "actual_start": None,
            "actual_complete": None,
            "assigned_station_id": assigned_station_id,
            "current_routing_step": 0,
            "created_by": created_by,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        
        await self.db.save_work_order(work_order)
        print(f"  [工单创建] {wo_code} | 产品:{product_id} | 数量:{planned_qty} | 状态:pending")
        return work_order
    
    async def get_work_order(self, wo_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.get_work_order(wo_id)
    
    async def _change_status(self, wo_id: str, new_status: str, operator: str) -> Dict[str, Any]:
        wo = await self.get_work_order(wo_id)
        if not wo:
            raise ValueError(f"工单{wo_id}不存在")
        
        current_status = wo["status"]
        valid_transitions = self.VALID_STATUS_TRANSITIONS.get(current_status, [])
        
        if new_status not in valid_transitions:
            raise ValueError(f"无效的状态转换：{current_status} -> {new_status}")
        
        wo["status"] = new_status
        wo["updated_by"] = operator
        wo["updated_at"] = datetime.now()
        await self.db.save_work_order(wo)
        
        print(f"  [工单状态] {wo['work_order_code']}: {current_status} -> {new_status}")
        return wo
    
    async def release_work_order(self, wo_id: str, released_by: str = "system") -> Dict[str, Any]:
        # 释放前检查
        wo = await self.get_work_order(wo_id)
        
        # 检查工艺路线
        if wo.get("routing_id"):
            routing_service = RoutingService(self.db)
            validation = await routing_service.validate_routing(wo["routing_id"])
            if not validation["valid"]:
                raise ValueError(f"工艺路线验证失败：{validation['errors']}")
        
        # 检查工位可用性
        if wo.get("assigned_station_id"):
            station_service = StationService(self.db)
            station_check = await station_service.check_station_available(wo["assigned_station_id"])
            if not station_check["available"]:
                raise ValueError(f"工位不可用：{station_check['reason']}")
            
            # 检查设备状态
            equipment_service = EquipmentService(self.db)
            eq_check = await equipment_service.check_equipment_for_production(wo["assigned_station_id"])
            if not eq_check["can_proceed"]:
                raise ValueError(f"设备故障，无法下达工单：{eq_check['faulty_equipment']}")
        
        return await self._change_status(wo_id, WorkOrderStatus.RELEASED.value, released_by)
    
    async def start_work_order(self, wo_id: str, started_by: str = "operator") -> Dict[str, Any]:
        wo = await self._change_status(wo_id, WorkOrderStatus.IN_PROGRESS.value, started_by)
        wo["actual_start"] = datetime.now()
        await self.db.save_work_order(wo)
        print(f"  [工单开始] {wo['work_order_code']} 实际开始时间：{wo['actual_start'].strftime('%Y-%m-%d %H:%M:%S')}")
        return wo
    
    async def complete_work_order(self, wo_id: str, completed_by: str = "system") -> Dict[str, Any]:
        wo = await self.get_work_order(wo_id)
        wo["actual_complete"] = datetime.now()
        await self.db.save_work_order(wo)
        wo = await self._change_status(wo_id, WorkOrderStatus.COMPLETED.value, completed_by)
        print(f"  [工单完成] {wo['work_order_code']} 实际完成时间：{wo['actual_complete'].strftime('%Y-%m-%d %H:%M:%S')}")
        return wo


class ProductionReportingService:
    """生产报工服务"""
    
    def __init__(self, db: MockDatabase):
        self.db = db
    
    async def create_report(self, work_order_id: str, station_id: str, operator_id: str,
                           quantity_produced: int, quantity_qualified: int, 
                           quantity_rejected: int = 0,
                           report_type: str = "normal",
                           shift: str = "day") -> Dict[str, Any]:
        wo = await self.db.get_work_order(work_order_id)
        if not wo:
            raise ValueError(f"工单{work_order_id}不存在")
        
        # 验证报工数量
        total_reported = sum(
            r["quantity_produced"] for r in self.db.production_reports 
            if r["work_order_id"] == work_order_id
        )
        remaining_qty = wo["planned_qty"] - total_reported
        
        if quantity_produced > remaining_qty:
            raise ValueError(f"报工数量超出计划：已报{total_reported}, 剩余{remaining_qty}")
        
        report_id = str(uuid.uuid4())
        report = {
            "id": report_id,
            "report_code": f"PR-{wo['work_order_code']}-{datetime.now().strftime('%Y%m%d')}",
            "work_order_id": work_order_id,
            "station_id": station_id,
            "operator_id": operator_id,
            "report_type": report_type,
            "shift": shift,
            "quantity_produced": quantity_produced,
            "quantity_qualified": quantity_qualified,
            "quantity_rejected": quantity_rejected,
            "created_at": datetime.now(),
        }
        
        await self.db.save_production_report(report)
        
        # 更新工单进度
        wo["completed_qty"] += quantity_produced
        wo["good_qty"] += quantity_qualified
        wo["defect_qty"] += quantity_rejected
        await self.db.save_work_order(wo)
        
        print(f"  [生产报工] {wo['work_order_code']} | 产出:{quantity_produced} | 合格:{quantity_qualified} | 不良:{quantity_rejected}")
        return report


class InspectionService:
    """检验服务"""
    
    def __init__(self, db: MockDatabase):
        self.db = db
    
    async def create_inspection(self, inspection_type: str, work_order_id: str,
                               product_id: str, batch_size: int,
                               aql_level: float = 1.0) -> Dict[str, Any]:
        # 验证必填字段
        if inspection_type in ["ipqc", "fqc", "oqc"] and not work_order_id:
            raise ValueError(f"{inspection_type}检验必须关联工单")
        
        inspection_id = str(uuid.uuid4())
        inspection = {
            "id": inspection_id,
            "inspection_code": f"INS-{inspection_type.upper()}-{datetime.now().strftime('%Y%m%d')}",
            "inspection_type": inspection_type,
            "work_order_id": work_order_id,
            "product_id": product_id,
            "batch_size": batch_size,
            "aql_level": aql_level,
            "sample_size": self._calculate_sample_size(batch_size),
            "status": InspectionStatus.PENDING.value,
            "created_at": datetime.now(),
        }
        
        await self.db.save_inspection(inspection)
        print(f"  [{inspection_type.upper()}检验] 创建：{inspection['inspection_code']} | 批量:{batch_size} | 样本:{inspection['sample_size']}")
        return inspection
    
    def _calculate_sample_size(self, batch_size: int) -> int:
        """简化样本大小计算"""
        if batch_size <= 50:
            return 8
        elif batch_size <= 200:
            return 20
        elif batch_size <= 500:
            return 50
        else:
            return 80
    
    async def submit_inspection_result(self, inspection_id: str, inspected_qty: int,
                                       defective_qty: int, inspector_id: str) -> Dict[str, Any]:
        inspection = None
        for insp in self.db.inspections:
            if insp["id"] == inspection_id:
                inspection = insp
                break
        
        if not inspection:
            raise ValueError(f"检验单{inspection_id}不存在")
        
        # AQL判定
        ac = int(inspection["sample_size"] * inspection["aql_level"] / 100) + 1  # 简化AC值计算
        
        if defective_qty <= ac:
            inspection["status"] = InspectionStatus.PASSED.value
            result = "PASS"
        else:
            inspection["status"] = InspectionStatus.FAILED.value
            result = "FAIL"
        
        inspection["inspected_qty"] = inspected_qty
        inspection["defective_qty"] = defective_qty
        inspection["inspector_id"] = inspector_id
        inspection["inspected_at"] = datetime.now()
        inspection["aql_ac"] = ac
        
        print(f"  [{inspection['inspection_type'].upper()}检验结果] {inspection['inspection_code']} | 检验:{inspected_qty} | 不良:{defective_qty} | AC:{ac} | 判定:{result}")
        return inspection


class WarehouseService:
    """仓库服务"""
    
    def __init__(self, db: MockDatabase):
        self.db = db
    
    async def create_warehouse(self, factory_id: str, warehouse_code: str, 
                              warehouse_name: str, warehouse_type: str) -> Dict[str, Any]:
        wh_id = str(uuid.uuid4())
        warehouse = {
            "id": wh_id,
            "warehouse_code": warehouse_code,
            "warehouse_name": warehouse_name,
            "factory_id": factory_id,
            "warehouse_type": warehouse_type,
            "status": "active",
            "created_at": datetime.now(),
        }
        self.db.warehouses[wh_id] = warehouse
        print(f"  [仓库] 创建：{warehouse_code} - {warehouse_name}")
        return warehouse
    
    async def inbound_finished_goods(self, work_order_id: str, warehouse_id: str,
                                    product_id: str, quantity: int) -> Dict[str, Any]:
        wo = await self.db.get_work_order(work_order_id)
        if not wo:
            raise ValueError(f"工单{work_order_id}不存在")
        
        if wo["status"] != WorkOrderStatus.COMPLETED.value:
            raise ValueError(f"工单未完成，不能入库：{wo['status']}")
        
        # 更新库存
        await self.db.update_inventory(product_id, quantity, warehouse_id)
        
        inventory_key = f"{product_id}_{warehouse_id}"
        current_qty = self.db.inventory[inventory_key]["qty"]
        
        print(f"  [成品入库] {wo['work_order_code']} | 产品:{product_id} | 数量:{quantity} | 当前库存:{current_qty}")
        return {
            "work_order_id": work_order_id,
            "product_id": product_id,
            "quantity": quantity,
            "warehouse_id": warehouse_id,
            "current_inventory": current_qty,
        }


# ==================== 工作流编排 ====================

class WorkOrderFulfillmentWorkflow:
    """工单履约工作流编排器"""
    
    def __init__(self):
        self.db = MockDatabase()
        self.wo_service = WorkOrderService(self.db)
        self.routing_service = RoutingService(self.db)
        self.station_service = StationService(self.db)
        self.equipment_service = EquipmentService(self.db)
        self.reporting_service = ProductionReportingService(self.db)
        self.inspection_service = InspectionService(self.db)
        self.warehouse_service = WarehouseService(self.db)
    
    async def setup_factory_environment(self):
        """初始化工厂环境"""
        print("\n" + "="*60)
        print("【步骤 0】初始化工厂环境")
        print("="*60)
        
        # 创建工厂基础数据
        factory_id = "FACTORY-SZ-001"
        
        # 创建工位
        station_smt = await self.station_service.create_station(
            factory_id=factory_id,
            station_code="SMT-LINE-01",
            station_name="SMT 贴片产线",
            station_type="production",
            capacity=500
        )
        
        station_dip = await self.station_service.create_station(
            factory_id=factory_id,
            station_code="DIP-LINE-01",
            station_name="DIP 插件产线",
            station_type="production",
            capacity=300
        )
        
        station_assembly = await self.station_service.create_station(
            factory_id=factory_id,
            station_code="ASSY-LINE-01",
            station_name="组装产线",
            station_type="production",
            capacity=400
        )
        
        station_qc = await self.station_service.create_station(
            factory_id=factory_id,
            station_code="QC-STATION-01",
            station_name="质检工位",
            station_type="inspection",
            capacity=100
        )
        
        # 创建设备并关联到工位
        await self.equipment_service.create_equipment(
            factory_id=factory_id,
            station_id=station_smt["id"],
            equipment_code="SMT-MACHINE-01",
            equipment_name="贴片机 A"
        )
        await self.equipment_service.create_equipment(
            factory_id=factory_id,
            station_id=station_smt["id"],
            equipment_code="SMT-MACHINE-02",
            equipment_name="贴片机 B"
        )
        
        await self.equipment_service.create_equipment(
            factory_id=factory_id,
            station_id=station_dip["id"],
            equipment_code="WAVE-SOLDER-01",
            equipment_name="波峰焊机"
        )
        
        # 创建仓库
        warehouse_fg = await self.warehouse_service.create_warehouse(
            factory_id=factory_id,
            warehouse_code="WH-FG-001",
            warehouse_name="成品仓",
            warehouse_type="finished_goods"
        )
        
        return {
            "factory_id": factory_id,
            "stations": {
                "smt": station_smt,
                "dip": station_dip,
                "assembly": station_assembly,
                "qc": station_qc,
            },
            "warehouse_fg": warehouse_fg,
        }
    
    async def run_workflow(self):
        """执行完整的工单履约工作流"""
        
        # 初始化环境
        env = await self.setup_factory_environment()
        factory_id = env["factory_id"]
        station_smt = env["stations"]["smt"]
        station_dip = env["stations"]["dip"]
        station_assembly = env["stations"]["assembly"]
        station_qc = env["stations"]["qc"]
        warehouse_fg = env["warehouse_fg"]
        
        product_id = "PRODUCT-PCB-001"
        sales_order_id = "SO-20260124-001"
        planned_qty = 1000
        
        # ========== 步骤 1: 创建工艺路线 ==========
        print("\n" + "="*60)
        print("【步骤 1】创建工艺路线")
        print("="*60)
        
        routing_steps = [
            {"sequence": 10, "operation_name": "SMT 贴片", "station_id": station_smt["id"], "standard_time": 120},
            {"sequence": 20, "operation_name": "DIP 插件", "station_id": station_dip["id"], "standard_time": 180},
            {"sequence": 30, "operation_name": "组装", "station_id": station_assembly["id"], "standard_time": 300},
            {"sequence": 40, "operation_name": "FQC 终检", "station_id": station_qc["id"], "standard_time": 60},
        ]
        
        routing = await self.routing_service.create_routing(
            factory_id=factory_id,
            product_id=product_id,
            steps=routing_steps
        )
        
        # 验证工艺路线
        await self.routing_service.validate_routing(routing["id"])
        
        # ========== 步骤 2: 创建工单 ==========
        print("\n" + "="*60)
        print("【步骤 2】创建生产工单")
        print("="*60)
        
        planned_start = datetime.now()
        planned_due = planned_start + timedelta(days=3)
        
        work_order = await self.wo_service.create_work_order(
            factory_id=factory_id,
            product_id=product_id,
            planned_qty=planned_qty,
            sales_order_id=sales_order_id,
            routing_id=routing["id"],
            priority="high",
            planned_start=planned_start,
            planned_due=planned_due,
            assigned_station_id=station_smt["id"],
            created_by="planner_zhang"
        )
        
        # ========== 步骤 3: 工单下达前检查 ==========
        print("\n" + "="*60)
        print("【步骤 3】工单下达前检查")
        print("="*60)
        
        # 检查设备状态（模拟正常运行）
        eq_check = await self.equipment_service.check_equipment_for_production(station_smt["id"])
        if not eq_check["can_proceed"]:
            print(f"  ❌ 设备检查失败，工单无法下达：{eq_check['faulty_equipment']}")
            return
        
        # ========== 步骤 4: 工单下达 ==========
        print("\n" + "="*60)
        print("【步骤 4】工单下达 (Release)")
        print("="*60)
        
        try:
            work_order = await self.wo_service.release_work_order(
                work_order["id"], 
                released_by="manager_li"
            )
        except ValueError as e:
            print(f"  ❌ 工单下达失败：{e}")
            return
        
        # ========== 步骤 5: 开始生产 ==========
        print("\n" + "="*60)
        print("【步骤 5】开始生产 (Start)")
        print("="*60)
        
        work_order = await self.wo_service.start_work_order(
            work_order["id"],
            started_by="operator_wang"
        )
        
        # ========== 步骤 6: 生产报工 (多批次) ==========
        print("\n" + "="*60)
        print("【步骤 6】生产报工 (多批次)")
        print("="*60)
        
        # 第一批报工
        report1 = await self.reporting_service.create_report(
            work_order_id=work_order["id"],
            station_id=station_smt["id"],
            operator_id="operator_wang",
            quantity_produced=400,
            quantity_qualified=395,
            quantity_rejected=5,
            report_type="normal",
            shift="day"
        )
        
        # 第二批报工
        report2 = await self.reporting_service.create_report(
            work_order_id=work_order["id"],
            station_id=station_dip["id"],
            operator_id="operator_liu",
            quantity_produced=600,
            quantity_qualified=590,
            quantity_rejected=10,
            report_type="normal",
            shift="day"
        )
        
        # 查看工单进度
        wo_progress = await self.wo_service.get_work_order(work_order["id"])
        print(f"\n  [工单进度] 已完成:{wo_progress['completed_qty']}/{wo_progress['planned_qty']} | "
              f"合格:{wo_progress['good_qty']} | 不良:{wo_progress['defect_qty']}")
        
        # ========== 步骤 7: IPQC 过程检验 ==========
        print("\n" + "="*60)
        print("【步骤 7】IPQC 过程检验")
        print("="*60)
        
        ipqc_inspection = await self.inspection_service.create_inspection(
            inspection_type="ipqc",
            work_order_id=work_order["id"],
            product_id=product_id,
            batch_size=500,
            aql_level=1.0
        )
        
        # 提交 IPQC 检验结果
        ipqc_result = await self.inspection_service.submit_inspection_result(
            inspection_id=ipqc_inspection["id"],
            inspected_qty=50,
            defective_qty=1,
            inspector_id="qc_zhao"
        )
        
        # ========== 步骤 8: FQC 最终检验 ==========
        print("\n" + "="*60)
        print("【步骤 8】FQC 最终检验")
        print("="*60)
        
        fqc_inspection = await self.inspection_service.create_inspection(
            inspection_type="fqc",
            work_order_id=work_order["id"],
            product_id=product_id,
            batch_size=wo_progress["completed_qty"],
            aql_level=0.65
        )
        
        # 提交 FQC 检验结果
        fqc_result = await self.inspection_service.submit_inspection_result(
            inspection_id=fqc_inspection["id"],
            inspected_qty=80,
            defective_qty=2,
            inspector_id="qc_sun"
        )
        
        # ========== 步骤 9: 工单完成 ==========
        print("\n" + "="*60)
        print("【步骤 9】工单完成 (Complete)")
        print("="*60)
        
        work_order = await self.wo_service.complete_work_order(
            work_order["id"],
            completed_by="manager_li"
        )
        
        # ========== 步骤 10: 成品入库 ==========
        print("\n" + "="*60)
        print("【步骤 10】成品入库")
        print("="*60)
        
        inbound_result = await self.warehouse_service.inbound_finished_goods(
            work_order_id=work_order["id"],
            warehouse_id=warehouse_fg["id"],
            product_id=product_id,
            quantity=wo_progress["good_qty"]
        )
        
        # ========== 工作流完成总结 ==========
        print("\n" + "="*60)
        print("【工单履约完成总结】")
        print("="*60)
        
        final_wo = await self.wo_service.get_work_order(work_order["id"])
        
        print(f"""
  工单编号：{final_wo['work_order_code']}
  产品名称：{final_wo['product_id']}
  销售订单：{final_wo['sales_order_id']}
  
  计划数量：{final_wo['planned_qty']}
  完成数量：{final_wo['completed_qty']}
  合格数量：{final_wo['good_qty']}
  不良数量：{final_wo['defect_qty']}
  
  良品率：{final_wo['good_qty']/final_wo['completed_qty']*100:.2f}%
  达成率：{final_wo['completed_qty']/final_wo['planned_qty']*100:.2f}%
  
  计划开始：{final_wo['planned_start'].strftime('%Y-%m-%d %H:%M')}
  实际开始：{final_wo['actual_start'].strftime('%Y-%m-%d %H:%M') if final_wo['actual_start'] else 'N/A'}
  实际完成：{final_wo['actual_complete'].strftime('%Y-%m-%d %H:%M') if final_wo['actual_complete'] else 'N/A'}
  
  最终状态：{final_wo['status']}
  入库仓库：{warehouse_fg['warehouse_code']}
  入库数量：{inbound_result['quantity']}
        """)
        
        print("="*60)
        print("✅ 工单履约工作流执行完成！")
        print("="*60)
        
        return final_wo


# ==================== 主程序 ====================

async def main():
    """主程序入口"""
    print("\n")
    print("╔" + "═"*58 + "╗")
    print("║" + " "*10 + "MES 工单履约场景工作流演示" + " "*20 + "║")
    print("╚" + "═"*58 + "╝")
    
    workflow = WorkOrderFulfillmentWorkflow()
    result = await workflow.run_workflow()
    
    return result


if __name__ == "__main__":
    asyncio.run(main())
