"""
全站系统搜索 API
参考 luaguage site_search_engine 设计：跨模块聚合搜索 + 分类 facets + 排序去重
搜索范围：工单、产品、设备、库存、工位、仓库、员工
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from database.db_config import get_db
from core.auth.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/search", tags=["Global Search"])

# 各模块搜索配置（字段名必须与 DB 实际列名一致，JOIN 用 CAST AS TEXT 兼容 uuid/varchar 混用）
# select: 返回列（避免 SELECT * 导致 JOIN 重复列）; fields: 参与 ILIKE 搜索的列; route: 前端跳转路由
SEARCH_MODULES = [
    {
        "source": "work_order", "label": "工单", "route": "/work-orders",
        "select": "wo.id, wo.work_order_code, wo.status, wo.priority, wo.planned_qty, wo.completed_qty, p.product_name",
        "from": "work_orders wo LEFT JOIN products p ON CAST(wo.product_id AS TEXT) = CAST(p.id AS TEXT)",
        "fields": ["wo.work_order_code", "p.product_name", "wo.status"],
    },
    {
        "source": "product", "label": "产品", "route": "/base-data",
        "select": "id, product_code, product_name, category, unit, status",
        "from": "products",
        "fields": ["product_code", "product_name", "category"],
    },
    {
        "source": "equipment", "label": "设备", "route": "/base-data",
        "select": "id, equipment_code, equipment_name, equipment_type, spec, status",
        "from": "equipment",
        "fields": ["equipment_code", "equipment_name", "spec"],
    },
    {
        "source": "inventory", "label": "库存", "route": "/inventory",
        "select": "i.id, i.material_code, i.batch_code, i.total_qty, i.available_qty, i.status, p.product_name",
        "from": "inventory i LEFT JOIN products p ON CAST(i.material_id AS TEXT) = CAST(p.id AS TEXT)",
        "fields": ["i.material_code", "p.product_name", "i.batch_code"],
    },
    {
        "source": "station", "label": "工位", "route": "/base-data",
        "select": "id, station_code, station_name, station_type, capacity, status",
        "from": "stations",
        "fields": ["station_code", "station_name", "station_type"],
    },
    {
        "source": "warehouse", "label": "仓库", "route": "/warehouses",
        "select": "id, warehouse_code, warehouse_name, warehouse_type, status",
        "from": "warehouses",
        "fields": ["warehouse_code", "warehouse_name", "warehouse_type"],
    },
    {
        "source": "employee", "label": "员工", "route": "/skill-matrix",
        "select": "id, username, full_name, email, role",
        "from": "users",
        "fields": ["username", "full_name", "email"],
    },
]


@router.get("")
async def global_search(
    q: str = Query(..., min_length=1, max_length=100, description="搜索关键词"),
    limit: int = Query(8, ge=1, le=20, description="每模块最大结果数"),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    全站聚合搜索：跨工单/产品/设备/库存/工位/仓库/员工搜索，
    返回分类结果 + facets 统计（参考 luaguage site_search_engine 结构）
    """
    keyword = q.strip()
    if not keyword:
        return {"status": "success", "query": "", "count": 0, "facets": {}, "results": []}

    like_pattern = f"%{keyword}%"
    all_results = []
    facets = {}

    for mod in SEARCH_MODULES:
        # 构建 OR 条件
        conditions = " OR ".join(
            f"CAST({f} AS TEXT) ILIKE :kw" for f in mod["fields"]
        )
        sql = f"""
            SELECT {mod['select']} FROM {mod['from']}
            WHERE {conditions}
            LIMIT :lim
        """
        try:
            result = await db.execute(text(sql), {"kw": like_pattern, "lim": limit})
            rows = result.mappings().all()
            count = len(rows)
            if count > 0:
                facets[mod["source"]] = count
                for row in rows:
                    row_dict = dict(row)
                    # 提取显示标题（优先用第一个搜索字段，去掉表别名前缀）
                    title = ""
                    subtitle = ""
                    for f in mod["fields"]:
                        key = f.split(".")[-1]
                        val = str(row_dict.get(key) or "")
                        if val and not title:
                            title = val
                        elif val and not subtitle:
                            subtitle = val
                    all_results.append({
                        "source": mod["source"],
                        "source_label": mod["label"],
                        "title": title or str(row_dict.get("id", "")),
                        "subtitle": subtitle,
                        "route": mod["route"],
                        "id": str(row_dict.get("id", "")),
                        "data": {k: str(v) for k, v in row_dict.items() if v is not None},
                    })
        except Exception as exc:
            # 表不存在/列名不匹配等情况跳过，但记录日志避免静默失败
            logger.warning("全站搜索模块 %s 查询失败: %s", mod["source"], exc)
            continue

    return {
        "status": "success",
        "query": keyword,
        "count": len(all_results),
        "facets": facets,
        "results": all_results,
    }
