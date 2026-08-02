"""
WMS Module - Warehouse Management System
库存管理、入库、出库、盘点
"""

from .inventory import InventoryService
from .warehouse import WarehouseService

__all__ = [
    "InventoryService",
    "WarehouseService",
]
