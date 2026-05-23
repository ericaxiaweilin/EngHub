# MES 生产专家系统开发文档

## 📋 概述

MES 生产专家系统是基于 LLM 的智能助手，为制造执行系统提供专业的问题分析、决策辅助和知识查询能力。

**底层模型网关**: `http://100.96.188.77:14041`

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     前端应用 (Frontend)                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    API Gateway (FastAPI)                     │
│                  /api/v1/expert/*                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   专家系统引擎 (ExpertEngine)                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   RAG       │  │   Tool      │  │    LLM Gateway      │  │
│  │ Knowledge   │  │   Calling   │  │    Client           │  │
│  │   Base      │  │   Registry  │  │  (100.96.188.77)    │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## 📁 目录结构

```
/workspace/
├── core/expert_system/          # 专家系统核心模块
│   ├── __init__.py             # ExpertEngine 主引擎
│   ├── config.py               # 配置管理
│   ├── knowledge.py            # RAG 知识库
│   ├── tools.py                # 工具注册表
│   └── llm_client.py           # LLM 网关客户端
│
├── api/v1/endpoints/expert/    # API 端点
│   ├── __init__.py
│   └── chat.py                 # 聊天接口
│
└── main.py                     # 应用入口 (已集成专家系统路由)
```

## 🔧 核心组件

### 1. ExpertEngine (专家引擎)

位于 `core/expert_system/__init__.py`

**主要功能**:
- 接收用户查询
- RAG 知识检索
- Prompt 构建
- Tool Calling 调度
- LLM 响应处理

**使用方法**:
```python
from core.expert_system import ExpertEngine

engine = ExpertEngine()
await engine.initialize()

result = await engine.chat(
    query="SMT-01 工位的 OEE 是多少？",
    context={"station_id": "SMT-01"}
)

print(result["answer"])
print(f"置信度：{result['confidence']}")
print(f"建议行动：{result['suggested_actions']}")
```

### 2. KnowledgeBase (知识库)

位于 `core/expert_system/knowledge.py`

**功能**:
- 文档加载与分块 (Chunking)
- 向量嵌入生成 (调用网关 Embedding API)
- 相似度检索

**知识来源**:
- 项目设计文档 (API 设计、ERD 等)
- SOP 标准作业程序
- MES 最佳实践文档
- 历史故障案例库

### 3. ToolRegistry (工具注册表)

位于 `core/expert_system/tools.py`

**可用工具**:

| 工具名称 | 功能描述 |
|---------|---------|
| `get_work_order_status` | 查询工单状态 |
| `get_station_info` | 查询工位信息 |
| `get_production_data` | 查询生产数据 |
| `get_quality_metrics` | 获取质量指标 |
| `analyze_defects` | 缺陷分析 |
| `get_device_status` | 设备状态查询 |
| `get_oee_metrics` | OEE 计算 |
| `get_inventory_level` | 库存查询 |
| `get_material_shortage` | 缺料分析 |

### 4. LLMGatewayClient (LLM 网关客户端)

位于 `core/expert_system/llm_client.py`

**配置**:
- 网关地址：`http://100.96.188.77:14041`
- 默认模型：`qwen-max`
- 温度参数：0.3 (保证专业性)

**功能**:
- Chat Completion
- Stream 流式响应
- Embedding 生成
- System Prompt 构建

## 🌐 API 接口

### POST `/api/v1/expert/chat`

与生产专家对话

**请求**:
```json
{
  "query": "SMT-01 工位今天的 OEE 怎么样？有什么改进建议？",
  "context": {
    "station_id": "SMT-01",
    "user_role": "production_manager"
  }
}
```

**响应**:
```json
{
  "answer": "SMT-01 工位今日 OEE 为 82.5%，略低于目标值 85%...\n\n主要损失来源:\n1. 设备故障停机 25 分钟\n2. 换型时间 35 分钟\n\n建议采取以下措施:\n- 安排设备预防性维护\n- 优化换型流程...",
  "confidence": 0.85,
  "sources": ["/workspace/01_API_Design_Detailed.md", "/workspace/OEE_Calculation_Method.md"],
  "suggested_actions": [
    "检查钢网张力并重新张紧",
    "验证回流焊温度曲线",
    "安排供料器预防性维护"
  ],
  "tool_calls_executed": 2
}
```

### GET `/api/v1/expert/health`

健康检查

**响应**:
```json
{
  "status": "healthy",
  "initialized": true,
  "knowledge_base_loaded": true
}
```

### GET `/api/v1/expert/tools`

列出所有可用工具

### POST `/api/v1/expert/initialize`

手动初始化/重新加载知识库

### GET `/api/v1/expert/knowledge/stats`

获取知识库统计信息

## ⚙️ 配置说明

环境变量 (`.env` 文件):

```bash
# LLM 网关配置
LLM_GATEWAY_URL=http://100.96.188.77:14041
LLM_API_KEY=your_api_key_here  # 如果需要认证
LLM_MODEL_NAME=qwen-max

# RAG 配置
VECTOR_STORE_PATH=./data/vector_store
CHUNK_SIZE=512
CHUNK_OVERLAP=50

# 专家系统行为
MAX_CONTEXT_LENGTH=4096
TEMPERATURE=0.3
MAX_TOKENS=2048
ENABLE_TOOL_CALLING=true
TOOL_TIMEOUT=30
```

## 🚀 快速开始

### 1. 启动服务

```bash
cd /workspace
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. 访问 API 文档

打开浏览器访问：`http://localhost:8000/docs`

### 3. 测试专家系统

```bash
# 健康检查
curl http://localhost:8000/api/v1/expert/health

# 对话测试
curl -X POST http://localhost:8000/api/v1/expert/chat \
  -H "Content-Type: application/json" \
  -d '{
    "query": "请介绍 MES 系统中的 OEE 计算方法"
  }'
```

## 📝 典型使用场景

### 场景 1: 生产异常诊断

**用户**: "SMT 产线良率突然下降到 92%，可能是什么原因？"

**专家系统**:
1. 调用 `get_quality_metrics` 获取最新质量数据
2. 调用 `analyze_defects` 分析主要缺陷类型
3. 检索知识库中的类似案例
4. 给出根本原因分析和改进建议

### 场景 2: 工单进度查询

**用户**: "WO-2025-0115-001 工单能按时完成吗？"

**专家系统**:
1. 调用 `get_work_order_status` 获取工单状态
2. 计算当前进度与计划的偏差
3. 评估剩余工序的产能
4. 给出交期风险评估

### 场景 3: 设备维护建议

**用户**: "PM-500 贴片机需要维护吗？"

**专家系统**:
1. 调用 `get_device_status` 获取设备状态
2. 调用 `get_oee_metrics` 分析性能趋势
3. 检查维护记录和下次维护计划
4. 给出维护建议和优先级

## 🔮 后续开发计划

### Phase 1 (已完成) ✓
- [x] 基础架构搭建
- [x] LLM 网关集成
- [x] 工具注册表
- [x] RAG 知识库框架
- [x] API 端点

### Phase 2 (进行中)
- [ ] 向量数据库集成 (pgvector/Milvus)
- [ ] 真实 API 对接 (替换 Mock 数据)
- [ ] 流式响应支持
- [ ] 对话历史管理

### Phase 3 (规划中)
- [ ] 多角色专家 (质量专家、设备专家等)
- [ ] 主动告警推送
- [ ] 报表自动生成
- [ ] 前端聊天界面集成

## 📞 技术支持

如有问题请联系开发团队或查看项目文档。
