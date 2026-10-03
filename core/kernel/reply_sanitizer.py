"""Strip tool-call markup that reasoning models sometimes emit as plain text.

真实形态取自线上 chat_messages 泄漏样本（2026-08-14 ~ 2026-10-03）：

1. 一整块 harness 风格调用标记，可能连续多段，也可能在文本中途被截断
   （8-15 那条 4714 字符里就是半截调用）。
2. 另一种 provider 的复数标记，内部用分隔标签分行承载工具名与 JSON。
3. 只残留一个孤立分隔标签。

不变量：**只删除调用标记本身，绝不丢弃标记之外的正文**。8-14 的样本是
"合法答复在前 + 调用标记在后"，任何"从第一个标记处截断"的写法都会把用户
已经拿到的答案吃掉。
"""

import re

_LT = "<"
_GT = ">"


def _tag(name: str, closing: bool = False) -> str:
    """构造字面标签，避免在本模块里出现可被误解析的原始尖括号序列。"""
    return re.escape(f"{_LT}{'/' if closing else ''}{name}{_GT}")


def _tag_open(name: str) -> str:
    """标签开头（允许带属性），如 harness 的 function/parameter 变体。"""
    return re.escape(f"{_LT}{name}") + r"[^>]*" + re.escape(_GT)


# 1) 成块的调用标记：只删这一块，块外的正文不动。
_BLOCK = re.compile(
    _tag_open("tool_call") + r".*?" + _tag("tool_call", closing=True),
    re.DOTALL | re.IGNORECASE,
)
# 未闭合的调用：后面所有行都是调用参数（S1 里就是 scope 的值），整段吃到末尾。
_UNCLOSED_BLOCK = re.compile(
    _tag_open("tool_call") + r".*",
    re.DOTALL | re.IGNORECASE,
)
# 块内的 function/parameter 子标签（块被截断时它们会留在正文里）。
_INNER = re.compile(
    r"(?:" + _tag_open("function") + r"|" + _tag_open("parameter")
    + r"|" + _tag("function", closing=True) + r"|" + _tag("parameter", closing=True)
    + r")",
    re.IGNORECASE,
)

# 2) 复数形态：整块删除，内部 JSON 属于调用参数，不是给用户看的内容。
_HARNESS = re.compile(
    _tag("tool_calls") + r".*?" + _tag("tool_calls", closing=True),
    re.DOTALL | re.IGNORECASE,
)
_HARNESS_UNCLOSED = re.compile(
    _tag("tool_calls") + r".*",
    re.DOTALL | re.IGNORECASE,
)
# 3) 孤立分隔标签。
_SEP = re.compile(
    r"(?:" + _tag("tool_sep") + r"|" + _tag("tool_sep", closing=True) + r")",
    re.IGNORECASE,
)


def strip_tool_call_markup(content: str) -> str:
    """去掉误混入正文的工具调用标记，返回仍然可读的答复文本。"""
    text = content or ""
    if _LT not in text:
        return text.strip()
    text = _HARNESS.sub("", text)
    text = _BLOCK.sub("", text)
    text = _HARNESS_UNCLOSED.sub("", text)
    text = _UNCLOSED_BLOCK.sub("", text)
    text = _INNER.sub("", text)
    text = _SEP.sub("", text)
    return text.strip()


def looks_like_tool_call_leak(content: str) -> bool:
    """判断文本里是否混进了调用标记（用于告警，不改语义）。"""
    text = content or ""
    if _LT not in text:
        return False
    return bool(
        re.search(_tag_open("tool_call"), text, re.IGNORECASE)
        or re.search(_tag("tool_calls"), text, re.IGNORECASE)
        or re.search(_tag("tool_call"), text, re.IGNORECASE)
        or _SEP.search(text)
    )
