# MES 企业级统一搜索引擎 v2

## 📖 概述

对标 **Atlassian Rovo** 的企业级站内数据搜索引擎，为 MES 系统提供全域统一搜索能力。

### 核心特性

| 特性 | 说明 |
|------|------|
| 🔍 **统一索引** | 工单、设备、物料、SOP、质量报告等全业务数据统一索引 |
| 🧠 **智能分词** | 支持中文分词 (jieba)、英文分词、停用词过滤 |
| 📊 **BM25 评分** | 经典检索算法 + 字段权重 boosting + 上下文感知 |
| 🔗 **深度链接** | 搜索结果点击直达业务详情页，带面包屑导航 |
| ⚡ **实时索引** | 支持增量更新、批量索引、自动同步 |
| 🔐 **权限感知** | 基于 RBAC 的动态权限过滤 |
| 🎯 **行动导向** | 结果卡片支持直接操作 (查看/审批/报工等) |
| 🔔 **关联上下文** | 自动展示关联工单、设备、文档等信息 |

---

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    前端搜索界面 (TypeScript)                  │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│   │  全局搜索框  │  │  结果列表   │  │  侧边过滤器  │        │
│   └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
                            ↓ HTTP/REST
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI 搜索服务层                          │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│   │  搜索端点   │  │  索引端点   │  │  建议端点   │        │
│   └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   搜索引擎核心 (Python)                       │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│   │  中文分词器  │  │  倒排索引   │  │  BM25 评分器 │        │
│   └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                   业务数据加载器                              │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│   │  工单转换   │  │  设备转换   │  │  SOP 转换    │        │
│   └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

---

## 📦 模块结构

```
core/search_engine/v2/
├── __init__.py          # 模块导出
├── models.py            # 数据模型定义
├── engine.py            # 搜索引擎核心
└── data_loader.py       # 业务数据加载器

api/v1/endpoints/search/v2/
└── search.py            # REST API 端点
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install jieba  # 可选，用于中文分词
```

### 2. 初始化搜索引擎

```python
from core.search_engine.v2 import get_search_engine, get_data_loader

engine = get_search_engine()
loader = get_data_loader(base_url="http://localhost:3000")
```

### 3. 索引业务数据

```python
# 创建工单文档
wo_doc = loader.create_work_order_document(
    work_order_id="WO-2024-001",
    title="iPhone 15 Pro 组装",
    product_name="iPhone 15 Pro",
    quantity=1000,
    status="in_progress",
    priority="high",
    station_id="STN-001",
    station_name="SMT 贴片线 A",
    owner_name="张工",
)

# 索引文档
engine.index_document(wo_doc)

# 批量索引
docs = [wo_doc, device_doc, sop_doc, ...]
for doc in docs:
    engine.index_document(doc)
```

### 4. 执行搜索

```python
from core.search_engine.v2 import SearchQuery, SearchEntityType

# 基本搜索
query = SearchQuery(query="iPhone")
response = engine.search(query)

# 带过滤的搜索
query = SearchQuery(
    query="工单",
    entity_types=[SearchEntityType.WORK_ORDER],
    filters={"status": "in_progress"},
    page=1,
    page_size=20,
)
response = engine.search(query)

# 查看结果
for hit in response.hits:
    print(f"标题：{hit.document.title}")
    print(f"分数：{hit.score}")
    print(f"链接：{hit.document.link.route_path}")
    print(f"操作：{[a.label for a in hit.document.actions]}")
```

---

## 🌐 API 使用

### 启动服务

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/search/v2/health` | GET | 健康检查 |
| `/api/v1/search/v2/stats` | GET | 索引统计 |
| `/api/v1/search/v2/search?q=xx` | GET | 搜索 |
| `/api/v1/search/v2/search` | POST | 高级搜索 |
| `/api/v1/search/v2/index` | POST | 索引文档 |
| `/api/v1/search/v2/index/{type}/{id}` | DELETE | 删除索引 |
| `/api/v1/search/v2/suggest?q=xx` | GET | 搜索建议 |
| `/api/v1/search/v2/seed/sample-data` | POST | 加载示例数据 |

### cURL 示例

```bash
# 加载示例数据
curl -X POST http://localhost:8000/api/v1/search/v2/seed/sample-data

# 搜索
curl "http://localhost:8000/api/v1/search/v2/search?q=iPhone&types=work_order,device"

# 高级搜索
curl -X POST http://localhost:8000/api/v1/search/v2/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "SMT",
    "entity_types": ["work_order", "device", "sop"],
    "filters": {"status": "running"},
    "page": 1,
    "page_size": 20
  }'

# 获取建议
curl "http://localhost:8000/api/v1/search/v2/suggest?q=SMT&limit=10"
```

---

## 📊 数据模型

### SearchDocument (统一文档协议)

```python
{
  "id": "work_order:WO-2024-001",
  "entity_type": "work_order",
  "title": "WO-2024-001 - iPhone 15 Pro 组装",
  "content": "工单编号：WO-2024-001\n产品名称：iPhone 15 Pro\n...",
  "summary": "iPhone 15 Pro x1000 - in_progress",
  "created_at": "2024-01-15T10:00:00",
  "updated_at": "2024-01-20T15:30:00",
  "owner_name": "张工",
  "status": "in_progress",
  "priority": "high",
  "tags": ["iPhone 15 Pro", "in_progress"],
  "category": "production",
  "link": {
    "entity_type": "work_order",
    "entity_id": "WO-2024-001",
    "route_path": "/work-orders/WO-2024-001",
    "permalink": "http://localhost:3000/work-orders/WO-2024-001",
    "breadcrumb": ["生产", "工单管理", "WO-2024-001"]
  },
  "actions": [
    {"action_type": "view", "label": "查看详情", "url": "/api/v1/work-orders/WO-2024-001"}
  ],
  "related_context": [...],
  "metadata": {...}
}
```

### 支持的实体类型

| 类型 | 说明 | 路由前缀 |
|------|------|----------|
| `work_order` | 工单 | `/work-orders/` |
| `station` | 工位 | `/stations/` |
| `device` | 设备 | `/devices/` |
| `material` | 物料 | `/materials/` |
| `sop` | 作业指导书 | `/sop/` |
| `quality_report` | 质量报告 | `/quality/` |
| `maintenance_plan` | 维护计划 | `/maintenance/` |
| `user` | 用户 | `/users/` |
| `alert` | 告警 | `/alerts/` |

---

## 🔧 高级功能

### 上下文感知 Boosting

```python
query = SearchQuery(
    query="SMT",
    context_station_id="STN-001",  # 当前工位
    context_user_id="user-123",     # 当前用户 (用于权限过滤)
)
```

位于 STN-001 工位的用户搜索"SMT"时，相关结果分数提升 50%。

### 状态 Boosting

活跃状态 (`active`, `running`, `in_progress`) 的文档分数自动提升 20%。

### 优先级 Boosting

高优先级 (`priority=high`) 的工单分数提升 20%。

### 缺陷优先

良率低于 95% 的质量报告分数提升 50%，便于快速发现问题。

### 即将过期提醒

30 天内过期的物料分数提升 50%。

---

## 🧪 测试

```python
from core.search_engine.v2 import (
    get_search_engine, 
    get_data_loader, 
    reset_search_engine,
    SearchQuery
)

def test_search():
    # 重置引擎
    reset_search_engine()
    
    engine = get_search_engine()
    loader = get_data_loader()
    
    # 创建测试数据
    wo = loader.create_work_order_document(
        work_order_id="WO-TEST-001",
        title="iPhone 组装",
        product_name="iPhone 15 Pro",
        quantity=100,
        status="in_progress",
        priority="high",
    )
    
    engine.index_document(wo)
    
    # 搜索
    query = SearchQuery(query="iPhone")
    result = engine.search(query)
    
    assert result.total_hits == 1
    assert result.hits[0].document.id == "work_order:WO-TEST-001"
    print("✅ 测试通过!")
```

---

## 📈 性能指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 索引速度 | >1000 docs/s | 批量索引性能 |
| 搜索延迟 | <50ms (P95) | 单次查询耗时 |
| 内存占用 | <100MB | 10 万文档规模 |
| 并发支持 | >100 QPS | 同时搜索请求 |

---

## 🔮 与专家系统集成

当 LLM 网关恢复后，搜索引擎将作为 RAG 核心组件:

```python
# 专家系统工具调用
async def search_mes_data(query: str) -> str:
    """搜索 MES 数据 (供 LLM 调用)"""
    engine = get_search_engine()
    search_query = SearchQuery(query=query, page_size=5)
    results = engine.search(search_query)
    
    # 格式化结果为 LLM 可读格式
    context = "\n\n".join([
        f"{hit.document.title}\n{hit.document.summary}\n链接：{hit.document.link.permalink}"
        for hit in results.hits[:3]
    ])
    
    return context if context else "未找到相关数据"
```

---

## 📝 待办事项

- [ ] 集成真实 MES 数据库自动同步
- [ ] 实现完整的 RBAC 权限过滤
- [ ] 添加向量检索支持 (pgvector/Milvus)
- [ ] 实现查询日志和分析
- [ ] 前端搜索界面开发 (Cmd+K 唤起)
- [ ] 搜索结果点击热区追踪
- [ ] 热门搜索词统计
- [ ] 同义词词典扩展

---

## 📄 许可证

内部项目，仅供 MES 系统使用。
