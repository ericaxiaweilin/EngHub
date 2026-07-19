"""
MES 线边仓管理与物料防错模块

功能：
1. 齐套检查：工单开工前强制校验物料齐套
2. 扫码防错：关键件安装前扫码比对 BOM
3. 批次追溯：记录成品使用的物料批次
4. 库存预警：线边仓库存低于安全水位自动报警
5. 先进先出 (FIFO)：物料出库遵循 FIFO 原则

作者：MES Development Team
日期：2026-05-24
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
import uuid
from collections import defaultdict

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MaterialStatus(Enum):
    """物料状态"""
    AVAILABLE = "AVAILABLE"  # 可用
    RESERVED = "RESERVED"  # 已预留
    IN_USE = "IN_USE"  # 使用中
    EXPIRED = "EXPIRED"  # 过期
    QUARANTINED = "QUARANTINED"  # 隔离
    CONSUMED = "CONSUMED"  # 已消耗


class CheckResult(Enum):
    """检查结果"""
    PASS = "PASS"  # 通过
    FAIL = "FAIL"  # 失败
    WARNING = "WARNING"  # 警告


@dataclass
class MaterialBatch:
    """物料批次"""
    batch_id: str
    material_code: str
    material_name: str
    quantity: int
    remaining_quantity: int
    supplier: str
    production_date: datetime
    expiry_date: Optional[datetime]
    received_at: datetime
    location: str  # 库位
    status: MaterialStatus = MaterialStatus.AVAILABLE
    inspection_status: str = "PENDING"  # PENDING/PASSED/FAILED
    
    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "material_code": self.material_code,
            "material_name": self.material_name,
            "quantity": self.quantity,
            "remaining_quantity": self.remaining_quantity,
            "supplier": self.supplier,
            "production_date": self.production_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "received_at": self.received_at.isoformat(),
            "location": self.location,
            "status": self.status.value,
            "inspection_status": self.inspection_status
        }


@dataclass
class BOMItem:
    """BOM 项目"""
    material_code: str
    material_name: str
    quantity_per_unit: float
    unit: str
    is_critical: bool = False  # 是否关键件
    alternative_codes: List[str] = field(default_factory=list)  # 可替代料号


@dataclass
class WorkOrderMaterialRequirement:
    """工单物料需求"""
    work_order_id: str
    material_code: str
    required_quantity: float
    reserved_quantity: float = 0.0
    consumed_quantity: float = 0.0
    is_kitted: bool = False
    
    def get_shortage(self) -> float:
        """计算缺料数量"""
        return self.required_quantity - self.reserved_quantity


@dataclass
class MaterialScanRecord:
    """物料扫码记录"""
    record_id: str
    workstation_id: str
    work_order_id: str
    serial_number: str  # 成品 SN
    material_batch_id: str
    material_code: str
    scanned_at: datetime
    scanned_by: str
    check_result: CheckResult
    error_message: str = ""


class LineSideWarehouse:
    """线边仓管理类"""
    
    def __init__(self):
        self.material_batches: Dict[str, MaterialBatch] = {}  # batch_id -> MaterialBatch
        self.material_inventory: Dict[str, List[str]] = defaultdict(list)  # material_code -> [batch_ids]
        self.safety_stock_levels: Dict[str, float] = {}  # material_code -> safety_stock
        self.low_stock_alerts: List[dict] = []
    
    def add_material_batch(self, batch: MaterialBatch):
        """添加物料批次"""
        self.material_batches[batch.batch_id] = batch
        self.material_inventory[batch.material_code].append(batch.batch_id)
        
        logger.info(f"📦 物料批次入库：{batch.batch_id}")
        logger.info(f"   物料：{batch.material_code} - {batch.material_name}")
        logger.info(f"   数量：{batch.quantity}, 库位：{batch.location}")
        logger.info(f"   供应商：{batch.supplier}, 生产日期：{batch.production_date.strftime('%Y-%m-%d')}")
        
        # 检查是否过期
        if batch.expiry_date and batch.expiry_date < datetime.now():
            batch.status = MaterialStatus.EXPIRED
            logger.warning(f"   ⚠️ 物料已过期！")
        
        # 检查库存水位
        self._check_safety_stock(batch.material_code)
    
    def _check_safety_stock(self, material_code: str):
        """检查安全库存"""
        if material_code not in self.safety_stock_levels:
            return
        
        total_available = self.get_available_quantity(material_code)
        safety_level = self.safety_stock_levels[material_code]
        
        if total_available < safety_level:
            alert = {
                "material_code": material_code,
                "current_quantity": total_available,
                "safety_level": safety_level,
                "shortage": safety_level - total_available,
                "alert_time": datetime.now()
            }
            self.low_stock_alerts.append(alert)
            logger.warning(f"⚠️ 库存预警：{material_code} 当前库存 {total_available} < 安全水位 {safety_level}")
    
    def get_available_quantity(self, material_code: str) -> float:
        """获取可用库存数量"""
        if material_code not in self.material_inventory:
            return 0.0
        
        total = 0.0
        for batch_id in self.material_inventory[material_code]:
            batch = self.material_batches.get(batch_id)
            if batch and batch.status == MaterialStatus.AVAILABLE:
                total += batch.remaining_quantity
        
        return total
    
    def get_batches_by_fifo(self, material_code: str, required_quantity: float) -> List[MaterialBatch]:
        """按 FIFO 原则获取物料批次"""
        if material_code not in self.material_inventory:
            return []
        
        batches = []
        remaining_needed = required_quantity
        
        # 按接收时间排序（FIFO）
        sorted_batch_ids = sorted(
            self.material_inventory[material_code],
            key=lambda bid: self.material_batches[bid].received_at
        )
        
        for batch_id in sorted_batch_ids:
            batch = self.material_batches[batch_id]
            if batch.status != MaterialStatus.AVAILABLE:
                continue
            
            if batch.remaining_quantity >= remaining_needed:
                # 当前批次足够
                batches.append(batch)
                break
            else:
                # 使用整个批次
                batches.append(batch)
                remaining_needed -= batch.remaining_quantity
        
        return batches
    
    def reserve_material(self, batch_id: str, quantity: float) -> bool:
        """预留物料"""
        if batch_id not in self.material_batches:
            return False
        
        batch = self.material_batches[batch_id]
        if batch.status != MaterialStatus.AVAILABLE:
            logger.warning(f"物料批次 {batch_id} 状态为 {batch.status.value}, 无法预留")
            return False
        
        if batch.remaining_quantity < quantity:
            logger.warning(f"物料批次 {batch_id} 剩余数量 {batch.remaining_quantity} < 需求 {quantity}")
            return False
        
        batch.remaining_quantity -= quantity
        if batch.remaining_quantity == 0:
            batch.status = MaterialStatus.CONSUMED
        
        logger.info(f"✅ 预留物料：{batch.batch_id}, 数量：{quantity}")
        return True
    
    def consume_material(self, batch_id: str, quantity: float, serial_number: str) -> bool:
        """消耗物料（绑定到产品 SN）"""
        if batch_id not in self.material_batches:
            return False
        
        batch = self.material_batches[batch_id]
        # 允许从 RESERVED 或 AVAILABLE 状态消耗
        if batch.status not in [MaterialStatus.AVAILABLE, MaterialStatus.RESERVED]:
            return False
        
        if batch.remaining_quantity < quantity:
            return False
        
        batch.remaining_quantity -= quantity
        if batch.remaining_quantity == 0:
            batch.status = MaterialStatus.CONSUMED
        
        logger.info(f"🔧 消耗物料：{batch.batch_id}, 数量：{quantity}, 绑定 SN: {serial_number}")
        return True


class MaterialKittingSystem:
    """物料齐套系统"""
    
    def __init__(self, warehouse: LineSideWarehouse):
        self.warehouse = warehouse
        self.bom_definitions: Dict[str, List[BOMItem]] = {}  # product_code -> [BOMItem]
        self.work_order_requirements: Dict[str, List[WorkOrderMaterialRequirement]] = {}
    
    def define_bom(self, product_code: str, bom_items: List[BOMItem]):
        """定义产品 BOM"""
        self.bom_definitions[product_code] = bom_items
        logger.info(f"📋 定义 BOM: {product_code}, 共 {len(bom_items)} 项物料")
    
    def calculate_material_requirements(
        self,
        work_order_id: str,
        product_code: str,
        quantity: int
    ) -> List[WorkOrderMaterialRequirement]:
        """计算工单物料需求"""
        if product_code not in self.bom_definitions:
            logger.error(f"产品 {product_code} 的 BOM 未定义")
            return []
        
        requirements = []
        for bom_item in self.bom_definitions[product_code]:
            required_qty = bom_item.quantity_per_unit * quantity
            
            req = WorkOrderMaterialRequirement(
                work_order_id=work_order_id,
                material_code=bom_item.material_code,
                required_quantity=required_qty
            )
            requirements.append(req)
        
        self.work_order_requirements[work_order_id] = requirements
        logger.info(f"📊 工单 {work_order_id} 物料需求计算完成，共 {len(requirements)} 项")
        
        return requirements
    
    def check_kitting_status(self, work_order_id: str) -> tuple[CheckResult, dict]:
        """检查工单齐套状态"""
        if work_order_id not in self.work_order_requirements:
            return CheckResult.FAIL, {"error": "工单物料需求未计算"}
        
        requirements = self.work_order_requirements[work_order_id]
        result_detail = {
            "work_order_id": work_order_id,
            "total_items": len(requirements),
            "kitted_items": 0,
            "shortage_items": [],
            "is_kitted": False
        }
        
        all_kitted = True
        for req in requirements:
            available_qty = self.warehouse.get_available_quantity(req.material_code)
            
            if available_qty >= req.required_quantity:
                req.is_kitted = True
                result_detail["kitted_items"] += 1
            else:
                all_kitted = False
                shortage = req.required_quantity - available_qty
                result_detail["shortage_items"].append({
                    "material_code": req.material_code,
                    "required": req.required_quantity,
                    "available": available_qty,
                    "shortage": shortage
                })
        
        result_detail["is_kitted"] = all_kitted
        
        if all_kitted:
            logger.info(f"✅ 工单 {work_order_id} 齐套检查通过")
            return CheckResult.PASS, result_detail
        else:
            logger.warning(f"❌ 工单 {work_order_id} 齐套检查失败，缺少 {len(result_detail['shortage_items'])} 项物料")
            return CheckResult.FAIL, result_detail
    
    def reserve_materials_for_work_order(self, work_order_id: str) -> bool:
        """为工单预留物料"""
        check_result, detail = self.check_kitting_status(work_order_id)
        if check_result != CheckResult.PASS:
            logger.error(f"工单 {work_order_id} 未齐套，无法预留物料")
            return False
        
        requirements = self.work_order_requirements[work_order_id]
        
        for req in requirements:
            batches = self.warehouse.get_batches_by_fifo(req.material_code, req.required_quantity)
            
            remaining_to_reserve = req.required_quantity
            for batch in batches:
                reserve_qty = min(batch.remaining_quantity, remaining_to_reserve)
                if not self.warehouse.reserve_material(batch.batch_id, reserve_qty):
                    logger.error(f"预留物料失败：{batch.batch_id}")
                    return False
                remaining_to_reserve -= reserve_qty
                
                if remaining_to_reserve <= 0:
                    break
            
            req.reserved_quantity = req.required_quantity
        
        logger.info(f"✅ 工单 {work_order_id} 物料预留完成")
        return True


class MaterialAntiErrorSystem:
    """物料防错系统"""
    
    def __init__(self, warehouse: LineSideWarehouse, kitting_system: MaterialKittingSystem):
        self.warehouse = warehouse
        self.kitting_system = kitting_system
        self.scan_records: List[MaterialScanRecord] = []
        self.sn_material_binding: Dict[str, Dict[str, str]] = defaultdict(dict)  # SN -> {material_code: batch_id}
    
    def scan_material(
        self,
        workstation_id: str,
        work_order_id: str,
        serial_number: str,
        material_batch_id: str,
        operator_id: str
    ) -> tuple[CheckResult, str]:
        """扫码防错检查"""
        # 检查批次是否存在
        if material_batch_id not in self.warehouse.material_batches:
            return CheckResult.FAIL, f"物料批次 {material_batch_id} 不存在"
        
        batch = self.warehouse.material_batches[material_batch_id]
        
        # 检查物料状态
        if batch.status not in [MaterialStatus.AVAILABLE, MaterialStatus.RESERVED]:
            return CheckResult.FAIL, f"物料状态异常：{batch.status.value}"
        
        # 检查是否过期
        if batch.expiry_date and batch.expiry_date < datetime.now():
            return CheckResult.FAIL, f"物料已过期：{batch.expiry_date.strftime('%Y-%m-%d')}"
        
        # 检查工单物料需求
        if work_order_id not in self.kitting_system.work_order_requirements:
            return CheckResult.WARNING, f"工单 {work_order_id} 未定义物料需求（非关键件可能允许）"
        
        requirements = self.kitting_system.work_order_requirements[work_order_id]
        material_required = any(req.material_code == batch.material_code for req in requirements)
        
        if not material_required:
            return CheckResult.FAIL, f"物料 {batch.material_code} 不在工单 BOM 中"
        
        # 记录扫码
        record_id = f"SCAN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
        record = MaterialScanRecord(
            record_id=record_id,
            workstation_id=workstation_id,
            work_order_id=work_order_id,
            serial_number=serial_number,
            material_batch_id=material_batch_id,
            material_code=batch.material_code,
            scanned_at=datetime.now(),
            scanned_by=operator_id,
            check_result=CheckResult.PASS
        )
        
        self.scan_records.append(record)
        
        # 绑定 SN 与物料批次
        self.sn_material_binding[serial_number][batch.material_code] = material_batch_id
        
        logger.info(f"✅ 扫码通过：SN={serial_number}, 物料={batch.material_code}, 批次={batch.batch_id}")
        
        return CheckResult.PASS, "扫码验证通过"
    
    def get_material_traceability(self, serial_number: str) -> dict:
        """获取成品的物料追溯信息"""
        if serial_number not in self.sn_material_binding:
            return {"error": f"SN {serial_number} 无物料绑定记录"}
        
        bindings = self.sn_material_binding[serial_number]
        traceability = {
            "serial_number": serial_number,
            "materials": []
        }
        
        for material_code, batch_id in bindings.items():
            batch = self.warehouse.material_batches.get(batch_id)
            if batch:
                traceability["materials"].append({
                    "material_code": material_code,
                    "batch_id": batch_id,
                    "supplier": batch.supplier,
                    "production_date": batch.production_date.strftime('%Y-%m-%d'),
                    "expiry_date": batch.expiry_date.strftime('%Y-%m-%d') if batch.expiry_date else None
                })
        
        return traceability
    
    def get_batch_usage(self, batch_id: str) -> List[str]:
        """获取批次物料被用于哪些成品"""
        used_in_sn = []
        for sn, bindings in self.sn_material_binding.items():
            for mat_code, b_id in bindings.items():
                if b_id == batch_id:
                    used_in_sn.append(sn)
        return used_in_sn


def demonstrate_material_system():
    """演示物料管理系统功能"""
    print("=" * 80)
    print("MES 线边仓管理与物料防错演示")
    print("=" * 80)
    
    # 初始化仓库
    warehouse = LineSideWarehouse()
    warehouse.safety_stock_levels = {
        "MOTOR-001": 50,
        "CONTROLLER-002": 30,
        "BELT-003": 100,
        "BLUETOOTH-MOD-004": 50
    }
    
    # 创建物料批次
    print("\n📦 步骤 1: 物料入库")
    print("-" * 80)
    
    batches = [
        MaterialBatch(
            batch_id="BATCH-20260520-001",
            material_code="MOTOR-001",
            material_name="跑步机电机 2.5HP",
            quantity=100,
            remaining_quantity=100,
            supplier="ABB Motors",
            production_date=datetime(2026, 5, 1),
            expiry_date=None,
            received_at=datetime(2026, 5, 20),
            location="A-01-01"
        ),
        MaterialBatch(
            batch_id="BATCH-20260520-002",
            material_code="CONTROLLER-002",
            material_name="主控制器 PCB",
            quantity=80,
            remaining_quantity=80,
            supplier="Foxconn",
            production_date=datetime(2026, 5, 15),
            expiry_date=datetime(2027, 5, 15),
            received_at=datetime(2026, 5, 20),
            location="A-02-01"
        ),
        MaterialBatch(
            batch_id="BATCH-20260521-003",
            material_code="BELT-003",
            material_name="跑步带 1500mm",
            quantity=200,
            remaining_quantity=200,
            supplier="Continental",
            production_date=datetime(2026, 5, 10),
            expiry_date=None,
            received_at=datetime(2026, 5, 21),
            location="B-01-01"
        ),
        MaterialBatch(
            batch_id="BATCH-20260522-004",
            material_code="BLUETOOTH-MOD-004",
            material_name="蓝牙模块 nRF52832",
            quantity=150,
            remaining_quantity=150,
            supplier="Nordic Semi",
            production_date=datetime(2026, 5, 18),
            expiry_date=datetime(2028, 5, 18),
            received_at=datetime(2026, 5, 22),
            location="A-03-01"
        )
    ]
    
    for batch in batches:
        warehouse.add_material_batch(batch)
    
    # 定义 BOM
    print("\n📋 步骤 2: 定义产品 BOM")
    print("-" * 80)
    
    kitting_system = MaterialKittingSystem(warehouse)
    
    bom_items = [
        BOMItem(
            material_code="MOTOR-001",
            material_name="跑步机电机 2.5HP",
            quantity_per_unit=1.0,
            unit="台",
            is_critical=True
        ),
        BOMItem(
            material_code="CONTROLLER-002",
            material_name="主控制器 PCB",
            quantity_per_unit=1.0,
            unit="块",
            is_critical=True
        ),
        BOMItem(
            material_code="BELT-003",
            material_name="跑步带 1500mm",
            quantity_per_unit=1.0,
            unit="条",
            is_critical=False
        ),
        BOMItem(
            material_code="BLUETOOTH-MOD-004",
            material_name="蓝牙模块 nRF52832",
            quantity_per_unit=1.0,
            unit="个",
            is_critical=True
        )
    ]
    
    kitting_system.define_bom("TM-X500", bom_items)
    
    # 计算工单物料需求
    print("\n📊 步骤 3: 计算工单物料需求")
    print("-" * 80)
    
    work_order_id = "WO-20260524-001"
    requirements = kitting_system.calculate_material_requirements(work_order_id, "TM-X500", 50)
    
    for req in requirements:
        print(f"   {req.material_code}: 需求 {req.required_quantity}")
    
    # 齐套检查
    print("\n✅ 步骤 4: 齐套检查")
    print("-" * 80)
    
    check_result, detail = kitting_system.check_kitting_status(work_order_id)
    
    print(f"齐套状态：{'通过 ✅' if check_result == CheckResult.PASS else '失败 ❌'}")
    print(f"齐套物料数：{detail['kitted_items']}/{detail['total_items']}")
    
    if detail['shortage_items']:
        print("缺料明细:")
        for item in detail['shortage_items']:
            print(f"   {item['material_code']}: 需求 {item['required']}, 可用 {item['available']}, 缺口 {item['shortage']}")
    
    # 预留物料
    print("\n🔒 步骤 5: 物料预留")
    print("-" * 80)
    
    if kitting_system.reserve_materials_for_work_order(work_order_id):
        print("物料预留成功")
    
    # 扫码防错
    print("\n📱 步骤 6: 扫码防错演示")
    print("-" * 80)
    
    anti_error_system = MaterialAntiErrorSystem(warehouse, kitting_system)
    
    # 正常扫码
    test_scans = [
        ("LINE-1-STATION-02", work_order_id, "SN-TM-X500-0001", "BATCH-20260520-001", "OP-001"),
        ("LINE-1-STATION-02", work_order_id, "SN-TM-X500-0001", "BATCH-20260520-002", "OP-001"),
        ("LINE-1-STATION-02", work_order_id, "SN-TM-X500-0001", "BATCH-20260522-004", "OP-001"),
    ]
    
    for scan_params in test_scans:
        result, message = anti_error_system.scan_material(*scan_params)
        print(f"   扫码结果：{result.value} - {message}")
    
    # 错误扫码演示（过期物料）
    print("\n⚠️ 步骤 7: 错误扫码演示（过期物料）")
    print("-" * 80)
    
    expired_batch = MaterialBatch(
        batch_id="BATCH-20250101-005",
        material_code="MOTOR-001",
        material_name="跑步机电机 2.5HP",
        quantity=50,
        remaining_quantity=50,
        supplier="Old Supplier",
        production_date=datetime(2024, 1, 1),
        expiry_date=datetime(2025, 1, 1),  # 已过期
        received_at=datetime(2025, 1, 5),
        location="C-01-01"
    )
    warehouse.add_material_batch(expired_batch)
    
    result, message = anti_error_system.scan_material(
        "LINE-1-STATION-02",
        work_order_id,
        "SN-TM-X500-0002",
        "BATCH-20250101-005",
        "OP-002"
    )
    print(f"   扫码结果：{result.value} - {message}")
    
    # 物料追溯
    print("\n🔍 步骤 8: 物料追溯查询")
    print("-" * 80)
    
    traceability = anti_error_system.get_material_traceability("SN-TM-X500-0001")
    
    print(f"成品 SN: {traceability['serial_number']}")
    print("使用物料:")
    for mat in traceability['materials']:
        print(f"   {mat['material_code']}:")
        print(f"      批次：{mat['batch_id']}")
        print(f"      供应商：{mat['supplier']}")
        print(f"      生产日期：{mat['production_date']}")
        if mat['expiry_date']:
            print(f"      有效期至：{mat['expiry_date']}")
    
    # 批次使用情况
    print("\n📊 步骤 9: 批次使用追溯")
    print("-" * 80)
    
    usage = anti_error_system.get_batch_usage("BATCH-20260520-001")
    print(f"批次 BATCH-20260520-001 用于以下成品:")
    for sn in usage:
        print(f"   {sn}")
    
    # 库存预警报告
    print("\n⚠️ 步骤 10: 库存预警报告")
    print("-" * 80)
    
    if warehouse.low_stock_alerts:
        print(f"当前库存预警数：{len(warehouse.low_stock_alerts)}")
        for alert in warehouse.low_stock_alerts:
            print(f"   {alert['material_code']}: 当前 {alert['current_quantity']} < 安全水位 {alert['safety_level']}")
    else:
        print("无库存预警")
    
    print("\n" + "=" * 80)
    print("物料管理系统演示完成")
    print("=" * 80)


if __name__ == "__main__":
    demonstrate_material_system()
