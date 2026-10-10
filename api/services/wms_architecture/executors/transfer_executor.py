"""Transfer Executor for WMS.

Handles transfer operations between warehouses.
"""

import uuid
from typing import Any, Dict, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, text

from api.services.wms_architecture.executors.base import BaseWmsExecutor
from api.services.wms_architecture.movements import MovementError, apply_transfer_pair
from database.models import Inventory


class TransferExecutor(BaseWmsExecutor):
    """Execute transfer operations."""
    
    def get_operation_name(self) -> str:
        return "transfer"
    
    async def execute(
        self,
        db: AsyncSession,
        factory_id: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute transfer operation.
        
        Args:
            db: Database session
            factory_id: Factory context
            context: {
                "material_id": str,
                "quantity": int,
                "from_warehouse_id": str,
                "to_warehouse_id": str,
                "to_location_id": Optional[str],
                "operator": str,
                "remark": Optional[str],
            }
            
        Returns:
            Transfer operation result
        """
        # Validate context
        errors = self.validate_context(context)
        if errors:
            return {"error": True, "errors": errors}
        
        # Extract parameters
        material_id = context.get("material_id")
        quantity = context.get("quantity", 0)
        from_warehouse_id = context.get("from_warehouse_id")
        to_warehouse_id = context.get("to_warehouse_id")
        to_location_id = context.get("to_location_id")
        operator = context.get("operator", "system")
        remark = context.get("remark")
        
        if from_warehouse_id == to_warehouse_id:
            return {"error": True, "message": "源仓库和目标仓库不能相同"}
        
        now = datetime.utcnow()
        
        # Find source inventory
        src_stmt = select(Inventory).where(
            and_(
                Inventory.factory_id == factory_id,
                Inventory.material_id == material_id,
                Inventory.warehouse_id == from_warehouse_id,
            )
        )
        src_result = await db.execute(src_stmt)
        # 同一仓库里同料号可能有多个批次行：原来用 scalar_one_or_none()，
        # 那样一遇多行就整笔抛 MultipleResultsFound；与终端调拨取同一读法（第一行）
        src_inv = src_result.scalars().first()
        
        if not src_inv:
            return {"error": True, "message": f"源仓库无物料 {material_id} 库存"}
        
        if src_inv.available_qty < quantity:
            return {
                "error": True,
                "message": f"源库存不足：需要 {quantity}，可用 {src_inv.available_qty}",
                "available_qty": src_inv.available_qty,
                "required_qty": quantity,
            }
        
        # 目标行没有就按源行属性建一行空数量库存 —— 数量由成对原语一次写对
        dst_stmt = select(Inventory).where(
            and_(
                Inventory.factory_id == factory_id,
                Inventory.material_id == material_id,
                Inventory.warehouse_id == to_warehouse_id,
            )
        )
        dst_result = await db.execute(dst_stmt)
        dst_inv = dst_result.scalars().first()
        if dst_inv is None:
            dst_inv = Inventory(
                id=str(uuid.uuid4()),
                material_id=material_id,
                material_code=src_inv.material_code,
                material_name=src_inv.material_name,
                factory_id=factory_id,
                warehouse_id=to_warehouse_id,
                location_id=to_location_id,
                batch_code=src_inv.batch_code,
                total_qty=0,
                available_qty=0,
                reserved_qty=0,
                unit=src_inv.unit or "pcs",
                status="available",
                created_at=now,
                updated_at=now,
            )
            db.add(dst_inv)
            await db.flush()

        # 这一格原来是全仓最坏的一处：既自己 `src_inv.total_qty -= quantity`（绕开记账原语，
        # 也就绕开质量冻结守卫 —— 智能体能把冻住的料调走），又自己手写两条
        # transaction_type="transfer" 的遗留流水，还没有单据号，事后说不清谁批的。
        # 现在与终端调拨同一条路：先落调拨单，再由 apply_transfer_pair 一次写两处数量 + 两条流水。
        request_code = f"TR-{(factory_id or '')[:4]}-{now:%Y%m%d%H%M%S}-{str(uuid.uuid4())[:6]}"
        await db.execute(text("""
            INSERT INTO wms_transfer_requests
              (id, factory_id, request_code, material_id, material_code, material_name,
               quantity, from_warehouse_id, to_warehouse_id, to_location_id, status,
               requested_by, approved_by, approved_at, completed_at, remark,
               created_at, updated_at)
            VALUES (:id, :fid, :code, :mid, :mc, :mn, :qty, :fw, :tw, :tl, 'completed',
                    :by, :by, :now, :now, :rm, :now, :now)
        """), {"id": str(uuid.uuid4()), "fid": factory_id, "code": request_code,
               "mid": material_id, "mc": src_inv.material_code,
               "mn": src_inv.material_name, "qty": int(quantity),
               "fw": from_warehouse_id, "tw": to_warehouse_id, "tl": to_location_id,
               "by": operator or "unknown",
               "rm": remark or "智能体调拨（执行人即责任人）", "now": now})

        # rollback 之后 ORM 对象会失效，再读 src_inv 就是一次同步 IO（MissingGreenlet）；
        # 要报给调用方的可用量必须在动手前取好。
        src_available_before = int(src_inv.available_qty or 0)
        try:
            out_txn, in_txn = await apply_transfer_pair(
                db, source=src_inv, target=dst_inv, quantity=int(quantity),
                reference_type="transfer_request", reference_id=request_code,
                reference_doc_no=request_code, operator=operator, remark=remark,
            )
        except MovementError as exc:
            await db.rollback()
            return {"error": True, "message": f"调拨没记成：{exc}",
                    "available_qty": src_available_before}

        await db.commit()
        await db.refresh(src_inv)
        await db.refresh(dst_inv)
        before_src, before_dst = int(out_txn.before_qty), int(in_txn.before_qty)
        after_src, after_dst = int(out_txn.after_qty), int(in_txn.after_qty)
        transfer_request_code = request_code

        return {
            "success": True,
            "type": "transfer",
            "material_id": material_id,
            "material_code": src_inv.material_code,
            "quantity": quantity,
            "from_warehouse_id": from_warehouse_id,
            "to_warehouse_id": to_warehouse_id,
            "before_src": before_src,
            "after_src": after_src,
            "before_dst": before_dst,
            "after_dst": after_dst,
            "transfer_request_code": transfer_request_code,
            "transaction_types": ["transfer_out", "transfer_in"],
            "operator": operator,
            "time": now.isoformat(),
        }
    
    def can_handle(self, operation: str) -> bool:
        return self.get_operation_name() == operation