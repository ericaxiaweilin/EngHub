"""通用业务工作流图序列化引擎。

引擎只消费结构化工作流定义，不保存 PMC、品质或设备等职位专属文案。
业务知识可以来自数据库、配置接口或职位 SOP；chatbot 只负责选择定义并把
统一的 nodes/edges 契约交给前端渲染。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def _list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def _step_value(step: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if step.get(key) is not None and step.get(key) != "":
            return step[key]
    return default


def _target_id(value: Any, *, current: str, normal_target: str, step_count: int) -> Optional[str]:
    if value in (None, "", "none"):
        return None
    if value in ("current", "retry", "return"):
        return current
    if value in ("next", "continue"):
        return normal_target
    if value in ("end", "stop"):
        return "end"
    try:
        index = int(value)
    except (TypeError, ValueError):
        return str(value) if str(value).startswith("step_") else None
    return f"step_{index}" if 0 <= index < step_count else None


def build_business_flow_diagram(
    *,
    workflow_key: str,
    title: str,
    steps: Iterable[Dict[str, Any]],
    role: Optional[str] = None,
    description: str = "",
    current_step: int = 0,
    source: str = "business_workflow_registry",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把任意业务工作流定义转换成统一、可交互的图数据契约。"""
    raw_steps = [step for step in steps if isinstance(step, dict)]
    current_step = max(0, min(current_step, max(len(raw_steps) - 1, 0)))

    nodes: List[Dict[str, Any]] = [{
        "id": "start",
        "kind": "start",
        "label": "Start",
        "title": "开始",
        "status": "completed" if raw_steps else "current",
        "summary": description,
    }]
    edges: List[Dict[str, Any]] = []

    for index, step in enumerate(raw_steps):
        action = _step_value(step, "action", "detail", "description", default="")
        node_role = _step_value(step, "owner", "role", default=role)
        node_status = "completed" if index < current_step else "current" if index == current_step else "pending"
        criteria = _list(_step_value(step, "judgement_criteria", "criteria", "decision_gate"))
        node_kind = _step_value(step, "kind", default="decision" if criteria else "task")
        exception_paths = _list(step.get("exception_paths"))
        node = {
            "id": f"step_{index}",
            "kind": node_kind,
            "step_index": index,
            "label": _step_value(step, "task", "name", "title", default=f"步骤 {index + 1}"),
            "title": _step_value(step, "task", "name", "title", default=f"步骤 {index + 1}"),
            "status": node_status,
            "role": node_role,
            "summary": action,
            "action": action,
            "inputs": _list(_step_value(step, "inputs", "input_requirements")),
            "judgement_criteria": criteria,
            "outputs": _list(step.get("outputs")),
            "deliverables": _list(step.get("deliverables")),
            "next_focus": _list(step.get("next_focus")),
            "blockers": _list(step.get("blockers")),
            "exception_paths": exception_paths,
            "work_matrix": step.get("work_matrix"),
            "matrix_fields": _list(step.get("matrix_fields")),
            "systems": _list(_step_value(step, "systems", "related_tools")),
            "details": {
                "step": _step_value(step, "step", default=index + 1),
                "owner": node_role,
                "action": action,
                "pass_condition": step.get("pass_condition"),
                "sla": step.get("sla"),
                "systems": _list(_step_value(step, "systems", "related_tools")),
            },
        }
        nodes.append(node)

    nodes.append({
        "id": "end",
        "kind": "end",
        "label": "End",
        "title": "流程闭环",
        "status": "pending",
        "summary": "所有节点交付物齐备后结束。",
    })

    if raw_steps:
        edges.append({
            "id": "edge_start",
            "source": "start",
            "target": "step_0",
            "label": "触发业务需求",
            "type": "normal",
        })
    else:
        edges.append({"id": "edge_empty", "source": "start", "target": "end", "label": "无步骤", "type": "normal"})

    for index, step in enumerate(raw_steps):
        source_id = f"step_{index}"
        normal_target = "end" if index == len(raw_steps) - 1 else f"step_{index + 1}"
        edges.append({
            "id": f"edge_pass_{index}",
            "source": source_id,
            "target": normal_target,
            "label": step.get("pass_condition") or "本步交付物齐备",
            "condition": _list(_step_value(step, "judgement_criteria", "criteria", "decision_gate")),
            "type": "normal",
        })

        for branch_index, raw_branch in enumerate(_list(step.get("exception_paths"))):
            branch = raw_branch if isinstance(raw_branch, dict) else {"action": str(raw_branch)}
            exception_id = f"exception_{index}_{branch_index}"
            branch_action = _step_value(branch, "action", "title", "label", default="异常处理")
            branch_condition = _step_value(branch, "condition", "when", default="本步判断不通过")
            nodes.append({
                "id": exception_id,
                "kind": "exception",
                "label": branch_action,
                "title": branch_action,
                "status": "pending",
                "role": _step_value(branch, "owner", "role", default=role),
                "summary": branch.get("description") or branch_action,
                "action": branch_action,
                "inputs": _list(branch.get("inputs")),
                "judgement_criteria": _list(branch_condition),
                "outputs": _list(branch.get("outputs")),
                "deliverables": _list(branch.get("deliverables")),
                "next_focus": _list(branch.get("next_focus")),
                "blockers": _list(branch.get("blockers")),
                "details": {"owner": _step_value(branch, "owner", "role", default=role), "action": branch_action},
            })
            edges.append({
                "id": f"edge_exception_{index}_{branch_index}",
                "source": source_id,
                "target": exception_id,
                "label": str(branch_condition),
                "condition": branch_condition,
                "type": branch.get("type") or "exception",
            })
            recovery_target = _target_id(
                branch.get("return_to"),
                current=source_id,
                normal_target=normal_target,
                step_count=len(raw_steps),
            )
            if recovery_target:
                edges.append({
                    "id": f"edge_recovery_{index}_{branch_index}",
                    "source": exception_id,
                    "target": recovery_target,
                    "label": branch.get("resume_condition") or "补齐证据后返回",
                    "type": "recovery",
                })

    counts: Dict[str, int] = {}
    for node in nodes:
        counts[node["kind"]] = counts.get(node["kind"], 0) + 1

    return {
        "type": "flow_diagram",
        "version": "business-engine-v2",
        "source": source,
        "workflow_key": workflow_key,
        "flow_code": workflow_key,
        "title": title,
        "description": description,
        "flow_type": "business_workflow",
        "status": "reference",
        "current_step": current_step,
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "step_count": len(raw_steps),
            "approval_node_count": 0,
            "interactive": True,
            "layout": "left-to-right-with-exception-branches",
            "node_type_counts": counts,
            **(metadata or {}),
        },
        "legend": [
            {"key": "normal", "label": "正常流转", "color": "#1677ff"},
            {"key": "current", "label": "当前/选中步骤", "color": "#13c2c2"},
            {"key": "exception", "label": "异常分支", "color": "#f5222d"},
            {"key": "recovery", "label": "补证据后回流", "color": "#fa8c16"},
        ],
        "engine_note": "节点来自业务工作流注册表；流程引擎统一输出输入、判断标准、输出、交付物、异常分支和下一步提示，chatbot 不拼接业务节点。",
    }


__all__ = ["build_business_flow_diagram"]
