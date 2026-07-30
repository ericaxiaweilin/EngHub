"""
Workflow Rule Service - 工作流规则服务 (D方案)
===============================================

从数据库读取状态转移规则和权限门禁，支持动态配置而无需修改代码。

This service provides access to workflow configuration stored in the database:
- State transitions: which states can transition to which
- Action gates: which roles are required for each action

When the database has no rules or there are errors, falls back to defaults.
"""

from typing import List, Optional, Dict, Any
from sqlalchemy import select

from database.models import WorkflowActionGate, WorkflowStateRule
from sqlalchemy.ext.asyncio import AsyncSession


class WorkflowRuleService:
    """提供工作流规则的访问接口"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ============================================================
    # ACTION GATES - 权限门禁查询
    # ============================================================
    async def get_allowed_roles(self, action: str, factory_id: str) -> List[str]:
        """
        获取指定动作在指定工厂允许的角色列表
        
        Args:
            action: 动作名称（如 release, complete, close...）
            factory_id: 工厂ID
            
        Returns:
            角色字符串列表
        """
        try:
            stmt = select(WorkflowActionGate.required_role).where(
                WorkflowActionGate.action == action,
                WorkflowActionGate.factory_id.in_([factory_id, 'ALL']),
                WorkflowActionGate.is_active == True,
            )
            result = await self.db.execute(stmt)
            roles = result.scalars().all()
            return list(set(roles))
        except Exception as e:
            print(f"[WARN] Querying action gates from DB failed: {e}")
            # 回退到硬编码默认值
            return self._get_default_action_gates(action)
    
    def _get_default_action_gates(self, action: str) -> List[str]:
        """默认的权限门禁（当数据库不可用时使用）"""
        default_gates = {
            "release": ["factory_manager", "production_manager", "admin"],
            "complete": ["factory_manager", "quality_manager", "admin"],
            "close": ["factory_manager", "admin"],
            "pause": ["operator", "team_leader"],
            "resume": ["operator", "team_leader"],
            "cancel": ["operator", "team_leader"],
        }
        return default_gates.get(action, [])
    
    # ============================================================
    # STATE TRANSITIONS - 状态转移规则查询
    # ============================================================
    async def get_allowed_transitions(self, from_status: str, factory_id: str) -> List[str]:
        """
        获取指定状态可以转移到的目标状态列表
        
        Args:
            from_status: 当前状态（如 draft, released, in_progress...）
            factory_id: 工厂ID
            
        Returns:
            目标状态字符串列表
        """
        try:
            stmt = select(WorkflowStateRule.allowed_next_state).where(
                WorkflowStateRule.current_state == from_status,
                WorkflowStateRule.factory_id.in_([factory_id, 'ALL']),
                WorkflowStateRule.is_active == True,
            )
            result = await self.db.execute(stmt)
            next_states = result.scalars().all()
            return list(set(next_states))
        except Exception as e:
            print(f"[WARN] Querying state transitions from DB failed: {e}")
            return self._get_default_transitions(from_status)
    
    def _get_default_transitions(self, from_status: str) -> List[str]:
        """默认的状态转移规则（当数据库不可用时使用）"""
        defaults = {
            "draft": ["pending", "cancelled"],
            "pending": ["released", "cancelled"],
            "released": ["in_progress", "on_hold", "cancelled"],
            "in_progress": ["on_hold", "pending_inbound", "completed", "cancelled"],
            "on_hold": ["in_progress", "cancelled"],
            "pending_inbound": ["completed"],
            "completed": [],
            "closed": [],
            "cancelled": [],
        }
        return defaults.get(from_status, [])
    
    # ============================================================
    # HELPER - 完整的工作流规则字典
    # ============================================================
    async def get_all_rules(self, factory_id: str) -> Dict[str, Any]:
        """
        获取所有工作流规则（用于UI展示或备份）
        
        Returns:
            包含 state_rules 和 action_gates 的字典
        """
        # 获取状态转移规则
        state_stmt = select(WorkflowStateRule).where(
            WorkflowStateRule.factory_id.in_([factory_id, 'ALL']),
            WorkflowStateRule.is_active == True,
        ).order_by(WorkflowStateRule.sort_order)
        state_result = await self.db.execute(state_stmt)
        state_rules = state_result.scalars().all()
        
        # 获取动作门禁
        action_stmt = select(WorkflowActionGate).where(
            WorkflowActionGate.factory_id.in_([factory_id, 'ALL']),
            WorkflowActionGate.is_active == True,
        ).order_by(WorkflowActionGate.sort_order)
        action_result = await self.db.execute(action_stmt)
        action_gates = action_result.scalars().all()
        
        return {
            'state_rules': [{
                'id': r.id,
                'current_state': r.current_state,
                'allowed_next_state': r.allowed_next_state,
                'description': r.description,
                'sort_order': r.sort_order,
            } for r in state_rules],
            'action_gates': [{
                'id': g.id,
                'action': g.action,
                'required_role': g.required_role,
                'description': g.description,
                'sort_order': g.sort_order,
            } for g in action_gates],
        }


__all__ = ["WorkflowRuleService"]
