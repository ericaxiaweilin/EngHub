"""库存流水类型词表 —— 从唯一枚举派生，不再手抄字符串。

历史上这里有三套词汇并存：

- core/wms/inventory.TransactionType：规范枚举（purchase_in/production_in/
  return_in/transfer_in/adjustment_in 与 production_out/sales_out/scrap_out/
  transfer_out/adjustment_out），成本核算 core/cost/costing.py 按它统计消耗。
- api 层写入方各自用字面量 inbound/outbound/transfer，绕过了枚举。
- 虚拟工厂脉搏写 production_out（与枚举一致）和 scenario_hold（枚举里没有）。

读取侧任何一处手抄列表都会随写入方漂移，所以本模块只从枚举派生，
遗留字面量显式标注为 legacy 并等待迁移。
"""

from enum import Enum

from core.wms.inventory import TransactionType


def _values(suffix: str) -> tuple:
    return tuple(v.value for v in TransactionType if v.value.endswith(suffix))


# 真实消耗：让库存减少且代表需求发生的移动。transfer_out 是内部搬移，不算消耗。
CONSUMPTION_TYPES = _values("_out") + ("outbound",)
CONSUMPTION_TYPES = tuple(
    t for t in CONSUMPTION_TYPES if t != TransactionType.TRANSFER_OUT.value
)
# 真实收货：让库存增加且代表供给到达的移动。transfer_in 是内部搬移，不算收货。
RECEIPT_TYPES = _values("_in") + ("inbound",)
RECEIPT_TYPES = tuple(
    t for t in RECEIPT_TYPES if t != TransactionType.TRANSFER_IN.value
)
# 内部移动与状态调整：不改变持有量总量语义，单独成组避免被当成消耗。
INTERNAL_TYPES = (
    TransactionType.TRANSFER_IN.value,
    TransactionType.TRANSFER_OUT.value,
    "transfer",
    "scenario_hold",
    "count_diff",
)

# 兼容旧调用点：OUTBOUND_TYPES/INBOUND_TYPES 之前是手抄字面量，现指向派生集合。
OUTBOUND_TYPES = CONSUMPTION_TYPES
INBOUND_TYPES = RECEIPT_TYPES

ALL_TYPES = CONSUMPTION_TYPES + RECEIPT_TYPES + INTERNAL_TYPES

# 待迁移的遗留字面量（写入侧应改用枚举值，之后从这里删除）。
LEGACY_WRITE_STRINGS = ("inbound", "outbound", "transfer")

__all__ = [
    "CONSUMPTION_TYPES",
    "RECEIPT_TYPES",
    "INTERNAL_TYPES",
    "OUTBOUND_TYPES",
    "INBOUND_TYPES",
    "ALL_TYPES",
    "LEGACY_WRITE_STRINGS",
    "TransactionType",
]
