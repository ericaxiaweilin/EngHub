"""
搜索 API 端点 v2
提供企业级统一搜索接口
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional, List
from datetime import datetime

from core.search_engine.v2 import (
    get_search_engine,
    get_data_loader,
    SearchQuery,
    SearchEntityType,
    SearchDocument,
)

router = APIRouter(prefix="/search", tags=["Search Engine v2"])


@router.get("/health")
async def health_check():
    """健康检查"""
    engine = get_search_engine()
    stats = engine.get_stats()
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "index_stats": stats,
    }


@router.get("/stats")
async def get_stats():
    """获取索引统计信息"""
    engine = get_search_engine()
    return engine.get_stats()


@router.get("/search", response_model=dict)
async def search(
    q: str = Query(..., description="搜索关键词", min_length=1),
    types: Optional[List[str]] = Query(None, description="实体类型过滤"),
    status: Optional[str] = Query(None, description="状态过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    sort_by: str = Query("relevance", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向"),
):
    """
    统一搜索接口
    
    支持搜索工单、设备、物料、SOP、质量报告等所有业务数据
    """
    engine = get_search_engine()
    
    # 解析实体类型
    entity_types = None
    if types:
        try:
            entity_types = [SearchEntityType(t) for t in types]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"无效的实体类型：{e}")
    
    # 构建查询
    filters = {}
    if status:
        filters["status"] = status
    
    query = SearchQuery(
        query=q,
        entity_types=entity_types,
        filters=filters,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        highlight_enabled=True,
        fuzzy_search=False,
    )
    
    # 执行搜索
    response = engine.search(query)
    
    return response.model_dump()


@router.post("/search", response_model=dict)
async def advanced_search(search_query: SearchQuery):
    """
    高级搜索接口
    
    支持复杂的过滤条件和上下文感知搜索
    """
    engine = get_search_engine()
    response = engine.search(search_query)
    return response.model_dump()


@router.post("/index")
async def index_document(document: SearchDocument):
    """
    索引单个文档
    
    用于实时同步业务数据变更
    """
    engine = get_search_engine()
    engine.index_document(document)
    
    return {
        "status": "success",
        "message": f"文档已索引：{document.id}",
        "document_id": document.id,
        "entity_type": document.entity_type.value,
    }


@router.delete("/index/{entity_type}/{entity_id}")
async def delete_document(entity_type: str, entity_id: str):
    """
    删除索引文档
    """
    try:
        et = SearchEntityType(entity_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的实体类型：{entity_type}")
    
    engine = get_search_engine()
    engine.delete_document(et, entity_id)
    
    return {
        "status": "success",
        "message": f"文档已删除：{entity_type}:{entity_id}",
    }


@router.get("/suggest")
async def get_suggestions(
    q: str = Query(..., description="查询前缀", min_length=1),
    limit: int = Query(5, ge=1, le=20, description="建议数量"),
):
    """
    获取搜索建议
    
    基于索引词汇的前缀匹配
    """
    engine = get_search_engine()
    tokenizer = engine.tokenizer
    
    # 分词
    tokens = tokenizer.tokenize(q)
    if not tokens:
        return {"suggestions": []}
    
    # 获取最后一个 token 的建议
    last_token = tokens[-1]
    all_terms = engine.index.get_all_terms()
    
    suggestions = [t for t in all_terms if t.startswith(last_token)]
    suggestions = list(set(suggestions))[:limit]
    
    return {"query": q, "suggestions": suggestions}


@router.post("/index/batch")
async def index_batch_documents(documents: list[SearchDocument]):
    """
    批量索引文档
    
    用于初始化或全量同步
    """
    engine = get_search_engine()
    
    success_count = 0
    failed_ids = []
    
    for doc in documents:
        try:
            engine.index_document(doc)
            success_count += 1
        except Exception as e:
            failed_ids.append(doc.id)
    
    return {
        "status": "completed",
        "total": len(documents),
        "success": success_count,
        "failed": len(failed_ids),
        "failed_ids": failed_ids,
    }


# 示例数据初始化端点
@router.post("/seed/sample-data")
async def seed_sample_data():
    """
    加载示例数据用于测试
    
    创建工单、设备、SOP、质量报告、物料等示例数据
    """
    from datetime import timedelta
    
    loader = get_data_loader()
    engine = get_search_engine()
    
    now = datetime.now()
    
    # 工单示例
    work_orders = [
        loader.create_work_order_document(
            work_order_id="WO-2024-001",
            title="iPhone 15 Pro 组装",
            product_name="iPhone 15 Pro",
            quantity=1000,
            status="in_progress",
            priority="high",
            station_id="STN-001",
            station_name="SMT 贴片线 A",
            owner_name="张工",
            description="紧急订单，需要优先处理",
        ),
        loader.create_work_order_document(
            work_order_id="WO-2024-002",
            title="MacBook Air 组装",
            product_name="MacBook Air M3",
            quantity=500,
            status="pending",
            priority="normal",
            station_id="STN-002",
            station_name="组装线 B",
            owner_name="李工",
        ),
        loader.create_work_order_document(
            work_order_id="WO-2024-003",
            title="iPad Pro 屏幕检测",
            product_name="iPad Pro 12.9",
            quantity=200,
            status="completed",
            priority="low",
            station_id="STN-003",
            station_name="质检站 C",
            owner_name="王工",
        ),
    ]
    
    # 设备示例
    devices = [
        loader.create_device_document(
            device_id="DEV-001",
            name="SMT 贴片机 A1",
            model="Fuji NXT III",
            status="running",
            location="车间 A - SMT 线",
            oee=87.5,
            last_maintenance=now - timedelta(days=15),
            next_maintenance=now + timedelta(days=15),
        ),
        loader.create_device_document(
            device_id="DEV-002",
            name="自动光学检测仪",
            model="Omron VT-S730",
            status="fault",
            location="车间 A - 质检站",
            oee=62.3,
            last_maintenance=now - timedelta(days=45),
            next_maintenance=now - timedelta(days=5),  # 已过期
            description="相机模块故障，待维修",
        ),
        loader.create_device_document(
            device_id="DEV-003",
            name="回流焊炉",
            model="Heller 1809EXL",
            status="stopped",
            location="车间 A - SMT 线",
            oee=0,
            last_maintenance=now - timedelta(days=7),
            next_maintenance=now + timedelta(days=23),
        ),
    ]
    
    # SOP 示例
    sops = [
        loader.create_sop_document(
            sop_id="SOP-PROD-001",
            title="SMT 贴片作业指导书",
            category="生产",
            version="V2.3",
            status="active",
            content_text="""
            1. 目的：规范 SMT 贴片操作流程
            2. 适用范围：所有 SMT 产线
            3. 操作步骤:
               - 检查 PCB 板是否完好
               - 确认钢网版本正确
               - 设置贴片机程序
               - 首件检验合格后批量生产
            4. 注意事项：静电防护、温湿度控制
            """,
            author="工艺部",
            effective_date=now - timedelta(days=30),
        ),
        loader.create_sop_document(
            sop_id="SOP-QA-002",
            title="外观检验标准",
            category="质量",
            version="V1.8",
            status="active",
            content_text="""
            1. 检验项目：划痕、脏污、色差、毛刺
            2. 判定标准:
               - 划痕长度<2mm 可接受
               - 脏污面积<1mm²可接受
               - 色差不超过ΔE=1.5
            3. 检验环境：D65 光源，照度 800-1200Lux
            """,
            author="品质部",
            effective_date=now - timedelta(days=60),
        ),
    ]
    
    # 质量报告示例
    quality_reports = [
        loader.create_quality_report_document(
            report_id="QR-2024-001",
            title="iPhone 15 Pro 首件检验报告",
            report_type="FAI",
            status="approved",
            defect_count=0,
            yield_rate=100.0,
            work_order_id="WO-2024-001",
            inspector="赵工",
        ),
        loader.create_quality_report_document(
            report_id="QR-2024-002",
            title="MacBook Air 过程检验报告",
            report_type="IPQC",
            status="rejected",
            defect_count=5,
            yield_rate=92.5,
            work_order_id="WO-2024-002",
            inspector="钱工",
            description="发现螺丝松动问题，已通知返工",
        ),
    ]
    
    # 物料示例
    materials = [
        loader.create_material_document(
            material_id="MAT-001",
            name="PCB 主板",
            spec="iPhone 15 Pro Rev.C",
            quantity=1500,
            unit="pcs",
            location="A-01-02",
            status="available",
            supplier="Foxconn",
        ),
        loader.create_material_document(
            material_id="MAT-002",
            name="锂电池",
            spec="3.8V 3200mAh",
            quantity=800,
            unit="pcs",
            location="B-03-01",
            status="available",
            supplier="CATL",
            expiry_date=now + timedelta(days=20),  # 即将过期
        ),
        loader.create_material_document(
            material_id="MAT-003",
            name="结构胶",
            spec="3M DP460",
            quantity=50,
            unit="kg",
            location="C-02-03",
            status="low_stock",
            supplier="3M",
            expiry_date=now + timedelta(days=180),
        ),
    ]
    
    # 索引所有文档
    all_docs = work_orders + devices + sops + quality_reports + materials
    
    for doc in all_docs:
        engine.index_document(doc)
    
    return {
        "status": "success",
        "message": f"已加载 {len(all_docs)} 条示例数据",
        "breakdown": {
            "work_orders": len(work_orders),
            "devices": len(devices),
            "sops": len(sops),
            "quality_reports": len(quality_reports),
            "materials": len(materials),
        },
        "index_stats": engine.get_stats(),
    }
