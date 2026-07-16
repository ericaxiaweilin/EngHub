# Model Bases + Luaguage Integration

EngHub Agent / MCP 已对接公司现有模型底座与 luaguage ERP 主数据。

## 结论先说

| 项目 | 角色 | 在 EngHub 中怎么用 |
|------|------|-------------------|
| **model-engineering-base** | OpenAI 兼容 LLM 平台 | Agent 对话 + tool calling（优先） |
| **model-stack** | MES 域模型网关 | 排程优化 / 缺陷预测 / 质量分析 / 域聊天 |
| **luaguage** | ERP 主系统（engflow） | BOM / PPAP / 物料主数据，给 Agent 当上下文，**不是 LLM** |

当前环境访问不到这两个模型底座的源码仓，也访问不到历史网关 IP `100.96.188.77:14041`。实现按 EngHub 既有 AI 集成约定做了双后端适配；把可达的 URL 配进环境变量即可切换到真实底座。

## 架构

```text
Codex / App
    │
    ├─ /api/v1/agent/chat  ──► ManufacturingAgent
    │                              │
    │                              ▼
    │                        ModelBaseClient
    │                     ┌────────┴────────┐
    │                     ▼                 ▼
    │          model-engineering-base    model-stack
    │          /v1/chat/completions      /api/v1/chat
    │                                    /api/v1/optimize
    │                                    /api/v1/predict
    │                                    /api/v1/analyze
    │
    └─ MCP tools ──► ToolRegistry
                        ├─ MES DB / demo tools
                        └─ luaguage BOM/PPAP/material tools
```

## 环境变量

```bash
# 选择后端: auto | model-engineering-base | model-stack
MODEL_BASE_PROVIDER=auto

# 两个底座可分开部署；未设置时都回落到历史 MODEL_GATEWAY_URL
MODEL_ENGINEERING_BASE_URL=http://model-engineering-base:8000
MODEL_STACK_URL=http://model-stack:14041

# 兼容旧变量
LLM_GATEWAY_URL=http://model-engineering-base:8000
MODEL_GATEWAY_URL=http://model-stack:14041
LLM_API_KEY=
LLM_MODEL_NAME=qwen-max

# luaguage ERP（主数据，不是模型）
LUAGUAGE_BASE_URL=http://luaguage:8080
LUAGUAGE_API_KEY=
LUAGUAGE_ENABLED=true
```

`MODEL_BASE_PROVIDER=auto` 时：

1. 优先走 **model-engineering-base**（支持 tools）
2. 失败则回退 **model-stack** `/api/v1/chat`
3. 两者都不可达时，Agent 仍返回 MES/luaguage 工具直读结果（offline fallback）

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/ai/health` | 双底座 + luaguage 连通性 |
| POST | `/api/v1/ai/chat` | 统一聊天（走 ModelBaseClient） |
| POST | `/api/v1/ai/optimize/schedule` | model-stack 排程 |
| POST | `/api/v1/ai/predict/defects` | model-stack 缺陷预测 |
| POST | `/api/v1/ai/analyze/quality` | model-stack 质量分析 |
| GET | `/api/v1/agent/health` | Agent + model_base 状态 |
| POST | `/api/v1/agent/chat` | 带 MES/luaguage tool calling |

## 新增 / 关键的 Agent·MCP 工具

- `get_model_base_status`
- `get_luaguage_bom`
- `get_luaguage_ppap`
- `get_luaguage_material`

## luaguage「AI 技术」评估

仓库内 `integrations/luaguage.py` 与架构文档表明：luaguage 提供的是 **ERP 主数据与同步**（BOM/PPAP/权限/销售订单），不是模型推理栈。

可复用到 Agent 的部分：

- BOM / 物料 / PPAP 作为工具上下文（已接入）
- Webhook 变更事件驱动缓存刷新（已保留 handler）
- 生产结果回写通知（已实现 HTTP 调用骨架）

不应期望从 luaguage 获取：

- `/v1/chat/completions` 或 embedding
- 替代 model-stack / model-engineering-base

## 代码位置

- `core/model_base/` — 双底座客户端
- `core/agent/llm_client.py` — Agent 经 ModelBaseClient 调模型
- `integrations/luaguage.py` — ERP HTTP 客户端 + 降级 demo
- `api/routes/ai_routes.py` — 模型底座 HTTP API
- `docs/AI_AGENT_MCP.md` — Agent/MCP 总览

## 验证

```bash
curl http://localhost:8000/api/v1/ai/health
curl -X POST http://localhost:8000/api/v1/agent/tools/invoke \
  -H 'Content-Type: application/json' \
  -d '{"name":"get_model_base_status","arguments":{}}'
curl -X POST http://localhost:8000/api/v1/agent/tools/invoke \
  -H 'Content-Type: application/json' \
  -d '{"name":"get_luaguage_bom","arguments":{"product_id":"SKU-A100"}}'
```
