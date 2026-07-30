"""

生产计划变更管理模块



提供计划变更申请、审批、版本追溯和影响分析功能。

这是生产计划业务闭环的关键一环，确保所有变更经过授权并记录可追溯。

"""



from datetime import datetime

from enum import Enum

from typing import Optional, Dict, Any, List, Set

from uuid import uuid4





class ChangeRequestLevel(Enum):

    """变更请求的审批级别（根据变更影响程度自动判断）"""

    LEVEL_1 = "level1"      # 小变更：数量小幅调整，无需额外审批

    LEVEL_2 = "level2"      # 中变更：需要生产经理审批

    LEVEL_3 = "level3"      # 大变更：需要计划主任或更高层级审批





class ChangeRequestStatus(Enum):

    """变更请求的状态流转"""

    PENDING = "pending"     # 待审批

    APPROVED = "approved"   # 已批准

    REJECTED = "rejected"   # 已拒绝

    PROCESSED = "processed" # 已执行





class PlanVersion:

    """生产计划的一个版本快照"""

    

    def __init__(self, plan_id: str, version_number: int, changed_by: str, 

                 change_type: str, description: str, previous_state: dict,

                 current_state: dict):

        self.id = str(uuid4())

        self.plan_id = plan_id

        self.version_number = version_number

        self.changed_by = changed_by

        self.change_type = change_type  # update / reschedule / cancel etc.

        self.description = description

        self.previous_state = previous_state  # 变更前完整状态

        self.current_state = current_state    # 变更后完整状态

        self.created_at = datetime.utcnow()

    

    def to_dict(self) -> Dict[str, Any]:

        return {

            "id": self.id,

            "plan_id": self.plan_id,

            "version_number": self.version_number,

            "changed_by": self.changed_by,

            "change_type": self.change_type,

            "description": self.description,

            "previous_state": self.previous_state,

            "current_state": self.current_state,

            "created_at": self.created_at.isoformat(),

        }





class ChangeRequest:

    """计划变更申请单——记录一次完整的变更请求及其审批流程"""

    

    def __init__(self, request_id: str, plan_id: str, factory_id: str, applicant: str,

                 changes: Dict[str, Any], description: str, change_type: str = "update"):

        self.request_id = request_id

        self.plan_id = plan_id

        self.factory_id = factory_id

        self.applicant = applicant

        self.changes = changes  # {field: {"old": old_value, "new": new_value}}

        self.description = description

        self.change_type = change_type

        self.status = ChangeRequestStatus.PENDING

        self.level = self._determine_impact_level(changes)

        self.approved_by: Optional[str] = None

        self.approved_at: Optional[datetime] = None

        self.rejected_reason: Optional[str] = None

        self.impact_analysis: Dict[str, Any] = {}

        self.created_at = datetime.utcnow()

        self.updated_at = self.created_at

    

    def _determine_impact_level(self, changes: Dict) -> ChangeRequestLevel:

        """根据变更内容自动确定所需审批级别"""

        # 检查变更字段

        has_date_change = "required_date" in changes

        has_priority_change = "priority" in changes

        has_customer_level_change = "customer_level" in changes

        has_qty_change = "quantity" in changes

        

        if has_qty_change:

            # 计算数量变化百分比

            old_qty = changes.get("quantity", {}).get("old", 0)

            new_qty = changes.get("quantity", {}).get("new", 0)

            if old_qty > 0:

                pct_change = abs(new_qty - old_qty) / old_qty

                if pct_change > 0.2:  # 超过20%的变化

                    return ChangeRequestLevel.LEVEL_3

                elif pct_change > 0.1:  # 超过10%的变化

                    return ChangeRequestLevel.LEVEL_2

        

        if has_date_change or has_priority_change or has_customer_level_change:

            return ChangeRequestLevel.LEVEL_2

        

        return ChangeRequestLevel.LEVEL_1  # 小变更，如备注等

    

    def approve(self, approved_by: str) -> None:

        """批准变更请求"""

        self.status = ChangeRequestStatus.APPROVED

        self.approved_by = approved_by

        self.approved_at = datetime.utcnow()

        self.updated_at = self.approved_at

    

    def reject(self, reason: str) -> None:

        """拒绝变更请求"""

        self.status = ChangeRequestStatus.REJECTED

        self.rejected_reason = reason

        self.updated_at = datetime.utcnow()

    

    def process(self) -> None:

        """变更已执行（批准后调用）"""

        self.status = ChangeRequestStatus.PROCESSED

        self.updated_at = datetime.utcnow()

    

    def set_impact_analysis(self, analysis: Dict[str, Any]) -> None:

        """设置影响分析结果"""

        self.impact_analysis = analysis

    

    def to_dict(self) -> Dict[str, Any]:

        result = {

            "request_id": self.request_id,

            "plan_id": self.plan_id,

            "factory_id": self.factory_id,

            "applicant": self.applicant,

            "changes": self.changes,

            "description": self.description,

            "change_type": self.change_type,

            "status": self.status.value,

            "level": self.level.value,

            "created_at": self.created_at.isoformat(),

            "updated_at": self.updated_at.isoformat(),

        }

        if self.approved_by:

            result["approved_by"] = self.approved_by

        if self.approved_at:

            result["approved_at"] = self.approved_at.isoformat()

        if self.rejected_reason:

            result["rejected_reason"] = self.rejected_reason

        if self.impact_analysis:

            result["impact_analysis"] = self.impact_analysis

        return result





class ChangeManagementService:
    """变更管理服务——处理所有计划变更的申请、审批和版本控制"""
    
    def __init__(self):
        self._requests = {}
        self._versions = {}
    
    def create_change_request(
        self,
        plan_id: str,
        factory_id: str,
        applicant: str,
        changes: dict,
        description: str,
        change_type: str = "update",
    ) -> ChangeRequest:
        """创建新的变更请求"""
        from datetime import datetime
        from uuid import uuid4
        request_id = f"PCR-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid4())[:8]}"
        
        request = ChangeRequest(
            request_id=request_id,
            plan_id=plan_id,
            factory_id=factory_id,
            applicant=applicant,
            changes=changes,
            description=description,
            change_type=change_type,
        )
        self._requests[request_id] = request
        if plan_id not in self._versions:
            self._versions[plan_id] = []
        return request
    
    def get_request(self, request_id: str) -> Optional[ChangeRequest]:
        """获取单个变更请求"""
        return self._requests.get(request_id)
    
    def list_requests(self, plan_id: Optional[str] = None, limit: int = 100) -> List[ChangeRequest]:
        """列出变更请求（带过滤条件）"""
        results = list(self._requests.values())
        if plan_id:
            results = [r for r in results if r.plan_id == plan_id]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]
    
    def approve_change_request(self, request_id: str, approved_by: str) -> bool:
        """批准变更请求"""
        request = self._requests.get(request_id)
        if request and request.status == ChangeRequestStatus.PENDING:
            request.approve(approved_by)
            if request.level == ChangeRequestLevel.LEVEL_1:
                # Level1 自动应用
                self._apply_change_request(request)
            return True
        return False
    
    def reject_change_request(self, request_id: str, reason: str) -> bool:
        """拒绝变更请求"""
        request = self._requests.get(request_id)
        if request and request.status == ChangeRequestStatus.PENDING:
            request.reject(reason)
            return True
        return False
    
    def _apply_change_request(self, request: ChangeRequest) -> bool:
        """内部方法：应用已批准的变更到计划（由 MPSService 调用）"""
        # 这个服务本身不直接访问计划，因为计划在其他服务中
        # 实际实现应由 MPSService 调用并结合其自身的 _plans 字典
        return True
    
    def get_versions(self, plan_id: str) -> List[PlanVersion]:
        """获取计划的版本历史"""
        return self._versions.get(plan_id, [])


# 全局实例（单例模式供其他模块使用）



    def create_change_request(

        self,

        plan_id: str,

        factory_id: str,

        applicant: str,

        changes: Dict[str, Any],

        description: str,

        change_type: str = "update",

    ) -> ChangeRequest:

        """创建新的变更请求"""

        from datetime import datetime

        from uuid import uuid4

        request_id = f"PCR-{datetime.utcnow().strftime('%Y%m%d')}-{str(uuid4())[:8]}"

        

        request = ChangeRequest(

            request_id=request_id,

            plan_id=plan_id,

            factory_id=factory_id,

            applicant=applicant,

            changes=changes,

            description=description,

            change_type=change_type,

        )

        

        self._requests[request_id] = request

        if plan_id not in self._versions:

            self._versions[plan_id] = []

        

        return request





    def add_version(
        self,
        plan_id: str,
        version_number: int,
        changed_by: str,
        change_type: str,
        description: str,
        previous_state: dict,
        current_state: dict,
    ) -> PlanVersion:
        """添加计划版本快照"""
        from datetime import datetime
        version = PlanVersion(
            plan_id=plan_id,
            version_number=version_number,
            changed_by=changed_by,
            change_type=change_type,
            description=description,
            previous_state=previous_state,
            current_state=current_state,
        )
        if plan_id not in self._versions:
            self._versions[plan_id] = []
        self._versions[plan_id].append(version)
        return version


# 全局单例实例（供其他模块使用）
change_mgmt_service = ChangeManagementService()
