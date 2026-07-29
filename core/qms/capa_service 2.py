"""
CAPA（Corrective and Preventive Action）纠正预防措施业务模块

提供完整的问题管理流程：从问题发现、根本原因分析、
到纠正预防措施的制定、执行跟踪和效果验证。
支持8D报告结构和5Why分析法等质量工具。
增强功能包括：5Why深层分析、鱼骨图分类归因、效果验证闭环。
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List
from uuid import uuid4


# ==================== 枚举与常量定义 ====================

class CAPASeverity(str, Enum):
    """问题严重程度"""
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class CAPAStatus(str, Enum):
    """CAPA案件状态"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    CLOSED = "closed"


class EIGHTD_STEP(Enum):
    """8D步骤编号"""
    D1_TEAM = "D1: 组建跨部门团队"
    D2_DESCRIBE = "D2: 描述问题"
    D3_CONTAIN = "D3: 临时遏制措施"
    D4_ROOT_CAUSE = "D4: 根本原因分析"
    D5_PERM_CORRECTIVE = "D5: 永久纠正措施"
    D6_VERIFY = "D6: 验证措施有效性"
    D7_PREVENTIVE = "D7: 预防措施更新标准"
    D8_CELEBRATE = "D8: 庆祝与经验总结"


class FishboneDimension(str, Enum):
    """鱼骨图（石川图）维度分类"""
    MAN = "man"       # 人员
    MACHINE = "machine"  # 设备
    MATERIAL = "material"  # 材料
    METHOD = "method"    # 方法/工艺
    MEASUREMENT = "measurement"  # 测量/检测
    ENVIRONMENT = "environment"    # 环境


class VerificationStatus(str, Enum):
    """效果验证状态"""
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


# ==================== CAPACase 实体类 ====================

class CAPACase:
    """CAPA案件实体——完整的8D问题记录 + 增强分析功能"""
    
    def __init__(self, case_number: str, title: str, severity: CAPASeverity):
        self.id = str(uuid4())
        self.case_number = case_number
        self.title = title
        self.severity = severity
        
        # 标准字段
        self.created_by = "system"
        self.created_at = datetime.utcnow()
        self.updated_at = self.created_at
        self.status = CAPAStatus.OPEN
        
        # 8D各步骤的状态和时间戳
        self.step_status = {step: "not_started" for step in EIGHTD_STEP}
        self.step_completed_at = {step: None for step in EIGHTD_STEP}
        
        # D1: 团队成员
        self.team_members: List[str] = []
        
        # D2: 问题详细描述
        self.problem_description: str = ""
        self.where_found: str = ""
        self.when_detected: str = ""
        self.extent: str = ""
        
        # D3: 临时遏制措施
        self.interim_actions: List[Dict] = []
        
        # D4: 根本原因分析 - 增强字段
        self.whys: Dict[str, Any] = {}  # 5Why逐层追问记录
        self.root_cause: str = ""  # 根本原因
        self.causes_used: List[str] = []  # 使用的分析方法 ["5Why", "Fishbone", "FMEA"]
        
        # 鱼骨图 - 各维度的潜在原因列表
        self.fishbone_dimensions = {
            FishboneDimension.MAN: [],
            FishboneDimension.MACHINE: [],
            FishboneDimension.MATERIAL: [],
            FishboneDimension.METHOD: [],
            FishboneDimension.MEASUREMENT: [],
            FishboneDimension.ENVIRONMENT: [],
        }
        
        # D5: 永久纠正措施行动计划
        self.corrective_action_plans: List[Dict] = []
        
        # D6: 验证结果 - 增强字段
        self.verification_results: Dict[str, Any] = {}
        
        # D7: 预防措施更新
        self.preventive_updates: Dict[str, Any] = {}
        
        # D8: 经验教训
        self.lessons_learned_text: str = ""
    
    # ==================== D1: 团队管理 ====================
    
    def add_team_member(self, user_id: str) -> None:
        """添加团队成员"""
        if user_id not in self.team_members:
            self.team_members.append(user_id)
    
    def remove_team_member(self, user_id: str) -> bool:
        """移除团队成员"""
        if user_id in self.team_members:
            self.team_members.remove(user_id)
            return True
        return False
    
    # ==================== D2: 问题描述 ====================
    
    def set_problem_description(self, desc: str) -> None:
        self.problem_description = desc
    
    def set_where_found(self, where: str) -> None:
        self.where_found = where
    
    def set_when_detected(self, when: str) -> None:
        self.when_detected = when
    
    def set_extent(self, extent: str) -> None:
        self.extent = extent
    
    # ==================== D3: 临时遏制措施 ====================
    
    def add_interim_action(self, description: str, owner: str, deadline: str, status: str = "planned") -> None:
        """添加临时遏制措施项"""
        self.interim_actions.append({
            "description": description,
            "owner": owner,
            "deadline": deadline,
            "status": status,
        })
    
    def update_interim_action(self, idx: int, status: str) -> bool:
        """更新临时措施状态"""
        if 0 <= idx < len(self.interim_actions):
            self.interim_actions[idx]["status"] = status
            return True
        return False
    
    # ==================== D4: 根本原因分析（5Why & 鱼骨图） ====================
    
    def add_why_step(self, step_num: int, why_question: str, answer: str) -> None:
        """添加5Why分析的某一层追问和回答"""
        if not hasattr(self, 'whys') or self.whys is None:
            self.whys = {}
        self.whys[f"why{step_num}"] = {
            "question": why_question,
            "answer": answer,
        }
        if step_num >= 4:
            self.root_cause = answer
    
    def get_why_analysis(self) -> Dict[str, Any]:
        """获取完整的5Why分析结构"""
        return {
            "whys": self.whys or {},
            "root_cause": self.root_cause or "",
            "steps_completed": len(self.whys or {}),
        }
    
    def set_root_cause(self, cause: str) -> None:
        """直接设置根本原因"""
        self.root_cause = cause
    
    def add_fishbone_item(self, dimension: FishboneDimension, item: str) -> None:
        """向鱼骨图的某个维度添加一个潜在原因项"""
        dim_key = dimension.value
        if dim_key in self.fishbone_dimensions:
            if item not in self.fishbone_dimensions[dim_key]:
                self.fishbone_dimensions[dim_key].append(item)
    
    def get_fishbone_summary(self) -> Dict[str, Any]:
        """获取鱼骨图的完整概览"""
        summary = {}
        for dim, items in self.fishbone_dimensions.items():
            summary[dim.value] = items
        return summary
    
    def clear_fishbone(self) -> None:
        """清空所有维度的鱼骨图条目"""
        for dim in self.fishbone_dimensions:
            self.fishbone_dimensions[dim] = []
    
    # ==================== D5: 纠正措施计划 ====================
    
    def add_corrective_action_plan(self, action_desc: str, owner: str, deadline: str) -> Dict[str, Any]:
        """添加一个具体的纠正措施行动计划项"""
        plan_id = str(uuid4())[:8]
        plan = {
            "id": plan_id,
            "description": action_desc,
            "owner": owner,
            "deadline": deadline,
            "status": "planned",
            "completion_pct": 0,
        }
        if not hasattr(self, 'corrective_action_plans') or self.corrective_action_plans is None:
            self.corrective_action_plans = []
        self.corrective_action_plans.append(plan)
        return plan
    
    def update_action_plan_status(self, plan_id: str, status: str, completion_pct: int = None) -> bool:
        """更新某个行动计划项的状态和完成百分比"""
        plans = getattr(self, 'corrective_action_plans', []) or []
        for plan in plans:
            if plan.get("id") == plan_id:
                plan["status"] = status
                if completion_pct is not None:
                    plan["completion_pct"] = completion_pct
                return True
        return False
    
    def mark_all_plans_completed(self) -> None:
        """将所有行动计划标记为已完成"""
        plans = getattr(self, 'corrective_action_plans', []) or []
        for plan in plans:
            plan["status"] = "completed"
            plan["completion_pct"] = 100
    
    # ==================== D6: 效果验证 ====================
    
    def set_verification_before(self, metrics: Dict[str, Any]) -> None:
        """设置改进前的基线数据"""
        if not hasattr(self, 'verification_results') or self.verification_results is None:
            self.verification_results = {}
        self.verification_results["before"] = metrics
    
    def set_verification_after(self, metrics: Dict[str, Any], improved: bool, verified_by: str) -> None:
        """设置改进后的数据并标记验证结果"""
        if not hasattr(self, 'verification_results') or self.verification_results is None:
            self.verification_results = {}
        self.verification_results["after"] = metrics
        self.verification_results["improved"] = improved
        self.verification_results["verified_by"] = verified_by
        self.verification_results["verified_at"] = datetime.utcnow().isoformat()
        if improved:
            self.status = CAPAStatus.VERIFIED
    
    def get_verification_status(self) -> str:
        """获取当前效果验证的状态"""
        vr = getattr(self, 'verification_results', {}) or {}
        if "verified_at" in vr:
            return VerificationStatus.VERIFIED.value
        return VerificationStatus.PENDING.value
    
    # ==================== D7: 预防措施 ====================
    
    def record_sop_update(self, sop_name: str, version: str, updated_by: str, update_date: str) -> None:
        """记录SOP文件更新情况"""
        if not hasattr(self, 'preventive_updates') or self.preventive_updates is None:
            self.preventive_updates = {}
        if "sops_updated" not in self.preventive_updates:
            self.preventive_updates["sops_updated"] = []
        self.preventive_updates["sops_updated"].append({
            "sop_name": sop_name,
            "version": version,
            "updated_by": updated_by,
            "update_date": update_date,
        })
    
    def record_training_conducted(self, training_title: str, attendees: List[str], date: str) -> None:
        """记录培训实施情况"""
        if not hasattr(self, 'preventive_updates') or self.preventive_updates is None:
            self.preventive_updates = {}
        self.preventive_updates["training_conducted"] = True
        self.preventive_updates["training_details"] = {
            "title": training_title,
            "attendees": attendees,
            "date": date,
        }
    
    # ==================== D8: 经验教训 ====================
    
    def set_lessons_learned(self, text: str) -> None:
        """记录本次CAPA的经验教训和标准化建议"""
        self.lessons_learned_text = text
    
    # ==================== 通用步骤推进 ====================
    
    def update_step_status(self, step: EIGHTD_STEP, status: str, completed_at: Optional[datetime] = None) -> None:
        """更新某个D步骤的状态"""
        self.step_status[step] = status
        if completed_at:
            self.step_completed_at[step] = completed_at
        self.updated_at = datetime.utcnow()
        
        # 如果所有步骤都完成且标记为closed，则自动关闭案件
        if all(st == "completed" for st in self.step_status.values()):
            self.status = CAPAStatus.CLOSED
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式用于序列化/API响应"""
        result = {
            "id": self.id,
            "case_number": self.case_number,
            "title": self.title,
            "severity": self.severity.value,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "updated_at": self.updated_at.isoformat(),
            "team_members": self.team_members,
            "problem_description": self.problem_description,
            "where_found": self.where_found,
            "when_detected": self.when_detected,
            "extent": self.extent,
            "interim_actions": self.interim_actions,
            "root_cause": self.root_cause,
            "causes_used": self.causes_used,
            "corrective_action_plans": self.corrective_action_plans,
            "verification_results": self.verification_results,
            "preventive_updates": self.preventive_updates,
            "lessons_learned": self.lessons_learned_text,
            "step_status": {s.value: st for s, st in self.step_status.items()},
            "fishbone_summary": self.get_fishbone_summary(),
            "why_analysis": self.get_why_analysis(),
        }
        return result


# ==================== CAPAService 服务类 ====================

class CAPAService:
    """CAPA业务服务类——管理CAPA案件的完整生命周期"""
    
    def __init__(self):
        self._cases = {}
        self._actions = {}
        self._next_case_number = 1
    
    def create_case(self, title: str, severity: CAPASeverity) -> CAPACase:
        """创建一个新的CAPA案件"""
        case_number = f"CAPA-{datetime.utcnow().strftime('%Y')}-{self._next_case_number:03d}"
        self._next_case_number += 1
        
        case = CAPACase(case_number, title, severity)
        case.created_by = "system"
        self._cases[case.id] = case
        return case
    
    def get_case(self, case_id: str) -> Optional[CAPACase]:
        """获取单个CAPA案件"""
        return self._cases.get(case_id)
    
    def list_cases(self, status: Optional[CAPAStatus] = None, severity: Optional[CAPASeverity] = None, limit: int = 100) -> List[CAPACase]:
        """列出CAPA案件（带过滤条件）"""
        results = list(self._cases.values())
        if status:
            results = [r for r in results if r.status == status]
        if severity:
            results = [r for r in results if r.severity == severity]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]
    
    def add_team_member(self, case_id: str, user_id: str) -> bool:
        """添加团队成员到案件"""
        case = self._cases.get(case_id)
        if case:
            case.add_team_member(user_id)
            return True
        return False
    
    def progress_case_step(self, case_id: str, step: EIGHTD_STEP, status: str) -> bool:
        """推进某个D步骤的状态"""
        case = self._cases.get(case_id)
        if case:
            case.update_step_status(step, status)
            if all(st == "completed" for st in case.step_status.values()):
                case.status = CAPAStatus.CLOSED
            return True
        return False
    
    def create_corrective_action(self, case_id: str, description: str, assigned_to: str, deadline: datetime) -> Dict[str, Any]:
        """创建永久纠正措施的行动项"""
        case = self._cases.get(case_id)
        if not case:
            raise ValueError("CAPA案件不存在")
        
        plan_id = str(uuid4())[:8]
        plan = {
            "id": plan_id,
            "description": description,
            "owner": assigned_to,
            "deadline": deadline.isoformat(),
            "status": "in_progress",
        }
        case.corrective_action_plans.append(plan)
        self._actions[plan_id] = plan
        return plan
    
    def verify_case(
        self,
        case_id: str,
        verification_result: str,
        verified_by: str,
    ) -> bool:
        """验证CAPA措施的有效性"""
        case = self._cases.get(case_id)
        if case:
            case.set_verification_after(
                metrics={"result": verification_result},
                improved=True,
                verified_by=verified_by,
            )
            return True
        return False
    
    def close_case(self, case_id: str) -> bool:
        """关闭CAPA案件（验证通过后）"""
        case = self._cases.get(case_id)
        if case and case.status == CAPAStatus.VERIFIED:
            case.step_status[EIGHTD_STEP.D8_CELEBRATE] = "completed"
            case.status = CAPAStatus.CLOSED
            return True
        return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取CAPA统计信息"""
        total = len(self._cases)
        open_count = sum(1 for c in self._cases.values() if c.status == CAPAStatus.OPEN)
        in_progress_count = sum(1 for c in self._cases.values() if c.status == CAPAStatus.IN_PROGRESS)
        verified_count = sum(1 for c in self._cases.values() if c.status == CAPAStatus.VERIFIED)
        closed_count = sum(1 for c in self._cases.values() if c.status == CAPAStatus.CLOSED)
        
        return {
            "total_cases": total,
            "open": open_count,
            "in_progress": in_progress_count,
            "verified": verified_count,
            "closed": closed_count,
        }
