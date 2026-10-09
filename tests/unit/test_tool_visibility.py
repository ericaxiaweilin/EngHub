"""工具可见性：每轮下发给模型的目录不再由手写关键词表决定。

这条链以前反过来咬过我们两次：
① `tests/unit/test_update_plan.py` 记下过"定义/执行器/提示词/前端全对，模型却永远收不到工具"；
② 这次实测的自然问法「帮我看看这批货晚不晚，还有没有法子往前挪」，
   词表（46 条规则 / 673 个词 / 28 张 hint 表）一个都没命中 —— 于是模型看不见
   `query_simulation_sensitivity` 的 schema，只能凭印象编一个"应该能提前几天"。
本文件钉住"可见性"这件事本身，并保留两条不是语义判断的例外（附件绑定、纯寒暄省 token）。
"""

import pytest

from api.routes.chat_routes import (  # noqa: E402
    _chat_tool_definitions, _select_tool_names_for_message,
)
from api.services.chat_tools_service import TOOL_DEFINITIONS  # noqa: E402

ALL_NAMES = {d.get("function", {}).get("name") for d in TOOL_DEFINITIONS}


@pytest.mark.asyncio
async def test_a_phrasing_the_word_table_misses_still_gets_the_tool():
    """配对实测：同一条问法，词表没命中，但目录必须发出去 —— 让模型自己选。"""
    question = "帮我看看这批货晚不晚，还有没有法子往前挪"
    gated = await _select_tool_names_for_message(question)
    assert "query_simulation_sensitivity" not in gated, \
        f"这条问法本该是词表的漏网之鱼，否则这个测试证明不了任何东西：{sorted(gated)[:6]}"

    sent = await _chat_tool_definitions(has_spreadsheet_attachment=False, user_message=question)
    names = {d.get("function", {}).get("name") for d in sent}
    assert "query_simulation_sensitivity" in names
    assert "query_pmc_rush_impact" in names, "改交期路径的问法还要能催料，工具不能只给一个"


@pytest.mark.asyncio
async def test_visibility_is_the_whole_catalog_not_a_slice():
    """可见性=全目录：任何带业务内容的句子都不该被裁。"""
    sent = await _chat_tool_definitions(has_spreadsheet_attachment=False,
                                        user_message="库存怎么样")
    assert {d.get("function", {}).get("name") for d in sent} == ALL_NAMES
    assert len(sent) >= 50, f"目录只剩 {len(sent)} 个，说明又有第二道裁剪溜回来了"


@pytest.mark.asyncio
async def test_pure_greeting_pays_no_catalog_but_a_greeting_plus_business_does():
    """例外只是省 token 的成本门：用 fullmatch，不能挡掉任何带内容的句子。"""
    assert await _chat_tool_definitions(has_spreadsheet_attachment=False,
                                        user_message="你好！") == []
    assert await _chat_tool_definitions(has_spreadsheet_attachment=False,
                                        user_message="你好，这批货晚不晚") != []


@pytest.mark.asyncio
async def test_spreadsheet_attachment_still_binds_to_the_workbook_only():
    """附件那条是物理约束（文件名不是 MES 实体），不是语义判断，保留。"""
    assert await _chat_tool_definitions(has_spreadsheet_attachment=True,
                                        workbook_id=None,
                                        user_message="看看这个表") == []
    sent = await _chat_tool_definitions(has_spreadsheet_attachment=True,
                                        workbook_id="wb-1", user_message="看看这个表")
    names = {d.get("function", {}).get("name") for d in sent}
    assert names and names < ALL_NAMES, "工作簿轮应该窄，但不能窄成空、也不能等于全目录"
    assert "query_simulation_sensitivity" not in names
