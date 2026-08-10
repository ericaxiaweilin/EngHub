"""将 TMS 审批流程引擎定义转换为可渲染的节点/连线图。

这个模块只负责序列化引擎已经保存的定义，不包含任何业务流程模板。
因此流程增加、删减或调整审批条件时，图会随引擎数据变化，不需要再改 chatbot。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def _value(step: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = step.get(key)
        if value is not None and value != "":
            return value
    return None


def build_flow_diagram(
    *,
    flow_id: str,
    flow_code: str,
    flow_type: str,
    status: str,
    current_step: int,
    steps: Iterable[Dict[str, Any]],
    records: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """从流程引擎的 steps/records 生成详细流程图数据。

    图的主链保持执行引擎的顺序；每个审批节点额外暴露审批人、会签/或签、
    条件、自动通过和 Agent 权限。拒绝、委托、升级等实际支持的动作也作为
    连线输出，交给前端渲染为异常/回流分支。
    """
    raw_steps = [step for step in steps if isinstance(step, dict)]
    raw_records = [record for record in (records or []) if isinstance(record, dict)]

    nodes: List[Dict[str, Any]] = [
        {
            "id": "start",
            "kind": "start",
            "label": "Start",
            "title": "开始",
            "status": "completed" if raw_steps else "pending",
        }
    ]

    for index, step in enumerate(raw_steps):
        step_index = int(step.get("step_index", index))
        step_records = [record for record in raw_records if record.get("step_index") == step_index]
        actions = [record.get("action") for record in step_records if record.get("action")]
        if status in {"rejected", "cancelled"} and actions:
            node_status = "rejected" if "reject" in actions else "completed"
        elif step_index < current_step:
            node_status = "completed"
        elif step_index == current_step and status == "active":
            node_status = "current"
        else:
            node_status = "pending"

        details = {
            key: step[key]
            for key in (
                "step_index", "step_name", "approver_role", "approver_id", "approver_ids",
                "approval_type", "condition", "auto_approve_if", "allow_agent",
                "requires_signature", "approver_type",
                "inputs", "input_requirements", "judgement_criteria", "criteria",
                "outputs", "deliverables", "next_focus", "blockers", "exception_paths",
                "work_matrix", "matrix_fields", "actions", "action",
            )
            if key in step and step[key] is not None
        }
        nodes.append({
            "id": f"step_{index}",
            "kind": "approval",
            "step_index": step_index,
            "label": _value(step, "step_name", "name") or f"Step {index + 1}",
            "title": _value(step, "step_name", "name") or f"第 {index + 1} 步审批",
            "status": node_status,
            "role": _value(step, "approver_role", "role"),
            "approver_id": step.get("approver_id"),
            "approval_type": step.get("approval_type", "or"),
            "condition": step.get("condition"),
            "auto_approve_if": step.get("auto_approve_if"),
            "allow_agent": bool(step.get("allow_agent", False)),
            "inputs": step.get("inputs", step.get("input_requirements", [])),
            "judgement_criteria": step.get("judgement_criteria", step.get("criteria", [])),
            "outputs": step.get("outputs", []),
            "deliverables": step.get("deliverables", []),
            "next_focus": step.get("next_focus", []),
            "blockers": step.get("blockers", []),
            "exception_paths": step.get("exception_paths", []),
            "work_matrix": step.get("work_matrix"),
            "matrix_fields": step.get("matrix_fields", []),
            "details": details,
            "history": step_records,
        })

    nodes.extend([
        {
            "id": "end",
            "kind": "end",
            "label": "End",
            "title": "通过结束",
            "status": "completed" if status == "approved" else "pending",
        },
        {
            "id": "rejected",
            "kind": "terminal",
            "label": "Rejected",
            "title": "驳回结束",
            "status": "completed" if status == "rejected" else "inactive",
        },
    ])

    edges: List[Dict[str, Any]] = []
    if raw_steps:
        edges.append({
            "id": "edge_start",
            "source": "start",
            "target": "step_0",
            "label": "流程启动",
            "type": "normal",
        })
    else:
        edges.append({
            "id": "edge_empty_flow",
            "source": "start",
            "target": "end",
            "label": "无审批步骤",
            "type": "normal",
        })
    for index in range(len(raw_steps)):
        source = f"step_{index}"
        target = "end" if index == len(raw_steps) - 1 else f"step_{index + 1}"
        edges.append({
            "id": f"edge_approve_{index}",
            "source": source,
            "target": target,
            "label": "approval_action == 'approve'",
            "condition": {"approval_action": "approve"},
            "type": "normal",
        })
        edges.append({
            "id": f"edge_reject_{index}",
            "source": source,
            "target": "rejected",
            "label": "approval_action == 'reject'",
            "condition": {"approval_action": "reject"},
            "type": "exception",
        })
        edges.append({
            "id": f"edge_delegate_{index}",
            "source": source,
            "target": source,
            "label": "approval_action == 'delegate'",
            "condition": {"approval_action": "delegate"},
            "type": "loop",
        })
        if index < len(raw_steps) - 1:
            edges.append({
                "id": f"edge_escalate_{index}",
                "source": source,
                "target": target,
                "label": "approval_action == 'escalate'",
                "condition": {"approval_action": "escalate"},
                "type": "escalation",
            })

    return {
        "type": "flow_diagram",
        "version": "engine-v1",
        "source": "tms_approval_engine",
        "flow_id": flow_id,
        "flow_code": flow_code,
        "title": flow_code or "流程引擎流程图",
        "flow_type": flow_type,
        "status": status,
        "current_step": current_step,
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "approval_node_count": len(raw_steps),
            "record_count": len(raw_records),
            "layout": "left-to-right-with-branches",
        },
        "legend": [
            {"key": "normal", "label": "正常通过", "color": "#1677ff"},
            {"key": "exception", "label": "驳回/异常", "color": "#f5222d"},
            {"key": "loop", "label": "委托回流", "color": "#fa8c16"},
            {"key": "escalation", "label": "升级流转", "color": "#722ed1"},
        ],
        "engine_note": "节点、连线与条件均来自 TMSApprovalFlow 的流程定义及其执行动作；chatbot 不补写业务节点。",
    }


__all__ = ["build_flow_diagram"]
