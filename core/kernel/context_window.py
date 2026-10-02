"""Bounded model context for the chat harness.

The canonical thread history remains append-only in ``chat_messages``.  This
module only prepares a smaller model-visible input when a long thread would
otherwise exceed the configured context budget, following the same separation
as Codex compaction: conversation history is durable, the active input is not.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List


DEFAULT_MAX_MESSAGES = 24
DEFAULT_MAX_CHARS = 24_000
SUMMARY_CHAR_BUDGET = 6_000


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def approximate_tokens(messages: List[Dict[str, Any]]) -> int:
    """Return a conservative, provider-independent token estimate."""
    chars = sum(len(_content_text(message.get("content"))) for message in messages)
    chars += sum(len(str(message.get("role", ""))) for message in messages)
    return max(1, (chars + 3) // 4)


def _message_chars(message: Dict[str, Any]) -> int:
    return len(_content_text(message.get("content"))) + len(str(message.get("role", "")))


def _summarize(messages: List[Dict[str, Any]]) -> str:
    lines = [
        "【历史上下文摘要】以下内容来自同一会话较早轮次；完整原文仍保存在会话记录中。"
    ]
    used = len(lines[0])
    for index, message in enumerate(messages, start=1):
        role = str(message.get("role") or "unknown")
        content = " ".join(_content_text(message.get("content")).split())
        if not content:
            content = "（无文本内容）"
        line = f"{index}. {role}: {content[:420]}"
        if used + len(line) + 1 > SUMMARY_CHAR_BUDGET:
            lines.append(f"（其余 {len(messages) - index + 1} 条历史已省略，仍可从会话检索）")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


@dataclass(frozen=True)
class CompactionResult:
    messages: List[Dict[str, Any]]
    compacted: bool
    original_message_count: int
    output_message_count: int
    summarized_message_count: int
    estimated_tokens_before: int
    estimated_tokens_after: int


def compact_messages(
    messages: List[Dict[str, Any]],
    *,
    max_messages: int = DEFAULT_MAX_MESSAGES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> CompactionResult:
    """Keep recent turns and prepend a bounded summary of older turns.

    The function never mutates caller-owned messages.  The last user turn is
    always retained; if a budget is too small, older messages are discarded
    before the current turn is considered.
    """
    source = deepcopy(messages)
    before_tokens = approximate_tokens(source)
    max_messages = max(4, int(max_messages))
    max_chars = max(2_000, int(max_chars))
    if len(source) <= max_messages and sum(_message_chars(m) for m in source) <= max_chars:
        return CompactionResult(
            messages=source,
            compacted=False,
            original_message_count=len(source),
            output_message_count=len(source),
            summarized_message_count=0,
            estimated_tokens_before=before_tokens,
            estimated_tokens_after=before_tokens,
        )

    tail = source[-max_messages:]
    # A compacted tail should begin at a user turn where possible, avoiding a
    # dangling assistant/tool pair as the first visible item after the summary.
    first_user = next(
        (index for index, message in enumerate(tail) if message.get("role") == "user"),
        0,
    )
    tail = tail[first_user:]
    older_count = len(source) - len(tail)
    summary = {"role": "system", "content": _summarize(source[:older_count])}

    # Keep the summary bounded and retain the newest user request even when a
    # single workbook/OCR message is unusually large.
    while len(tail) > 1 and (
        len(tail) > max_messages - 1
        or _message_chars(summary) + sum(_message_chars(m) for m in tail) > max_chars
    ):
        tail.pop(0)
    result = [summary, *tail]
    after_tokens = approximate_tokens(result)
    return CompactionResult(
        messages=result,
        compacted=True,
        original_message_count=len(source),
        output_message_count=len(result),
        summarized_message_count=older_count,
        estimated_tokens_before=before_tokens,
        estimated_tokens_after=after_tokens,
    )
