"""
检验服务 - 岗位替代 Phase 4: 替代质检员
IQC/IPQC/FQC/OQC 检验工作流 + 检验项 Checklist + AQL抽样 + 自动判定报告
"""
import uuid
import math
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

    # ==================== AQL 抽样方案 (GB/T 2828.1) ====================

    # 简化 AQL 表：批量范围 → (抽样数, Ac, Re) for AQL=1.0 正常检验 Level II
    AQL_TABLE = {
        (2, 8): (2, 0, 1),
        (9, 15): (3, 0, 1),
        (16, 25): (5, 0, 1),
        (26, 50): (8, 0, 1),
        (51, 90): (13, 0, 1),
        (91, 150): (20, 1, 2),
        (151, 280): (32, 1, 2),
        (281, 500): (50, 2, 3),
        (501, 1200): (80, 3, 4),
        (1201, 3200): (125, 5, 6),
        (3201, 10000): (200, 7, 8),
        (10001, 35000): (315, 10, 11),
        (35001, 150000): (500, 14, 15),
        (150001, 500000): (800, 21, 22),
        (500001, 9999999): (1250, 21, 22),
    }

    def get_aql_sampling_plan(self, batch_qty: int, aql: float = 1.0, level: str = "II") -> Dict[str, Any]:
        """根据批量获取 AQL 抽样方案（GB/T 2828.1 正常检验 Level II, AQL=1.0）"""
        for (lo, hi), (sample, ac, re) in self.AQL_TABLE.items():
            if lo <= batch_qty <= hi:
                return {
                    "batch_qty": batch_qty,
                    "aql": aql,
                    "inspection_level": level,
                    "sample_size": sample,
                    "accept_number": ac,
                    "reject_number": re,
                    "rule": f"抽 {sample} 件，不良 ≤ {ac} 判合格，≥ {re} 判不合格",
                }
        # 超大批量
        return {
            "batch_qty": batch_qty,
            "aql": aql,
            "inspection_level": level,
            "sample_size": 1250,
            "accept_number": 21,
            "reject_number": 22,
            "rule": "抽 1250 件，不良 ≤ 21 判合格，≥ 22 判不合格",
        }

    # ==================== 检验计划自动生成 ====================

    INSPECTION_TEMPLATES: Dict[str, List[Dict]] = {
        "IQC": [
            {"item_name": "外观检查", "category": "外观", "spec_value": "无损伤/污染/锈蚀", "upper_limit": None, "lower_limit": None},
            {"item_name": "尺寸测量", "category": "尺寸", "spec_value": "按图纸", "upper_limit": 0.1, "lower_limit": -0.1},
            {"item_name": "材质证明", "category": "文件", "spec_value": "有材质证明书", "upper_limit": None, "lower_limit": None},
            {"item_name": "包装完整性", "category": "包装", "spec_value": "无破损/受潮", "upper_limit": None, "lower_limit": None},
            {"item_name": "标识核对", "category": "标识", "spec_value": "物料编码/批次号正确", "upper_limit": None, "lower_limit": None},
        ],
        "IPQC": [
            {"item_name": "首件确认", "category": "首件", "spec_value": "首件合格", "upper_limit": None, "lower_limit": None},
            {"item_name": "关键尺寸", "category": "尺寸", "spec_value": "按工艺卡", "upper_limit": 0.05, "lower_limit": -0.05},
            {"item_name": "工艺参数", "category": "工艺", "spec_value": "温度/压力/速度在范围内", "upper_limit": None, "lower_limit": None},
            {"item_name": "外观质量", "category": "外观", "spec_value": "无划伤/毛刺/变形", "upper_limit": None, "lower_limit": None},
        ],
        "FQC": [
            {"item_name": "功能测试", "category": "功能", "spec_value": "各项功能正常", "upper_limit": None, "lower_limit": None},
            {"item_name": "外观终检", "category": "外观", "spec_value": "无缺陷", "upper_limit": None, "lower_limit": None},
            {"item_name": "尺寸全检", "category": "尺寸", "spec_value": "全部尺寸合格", "upper_limit": 0.1, "lower_limit": -0.1},
            {"item_name": "包装检查", "category": "包装", "spec_value": "包装规范/附件齐全", "upper_limit": None, "lower_limit": None},
            {"item_name": "标识检查", "category": "标识", "spec_value": "标签/合格证齐全", "upper_limit": None, "lower_limit": None},
        ],
    }

    async def generate_inspection_plan(self, task_id: str, inspect_type: str) -> Dict[str, Any]:
        """根据检验类型自动生成检验项（替代质检员手动填写）"""
        template = self.INSPECTION_TEMPLATES.get(inspect_type.upper(), self.INSPECTION_TEMPLATES["IQC"])
        await self.add_items(task_id, template)
        return {
            "success": True,
            "inspect_type": inspect_type,
            "items_generated": len(template),
            "items": [t["item_name"] for t in template],
        }

    # ==================== 自动判定报告 ====================

    async def auto_judge_and_report(self, task_id: str) -> Dict[str, Any]:
        """自动判定 + 生成检验报告（替代质检员手动判定+写报告）"""
        detail = await self.get_task_detail(task_id)
        if "error" in detail:
            return detail

        task = detail["task"]
        items = detail["items"]
        total = len(items)
        passed = sum(1 for i in items if i.get("is_pass"))
        failed = total - passed
        defect_rate = round(failed / total * 100, 2) if total > 0 else 0

        # 自动判定逻辑
        if failed == 0:
            result = "PASS"
            disposition = "合格入库"
        elif defect_rate <= 5:
            result = "CONDITIONAL"
            disposition = "条件放行（挑选/返工）"
        else:
            result = "FAIL"
            disposition = "不合格（退货/报废）"

        # 更新任务状态
        await self.complete_inspection(task_id, result, disposition)

        # 生成报告
        report = {
            "report_code": f"QR-{task.get('task_code', '')}",
            "task_id": task_id,
            "inspect_type": task.get("inspect_type"),
            "material_code": task.get("material_code"),
            "material_name": task.get("material_name"),
            "batch_qty": task.get("batch_qty"),
            "sample_qty": task.get("sample_qty"),
            "inspection_result": result,
            "disposition": disposition,
            "statistics": {
                "total_items": total,
                "passed": passed,
                "failed": failed,
                "defect_rate": defect_rate,
            },
            "failed_items": [
                {"item_name": i.get("item_name"), "measured_value": i.get("measured_value"),
                 "defect_type": i.get("defect_type"), "severity": i.get("severity")}
                for i in items if not i.get("is_pass")
            ],
            "inspector": task.get("inspector"),
            "completed_at": datetime.utcnow().isoformat(),
        }
        return report
