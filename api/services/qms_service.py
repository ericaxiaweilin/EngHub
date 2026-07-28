"""
QMS质量模块业务服务层 - 统一封装 IQC、FAI、IPC、OQC、CAPA 五大子模块

服务设计原则：
1. 每个子模块使用独立的服务类实现，保持高内聚低耦合
2. QMSService 作为统一门面，协调跨模块的业务流程
3. CAPA自动触发机制嵌入各检验节点，实现质量闭环
4. 支持内存模式（原型）和数据库模式（生产环境）扩展
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

# 子模块导入
from core.qms.iqc_service import IQCService, IQCStatus, InspectionResultType, DispositionType
from core.qms.fai_service import FAIService, FAIStatus, FAIStructure, FAILevel
from core.qms.ipc_service import IPCService, IPCFrequencyType, IPCStatus
from core.qms.oqc_service import OQCService, OQCStatus, OQCResultType
from core.qms.capa_service import CAPAService, CAPASeverity, CAPAStatus, EIGHTD_STEP


from core.qms.iqc_service import IQCStatus, InspectionResultType, DispositionType
from core.qms.fai_service import FAIStatus, FAIStructure, FAILevel, FAIResultType
from core.qms.ipc_service import IPCFrequencyType, IPCStatus, IPCResultType
from core.qms.oqc_service import OQCStatus, OQCResultType
from core.qms.capa_service import CAPAService, CAPASeverity, CAPAStatus, EIGHTD_STEP


class QMSService:
    """
    QMS统一服务门面 - 整合所有质量子模块
    
    在内存模式下使用各子模块的独立服务实例，
    在生产环境中可替换为基于数据库会话的持久化实现。
    """
    
    def __init__(self):
        # 初始化各子模块服务（内存版本）
        self.iqc_service = IQCService()
        self.fai_service = FAIService()
        self.ipc_service = IPCService()
        self.oqc_service = OQCService()
        self.capa_service = CAPAService()
    
    # ==================== IQC 接口 ====================
    
    async def create_iqc_record(self, **kwargs) -> Dict[str, Any]:
        """创建IQ C记录（调用内核服务）"""
        return self.iqc_service.create_record(**kwargs)
    
    async def complete_iqc_inspection(self, iqc_id: str, result: InspectionResultType, 
                                     sample_inspected: int, defects: Optional[List[Dict]] = None) -> bool:
        """完成IQ C检验 - 并自动触发CAPA（如需要）"""
        record = self.iqc_service.get_record(iqc_id)
        if not record or record.status != IQCStatus.IN_PROGRESS:
            return False
        
        # 记录结果
        record.record_result(result, sample_inspected, defects)
        
        # 🚀 CAPA 自动触发：如果结果为不合格且缺陷严重，则自动创建CAPA
        if result == InspectionResultType.FAIL and defects:
            # 检查是否有重大或关键缺陷
            critical_defects = [d for d in defects if d.get("severity", "").upper() in ["CRITICAL", "MAJOR"]]
            if critical_defects:
                # 调用辅助函数创建CAPA
                await self._maybe_create_capa_from_iqc(iqc_id, defects, "major")
        
        return True
    
    async def dispose_iqc_record(self, iqc_id: str, disposition: str, by: str) -> bool:
        """处置IQ C记录"""
        return self.iqc_service.dispose_record(iqc_id, disposition, by)
    
    async def _maybe_create_capa_from_iqc(self, iqc_id: str, defects: List[Dict], severity_level: str) -> Optional[str]:
        """根据IQ C结果判断是否需要自动创建CAPA（MAJOR及以上严重程度）"""
        if severity_level.lower() not in ["major", "critical"]:
            return None
        
        try:
            # 获取记录详情（简化版：从IQ C服务中查找）
            record = self.iqc_service.get_record(iqc_id)
            if not record:
                return None
            
            # 提取缺陷描述
            defect_descriptions = [d.get("description", "") for d in defects if d.get("severity", "").upper() in ["MAJOR", "CRITICAL"]]
            summary = "; ".join(defect_descriptions[:3]) if defect_descriptions else "无详细描述"
            
            # 创建CAPA案件
            capa_case = self.capa_service.create_case(
                title=f"IQC严重缺陷 - {record.product_name}",
                severity=CAPASeverity(severity_level),
                source_type="iqc",
                source_id=str(record.id)[:8] if hasattr(record, 'id') else "",
            )
            
            # 自动填充基本信息
            capa_case.problem_description = f"IQC检验发现{len(defects)}个缺陷：{summary}"
            capa_case.where_found = "来料检验环节"
            capa_case.extent = f"供应商: {record.supplier_id}, 批次: {record.batch_no}"
            capa_case.add_team_member("quality_manager")
            
            print(f"[🚀 自动触发] IQC案件{iqc_id[:8]}... → CAPA {capa_case.case_number}")
            return capa_case.id
        except Exception as e:
            print(f"[⚠️ CAPA触发失败] {str(e)}")
            return None
    
    # ==================== FAI 接口 ====================
    
    async def create_fai_record(self, **kwargs) -> Dict[str, Any]:
        """创建首件检验记录"""
        return self.fai_service.create_fai_record(**kwargs)
    
    async def complete_fai_inspection(self, fai_id: str, result: FAIResultType, 
                                     defects: Optional[List[Dict]] = None) -> bool:
        """完成FAI检验 - 不合格时强制触发CAPA（首件不合格即重大问题！）"""
        record = self.fai_service.get_record(fai_id)
        if not record or record.status != FAIStatus.IN_PROGRESS:
            return False
        
        record.finish_inspection(result)
        
        # 🚀 FAI不合格必须触发CAPA（首件代表工艺稳定性）
        if result == FAIResultType.FAIL:
            await self._maybe_create_capa_from_fai(fai_id, defects)
        
        return True
    
    async def _maybe_create_capa_from_fai(self, fai_id: str, defects: Optional[List[Dict]]) -> Optional[str]:
        """FAI不合格时自动触发CAPA（强制）"""
        if defects and any(d.get("severity", "").upper() in ["MAJOR", "CRITICAL"] for d in defects):
            try:
                record = self.fai_service.get_record(fai_id)
                if not record:
                    return None
                
                capa_case = self.capa_service.create_case(
                    title=f"FAI首件不合格 - {record.product_name}",
                    severity=CAPASeverity.CRITICAL,  # FAI不合格视为最高优先级
                    source_type="fai",
                    source_id=str(record.id)[:8] if hasattr(record, 'id') else "",
                )
                capa_case.problem_description = f"首件检验判定FAIL，发现关键缺陷"
                capa_case.where_found = f"{record.process_stage}工序首件"
                capa_case.extent = f"批量: {record.sample_qty}, 机器: {record.machine_id}"
                capa_case.add_team_member("engineering_lead")
                
                print(f"[🚀 强制触发] FAI案件{fai_id[:8]}... → CAPA {capa_case.case_number} (CRITICAL)")
                return capa_case.id
            except Exception as e:
                print(f"[⚠️ FAI CAPA触发失败: {e}]")
        return None
    
    # ==================== IPC 接口 ====================
    
    async def create_ipc_plan(self, **kwargs) -> Dict[str, Any]:
        """创建IPC巡检计划"""
        return self.ipc_service.create_ipc_plan(**kwargs)
    
    async def complete_ipc_inspection(self, ipc_id: str, result: IPCResultType, 
                                     defects: Optional[List[Dict]] = None) -> bool:
        """完成IPC检验 - 连续多次不合格触发CAPA（简化：本次即触发）"""
        record = self.ipc_service.get_record(ipc_id)
        if not record or record.status != IPCStatus.IN_PROGRESS:
            return False
        
        record.complete_inspection(result)
        
        # 🚀 IPC连续缺陷可触发CAPA（当前简化实现：每次FAIL都触发）
        if result == IPCResultType.FAIL and defects:
            await self._maybe_create_capa_from_ipc(ipc_id, defects)
        
        return True
    
    async def _maybe_create_capa_from_ipc(self, ipc_id: str, defects: List[Dict]) -> Optional[str]:
        """IPC检验不合格时自动触发CAPA"""
        critical_count = sum(1 for d in defects if d.get("severity", "").upper() in ["MAJOR", "CRITICAL"])
        if critical_count >= 1:  # 至少1个重大缺陷
            try:
                record = self.ipc_service.get_record(ipc_id)
                if not record:
                    return None
                
                capa_case = self.capa_service.create_case(
                    title=f"IPC过程失控 - {record.process_stage}",
                    severity=CAPASeverity.MAJOR,
                    source_type="ipc",
                    source_id=str(record.id)[:8] if hasattr(record, 'id') else "",
                )
                capa_case.problem_description = f"巡检发现{critical_count}个关键缺陷"
                capa_case.where_found = f"工单{record.work_order_id}的{record.process_stage}"
                capa_case.add_team_member("production_supervisor")
                
                print(f"[🚀 触发] IPC案件{ipc_id[:8]}... → CAPA {capa_case.case_number}")
                return capa_case.id
            except Exception as e:
                print(f"[⚠️ IPC CAPA触发失败: {e}]")
        return None
    
    # ==================== OQC 接口 ====================
    
    async def create_oqc_record(self, **kwargs) -> Dict[str, Any]:
        """创建出货检验记录"""
        return self.oqc_service.create_oqc_record(**kwargs)
    
    async def complete_oqc_inspection(self, oqc_id: str, result: OQCResultType) -> bool:
        """完成OQC检验 - 不合格时需处置并可能触发CAPA"""
        record = self.oqc_service.get_record(oqc_id)
        if not record or record.status != OQCStatus.IN_PROGRESS:
            return False
        
        record.complete_inspection(result)
        # OQC不合格通常涉及退货，视情况再决定是否需要CAPA
        return True
    
    async def dispose_oqc_record(self, oqc_id: str, disposition: str, by: str, shipped_qty: Optional[int] = None) -> bool:
        """处置OQC记录"""
        return self.oqc_service.dispose_record(oqc_id, disposition, by, shipped_qty)
    
    # ==================== CAPA 接口 ====================
    
    async def create_capa_case(self, title: str, severity: str, **kwargs) -> Dict[str, Any]:
        """创建CAPA案件"""
        case = self.capa_service.create_case(title=title, severity=CAPASeverity(severity), **kwargs)
        return {
            "id": case.id,
            "case_number": case.case_number,
            "title": case.title,
            "severity": case.severity.value,
            "status": case.status.value,
        }
    
    async def progress_capa_step(self, case_id: str, step: str, status: str) -> bool:
        """推进CAPA的某个D步骤"""
        step_map = {
            "d1": EIGHTD_STEP.D1_TEAM, "d2": EIGHTD_STEP.D2_DESCRIBE, "d3": EIGHTD_STEP.D3_CONTAIN,
            "d4": EIGHTD_STEP.D4_ROOT_CAUSE, "d5": EIGHTD_STEP.D5_PERM_CORRECTIVE,
            "d6": EIGHTD_STEP.D6_VERIFY, "d7": EIGHTD_STEP.D7_PREVENTIVE, "d8": EIGHTD_STEP.D8_CELEBRATE,
        }
        etype = step_map.get(step.lower())
        if etype:
            return self.capa_service.progress_case_step(case_id, etype, status)
        return False
    
    async def list_cases(self, limit: int = 100) -> List[Dict[str, Any]]:
        """列出所有CAPA案件"""
        cases = self.capa_service.list_cases(limit=limit)
        return [c.to_dict() for c in cases]
    
    # ==================== CAPA Enhanced Methods (5Why, Fishbone, Verification) ====================

    def capa_add_why_step(self, case_id: str, step_num: int, question: str, answer: str) -> bool:
        """Add one layer of 5Why追问 to a CAPA case"""
        case = self.capa_service.get_case(case_id)
        if case:
            case.add_why_step(step_num, question, answer)
            return True
        return False

    def capa_set_root_cause(self, case_id: str, cause: str) -> bool:
        """Directly set the root cause for a CAPA case"""
        case = self.capa_service.get_case(case_id)
        if case:
            case.set_root_cause(cause)
            return True
        return False

    def capa_add_fishbone_item(self, case_id: str, dimension: str, item: str) -> bool:
        """Add a potential cause to fishbone diagram dimension"""
        from core.qms.capa_service import FishboneDimension
        try:
            dim_enum = FishboneDimension(dimension.lower())
        except:
            return False
        
        case = self.capa_service.get_case(case_id)
        if case:
            case.add_fishbone_item(dim_enum, item)
            return True
        return False

    def capa_get_fishbone_summary(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Get full fishbone diagram summary by dimension"""
        case = self.capa_service.get_case(case_id)
        if case:
            return case.get_fishbone_summary()
        return None

    def capa_set_verification_before(self, case_id: str, metrics: Dict[str, Any]) -> bool:
        """Set baseline data before improvement"""
        case = self.capa_service.get_case(case_id)
        if case:
            case.set_verification_before(metrics)
            return True
        return False

    def capa_set_verification_after(self, case_id: str, metrics: Dict[str, Any], improved: bool, verified_by: str) -> bool:
        """Set post-improvement data and mark verification result"""
        case = self.capa_service.get_case(case_id)
        if case:
            case.set_verification_after(metrics, improved, verified_by)
            return True
        return False

    def capa_get_verification_status(self, case_id: str) -> Optional[str]:
        """Get current verification status"""
        case = self.capa_service.get_case(case_id)
        if case:
            return case.get_verification_status()
        return None

    def capa_create_action_plan(self, case_id: str, description: str, owner: str, deadline: str) -> Dict[str, Any]:
        """Create a specific corrective action plan item"""
        case = self.capa_service.get_case(case_id)
        if case:
            plan = case.add_corrective_action_plan(description, owner, deadline)
            return plan
        return {}

    def capa_update_action_status(self, case_id: str, plan_id: str, status: str, pct: int = None) -> bool:
        """Update action plan status and completion percentage"""
        case = self.capa_service.get_case(case_id)
        if case:
            return case.update_action_plan_status(plan_id, status, pct)
        return False

    def capa_record_sop_update(self, case_id: str, sop_name: str, version: str, updated_by: str, update_date: str) -> bool:
        """Record SOP document update"""
        case = self.capa_service.get_case(case_id)
        if case:
            case.record_sop_update(sop_name, version, updated_by, update_date)
            return True
        return False

    def capa_record_training(self, case_id: str, title: str, attendees: List[str], date: str) -> bool:
        """Record training implementation"""
        case = self.capa_service.get_case(case_id)
        if case:
            case.record_training_conducted(title, attendees, date)
            return True
        return False

    def capa_set_lessons_learned(self, case_id: str, text: str) -> bool:
        """Record lessons learned and standardization suggestions"""
        case = self.capa_service.get_case(case_id)
        if case:
            case.set_lessons_learned(text)
            return True
        return False

    async def get_statistics(self) -> Dict[str, Any]:
        """获取CAPA统计信息"""
        return self.capa_service.get_statistics()
    
    # ==================== 查询接口 ====================
    
    async def list_iqc_records(self, factory_id: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """列出IQ C记录"""
        records = self.iqc_service.list_records(limit=limit)
        # 转换为字典格式（简化）
        return [{"id": r.id, "status": r.status.value, "product_id": r.product_id} for r in records]
    
    async def list_fai_records(self, limit: int = 100) -> List[Dict]:
        """列出FAI记录"""
        records = self.fai_service._records.values()  # 访问内部存储（原型模式）
        return [{"id": r.id, "status": r.status.value, "product_id": r.product_id} for r in records][:limit]
    
    async def list_ipc_records(self, limit: int = 100) -> List[Dict]:
        """列出IPC记录"""
        records = self.ipc_service._records.values()
        return [{"id": r.id, "status": r.status.value, "work_order_id": r.work_order_id} for r in records][:limit]
    
    async def list_oqc_records(self, limit: int = 100) -> List[Dict]:
        """列出OQC记录"""
        records = self.oqc_service._records.values()
        return [{"id": r.id, "status": r.status.value, "order_id": r.order_id} for r in records][:limit]



    # ==================== CAPA Enhanced Methods ====================

    def capa_create_case(self, title: str, severity: str, source_type: Optional[str] = None, source_id: Optional[str] = None) -> Dict[str, Any]:
        """Create a new CAPA case"""
        case = self.capa_service.create_case(title=title, severity=CAPASeverity(severity))
        # Set source reference (create_case doesn't accept these params directly)
        if source_type:
            case.source_type = source_type
        if source_id:
            case.source_id = source_id
        return {
            "id": case.id,
            "case_number": case.case_number,
            "title": case.title,
            "severity": case.severity.value,
            "status": case.status.value,
        }
