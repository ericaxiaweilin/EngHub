"""
插单审批服务 —— 插单/急单决策全链路（评估→提报→审批→执行→留痕）

审计 Q4 改造：把计划员个人裁量的插单决策，变为
  决策权分配（按影响等级绑定角色）+ 审批流（状态机）+ 落库留痕。

核心职责：
1. create_from_eval：把 rush-order-impact 评估结果落库为审批单草稿
2. submit/approve/reject/cancel：状态机推进，approve 触发调度执行
3. 角色校验 + 防自我审批
4. 审批日志 + 状态流转留痕
"""

from datetime import datetime
from typing import Dict, Any, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    RushOrderApproval,
    RushOrderApprovalLog,
    WoStatusLog,
    WorkOrder,
)

# 决策权矩阵：影响等级 → 审批人角色编码（复用现有 RBAC，零新权限）
# L1: 无影响或延迟≤24h → 计划主管自审（需原因）
# L2: 延迟≤72h → 生产经理
# L3: 延迟>72h / emergency / 影响高优先级 → 生产处长或厂长
LEVEL_ROLE_MAP = {
    1: "planner",
    2: "production_manager",
    3: "production_director",
}

# 允许自审的等级（L1 例外：影响可控，计划员可自审但需原因）
SELF_APPROVE_LEVELS = {1}

VALID_TRANSITIONS = {
    "draft": {"submit"},
    "submitted": {"approve", "reject"},
    "approved": {"execute"},
    "executed": set(),
    "rejected": set(),
    "cancelled": set(),
}


def determine_approval_level(
    affected_orders: int,
    max_delay_days: float,
    rush_priority: str,
    impact_json: Optional[dict] = None,
) -> int:
    """按决策权矩阵自动定级。

    - emergency 强制 L3（全厂重排不可逆）
    - 延迟 > 72h（3 天）→ L3
    - 延迟 ≤ 24h 且无高风险订单 → L1
    - 其余（≤72h）→ L2
    """
    if rush_priority == "emergency":
        return 3

    # 影响高客户等级订单 → 升 L3
    if impact_json:
        delayed = impact_json.get("delayed_orders") or []
        if any(
            (o.get("priority") in ("urgent", "emergency"))
            or (o.get("customer_level") == "a")
            for o in delayed
        ):
            return 3

    if max_delay_days <= 1.0:
        return 1
    if max_delay_days <= 3.0:
        return 2
    return 3


def _user_roles(user) -> List[str]:
    """提取用户角色编码列表（兼容 role / role_code / user_roles 多形态）。"""
    roles: List[str] = []
    role = getattr(user, "role", None)
    if role:
        roles.append(role)
    role_code = getattr(user, "role_code", None)
    if role_code and role_code not in roles:
        roles.append(role_code)
    user_roles = getattr(user, "user_roles", None)
    if user_roles:
        for ur in user_roles:
            r = getattr(ur, "role_obj", None) or ur
            code = getattr(r, "role_code", None)
            if code and code not in roles:
                roles.append(code)
    return roles


def _can_approve_level(user, level: int) -> bool:
    """判断用户是否能审批指定级别（持有对应角色或 superuser/admin）。"""
    if getattr(user, "is_superuser", False) or getattr(user, "role", None) == "admin":
        return True
    roles = _user_roles(user)
    if not roles:
        return False
    # 审批角色本身具备；或更高层级角色（factory_manager 全权限）也可批
    allowed = {LEVEL_ROLE_MAP[level], "factory_manager"}
    return bool(set(roles) & allowed)


class RushApprovalService:
    """插单审批引擎（DB 持久化）"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─────────────── 内部工具 ───────────────

    async def _log(self, approval_id: str, action: str, actor: str, actor_role: Optional[str], comment: Optional[str] = None) -> None:
        self.db.add(RushOrderApprovalLog(
            approval_id=approval_id,
            action=action,
            actor=actor,
            actor_role=actor_role,
            comment=comment,
        ))

    @staticmethod
    def _gen_code(factory_id: str) -> str:
        return f"RA-{datetime.utcnow().strftime('%Y%m%d')}-{uuid4().hex[:6]}"

    # ─────────────── 查询 ───────────────

    async def get(self, approval_id: str) -> Optional[RushOrderApproval]:
        return await self.db.get(RushOrderApproval, approval_id)

    async def list_by(self, factory_id: str, status: Optional[str] = None, applicant: Optional[str] = None, limit: int = 50) -> List[RushOrderApproval]:
        stmt = select(RushOrderApproval).where(RushOrderApproval.factory_id == factory_id)
        if status:
            stmt = stmt.where(RushOrderApproval.status == status)
        if applicant:
            stmt = stmt.where(RushOrderApproval.applicant == applicant)
        stmt = stmt.order_by(RushOrderApproval.created_at.desc()).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def list_logs(self, approval_id: str) -> List[RushOrderApprovalLog]:
        stmt = select(RushOrderApprovalLog).where(
            RushOrderApprovalLog.approval_id == approval_id
        ).order_by(RushOrderApprovalLog.created_at.asc())
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    # ─────────────── 流程动作 ───────────────

    async def create_from_eval(
        self,
        *,
        factory_id: str,
        product_id: str,
        quantity: int,
        due_date: Optional[str],
        rush_priority: str,
        impact: Dict[str, Any],
        rush: Dict[str, Any],
        recommendation: str,
        applicant: str,
    ) -> Dict[str, Any]:
        """把 rush-order-impact 评估结果落库为审批单草稿。"""
        affected_orders = int(impact.get("affected_orders", 0))
        max_delay_days = float(impact.get("max_delay_hours", 0) or 0) / 24.0
        if impact.get("max_delay_days") is not None:
            max_delay_days = float(impact["max_delay_days"])
        # 兼容旧字段名
        delayed_orders = impact.get("delayed_orders", [])
        impact_json = {
            "affected_orders": affected_orders,
            "total_existing_orders": impact.get("total_existing_orders", 0),
            "max_delay_hours": impact.get("max_delay_hours", 0),
            "delayed_orders": delayed_orders,
            "rush_feasible": rush.get("due_feasible", True),
        }

        level = determine_approval_level(affected_orders, max_delay_days, rush_priority, impact_json)
        from datetime import date
        due = None
        if due_date:
            try:
                due = date.fromisoformat(due_date)
            except ValueError:
                due = None

        approval = RushOrderApproval(
            approval_code=self._gen_code(factory_id),
            factory_id=factory_id,
            product_id=product_id,
            quantity=quantity,
            due_date=due,
            rush_priority=rush_priority,
            impact_json=impact_json,
            affected_orders=affected_orders,
            max_delay_days=max_delay_days,
            process_hours=rush.get("process_hours"),
            recommendation=recommendation,
            approval_level=level,
            required_role=LEVEL_ROLE_MAP.get(level, "production_manager"),
            status="draft",
            applicant=applicant,
            created_by=applicant,
        )
        self.db.add(approval)
        await self.db.flush()
        await self._log(approval.id, "draft", applicant, None, "评估完成，生成审批单草稿")
        await self.db.commit()

        return approval.to_dict() | {"logs": await self._logs_dict(approval.id)}

    async def _logs_dict(self, approval_id: str) -> List[Dict[str, Any]]:
        logs = await self.list_logs(approval_id)
        return [l.to_dict() for l in logs]

    async def submit(self, approval_id: str, actor: str, comment: Optional[str] = None) -> Dict[str, Any]:
        approval = await self.get(approval_id)
        if not approval:
            return {"success": False, "message": "审批单不存在"}
        if approval.status != "draft":
            return {"success": False, "message": f"当前状态 {approval.status} 不能提报"}

        approval.status = "submitted"
        approval.updated_at = datetime.utcnow()
        await self._log(approval.id, "submit", actor, None, comment)
        await self.db.commit()
        return {"success": True, "data": approval.to_dict()}

    async def approve(
        self,
        approval_id: str,
        actor: str,
        user,
        comment: Optional[str] = None,
        *,
        run_execute: bool = True,
    ) -> Dict[str, Any]:
        """审批通过。校验角色 + 防自我审批，通过后触发调度执行。"""
        approval = await self.get(approval_id)
        if not approval:
            return {"success": False, "message": "审批单不存在"}
        if approval.status != "submitted":
            return {"success": False, "message": f"当前状态 {approval.status} 不能审批"}

        # 防自我审批（L1 除外）
        if approval.approval_level not in SELF_APPROVE_LEVELS and approval.applicant == actor:
            return {"success": False, "message": "申请人与审批人不能为同一人"}

        # 角色校验
        if not _can_approve_level(user, approval.approval_level):
            return {
                "success": False,
                "message": f"角色权限不足：本单需 {approval.required_role} 及以上审批（L{approval.approval_level}）",
            }

        approval.status = "approved"
        approval.approver = actor
        approval.approved_at = datetime.utcnow()
        approval.updated_at = datetime.utcnow()
        await self._log(approval.id, "approve", actor, getattr(user, "role", None), comment)

        result = {"success": True, "execution": None}
        if run_execute:
            exec_res = await self._execute(approval, actor)
            result["execution"] = exec_res
            if not exec_res.get("success"):
                # 执行失败则回滚审批状态，便于重新审批
                approval.status = "submitted"
                approval.updated_at = datetime.utcnow()

        await self.db.commit()
        if not result.get("execution") or result["execution"].get("success"):
            return result
        return {"success": False, "message": result["execution"].get("message", "调度执行失败")}

    async def _execute(self, approval: RushOrderApproval, actor: str) -> Dict[str, Any]:
        """批准后执行：紧急单全厂重排 / 普通插单增量重排。"""
        try:
            from api.services.aps_service import ApsService

            svc = ApsService(self.db)
            if approval.rush_priority in ("urgent", "emergency"):
                # 紧急单 → 全厂重排
                result = await svc.reschedule(
                    factory_id=approval.factory_id,
                    created_by=actor,
                    change_reason=f"插单审批 {approval.approval_code} 通过",
                )
            else:
                result = await svc.reschedule(
                    factory_id=approval.factory_id,
                    created_by=actor,
                    change_reason=f"插单审批 {approval.approval_code} 通过",
                )
            if not result.get("schedule_id"):
                return {"success": False, "message": result.get("message", "调度未生成新排程")}

            approval.target_schedule_id = result["schedule_id"]
            approval.status = "executed"
            approval.executed_at = datetime.utcnow()
            approval.updated_at = datetime.utcnow()
            await self._log(approval.id, "execute", actor, None, f"新排程 {result['schedule_id']} 已生成")
            return {"success": True, "schedule_id": result["schedule_id"]}
        except Exception as e:
            return {"success": False, "message": str(e)}

    async def reject(self, approval_id: str, actor: str, user, reason: str) -> Dict[str, Any]:
        approval = await self.get(approval_id)
        if not approval:
            return {"success": False, "message": "审批单不存在"}
        if approval.status != "submitted":
            return {"success": False, "message": f"当前状态 {approval.status} 不能驳回"}
        if not _can_approve_level(user, approval.approval_level):
            return {"success": False, "message": f"角色权限不足：本单需 {approval.required_role} 及以上审批"}
        if not reason:
            return {"success": False, "message": "驳回必须填写原因"}

        approval.status = "rejected"
        approval.reject_reason = reason
        approval.updated_at = datetime.utcnow()
        await self._log(approval.id, "reject", actor, getattr(user, "role", None), reason)
        await self.db.commit()
        return {"success": True, "data": approval.to_dict()}

    async def cancel(self, approval_id: str, actor: str, user) -> Dict[str, Any]:
        approval = await self.get(approval_id)
        if not approval:
            return {"success": False, "message": "审批单不存在"}
        if approval.status not in ("draft", "submitted"):
            return {"success": False, "message": f"当前状态 {approval.status} 不能撤销"}
        if approval.applicant != actor and not getattr(user, "is_superuser", False):
            return {"success": False, "message": "仅申请人可撤销"}

        approval.status = "cancelled"
        approval.updated_at = datetime.utcnow()
        await self._log(approval.id, "cancel", actor, None, None)
        await self.db.commit()
        return {"success": True, "data": approval.to_dict()}

    # ─────────────── 调度挂钩辅助 ───────────────

    async def find_approved_for_wo(self, factory_id: str, product_id: str) -> Optional[RushOrderApproval]:
        """调度代理查询：该产品是否有已批准未执行的插单审批单。

        用于把 scheduling_agent 的"紧急单直接重排"改为"有批文才重排"。
        """
        stmt = select(RushOrderApproval).where(
            RushOrderApproval.factory_id == factory_id,
            RushOrderApproval.product_id == product_id,
            RushOrderApproval.status == "approved",
        ).order_by(RushOrderApproval.created_at.desc()).limit(1)
        res = await self.db.execute(stmt)
        return res.scalars().first()
