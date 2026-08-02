"""
Code Table Service - 统一码表/基础数据管理服务
==============================================
提供码表的 CRUD + 按分类查询 + 内存缓存（减少高频查询的 DB 压力）。
缓存策略：进程级 dict，TTL 5 分钟；写操作后主动失效。
"""

import time
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func

from database.models import CodeTable

# ============================================================
# 进程级缓存（单 worker 场景足够；多 worker 可换 Redis）
# ============================================================
_cache: Dict[str, Any] = {}
_CACHE_TTL = 300  # 5 分钟


def _cache_key(category: str, factory_id: Optional[str] = None) -> str:
    return f"{category}:{factory_id or '__global__'}"


def invalidate_cache(category: Optional[str] = None):
    """失效缓存。category=None 时清空全部。"""
    if category is None:
        _cache.clear()
    else:
        keys_to_del = [k for k in _cache if k.startswith(f"{category}:")]
        for k in keys_to_del:
            del _cache[k]


class CodeTableService:
    """统一码表 CRUD 服务"""

    def __init__(self, db):
        self.db = db

    # ----------------------------------------------------------
    # 查询
    # ----------------------------------------------------------

    async def list_by_category(
        self, category: str, factory_id: Optional[str] = None, include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        """按分类获取码表（优先走缓存）。
        factory_id 非空时：返回全局 + 该工厂专属条目。
        """
        ck = _cache_key(category, factory_id)
        now = time.time()
        if ck in _cache and (now - _cache[ck]["ts"]) < _CACHE_TTL and not include_inactive:
            return _cache[ck]["data"]

        stmt = select(CodeTable).where(CodeTable.category == category)
        if factory_id:
            stmt = stmt.where(
                (CodeTable.factory_id == None) | (CodeTable.factory_id == factory_id)  # noqa: E711
            )
        if not include_inactive:
            stmt = stmt.where(CodeTable.is_active == True)  # noqa: E712
        stmt = stmt.order_by(CodeTable.sort_order, CodeTable.code)

        rows = (await self.db.execute(stmt)).scalars().all()
        data = [r.to_dict() for r in rows]

        if not include_inactive:
            _cache[ck] = {"data": data, "ts": now}
        return data

    async def list_categories(self) -> List[Dict[str, Any]]:
        """获取所有码表分类及条目数（供设置页面 Tab 列表）。"""
        stmt = (
            select(CodeTable.category, func.count(CodeTable.id).label("count"))
            .group_by(CodeTable.category)
            .order_by(CodeTable.category)
        )
        rows = (await self.db.execute(stmt)).all()
        return [{"category": r.category, "count": r.count} for r in rows]

    async def get_by_code(self, category: str, code: str) -> Optional[CodeTable]:
        stmt = select(CodeTable).where(
            CodeTable.category == category, CodeTable.code == code
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    # ----------------------------------------------------------
    # 新增
    # ----------------------------------------------------------

    async def create(
        self,
        category: str,
        code: str,
        name: str,
        name_en: Optional[str] = None,
        description: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        extra: Optional[Dict] = None,
        sort_order: int = 0,
        factory_id: Optional[str] = None,
    ) -> CodeTable:
        """新增码表条目（用户自定义，is_system=False）。"""
        existing = await self.get_by_code(category, code)
        if existing:
            raise ValueError(f"[{category}] 编码 '{code}' 已存在")

        item = CodeTable(
            id=str(uuid.uuid4()),
            category=category,
            code=code.upper() if category == "process_code" else code,
            name=name,
            name_en=name_en,
            description=description,
            keywords=keywords,
            extra=extra,
            sort_order=sort_order,
            is_active=True,
            is_system=False,
            factory_id=factory_id,
        )
        self.db.add(item)
        await self.db.flush()
        invalidate_cache(category)
        return item

    # ----------------------------------------------------------
    # 更新
    # ----------------------------------------------------------

    async def update(self, item_id: str, **fields) -> CodeTable:
        """更新码表条目（系统内置条目可改名/排序/停用，不可改 code）。"""
        stmt = select(CodeTable).where(CodeTable.id == item_id)
        item = (await self.db.execute(stmt)).scalar_one_or_none()
        if not item:
            raise ValueError("码表条目不存在")

        allowed = {"name", "name_en", "description", "keywords", "extra", "sort_order", "is_active", "factory_id"}
        # 非系统条目允许改 code
        if not item.is_system:
            allowed.add("code")

        for k, v in fields.items():
            if k in allowed and v is not None:
                setattr(item, k, v)

        await self.db.flush()
        invalidate_cache(item.category)
        return item

    # ----------------------------------------------------------
    # 删除（仅非系统条目）
    # ----------------------------------------------------------

    async def delete(self, item_id: str) -> None:
        stmt = select(CodeTable).where(CodeTable.id == item_id)
        item = (await self.db.execute(stmt)).scalar_one_or_none()
        if not item:
            raise ValueError("码表条目不存在")
        if item.is_system:
            raise ValueError("系统内置条目不可删除，可选择停用")
        category = item.category
        await self.db.delete(item)
        await self.db.flush()
        invalidate_cache(category)

    # ----------------------------------------------------------
    # 供编码模块调用：获取工序代码字典（DB 优先，fallback 硬编码）
    # ----------------------------------------------------------

    async def get_process_codes_dict(self) -> Dict[str, Dict[str, Any]]:
        """返回 {code: {name, en, keywords}} 格式，兼容 work_order_coding 使用。"""
        items = await self.list_by_category("process_code", include_inactive=False)
        result = {}
        for it in items:
            result[it["code"]] = {
                "name": it["name"],
                "en": it.get("name_en") or it["code"],
                "keywords": it.get("keywords") or [],
            }
        return result

    async def get_wo_types_dict(self) -> Dict[str, str]:
        """返回 {code: name} 格式。"""
        items = await self.list_by_category("wo_type", include_inactive=False)
        return {it["code"]: it["name"] for it in items}
