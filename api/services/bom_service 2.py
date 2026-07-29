"""
BOM Query Service - BOM 树形浏览、物料搜索、工单关联、版本对比
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy import select, func, or_, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import EngHubBomItem

logger = logging.getLogger(__name__)


class BomService:
    """BOM 查询服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_models(self) -> List[Dict[str, Any]]:
        """获取所有已同步的产品型号列表（含物料数量统计）"""
        result = await self.db.execute(
            select(
                EngHubBomItem.product_model,
                func.count(EngHubBomItem.id).label("item_count"),
                func.max(EngHubBomItem.synced_at).label("last_synced"),
            )
            .where(EngHubBomItem.product_model.isnot(None))
            .group_by(EngHubBomItem.product_model)
            .order_by(func.count(EngHubBomItem.id).desc())
        )
        rows = result.all()
        return [
            {
                "model_name": row.product_model,
                "item_count": row.item_count,
                "last_synced": row.last_synced.isoformat() if row.last_synced else None,
            }
            for row in rows
        ]

    async def get_bom_tree(self, model_name: str, max_level: int = 10) -> Dict[str, Any]:
        """递归展开多级 BOM 树"""
        result = await self.db.execute(
            select(EngHubBomItem)
            .where(EngHubBomItem.product_model == model_name)
            .order_by(EngHubBomItem.level, EngHubBomItem.part_number)
        )
        items = result.scalars().all()

        if not items:
            return {"model_name": model_name, "tree": [], "total_items": 0}

        # 构建树结构
        item_dicts = [self._item_to_dict(item) for item in items]
        tree = self._build_tree(item_dicts)

        return {
            "model_name": model_name,
            "tree": tree,
            "total_items": len(item_dicts),
            "max_level": max(i["level"] or 0 for i in item_dicts),
        }

    async def search_materials(
        self,
        keyword: str,
        model_name: Optional[str] = None,
        category_l1: Optional[str] = None,
        component_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """物料搜索"""
        conditions = [
            or_(
                EngHubBomItem.part_number.ilike(f"%{keyword}%"),
                EngHubBomItem.description.ilike(f"%{keyword}%"),
            )
        ]
        if model_name:
            conditions.append(EngHubBomItem.product_model == model_name)
        if category_l1:
            conditions.append(EngHubBomItem.category_l1 == category_l1)
        if component_type:
            conditions.append(EngHubBomItem.component_type == component_type)

        # 总数
        count_result = await self.db.execute(
            select(func.count(EngHubBomItem.id)).where(*conditions)
        )
        total = count_result.scalar() or 0

        # 分页查询
        result = await self.db.execute(
            select(EngHubBomItem)
            .where(*conditions)
            .order_by(EngHubBomItem.product_model, EngHubBomItem.level)
            .limit(limit)
            .offset(offset)
        )
        items = result.scalars().all()

        return {
            "total": total,
            "items": [self._item_to_dict(i) for i in items],
            "limit": limit,
            "offset": offset,
        }

    async def get_material_detail(self, part_number: str) -> Dict[str, Any]:
        """物料详情（含使用该物料的所有产品）"""
        result = await self.db.execute(
            select(EngHubBomItem)
            .where(EngHubBomItem.part_number == part_number)
            .order_by(EngHubBomItem.product_model)
        )
        items = result.scalars().all()

        if not items:
            return {"part_number": part_number, "found": False, "usages": []}

        # 取第一条作为主信息
        primary = items[0]
        used_in_models = list(set(i.product_model for i in items if i.product_model))

        return {
            "part_number": part_number,
            "found": True,
            "description": primary.description,
            "category_l1": primary.category_l1,
            "category_l2": primary.category_l2,
            "material_family": primary.material_family,
            "component_type": primary.component_type,
            "unit": primary.unit,
            "unit_price": primary.unit_price,
            "vendor_code": primary.vendor_code,
            "vendor_name": primary.vendor_name,
            "used_in_models": used_in_models,
            "usage_count": len(used_in_models),
        }

    async def get_bom_for_work_order(self, work_order_id: str) -> Dict[str, Any]:
        """根据工单关联 BOM（通过 product_id 匹配 model_name）"""
        from database.models import WorkOrder

        # 查工单获取 product_id
        result = await self.db.execute(
            select(WorkOrder).where(WorkOrder.id == work_order_id)
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return {"work_order_id": work_order_id, "found": False, "bom_items": []}

        product_id = wo.product_id
        # 用 product_id 匹配 BOM（可能是 model_name 或 product_sap_code）
        bom_result = await self.db.execute(
            select(EngHubBomItem)
            .where(
                or_(
                    EngHubBomItem.product_model == product_id,
                    EngHubBomItem.part_number == product_id,
                )
            )
            .order_by(EngHubBomItem.level)
        )
        bom_items = bom_result.scalars().all()

        # 计算物料总成本
        total_cost = sum((i.total_cost or 0) * (i.quantity or 1) for i in bom_items)

        return {
            "work_order_id": work_order_id,
            "product_id": product_id,
            "found": len(bom_items) > 0,
            "bom_items": [self._item_to_dict(i) for i in bom_items],
            "total_material_cost": round(total_cost, 2),
            "item_count": len(bom_items),
        }

    async def compare_bom(
        self, model_name: str, date_a: str, date_b: str
    ) -> Dict[str, Any]:
        """对比两个时间点的 BOM 快照差异"""
        from datetime import date as date_type

        try:
            da = datetime.fromisoformat(date_a)
            db_date = datetime.fromisoformat(date_b)
        except ValueError:
            return {"error": "Invalid date format. Use ISO format: YYYY-MM-DD"}

        # 获取两个时间点存在的物料
        result_a = await self.db.execute(
            select(EngHubBomItem.part_number, EngHubBomItem.quantity, EngHubBomItem.unit_price)
            .where(
                EngHubBomItem.product_model == model_name,
                EngHubBomItem.synced_at <= da,
            )
        )
        items_a = {row[0]: {"quantity": row[1], "unit_price": row[2]} for row in result_a.all()}

        result_b = await self.db.execute(
            select(EngHubBomItem.part_number, EngHubBomItem.quantity, EngHubBomItem.unit_price)
            .where(
                EngHubBomItem.product_model == model_name,
                EngHubBomItem.synced_at <= db_date,
            )
        )
        items_b = {row[0]: {"quantity": row[1], "unit_price": row[2]} for row in result_b.all()}

        # 计算差异
        added = [pn for pn in items_b if pn not in items_a]
        removed = [pn for pn in items_a if pn not in items_b]
        changed = []
        for pn in items_a:
            if pn in items_b:
                if items_a[pn]["quantity"] != items_b[pn]["quantity"] or items_a[pn]["unit_price"] != items_b[pn]["unit_price"]:
                    changed.append({
                        "part_number": pn,
                        "before": items_a[pn],
                        "after": items_b[pn],
                    })

        return {
            "model_name": model_name,
            "date_a": date_a,
            "date_b": date_b,
            "summary": {
                "added_count": len(added),
                "removed_count": len(removed),
                "changed_count": len(changed),
            },
            "added": added[:100],
            "removed": removed[:100],
            "changed": changed[:100],
        }

    def _build_tree(self, items: List[Dict]) -> List[Dict]:
        """将扁平 BOM 列表构建为树结构"""
        # 按 parent_part 分组
        children_map: Dict[str, List[Dict]] = {}
        roots = []

        for item in items:
            parent = item.get("parent_part")
            if parent and parent != item["part_number"]:
                children_map.setdefault(parent, []).append(item)
            else:
                roots.append(item)

        # 如果没有明确的根节点，取 level 最小的
        if not roots:
            min_level = min((i["level"] or 0) for i in items)
            roots = [i for i in items if (i["level"] or 0) == min_level]

        # 递归挂载子节点
        def attach_children(node):
            pn = node["part_number"]
            if pn in children_map:
                node["children"] = children_map[pn]
                for child in node["children"]:
                    attach_children(child)
            else:
                node["children"] = []
            return node

        return [attach_children(r) for r in roots[:200]]  # 限制根节点数量

    @staticmethod
    def _item_to_dict(item: EngHubBomItem) -> Dict[str, Any]:
        return {
            "id": item.id,
            "source_row_id": item.source_row_id,
            "product_model": item.product_model,
            "part_number": item.part_number,
            "description": item.description,
            "level": item.level,
            "quantity": item.quantity,
            "unit": item.unit,
            "unit_price": item.unit_price,
            "total_cost": item.total_cost,
            "vendor_code": item.vendor_code,
            "vendor_name": item.vendor_name,
            "parent_part": item.parent_part,
            "category_l1": item.category_l1,
            "category_l2": item.category_l2,
            "material_family": item.material_family,
            "component_type": item.component_type,
        }
