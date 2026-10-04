"""to-do 模式（update_plan）：工具契约与执行器行为测试。

钉住的东西分两类：
1. **接线契约** —— 工具必须真的出现在 TOOL_DEFINITIONS 里（否则模型根本看不到它），
   必须有中文标签（否则前端卡片显示裸工具名），提示词必须开「计划清单」那条例外。
2. **执行器行为** —— 计划结果要能直接塞进 tool_calls（jsonb）并被前端渲染，
   所以：非法输入必须回 error（ToolAction.success 靠 "error" in result 判定），
   id 必须唯一（否则前端打勾串行），状态必须收敛到固定枚举。
"""

import json

import pytest

from api.services.chat_tools_service import (
    TOOL_DEFINITIONS,
    TOOL_LABELS,
    _TOOL_EXECUTORS,
    execute_tool,
)

pytestmark = [pytest.mark.unit]


def _tool_names():
    return {
        item["function"]["name"]
        for item in TOOL_DEFINITIONS
        if item.get("type") == "function"
    }


# ── 接线契约 ────────────────────────────────────────────────────────────────

def test_update_plan_is_offered_to_the_model():
    """工具定义缺失 = 模型永远调不到，计划清单整个功能不存在。"""
    assert "update_plan" in _tool_names()
    assert "update_plan" in _TOOL_EXECUTORS


def test_update_plan_has_a_chinese_label():
    """前端卡片直接读 TOOL_LABELS，缺了就显示裸工具名。"""
    assert TOOL_LABELS.get("update_plan") == "执行计划"


@pytest.mark.asyncio
async def test_update_plan_is_selected_for_multi_step_turns():
    """**真正的契约**：每轮实际下发给模型的工具集里必须有它。

    ``GET /api/v1/chat/tools`` 返回的是全量静态目录（55 个），不代表每轮会发 ——
    实际发的是 ``_select_tool_names_for_message`` 的"最小可用集"。
    当初就是只验了前者，工具定义、执行器、提示词、前端全对，模型却永远收不到它，
    实测两次一次没调。这条用例钉住这个洞。
    """
    from api.routes.chat_routes import _select_tool_names_for_message

    for question in (
        "帮我梳理一下导入 MES 系统的实施步骤，先列个计划再逐步说明",
        "帮我整理一份给老板的季度汇报，先拉数据、再做图表、最后写结论",
        "帮我排查一下最近停机的原因并给整改建议",
        "产线现在什么情况",  # 未分类的数据请求，靠通用只读集兜住
    ):
        selected = await _select_tool_names_for_message(question)
        assert "update_plan" in selected, f"{question!r} 没选到 update_plan: {selected}"


@pytest.mark.asyncio
async def test_update_plan_is_not_attached_to_chitchat():
    """反向：闲聊不该白搭一个工具（保持"最小可用集"的设计）。"""
    from api.routes.chat_routes import _select_tool_names_for_message

    assert await _select_tool_names_for_message("你好") == set()


def test_prompt_grants_a_structured_plan_exception():
    """提示词原本禁止输出过程；不显式开这条例外，模型不会主动声明计划。"""
    from api.routes.chat_routes import SYSTEM_PROMPT

    # 用前缀而不是完整方括号标题 —— 小标题措辞会调（曾经是【计划清单】），
    # 但"计划清单"这个条款本身不能被删掉。
    assert "【计划清单" in SYSTEM_PROMPT
    assert "update_plan" in SYSTEM_PROMPT
    assert "禁止只在答复正文里用" in SYSTEM_PROMPT  # 不点明后果，模型会用正文编号糊弄


# ── 执行器行为 ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_result_is_renderable_and_persistable():
    """计划要落进 chat_messages.tool_calls（jsonb）→ 必须可 JSON 序列化。"""
    out = await execute_tool(
        None, "update_plan",
        {
            "title": "排查 A 线停机",
            "items": [
                {"id": "s1", "title": "查设备状态", "status": "completed"},
                {"id": "s2", "title": "查停机记录", "status": "in_progress"},
                {"id": "s3", "title": "给结论", "status": "pending"},
            ],
        },
    )
    assert "error" not in out          # ToolAction.success 就是看这个键
    assert out["type"] == "plan"
    assert out["title"] == "排查 A 线停机"
    assert out["total"] == 3 and out["done"] == 1 and out["in_progress"] == 1
    assert out["progress_pct"] == 33
    json.dumps(out, ensure_ascii=False)  # 落 jsonb 前必须能序列化


@pytest.mark.asyncio
async def test_unknown_status_falls_back_to_pending():
    out = await execute_tool(
        None, "update_plan",
        {"items": [{"id": "a", "title": "t", "status": "bogus"}]},
    )
    assert out["items"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_duplicate_ids_are_made_unique():
    """id 重复会让前端 key 冲突、打勾串行。"""
    out = await execute_tool(
        None, "update_plan",
        {"items": [{"id": "a", "title": "x"}, {"id": "a", "title": "y"}]},
    )
    ids = [i["id"] for i in out["items"]]
    assert len(ids) == len(set(ids)) == 2


@pytest.mark.asyncio
async def test_plan_is_capped_at_20_items():
    out = await execute_tool(
        None, "update_plan",
        {"items": [{"id": f"i{n}", "title": f"t{n}"} for n in range(30)]},
    )
    assert out["total"] == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [
    {"items": []},
    {"items": "not-a-list"},
    {},
    {"items": [{"id": "a", "title": "   "}]},
])
async def test_junk_input_is_rejected_not_silently_accepted(args):
    """回 error 才会让卡片显示失败；静默接受会渲染出空计划。"""
    out = await execute_tool(None, "update_plan", args)
    assert "error" in out


@pytest.mark.asyncio
async def test_update_plan_does_not_touch_the_database():
    """计划是本轮对话的过程状态，只读；传 None 作为 db 也不该炸。"""
    out = await execute_tool(None, "update_plan", {"items": [{"id": "a", "title": "t"}]})
    assert "error" not in out
