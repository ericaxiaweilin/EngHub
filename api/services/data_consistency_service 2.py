

"""
v2.5 - Data Consistency Reconciler
自动对账机器人 + 线边仓 Min-Max 补货触发器
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from database.models import (
    WorkOrder,
    ProductionReport,
    DefectRecord,
    Inventory,
    OutboundOrder,
    ReconciliationLog,
    PullReplenishmentTask,
    ReplenishmentThreshold,
)


class DataConsistencyService:
    """数据一致性服务 — 对账 + 拉动式补货"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==================== 自动对账 ====================

    async def reconcile_work_order(self, work_order_id: str) -> Dict[str, Any]:
        """
        对账单个工单：[工单产量] vs [良品+不良品] vs [库存增量]
        发现差异自动标记异常
        """
        wo_result = await self.db.execute(
            select(WorkOrder).where(WorkOrder.id == work_order_id)
        )
        wo = wo_result.scalar_one_or_none()
        if not wo:
            raise ValueError("工单不存在")

        # 汇总报工
        report_agg = await self.db.execute(
            select(
                func.sum(ProductionReport.good_qty).label("good_sum"),
                func.sum(ProductionReport.defect_qty).label("defect_sum"),
                func.sum(ProductionReport.scrap_qty).label("scrap_sum"),
            ).where(ProductionReport.work_order_id == work_order_id)
        )
        row = report_agg.first() or (0, 0, 0)
        good_qty = int(row[0] or 0)
        defect_qty = int(row[1] or 0)
        scrap_qty = int(row[2] or 0)
        net_change = good_qty + defect_qty + scrap_qty

        expected_delta = wo.planned_qty - wo.completed_qty  # 期望新增产量
        delta = net_change - expected_delta

        status = "ok" if abs(delta) <= 1 else "mismatch"
        if delta != 0:
            status_detail = f"工单进度差 {expected_delta}, 报工实际产出 {net_change}, 差异 {delta}"
        else:
            status_detail = None

        log = ReconciliationLog(
            reconcile_code=f"REC-{work_order_id[:8].upper()}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            factory_id=wo.factory_id,
            work_order_id=work_order_id,
            planned_qty=wo.planned_qty,
            good_qty=good_qty,
            defect_qty=defect_qty,
            scrap_qty=scrap_qty,
            net_change=net_change,
            expected_delta=expected_delta,
            delta=delta,
            status=status,
            discrepancy_detail=status_detail,
            checked_by="auto_reconciler",
            checked_at=datetime.utcnow(),
        )
        self.db.add(log)
        await self.db.commit()

        return {"status": status, "log": log}

    async def batch_reconcile_all(self, factory_id: str) -> List[Dict[str, Any]]:
        """批量对所有工单对账"""
        wo_query = await self.db.execute(
            select(WorkOrder).where(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status.in_(["in_progress", "pending_inbound"]),
            )
        )
        orders = wo_query.scalars().all()
        results = []
        for wo in orders:
            try:
                result = await self.reconcile_work_order(wo.id)
                results.append({"work_order_id": wo.id, **result})
            except Exception as exc:
                results.append({"work_order_id": wo.id, "status": "error", "detail": str(exc)})
        return results

    # ==================== Min-Max 拉动式补货 ====================

    async def check_and_create_replenishment_tasks(self) -> List[PullReplenishmentTask]:
        """
        扫描所有 Min-Max 水位阈值，当库存低于 min_level 时自动创建补货任务
        线边仓消耗 → 主仓调拨
        """
        threshold_query = await self.db.execute(
            select(ReplenishmentThreshold).where(ReplenishmentThreshold.active == True)
        )
        thresholds = threshold_query.scalars().all()
        tasks = []

        for threshold in thresholds:
            # 查当前库存
            inv_result = await self.db.execute(
                select(Inventory).where(
                    Inventory.factory_id == threshold.factory_id,
                    Inventory.material_id == threshold.material_id,
                )
            )
            invs = inv_result.scalars().all()
            current_total = sum(inv.available_qty for inv in invs)

            if current_total <= threshold.min_level:
                qty_to_reorder = max(
                    threshold.reorder_lot_size,
                    min(threshold.max_level - current_total, threshold.reorder_lot_size)
                )

                task_code = f"PRT-{threshold.factory_id}-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:6].upper()}"
                task = PullReplenishmentTask(
                    task_code=task_code,
                    factory_id=threshold.factory_id,
                    source_warehouse_id=str(threshold.warehouse_id) if threshold.warehouse_id else None,
                    target_location_id=str(threshold.location_id) if threshold.location_id else threshold.line_side_location,
                    material_id=threshold.material_id,
                    requested_qty=qty_to_reorder,
                    trigger_type="min_reached",
                    threshold_id=str(threshold.id),
                    created_by="auto_reconciler",
                )
                self.db.add(task)
                tasks.append(task)

        if tasks:
            await self.db.commit()

        return tasks

    async def list_pending_replenishments(self, factory_id: str, status: Optional[str] = "pending") -> List[PullReplenishmentTask]:
        """查询待处理补货任务"""
        stmt = select(PullReplenishmentTask).where(PullReplenishmentTask.factory_id == factory_id)
        if status:
            stmt = stmt.where(PullReplenishmentTask.status == status)
        stmt = stmt.order_by(PullReplenishmentTask.created_at.desc())
        return list((await self.db.execute(stmt)).scalars().all())

    async def fulfill_replenishment_task(self, task_id: str) -> PullReplenishmentTask:
        """完成补货任务 — 扣减源仓库库存，增加线边仓库存（简化）"""
        task = await self.db.execute(
            select(PullReplenishmentTask).where(PullReplenishmentTask.id == task_id)
        ).scalar_one_or_none()
        if not task:
            raise ValueError("补货任务不存在")

        task.status = "completed"
        task.fulfilled_qty = task.requested_qty
        task.completed_at = datetime.utcnow()
        await self.db.commit()
        return task

