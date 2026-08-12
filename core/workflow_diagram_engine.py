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


def _unique_strings(*values: Any) -> List[str]:
    """Flatten configured labels while keeping diagram-level lists readable."""
    result: List[str] = []
    seen = set()

    def visit(value: Any) -> None:
        if value is None or value == "":
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                visit(item)
            return
        if isinstance(value, dict):
            for key in ("name", "label", "title", "role", "owner"):
                if value.get(key):
                    visit(value[key])
                    return
            return
        text = str(value).strip()
        if not text:
            return
        marker = text.casefold()
        if marker not in seen:
            seen.add(marker)
            result.append(text)

    for value in values:
        visit(value)
    return result


def _party_names(*values: Any) -> List[str]:
    """Normalize owner/stakeholder strings such as 'PMC/采购/RD' into parties."""
    raw = _unique_strings(*values)
    parties: List[str] = []
    for value in raw:
        parts = value.replace("→", "/").replace("、", "/").replace("，", "/").split("/")
        parties.extend(part.strip() for part in parts if part.strip())
    return _unique_strings(parties)


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
    fallback_paths: List[Dict[str, Any]] = []
    fallbacks_by_step: List[List[Dict[str, Any]]] = []

    for index, step in enumerate(raw_steps):
        action = _step_value(step, "action", "detail", "description", default="")
        node_role = _step_value(step, "owner", "role", default=role)
        node_status = "completed" if index < current_step else "current" if index == current_step else "pending"
        criteria = _list(_step_value(step, "judgement_criteria", "criteria", "decision_gate"))
        node_kind = _step_value(step, "kind", default="decision" if criteria else "task")
        exception_paths = _list(step.get("exception_paths"))
        related_parties = _party_names(
            node_role,
            step.get("related_parties"),
            step.get("stakeholders"),
            step.get("consulted"),
            step.get("informed"),
        )
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
            "fallbacks": exception_paths,
            "work_matrix": step.get("work_matrix"),
            "matrix_fields": _list(step.get("matrix_fields")),
            "systems": _list(_step_value(step, "systems", "related_tools")),
            "related_parties": related_parties,
            "details": {
                "step": _step_value(step, "step", default=index + 1),
                "owner": node_role,
                "action": action,
                "pass_condition": step.get("pass_condition"),
                "sla": step.get("sla"),
                "systems": _list(_step_value(step, "systems", "related_tools")),
                "related_parties": related_parties,
            },
        }
        configured_branches = _list(step.get("exception_paths"))
        if not configured_branches:
            configured_branches = [{
                "condition": "输入缺失或本步判断不通过",
                "action": "补齐输入/责任人/恢复时间后回到本步骤重判",
                "owner": node_role or role or "流程负责人",
                "inputs": ["缺失字段、异常证据或责任人"],
                "outputs": ["补齐后的证据", "恢复时间/升级结论"],
                "deliverables": ["补证据记录或升级记录"],
                "return_to": "current",
                "resume_condition": "输入齐全且放行门槛通过",
                "type": "fallback",
                "generated": True,
            }]
        node["fallbacks"] = configured_branches
        fallbacks_by_step.append(configured_branches)
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
            "path": "normal",
        })
    else:
        edges.append({"id": "edge_empty", "source": "start", "target": "end", "label": "无步骤", "type": "normal", "path": "normal"})

    for index, step in enumerate(raw_steps):
        source_id = f"step_{index}"
        normal_target = "end" if index == len(raw_steps) - 1 else f"step_{index + 1}"
        normal_edge = {
            "id": f"edge_pass_{index}",
            "source": source_id,
            "target": normal_target,
            "label": step.get("pass_condition") or "本步交付物齐备",
            "condition": _list(_step_value(step, "judgement_criteria", "criteria", "decision_gate")),
            "type": "normal",
            "path": "normal",
        }
        edges.append(normal_edge)

        for branch_index, raw_branch in enumerate(fallbacks_by_step[index]):
            branch = raw_branch if isinstance(raw_branch, dict) else {"action": str(raw_branch)}
            exception_id = f"exception_{index}_{branch_index}"
            branch_action = _step_value(branch, "action", "title", "label", default="异常处理")
            branch_condition = _step_value(branch, "condition", "when", default="本步判断不通过")
            branch_owner = _step_value(branch, "owner", "role", default=node_role or role)
            branch_parties = _party_names(
                branch_owner,
                branch.get("related_parties"),
                branch.get("stakeholders"),
                branch.get("consulted"),
                branch.get("informed"),
            )
            branch_type = branch.get("type") or "fallback"
            nodes.append({
                "id": exception_id,
                "kind": "fallback",
                "label": branch_action,
                "title": branch_action,
                "status": "pending",
                "role": branch_owner,
                "summary": branch.get("description") or branch_action,
                "action": branch_action,
                "inputs": _list(branch.get("inputs")),
                "judgement_criteria": _list(branch_condition),
                "outputs": _list(branch.get("outputs")),
                "deliverables": _list(branch.get("deliverables")),
                "next_focus": _list(branch.get("next_focus")),
                "blockers": _list(branch.get("blockers")),
                "systems": _list(_step_value(branch, "systems", "related_tools")),
                "related_parties": branch_parties,
                "fallback_of": source_id,
                "resume_condition": branch.get("resume_condition") or "补齐证据后返回",
                "generated": bool(branch.get("generated")),
                "details": {
                    "owner": branch_owner,
                    "action": branch_action,
                    "resume_condition": branch.get("resume_condition") or "补齐证据后返回",
                    "related_parties": branch_parties,
                },
            })
            fallback_edge = {
                "id": f"edge_exception_{index}_{branch_index}",
                "source": source_id,
                "target": exception_id,
                "label": str(branch_condition),
                "condition": branch_condition,
                "type": branch_type,
                "path": "fallback",
            }
            edges.append(fallback_edge)
            recovery_target = _target_id(
                branch.get("return_to"),
                current=source_id,
                normal_target=normal_target,
                step_count=len(raw_steps),
            )
            if recovery_target:
                recovery_edge = {
                    "id": f"edge_recovery_{index}_{branch_index}",
                    "source": exception_id,
                    "target": recovery_target,
                    "label": branch.get("resume_condition") or "补齐证据后返回",
                    "type": "recovery",
                    "path": "fallback",
                }
                edges.append(recovery_edge)
            fallback_paths.append({
                "id": exception_id,
                "from_step": source_id,
                "condition": branch_condition,
                "action": branch_action,
                "owner": branch_owner,
                "related_parties": branch_parties,
                "inputs": _list(branch.get("inputs")),
                "outputs": _list(branch.get("outputs")),
                "deliverables": _list(branch.get("deliverables")),
                "return_to": recovery_target,
                "resume_condition": branch.get("resume_condition") or "补齐证据后返回",
                "type": branch_type,
                "generated": bool(branch.get("generated")),
            })

    counts: Dict[str, int] = {}
    for node in nodes:
        counts[node["kind"]] = counts.get(node["kind"], 0) + 1

    normal_path = [edge for edge in edges if edge.get("path") == "normal"]
    input_artifacts = _unique_strings(*(node.get("inputs") for node in nodes if node.get("kind") not in {"start", "end", "fallback"}))
    output_artifacts = _unique_strings(
        *(node.get("outputs") for node in nodes if node.get("kind") not in {"start", "end", "fallback"}),
        *(node.get("deliverables") for node in nodes if node.get("kind") not in {"start", "end", "fallback"}),
    )
    related_parties = _party_names(
        *(node.get("related_parties") for node in nodes if node.get("kind") not in {"start", "end"}),
        (metadata or {}).get("related_parties"),
    )
    systems = _unique_strings(
        *(node.get("systems") for node in nodes if node.get("kind") not in {"start", "end"}),
        (metadata or {}).get("related_tools"),
    )

    # The workflow engine owns the graph layout.  The UI only renders these
    # coordinates, so normal, fallback and recovery paths remain one connected
    # diagram instead of independent cards arranged by the chatbot.
    canvas_width = 1180
    # Keep the three lanes visually balanced.  The previous 190px main cards
    # left a large empty lower half and made a six-step workflow unnecessarily
    # tall, which in turn forced the UI to render it at an unreadable scale.
    main_width = 360
    main_height = 154
    side_width = 320
    fallback_height = 116
    main_x = (canvas_width - main_width) // 2
    left_x = 30
    right_x = canvas_width - side_width - 30
    node_by_id = {node["id"]: node for node in nodes}
    node_by_id["start"]["layout"] = {
        "x": (canvas_width - 210) // 2,
        "y": 28,
        "width": 210,
        "height": 56,
        "lane": "normal",
        "rank": -1,
    }

    cursor_y = 128
    for index, step_fallbacks in enumerate(fallbacks_by_step):
        pair_rows = max(1, (len(step_fallbacks) + 1) // 2)
        row_height = max(main_height + 62, pair_rows * (fallback_height + 16) + 42)
        step_id = f"step_{index}"
        node_by_id[step_id]["layout"] = {
            "x": main_x,
            "y": cursor_y,
            "width": main_width,
            "height": main_height,
            "lane": "normal",
            "rank": index,
        }
        for branch_index in range(len(step_fallbacks)):
            fallback_id = f"exception_{index}_{branch_index}"
            if fallback_id not in node_by_id:
                continue
            is_left = branch_index % 2 == 0
            node_by_id[fallback_id]["layout"] = {
                "x": left_x if is_left else right_x,
                "y": cursor_y + 8 + (branch_index // 2) * (fallback_height + 16),
                "width": side_width,
                "height": fallback_height,
                "lane": "fallback-left" if is_left else "fallback-right",
                "rank": index,
            }
        cursor_y += row_height

    node_by_id["end"]["layout"] = {
        "x": (canvas_width - 210) // 2,
        "y": cursor_y,
        "width": 210,
        "height": 56,
        "lane": "normal",
        "rank": len(raw_steps),
    }
    canvas = {
        "width": canvas_width,
        "height": cursor_y + 94,
        "direction": "top-to-bottom",
        "lanes": [
            {"key": "fallback-left", "label": "不通过 / Fallback", "x": left_x, "width": side_width},
            {"key": "normal", "label": "正常主流程", "x": main_x, "width": main_width},
            {"key": "fallback-right", "label": "不通过 / Fallback", "x": right_x, "width": side_width},
        ],
    }
    for edge in edges:
        edge["routing"] = (
            "vertical-main"
            if edge.get("path") == "normal"
            else "return-to-gate"
            if edge.get("type") == "recovery"
            else "branch-from-gate"
        )

    return {
        "type": "flow_diagram",
        "version": "business-engine-v3",
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
        "normal_path": normal_path,
        "fallback_paths": fallback_paths,
        "canvas": canvas,
        "inputs": input_artifacts,
        "outputs": output_artifacts,
        "related_parties": related_parties,
        "systems": systems,
        "meta": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "step_count": len(raw_steps),
            "approval_node_count": 0,
            "interactive": True,
            "layout": "single-canvas-connected-flow-v1",
            "node_type_counts": counts,
            "input_count": len(input_artifacts),
            "output_count": len(output_artifacts),
            "related_party_count": len(related_parties),
            "fallback_count": len(fallback_paths),
            **(metadata or {}),
        },
        "legend": [
            {"key": "normal", "label": "正常流转", "color": "#1677ff"},
            {"key": "current", "label": "当前/选中步骤", "color": "#13c2c2"},
            {"key": "fallback", "label": "Fallback / 异常分支", "color": "#f5222d"},
            {"key": "recovery", "label": "补证据后回流", "color": "#fa8c16"},
        ],
        "engine_note": "节点来自业务工作流注册表；流程引擎统一输出正常主线、Fallback回流、输入物、判断标准、输出物、交付物、关联方和系统留痕，chatbot 不拼接业务节点。",
    }


__all__ = ["build_business_flow_diagram"]
