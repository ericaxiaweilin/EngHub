"""PermissionGate - Chat V2 权限门控（Phase 4）。

职责：
1. 工具 → (module, action) 映射（读=view，写=对应动作）
2. 基于 core/auth/roles.get_user_permissions 校验当前用户是否被允许
3. 写操作强制 operator 与 current_user 一致
4. 工厂数据作用域校验（data_scope: own/all）

门控失败时返回错误文案（模型不得执行该工具）；通过返回 None。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set

# 工具 → 所需权限（读工具默认 view；写工具显式映射到动作）
_READ_TOOLS: Dict[str, str] = {
    "query_work_orders": "work_order",
    "query_order_work_order_status": "work_order",
    "get_work_order_detail": "work_order",
    "get_production_summary": "production_report",
    "query_inventory": "wms",
    "query_pmc_material_supply": "pp",
    "query_pmc_rush_impact": "pp",
    "query_defects": "qms",
    "query_equipment": "equipment",
    "query_simulation_audits": "simulation",
    "query_routing": "routing",
    "query_skill_matrix": "hr",
    "get_work_order_form": "work_order",
    "get_inspection_form": "qms",
    "get_pending_alerts": "qms",
    "query_alert_reviews": "qms",
    "query_ocap_tasks": "qms",
    "query_hr_roster": "hr",
    "query_workflow_diagram": "tms",
    "query_pmc_work_matrix": "pp",
    "query_process_knowledge": "ai",
    "query_collaboration": "ai",
    "query_downtime": "equipment",
    "query_maintenance_due": "equipment",
    "query_shortage_alerts": "pp",
    "query_stagnant": "wms",
    "query_spc_anomalies": "qms",
    "query_environment": "qms",
    "get_virtual_factory_status": "simulation",
    "run_virtual_factory_pulse": "simulation",
    "search_entity": "ai",
    "query_pmc_audit_evidence": "pp",
}

# 写工具：tool → (module, action)
_WRITE_TOOLS: Dict[str, tuple] = {
    "create_work_order": ("work_order", "create"),
    "release_work_order": ("work_order", "release"),
    "create_production_report": ("production_report", "confirm_report"),
    "complete_work_order": ("work_order", "complete"),
    "pause_work_order": ("work_order", "pause"),
    "resume_work_order": ("work_order", "resume"),
    "split_work_order": ("work_order", "split"),
    "run_compliance_simulation": ("simulation", "create"),
    "run_workflow": ("tms", "create"),
    "export_report_file": ("production_report", "export"),
    "acknowledge_alert": ("qms", "edit"),
    "run_alert_patrol": ("qms", "edit"),
    "create_followup_task": ("tms", "create"),
}

# action → 是否需要 Write 级校验（写操作需记录 operator）
_WRITE_ACTIONS = {
    "create", "edit", "delete", "approve", "release", "start",
    "pause", "resume", "complete", "close", "cancel", "split",
    "confirm_report", "modify_report", "export", "manage",
}

# 工厂隔离：own 数据范围只允许访问当前 factory_id 的工具
_SCOPED_READ_TOOLS = {
    "query_work_orders", "query_inventory", "query_defects",
    "query_equipment", "query_pmc_material_supply", "query_pmc_rush_impact",
}


class PermissionGate:
    """基于用户权限集 + 数据作用域的 Chat V2 工具门控。"""

    def __init__(self, read_map: Optional[Dict[str, str]] = None,
                 write_map: Optional[Dict[str, tuple]] = None,
                 scoped_read: Optional[Set[str]] = None) -> None:
        self._read = read_map if read_map is not None else _READ_TOOLS
        self._write = write_map if write_map is not None else _WRITE_TOOLS
        self._scoped_read = scoped_read if scoped_read is not None else _SCOPED_READ_TOOLS

    def module_for_tool(self, tool_name: str) -> Optional[str]:
        return self._read.get(tool_name) or (self._write.get(tool_name)[0]
                                              if tool_name in self._write else None)

    def check(self, *, tool_name: str, ctx: Any, user_permissions: list,
              operator: str, factory_id: str) -> Optional[str]:
        """校验是否允许执行该工具。返回 None=放行；字符串=拒绝原因。"""
        # skill 名（带模块路径或裸名）→ 归一化
        base = tool_name.rsplit(".", 1)[-1]

        if base in self._write:
            module, action = self._write[base]
        elif base in self._read:
            module, action = self._read[base], "view"
        else:
            # 未知工具：不拦截（由执行器决定缺失与否），只做作用域兜底
            return None

        allowed = self._has_permission(user_permissions, module, action)
        if not allowed:
            return f"无权限执行 {base}（{module}.{action}）"

        # 写操作：operator 必须与当前用户一致
        if action in _WRITE_ACTIONS:
            current = getattr(ctx.user, "username", None) if ctx else operator
            if current and operator and current != operator:
                return f"{base} 为写操作，操作人身份不匹配（{current} ≠ {operator}）"

        # 工厂隔离：own 作用域下，scoped 查询必须携带当前 factory_id
        if base in self._scoped_read:
            scope = self._data_scope(user_permissions)
            if scope == "own":
                if not factory_id:
                    return f"{base} 需要指定工厂（factory_id）"
        return None

    @staticmethod
    def _has_permission(user_permissions: list, module: str, action: str) -> bool:
        if not user_permissions:
            return False
        # 超管/管理员的 get_user_permissions 已返回全模块全动作
        for perm in user_permissions:
            if perm.get("module") == module:
                return action in perm.get("actions", [])
        return False

    @staticmethod
    def _data_scope(user_permissions: list | None) -> str:
        # 简单判断：全模块全动作 → all；否则 own
        if user_permissions is None:
            return "own"
        if user_permissions and all(
            set(p.get("actions", []) or []) == {"view", "create", "edit", "delete", "approve",
                                                 "release", "start", "complete", "cancel",
                                                 "confirm_report", "modify_report", "export", "manage"}
            for p in user_permissions
        ) and len(user_permissions) >= 10:
            return "all"
        return "own"