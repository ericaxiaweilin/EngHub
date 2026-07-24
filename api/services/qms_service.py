"""
QMS 质量管理服务 - 检验/SPC/8D/质量看板
"""
import uuid
import logging
import math
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    QualityInspection, DefectRecord, WorkOrder,
    QmsInspectionItem, QmsSpcPoint, Qms8dReport,
)

logger = logging.getLogger(__name__)


class QmsService:
    """QMS 质量管理服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ============== 检验管理 ==============

    async def create_inspection(
        self,
        factory_id: str,
        work_order_id: str,
        inspect_type: str,
        inspector_id: str,
        sample_qty: int,
        items: List[Dict[str, Any]],
        remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        """创建检验单 + 检验项"""
        inspection_id = str(uuid.uuid4())
        inspection = QualityInspection(
            id=inspection_id,
            factory_id=factory_id,
            work_order_id=work_order_id,
            routing_step_id=inspect_type,  # 复用字段存类型标识
            inspect_type=inspect_type.upper(),
            inspector_id=inspector_id,
            sample_qty=sample_qty,
            defect_qty=0,
            result="PENDING",
            remark=remark,
        )
        self.db.add(inspection)

        # 创建检验项
        for item in items:
            insp_item = QmsInspectionItem(
                id=str(uuid.uuid4()),
                inspection_id=inspection_id,
                item_name=item.get("item_name", ""),
                item_code=item.get("item_code"),
                spec_lower=item.get("spec_lower"),
                spec_upper=item.get("spec_upper"),
                target_value=item.get("target_value"),
                measurement_method=item.get("measurement_method"),
                remark=item.get("remark"),
            )
            self.db.add(insp_item)

        await self.db.commit()
        return {"success": True, "inspection_id": inspection_id, "message": f"检验单已创建（{inspect_type.upper()}）"}

    async def submit_inspection_result(
        self,
        inspection_id: str,
        items_result: List[Dict[str, Any]],
        defect_qty: int = 0,
    ) -> Dict[str, Any]:
        """提交检验结果，自动判定 PASS/FAIL"""
        inspection = await self.db.get(QualityInspection, inspection_id)
        if not inspection:
            return {"success": False, "message": "检验单不存在"}

        # 更新检验项实测值
        ng_count = 0
        for ir in items_result:
            item = await self.db.get(QmsInspectionItem, ir["item_id"])
            if item:
                item.measured_value = ir.get("measured_value")
                # 自动判定
                val = ir.get("measured_value")
                if val is not None:
                    ok = True
                    if item.spec_lower is not None and val < item.spec_lower:
                        ok = False
                    if item.spec_upper is not None and val > item.spec_upper:
                        ok = False
                    item.result = "OK" if ok else "NG"
                    if not ok:
                        ng_count += 1
                else:
                    item.result = ir.get("result", "OK")
                    if item.result == "NG":
                        ng_count += 1

        # 判定整体结果
        overall = "PASS" if ng_count == 0 else "FAIL"
        inspection.result = overall
        inspection.defect_qty = defect_qty or ng_count

        await self.db.commit()
        return {"success": True, "result": overall, "ng_items": ng_count}

    # ============== SPC 控制图 ==============

    async def record_spc_point(
        self,
        factory_id: str,
        characteristic_code: str,
        measured_value: float,
        characteristic_name: Optional[str] = None,
        work_order_id: Optional[str] = None,
        station_id: Optional[str] = None,
        sample_group: Optional[int] = None,
        measured_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录 SPC 数据点，自动计算控制限"""
        # 获取历史数据计算控制限
        stmt = select(QmsSpcPoint.measured_value).where(
            QmsSpcPoint.factory_id == factory_id,
            QmsSpcPoint.characteristic_code == characteristic_code,
        ).order_by(QmsSpcPoint.measured_at.desc()).limit(24)
        result = await self.db.execute(stmt)
        history = [r[0] for r in result.fetchall()]

        # 计算 Xbar 控制限（3-sigma）
        all_values = history + [measured_value]
        n = len(all_values)
        mean = sum(all_values) / n
        if n >= 2:
            std = math.sqrt(sum((x - mean) ** 2 for x in all_values) / (n - 1))
        else:
            std = 0
        ucl = mean + 3 * std
        lcl = mean - 3 * std
        is_ooc = measured_value > ucl or measured_value < lcl

        point = QmsSpcPoint(
            id=str(uuid.uuid4()),
            factory_id=factory_id,
            characteristic_code=characteristic_code,
            characteristic_name=characteristic_name,
            work_order_id=work_order_id,
            station_id=station_id,
            measured_value=measured_value,
            sample_group=sample_group,
            ucl=round(ucl, 4),
            lcl=round(lcl, 4),
            cl=round(mean, 4),
            is_out_of_control=is_ooc,
            measured_by=measured_by,
        )
        self.db.add(point)
        await self.db.commit()

        return {
            "success": True,
            "point_id": point.id,
            "value": measured_value,
            "ucl": round(ucl, 4),
            "lcl": round(lcl, 4),
            "cl": round(mean, 4),
            "is_out_of_control": is_ooc,
        }

    async def get_spc_chart(
        self,
        factory_id: str,
        characteristic_code: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """获取 SPC 控制图数据"""
        stmt = select(QmsSpcPoint).where(
            QmsSpcPoint.factory_id == factory_id,
            QmsSpcPoint.characteristic_code == characteristic_code,
        ).order_by(QmsSpcPoint.measured_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        points = list(reversed(result.scalars().all()))

        return {
            "characteristic_code": characteristic_code,
            "characteristic_name": points[0].characteristic_name if points else characteristic_code,
            "points": [
                {
                    "id": p.id,
                    "value": p.measured_value,
                    "ucl": p.ucl,
                    "lcl": p.lcl,
                    "cl": p.cl,
                    "is_out_of_control": p.is_out_of_control,
                    "sample_group": p.sample_group,
                    "measured_at": p.measured_at.isoformat() if p.measured_at else None,
                    "station_id": p.station_id,
                }
                for p in points
            ],
            "total": len(points),
            "ooc_count": sum(1 for p in points if p.is_out_of_control),
        }

    # ============== 8D 报告 ==============

    async def create_8d(
        self,
        factory_id: str,
        title: str,
        defect_record_id: Optional[str] = None,
        severity: str = "major",
        opened_by: Optional[str] = None,
        due_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """创建 8D 报告"""
        now = datetime.utcnow()
        report_code = f"8D-{factory_id[:4]}-{now.strftime('%Y%m%d')}-{str(uuid.uuid4())[:4].upper()}"

        report = Qms8dReport(
            id=str(uuid.uuid4()),
            report_code=report_code,
            factory_id=factory_id,
            defect_record_id=defect_record_id,
            title=title,
            severity=severity,
            status="open",
            opened_by=opened_by,
            due_date=due_date or (now + timedelta(days=14)),
        )
        self.db.add(report)

        # 如果关联缺陷，更新缺陷的纠正措施状态
        if defect_record_id:
            defect = await self.db.get(DefectRecord, defect_record_id)
            if defect:
                defect.review_status = "under_review"

        await self.db.commit()
        return {"success": True, "report_id": report.id, "report_code": report_code}

    async def update_8d_step(
        self,
        report_id: str,
        step: str,
        content: str,
    ) -> Dict[str, Any]:
        """更新 8D 步骤 (d1-d8)"""
        report = await self.db.get(Qms8dReport, report_id)
        if not report:
            return {"success": False, "message": "8D 报告不存在"}

        field_map = {
            "d1": "d1_team", "d2": "d2_problem_description",
            "d3": "d3_containment_action", "d4": "d4_root_cause",
            "d5": "d5_corrective_action", "d6": "d6_implementation",
            "d7": "d7_preventive_action", "d8": "d8_congratulations",
        }
        field = field_map.get(step.lower())
        if not field:
            return {"success": False, "message": f"无效步骤: {step}"}

        setattr(report, field, content)
        if report.status == "open":
            report.status = "in_progress"
        report.updated_at = datetime.utcnow()
        await self.db.commit()
        return {"success": True, "message": f"{step.upper()} 已更新"}

    async def close_8d(self, report_id: str, closed_by: str) -> Dict[str, Any]:
        """关闭 8D 报告"""
        report = await self.db.get(Qms8dReport, report_id)
        if not report:
            return {"success": False, "message": "8D 报告不存在"}
        report.status = "closed"
        report.closed_by = closed_by
        report.updated_at = datetime.utcnow()

        if report.defect_record_id:
            defect = await self.db.get(DefectRecord, report.defect_record_id)
            if defect:
                defect.review_status = "closed"

        await self.db.commit()
        return {"success": True, "message": "8D 报告已关闭"}

    # ============== 质量看板 ==============

    async def get_quality_dashboard(self, factory_id: str) -> Dict[str, Any]:
        """质量看板数据"""
        # 检验统计
        insp_stmt = select(
            QualityInspection.result, func.count()
        ).where(QualityInspection.factory_id == factory_id).group_by(QualityInspection.result)
        insp_result = await self.db.execute(insp_stmt)
        insp_stats = {r[0]: r[1] for r in insp_result.fetchall()}

        total_insp = sum(insp_stats.values())
        pass_count = insp_stats.get("PASS", 0)
        pass_rate = (pass_count / total_insp * 100) if total_insp > 0 else 0

        # 缺陷 Top 类型
        defect_stmt = select(
            DefectRecord.defect_type, func.sum(DefectRecord.quantity)
        ).where(DefectRecord.factory_id == factory_id).group_by(
            DefectRecord.defect_type
        ).order_by(func.sum(DefectRecord.quantity).desc()).limit(5)
        defect_result = await self.db.execute(defect_stmt)
        top_defects = [{"type": r[0], "qty": r[1]} for r in defect_result.fetchall()]

        # 8D 状态统计
        eightd_stmt = select(
            Qms8dReport.status, func.count()
        ).where(Qms8dReport.factory_id == factory_id).group_by(Qms8dReport.status)
        eightd_result = await self.db.execute(eightd_stmt)
        eightd_stats = {r[0]: r[1] for r in eightd_result.fetchall()}

        # SPC 异常统计
        spc_stmt = select(func.count()).where(
            QmsSpcPoint.factory_id == factory_id,
            QmsSpcPoint.is_out_of_control == True,
        )
        spc_ooc = (await self.db.execute(spc_stmt)).scalar() or 0

        return {
            "factory_id": factory_id,
            "inspection": {
                "total": total_insp,
                "pass": pass_count,
                "fail": insp_stats.get("FAIL", 0),
                "pending": insp_stats.get("PENDING", 0),
                "pass_rate": round(pass_rate, 1),
            },
            "top_defects": top_defects,
            "eight_d": eightd_stats,
            "spc_ooc_count": spc_ooc,
        }
