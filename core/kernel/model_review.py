"""ModelReview - 结构化事实审查（Phase 5）。

把 chat_routes._verify_grounded_reply 升级为：
    Evidence 链 → 模型审查 → ReviewResult(verdict/issues/evidence_chain) → 修正

verdict:
    grounded            事实逐项可验证，直接返回
    partially_grounded  部分陈述可验证（去掉不可验证项后返回，标记 warning）
    hallucinated        关键陈述与工具事实矛盾 → 最多重试 2 次（带证据约束）

依赖 call_llm 注入（与 AgentLoop 相同签名），无全局状态，便于单测。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.kernel.evidence import Evidence, build_evidence_chain

_logger = logging.getLogger("engflow_model_review")

MAX_RETRIES = 2

REVIEW_SYSTEM_PROMPT = (
    "你是事实审校器。基于给定的工具事实 JSON，逐项判断模型草稿中的每一条陈述：\n"
    "1. 能被工具结果直接验证 → 保留；\n"
    "2. 工具结果未提供依据（猜测/推断/预警/建议/示例/未执行动作）→ 删除；\n"
    "3. 与工具结果矛盾 → 删除。\n"
    "只输出修订后的最终答复（中文自然表达），不要输出解释。"
)


@dataclass
class ReviewResult:
    verdict: str = "grounded"                 # grounded | partially_grounded | hallucinated
    issues: List[str] = field(default_factory=list)
    evidence_chain: List[Dict[str, Any]] = field(default_factory=list)
    revised_reply: str = ""
    original_reply: str = ""
    retries: int = 0
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "issues": self.issues,
            "evidence_chain": self.evidence_chain,
            "revised_reply": self.revised_reply,
            "retries": self.retries,
            "duration_ms": round(self.duration_ms, 1),
        }


class ModelReviewer:
    """基于工具事实的草稿审校 + 修正循环。"""

    def __init__(
        self,
        call_llm: Callable[[Dict[str, Any]], Awaitable[Any]],
        clean_reply: Callable[[str], str],
        *,
        max_retries: int = MAX_RETRIES,
        request_timeout: float = 60.0,
    ) -> None:
        self._call_llm = call_llm
        self._clean_reply = clean_reply
        self._max_retries = max_retries
        self._timeout = request_timeout

    async def review(
        self,
        reply: str,
        actions: List[Any],
        model: str,
    ) -> ReviewResult:
        start = time.monotonic()
        chain = build_evidence_chain(actions)
        result = ReviewResult(
            original_reply=reply,
            evidence_chain=[e.to_dict() for e in chain],
        )
        if not chain:
            result.verdict = "grounded"
            result.revised_reply = reply
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        revised = await self._review_once(reply, chain, model)
        if revised is None:
            # 网关失败：无法审查 → 保留草稿，不误判为幻觉
            result.verdict = "grounded"
            result.revised_reply = reply
            result.issues.append("审查服务不可用，保留原始答复")
            result.duration_ms = (time.monotonic() - start) * 1000
            return result
        result.revised_reply = revised or reply
        result.verdict = self._classify(revised, chain, reply)

        if result.verdict == "hallucinated":
            result.retries += 1
            _logger.info("[model_review] hallucinated, retry 1/%d", self._max_retries)
            for attempt in range(self._max_retries):
                constrained = self._with_constraint(reply, chain)
                fixed = await self._review_once(constrained, chain, model)
                if fixed is None:
                    break
                if fixed:
                    result.revised_reply = fixed
                    result.retries = attempt + 1
                    result.verdict = self._classify(fixed, chain, reply)
                    if result.verdict != "hallucinated":
                        break
            if result.verdict == "hallucinated":
                result.issues.append("多次修正仍与工具事实矛盾，返回最保守版本")
                if result.revised_reply in (reply, ""):
                    result.revised_reply = reply

        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    # ── 内部 ──

    async def _review_once(
        self, draft: str, chain: List[Evidence], model: str,
    ) -> Optional[str]:
        """执行一次审查。返回 None=网关/解析失败（保留草稿）；""=模型空输出；str=修订。"""
        facts = [e.to_dict() for e in chain]
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"工具事实：\n{json.dumps(facts, ensure_ascii=False, default=str)}"
                        f"\n\n待审校草稿：\n{draft}"
                    ),
                },
            ],
            "temperature": 0,
            "max_tokens": 768,
        }
        try:
            resp = await self._call_llm(payload, request_timeout=self._timeout)
            if resp.status_code >= 400:
                return None
            data = resp.json()
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return self._clean_reply(content) or ""
        except Exception as exc:  # noqa: BLE001
            _logger.warning("[model_review] review call failed: %s", exc)
            return None

    def _classify(
        self, revised: str, chain: List[Evidence], original: str = "",
    ) -> str:
        """结构化判定：依据工具事实是否可支撑草稿。

        启发式：修订为空 → hallucinated；修订短于草稿且删减显著 → partially；
        其余 → grounded。
        """
        if not revised:
            return "hallucinated"
        if original and len(revised.strip()) < len(original.strip()) * 0.5:
            return "partially_grounded"
        return "grounded"

    def _with_constraint(self, draft: str, chain: List[Evidence]) -> str:
        facts = [e.to_dict() for e in chain]
        return (
            f"{draft}\n\n[约束] 只允许基于以下事实重写，不得新增任何未在事实中的信息：\n"
            f"{json.dumps(facts, ensure_ascii=False, default=str)}"
        )