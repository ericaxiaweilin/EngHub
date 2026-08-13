"""Tests for Phase 5 — Evidence + ModelReview（结构化事实审查）。

覆盖：
- evidence 置信度推断、链构建
- ModelReviewer：grounded / partially / hallucinated 判定
- hallucinated → 重试修正
- Kernel 接入：reviewer 接管后替换草稿、跳过内部 verify、metadata 记录
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.kernel.evidence import Evidence, build_evidence_chain, confidence_for_result
from core.kernel.model_review import ModelReviewer, ReviewResult


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _action(tool, result, args=None):
    return SimpleNamespace(
        tool=tool, label=tool, arguments=args or {}, result=result, success=True,
    )


# ──────────────────────────────────────────────
# Evidence
# ──────────────────────────────────────────────

def test_confidence_inference():
    assert confidence_for_result({"error": "boom"}) == 0.0
    assert confidence_for_result({"permission_denied": True}) == 0.0
    assert confidence_for_result({"count": 0, "inventory": []}) == 0.5
    assert confidence_for_result({"result": {"a": 1}}) == 1.0
    assert confidence_for_result({"work_orders": [1]}) == 1.0


def test_build_evidence_chain():
    chain = build_evidence_chain([
        _action("query_work_orders", {"count": 1, "work_orders": [{"x": 1}]}),
        _action("create_work_order", {"error": "no"}),
    ])
    assert len(chain) == 2
    assert chain[0].tool_name == "query_work_orders"
    assert chain[0].confidence == 1.0
    assert chain[1].confidence == 0.0
    d = chain[0].to_dict()
    assert d["tool_name"] == "query_work_orders"


def test_evidence_to_dict():
    e = Evidence(tool_name="t", tool_args={"k": 1}, tool_result={"r": 2})
    d = e.to_dict()
    assert d["tool_name"] == "t" and d["timestamp"]


# ──────────────────────────────────────────────
# ModelReviewer
# ──────────────────────────────────────────────

def _llm_resp(content):
    return MagicMock(
        status_code=200,
        json=lambda: {"choices": [{"message": {"content": content}}]},
    )


@pytest.mark.asyncio
async def test_review_no_actions_returns_as_is():
    reviewer = ModelReviewer(
        call_llm=AsyncMock(), clean_reply=lambda c: c,
    )
    result = await reviewer.review("草稿", [], "m")
    assert result.verdict == "grounded"
    assert result.revised_reply == "草稿"


@pytest.mark.asyncio
async def test_review_grounded():
    calls = []

    async def call_llm(payload, **_kw):
        calls.append(payload)
        return _llm_resp("修订后的完整答复")

    reviewer = ModelReviewer(call_llm=call_llm, clean_reply=lambda c: c)
    result = await reviewer.review(
        "工单状态正确。", [_action("query_work_orders", {"count": 1, "work_orders": [{"x": 1}]})],
        "m",
    )
    assert result.verdict == "grounded"
    assert result.revised_reply == "修订后的完整答复"
    assert len(result.evidence_chain) == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_review_partially_grounded_when_trimmed():
    async def call_llm(payload, **_kw):
        return _llm_resp("简短")  # 远短于原稿 → partially

    reviewer = ModelReviewer(call_llm=call_llm, clean_reply=lambda c: c)
    result = await reviewer.review(
        "一个非常长的草稿说明有很多不必要的推断与猜测内容需要被删除以便判定为部分可信",
        [_action("query_work_orders", {"count": 1, "work_orders": [{"x": 1}]})],
        "m",
    )
    assert result.verdict == "partially_grounded"


@pytest.mark.asyncio
async def test_review_hallucinated_retries():
    """空修订 → hallucinated；第二次返回合理 → grounded。"""
    responses = ["", "修复后的答复"]

    async def call_llm(payload, **_kw):
        return _llm_resp(responses.pop(0))

    reviewer = ModelReviewer(call_llm=call_llm, clean_reply=lambda c: c)
    result = await reviewer.review(
        "草稿",
        [_action("query_work_orders", {"count": 1, "work_orders": [{"x": 1}]})],
        "m",
    )
    assert result.retries == 1
    assert result.revised_reply == "修复后的答复"


@pytest.mark.asyncio
async def test_review_gateway_error_keeps_draft():
    async def call_llm(payload, **_kw):
        return MagicMock(status_code=500)

    reviewer = ModelReviewer(call_llm=call_llm, clean_reply=lambda c: c)
    result = await reviewer.review(
        "草稿", [_action("t", {"r": 1})], "m",
    )
    assert result.revised_reply == "草稿"
    assert result.verdict == "grounded"


# ──────────────────────────────────────────────
# Kernel 接入
# ──────────────────────────────────────────────

async def _run_kernel_with_reviewer(review_content="审查后答复"):
    from core.kernel import HarnessKernel
    from core.kernel.context import KernelContext

    db = AsyncMock()

    async def responder(payload):
        # 第一轮：工具调用；第二轮：最终草稿
        if any(m.get("role") == "tool" for m in payload["messages"]):
            return MagicMock(
                status_code=200,
                json=lambda: {"choices": [{"message": {"content": "草稿"}}]},
            )
        import json
        return MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {
                "content": "",
                "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {"name": "query_work_orders", "arguments": json.dumps({})},
                }],
            }}]},
        )

    internal_verify_calls = []

    async def internal_verify(reply, actions, payload):
        internal_verify_calls.append(reply)
        return reply

    reviewer_calls = []

    class FakeReviewer:
        async def review(self, reply, actions, model):
            reviewer_calls.append(reply)
            return SimpleNamespace(
                verdict="grounded", issues=[], evidence_chain=[], revised_reply=review_content,
                to_dict=lambda: {"verdict": "grounded", "revised_reply": review_content},
            )

    fake_reviewer = FakeReviewer()

    kernel = HarnessKernel(
        db=db,
        call_llm=responder,
        resolve_model_route=AsyncMock(return_value={
            "task_id": "t", "provider": "p", "gateway_model": "m",
            "request_timeout": 5.0, "max_completion_tokens": 256,
        }),
        execute_tool=AsyncMock(return_value={"count": 1, "work_orders": [{"x": 1}]}),
        clean_reply=lambda c: c,
        ground_tool_result=lambda r: "grounded",
        verify_reply=internal_verify,
        make_tool_action=lambda *a, **k: SimpleNamespace(tool=a[0]),
        write_tools=frozenset(), sim_tools=frozenset(),
        tool_definitions=[],
        system_prompt="sys", final_grounding_prompt="ground",
        max_tool_rounds=3,
        model_reviewer=fake_reviewer,
    )
    ctx = KernelContext(
        request_id="req-review", factory_id="F01",
        user=SimpleNamespace(username="eric"),
        messages=[{"role": "user", "content": "hi"}],
        model_route={"task_id": "t", "provider": "p", "gateway_model": "m"},
        operator="eric",
    )
    result = await kernel.handle(ctx)
    return result, internal_verify_calls, reviewer_calls


@pytest.mark.asyncio
async def test_kernel_reviewer_replaces_reply_and_skips_internal_verify():
    result, internal_verify_calls, reviewer_calls = await _run_kernel_with_reviewer()
    assert result.reply == "审查后答复"
    assert reviewer_calls == ["草稿"]
    assert internal_verify_calls == []  # reviewer 接管，内部 verify 不再执行
    assert result.telemetry["review"]["verdict"] == "grounded"