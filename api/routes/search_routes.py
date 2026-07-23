"""
全站系统搜索 API
参考 luaguage site_search_engine 设计：跨模块聚合搜索 + 分类 facets + 排序去重
搜索范围：工单、产品、设备、库存、工位、仓库、员工
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from database.db_config import get_db
from core.auth.security import get_current_user

router = APIRouter(prefix="/api/v1/search", tags=["Global Search"])

# 各模块搜索配置：(source标识, 中文标签, SQL表名, 搜索字段列表, 前端跳转路由)
SEARCH_MODULES = [
    ("work_order", "工单", "work_orders", ["work_order_number", "product_name", "status"], "/work-orders"),
    ("product", "产品", "products", ["product_code", "product_name", "specification"], "/base-data"),
    ("equipment", "设备", "equipment", ["equipment_code", "equipment_name", "model"], "/base-data"),
    ("inventory", "库存", "inventory", ["item_code", "item_name", "warehouse_id"], "/inventory"),
    ("station", "工位", "stations", ["station_code", "station_name", "station_type"], "/base-data"),
    ("warehouse", "仓库", "warehouses", ["warehouse_code", "warehouse_name", "warehouse_type"], "/warehouses"),
    ("employee", "员工", "users", ["username", "full_name", "email"], "/skill-matrix"),
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

    for source, label, table, fields, route in SEARCH_MODULES:
        # 构建 OR 条件
        conditions = " OR ".join(
            f"CAST({f} AS TEXT) ILIKE :kw" for f in fields
        )
        sql = f"""
            SELECT * FROM {table}
            WHERE {conditions}
            LIMIT :lim
        """
        try:
            result = await db.execute(text(sql), {"kw": like_pattern, "lim": limit})
            rows = result.mappings().all()
            count = len(rows)
            if count > 0:
                facets[source] = count
                for row in rows:
                    row_dict = dict(row)
                    # 提取显示标题（优先用第一个搜索字段）
                    title = ""
                    subtitle = ""
                    for f in fields:
                        val = str(row_dict.get(f) or "")
                        if val and not title:
                            title = val
                        elif val and not subtitle:
                            subtitle = val
                    all_results.append({
                        "source": source,
                        "source_label": label,
                        "title": title or str(row_dict.get("id", "")),
                        "subtitle": subtitle,
                        "route": route,
                        "id": str(row_dict.get("id", "")),
                        "data": {k: str(v) for k, v in row_dict.items() if v is not None},
                    })
        except Exception:
            # 表不存在等情况静默跳过
            continue

    return {
        "status": "success",
        "query": keyword,
        "count": len(all_results),
        "facets": facets,
        "results": all_results,
    }
