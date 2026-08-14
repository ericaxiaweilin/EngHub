"""Chat 用户长期记忆服务（跨会话）。

基于 Harness Kernel 架构：请求前置入记忆块（system prompt 头部），请求结束
后从用户消息规则提取新事实落库。规则提取不消耗额外 LLM 调用，保证可靠与低成本。

事实 key 约定：
  display_name  用户希望被称呼的名字/昵称（来源：用户明确告知）
  full_name     用户全名（来源：User.full_name 兜底）
  role          岗位/角色
  preferences   一句话工作偏好（可选）
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ChatMemory, generate_uuid


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


def build_memory_block(facts: Dict[str, str]) -> str:
    """把记忆事实拼成可注入 system prompt 的文本块（无事实则返回空串）。"""
    if not facts:
        return ""
    lines = []
    display = facts.get("display_name")
    if display:
        lines.append(f"- 当前用户希望被称呼为：{display}")
    full = facts.get("full_name")
    if full and full != display:
        lines.append(f"- 用户全名：{full}")
    role = facts.get("role")
    if role:
        lines.append(f"- 用户岗位：{role}")
    prefs = facts.get("preferences")
    if prefs:
        lines.append(f"- 用户偏好：{prefs}")
    other = {k: v for k, v in facts.items() if k not in {"display_name", "full_name", "role", "preferences"}}
    for key, value in other.items():
        lines.append(f"- {key}：{value}")
    if not lines:
        return ""
    return "【用户长期记忆】以下是此前对话中已记住的关于当前用户的事实，回答时请自然引用（例如称呼其姓名），不要复述\"记忆\"二字：\n" + "\n".join(lines) + "\n"


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
    """写入（或覆盖）一条记忆。返回是否发生写入。"""
    value = str(value or "").strip()
    if not value:
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


def _clean_name(raw: str) -> str:
    name = raw.strip()
    name = _NAME_STRIP_LEAD.sub("", name).strip()
    name = _NAME_STRIP_TAIL.sub("", name).strip()
    if any(marker in name for marker in _QUESTION_MARKERS):
        return ""
    return name if len(name) >= 2 else ""


_FULL_NAME_RE = re.compile(
    r"(?:我的名字|我的全名|全名是|姓名为|我的姓名)[\s\uff1a:，,]*"
    r"([\u4e00-\u9fa5A-Za-z0-9·．.]{2,20})"
)


def learn_from_text(text: str) -> List[Dict[str, Any]]:
    """从一条用户消息中提取可记忆事实，返回 [{key, value, confidence}]。

    规则：名字的多种口语表达（我叫X / 我是X / 请叫我X / 我的名字X）。
    只提取明确告知，不做猜测；对「我是谁？」「你记得我吗」类提问返回空。
    """
    if not text:
        return []
    facts: List[Dict[str, Any]] = []
    for regex in (_FULL_NAME_RE, _NAME_RE):
        m = regex.search(text)
        if m:
            name = _clean_name(m.group(1))
            if name and len(name) >= 2:
                facts.append({"key": "display_name", "value": name, "confidence": 2})
                break
    return facts


def memory_from_user_row(user: Any) -> Dict[str, str]:
    """用 User 记录兜底：用户没告诉名字时，至少记住工号/全名。"""
    facts: Dict[str, str] = {}
    full = str(getattr(user, "full_name", "") or "").strip()
    if full:
        facts["full_name"] = full
    username = str(getattr(user, "username", "") or "").strip()
    if username:
        facts["工号"] = username
    role = str(getattr(user, "role", "") or "").strip()
    if role and role not in {"operator", "admin", "superuser"}:
        facts["role"] = role
    return facts
