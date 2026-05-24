"""
MES 生产数据搜索引擎 API
提供搜索、索引管理、统计等功能
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from core.search_engine import get_search_engine, initialize_search_engine
from core.search_engine.config import SearchEngineConfig

router = APIRouter(prefix="/search", tags=["搜索引擎"])


class SearchRequest(BaseModel):
    """搜索请求"""
    query: str
    search_types: Optional[List[str]] = ["all"]
    filters: Optional[Dict[str, Any]] = None
    top_k: Optional[int] = 10
    min_score: Optional[float] = 0.3


class IndexDataRequest(BaseModel):
    """索引数据请求"""
    data_type: str
    documents: List[Dict[str, Any]]
    id_field: Optional[str] = "id"


@router.post("/search")
async def search(request: SearchRequest):
    """
    执行搜索
    
    - **query**: 搜索关键词
    - **search_types**: 搜索的数据类型列表，默认["all"]
    - **filters**: 过滤条件
    - **top_k**: 返回结果数量，默认 10
    - **min_score**: 最小相关性分数，默认 0.3
    """
    try:
        engine = get_search_engine()
        results = engine.search(
            query=request.query,
            search_types=request.search_types,
            filters=request.filters,
            top_k=request.top_k,
            min_score=request.min_score
        )
        
        return {
            "success": True,
            "query": request.query,
            "total_results": len(results),
            "results": [result.to_dict() for result in results],
            "search_types": request.search_types,
            "filters": request.filters
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败：{str(e)}")


@router.get("/search")
async def search_get(
    q: str = Query(..., description="搜索关键词"),
    types: Optional[str] = Query("all", description="搜索类型，逗号分隔"),
    top_k: Optional[int] = Query(10, description="返回结果数"),
    min_score: Optional[float] = Query(0.3, description="最小分数")
):
    """GET 方式的搜索接口"""
    search_types = types.split(",") if types else ["all"]
    
    try:
        engine = get_search_engine()
        results = engine.search(
            query=q,
            search_types=search_types,
            top_k=top_k,
            min_score=min_score
        )
        
        return {
            "success": True,
            "query": q,
            "total_results": len(results),
            "results": [result.to_dict() for result in results]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败：{str(e)}")


@router.post("/index")
async def index_data(request: IndexDataRequest):
    """
    索引数据
    
    - **data_type**: 数据类型 (work_order, station, device, material, quality, inventory, production, defect, sop)
    - **documents**: 文档列表
    - **id_field**: ID 字段名，默认"id"
    """
    try:
        engine = get_search_engine()
        engine.index_data(
            data_type=request.data_type,
            documents=request.documents,
            id_field=request.id_field
        )
        
        return {
            "success": True,
            "message": f"成功索引 {len(request.documents)} 条 {request.data_type} 数据",
            "indexed_count": len(request.documents),
            "data_type": request.data_type
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"索引失败：{str(e)}")


@router.get("/stats")
async def get_stats():
    """获取搜索引擎统计信息"""
    try:
        engine = get_search_engine()
        stats = engine.get_stats()
        
        return {
            "success": True,
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败：{str(e)}")


@router.get("/suggest")
async def suggest_query(
    q: str = Query(..., description="部分查询词"),
    limit: Optional[int] = Query(5, description="建议数量")
):
    """获取查询建议"""
    try:
        engine = get_search_engine()
        suggestions = engine.suggest_query(partial_query=q, limit=limit)
        
        return {
            "success": True,
            "query": q,
            "suggestions": suggestions
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取建议失败：{str(e)}")


@router.get("/health")
async def health_check():
    """健康检查"""
    try:
        engine = get_search_engine()
        stats = engine.get_stats()
        
        return {
            "status": "healthy",
            "engine_initialized": True,
            "total_documents": stats["total_documents"],
            "supported_types": stats["supported_types"]
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@router.post("/initialize")
async def initialize_engine(config: Optional[Dict[str, Any]] = None):
    """初始化/重置搜索引擎"""
    try:
        search_config = SearchEngineConfig(**config) if config else SearchEngineConfig()
        engine = initialize_search_engine(search_config)
        stats = engine.get_stats()
        
        return {
            "success": True,
            "message": "搜索引擎初始化成功",
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"初始化失败：{str(e)}")
