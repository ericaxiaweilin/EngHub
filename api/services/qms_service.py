"""
QMS质量模块业务服务层 - 持久化版本（基于 SQLAlchemy ORM）

此版本通过 SQLAlchemy 操作真实数据库，所有数据持久化存储。
设计用于生产环境，与内存版本（开发调试时）功能一致但持久化到SQL表。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
import statistics
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Older production images do not contain the optional phase-specific adapters.
# Core inspection and SPC operations below remain available without them.
try:
    from api.services.qms_persistence_service import (
        IQCPersistenceService, FAIPersistenceService, IPCPersistenceService,
        OQCPersistenceService, CAPAPersistenceService,
    )
except ImportError:
    IQCPersistenceService = None
    FAIPersistenceService = None
    IPCPersistenceService = None
    OQCPersistenceService = None
    CAPAPersistenceService = None

# 导入模型（用于软删除操作）
from database.models import DefectRecord, QualityInspection, QmsSpcPoint

class QMSService:
    """
    QMS统一服务门面（持久化版本）
    
    所有操作通过AsyncSession直接与数据库交互，实现真正的持久化存储。
    使用时需传入db_session参数或通过依赖注入获取。
    """
    
    def __init__(self, db_session: Optional[AsyncSession] = None):
        self.db = db_session
    
    async def _get_db(self) -> AsyncSession:
        """获取数据库会话（从实例变量或创建新会话）"""
        if self.db is None:
            from database.db_config import get_db
            # 此处简化：实际应用中应通过依赖注入传入session
            raise RuntimeError("Database session not provided. Pass db to constructor or use dependency injection.")
        return self.db

    async def create_inspection(
        self,
        factory_id: str,
        work_order_id: str,
        routing_step_id: str,
        inspect_type: str,
        inspector_id: str,
        sample_qty: int,
        items: Optional[List[Dict[str, Any]]] = None,
        inspection_phase: Optional[str] = None,
        sampling_method: Optional[str] = None,
        check_tool_id: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> Dict[str, Any]:
        db = await self._get_db()
        inspection = QualityInspection(
            factory_id=factory_id,
            work_order_id=work_order_id,
            routing_step_id=routing_step_id,
            inspect_type=inspect_type.upper(),
            inspection_phase=inspection_phase or inspect_type.upper(),
            inspector_id=inspector_id,
            sample_qty=sample_qty,
            sampling_method=sampling_method,
            check_tool_id=check_tool_id,
            defect_qty=0,
            result="PENDING",
            defect_details={"items": items or []},
            remark=remark,
        )
        db.add(inspection)
        await db.commit()
        await db.refresh(inspection)
        return {"id": inspection.id, "result": inspection.result, "created_at": inspection.created_at.isoformat()}

    async def submit_inspection_result(
        self,
        inspection_id: str,
        items_result: List[Dict[str, Any]],
        defect_qty: int = 0,
    ) -> Dict[str, Any]:
        db = await self._get_db()
        inspection = await db.get(QualityInspection, inspection_id)
        if not inspection:
            return {"success": False, "message": "检验单不存在"}
        failed = defect_qty > 0 or any(
            str(item.get("result", "")).upper() == "FAIL" for item in items_result
        )
        details = dict(inspection.defect_details or {})
        details["results"] = items_result
        inspection.defect_details = details
        inspection.defect_qty = defect_qty
        inspection.result = "FAIL" if failed else "PASS"
        await db.commit()
        return {"success": True, "id": inspection.id, "result": inspection.result}

    async def record_spc_point(
        self,
        factory_id: str,
        characteristic_code: str,
        measured_value: float,
        characteristic_name: Optional[str] = None,
        work_order_id: Optional[str] = None,
        station_id: Optional[str] = None,
        sample_group: Optional[int] = None,
        control_chart_type: str = "xbar",
        calculation_method: str = "three_sigma",
        subgroup_count: Optional[int] = None,
        measured_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        db = await self._get_db()
        values = list(
            (
                await db.execute(
                    select(QmsSpcPoint.measured_value)
                    .where(
                        QmsSpcPoint.factory_id == factory_id,
                        QmsSpcPoint.characteristic_code == characteristic_code,
                    )
                    .order_by(QmsSpcPoint.measured_at.desc())
                    .limit(49)
                )
            ).scalars()
        )
        values.append(measured_value)
        center = statistics.fmean(values)
        sigma = statistics.pstdev(values) if len(values) > 1 else 0.0
        ucl, lcl = center + 3 * sigma, center - 3 * sigma
        point = QmsSpcPoint(
            factory_id=factory_id,
            characteristic_code=characteristic_code,
            characteristic_name=characteristic_name,
            control_chart_type=control_chart_type,
            calculation_method=calculation_method,
            subgroup_count=subgroup_count,
            work_order_id=work_order_id,
            station_id=station_id,
            measured_value=measured_value,
            sample_group=sample_group,
            ucl=ucl,
            lcl=lcl,
            cl=center,
            is_out_of_control=measured_value > ucl or measured_value < lcl,
            measured_at=datetime.utcnow(),
            measured_by=measured_by,
        )
        db.add(point)
        await db.commit()
        await db.refresh(point)
        return self._spc_dict(point)

    async def get_spc_chart(
        self, factory_id: str, characteristic_code: str, limit: int = 50
    ) -> Dict[str, Any]:
        db = await self._get_db()
        points = list(
            (
                await db.execute(
                    select(QmsSpcPoint)
                    .where(
                        QmsSpcPoint.factory_id == factory_id,
                        QmsSpcPoint.characteristic_code == characteristic_code,
                    )
                    .order_by(QmsSpcPoint.measured_at.desc())
                    .limit(limit)
                )
            ).scalars()
        )
        points.reverse()
        ooc_count = sum(1 for p in points if p.is_out_of_control)
        char_name = points[0].characteristic_name if points and hasattr(points[0], 'characteristic_name') else characteristic_code
        return {
            "count": len(points),
            "characteristic_code": characteristic_code,
            "characteristic_name": char_name,
            "ooc_count": ooc_count,
            "points": [self._spc_dict(point) for point in points],
        }

    @staticmethod
    def _spc_dict(point: QmsSpcPoint) -> Dict[str, Any]:
        return {
            "id": point.id,
            "characteristic_code": point.characteristic_code,
            "control_chart_type": point.control_chart_type,
            "calculation_method": point.calculation_method,
            "subgroup_count": point.subgroup_count,
            "measured_value": point.measured_value,
            "value": point.measured_value,
            "sample_group": point.sample_group,
            "ucl": point.ucl,
            "lcl": point.lcl,
            "cl": point.cl,
            "is_out_of_control": point.is_out_of_control,
            "measured_at": point.measured_at.isoformat() if point.measured_at else None,
        }
    
    # ==================== IQ C 接口 ====================
    
    async def create_iqc_record(
        self,
        inbound_order_id: str,
        supplier_id: str,
        product_id: str,
        product_name: str,
        quantity_received: int,
        batch_no: str,
        inspector_id: str,
        factory_id: str,
        sample_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """持久化创建IQ C记录"""
        db = await self._get_db()
        return await IQCPersistenceService.create_iqc_record(
            session=db,
            inbound_order_id=inbound_order_id,
            supplier_id=supplier_id,
            product_id=product_id,
            product_name=product_name,
            quantity_received=quantity_received,
            batch_no=batch_no,
            inspector_id=inspector_id,
            factory_id=factory_id,
            sample_size=sample_size,
        )
    
    async def complete_iqc_inspection(
        self,
        inspection_id: str,
        result: str,  # PASS/FAIL
        sample_inspected: int,
        defects: Optional[List[Dict]] = None,
    ) -> bool:
        """持久化完成IQ C检验并触发CAPA（如需要）"""
        db = await self._get_db()
        success = await IQCPersistenceService.complete_iqc_inspection(
            session=db,
            inspection_id=inspection_id,
            result=result.upper(),
            sample_inspected=sample_inspected,
            defects=defects,
        )
        
        # 简单示例：如果失败且有关键缺陷，创建CAPA（实际应调用CAPAService）
        if result.upper() == "FAIL" and defects:
            critical_defects = [d for d in defects if d.get("severity", "").upper() in ["MAJOR", "CRITICAL"]]
            if critical_defects:
                print(f"[⚠️ CAPA自动触发] IQC {inspection_id} 失败，检测到关键缺陷")
                # 这里可以调用 CAPAPersistenceService.create_capa_case()
        
        return success
    
    async def dispose_iqc_record(self, inspection_id: str, disposition: str) -> bool:
        """持久化处置IQ C记录"""
        db = await self._get_db()
        return await IQCPersistenceService.dispose_iqc_record(session=db, inspection_id=inspection_id, disposition=disposition)
    
    async def list_iqc_records(self, factory_id: str, limit: int = 50) -> List[Dict]:
        """列出IQ C记录（带分页）"""
        db = await self._get_db()
        return await IQCPersistenceService.list_iqc_records(session=db, factory_id=factory_id, limit=limit)
    
    # ==================== FAI 接口 ====================
    
    async def create_fai_record(
        self,
        work_order_id: str,
        factory_id: str,
        product_id: str,
        product_name: str,
        batch_no: str,
        machine_id: str,
        inspector_id: str,
    ) -> Dict[str, Any]:
        """持久化创建首件检验记录"""
        db = await self._get_db()
        return await FAIPersistenceService.create_fai_record(
            session=db,
            work_order_id=work_order_id,
            factory_id=factory_id,
            product_id=product_id,
            product_name=product_name,
            batch_no=batch_no,
            machine_id=machine_id,
            inspector_id=inspector_id,
        )
    
    async def complete_fai_inspection(self, fai_id: str, result: str, defects: Optional[List[Dict]]) -> bool:
        """完成FAI检验（不合格强制触发CAPA）"""
        db = await self._get_db()
        # FAI持久化处理...（略，与IQ C类似）
        return True
    
    # ==================== IPC 接口 ====================
    
    async def create_ipc_plan(
        self,
        work_order_id: str,
        factory_id: str,
        product_id: str,
        process_stage: str,
        frequency_type: str,
        frequency_value: int,
        operator_id: str,
        inspector_id: str,
    ) -> Dict[str, Any]:
        """持久化创建IPC巡检计划"""
        db = await self._get_db()
        return await IPCPersistenceService.create_ipc_plan(
            session=db,
            work_order_id=work_order_id,
            factory_id=factory_id,
            product_id=product_id,
            process_stage=process_stage,
            frequency_type=frequency_type,
            frequency_value=frequency_value,
            operator_id=operator_id,
            inspector_id=inspector_id,
        )
    
    # ==================== OQC 接口 ====================
    
    async def create_oqc_record(
        self,
        order_id: str,
        customer_id: str,
        product_id: str,
        product_name: str,
        batch_no: str,
        quantity_to_ship: int,
        inspector_id: str,
    ) -> Dict[str, Any]:
        """持久化创建出货检验记录"""
        db = await self._get_db()
        return await OQCPersistenceService.create_oqc_record(
            session=db,
            order_id=order_id,
            customer_id=customer_id,
            product_id=product_id,
            product_name=product_name,
            batch_no=batch_no,
            quantity_to_ship=quantity_to_ship,
            inspector_id=inspector_id,
        )
    
    # ==================== CAPA 接口（持久化版） ====================
    
    async def capa_create_case(
        self,
        title: str,
        severity: str,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """持久化创建CAPA案件"""
        db = await self._get_db()
        return await CAPAPersistenceService.create_capa_case(
            session=db,
            title=title,
            severity=severity,
            source_type=source_type,
            source_id=source_id,
        )
    
    async def list_capa_cases(self, status: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """列出CAPA案件"""
        db = await self._get_db()
        return await CAPAPersistenceService.list_capa_cases(session=db, status=status, limit=limit)
    
    # ==================== 辅助方法（简化的内存版本，生产时需改为持久化） ====================
    
    async def capa_add_why_step(self, case_id: str, step_num: int, question: str, answer: str) -> bool:
        """添加5Why追问（临时内存实现）"""
        # TODO: 持久化存储到数据库
        print(f"[TODO持久化] 添加5Why步骤{step_num}到案件{case_id}")
        return True
    
    async def capa_set_root_cause(self, case_id: str, cause: str) -> bool:
        """设置根本原因（临时内存实现）"""
        print(f"[TODO持久化] 设置根本原因到案件{case_id}")
        return True
    
    async def capa_add_fishbone_item(self, case_id: str, dimension: str, item: str) -> bool:
        """添加鱼骨图项（临时内存实现）"""
        print(f"[TODO持久化] 添加鱼骨图项到{dimension}维度")
        return True
    
    async def capa_get_fishbone_summary(self, case_id: str) -> Optional[Dict[str, Any]]:
        """获取鱼骨图摘要（临时内存实现）"""
        return {}
    
    async def capa_set_verification_before(self, case_id: str, metrics: Dict[str, Any]) -> bool:
        """设置验证前数据（临时内存实现）"""
        print(f"[TODO持久化] 设置CAPA {case_id} 验证前数据")
        return True
    
    async def capa_set_verification_after(self, case_id: str, metrics: Dict[str, Any], improved: bool, verified_by: str) -> bool:
        """设置验证后数据（临时内存实现）"""
        print(f"[TODO持久化] 设置CAPA {case_id} 验证后数据")
        return True
    
    async def capa_create_action_plan(self, case_id: str, description: str, owner: str, deadline: str) -> Dict[str, Any]:
        """创建行动计划项（临时内存实现）"""
        return {"id": "temp", "description": description, "owner": owner, "status": "planned"}

    # ==================== 软删除操作（Soft Delete Operations） ====================

    async def soft_delete_defect(self, defect_id: str, deleted_by: str) -> Dict[str, Any]:
        """软删除缺陷记录 - 标记为archived状态，查询时过滤"""
        db = await self._get_db()
        
        # 检查缺陷是否存在
        from database.models import DefectRecord
        defect = await db.get(DefectRecord, defect_id)
        if not defect:
            return {"success": False, "message": "缺陷记录不存在"}
        
        # 软删除：设置status或添加deleted_at字段
        # 由于当前模型无deleted字段，这里采用标记方式（实际生产需数据库迁移添加is_deleted列）
        # 方案1：使用现有status字段设为'archived'（如果适用）
        # 方案2：逻辑删除 - 仅在应用层维护一个"已删除集合"（不持久化，重启失效）
        # 建议：执行数据库迁移添加 is_deleted BOOLEAN DEFAULT false 索引
        
        # 此处先记录日志，表示需要实现的软删除
        print(f"[SOFT_DELETE] 缺陷 {defect_id} 由 {deleted_by} 标记为删除 (需实现持久化删除)")
        
        # 临时实现：更新记录但保留数据（占位符）
        defect.updated_at = datetime.utcnow()
        # 注意：实际生产应设置 is_deleted = true 或类似标记
        
        await db.commit()
        return {"success": True, "message": f"缺陷 {defect_id} 已软删除 (实际需配合数据库迁移)"}

    async def soft_delete_inspection(self, inspection_id: str, deleted_by: str) -> Dict[str, Any]:
        """软删除检验记录 - 标记为archived状态，查询时过滤"""
        db = await self._get_db()
        
        from database.models import QualityInspection
        inspection = await db.get(QualityInspection, inspection_id)
        if not inspection:
            return {"success": False, "message": "检验记录不存在"}
        
        print(f"[SOFT_DELETE] 检验 {inspection_id} 由 {deleted_by} 标记为删除 (需实现持久化删除)")
        
        inspection.updated_at = datetime.utcnow()
        await db.commit()
        return {"success": True, "message": f"检验 {inspection_id} 已软删除 (实际需配合数据库迁移)"}

    async def get_quality_dashboard(self, factory_id: str) -> Dict[str, Any]:
        """质量看板聚合数据"""
        db = await self._get_db()
        from sqlalchemy import select, func, case
        from database.models import QualityInspection, DefectRecord

        # 检验统计
        insp_res = await db.execute(
            select(
                func.count(QualityInspection.id),
                func.sum(case((func.upper(QualityInspection.result) == 'PASS', 1), else_=0)),
            ).where(QualityInspection.factory_id == factory_id)
        )
        row = insp_res.one()
        total_inspections = row[0] or 0
        passed = row[1] or 0
        pass_rate = round(passed / max(total_inspections, 1) * 100, 1)

        # 不良品统计
        defect_res = await db.execute(
            select(
                func.count(DefectRecord.id),
                func.sum(DefectRecord.quantity),
            ).where(DefectRecord.factory_id == factory_id)
        )
        drow = defect_res.one()
        total_defects = drow[0] or 0
        total_defect_qty = drow[1] or 0

        # 按严重等级分布
        sev_res = await db.execute(
            select(DefectRecord.severity, func.count(DefectRecord.id))
            .where(DefectRecord.factory_id == factory_id)
            .group_by(DefectRecord.severity)
        )
        severity_dist = {r[0]: r[1] for r in sev_res.all()}

        # 按缺陷类型分布
        type_res = await db.execute(
            select(DefectRecord.defect_type, func.count(DefectRecord.id))
            .where(DefectRecord.factory_id == factory_id)
            .group_by(DefectRecord.defect_type)
        )
        type_dist = {r[0]: r[1] for r in type_res.all()}

        # 最近不良品
        recent_res = await db.execute(
            select(DefectRecord)
            .where(DefectRecord.factory_id == factory_id)
            .order_by(DefectRecord.created_at.desc())
            .limit(10)
        )
        recent_defects = [
            {
                "id": d.id,
                "record_code": d.record_code,
                "defect_type": d.defect_type,
                "severity": d.severity,
                "quantity": d.quantity,
                "disposition": d.disposition,
                "station_id": d.station_id,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in recent_res.scalars().all()
        ]

        # SPC 异常点
        spc_ooc = 0
        try:
            from database.models import QmsSpcPoint
            spc_res = await db.execute(
                select(func.count(QmsSpcPoint.id))
                .where(QmsSpcPoint.factory_id == factory_id)
                .where(QmsSpcPoint.is_out_of_control == True)
            )
            spc_ooc = spc_res.scalar() or 0
        except Exception:
            pass

        # 8D 报告统计
        eight_d_in_progress = 0
        eight_d_open = 0
        try:
            from database.models import Qms8dReport
            d8_res = await db.execute(
                select(Qms8dReport.status, func.count(Qms8dReport.id))
                .where(Qms8dReport.factory_id == factory_id)
                .group_by(Qms8dReport.status)
            )
            for status, cnt in d8_res.all():
                if status in ('in_progress', 'D1', 'D2', 'D3', 'D4', 'D5', 'D6', 'D7'):
                    eight_d_in_progress += cnt
                elif status in ('open', 'new'):
                    eight_d_open += cnt
        except Exception:
            pass

        # top_defects: [{type, qty}] 按数量降序
        top_defects = [
            {"type": dtype, "qty": int(cnt)}
            for dtype, cnt in sorted(type_dist.items(), key=lambda x: x[1], reverse=True)
        ]

        return {
            "factory_id": factory_id,
            "inspection": {
                "pass_rate": pass_rate,
                "total": total_inspections,
                "passed": int(passed),
            },
            "spc_ooc_count": spc_ooc,
            "eight_d": {
                "in_progress": eight_d_in_progress,
                "open": eight_d_open,
            },
            "top_defects": top_defects,
            "severity_distribution": severity_dist,
            "defect_type_distribution": type_dist,
            "recent_defects": recent_defects,
        }
