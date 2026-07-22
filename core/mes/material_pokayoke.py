"""
MES Material Poka-Yoke System (物料防错系统)
功能：齐套检查、扫码防错、批次追溯、FIFO、过期拦截
"""

from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum

class MaterialStatus(Enum):
    OK = "正常"
    LOW_STOCK = "低库存"
    EXPIRED = "过期"

@dataclass
class MaterialItem:
    material_code: str
    batch_no: str
    quantity: int
    manufacture_date: datetime
    expiry_date: datetime
    bin_location: str
    status: MaterialStatus = MaterialStatus.OK
    
    def is_expired(self) -> bool:
        return datetime.now() > self.expiry_date

@dataclass
class BOMItem:
    material_code: str
    required_qty: float
    description: str

@dataclass
class WorkOrderMaterialReq:
    wo_id: str
    bom_items: List[BOMItem]
    planned_qty: int

class MaterialWarehouse:
    def __init__(self):
        self.inventory: Dict[str, List[MaterialItem]] = {}
        self.scan_history: List[Dict] = []

    def add_material(self, item: MaterialItem):
        if item.material_code not in self.inventory:
            self.inventory[item.material_code] = []
        self.inventory[item.material_code].append(item)
        self.inventory[item.material_code].sort(key=lambda x: x.manufacture_date)

    def get_available_batches(self, code: str) -> List[MaterialItem]:
        if code not in self.inventory:
            return []
        return [i for i in self.inventory[code] if i.quantity > 0 and not i.is_expired()]

class MaterialPokaYoke:
    def __init__(self, warehouse: MaterialWarehouse):
        self.warehouse = warehouse
        self.wo_requirements: Dict[str, WorkOrderMaterialReq] = {}
        self.scanned_materials: Dict[str, Dict[str, float]] = {}

    def register_wo_bom(self, req: WorkOrderMaterialReq):
        self.wo_requirements[req.wo_id] = req
        self.scanned_materials[req.wo_id] = {item.material_code: 0.0 for item in req.bom_items}

    def check_kitting(self, wo_id: str) -> Tuple[bool, List[str]]:
        if wo_id not in self.wo_requirements:
            return False, ["工单不存在"]
        req = self.wo_requirements[wo_id]
        errors = []
        for item in req.bom_items:
            available = self.warehouse.get_available_batches(item.material_code)
            total_avail = sum(i.quantity for i in available)
            needed = item.required_qty * req.planned_qty
            if total_avail < needed:
                errors.append(f"物料 {item.material_code} 不足：需{needed}, 有{total_avail}")
        return len(errors) == 0, errors

    def scan_material(self, wo_id: str, material_code: str, batch_no: str, qty: float, operator: str) -> Tuple[bool, str]:
        if wo_id not in self.wo_requirements:
            return False, "工单不存在"
        req = self.wo_requirements[wo_id]
        bom_codes = [i.material_code for i in req.bom_items]
        
        if material_code not in bom_codes:
            return False, f"❌ 错料警报！工单 {wo_id} 不需要物料 {material_code}"
        
        batches = self.warehouse.get_available_batches(material_code)
        target_batch = next((b for b in batches if b.batch_no == batch_no), None)
        
        if not target_batch:
            return False, f"❌ 批次 {batch_no} 不存在或已过期/无库存"
        
        if target_batch.is_expired():
            return False, f"❌ 过期拦截！批次 {batch_no} 已过期"
        
        self.scanned_materials[wo_id][material_code] += qty
        self.warehouse.scan_history.append({
            "time": datetime.now(),
            "action": "SCAN",
            "wo_id": wo_id,
            "code": material_code,
            "batch": batch_no,
            "qty": qty,
            "operator": operator
        })
        
        current = self.scanned_materials[wo_id][material_code]
        needed = next(i.required_qty * req.planned_qty for i in req.bom_items if i.material_code == material_code)
        msg = f"✅ 扫码成功：{material_code} ({batch_no}) x{qty}. 累计:{current}/{needed}"
        if current >= needed:
            msg += " [齐套]"
        return True, msg

    def get_traceability(self, wo_id: str) -> List[Dict]:
        return [h for h in self.warehouse.scan_history if h.get('wo_id') == wo_id]

if __name__ == "__main__":
    print("=== MES 物料防错系统演示 ===")
    wh = MaterialWarehouse()
    mp = MaterialPokaYoke(wh)
    
    now = datetime.now()
    wh.add_material(MaterialItem("M-ESC-001", "B20231001", 1000, now-timedelta(days=10), now+timedelta(days=350), "A-01"))
    wh.add_material(MaterialItem("M-MOTOR-500", "B20231005", 500, now-timedelta(days=5), now+timedelta(days=360), "A-02"))
    wh.add_material(MaterialItem("M-BELT-OLD", "B20220101", 100, now-timedelta(days=400), now-timedelta(days=35), "A-03"))
    
    bom = [
        BOMItem("M-ESC-001", 1.0, "控制器"),
        BOMItem("M-MOTOR-500", 1.0, "电机"),
    ]
    wo_req = WorkOrderMaterialReq("WO-20231027-01", bom, 10)
    mp.register_wo_bom(wo_req)
    
    print("\n1. 齐套检查...")
    ok, errs = mp.check_kitting("WO-20231027-01")
    print(f"   结果：{'通过' if ok else '失败'}")
    
    print("\n2. 正常扫码上料...")
    success, msg = mp.scan_material("WO-20231027-01", "M-ESC-001", "B20231001", 10, "OP-001")
    print(f"   {msg}")
    
    print("\n3. 错料测试...")
    success, msg = mp.scan_material("WO-20231027-01", "M-WRONG-CODE", "B123", 1, "OP-001")
    print(f"   {msg}")
    
    print("\n4. 过期物料拦截测试...")
    # 添加过期物料到仓库再测试
    wh.add_material(MaterialItem("M-BELT-OLD", "B20220101", 100, now-timedelta(days=400), now-timedelta(days=35), "A-03"))
    # 更新 BOM 包含它来测试过期
    bom2 = [BOMItem("M-BELT-OLD", 1.0, "皮带")]
    wo_req2 = WorkOrderMaterialReq("WO-TEST-02", bom2, 1)
    mp.register_wo_bom(wo_req2)
    success, msg = mp.scan_material("WO-TEST-02", "M-BELT-OLD", "B20220101", 1, "OP-001")
    print(f"   {msg}")
    
    print("\n✅ 物料防错演示完成")
