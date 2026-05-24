# MES 生产数据搜索引擎

## 📋 概述

MES 生产数据搜索引擎是一个独立的全文搜索系统，支持工单、工位、设备、物料、质量记录、SOP 等多种生产数据的快速检索。该引擎可作为生产专家系统的核心组件，在 LLM 网关不可用时提供独立的数据查询能力。

## 🏗️ 架构设计

```
core/search_engine/
├── config.py          # 配置管理
├── engine.py          # 核心搜索引擎 (倒排索引)
├── data_loader.py     # 数据加载器 (示例数据+真实数据接口)
└── __init__.py        # 模块导出

api/v1/endpoints/search/
└── search.py          # REST API 端点
```

## 🔧 核心功能

### 1. 全文搜索
- 中文分词（支持双字组合）
- 倒排索引快速匹配
- Jaccard 相似度计算
- 精确匹配加分

### 2. 多类型支持
| 类型 | 说明 | 示例数据 |
|------|------|----------|
| work_order | 工单 | 生产工单、组装工单 |
| station | 工位 | SMT 线、总装线、检验站 |
| device | 设备 | 贴片机、AOI、机器人 |
| material | 物料 | IC 芯片、显示屏、电池 |
| quality | 质量记录 | FQC、IPQC 检验记录 |
| sop | 作业指导书 | SMT/SOP/QC标准作业程序 |
| inventory | 库存 | (待扩展) |
| production | 生产记录 | (待扩展) |
| defect | 缺陷记录 | (待扩展) |

### 3. 高级特性
- **多条件过滤**: 按状态、类型、类别等字段过滤
- **结果高亮**: 自动提取包含关键词的片段
- **相关性评分**: 基于词频和精确匹配的分数排序
- **缓存机制**: 查询结果缓存，TTL 可配置
- **查询建议**: 基于索引词汇的自动补全

## 🚀 快速开始

### 1. 初始化搜索引擎

```python
from core.search_engine import get_search_engine, initialize_search_engine
from core.search_engine.data_loader import MESDataLoader

# 获取引擎实例
engine = get_search_engine()

# 加载示例数据（测试用）
loader = MESDataLoader(engine)
result = loader.load_sample_data()
print(f"已加载 {result['total']} 条示例数据")
```

### 2. 执行搜索

```python
# 基本搜索
results = engine.search("iPhone", top_k=10)

# 指定类型搜索
results = engine.search("SMT", search_types=["station", "device", "sop"])

# 带过滤搜索
results = engine.search("工单", filters={"status": "running"})

# 处理结果
for result in results:
    print(f"[{result.type}] {result.title}")
    print(f"  分数：{result.score}")
    print(f"  内容：{result.content[:100]}...")
    if result.highlights:
        print(f"  高亮：{result.highlights}")
```

### 3. 索引自定义数据

```python
# 工单数据
work_orders = [
    {
        "id": "WO202401001",
        "code": "WO-2024-001",
        "name": "产品组装工单",
        "status": "running",
        "description": "详细描述..."
    }
]
engine.index_data("work_order", work_orders)

# 设备数据
devices = [...]
engine.index_data("device", devices)
```

## 🌐 REST API

### 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/search/health` | 健康检查 |
| GET | `/api/v1/search/stats` | 统计信息 |
| GET | `/api/v1/search/search` | 搜索 (GET) |
| POST | `/api/v1/search/search` | 搜索 (POST) |
| POST | `/api/v1/search/index` | 索引数据 |
| GET | `/api/v1/search/suggest` | 查询建议 |
| POST | `/api/v1/search/initialize` | 初始化引擎 |

### API 使用示例

#### 1. 搜索
```bash
# GET 方式
curl "http://localhost:8000/api/v1/search/search?q=iPhone&top_k=5"

# POST 方式
curl -X POST "http://localhost:8000/api/v1/search/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "SMT", "search_types": ["station", "device"], "top_k": 10}'
```

#### 2. 索引数据
```bash
curl -X POST "http://localhost:8000/api/v1/search/index" \
  -H "Content-Type: application/json" \
  -d '{
    "data_type": "work_order",
    "documents": [
      {"id": "WO001", "name": "测试工单", "status": "running"}
    ]
  }'
```

#### 3. 获取统计
```bash
curl "http://localhost:8000/api/v1/search/stats"
```

## 🔍 搜索算法

### 分词策略
1. 移除标点符号
2. 按空格分割
3. 生成双字组合（中文分词简化版）

### 评分公式
```
score = jaccard_similarity + exact_match_bonus + weight_bonus

其中:
- jaccard_similarity = |query_tokens ∩ doc_tokens| / |query_tokens ∪ doc_tokens|
- exact_match_bonus = 0.2 (每个精确匹配字段)
- weight_bonus = 0.1 (活跃状态文档)
```

### 索引结构
- **倒排索引**: 词 -> 文档 ID 集合
- **字段索引**: 字段值 -> 文档 ID 集合
- **文档存储**: 完整文档数据

## 📊 性能优化

1. **缓存**: 查询结果缓存，默认 TTL 300 秒
2. **增量索引**: 支持动态添加文档
3. **分块处理**: 大文本自动分块索引

## 🔮 与专家系统集成

当 LLM 网关恢复后，搜索引擎将作为 RAG 的核心组件：

```python
# 专家系统工具调用
tools = {
    "search_work_orders": lambda q: engine.search(q, ["work_order"]),
    "search_devices": lambda q: engine.search(q, ["device"]),
    "search_sops": lambda q: engine.search(q, ["sop"]),
}

# LLM 根据问题自动调用搜索工具
# 例如："查找正在运行的 iPhone 工单" 
# -> 调用 search_work_orders("iPhone running")
```

## 📝 待扩展功能

- [ ] 连接真实 MES 数据库
- [ ] 集成向量数据库 (pgvector/Milvus)
- [ ] 更智能的中文分词 (jieba)
- [ ] 同义词扩展
- [ ] 搜索结果聚合
- [ ] 实时数据同步

## 🛠️ 技术栈

- **语言**: Python 3.12+
- **框架**: FastAPI
- **索引**: 内存倒排索引
- **分词**: 正则 + 双字组合

## 📖 相关文档

- [专家系统文档](EXPERT_SYSTEM_README.md)
- [API 文档](http://localhost:8000/docs)
