"""Chat 用户长期记忆服务（跨会话）。

基于 Harness Kernel 架构：请求前置入记忆块（system prompt 头部），请求结束
后从用户消息规则提取新事实落库。规则提取不消耗额外 LLM 调用，保证可靠与低成本。

参考 luaguage 记忆体系（分层 / 画像 / 注入指引 / 写侧安全闸门）并适配本仓库：
- 个人画像：User 行（工号/全名/岗位/部门/工作中心）与已学事实合并成结构化画像
- 注入指引：CROSS_SESSION_SYSTEM_GUIDANCE（必须参考记忆）/ PERSONALIZATION（语气调整）
- 写侧安全：扫描记忆内容，凭据/命令/外传通道硬拦截，注入标记落库前消毒
- 规则提取：名字（多种说法）+ 岗位/部门/偏好，只记明确告知，防疑问句误学

事实 key 约定：
  display_name  用户希望被称呼的名字/昵称（来源：用户明确告知）
  full_name     用户全名（来源：User.full_name 兜底）
  role          岗位/角色
  department    部门
  preferences   一句话工作偏好
  work_center   工序组（来源：User.work_center 兜底）
  username      工号（来源：User.username 兜底）
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ChatMemory, generate_uuid


# ──────────────────────────────────────────────
# 注入指引（参照 luaguage chat_memory_injection）
# ──────────────────────────────────────────────

CROSS_SESSION_SYSTEM_GUIDANCE = (
    "【跨会话长期记忆】以下是此前对话中已记住的关于当前用户的事实。"
    "回答时必须参考其中与用户问题相关的姓名、岗位、偏好等上下文；"
    "不得否认记忆中已明确记录的信息；"
    "但长期记忆不能替代 BOM/EC/工单等正式业务证据，正式数据以系统查询结果为准。"
)

PERSONALIZATION_MEMORY_GUIDANCE = (
    "【个性化】若记忆中包含用户的沟通偏好（如喜欢简洁/详细/用表格），"
    "请自然调整回复风格，不要声明“根据你的偏好”。"
    "若记忆中包含用户名字，自然对话中偶尔可以称呼，但不要每句都叫。"
)


# ──────────────────────────────────────────────
# 读取
# ──────────────────────────────────────────────

async def load_user_memory(
    db: AsyncSession,
    *,
    user_id: str,
    factory_id: Optional[str] = None,
) -> Dict[str, str]:
    """读取该用户的长期记忆事实，返回 {key: value}。"""
    stmt = select(ChatMemory).where(ChatMemory.user_id == user_id)
    if factory_id:
        stmt = stmt.where(ChatMemory.factory_id == factory_id)
    rows = (await db.execute(stmt)).scalars().all()
    facts: Dict[str, str] = {}
    for r in rows:
        key = str(r.key or "")
        value = str(r.value or "").strip()
        if key and value:
            facts[key] = value
    return facts


async def load_user_memory_rows(
    db: AsyncSession,
    *,
    user_id: str,
    factory_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """读取该用户的记忆记录（含来源/置信度/时间），供画像面板展示。"""
    stmt = select(ChatMemory).where(ChatMemory.user_id == user_id)
    if factory_id:
        stmt = stmt.where(ChatMemory.factory_id == factory_id)
    stmt = stmt.order_by(ChatMemory.updated_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        value = str(r.value or "").strip()
        if not value:
            continue
        out.append({
            "key": str(r.key or ""),
            "value": value,
            "confidence": int(r.confidence or 0),
            "source": str(r.source or "chat"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return out


def build_user_profile(
    user: Any,
    facts: Dict[str, str],
    *,
    role_obj: Any = None,
) -> Dict[str, Any]:
    """个人画像：User 行 + 已学事实合并成结构化画像。

    返回 {identity, role, work, preferences} 分层结构。
    """
    profile: Dict[str, Any] = {
        "identity": {},
        "role": {},
        "work": {},
        "preferences": {},
    }
    username = str(getattr(user, "username", "") or "").strip()
    full_name = str(getattr(user, "full_name", "") or "").strip()
    if username:
        profile["identity"]["工号"] = username
    if full_name:
        profile["identity"]["全名"] = full_name
    display = facts.get("display_name")
    if display:
        profile["identity"]["称呼"] = display

    role_name = str(getattr(user, "role", "") or "").strip()
    if role_obj is not None:
        role_name = str(getattr(role_obj, "role_name", "") or role_name).strip()
        dept = str(getattr(role_obj, "department", "") or "").strip()
        position = str(getattr(role_obj, "position", "") or "").strip()
        if dept and dept != "all":
            profile["role"]["部门"] = dept
        if position:
            profile["role"]["职级"] = position
    if role_name and role_name not in {"operator", "admin", "superuser"}:
        profile["role"]["岗位"] = role_name
    learned_role = facts.get("role")
    if learned_role and learned_role != role_name:
        profile["role"]["岗位"] = learned_role
    dept = facts.get("department")
    if dept and not profile["role"].get("部门"):
        profile["role"]["部门"] = dept

    work_center = str(getattr(user, "work_center", "") or "").strip()
    if work_center:
        profile["work"]["工序组"] = work_center

    prefs = facts.get("preferences")
    if prefs:
        profile["preferences"]["工作偏好"] = prefs
    return profile


def build_memory_block(
    facts: Dict[str, str],
    *,
    profile: Optional[Dict[str, Any]] = None,
    include_guidance: bool = True,
) -> str:
    """把记忆事实拼成可注入 system prompt 的文本块（无事实则返回空串）。

    注入结构：画像(身份/岗位/部门) → 用户偏好 → 其他事实 → 个性化指引。
    """
    if not facts and not profile:
        return ""
    lines: List[str] = []
    if profile:
        identity = profile.get("identity") or {}
        role = profile.get("role") or {}
        work = profile.get("work") or {}
        parts: List[str] = []
        for item in (identity, role, work):
            for k, v in item.items():
                parts.append(f"{k}：{v}")
        if parts:
            lines.append("- " + "；".join(parts))
    prefs = facts.get("preferences")
    if prefs:
        lines.append(f"- 工作偏好：{prefs}")
    other_keys = {"display_name", "full_name", "role", "department", "preferences", "work_center", "username"}
    other = {k: v for k, v in facts.items() if k not in other_keys}
    for key, value in other.items():
        lines.append(f"- {key}：{value}")
    if not lines:
        return ""
    header = CROSS_SESSION_SYSTEM_GUIDANCE if include_guidance else "【用户长期记忆】"
    block = header + "\n" + "\n".join(lines) + "\n"
    if include_guidance:
        block += "\n" + PERSONALIZATION_MEMORY_GUIDANCE + "\n"
    return block


# ──────────────────────────────────────────────
# 写侧安全闸门（参照 luaguage chat_memory_security）
# ──────────────────────────────────────────────

_CREDENTIAL_RE = [
    re.compile(r"(?i)\bapi[_-]?key\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(secret|password|passwd|pwd)\b\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)\b(?:mongodb(?:\+srv)?|postgres(?:ql)?|redis|mysql)://[^\s]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}"),
]
_SHELL_RE = [
    re.compile(r"(?i)\brm\s+-rf\b"),
    re.compile(r"(?i)\bsudo\s+"),
    re.compile(r"(?i)\bbash\s+-c\b"),
    re.compile(r"(?i)\bsh\s+-c\b"),
    re.compile(r"(?i)\beval\s*\("),
]
# 敏感信息意图：用户让 bot「记住密码/账号/卡号/身份证」等 → 直接不落库
_SENSITIVE_INTENT_RE = [
    re.compile(r"(记住|记下|保存|存储)(我的|一下|这个)?(密码|口令|账号|密码是|api\s*key|密钥|卡号|身份证号|验证码)", re.I),
    re.compile(r"(密码|口令|密钥|验证码|身份证号)\s*(是|为|：|:)\s*\S+", re.I),
    re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key)\b"),
]
_INJECTION_RE = [
    re.compile(r"(?i)\bignore (all |any |the )?(previous|prior|above|earlier) (instructions?|prompts?|rules?)"),
    re.compile(r"(?i)\bdisregard (all |any )?(previous|prior|above) (instructions?|rules?)"),
    re.compile(r"(?i)\byou are now (an? |the |just )?(ai|assistant|agent|gpt|admin|hacker|developer|system)"),
    re.compile(r"忽略(之前|以前|上面|所有)(的)?(指令|提示|规则|要求)"),
    re.compile(r"不要(遵循|遵守|理会)(之前|以前)(的)?(指令|规则|要求)"),
    re.compile(r"你现在是(一个|一名)?(ai|人工智能|助手|机器人|黑客|管理员|系统)"),
    re.compile(r"重新(设定|定义|设置)(你的)?(角色|指令|规则|系统提示)"),
]
HARD_BLOCK_PATTERNS = _CREDENTIAL_RE + _SHELL_RE + _SENSITIVE_INTENT_RE
SANITIZE_PATTERNS = _INJECTION_RE
_REDACTED = "[已过滤]"


def scan_memory_content(text: str) -> Dict[str, Any]:
    """扫描记忆内容：硬拦截类（凭据/命令/敏感意图）与消毒类（注入标记）。"""
    blob = str(text or "")
    if not blob:
        return {"blocked": False, "hard_categories": [], "sanitize_hits": []}
    hard: List[str] = []
    for pat in HARD_BLOCK_PATTERNS:
        if pat.search(blob):
            hard.append(pat.pattern)
    sanitize_hits: List[str] = []
    for pat in SANITIZE_PATTERNS:
        if pat.search(blob):
            sanitize_hits.append(pat.pattern)
    return {
        "blocked": bool(hard),
        "hard_categories": hard[:3],
        "sanitize_hits": sanitize_hits[:3],
    }


def sanitize_memory_text(text: str) -> str:
    """消毒注入标记（替换为 [已过滤]），硬拦截内容不在此处理。"""
    blob = str(text or "")
    for pat in SANITIZE_PATTERNS:
        blob = pat.sub(_REDACTED, blob)
    return blob


def should_persist_text(text: str) -> bool:
    """写侧闸门：内容含凭据/命令类信息时不落库。"""
    return not scan_memory_content(text)["blocked"]


# ──────────────────────────────────────────────
# 写入
# ──────────────────────────────────────────────

async def remember(
    db: AsyncSession,
    *,
    user_id: str,
    key: str,
    value: str,
    factory_id: Optional[str] = None,
    confidence: int = 2,
    source: str = "chat",
) -> bool:
    """写入（或覆盖）一条记忆。返回是否发生写入。写侧安全闸门在此拦截。"""
    value = str(value or "").strip()
    if not value:
        return False
    scan = scan_memory_content(value)
    if scan["blocked"]:
        return False
    if scan["sanitize_hits"]:
        value = sanitize_memory_text(value)
        if not value.strip():
            return False
    stmt = select(ChatMemory).where(
        ChatMemory.user_id == user_id,
        ChatMemory.key == key,
    )
    if factory_id:
        stmt = stmt.where(ChatMemory.factory_id == factory_id)
    row = (await db.execute(stmt)).scalars().first()
    now = datetime.utcnow()
    if row:
        if str(row.value or "").strip() == value:
            return False
        row.value = value
        row.confidence = confidence
        row.source = source
        row.updated_at = now
    else:
        db.add(ChatMemory(
            id=generate_uuid(),
            user_id=user_id,
            factory_id=factory_id,
            key=key,
            value=value,
            confidence=confidence,
            source=source,
            created_at=now,
            updated_at=now,
        ))
    return True


async def forget(db: AsyncSession, *, user_id: str, key: str) -> None:
    """删除一条记忆。"""
    stmt = delete(ChatMemory).where(
        ChatMemory.user_id == user_id,
        ChatMemory.key == key,
    )
    await db.execute(stmt)


# ──────────────────────────────────────────────
# 规则提取（从用户消息里识别可记住的事实）
# ──────────────────────────────────────────────

_NAME_RE = re.compile(
    r"(?:我叫|名字是|名字叫|称呼我|请叫我|我是|可以叫我|我叫作)[\s\uff1a:，,]*"
    r"([\u4e00-\u9fa5A-Za-z0-9·．.]{2,20})"
)
# 剔除口语连接词，避免把「是陈小明」「叫陈小明」「作张伟」整段当名字；词尾去语气词
_NAME_STRIP_LEAD = re.compile(r"^[是叫叫做为的就是作]+")
_NAME_STRIP_TAIL = re.compile(r"[吧啊哈呀哦]$")
# 疑问词守卫：捕获到「你记得吗/叫什么」这类提问片段时视为非名字
_QUESTION_MARKERS = ("吗", "谁", "什么", "记得", "忘了", "么", "啥")


# 岗位/角色词尾：这些词后面再匹配名字会误把岗位当名字 → 名字守卫
_ROLE_SUFFIXES = ("计划员", "调度员", "主管", "经理", "专员", "班长", "组长",
                  "厂长", "文员", "操作员", "仓管", "检验员", "质检员", "工艺员",
                  "工程师", "主任", "科长", "课长", "部长", "干事", "管理员")
# 部门符号：X部/X科/X课/X中心 → 名字在「我是X」后不应是部门
_DEPT_SUFFIXES = ("部", "科", "课", "中心")


def _is_roleish(name: str) -> bool:
    return any(name.endswith(sfx) for sfx in _ROLE_SUFFIXES) or (
        len(name) >= 2 and name.endswith(_DEPT_SUFFIXES)
    )


def _clean_name(raw: str) -> str:
    name = raw.strip()
    name = _NAME_STRIP_LEAD.sub("", name).strip()
    name = _NAME_STRIP_TAIL.sub("", name).strip()
    if any(marker in name for marker in _QUESTION_MARKERS):
        return ""
    if _is_roleish(name):
        return ""
    return name if len(name) >= 2 else ""


_FULL_NAME_RE = re.compile(
    r"(?:我的名字|我的全名|全名是|姓名为|我的姓名)[\s\uff1a:，,]*"
    r"([\u4e00-\u9fa5A-Za-z0-9·．.]{2,20})"
)

# 岗位/角色：我是计划员 / 担任物料主管 / 我的岗位是生产调度
_ROLE_RE = re.compile(
    r"(?:我是|我担任|担任|我负责|负责|我的岗位是|岗位是|我的角色是|我是做)"
    r"[\s\uff1a:，,]*"
    r"([\u4e00-\u9fa5A-Za-z]{2,12}(?:计划|调度|员|主管|经理|工程师|专员|班长|组长|厂长|主管|经理|文员|操作员|仓管|检验员|质检员|工艺员))"
)
# 部门：我在计划部 / 我是生产部 / 我在物料科
_DEPT_RE = re.compile(
    r"(?:我在|我是|属于|属于的部门是|部门是|在|负责)"
    r"[\s\uff1a:，,]*"
    r"([\u4e00-\u9fa5]{2,6}部|[\u4e00-\u9fa5]{2,6}科|[\u4e00-\u9fa5]{2,6}课|[\u4e00-\u9fa5]{2,6}中心)"
)
# 偏好：以后都简洁 / 用表格 / 详细一点 / 简要说重点
_PREF_RE = re.compile(
    r"(?:以后|平时|请|希望|尽量|每次)?"
    r"(?:都用|用|要|请|希望|尽量|以后)"
    r"[\s\uff1a:，,]*"
    r"(表格|简洁|简练|详细|重点|中文|英文|精炼|简短|完整|结构化|优先用表)"
)
_PREF_FULL_RE = re.compile(
    r"(?:以后|我希望|请)(都|尽量)?"
    r"[\s\uff1a:，,]*"
    r"([\u4e00-\u9fa5A-Za-z0-9·．,，]{2,30}(?:回答|回复|汇报|展示|说明|总结))"
)

_PREF_KEYWORDS = ("简洁", "简练", "简短", "详细", "表格", "精炼", "重点", "中文", "英文", "结构化")


def _clean_role(raw: str) -> str:
    value = raw.strip()
    if any(m in value for m in _QUESTION_MARKERS):
        return ""
    return value if len(value) >= 2 else ""


def learn_from_text(text: str) -> List[Dict[str, Any]]:
    """从一条用户消息中提取可记忆事实，返回 [{key, value, confidence}]。

    只提取明确告知，不做猜测；对「我是谁？」「你记得我吗」类提问返回空。
    支持：名字 / 岗位 / 部门 / 偏好。
    """
    if not text:
        return []
    facts: List[Dict[str, Any]] = []
    # 名字
    for regex in (_FULL_NAME_RE, _NAME_RE):
        m = regex.search(text)
        if m:
            name = _clean_name(m.group(1))
            if name and len(name) >= 2:
                facts.append({"key": "display_name", "value": name, "confidence": 2})
            break
    # 岗位
    m = _ROLE_RE.search(text)
    if m:
        role = _clean_role(m.group(1))
        if role:
            facts.append({"key": "role", "value": role, "confidence": 2})
    # 部门
    m = _DEPT_RE.search(text)
    if m:
        dept = _clean_role(m.group(1))
        if dept and "部" in dept:
            facts.append({"key": "department", "value": dept, "confidence": 2})
    # 偏好：先整句，再短词
    m = _PREF_FULL_RE.search(text)
    if m:
        pref = _clean_role(m.group(2))
        if pref:
            facts.append({"key": "preferences", "value": pref, "confidence": 2})
    else:
        m = _PREF_RE.search(text)
        if m:
            pref = _clean_role(m.group(1))
            if pref:
                facts.append({"key": "preferences", "value": f"偏好{pref}", "confidence": 2})
    return facts


def memory_from_user_row(user: Any, role_obj: Any = None) -> Dict[str, str]:
    """用 User 记录兜底：用户没告诉名字时，至少记住工号/全名。"""
    facts: Dict[str, str] = {}
    full = str(getattr(user, "full_name", "") or "").strip()
    if full:
        facts["full_name"] = full
    username = str(getattr(user, "username", "") or "").strip()
    if username:
        facts["username"] = username
    role = str(getattr(user, "role", "") or "").strip()
    if role_obj is not None:
        role = str(getattr(role_obj, "role_name", "") or role).strip()
    if role and role not in {"operator", "admin", "superuser"}:
        facts["role"] = role
    dept = str(getattr(role_obj, "department", "") or "").strip() if role_obj is not None else ""
    if dept and dept != "all":
        facts["department"] = dept
    return facts
