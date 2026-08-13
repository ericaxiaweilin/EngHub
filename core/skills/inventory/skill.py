"""Inventory Skill - 库存域。

当前完全迁移：query_inventory
未迁移：query_stagnant（返回 LEGACY_FALLBACK → 调用方回退到 chat_tools_service）

exec 注入由调用方传入（传入 self.execute 或签名兼容函数）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from core.skills.base import BaseSkill
from core.skills.registry import LEGACY_FALLBACK
from core.skills.work_order.skill import _td


class InventorySkill(BaseSkill):
    """库存域技能。"""

    def __init__(self, exec_impl: Optional[Callable[..., Any]] = None) -> None:
        # exec_impl: 可选注入的 legacy 执行函数（签名同 chat_tools_service.execute_tool）
        self._exec_impl = exec_impl

    @property
    def name(self) -> str:
        return "inventory"

    @property
    def module(self) -> str:
        return "inventory"

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            _td(
                "query_inventory",
                "查询库存，支持按物料编码/名称关键词过滤，返回可用量与总量",
                {
                    "material_keyword": {"type": "string", "description": "物料关键词"},
                    "factory_id": {"type": "string", "description": "工厂ID"},
                    "limit": {"type": "integer", "description": "返回数量上限"},
                },
            ),
            _td(
                "query_stagnant",
                "查询滞呆料（超过给定天数无出入库的物料）",
                {
                    "days": {"type": "integer", "description": "滞呆天数阈值，默认180"},
                    "factory_id": {"type": "string", "description": "工厂ID"},
                    "limit": {"type": "integer", "description": "返回数量上限"},
                },
            ),
        ]

    async def execute(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        db: Any = None,
        operator: str = "ai_assistant",
        factory_id: Optional[str] = None,
        ctx: Any = None,
    ) -> Dict[str, Any]:
        if tool_name == "query_inventory":
            return await self._query_inventory(
                db, args, factory_id=factory_id,
                operator=operator,
            )
        if tool_name == "query_stagnant":
            # 未迁移：交给 legacy，保持行为零漂移
            if self._exec_impl is not None:
                return await self._exec_impl(
                    db, "query_stagnant", args,
                    operator=operator, factory_id=factory_id,
                )
            return dict(LEGACY_FALLBACK)
        return {"error": f"inventory skill 未实现工具：{tool_name}"}

    async def _query_inventory(
        self, db, args: Dict[str, Any], *, factory_id: Optional[str], operator: str,
    ) -> Dict[str, Any]:
        """查询库存（对齐旧版 chat_tools_service._tool_query_inventory 行为）。"""
        from sqlalchemy import select

        from database.models import Inventory

        limit = min(int(args.get("limit") or 10), 50)
        fid = args.get("factory_id") or factory_id

        stmt = select(Inventory).order_by(Inventory.updated_at.desc()).limit(limit)
        if fid:
            stmt = stmt.where(Inventory.factory_id == fid)
        kw = args.get("material_keyword")
        if kw and kw.strip():
            kw = kw.strip()
            stmt = stmt.where(
                (Inventory.material_code.ilike(f"%{kw}%"))
                | (Inventory.material_id.ilike(f"%{kw}%"))
            )
        rows = (await db.execute(stmt)).scalars().all()
        items = [
            {
                "material_id": inv.material_id,
                "material_code": inv.material_code,
                "warehouse_id": inv.warehouse_id,
                "batch_code": inv.batch_code,
                "total_qty": inv.total_qty,
                "available_qty": inv.available_qty,
                "reserved_qty": inv.reserved_qty,
                "status": inv.status,
            }
            for inv in rows
        ]
        return {"count": len(items), "inventory": items}


SKILL = InventorySkill()


def build_skill() -> BaseSkill:
    return InventorySkill()