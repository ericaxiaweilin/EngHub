"""库存流水的唯一词表 + 唯一写入原语 —— 数量与流水必须同时落。

历史上这里有三套词汇并存：

- core/wms/inventory.TransactionType：规范枚举（purchase_in/production_in/
  return_in/transfer_in/adjustment_in 与 production_out/sales_out/scrap_out/
  transfer_out/adjustment_out），成本核算 core/cost/costing.py 按它统计消耗。
- api 层写入方各自用字面量 inbound/outbound/transfer，绕过了枚举。
- 种子脚本 scripts/seed_mech_workflows.py 直接 INSERT 枚举外的 scenario_hold，
  以及没有 before/after、没有单据号的 production_out（线上 93 条 production_out
  全部来自这个脚本，虚拟工厂脉搏一条流水都不写）。

读取侧任何一处手抄列表都会随写入方漂移，所以本模块只从枚举派生，
遗留字面量显式标注为 legacy 并等待迁移。
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from core.wms.inventory import TransactionType
from database.models import InventoryTransaction


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


# ── 写入侧唯一原语 ─────────────────────────────────────────────────────
#
# "有单无账"的根因：单据落了库、库存数量也改了，唯独流水没写。
# 所以这里把"改数量 + 记流水"合成一个动作，并强制要求可追溯锚点：
# 宁可让收货/出库当场失败，也不留一笔回溯不到的库存量。

# 领料必须挂到工单（成本与齐套要归到对象）；销售出库的锚点是单据本身。
WORK_ORDER_ANCHORED_TYPES = (TransactionType.PRODUCTION_OUT.value,)

INBOUND_TYPE_BY_DOC: Dict[str, TransactionType] = {
    "purchase": TransactionType.PURCHASE_IN,
    "production": TransactionType.PRODUCTION_IN,
    "return": TransactionType.RETURN_IN,
    "adjustment": TransactionType.ADJUSTMENT_IN,
}
OUTBOUND_TYPE_BY_DOC: Dict[str, TransactionType] = {
    "production": TransactionType.PRODUCTION_OUT,
    "sales": TransactionType.SALES_OUT,
    "shipment": TransactionType.SALES_OUT,
    "scrap": TransactionType.SCRAP_OUT,
    "adjustment": TransactionType.ADJUSTMENT_OUT,
}


class MovementError(ValueError):
    """记不了账：锚点缺失、数量不合法或类型认不出来。"""
# 调拨的两个方向。`apply_movement` 故意不收这两个类型 —— 单边记账等于把货变出来或变没了，
# 调拨必须成对：源出一、目标入，同一张单据号下两条流水一起落。
TRANSFER_OUT = TransactionType.TRANSFER_OUT.value
TRANSFER_IN = TransactionType.TRANSFER_IN.value


async def apply_transfer_pair(
    db: Any,
    *,
    source: Any,
    target: Any,
    quantity: int,
    reference_type: str,
    reference_id: str,
    reference_doc_no: str,
    operator: Optional[str] = None,
    remark: Optional[str] = None,
) -> tuple:
    """一次调拨 = 两条流水 + 两处数量变更，全部在一个事务里。

    为什么要单独一个原语而不是调两次 `apply_movement`：
    · 那个原语按"收货/消耗"分类，调拨两边都不属于（`transfer_out` 不是消耗、
      `transfer_in` 不是收货 —— 货没离开厂）；
    · 分两次调就可能只成一次：源扣了、目标没加，库存凭空消失；
    · 两边必须挂同一个 `reference_doc_no`，否则事后无法证明这两条是同一笔搬移。

    数量恒为正（与 `apply_movement` 同一约定），方向由流水类型决定。
    历史上那 89 条 `transaction_type='transfer'` 且带负数量、没有单据号的流水
    就是这个约定没立住留下的，保留原样、不回填。
    """
    qty = int(quantity)
    if qty <= 0:
        raise MovementError(f"调拨数量必须是正整数，收到 {quantity!r}")
    if not (reference_id or "").strip() or not (reference_doc_no or "").strip():
        raise MovementError("调拨缺少单据锚点（reference_id / reference_doc_no），拒绝记账")
    if source is None or target is None:
        raise MovementError("调拨必须有源库存行和目标库存行")
    if source.id == target.id:
        raise MovementError("源与目标是同一行库存，这不是一次搬移")
    if int(source.available_qty or 0) < qty:
        raise MovementError(
            f"源库存可用量不足：available={source.available_qty} 需移 {qty}")

    now = datetime.utcnow()
    src_before = int(source.total_qty or 0)
    tgt_before = int(target.total_qty or 0)
    source.total_qty = src_before - qty
    source.available_qty = int(source.available_qty or 0) - qty
    source.last_movement_at = now
    source.updated_at = now
    target.total_qty = tgt_before + qty
    target.available_qty = int(target.available_qty or 0) + qty
    target.last_movement_at = now
    target.updated_at = now

    out_txn = InventoryTransaction(
        id=str(uuid.uuid4()), factory_id=source.factory_id, inventory_id=source.id,
        material_id=source.material_id, batch_code=source.batch_code,
        transaction_type=TRANSFER_OUT, quantity=qty,
        before_qty=src_before, after_qty=src_before - qty,
        reference_type=reference_type, reference_id=reference_id,
        reference_doc_no=reference_doc_no, operator=operator,
        remark=remark or "调拨出", created_at=now,
    )
    in_txn = InventoryTransaction(
        id=str(uuid.uuid4()), factory_id=target.factory_id, inventory_id=target.id,
        material_id=target.material_id, batch_code=target.batch_code or source.batch_code,
        transaction_type=TRANSFER_IN, quantity=qty,
        before_qty=tgt_before, after_qty=tgt_before + qty,
        reference_type=reference_type, reference_id=reference_id,
        reference_doc_no=reference_doc_no, operator=operator,
        remark=remark or "调拨入", created_at=now,
    )
    db.add(out_txn)
    db.add(in_txn)
    return out_txn, in_txn




def document_movement_type(direction: str, doc_type: Optional[str]) -> str:
    """单据类型 -> 规范流水类型。认不出来就拒，不再新增第 4 套写法。"""
    table = {"in": INBOUND_TYPE_BY_DOC, "out": OUTBOUND_TYPE_BY_DOC}.get(direction)
    if table is None:
        raise MovementError(f"未知的记账方向 {direction!r}（只支持 in/out）")
    member = table.get((doc_type or "").strip().lower())
    if member is None:
        raise MovementError(
            f"{'入库' if direction == 'in' else '出库'}类型 {doc_type!r} 无法映射到流水词表，"
            f"可用值：{'、'.join(sorted(table))}"
        )
    return member.value


async def apply_movement(
    db: Any,
    *,
    inventory: Any,
    transaction_type: str,
    quantity: int,
    reference_type: str,
    reference_id: str,
    reference_doc_no: str,
    work_order_id: Optional[str] = None,
    operator: Optional[str] = None,
    remark: Optional[str] = None,
) -> Any:
    """同一事务里改一处库存并记一条流水。quantity 恒为正，方向由流水类型决定。

    线上已有的 183 条流水就是"正数量 + 类型带方向"的约定，沿用它，不改成有符号数。
    """
    qty = int(quantity)
    if qty <= 0:
        raise MovementError(f"流水数量必须是正整数，收到 {quantity!r}")
    if not (reference_id or "").strip() or not (reference_doc_no or "").strip():
        raise MovementError("流水缺少单据锚点（reference_id / reference_doc_no），拒绝记账")
    if transaction_type in LEGACY_WRITE_STRINGS:
        raise MovementError(
            f"{transaction_type!r} 是待迁移的遗留字面量，新流水一律写规范类型"
            f"（{TransactionType.PURCHASE_IN.value}/{TransactionType.PRODUCTION_OUT.value} 等）"
        )
    if transaction_type in WORK_ORDER_ANCHORED_TYPES and not (work_order_id or "").strip():
        raise MovementError(f"{transaction_type} 必须挂 work_order_id，否则领料归不到工单")
    if transaction_type in CONSUMPTION_TYPES:
        delta = -qty
    elif transaction_type in RECEIPT_TYPES:
        delta = qty
    else:
        raise MovementError(
            f"{transaction_type} 既不是收货也不是消耗类型；调拨/盘点要成对记账，走各自路径"
        )

    before = int(inventory.total_qty or 0)
    after = before + delta
    if after < 0:
        raise MovementError(
            f"库存 {inventory.id} 不足以扣减 {qty}（当前 total_qty={before}）"
        )
    available = int(inventory.available_qty or 0)
    if available + delta < 0:
        raise MovementError(
            f"可用量不足：batch={inventory.batch_code} available={available} 需扣 {qty}"
        )
    inventory.total_qty = after
    inventory.available_qty = available + delta
    inventory.last_movement_at = datetime.utcnow()

    txn = InventoryTransaction(
        id=str(uuid.uuid4()),
        factory_id=inventory.factory_id,
        inventory_id=inventory.id,
        material_id=inventory.material_id,
        batch_code=inventory.batch_code,
        transaction_type=transaction_type,
        quantity=qty,
        before_qty=before,
        after_qty=after,
        reference_type=reference_type,
        reference_id=reference_id,
        reference_doc_no=reference_doc_no,
        work_order_id=work_order_id,
        operator=operator,
        remark=remark,
        created_at=datetime.utcnow(),
    )
    db.add(txn)
    return txn


__all__ = [
    "CONSUMPTION_TYPES",
    "RECEIPT_TYPES",
    "INTERNAL_TYPES",
    "OUTBOUND_TYPES",
    "INBOUND_TYPES",
    "ALL_TYPES",
    "LEGACY_WRITE_STRINGS",
    "WORK_ORDER_ANCHORED_TYPES",
    "MovementError",
    "document_movement_type",
    "apply_movement",
    "TransactionType",
]
