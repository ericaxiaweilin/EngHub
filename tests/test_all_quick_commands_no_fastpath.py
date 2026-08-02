"""全部快捷命令 / 工作流标签禁止 fastpath：不得 keyword → 强制工具。"""

from api.services.chat_tools_service import (
    INTENT_RULES,
    detect_intent_tool,
    resolve_intent,
)
from api.services.workflow_service import WORKFLOW_DEFINITIONS, list_workflows


# 与前端 FALLBACK_QUICK_COMMANDS / 058 预置命令对齐
PRESET_QUICK_COMMANDS = [
    "今天生产情况怎么样？",
    "查询在制工单",
    "查询库存水平",
    "最近有哪些不良品？",
    "设备运行状态如何？",
    "跑一次高温加班合规仿真",
    "最近的仿真审计记录",
]


def test_intent_rules_emptied_no_keyword_fastpath():
    assert INTENT_RULES == []


def test_all_preset_quick_commands_have_no_resolve_intent_fastpath():
    for cmd in PRESET_QUICK_COMMANDS:
        assert resolve_intent(cmd) is None, f"快捷命令仍被 fastpath: {cmd}"
        assert detect_intent_tool(cmd) is None, f"detect_intent 仍命中: {cmd}"


def test_all_workflow_labels_have_no_resolve_intent_fastpath():
    for wf in list_workflows():
        label = wf["label"]
        assert resolve_intent(label) is None, f"工作流标签仍被 fastpath: {label}"
        assert detect_intent_tool(label) is None, f"detect_intent 仍命中: {label}"
        for kw in WORKFLOW_DEFINITIONS[wf["name"]].get("trigger_keywords", []):
            assert resolve_intent(kw) is None, f"工作流触发词仍被 fastpath: {kw}"


def test_chat_routes_do_not_import_resolve_intent_for_fastpath():
    """chat_routes 不得再 import/调用 resolve_intent（防回归）。"""
    from pathlib import Path
    import ast

    src = Path("api/routes/chat_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in (node.names or [])}
            assert "resolve_intent" not in names
            assert "detect_intent_tool" not in names
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"resolve_intent", "detect_intent_tool", "_run_deterministic"}
