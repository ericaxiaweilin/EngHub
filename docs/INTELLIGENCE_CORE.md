# EngHub Intelligence Core

EngHub 不是纯 CRUD 系统。当前核心已经收敛为一个明确的智能主线：

- `core/intelligence/`
  - 智能核心统一入口
  - 汇聚 AI、专家系统、搜索、Sim-ERP 仿真与决策表面
- `core/sim_erp/`
  - 物理仿真、规则插件、仲裁器、审计
- `core/ai_service.py`
  - 外部 AI 网关适配层
- `core/expert_system/`
  - 生产专家系统、RAG、工具调用
- `core/search_engine/v2/`
  - 企业级统一搜索与上下文检索

## Unified Flow

```text
Physical Input
  -> Sim-ERP Physics Core
  -> Compliance Plugins
  -> Decision Arbiter
  -> Audit Trail
  -> Intelligence Hub
  -> AI Prediction / Expert Reasoning / Unified Search
  -> Decision Studio
```

## Main Entry Points

- `core/intelligence/hub.py`
  - `ManufacturingIntelligenceHub`
- `core/intelligence/decision.py`
  - `DecisionStudio`
- `api/routes/intelligence_routes.py`
  - `/api/v1/intelligence/overview`
  - `/api/v1/intelligence/health`

## Why this layer exists

这层不是为了重新包装 CRUD，而是为了把下面四种能力收成同一个系统边界：

1. 仿真
2. AI 预测
3. 场景推演 / 专家推理
4. 决策执行

之后无论继续补本地预测器、排程优化器、场景对比器，优先落在 `core/intelligence/`，再由它协调底层模块，而不是继续把能力散落在不同路由里。
