"""
WMS Inventory Service
库存管理模块

功能:
- 库存查询
- 入库 (采购入库、生产入库、退货入库)
- 出库 (生产领料、销售出库)
- 库存盘点
- FIFO批次管理
"""

import uuid
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from enum import Enum


class TransactionType(str, Enum):
    """库存事务类型"""
    PURCHASE_IN = "purchase_in"       # 采购入库
    PRODUCTION_IN = "production_in"   # 生产入库
    RETURN_IN = "return_in"           # 退货入库
    TRANSFER_IN = "transfer_in"        # 调拨入库
    ADJUSTMENT_IN = "adjustment_in"   # 盘盈入库
    
    PRODUCTION_OUT = "production_out" # 生产领料
    SALES_OUT = "sales_out"           # 销售出库
    SCRAP_OUT = "scrap_out"           # 报废出库
    TRANSFER_OUT = "transfer_out"      # 调拨出库
    ADJUSTMENT_OUT = "adjustment_out"  # 盘亏出库


class InventoryStatus(str, Enum):
    """库存状态"""
    AVAILABLE = "available"     # 可用
    RESERVED = "reserved"       # 预留
    QC_HOLD = "qc_hold"         # 待验
    FROZEN = "frozen"           # 冻结
    QUARANTINE = "quarantine"   # 隔离


class InventoryService:
    """
    库存服务
    
    核心功能:
    - 库存查询 (可用量、预留量)
    - 入库操作 (自动生成批次号)
    - 出库操作 (FIFO策略)
    - 库存盘点
    """
    
    def __init__(self, db_pool=None):
        self.db_pool = db_pool
    
    def generate_batch_code(self, material_code: str) -> str:
        """生成批次号"""
        today = date.today().strftime("%Y%m%d")
        random_suffix = str(uuid.uuid4())[:6].upper()
        return f"BATCH-{material_code}-{today}-{random_suffix}"
    
    async def get_inventory(
        self,
        material_id: str,
        warehouse_id: str = None,
    ) -> Dict[str, Any]:
        """获取库存信息"""
        inventory = {
            "material_id": material_id,
            "warehouse_id": warehouse_id,
            "total_qty": 10000,
            "available_qty": 9500,
            "reserved_qty": 300,
            "qc_hold_qty": 100,
            "frozen_qty": 0,
            "batches": [],
        }
        
        # TODO: 查询实际库存
        
        return inventory
    
    async def list_inventory(
        self,
        factory_id: str,
        warehouse_id: str = None,
        material_id: str = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取库存列表"""
        return []
    
    async def inbound(
        self,
        factory_id: str,
        warehouse_id: str,
        material_id: str,
        material_code: str,
        quantity: float,
        batch_code: str = None,
        supplier_id: str = None,
        purchase_order_id: str = None,
        production_order_id: str = None,
        unit_cost: float = None,
        location_id: str = None,
        transaction_type: str = TransactionType.PURCHASE_IN.value,
        reference_id: str = None,
        created_by: str = None,
    ) -> Dict[str, Any]:
        """
        入库操作
        
        Args:
            batch_code: 批次号，不指定则自动生成
            transaction_type: 入库类型
        """
        # 自动生成批次号
        if not batch_code:
            batch_code = self.generate_batch_code(material_code)
        
        # 创建入库记录
        inbound_record = {
            "id": str(uuid.uuid4()),
            "transaction_type": transaction_type,
            "factory_id": factory_id,
            "warehouse_id": warehouse_id,
            "material_id": material_id,
            "material_code": material_code,
            "quantity": quantity,
            "batch_code": batch_code,
            "supplier_id": supplier_id,
            "purchase_order_id": purchase_order_id,
            "production_order_id": production_order_id,
            "unit_cost": unit_cost,
            "location_id": location_id,
            "reference_id": reference_id,
            "status": "completed",
            "created_by": created_by,
            "created_at": datetime.now(),
        }
        
        # 创建批次库存记录
        batch_inventory = {
            "id": str(uuid.uuid4()),
            "material_id": material_id,
            "batch_code": batch_code,
            "warehouse_id": warehouse_id,
            "location_id": location_id,
            "quantity": quantity,
            "available_qty": quantity,
            "supplier_id": supplier_id,
            "receive_date": date.today(),
            "manufacture_date": None,
            "expire_date": None,
            "unit_cost": unit_cost,
            "status": InventoryStatus.AVAILABLE.value,
        }
        
        return {
            "inbound_record": inbound_record,
            "batch_inventory": batch_inventory,
        }
    
    async def outbound(
        self,
        factory_id: str,
        warehouse_id: str,
        material_id: str,
        quantity: float,
        work_order_id: str = None,
        sales_order_id: str = None,
        batch_code: str = None,
        location_id: str = None,
        transaction_type: str = TransactionType.PRODUCTION_OUT.value,
        reference_id: str = None,
        created_by: str = None,
    ) -> Dict[str, Any]:
        """
        出库操作
        
        支持FIFO策略: 不指定批次时自动选择最早入库的批次
        """
        # 获取出库批次 (FIFO策略)
        outbound_batches = await self._get_fifo_batches(
            material_id=material_id,
            warehouse_id=warehouse_id,
            required_qty=quantity,
            exclude_batch=batch_code,
        )
        
        if sum(b["quantity"] for b in outbound_batches) < quantity:
            raise ValueError(f"库存不足，当前可用: {sum(b['quantity'] for b in outbound_batches)}, 需要: {quantity}")
        
        # 创建出库记录
        outbound_record = {
            "id": str(uuid.uuid4()),
            "transaction_type": transaction_type,
            "factory_id": factory_id,
            "warehouse_id": warehouse_id,
            "material_id": material_id,
            "quantity": quantity,
            "work_order_id": work_order_id,
            "sales_order_id": sales_order_id,
            "batch_code": batch_code,
            "location_id": location_id,
            "reference_id": reference_id,
            "outbound_batches": outbound_batches,
            "status": "completed",
            "created_by": created_by,
            "created_at": datetime.now(),
        }
        
        return outbound_record
    
    async def _get_fifo_batches(
        self,
        material_id: str,
        warehouse_id: str,
        required_qty: float,
        exclude_batch: str = None,
    ) -> List[Dict[str, Any]]:
        """获取FIFO批次 (最早入库的批次)"""
        batches = []
        
        # TODO: 查询实际批次数据，按入库日期排序
        
        # 示例数据
        if required_qty <= 1000:
            batches = [{"batch_code": "BATCH-MAT-001-20260220-ABC123", "quantity": 1000, "unit_cost": 10.0}]
        else:
            batches = [
                {"batch_code": "BATCH-MAT-001-20260220-ABC123", "quantity": 1000, "unit_cost": 10.0},
                {"batch_code": "BATCH-MAT-001-20260221-DEF456", "quantity": 1000, "unit_cost": 10.5},
            ]
        
        return batches
    
    async def reserve_inventory(
        self,
        material_id: str,
        warehouse_id: str,
        quantity: float,
        work_order_id: str,
        reserved_by: str = None,
    ) -> Dict[str, Any]:
        """预留库存"""
        reserve_record = {
            "id": str(uuid.uuid4()),
            "material_id": material_id,
            "warehouse_id": warehouse_id,
            "quantity": quantity,
            "work_order_id": work_order_id,
            "status": "reserved",
            "reserved_by": reserved_by,
            "reserved_at": datetime.now(),
        }
        
        return reserve_record
    
    async def create_inventory_count(
        self,
        factory_id: str,
        warehouse_id: str,
        count_date: date,
        count_type: str = "periodic",
        created_by: str = None,
    ) -> Dict[str, Any]:
        """创建盘点单"""
        count_record = {
            "id": str(uuid.uuid4()),
            "factory_id": factory_id,
            "warehouse_id": warehouse_id,
            "count_date": count_date,
            "count_type": count_type,
            "status": "draft",
            "created_by": created_by,
            "created_at": datetime.now(),
        }
        
        return count_record
    
    async def submit_count_result(
        self,
        count_id: str,
        items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        提交盘点结果
        
        items: [
            {
                "material_id": "MAT-001",
                "batch_code": "BATCH-001",
                "system_qty": 1000,
                "counted_qty": 980,
                "difference": -20,
            }
        ]
        """
        # 计算差异
        total_system_qty = sum(item["system_qty"] for item in items)
        total_counted_qty = sum(item["counted_qty"] for item in items)
        total_difference = total_counted_qty - total_system_qty
        
        # 生成调整建议
        adjustments = []
        for item in items:
            if item["difference"] != 0:
                adjustments.append({
                    "material_id": item["material_id"],
                    "batch_code": item["batch_code"],
                    "difference": item["difference"],
                    "adjustment_type": "increase" if item["difference"] > 0 else "decrease",
                })
        
        result = {
            "count_id": count_id,
            "total_system_qty": total_system_qty,
            "total_counted_qty": total_counted_qty,
            "total_difference": total_difference,
            "adjustments": adjustments,
            "status": "pending_approval" if adjustments else "completed",
        }
        
        return result
    
    async def get_material_trace(
        self,
        material_id: str,
        batch_code: str = None,
    ) -> Dict[str, Any]:
        """物料追溯"""
        trace = {
            "material_id": material_id,
            "batch_code": batch_code,
            "inbound_records": [],
            "outbound_records": [],
            "current_location": None,
        }
        
        # TODO: 查询追溯数据
        
        return trace


__all__ = [
    "InventoryService",
    "TransactionType",
    "InventoryStatus",
]
