"""质量异常分诊工作流：完整多步编排，禁止 fastpath 捷径。"""

from api.services.workflow_service import WORKFLOW_DEFINITIONS, match_workflow


def test_quality_alert_triage_has_full_four_step_pipeline():
    wf = WORKFLOW_DEFINITIONS["quality_alert_triage"]
    tools = [step["tool"] for step in wf["steps"]]
    assert tools == [
        "query_defects",
        "query_ocap_tasks",
        "query_work_orders",
        "get_pending_alerts",
    ]
    assert wf["steps"][0]["args"]["severity"] == "critical"


def test_quality_alert_triage_does_not_match_bare_triage_keyword():
    """单独「分诊」不应触发工作流 fastpath，避免误路由。"""
    assert match_workflow("分诊") is None
    assert match_workflow("质量异常分诊") == "quality_alert_triage"


def test_query_ocap_tasks_schema_has_parameters_wrapper():
    from api.services.chat_tools_service import TOOL_DEFINITIONS

    tool = next(t for t in TOOL_DEFINITIONS if t["function"]["name"] == "query_ocap_tasks")
    params = tool["function"]["parameters"]
    assert params["type"] == "object"
    assert "operator" not in params.get("required", [])
