"""
设备维保服务 - 岗位替代 Phase 5: 替代设备维护员
点检/保养/维修工单 + 自动排程 + 故障预测 + 点检模板 + SOP + 备件请购
"""
import uuid
import json
import logging
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

_logger = logging.getLogger("maintenance")


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
            SELECT equipment_id, equipment_name, frequency_days
            FROM maintenance_tasks
            WHERE factory_id = :fid AND frequency_days IS NOT NULL AND frequency_days > 0
                AND status = 'completed'
            GROUP BY equipment_id, equipment_name, frequency_days
            ORDER BY MAX(completed_at) DESC
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

    # ==================== 点检模板自动生成 ====================

    # 按设备类型的标准点检模板
    INSPECTION_TEMPLATES: Dict[str, List[Dict]] = {
        "CNC": [
            {"item_name": "主轴温度", "category": "温度", "standard_value": "≤ 60℃"},
            {"item_name": "导轨润滑", "category": "润滑", "standard_value": "油膜均匀"},
            {"item_name": "冷却液液位", "category": "液位", "standard_value": "≥ 2/3"},
            {"item_name": "刀具磨损", "category": "刀具", "standard_value": "磨损量≤0.2mm"},
            {"item_name": "气压表读数", "category": "气压", "standard_value": "0.5-0.7MPa"},
            {"item_name": "异响/振动", "category": "声音", "standard_value": "无异常"},
        ],
        "注塑机": [
            {"item_name": "模具温度", "category": "温度", "standard_value": "按工艺卡"},
            {"item_name": "液压油温", "category": "温度", "standard_value": "≤ 55℃"},
            {"item_name": "射嘴清洁", "category": "清洁", "standard_value": "无堵塞"},
            {"item_name": "安全门开关", "category": "安全", "standard_value": "灵敏可靠"},
            {"item_name": "加热圈电流", "category": "电气", "standard_value": "额定±10%"},
        ],
        "SMT": [
            {"item_name": "吸嘴真空度", "category": "真空", "standard_value": "≥ -60kPa"},
            {"item_name": "锡膏厚度", "category": "印刷", "standard_value": "0.12-0.15mm"},
            {"item_name": "回流焊温度曲线", "category": "温度", "standard_value": "峰值 245±5℃"},
            {"item_name": "抛料率", "category": "质量", "standard_value": "≤ 0.3%"},
            {"item_name": "导轨清洁", "category": "清洁", "standard_value": "无锡珠残留"},
        ],
        "default": [
            {"item_name": "外观检查", "category": "外观", "standard_value": "无损伤/渗漏"},
            {"item_name": "运行声音", "category": "声音", "standard_value": "无异响"},
            {"item_name": "润滑状态", "category": "润滑", "standard_value": "油位正常"},
            {"item_name": "安全防护", "category": "安全", "standard_value": "护罩/急停正常"},
            {"item_name": "清洁状态", "category": "清洁", "standard_value": "无积尘/杂物"},
        ],
    }

    async def generate_inspection_checklist(self, equipment_id: str, task_id: str) -> Dict[str, Any]:
        """根据设备类型自动生成点检项"""
        # 获取设备类型
        eq_result = await self.db.execute(text(
            "SELECT equipment_type, equipment_name FROM equipment WHERE id = :id"
        ), {"id": equipment_id})
        eq = eq_result.mappings().first()
        eq_type = eq["equipment_type"] if eq else None

        # 匹配模板（模糊匹配：包含关键词即可）
        template = self.INSPECTION_TEMPLATES.get("default")
        if eq_type:
            for key, items in self.INSPECTION_TEMPLATES.items():
                if key != "default" and key.lower() in (eq_type or "").lower():
                    template = items
                    break

        # 写入点检项
        await self.add_checklist(task_id, template)
        return {
            "success": True,
            "equipment_type": eq_type,
            "items_generated": len(template),
            "template_used": [t["item_name"] for t in template],
        }

    # ==================== 维修 SOP 推送 ====================

    REPAIR_SOPS: Dict[str, List[Dict[str, str]]] = {
        "主轴故障": [
            {"step": "1", "action": "停机并挂牌上锁", "safety": "必须"},
            {"step": "2", "action": "检查主轴温度、异响、振动", "tool": "红外测温仪/振动笔"},
            {"step": "3", "action": "检查轴承间隙（轴向/径向）", "tool": "百分表"},
            {"step": "4", "action": "检查润滑系统（油量/油泵/油路）", "tool": ""},
            {"step": "5", "action": "更换轴承或调整预紧力", "tool": "专用拉马"},
            {"step": "6", "action": "试运行 30min，监测温升≤ 15℃", "safety": "试运行前确认护罩安装"},
        ],
        "液压泄漏": [
            {"step": "1", "action": "停机卸压", "safety": "必须"},
            {"step": "2", "action": "定位泄漏点（密封圈/油管/接头）", "tool": ""},
            {"step": "3", "action": "更换密封件或紧固接头", "tool": "扭矩扳手"},
            {"step": "4", "action": "补充液压油至标准液位", "tool": ""},
            {"step": "5", "action": "试压运行，观察 10min 无渗漏", "safety": "戴护目镜"},
        ],
        "电气故障": [
            {"step": "1", "action": "断电并验电", "safety": "必须，挂禁止合闸牌"},
            {"step": "2", "action": "检查报警代码，查阅电气原理图", "tool": "万用表"},
            {"step": "3", "action": "检查接触器/继电器/保险丝", "tool": "万用表"},
            {"step": "4", "action": "检查接线端子是否松动/烧蚀", "tool": ""},
            {"step": "5", "action": "更换故障元件，紧固接线", "tool": ""},
            {"step": "6", "action": "送电试运行，确认报警消除", "safety": "送电前确认人员撤离"},
        ],
    }

    async def get_repair_sop(self, fault_type: str) -> Dict[str, Any]:
        """根据故障类型获取维修 SOP"""
        # 模糊匹配
        sop = None
        matched_key = None
        for key, steps in self.REPAIR_SOPS.items():
            if key in fault_type or fault_type in key:
                sop = steps
                matched_key = key
                break

        if not sop:
            # 通用 SOP
            sop = [
                {"step": "1", "action": "停机并确认安全", "safety": "必须"},
                {"step": "2", "action": "记录故障现象（拍照/录像）", "tool": ""},
                {"step": "3", "action": "分析故障原因", "tool": ""},
                {"step": "4", "action": "执行维修/更换", "tool": ""},
                {"step": "5", "action": "试运行确认", "safety": "确认防护装置复位"},
            ]
            matched_key = "通用维修"

        return {"fault_type": fault_type, "matched_sop": matched_key, "steps": sop, "total_steps": len(sop)}

    # ==================== 备件自动请购 ====================

    async def check_spare_parts_and_suggest(self, factory_id: str, parts_used: str) -> Dict[str, Any]:
        """维修完成后检查备件库存，不足则生成请购建议。

        parts_used 格式："物料编码:数量,物料编码:数量" 或 JSON
        """
        suggestions = []
        parts_list = []

        # 解析 parts_used
        try:
            parts_list = json.loads(parts_used)
        except (json.JSONDecodeError, TypeError):
            # 尝试 "CODE:QTY,CODE:QTY" 格式
            if parts_used and ":" in parts_used:
                for item in parts_used.split(","):
                    parts = item.strip().split(":")
                    if len(parts) == 2:
                        parts_list.append({"material_code": parts[0].strip(), "qty": int(parts[1].strip())})

        for part in parts_list:
            code = part.get("material_code", "")
            used_qty = part.get("qty", 0)
            if not code:
                continue

            # 查询库存
            inv_result = await self.db.execute(text("""
                SELECT COALESCE(SUM(available_qty), 0) as avail
                FROM inventory WHERE factory_id = :fid AND material_code = :code
            """), {"fid": factory_id, "code": code})
            avail = inv_result.scalar() or 0

            # 安全库存 = 用量 * 2（简化）
            safety_stock = used_qty * 2
            if avail < safety_stock:
                suggestions.append({
                    "material_code": code,
                    "current_stock": int(avail),
                    "used_in_repair": used_qty,
                    "safety_stock": safety_stock,
                    "suggested_order_qty": max(safety_stock - int(avail), used_qty),
                    "urgency": "high" if avail == 0 else "medium",
                })

        return {
            "parts_checked": len(parts_list),
            "suggestions": suggestions,
            "need_purchase": len(suggestions) > 0,
            "message": f"{len(suggestions)} 种备件需请购" if suggestions else "备件库存充足",
        }
