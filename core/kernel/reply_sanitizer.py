"""Strip tool-call markup that reasoning models sometimes emit as plain text.

真实形态取自线上 chat_messages 泄漏样本（2026-08-14 ~ 2026-10-04）：

1. 一整块 harness 风格调用标记，可能连续多段，也可能在文本中途被截断
   （8-15 那条 4714 字符里就是半截调用）。
2. 另一种 provider 的复数标记，内部用分隔标签分行承载工具名与 JSON。
3. 只残留一个孤立分隔标签。
4. 另一种 provider 的 tool_use 形态（线上 2026-10-04 泄漏样本）：
   <tool_use>{"name": "...", ...}</tool_use>，也可能未闭合。
5. 推理区块（线上 2026-08-16 / 2026-10-03 泄漏样本）：<think>…</think>、
   <thinking>…</thinking>、带属性的 <think type="…">，以及**只有闭标签的
   孤立 </think>**。最后一种最隐蔽——它既没有开标签可配对，也逃得过
   looks_like_tool_call_leak 的预判，两条路都会放行。
6. invoke 形态（线上 2026-08-15 泄漏样本）：<invoke name="…">…</invoke>，
   常与孤立 </invoke> 混在一起。**开标签**此前没有任何规则覆盖，
   只删孤立闭标签会把 <invoke name="…"> 留给用户。
7. 流末尾被截断的开标签（8-15 那条 4714 字符样本的真实成因）：
   模型连续吐出几百个 <tool_call> 开标签、一个闭标签都没有。流式路径
   若只从「最后一个 <」开始暂扣，前面几百个开标签会当场外发；收尾时
   若流正好断在 <tool_call 这种半截标签上，连暂扣尾巴本身也清不掉。

不变量：**只删除调用标记本身，绝不丢弃标记之外的正文**。8-14 的样本是
"合法答复在前 + 调用标记在后"，任何"从第一个标记处截断"的写法都会把用户
已经拿到的答案吃掉。

同理，合法的尖括号文本（"当 a<b 时成立"）与合法 JSON
（{"code": 200}）必须原样保留——tests/unit/test_reply_sanitizer.py 有钉子。
"""

import json
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
# 6) invoke 形态：与 tool_use 同构。**开标签**此前无人覆盖，只删 </invoke>
# 会把 <invoke name="…"> 留给用户（线上 2026-08-15 样本）。
_INVOKE = re.compile(
    _tag_open("invoke") + r".*?" + _tag("invoke", closing=True),
    re.DOTALL | re.IGNORECASE,
)
_INVOKE_UNCLOSED = re.compile(
    _tag_open("invoke") + r".*",
    re.DOTALL | re.IGNORECASE,
)

# 推理区块。线上残留（2026-08-14 ~ 2026-10-04）里形态不止一种，只匹配字面量
# "<think>" 会漏掉三类真实样本：
#   a. 变体标签名 <thinking>…</thinking>；
#   b. 带属性的开标签 <think type="reasoning">…</think>；
#   c. 孤立的闭标签 </think>——开标签被前一轮剥掉后剩下的尾巴，
#      既没有开标签可配对，也不在 looks_like_tool_call_leak 的预判范围内。
# 因此闭标签单独一条规则，且必须无条件执行（见 strip_reasoning_markup）。
_REASONING_NAMES = "think|thinking|reasoning"
_THINK_CLOSED = re.compile(
    r"<(?:" + _REASONING_NAMES + r")(?:\s[^>]*)?>.*?</(?:" + _REASONING_NAMES + r")\s*>",
    re.DOTALL | re.IGNORECASE,
)
_THINK_UNCLOSED = re.compile(
    r"<(?:" + _REASONING_NAMES + r")(?:\s[^>]*)?>.*",
    re.DOTALL | re.IGNORECASE,
)
_THINK_ORPHAN_CLOSE = re.compile(
    r"</(?:" + _REASONING_NAMES + r")\s*>",
    re.IGNORECASE,
)

# 4) 协议标签的孤立闭标签：同上，开标签已被剥掉时只剩尾巴。
_ORPHAN_CLOSE = re.compile(
    r"</(?:tool_call|tool_calls|tool_use|function|parameter|tool_sep|invoke)\s*>",
    re.IGNORECASE,
)

# 3) 孤立分隔标签。
_SEP = re.compile(
    r"(?:" + _tag("tool_sep") + r"|" + _tag("tool_sep", closing=True) + r")",
    re.IGNORECASE,
)

# 7) 流式暂扣点：所有「块开标签」的并集。feed() 只从最后一个 "<" 暂扣是不够的——
# 连续多个未闭合开标签时（8-15 那条 4714 字符样本），前面的开标签会被当成
# 普通文本外发。因此还要从「最早的一个未闭合开标签」开始暂扣；这些内容在
# flush() 里由 *_UNCLOSED 规则整段吃掉。
_HOLD_OPENER = re.compile(
    r"(?:"
    + _tag_open("tool_call")          # 同时覆盖 <tool_calls>（[^>]* 吃掉 "s"）
    + r"|" + _tag_open("tool_use")
    + r"|" + _tag_open("invoke")
    + r"|" + r"<(?:" + _REASONING_NAMES + r")(?:\s[^>]*)?>"
    + r")",
    re.IGNORECASE,
)

# 7b) 流末尾被截断的开标签：<tool_call / <tool_use / <invoke / <think … 半截，
# 没有 ">"。只在「字符串末尾」生效（$ 锚定），且标签名前缀至少 3 个字符——
# 单个字母前缀（<t / <i / <f / <p）太容易撞上正文里的合法尖括号
# （"当 a<b 时成立" 里的 "<b"），不放行。
_PROTOCOL_TAGS = (
    "tool_call", "tool_calls", "tool_use", "tool_sep",
    "think", "thinking", "reasoning", "invoke", "function", "parameter",
)
_MIN_PARTIAL = 3
_PARTIAL_ALTS = sorted(
    {re.escape(n[:i]) for n in _PROTOCOL_TAGS for i in range(_MIN_PARTIAL, len(n) + 1)},
    key=len,
    reverse=True,
)
_PARTIAL_TAG = re.compile(
    r"</?(?:" + "|".join(_PARTIAL_ALTS) + r")(?![a-zA-Z_])[^>]*$",
    re.IGNORECASE,
)


def strip_tool_call_markup(content: str) -> str:
    """去掉误混入正文的调用/推理标记，返回仍然可读的答复文本。"""
    text = content or ""
    if _LT not in text and '"tool"' not in text:
        return text.strip()
    text = _HARNESS.sub("", text)
    text = _BLOCK.sub("", text)
    text = _TOOL_USE.sub("", text)
    text = _INVOKE.sub("", text)
    text = _HARNESS_UNCLOSED.sub("", text)
    text = _TOOL_USE_UNCLOSED.sub("", text)
    text = _INVOKE_UNCLOSED.sub("", text)
    text = _UNCLOSED_BLOCK.sub("", text)
    text = _INNER.sub("", text)
    text = _SEP.sub("", text)
    text = _THINK_CLOSED.sub("", text)
    text = _THINK_UNCLOSED.sub("", text)
    text = _THINK_ORPHAN_CLOSE.sub("", text)
    text = _ORPHAN_CLOSE.sub("", text)
    text = _PARTIAL_TAG.sub("", text)
    text = strip_tool_json(text)
    return text.strip()


def strip_reasoning_markup(text: str) -> str:
    """无条件清一遍推理区块（闭合 / 未闭合 / 带属性 / 变体标签名 / 孤立闭标签）。

    与 ``strip_tool_call_markup`` 的分工：那个走 ``looks_like_tool_call_leak`` 预判，
    而孤立闭标签与变体标签名恰好都逃得过那个预判，所以推理区块必须单独一条
    无条件通道，否则 ``_clean_model_reply`` 会整段放行。

    不变量与调用标记一致：**只删标记本身，标记之外的正文一律保留**。
    """
    out = text or ""
    if _LT not in out:
        return out
    out = _THINK_CLOSED.sub("", out)
    out = _THINK_UNCLOSED.sub("", out)
    out = _THINK_ORPHAN_CLOSE.sub("", out)
    return out


def looks_like_tool_call_leak(content: str) -> bool:
    """判断文本里是否混进了调用标记（用于告警，不改语义）。"""
    text = content or ""
    if _LT not in text and '"tool"' not in text:
        return False
    return bool(
        re.search(_tag_open("tool_call"), text, re.IGNORECASE)
        or re.search(_tag_open("tool_use"), text, re.IGNORECASE)
        or re.search(_tag_open("invoke"), text, re.IGNORECASE)
        or bool(_TOOL_JSON_START.search(text))
        or re.search(_tag("tool_calls"), text, re.IGNORECASE)
        or re.search(_tag("tool_call"), text, re.IGNORECASE)
        or _SEP.search(text)
        or _ORPHAN_CLOSE.search(text)
        or _PARTIAL_TAG.search(text)
    )


def strip_complete_blocks(text: str) -> str:
    """只删已经闭合的调用/推理标记块；跨 chunk 的半截标签原样保留待后续判定。"""
    out = text or ""
    if _LT not in out:
        return out
    out = _HARNESS.sub("", out)
    out = _BLOCK.sub("", out)
    out = _TOOL_USE.sub("", out)
    out = _INVOKE.sub("", out)
    out = _THINK_CLOSED.sub("", out)
    out = _THINK_ORPHAN_CLOSE.sub("", out)
    out = _ORPHAN_CLOSE.sub("", out)
    out = _INNER.sub("", out)
    out = _SEP.sub("", out)
    return out


_TOOL_JSON_START = re.compile(r'\{\s*"tool"\s*:')


def _scan_json_span(text: str, start: int):
    """从 start（应为 '{'）按括号配平找 JSON 结束位置；字符串与转义被正确跳过。

    返回 (end_exclusive, parsed)；配不平或解析失败返回 (None, None)。
    """
    depth = 0
    in_str = False
    esc = False
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    raw = text[start:i + 1]
                    try:
                        parsed = json.loads(raw)
                    except Exception:  # noqa: BLE001
                        return None, None
                    return i + 1, parsed
        i += 1
    return None, None


def _is_tool_call_json(parsed) -> bool:
    return (
        isinstance(parsed, dict)
        and isinstance(parsed.get("tool"), str)
        and isinstance(parsed.get("arguments"), (dict, str))
    )


def extract_tool_json_spans(text: str):
    """找出文本里完整的裸 tool-JSON 调用，返回 [(start, end, name, args_dict)]。

    arguments 可能是对象，也可能是二次序列化的字符串，统一转成 dict。
    """
    spans = []
    for m in _TOOL_JSON_START.finditer(text or ""):
        start = m.start()
        end, parsed = _scan_json_span(text, start)
        if end is None or not _is_tool_call_json(parsed):
            continue
        args = parsed.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:  # noqa: BLE001
                args = {}
        if not isinstance(args, dict):
            args = {}
        spans.append((start, end, str(parsed.get("tool")), args))
    return spans


def strip_tool_json(text: str) -> str:
    """删除完整的裸 tool-JSON 调用；末尾截断的半截调用也一并吃掉。"""
    out = text or ""
    if '"tool"' not in out:
        return out
    for start, end, _name, _args in reversed(extract_tool_json_spans(out)):
        out = out[:start] + out[end:]
    m = list(_TOOL_JSON_START.finditer(out))
    if m:
        out = out[:m[0].start()]
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
        for start, end, _name, _args in reversed(extract_tool_json_spans(buf)):
            buf = buf[:start] + buf[end:]
        hold = len(buf)
        lt_idx = buf.rfind(_LT)
        if lt_idx != -1:
            hold = min(hold, lt_idx)
        # 关键：不能只从「最后一个 <」暂扣。连续多个未闭合开标签时，前面的
        # 开标签会被当成普通文本外发（线上 8-15 那条 4714 字符样本）。
        # 从「最早的未闭合开标签」起一并暂扣，交由 flush() 整段吃掉。
        mo = _HOLD_OPENER.search(buf)
        if mo:
            hold = min(hold, mo.start())
        m = list(_TOOL_JSON_START.finditer(buf))
        if m:
            hold = min(hold, m[0].start())
        self._buf = buf[hold:]
        return buf[:hold]

    def flush(self) -> str:
        """流结束：对暂扣尾巴做完整清洗（含未闭合块、推理标记与半截标签）并返回。"""
        out, self._buf = self._buf, ""
        if not out:
            return out
        if _LT not in out and '"tool"' not in out:
            return out
        out = strip_complete_blocks(out)
        out = _THINK_UNCLOSED.sub("", out)
        out = _HARNESS_UNCLOSED.sub("", out)
        out = _TOOL_USE_UNCLOSED.sub("", out)
        out = _INVOKE_UNCLOSED.sub("", out)
        out = _UNCLOSED_BLOCK.sub("", out)
        out = _THINK_ORPHAN_CLOSE.sub("", out)
        out = _ORPHAN_CLOSE.sub("", out)
        out = _PARTIAL_TAG.sub("", out)
        out = strip_tool_json(out)
        return out.strip()


# ──────────────────────────────────────────────
# 「正文里的数字算不算数据引用」—— 对话核实与 L4 可回溯率共用这一份口径
# ──────────────────────────────────────────────
_DATA_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9.])\d[\d,]{2,}(?:\.\d+)?(?![A-Za-z0-9])")


# 「这条答复自己已经把数标成没查过库」的说法不止一种：内核追加的标注是一句固定话，
# 模型自己也会写"按经验估算/不调用接口/不是实时数据"。判据和标注必须认同一份短语表，
# 否则一边算披露、另一边追加第二遍标注，读者看到两段互相矛盾的免责声明。
DISCLOSURE_PHRASES = ("未经核实", "没有调用 MES 工具核实", "不调用接口", "不用调接口",
                      "经验估算", "按经验估", "不是实时数据", "非实时数据", "估算值")


def is_disclosed(text) -> bool:
    body = str(text or "")
    return any(phrase in body for phrase in DISCLOSURE_PHRASES)


def numeric_claims(text: str) -> list:
    """返回正文里像"数据读数"的数字串。

    刻意排掉三类看着像数字的东西：年份（2026）、ID/UUID 里的一段（e085、2448a9 ——
    前后粘着字母或数字就不算）、日期分片（2026-10-02 只剩年份，已被排掉）。
    判"这句话有没有引用台账数"统一用这里，别各处再各写一条正则。"""
    out = []
    for tok in _DATA_NUMBER_RE.findall(str(text or "")):
        plain = tok.replace(",", "")
        if re.fullmatch(r"20\d\d", plain):
            continue
        out.append(tok)
    return out


# ── 「引擎报了算不出」的唯一判据：出口要补一行、读数要判点名率，两处必须同一把尺 ──
_GAP_FIELDS = ("reason", "ask", "missing")
_GAP_SPLIT = re.compile(r"[，。；、：:（）()\[\]「」\s→/]+")


def iter_unavailable(result):
    """从一次（或一批）工具返回里摊平所有 unavailable 条目。

    形状有三层：list（一条答复里多个工具）、dict、以及放在 answers/layers 里的结果。
    少认一层就会把"有缺项"读成"没缺项" —— 那是静默放行。
    """
    if isinstance(result, list):
        flat = []
        for one in result:
            flat.extend(iter_unavailable(one))
        return flat
    if not isinstance(result, dict):
        return []
    blocks = [result]
    answers = result.get("answers")
    if isinstance(answers, dict):
        # answers 是 {"键": {…}}：真正的 unavailable 常在值里，只认这一层 dict 本身会漏
        blocks.append(answers)
        blocks.extend(x for x in answers.values() if isinstance(x, dict))
    layers = result.get("layers")
    if isinstance(layers, list):
        blocks.extend(x for x in layers if isinstance(x, dict))
    out = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        items = b.get("unavailable")
        if isinstance(items, list):
            out.extend(x for x in items if isinstance(x, dict))
    return out


def gap_phrases(item):
    """这一条缺项"该出现在正文里"的说法：只取它自己的 reason/ask/missing 片段。

    通用词表（算不出/缺/没有…）判不得这件事：答复讲**另一批杠杆**没效果时句子里也有
    那些词，会被误判成"这条点名了"（实测 3db81365 就是这样）。
    """
    out = []
    for field in _GAP_FIELDS:
        for seg in _GAP_SPLIT.split(str((item or {}).get(field) or "")):
            seg = seg.strip(" 。.；;，,")
            if len(seg) >= 4 and seg not in out:
                out.append(seg)
    # 不回退到 name：那等于要求答复里写 `change_attribution` 这种内部键名，
    # 而 L4「契约泄漏内部标识数」正是罚这个。三样都没有 = 信封不合格（另有判线罚它），
    # 这一格对它不判：既不给分也不扣分。
    return out


def gap_is_disclosed(item, reply: str) -> bool:
    """答复有没有把这一条缺项交代给读者。"""
    phrases = gap_phrases(item)
    return bool(phrases) and any(p in (reply or "") for p in phrases)


def missing_gap_note(items, reply: str, cap: int = 3) -> str:
    """有缺项没带到 → 要追加的一行；都带到了（或没缺项）→ 空串。"""
    lost = [it for it in (items or []) if not gap_is_disclosed(it, reply)]
    if not lost:
        return ""
    # 几个杠杆常共享同一句 reason（实测三个杠杆都是"这一维测不出斜率，无法归因"），
    # 原样列出来就是把同一句话重复三遍 —— 按说法去重，条数另外报。
    uniq = []
    for it in lost:
        phrase = str(it.get("reason") or it.get("ask")
                     or (gap_phrases(it) or [""])[0] or "这条没写清缺什么")[:60]
        if phrase not in uniq:
            uniq.append(phrase)
    shown = uniq[:cap]
    more = f"…（列出 {len(shown)} 种说法，共 {len(lost)} 项）" if len(lost) > len(shown) else ""
    return ("\n\n〔引擎本轮还有 " + str(len(lost)) + " 项给不出数〕"
            + "；".join(shown) + more
            + " —— 这不是「没做」，是这一项本轮缺输入或量不出斜率；"
              "把输入补上才谈得到一个数。")
