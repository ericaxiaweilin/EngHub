"""Strip tool-call markup that reasoning models sometimes emit as plain text.

真实形态取自线上 chat_messages 泄漏样本（2026-08-14 ~ 2026-10-03）：

1. 一整块 harness 风格调用标记，可能连续多段，也可能在文本中途被截断
   （8-15 那条 4714 字符里就是半截调用）。
2. 另一种 provider 的复数标记，内部用分隔标签分行承载工具名与 JSON。
3. 只残留一个孤立分隔标签。
4. 另一种 provider 的 tool_use 形态（线上 2026-10-04 泄漏样本）：
   <tool_use>{"name": "...", ...}</tool_use>，也可能未闭合。

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
# 4) tool_use 形态：整块删除；未闭合则吃到末尾（JSON 属于调用参数）。
_TOOL_USE = re.compile(
    _tag_open("tool_use") + r".*?" + _tag("tool_use", closing=True),
    re.DOTALL | re.IGNORECASE,
)
_TOOL_USE_UNCLOSED = re.compile(
    _tag_open("tool_use") + r".*",
    re.DOTALL | re.IGNORECASE,
)

_THINK_CLOSED = re.compile(
    r"<think>.*?</think>",
    re.DOTALL | re.IGNORECASE,
)
_THINK_UNCLOSED = re.compile(
    r"<think>.*",
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
    text = _TOOL_USE.sub("", text)
    text = _HARNESS_UNCLOSED.sub("", text)
    text = _TOOL_USE_UNCLOSED.sub("", text)
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
        or re.search(_tag_open("tool_use"), text, re.IGNORECASE)
        or re.search(_tag("tool_calls"), text, re.IGNORECASE)
        or re.search(_tag("tool_call"), text, re.IGNORECASE)
        or _SEP.search(text)
    )


def strip_complete_blocks(text: str) -> str:
    """只删已经闭合的调用/推理标记块；跨 chunk 的半截标签原样保留待后续判定。"""
    out = text or ""
    if _LT not in out:
        return out
    out = _HARNESS.sub("", out)
    out = _BLOCK.sub("", out)
    out = _TOOL_USE.sub("", out)
    out = _THINK_CLOSED.sub("", out)
    out = _INNER.sub("", out)
    out = _SEP.sub("", out)
    return out


class StreamSanitizer:
    """SSE 流式逐块过滤：已闭合的标记块直接吃掉，未闭合的尾巴暂扣。

    用法：每来一个 delta 调 feed()，返回值是可直接展示/落库的安全前缀；
    流结束调 flush() 拿暂扣尾巴的完整清洗结果。普通文本（含单独的 "<"）
    只延迟一个 chunk，不丢字；flush 时原样放出。
    """

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, text: str) -> str:
        """输入一块增量，返回可安全外发的前缀（可能为空字符串）。"""
        if not text:
            return ""
        buf = strip_complete_blocks(self._buf + text)
        idx = buf.rfind(_LT)
        if idx == -1:
            self._buf = ""
            return buf
        self._buf = buf[idx:]
        return buf[:idx]

    def flush(self) -> str:
        """流结束：对暂扣尾巴做完整清洗（含未闭合块与 think）并返回。"""
        out, self._buf = self._buf, ""
        if not out or _LT not in out:
            return out
        out = strip_complete_blocks(out)
        out = _THINK_UNCLOSED.sub("", out)
        out = _HARNESS_UNCLOSED.sub("", out)
        out = _TOOL_USE_UNCLOSED.sub("", out)
        out = _UNCLOSED_BLOCK.sub("", out)
        return out.strip()
