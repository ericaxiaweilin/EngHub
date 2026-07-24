"""
Agent 工作流编排服务（确定性流程模板）

把 chat_tools_service 的单步工具串成可复用的多步流程：
- WORKFLOW_DEFINITIONS：name → { label, description, trigger_keywords, steps[] }
- step = { tool, args }，args 支持占位符：
    * {user.xxx}      引用用户参数（run_workflow 的 params）
    * {steps.N.field} 引用第 N 步结果的字段（支持多级点路径）
- run_workflow：顺序执行 steps，任一步 error 即中止，返回已完成步骤 + 失败原因。

设计原则（延续「确定性业务底座」）：
- 流程为静态模板，步骤与参数解析完全确定，不依赖模型自由编排，可控可复现。
- 写链路全程透传 operator，角色门槛/职责分离由底层服务层强制执行，工作流不绕过审核。
- 查询步骤按 factory_id 隔离（多工厂不串号）。

循环导入规避：本模块顶层导入 chat_tools_service 的 execute_tool / TOOL_LABELS；
chat_tools_service 的 run_workflow 执行器与 resolve_intent 则在函数内懒加载本模块。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from api.services.chat_tools_service import execute_tool, TOOL_LABELS


# ==================== 工作流定义（静态模板） ====================

WORKFLOW_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "daily_production_review": {
        "label": "生产日度复盘",
        "description": "一键复盘今日生产：生产统计汇总 → 在制工单 → 不良品记录，最后综合分析。",
        "trigger_keywords": [
            "复盘", "日度总结", "日度复盘", "生产复盘", "今天复盘", "复盘今天",
        ],
        "steps": [
            {"tool": "get_production_summary", "args": {}},
            {"tool": "query_work_orders", "args": {"status": "in_progress"}},
            {"tool": "query_defects", "args": {}},
        ],
    },
    "create_and_release": {
        "label": "一键建单下达",
        "description": "创建生产工单并下达（写链路，全程走角色门槛与职责分离）。"
                       "需要参数：product_id 产品、planned_qty 数量、planned_due 计划完成日期。",
        "trigger_keywords": [
            "建单并下达", "一键建单", "创建并下达", "建单下达", "建工单并下达",
        ],
        "steps": [
            {
                "tool": "create_work_order",
                "args": {
                    "product_id": "{user.product_id}",
                    "planned_qty": "{user.planned_qty}",
                    "planned_due": "{user.planned_due}",
                },
            },
            {"tool": "release_work_order", "args": {"work_order_code": "{steps.0.work_order_code}"}},
        ],
    },
    "quality_alert_triage": {
        "label": "质量异常分诊",
        "description": "质量异常快速分诊：先查严重(critical)不良品，再查在制工单，评估影响范围并给处置建议。",
        "trigger_keywords": [
            "质量分诊", "异常分诊", "质量警报", "质量异常分诊", "分诊",
        ],
        "steps": [
            {"tool": "query_defects", "args": {"severity": "critical"}},
            {"tool": "query_work_orders", "args": {"status": "in_progress"}},
        ],
    },
    "full_compliance_check": {
        "label": "全面合规检查",
        "description": "全面人机工程/劳动合规检查：运行一次合规仿真，并回看最近的仿真审计记录。",
        "trigger_keywords": [
            "全面合规", "合规检查", "合规自查", "全面合规检查",
        ],
        "steps": [
            {"tool": "run_compliance_simulation", "args": {}},
            {"tool": "query_simulation_audits", "args": {"limit": 5}},
        ],
    },
}


# ==================== 占位符解析 ====================

def _lookup(obj: Any, parts: List[str]) -> Any:
    """按点路径逐级取嵌套值，取不到返回 None。"""
    cur = obj
    for part in parts:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _resolve_value(value: Any, user_params: Dict[str, Any], step_results: List[Dict[str, Any]]) -> Any:
    """解析单个占位符值。

    - "{user.xxx}"       → user_params["xxx"]
    - "{steps.N}"        → 第 N 步的完整结果
    - "{steps.N.a.b}"    → 第 N 步结果的 a.b 字段
    - 其余字符串/非字符串原样返回。
    解析不到时返回 None（由调用方剔除该参数键）。
    """
    if not isinstance(value, str):
        return value
    s = value.strip()
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        if inner.startswith("user."):
            return user_params.get(inner[len("user."):])
        if inner.startswith("steps."):
            rest = inner[len("steps."):]
            parts = rest.split(".", 1)
            try:
                idx = int(parts[0])
            except (ValueError, IndexError):
                return None
            if idx < 0 or idx >= len(step_results):
                return None
            if len(parts) == 1:
                return step_results[idx]
            return _lookup(step_results[idx], parts[1].split("."))
        return None
    return value


def _resolve_args(
    args_template: Optional[Dict[str, Any]],
    user_params: Dict[str, Any],
    step_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """解析一步的参数模板，剔除解析为 None 的键（避免把空值传给工具）。"""
    resolved: Dict[str, Any] = {}
    for key, val in (args_template or {}).items():
        rv = _resolve_value(val, user_params, step_results)
        if rv is not None:
            resolved[key] = rv
    return resolved


def _workflow_needs_user_params(wf: Dict[str, Any]) -> bool:
    """判断工作流是否需要用户提供参数（任一步 args 引用了 {user.} 占位符）。"""
    for step in wf.get("steps", []):
        for val in (step.get("args") or {}).values():
            if isinstance(val, str) and "{user." in val:
                return True
    return False


# ==================== 工作流匹配 / 清单 ====================

def match_workflow(message: str) -> Optional[str]:
    """确定性工作流触发：命中触发词返回工作流名，否则 None。

    仅对「无需用户参数」的工作流做确定性路由（如生产复盘/质量分诊/合规检查）；
    需要参数的写链路工作流（如一键建单下达）交给模型 auto 循环提取参数后调用。"""
    if not message:
        return None
    for name, wf in WORKFLOW_DEFINITIONS.items():
        if _workflow_needs_user_params(wf):
            continue
        if any(kw in message for kw in wf.get("trigger_keywords", [])):
            return name
    return None


def list_workflows() -> List[Dict[str, Any]]:
    """返回工作流清单（供 /chat/tools 展示与前端快捷指令）。"""
    return [
        {
            "name": name,
            "label": wf["label"],
            "description": wf["description"],
            "trigger_keywords": wf.get("trigger_keywords", []),
            "step_count": len(wf.get("steps", [])),
            "needs_params": _workflow_needs_user_params(wf),
        }
        for name, wf in WORKFLOW_DEFINITIONS.items()
    ]


# ==================== 工作流执行 ====================

async def run_workflow(
    db: AsyncSession,
    name: str,
    user_params: Optional[Dict[str, Any]] = None,
    operator: str = "ai_assistant",
    factory_id: Optional[str] = None,
) -> Dict[str, Any]:
    """顺序执行工作流的各个步骤。

    任一步返回 error 即中止，返回已完成步骤与失败原因；
    全部成功则返回每步结果。写链路全程透传 operator（角色门槛由服务层强制执行），
    查询步骤按 factory_id 隔离。"""
    wf = WORKFLOW_DEFINITIONS.get(name)
    if not wf:
        return {
            "error": f"未知工作流：{name}",
            "available_workflows": [
                {"name": n, "label": w["label"]} for n, w in WORKFLOW_DEFINITIONS.items()
            ],
        }

    user_params = user_params or {}
    steps = wf.get("steps", [])
    step_results: List[Dict[str, Any]] = []
    steps_out: List[Dict[str, Any]] = []

    for i, step in enumerate(steps):
        tool = step["tool"]
        args = _resolve_args(step.get("args"), user_params, step_results)
        result = await execute_tool(db, tool, args, operator=operator, factory_id=factory_id)
        success = "error" not in result
        steps_out.append({
            "step": i,
            "tool": tool,
            "label": TOOL_LABELS.get(tool, tool),
            "arguments": args,
            "result": result,
            "success": success,
        })
        step_results.append(result)
        if not success:
            return {
                "workflow": name,
                "label": wf["label"],
                "success": False,
                "error": result.get("error"),
                "failed_step": i,
                "failed_step_label": TOOL_LABELS.get(tool, tool),
                "steps": steps_out,
                "completed_steps": i,
                "total_steps": len(steps),
                "summary": f"{wf['label']}：执行到第 {i + 1}/{len(steps)} 步「{TOOL_LABELS.get(tool, tool)}」时失败：{result.get('error')}",
            }

    return {
        "workflow": name,
        "label": wf["label"],
        "success": True,
        "steps": steps_out,
        "completed_steps": len(steps_out),
        "total_steps": len(steps),
        "summary": f"{wf['label']}：{len(steps_out)}/{len(steps)} 步全部完成",
    }


__all__ = ["WORKFLOW_DEFINITIONS", "run_workflow", "match_workflow", "list_workflows"]
