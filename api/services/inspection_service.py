"""
检验服务 - 岗位替代 Phase 4: 替代质检员
IQC/IPQC/FQC/OQC 检验工作流 + 检验项 Checklist
"""
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


def _gen_id() -> str:
    return str(uuid.uuid4())


def _gen_task_code(factory_id: str, inspect_type: str) -> str:
    ts = datetime.now().strftime("%m%d%H%M")
    suffix = uuid.uuid4().hex[:4].upper()
    return f"{inspect_type}-{factory_id[:3].upper()}-{ts}-{suffix}"


class InspectionService:
    """检验任务工作流服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_task(
        self,
        factory_id: str,
        inspect_type: str,
        material_code: Optional[str] = None,
        material_name: Optional[str] = None,
        product_id: Optional[str] = None,
        work_order_id: Optional[str] = None,
        station_id: Optional[str] = None,
        batch_qty: int = 0,
        sample_qty: int = 0,
        source_type: Optional[str] = None,
        source_code: Optional[str] = None,
        created_by: str = "system",
    ) -> Dict[str, Any]:
        """创建检验任务"""
        task_id = _gen_id()
        task_code = _gen_task_code(factory_id, inspect_type)

        await self.db.execute(text("""
            INSERT INTO inspection_tasks (id, factory_id, task_code, inspect_type,
                material_code, material_name, product_id, work_order_id, station_id,
                batch_qty, sample_qty, source_type, source_code, status, created_by, created_at, updated_at)
            VALUES (:id, :fid, :code, :type, :mcode, :mname, :pid, :woid, :sid,
                :batch, :sample, :stype, :scode, 'pending', :by, :now, :now)
        """), {
            "id": task_id, "fid": factory_id, "code": task_code, "type": inspect_type,
            "mcode": material_code, "mname": material_name, "pid": product_id,
            "woid": work_order_id, "sid": station_id,
            "batch": batch_qty, "sample": sample_qty,
            "stype": source_type, "scode": source_code,
            "by": created_by, "now": datetime.utcnow(),
        })
        await self.db.commit()

        return {"id": task_id, "task_code": task_code, "inspect_type": inspect_type, "status": "pending"}

    async def add_items(self, task_id: str, items: List[Dict]) -> Dict[str, Any]:
        """添加检验项（Checklist）"""
        for i, item in enumerate(items):
            await self.db.execute(text("""
                INSERT INTO inspection_items (id, task_id, seq, item_name, item_code, category,
                    spec_value, upper_limit, lower_limit, target_value)
                VALUES (:id, :tid, :seq, :name, :code, :cat, :spec, :upper, :lower, :target)
            """), {
                "id": _gen_id(), "tid": task_id, "seq": i + 1,
                "name": item.get("item_name", ""), "code": item.get("item_code"),
                "cat": item.get("category"), "spec": item.get("spec_value"),
                "upper": item.get("upper_limit"), "lower": item.get("lower_limit"),
                "target": item.get("target_value"),
            })
        await self.db.commit()
        return {"success": True, "items_added": len(items)}

    async def start_inspection(self, task_id: str, inspector: str) -> Dict[str, Any]:
        """开始检验"""
        await self.db.execute(text("""
            UPDATE inspection_tasks SET status = 'inspecting', inspector = :insp,
                started_at = :now, updated_at = :now WHERE id = :id
        """), {"insp": inspector, "now": datetime.utcnow(), "id": task_id})
        await self.db.commit()
        return {"success": True, "status": "inspecting"}

    async def submit_measurement(
        self, task_id: str, item_id: str, measured_value: float,
        defect_type: Optional[str] = None, severity: Optional[str] = None, remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        """提交单项测量值"""
        # 获取检验项标准
        result = await self.db.execute(text(
            "SELECT upper_limit, lower_limit FROM inspection_items WHERE id = :id"
        ), {"id": item_id})
        item = result.mappings().first()
        if not item:
            return {"error": "检验项不存在"}

        # 判定合格
        is_pass = True
        if item["upper_limit"] is not None and measured_value > item["upper_limit"]:
            is_pass = False
        if item["lower_limit"] is not None and measured_value < item["lower_limit"]:
            is_pass = False

        await self.db.execute(text("""
            UPDATE inspection_items SET measured_value = :val, is_pass = :pass,
                defect_type = :dtype, severity = :sev, remark = :remark
            WHERE id = :id
        """), {
            "val": measured_value, "pass": is_pass,
            "dtype": defect_type, "sev": severity, "remark": remark, "id": item_id,
        })
        await self.db.commit()

        return {"success": True, "is_pass": is_pass, "measured_value": measured_value}

    async def complete_inspection(
        self, task_id: str, result: str, disposition: Optional[str] = None, remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        """完成检验（判定结果）"""
        now = datetime.utcnow()

        # 统计不良
        stats = await self.db.execute(text("""
            SELECT COUNT(*) as total, SUM(CASE WHEN is_pass = FALSE THEN 1 ELSE 0 END) as defects
            FROM inspection_items WHERE task_id = :tid
        """), {"tid": task_id})
        s = stats.mappings().first()
        total = s["total"] or 0
        defects = s["defects"] or 0
        defect_rate = round(defects / total * 100, 2) if total > 0 else 0

        status = "passed" if result == "PASS" else "failed" if result == "FAIL" else "conditional"

        await self.db.execute(text("""
            UPDATE inspection_tasks SET status = :status, result = :result,
                disposition = :disp, defect_qty = :defects, defect_rate = :rate,
                remark = :remark, completed_at = :now, updated_at = :now
            WHERE id = :id
        """), {
            "status": status, "result": result, "disp": disposition,
            "defects": defects, "rate": defect_rate, "remark": remark,
            "now": now, "id": task_id,
        })
        await self.db.commit()

        return {
            "success": True, "result": result, "status": status,
            "total_items": total, "defect_qty": defects, "defect_rate": defect_rate,
        }

    async def list_tasks(
        self, factory_id: str, inspect_type: Optional[str] = None, status: Optional[str] = None, limit: int = 50
    ) -> Dict[str, Any]:
        """检验任务列表"""
        query = "SELECT * FROM inspection_tasks WHERE factory_id = :fid"
        params: Dict[str, Any] = {"fid": factory_id}
        if inspect_type:
            query += " AND inspect_type = :type"
            params["type"] = inspect_type
        if status:
            query += " AND status = :status"
            params["status"] = status
        query += " ORDER BY created_at DESC LIMIT :lim"
        params["lim"] = limit

        result = await self.db.execute(text(query), params)
        return {"items": [dict(r) for r in result.mappings().all()]}

    async def get_task_detail(self, task_id: str) -> Dict[str, Any]:
        """检验任务详情（含检验项）"""
        task_result = await self.db.execute(text(
            "SELECT * FROM inspection_tasks WHERE id = :id"
        ), {"id": task_id})
        task = task_result.mappings().first()
        if not task:
            return {"error": "任务不存在"}

        items_result = await self.db.execute(text(
            "SELECT * FROM inspection_items WHERE task_id = :tid ORDER BY seq"
        ), {"tid": task_id})
        items = [dict(r) for r in items_result.mappings().all()]

        return {"task": dict(task), "items": items}

    # ==================== 不良统计 ====================

    async def defect_pareto(self, factory_id: str, days: int = 30) -> Dict[str, Any]:
        """不良 Pareto 分析"""
        result = await self.db.execute(text("""
            SELECT defect_type, COUNT(*) as count
            FROM inspection_items ii
            JOIN inspection_tasks it ON ii.task_id = it.id
            WHERE it.factory_id = :fid AND ii.is_pass = FALSE
                AND it.created_at >= NOW() - INTERVAL ':days days'
            GROUP BY defect_type ORDER BY count DESC LIMIT 10
        """.replace(":days", str(days))), {"fid": factory_id})
        items = [dict(r) for r in result.mappings().all()]

        total = sum(i["count"] for i in items)
        cumulative = 0
        for item in items:
            cumulative += item["count"]
            item["cumulative_pct"] = round(cumulative / total * 100, 1) if total > 0 else 0

        return {"items": items, "total_defects": total, "period_days": days}

    async def quality_kpi(self, factory_id: str) -> Dict[str, Any]:
        """质量 KPI 概览"""
        # 近7天检验统计
        result = await self.db.execute(text("""
            SELECT
                COUNT(*) as total_tasks,
                SUM(CASE WHEN result = 'PASS' THEN 1 ELSE 0 END) as passed,
                SUM(CASE WHEN result = 'FAIL' THEN 1 ELSE 0 END) as failed,
                AVG(defect_rate) as avg_defect_rate
            FROM inspection_tasks
            WHERE factory_id = :fid AND created_at >= NOW() - INTERVAL '7 days'
        """), {"fid": factory_id})
        stats = result.mappings().first()

        total = stats["total_tasks"] or 0
        passed = stats["passed"] or 0
        pass_rate = round(passed / total * 100, 1) if total > 0 else 100

        return {
            "total_tasks": total,
            "passed": passed,
            "failed": stats["failed"] or 0,
            "pass_rate": pass_rate,
            "avg_defect_rate": round(stats["avg_defect_rate"] or 0, 2),
        }
