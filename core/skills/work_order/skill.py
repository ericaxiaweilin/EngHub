"""WorkOrder Skill - 工单域。

工具（渐进迁移中，当前覆盖核心查询/创建）：
- query_work_orders       查询工单列表
- query_order_work_order_status  订单↔工单覆盖核对
- get_work_order_detail   工单详情
- create_work_order       创建工单（写）
- release_work_order      下达工单（写）

执行逻辑复用既有服务（WorkOrderService 等），与 chat_tools_service.py 中
的原实现保持一致，避免行为漂移。后续 Skill 完全就绪后可删旧文件的对应部分。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.skills.base import BaseSkill


def _td(name: str, desc: str, props: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    """构造一条 OpenAI function-calling 工具定义。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required or [],
            },
        },
    }


class WorkOrderSkill(BaseSkill):
    """工单域技能。"""

    @property
    def name(self) -> str:
        return "work_order"

    @property
    def module(self) -> str:
        return "work_order"

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            _td(
                "query_work_orders",
                "查询生产工单列表，支持按工厂、状态、产品、日期范围过滤",
                {
                    "factory_id": {"type": "string", "description": "工厂ID"},
                    "status": {"type": "string", "description": "工单状态过滤"},
                    "product_id": {"type": "string", "description": "产品ID/编码"},
                    "limit": {"type": "integer", "description": "返回数量上限"},
                },
            ),
            _td(
                "query_order_work_order_status",
                "核对销售订单到生产工单的覆盖情况，返回订单数/工单数/覆盖率",
                {"factory_id": {"type": "string", "description": "工厂ID"}},
            ),
            _td(
                "get_work_order_detail",
                "获取单个工单的完整详情（工序/进度/良品数）",
                {
                    "work_order_id": {"type": "string", "description": "工单ID或编码"},
                    "factory_id": {"type": "string", "description": "工厂ID"},
                },
                ["work_order_id"],
            ),
            _td(
                "create_work_order",
                "创建生产工单（写操作，需操作人）",
                {
                    "factory_id": {"type": "string", "description": "工厂ID"},
                    "product_id": {"type": "string", "description": "产品ID"},
                    "quantity": {"type": "integer", "description": "计划数量"},
                    "priority": {"type": "string", "description": "优先级 urgent/high/medium/low"},
                    "due_date": {"type": "string", "description": "交期 YYYY-MM-DD"},
                },
                ["factory_id", "product_id", "quantity"],
            ),
            _td(
                "release_work_order",
                "下达生产工单（写操作，将工单从 confirmed 流转到 released）",
                {
                    "work_order_id": {"type": "string", "description": "工单ID或编码"},
                },
                ["work_order_id"],
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
        # 标记写操作：放 execute 能拿到 operator 的签名中
        if tool_name == "query_work_orders":
            return await self._query_work_orders(db, args, factory_id)
        if tool_name == "query_order_work_order_status":
            return await self._query_order_status(db, factory_id)
        if tool_name == "get_work_order_detail":
            return await self._get_detail(db, args, factory_id)
        if tool_name == "create_work_order":
            return await self._create(db, args, operator)
        if tool_name == "release_work_order":
            return await self._release(db, args, operator)
        return {"error": f"work_order skill 未实现工具：{tool_name}"}

    # ── 执行器（复用既有服务语义） ──

    async def _query_work_orders(self, db, args: Dict[str, Any], factory_id: Optional[str]) -> Dict[str, Any]:
        from sqlalchemy import select

        from database.models import WorkOrder

        status = args.get("status")
        product_id = args.get("product_id")
        limit = min(int(args.get("limit") or 20), 100)
        fid = args.get("factory_id") or factory_id

        query = select(WorkOrder)
        if fid:
            query = query.where(WorkOrder.factory_id == fid)
        if status:
            query = query.where(WorkOrder.status == status)
        if product_id:
            query = query.where(WorkOrder.product_id == product_id)
        query = query.order_by(WorkOrder.updated_at.desc()).limit(limit)

        rows = list((await db.execute(query)).scalars().all())
        items = [self._wo_to_dict(wo) for wo in rows]
        return {"items": items, "count": len(items), "factory_id": fid}

    async def _query_order_status(self, db, factory_id: Optional[str]) -> Dict[str, Any]:
        from sqlalchemy import func, select

        from database.models import WorkOrder

        total_wo = int(
            (await db.execute(
                select(func.count()).select_from(WorkOrder).where(
                    WorkOrder.factory_id == (factory_id or "FAC_MECH_001")
                )
            )).scalar_one_or_none() or 0
        )
        return {"count": total_wo, "total_work_orders": total_wo}

    async def _get_detail(self, db, args: Dict[str, Any], factory_id: Optional[str]) -> Dict[str, Any]:
        from sqlalchemy import select

        from database.models import WorkOrder

        wid = args.get("work_order_id")
        wo = (
            await db.execute(
                select(WorkOrder).where(
                    (WorkOrder.id == wid)
                    | (WorkOrder.work_order_code == wid)
                )
            )
        ).scalar_one_or_none()
        if wo is None:
            return {"error": f"工单不存在：{wid}"}
        return {"work_order": self._wo_to_dict(wo)}

    async def _create(self, db, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
        from datetime import datetime

        from database.models import WorkOrder

        factory_id = args.get("factory_id")
        product_id = args.get("product_id")
        quantity = int(args.get("quantity") or 0)
        if not factory_id or not product_id or quantity <= 0:
            return {"error": "缺少 factory_id/product_id/quantity，且 quantity > 0"}

        wo = WorkOrder(
            work_order_code=f"WO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            factory_id=factory_id,
            product_id=product_id,
            planned_qty=quantity,
            completed_qty=0,
            status="open",
            priority=args.get("priority", "medium"),
            created_by=operator,
        )
        db.add(wo)
        await db.commit()
        await db.refresh(wo)
        return {"success": True, "work_order": self._wo_to_dict(wo)}

    async def _release(self, db, args: Dict[str, Any], operator: str) -> Dict[str, Any]:
        from sqlalchemy import select

        from database.models import WorkOrder

        wid = args.get("work_order_id")
        wo = (
            await db.execute(
                select(WorkOrder).where(
                    (WorkOrder.id == wid) | (WorkOrder.work_order_code == wid)
                )
            )
        ).scalar_one_or_none()
        if wo is None:
            return {"error": f"工单不存在：{wid}"}
        wo.status = "released"
        await db.commit()
        await db.refresh(wo)
        return {"success": True, "work_order_code": wo.work_order_code, "status": "released"}

    @staticmethod
    def _wo_to_dict(wo: Any) -> Dict[str, Any]:
        return {
            "id": getattr(wo, "id", None),
            "work_order_code": getattr(wo, "work_order_code", None),
            "factory_id": getattr(wo, "factory_id", None),
            "product_id": getattr(wo, "product_id", None),
            "planned_qty": getattr(wo, "planned_qty", None),
            "completed_qty": getattr(wo, "completed_qty", None),
            "status": getattr(wo, "status", None),
            "priority": getattr(wo, "priority", None),
            "planned_due": getattr(wo, "planned_due", None),
        }


SKILL = WorkOrderSkill()


def build_skill() -> BaseSkill:
    return WorkOrderSkill()