"""
设备维保服务 - 岗位替代 Phase 5: 替代设备维护员
点检/保养/维修工单 + 自动排程 + 故障预测
"""
import uuid
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


def _gen_id() -> str:
    return str(uuid.uuid4())


def _gen_task_code(factory_id: str, task_type: str) -> str:
    prefix = {"inspection": "INS", "lubrication": "LUB", "repair": "REP", "overhaul": "OVH", "calibration": "CAL"}.get(task_type, "MNT")
    ts = datetime.now().strftime("%m%d%H%M")
    suffix = uuid.uuid4().hex[:4].upper()
    return f"{prefix}-{factory_id[:3].upper()}-{ts}-{suffix}"


class MaintenanceService:
    """设备维保服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_task(
        self, factory_id: str, task_type: str, equipment_id: str,
        equipment_name: Optional[str] = None, station_id: Optional[str] = None,
        planned_date: Optional[str] = None, planned_duration_minutes: int = 60,
        priority: str = "medium", assigned_to: Optional[str] = None,
        source: str = "manual", remark: Optional[str] = None,
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """创建维保任务"""
        task_id = _gen_id()
        task_code = _gen_task_code(factory_id, task_type)

        await self.db.execute(text("""
            INSERT INTO maintenance_tasks (id, factory_id, task_code, task_type, priority,
                equipment_id, equipment_name, station_id, planned_date, planned_duration_minutes,
                status, assigned_to, source, remark, created_by, created_at, updated_at)
            VALUES (:id, :fid, :code, :type, :pri, :eid, :ename, :sid, :pdate, :dur,
                'pending', :assigned, :source, :remark, :by, :now, :now)
        """), {
            "id": task_id, "fid": factory_id, "code": task_code, "type": task_type,
            "pri": priority, "eid": equipment_id, "ename": equipment_name,
            "sid": station_id, "pdate": date.fromisoformat(planned_date) if planned_date else date.today(),
            "dur": planned_duration_minutes, "assigned": assigned_to,
            "source": source, "remark": remark, "by": created_by, "now": datetime.utcnow(),
        })
        await self.db.commit()
        return {"id": task_id, "task_code": task_code, "task_type": task_type, "status": "pending"}

    async def add_checklist(self, task_id: str, items: List[Dict]) -> Dict[str, Any]:
        """添加点检项"""
        for i, item in enumerate(items):
            await self.db.execute(text("""
                INSERT INTO maintenance_checklist (id, task_id, seq, item_name, category, standard_value)
                VALUES (:id, :tid, :seq, :name, :cat, :std)
            """), {
                "id": _gen_id(), "tid": task_id, "seq": i + 1,
                "name": item.get("item_name", ""), "cat": item.get("category"),
                "std": item.get("standard_value"),
            })
        await self.db.commit()
        return {"success": True, "items_added": len(items)}

    async def start_task(self, task_id: str, assigned_to: str) -> Dict[str, Any]:
        """开始执行"""
        await self.db.execute(text("""
            UPDATE maintenance_tasks SET status = 'in_progress', assigned_to = :who,
                started_at = :now, updated_at = :now WHERE id = :id
        """), {"who": assigned_to, "now": datetime.utcnow(), "id": task_id})
        await self.db.commit()
        return {"success": True, "status": "in_progress"}

    async def submit_checklist_item(
        self, task_id: str, item_id: str, measured_value: str, is_normal: bool, remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        """提交点检结果"""
        await self.db.execute(text("""
            UPDATE maintenance_checklist SET measured_value = :val, is_normal = :normal, remark = :remark
            WHERE id = :id AND task_id = :tid
        """), {"val": measured_value, "normal": is_normal, "remark": remark, "id": item_id, "tid": task_id})
        await self.db.commit()
        return {"success": True}

    async def complete_task(
        self, task_id: str, result: str, findings: Optional[str] = None,
        parts_used: Optional[str] = None, cost: float = 0,
    ) -> Dict[str, Any]:
        """完成维保任务"""
        now = datetime.utcnow()
        # 计算实际时长
        task_result = await self.db.execute(text(
            "SELECT started_at FROM maintenance_tasks WHERE id = :id"
        ), {"id": task_id})
        task = task_result.mappings().first()
        actual_minutes = int((now - task["started_at"]).total_seconds() / 60) if task and task["started_at"] else 0

        await self.db.execute(text("""
            UPDATE maintenance_tasks SET status = 'completed', result = :result,
                findings = :findings, parts_used = :parts, cost = :cost,
                actual_duration_minutes = :dur, completed_at = :now, updated_at = :now
            WHERE id = :id
        """), {
            "result": result, "findings": findings, "parts": parts_used,
            "cost": cost, "dur": actual_minutes, "now": now, "id": task_id,
        })
        await self.db.commit()
        return {"success": True, "actual_duration_minutes": actual_minutes}

    async def list_tasks(
        self, factory_id: str, task_type: Optional[str] = None, status: Optional[str] = None,
        equipment_id: Optional[str] = None, limit: int = 50,
    ) -> Dict[str, Any]:
        """维保任务列表"""
        query = "SELECT * FROM maintenance_tasks WHERE factory_id = :fid"
        params: Dict[str, Any] = {"fid": factory_id}
        if task_type:
            query += " AND task_type = :type"
            params["type"] = task_type
        if status:
            query += " AND status = :status"
            params["status"] = status
        if equipment_id:
            query += " AND equipment_id = :eid"
            params["eid"] = equipment_id
        query += " ORDER BY planned_date DESC, created_at DESC LIMIT :lim"
        params["lim"] = limit

        result = await self.db.execute(text(query), params)
        return {"items": [dict(r) for r in result.mappings().all()]}

    async def get_task_detail(self, task_id: str) -> Dict[str, Any]:
        """任务详情（含点检项）"""
        task_result = await self.db.execute(text(
            "SELECT * FROM maintenance_tasks WHERE id = :id"
        ), {"id": task_id})
        task = task_result.mappings().first()
        if not task:
            return {"error": "任务不存在"}

        items_result = await self.db.execute(text(
            "SELECT * FROM maintenance_checklist WHERE task_id = :tid ORDER BY seq"
        ), {"tid": task_id})
        return {"task": dict(task), "checklist": [dict(r) for r in items_result.mappings().all()]}

    # ==================== 自动保养排程 ====================

    async def auto_schedule_pm(self, factory_id: str, created_by: str = "system") -> Dict[str, Any]:
        """自动生成预防性保养任务（基于频率）"""
        today = date.today()
        created = 0

        # 查找有保养周期且到期的设备
        result = await self.db.execute(text("""
            SELECT DISTINCT equipment_id, equipment_name, frequency_days
            FROM maintenance_tasks
            WHERE factory_id = :fid AND frequency_days IS NOT NULL AND frequency_days > 0
                AND status = 'completed'
            ORDER BY completed_at DESC
        """), {"fid": factory_id})
        completed = result.mappings().all()

        for row in completed:
            # 检查是否已有未完成的同设备任务
            pending = await self.db.execute(text("""
                SELECT id FROM maintenance_tasks
                WHERE factory_id = :fid AND equipment_id = :eid AND status IN ('pending', 'in_progress')
            """), {"fid": factory_id, "eid": row["equipment_id"]})
            if pending.first():
                continue

            # 检查是否到期
            last_done = await self.db.execute(text("""
                SELECT MAX(completed_at) as last_at FROM maintenance_tasks
                WHERE factory_id = :fid AND equipment_id = :eid AND status = 'completed'
            """), {"fid": factory_id, "eid": row["equipment_id"]})
            last = last_done.mappings().first()
            if last and last["last_at"]:
                next_due = last["last_at"].date() + timedelta(days=row["frequency_days"])
                if next_due <= today:
                    await self.create_task(
                        factory_id=factory_id, task_type="inspection",
                        equipment_id=row["equipment_id"], equipment_name=row["equipment_name"],
                        planned_date=next_due.isoformat(), source="auto_schedule",
                        created_by=created_by,
                    )
                    created += 1

        return {"success": True, "tasks_created": created, "message": f"自动生成 {created} 个保养任务"}

    # ==================== 故障预测 ====================

    async def predict_faults(self, factory_id: str) -> Dict[str, Any]:
        """基于停机历史的故障预测"""
        # 近30天停机统计
        result = await self.db.execute(text("""
            SELECT equipment_id, COUNT(*) as breakdown_count,
                SUM(EXTRACT(EPOCH FROM (COALESCE(end_time, NOW()) - start_time)) / 60) as total_downtime_min
            FROM equipment_downtime
            WHERE factory_id = :fid AND start_time >= NOW() - INTERVAL '30 days'
            GROUP BY equipment_id ORDER BY total_downtime_min DESC LIMIT 10
        """), {"fid": factory_id})
        stats = [dict(r) for r in result.mappings().all()]

        predictions = []
        for s in stats:
            risk = "low"
            if s["breakdown_count"] >= 5 or (s["total_downtime_min"] or 0) > 500:
                risk = "high"
            elif s["breakdown_count"] >= 3 or (s["total_downtime_min"] or 0) > 200:
                risk = "medium"

            predictions.append({
                "equipment_id": s["equipment_id"],
                "breakdown_count_30d": s["breakdown_count"],
                "total_downtime_min": round(s["total_downtime_min"] or 0, 1),
                "risk_level": risk,
                "recommendation": "建议安排预防性检修" if risk == "high" else "加强监控" if risk == "medium" else "正常",
            })

        return {"predictions": predictions, "period": "30天", "high_risk_count": sum(1 for p in predictions if p["risk_level"] == "high")}

    # ==================== 设备读数 ====================

    async def record_reading(
        self, factory_id: str, equipment_id: str, metric_type: str, metric_value: float,
        unit: Optional[str] = None, warning_threshold: Optional[float] = None,
        alarm_threshold: Optional[float] = None, recorded_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录设备读数"""
        is_alarm = False
        if alarm_threshold and metric_value >= alarm_threshold:
            is_alarm = True

        await self.db.execute(text("""
            INSERT INTO equipment_readings (id, factory_id, equipment_id, metric_type, metric_value,
                unit, warning_threshold, alarm_threshold, is_alarm, recorded_at, recorded_by)
            VALUES (:id, :fid, :eid, :type, :val, :unit, :warn, :alarm, :is_alarm, :now, :by)
        """), {
            "id": _gen_id(), "fid": factory_id, "eid": equipment_id,
            "type": metric_type, "val": metric_value, "unit": unit,
            "warn": warning_threshold, "alarm": alarm_threshold,
            "is_alarm": is_alarm, "now": datetime.utcnow(), "by": recorded_by,
        })
        await self.db.commit()

        return {"success": True, "is_alarm": is_alarm, "metric_value": metric_value}
