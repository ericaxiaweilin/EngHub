"""对话确认承接：把“用户说确认”固化为显式 grounding，杜绝重复追问。

背景：确认完全靠模型自觉时，降级模型会无视已确认内容反复提问
（线上 2026-10-04 事故：同一问题连问三轮）。本模块是纯函数：
输入历史 messages，输出要不要追加一条 system grounding。

触发必须同时满足三条，缺一不可：
1. 本轮是短确认开头（纯确认词，或确认词 + 简短补充指示）；
2. 上轮助手确实在提问（?/？/请确认/请补充/告诉我/吗呢结尾）；
3. 补充部分不像新请求（动词黑名单），且本轮不是疑问句。

与 compaction 的关系：context_window.compact_messages 永远原样保留
最近若干轮，确认场景的问答对一定在 tail 里，所以这里直接读原文即可，
不需要持久化 pending-question 状态——历史本身就是状态。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

_CONFIRM_LEADS = (
    "确认", "是的", "是", "好", "好的", "可以", "同意", "没问题", "继续",
    "就这样", "开始", "OK", "ok", "Yes", "yes", "对", "嗯", "嗯嗯", "行",
    "那就这样", "就按你说的", "照做", "执行吧",
)

# 以这些词开头的补充通常是新请求而非确认（如“可以帮我查一下”），必须排除
_NON_CONFIRM_HINTS = (
    "帮", "请", "查", "找", "做", "建", "生成", "告诉", "什么", "怎么",
    "为什么", "是否", "多少", "哪个", "哪些", "列出", "显示", "分析",
    "创建", "删除", "下达", "报工", "完工", "一下", "看下", "查下",
    "帮忙", "麻烦", "请问",
)


def message_text(content: Any) -> str:
    """用户消息可能是纯文本或多模态列表，统一抽成文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and str(part.get("type") or "") == "text":
                parts.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content or "")


def confirmation_grounding(history: List[Dict[str, Any]]) -> str:
    """判定是否需要追加确认 grounding；返回 "" 表示不干预。"""
    if not history:
        return ""
    last = history[-1] if isinstance(history[-1], dict) else {}
    if str(last.get("role") or "") != "user":
        return ""
    text = message_text(last.get("content")).strip()
    if not text or len(text) > 30:
        return ""
    if text.endswith(("?", "？")):
        return ""
    head = re.split(r"[\s，。！!、:：]+", text, maxsplit=1)[0]
    if head in _CONFIRM_LEADS:
        rest = text[len(head):].strip(" ，。！!、:：")
    elif any(
        text.startswith(lead)
        for lead in ("确认", "好的", "可以", "同意", "是", "那就", "就按", "照做")
    ):
        rest = text
        for lead in ("确认", "好的", "可以", "同意", "是", "那就", "就按", "照做"):
            if text.startswith(lead):
                rest = text[len(lead):].strip(" ，。！!、:：")
                break
    else:
        return ""
    if rest and any(hint in rest for hint in _NON_CONFIRM_HINTS):
        return ""
    prev = next(
        (m for m in reversed(history[:-1])
         if isinstance(m, dict) and str(m.get("role") or "") == "assistant"),
        None,
    )
    if prev is None:
        return ""
    prev_text = message_text(prev.get("content"))
    if not (
        "?" in prev_text or "？" in prev_text
        or "请确认" in prev_text or "请补充" in prev_text or "告诉我" in prev_text
        or re.search(r"(吗|呢|否|还是)[。？?\s]*$", prev_text)
    ):
        return ""
    note = "【用户已确认】用户已接受你上一轮的提议/回答，直接继续执行下一步，严禁重复提问已经确认过的内容。"
    if rest:
        note += f"用户补充指示：{rest}，一并执行。"
    return note
