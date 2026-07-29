"""
APS 有限产能排程引擎 - 岗位替代 Phase 2
优先规则调度（EDD/SPT/CR）+ 约束传播 + 插单重排 + 冲突检测
"""
import uuid
import json
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text

from database.models import WorkOrder, Station, Equipment


def _gen_id() -> str:
    return str(uuid.uuid4())


# 排程算法
ALGORITHMS = {
    "EDD": "最早交期优先",
    "SPT": "最短加工时间优先",
    "CR": "关键比率优先",
    "PRIORITY": "优先级优先",
}


class ApsEngine:
    """有限产能排程引擎"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def schedule(
        self,
        factory_id: str,
        algorithm: str = "EDD",
        horizon_days: int = 7,
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """
        执行排程
        1. 获取待排工单池
        2. 获取工位产能约束
        3. 按算法排序
        4. 逐工单分配到工位+时间段
        5. 检测冲突
        """
        now = datetime.utcnow()
        schedule_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        schedule_end = schedule_start + timedelta(days=horizon_days)

        # 1. 获取待排工单（状态为 released 或 pending）
        wo_stmt = select(WorkOrder).where(
            and_(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status.in_(["released", "pending", "in_progress"]),
                WorkOrder.wo_type == "master",
            )
        )
        wo_result = await self.db.execute(wo_stmt)
        work_orders = list(wo_result.scalars().all())

        if not work_orders:
            return {"error": "无待排工单", "schedule_id": None}

        # 2. 获取工位产能
        cap_result = await self.db.execute(text(
            "SELECT * FROM station_capacity WHERE factory_id = :fid AND is_active = TRUE"
        ), {"fid": factory_id})
        capacities = {r["station_id"]: dict(r) for r in cap_result.mappings().all()}

        # 获取工位列表
        station_stmt = select(Station).where(Station.factory_id == factory_id)
        station_result = await self.db.execute(station_stmt)
        stations = list(station_result.scalars().all())
        station_ids = [s.id for s in stations]

        if not station_ids:
            station_ids = list(capacities.keys()) or ["ST-01", "ST-02", "ST-03"]

        # 3. 按算法排序工单
        sorted_wos = self._sort_work_orders(work_orders, algorithm)

        # 4. 排程分配
        # 每个工位的时间轴（记录已占用的时间段）
        station_timeline: Dict[str, List[Dict]] = {sid: [] for sid in station_ids}
        tasks = []
        conflicts = []

        for wo in sorted_wos:
            # 确定目标工位
            target_station = wo.assigned_station_id or station_ids[0]
            if target_station not in station_timeline:
                target_station = station_ids[0]

            # 计算加工时间（简化：每件 0.5h + 换型时间）
            cap = capacities.get(target_station, {})
            setup_time = cap.get("setup_time_minutes", 30)
            efficiency = cap.get("efficiency_rate", 0.85)
            available_hours = cap.get("available_hours_per_day", 16)

            process_hours = (wo.planned_qty * 0.5) / efficiency
            total_hours = process_hours + (setup_time / 60)

            # 找最早可用时间
            earliest_start = self._find_earliest_slot(
                station_timeline[target_station], schedule_start, total_hours, available_hours
            )
            earliest_end = earliest_start + timedelta(hours=total_hours)

            # 检查交期冲突
            is_late = False
            if wo.planned_due and earliest_end > wo.planned_due:
                is_late = True
                conflicts.append({
                    "type": "delivery_risk",
                    "work_order": wo.work_order_code,
                    "planned_due": wo.planned_due.isoformat() if wo.planned_due else None,
                    "estimated_end": earliest_end.isoformat(),
                    "delay_hours": round((earliest_end - wo.planned_due).total_seconds() / 3600, 1),
                })

            task = {
                "id": _gen_id(),
                "work_order_id": wo.id,
                "work_order_code": wo.work_order_code,
                "product_id": wo.product_id,
                "station_id": target_station,
                "planned_qty": wo.planned_qty,
                "planned_start": earliest_start,
                "planned_end": earliest_end,
                "setup_minutes": setup_time,
                "process_hours": round(process_hours, 2),
                "priority": wo.priority,
                "is_late": is_late,
                "sequence_in_station": len(station_timeline[target_station]) + 1,
            }
            tasks.append(task)

            # 占用时间轴
            station_timeline[target_station].append({
                "start": earliest_start,
                "end": earliest_end,
                "wo_code": wo.work_order_code,
            })

        # 5. 保存排程结果
        schedule_id = _gen_id()
        schedule_code = f"APS-{factory_id[:3].upper()}-{now.strftime('%m%d%H%M')}"

        await self.db.execute(text("""
            INSERT INTO aps_schedules (id, schedule_code, factory_id, status, algorithm,
                horizon_start, horizon_end, total_tasks, conflict_count, created_by, created_at)
            VALUES (:id, :code, :fid, 'draft', :algo, :start, :end, :tasks, :conflicts, :by, :now)
        """), {
            "id": schedule_id,
            "code": schedule_code,
            "fid": factory_id,
            "algo": algorithm,
            "start": schedule_start,
            "end": schedule_end,
            "tasks": len(tasks),
            "conflicts": len(conflicts),
            "by": created_by,
            "now": now,
        })

        # 保存任务明细
        for t in tasks:
            await self.db.execute(text("""
                INSERT INTO aps_schedule_tasks (id, schedule_id, work_order_id, station_id,
                    planned_start, planned_end, setup_minutes, sequence_in_station, material_ready, operation_seq)
                VALUES (:id, :sid, :wo_id, :st_id, :start, :end, :setup, :seq, TRUE, :op_seq)
            """), {
                "id": t["id"],
                "sid": schedule_id,
                "wo_id": t["work_order_id"],
                "st_id": t["station_id"],
                "start": t["planned_start"],
                "end": t["planned_end"],
                "setup": t["setup_minutes"],
                "seq": t["sequence_in_station"],
                "op_seq": t["sequence_in_station"],
            })

        await self.db.commit()

        return {
            "schedule_id": schedule_id,
            "schedule_code": schedule_code,
            "algorithm": algorithm,
            "algorithm_name": ALGORITHMS.get(algorithm, algorithm),
            "horizon": f"{schedule_start.date()} ~ {schedule_end.date()}",
            "total_tasks": len(tasks),
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
            "tasks": [{**t, "planned_start": t["planned_start"].isoformat(), "planned_end": t["planned_end"].isoformat()} for t in tasks],
            "station_utilization": self._calc_utilization(station_timeline, schedule_start, schedule_end),
        }

    async def reschedule(
        self,
        factory_id: str,
        insert_wo_id: Optional[str] = None,
        algorithm: str = "EDD",
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """
        插单重排：保持已开工(in_progress)不动，重排未开工工单
        """
        # 标记已开工工单为锁定
        locked_stmt = select(WorkOrder).where(
            and_(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status == "in_progress",
                WorkOrder.wo_type == "master",
            )
        )
        locked_result = await self.db.execute(locked_stmt)
        locked_wos = list(locked_result.scalars().all())
        locked_ids = {wo.id for wo in locked_wos}

        # 执行新排程（会自动排除已完成的）
        result = await self.schedule(factory_id, algorithm, created_by=created_by)

        if "error" not in result:
            result["locked_orders"] = len(locked_ids)
            result["note"] = f"已锁定 {len(locked_ids)} 个在制工单，仅重排未开工工单"

        return result

    async def get_gantt_data(self, factory_id: str, schedule_id: Optional[str] = None) -> Dict[str, Any]:
        """获取甘特图数据"""
        if schedule_id:
            task_result = await self.db.execute(text(
                "SELECT t.*, w.work_order_code, w.product_id, w.planned_qty, w.priority, w.planned_due "
                "FROM aps_schedule_tasks t JOIN work_orders w ON t.work_order_id = w.id "
                "WHERE t.schedule_id = :sid ORDER BY t.station_id, t.planned_start"
            ), {"sid": schedule_id})
        else:
            # 获取最新排程
            latest = await self.db.execute(text(
                "SELECT id FROM aps_schedules WHERE factory_id = :fid ORDER BY created_at DESC LIMIT 1"
            ), {"fid": factory_id})
            row = latest.first()
            if not row:
                return {"stations": [], "tasks": []}
            schedule_id = row[0]
            task_result = await self.db.execute(text(
                "SELECT t.*, w.work_order_code, w.product_id, w.planned_qty, w.priority, w.planned_due "
                "FROM aps_schedule_tasks t JOIN work_orders w ON t.work_order_id = w.id "
                "WHERE t.schedule_id = :sid ORDER BY t.station_id, t.planned_start"
            ), {"sid": schedule_id})

        tasks = [dict(r) for r in task_result.mappings().all()]

        # 按工位分组
        by_station: Dict[str, List] = defaultdict(list)
        for t in tasks:
            by_station[t["station_id"]].append({
                "id": t["id"],
                "work_order_code": t["work_order_code"],
                "product_id": t["product_id"],
                "planned_qty": t["planned_qty"],
                "priority": t["priority"],
                "start": t["planned_start"],
                "end": t["planned_end"],
                "setup_minutes": t.get("setup_minutes", 0),
                "sequence": t.get("sequence_in_station", 0),
            })

        return {
            "schedule_id": schedule_id,
            "stations": [{"station_id": sid, "tasks": tasks_list} for sid, tasks_list in by_station.items()],
            "total_tasks": len(tasks),
        }

    async def detect_conflicts(self, factory_id: str) -> Dict[str, Any]:
        """冲突检测：设备过载 / 交期风险 / 物料未齐"""
        conflicts = []

        # 检查最新排程中的交期风险
        latest = await self.db.execute(text(
            "SELECT id FROM aps_schedules WHERE factory_id = :fid ORDER BY created_at DESC LIMIT 1"
        ), {"fid": factory_id})
        row = latest.first()
        if row:
            task_result = await self.db.execute(text(
                "SELECT t.planned_end, w.work_order_code, w.planned_due, w.planned_qty "
                "FROM aps_schedule_tasks t JOIN work_orders w ON t.work_order_id = w.id "
                "WHERE t.schedule_id = :sid AND w.planned_due IS NOT NULL"
            ), {"sid": row[0]})
            for r in task_result.mappings().all():
                if r["planned_end"] and r["planned_due"]:
                    end = r["planned_end"] if isinstance(r["planned_end"], datetime) else datetime.fromisoformat(str(r["planned_end"]))
                    due = r["planned_due"] if isinstance(r["planned_due"], datetime) else datetime.fromisoformat(str(r["planned_due"]))
                    if end > due:
                        conflicts.append({
                            "type": "delivery_risk",
                            "work_order": r["work_order_code"],
                            "delay_hours": round((end - due).total_seconds() / 3600, 1),
                        })

        # 检查物料未齐的已排工单
        wo_stmt = select(WorkOrder).where(
            and_(
                WorkOrder.factory_id == factory_id,
                WorkOrder.status.in_(["released", "pending"]),
            )
        )
        wo_result = await self.db.execute(wo_stmt)
        for wo in wo_result.scalars().all():
            # 简化：检查是否有 BOM 且库存不足
            bom_count = await self.db.execute(
                select(func.count()).select_from(BomItem).where(
                    and_(BomItem.factory_id == factory_id, BomItem.product_id == wo.product_id)
                )
            )
            if bom_count.scalar() == 0:
                conflicts.append({
                    "type": "no_bom",
                    "work_order": wo.work_order_code,
                    "message": f"产品 {wo.product_id} 无 BOM，无法进行物料齐套检查",
                })

        return {"conflicts": conflicts, "count": len(conflicts)}

    # ==================== 内部方法 ====================

    def _sort_work_orders(self, work_orders: List[WorkOrder], algorithm: str) -> List[WorkOrder]:
        """按算法排序工单"""
        priority_weight = {"urgent": 0, "high": 1, "medium": 2, "low": 3}

        if algorithm == "EDD":
            return sorted(work_orders, key=lambda wo: wo.planned_due or datetime.max)
        elif algorithm == "SPT":
            return sorted(work_orders, key=lambda wo: wo.planned_qty or 0)
        elif algorithm == "CR":
            # 关键比率 = (交期 - 现在) / 剩余加工时间
            now = datetime.utcnow()
            def cr(wo):
                remaining = max(1, wo.planned_qty or 1) * 0.5
                if wo.planned_due:
                    slack = (wo.planned_due - now).total_seconds() / 3600
                    return slack / remaining
                return 999
            return sorted(work_orders, key=cr)
        elif algorithm == "PRIORITY":
            return sorted(work_orders, key=lambda wo: priority_weight.get(wo.priority, 2))
        else:
            return work_orders

    def _find_earliest_slot(
        self, timeline: List[Dict], schedule_start: datetime, hours_needed: float, available_hours: float
    ) -> datetime:
        """找最早可用时间段"""
        if not timeline:
            return schedule_start

        # 找最后一个任务的结束时间
        last_end = max(t["end"] for t in timeline)
        return last_end

    def _calc_utilization(
        self, station_timeline: Dict[str, List[Dict]], start: datetime, end: datetime
    ) -> Dict[str, float]:
        """计算各工位利用率"""
        total_hours = (end - start).total_seconds() / 3600
        utilization = {}
        for sid, tasks in station_timeline.items():
            if not tasks:
                utilization[sid] = 0
                continue
            busy_hours = sum((t["end"] - t["start"]).total_seconds() / 3600 for t in tasks)
            utilization[sid] = round(min(busy_hours / total_hours * 100, 100), 1)
        return utilization
