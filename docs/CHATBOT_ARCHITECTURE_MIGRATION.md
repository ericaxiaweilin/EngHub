# EngFlow Chatbot Architecture Migration Plan & Status

> 本文同时维护目标架构和实际落地进度。以下进度快照基于工作区分支
> `codex/pmc-workbench-data-closure` 的 HEAD `1d22fbb`（2026-08-13 09:42，+07:00）核对；
> 远端 `origin/main` 当前仍停留在 2026-07-31，不代表这条 EngFlow 开发线的最新状态。

## 0.1 实际进度快照（2026-08-13）

| 阶段 | 状态 | 已落地 | 当前边界 / 风险 |
|------|------|--------|----------------|
| Phase 1 Kernel | 🟡 可运行骨架 | `core/kernel/`、`HarnessKernel`、`AgentLoop`、`KernelContext`、Telemetry、`POST /api/v1/chat/v2`；Checkpoint 已按工具轮次保存，支持可选 DB 冷存储和进程重启恢复 | DB 冷存储需执行 084 并开启 `CHECKPOINT_PERSISTENCE_ENABLED=1`；State Runtime/Recovery 尚未接入 |
| Phase 2 Skills | 🟡 部分完成 | `SkillRegistry`、WorkOrder/Inventory/Quality 三个 Skill，V2 采用 Skill-first；质量域已迁移不良记录和 SPC 失控查询 | PMC、BOM、设备、HR、仿真、工作流等仍走 `chat_tools_service.py` legacy fallback，约 30+ 工具尚未完成拆分 |
| Phase 3 Persistence | 🟡 基础完成 | `ChatSession/Message/Telemetry` ORM、`082_chat_engflow_persistence.sql`、持久化服务、V2/stream session_id、服务端历史自动加载、Trace/Replay、会话列表 | 历史仍按最近 50 条截断；流式链路已持久化但仍缺完整断线续传 |
| Phase 4 Permission/Event | 🟡 权限完成，事件基础完成 | V2/stream 的 `PermissionGate`；Agent Event Bus 已支持 `agent_events` 持久化、DB replay 和 `/api/v1/agent-supervisor/events` | Event Bus 持久化为可选配置；缺权限信息时当前策略仍会放行 |
| Phase 5 Review/Evidence | 🟡 基础完成 | Evidence chain、`ModelReviewer`、grounded/partial/hallucinated 分类和最多 2 次修正 | 审查分类仍含启发式逻辑，source table 证据尚未由工具统一填充，缺少持久化审查审计 |
| Phase 6 Engineering Surface | 🟡 端点已落地 | trace、replay、eval、plugins、version、model-compare、failures 共 7 类端点 | Eval 当前是单 case；Replay 主要是消息回放而非重新执行；model-compare 未走完整工具/审查链 |

**当前结论**：Chat V2 已具备可运行的 Kernel 链路和工程观测基础，但仍处于渐进迁移期；V1 保持回退，剩余 Skill 拆分、Checkpoint DB 化、生产环境 migration/配置和端到端压测完成前，不宜宣称 chatbot 架构迁移完毕。

**当前最高优先级**：完成剩余 Skill 拆分；确认生产环境执行 082/083/084 migration 并开启 Event Bus/Checkpoint 持久化；再做端到端压测和断线恢复。

## 0. Scope 界定（重要）

本方案**仅针对 Chat V2 链路**（web 端 Chat / UI / API 走 Experience Surface → Harness Kernel）。

**CLI 不在本方案范围内**，CLI 是独立的体验面，不经过 Harness Kernel。后续若需要，可复用 Phase 2 产出的 Skill 模块与 Phase 3 的 Trace/Replay，但接入点不同：
- Chat V2：Experience Surface (web) → Harness Kernel → Skills → Connector → Source Truth
- CLI：独立入口 → 直接调用 Skills（复用，不经 Kernel 的 Agent Loop / State Runtime / Permission）

> 迁移期间 Chat V1（现有 `POST /api/v1/chat`）保持可用作为回退，V2 完全稳定后再下线。

## 1. Current State Summary

> 本节保留迁移开始时的基线问题，实时完成度以第 0.1 节为准。

### 1.1 文件规模

| 文件 | 行数 | 职责 |
|------|------|------|
| `api/routes/chat_routes.py` | 1,507 | 入口端点 + LLM 调用 + grounding 验证 |
| `api/services/chat_tools_service.py` | 3,006 | 工具定义 + 执行器 + 意图规则 + 全部业务逻辑 |
| `api/services/parallel_orchestrator.py` | 853 | 并行 agent 编排（16 agent 注册） |
| `api/services/agent_supervisor_service.py` | 624 | Agent 监控心跳 |
| `core/agent/event_bus.py` | 168 | 事件总线（内存 500 条环形缓冲） |
| `core/agent/runtime.py` | — | Agent 运行时 |
| `core/agent/hooks.py` | — | 钩子拦截 |
| `api/services/chat_architecture/` (21 files) | ~800 | 未接入的重构骨架 |

### 1.2 当前请求流

```
User Input (text + images)
  │
  ▼
POST /api/v1/chat
  │
  ├─[1] 加载附件 (DB files, factory-isolated)
  │
  ├─[2] 并行编排器关键词检测 (parallel_orchestrator)
  │     ├─ "指挥官" → FactoryCommander.run_cycle()
  │     ├─ "插单" → rush_order_evaluation agents
  │     └─ 其他并行意图 → ParallelOrchestrator.execute()
  │
  ├─[3] Model Stack 路由 (Control Plane → provider/model)
  │
  ├─[4] 构建 messages[] + SYSTEM_PROMPT
  │
  ├─[5] LLM Tool-Calling Loop (MAX 5 rounds)
  │     ├─ POST → LLM Gateway (OpenAI-compatible)
  │     ├─ 有 tool_calls? → execute_tool() → append results → loop
  │     └─ 无 tool_calls? → grounding verification → return
  │
  └─[6] ChatResponse (reply, model, degraded, actions, diagrams)
```

### 1.3 关键问题

| # | 问题 | 影响 |
|---|------|------|
| P1 | **单文件 3006 行**：35+ 工具定义+执行器+意图规则全在 `chat_tools_service.py` | 不可维护，改一个工具影响全部 |
| P2 | **无会话持久化**：对话历史由前端每次全量发送，后端不存储 | 无法做 Trace/Replay/Eval |
| P3 | **三套 Agent 注册表**：`parallel_orchestrator.AGENT_REGISTRY`(16), `agent_supervisor.AGENTS`, `quick_command_service.AGENT_KEYWORD_RULES` 互不统属 | 定义冲突，行为不一致 |
| P4 | **意图路由碎片化**：4 层意图检测（keyword/LLM/parallel/quick_command），仅 2 层实际生效 | 不可预测，调试困难 |
| P5 | **无 Permission 层**：write 工具仅传 operator，无角色/权限门控 | 安全隐患 |
| P6 | **无 Checkpoint**：tool loop 中途失败无法恢复 | 可靠性差 |
| P7 | **Event Bus 仅内存**：500 条环形缓冲，无持久化，无 Trace 能力 | 无法做 Replay |
| P8 | **chat_architecture/ 骨架未接入**：`_execute_tool_loop()` 返回 placeholder | 重构半途而废 |

---

## 2. Target Architecture → Current Mapping

### 2.1 ENGFLOW 核心层映射（仅 Chat V2）

```
ENGFLOW Target (Chat V2)          Current Codebase                Status
─────────────────────────────────────────────────────────────────────────
Experience Surface
  Chat / UI / API                chat_routes.py (POST /chat/v2)  ✅ V2 已接入
  CLI                           （独立，不经过 Kernel）           ➖ 不在范围

Harness Kernel
  Agent Loop                     core/kernel/agent_loop.py        ✅ V2 已接入
  State Runtime                  chat_architecture/state/engine.py ⚠️ 已建未接入
  Context                        core/kernel/context.py            ✅
  Permission                     core/kernel/permission.py         🟡 已接入，缺权限时放行
  Recovery                       chat_architecture/recovery/      ⚠️ 骨架未接入
  Checkpoint                     core/kernel/checkpoint.py         🟡 内存热路径 + 可选 agent_checkpoints DB
  Event Bus                      core/agent/event_bus.py           🟡 内存 + agent_events DB replay
  Telemetry                      core/kernel/telemetry.py          ✅ 内存 + V2 DB 总体遥测

Capability Layer
  Skills                         core/skills/ + legacy fallback    🟡 3 个 Skill 已接入
  Capability Plugins             SkillRegistry                    🟡 WorkOrder/Inventory/Quality
  Binder/Policy                  core/kernel/permission.py         🟡 工具级权限已接入
  Connector                      ❌ 无                            🔴 待建

Model Adapters
  Model Stack Control Plane      chat_routes.py L194-265          ✅ 可用
  LLM Gateway (litellm)          chat_routes.py L268-286          ✅ 可用

Source Truth                     DB (PostgreSQL)                  ✅
Evidence                         core/kernel/evidence.py           🟡 已结构化
Model Review                     core/kernel/model_review.py        🟡 已接入 V2
Correction / Done                ModelReviewer retry               ⚠️ 有修正，无完整审计事件

Engineering Surface
  Trace                          GET /chat/trace/{request_id}       ✅
  Replay                         GET /chat/replay/{session_id}      🟡 消息回放
  Eval                           POST /chat/eval                    🟡 单 case
  Plugin Registry                GET /chat/plugins                   ✅
  Harness Version                GET /chat/version                   ✅ 0.8.0
  Model Comparison               POST /chat/model-compare             🟡 基础对比
  Failure Analysis               GET /chat/failures                   ✅ 内存 + DB
```

### 2.2 可直接复用的模块

| 模块 | 文件 | 复用方式 |
|------|------|----------|
| State Machine | `chat_architecture/state/engine.py` | 扩展状态集，接入 agent loop |
| Recovery Registry | `chat_architecture/recovery/registry.py` | 直接使用，补充策略 |
| Business Executor Registry | `chat_architecture/business_executors/executor_registry.py` | 作为 Skill 注册表基础 |
| Factory Resolver | `chat_architecture/resolvers/factory_resolver.py` | 直接使用 |
| Response Formatter | `chat_architecture/formatter/response_formatter.py` | 直接使用 |
| Event Bus | `core/agent/event_bus.py` | 扩展持久化，接入 Telemetry |
| Agent Hooks | `core/agent/hooks.py` | 扩展为 Permission 层 |
| sim_erp Plugin Pattern | `core/sim_erp/plugins/registry.py` | 作为 Plugin Registry 参考 |

---

## 3. Migration Phases

### Phase 1: Harness Kernel Skeleton（2-3 天）

**目标**：在现有 `chat_routes.py` 旁边建一个最小可运行的 Kernel，跑通一条完整链路。

**新增文件**：
```
core/kernel/
├── __init__.py
├── kernel.py              # HarnessKernel 主类
├── agent_loop.py          # Agent Loop (从 chat_routes.py 抽取)
├── context.py             # Context (请求上下文 + 工厂 + 用户 + 会话)
├── checkpoint.py          # Checkpoint (tool loop 断点恢复)
└── telemetry.py           # Telemetry (结构化日志 + metrics)
```

**具体动作**：

1. **`core/kernel/context.py`** — 定义 `KernelContext` dataclass：
   ```python
   @dataclass
   class KernelContext:
       request_id: str
       factory_id: str
       user: User
       session_id: Optional[str]       # 前端传入的会话 ID
       messages: List[Dict]             # 对话历史
       attachments: List[Dict]          # 附件
       model_route: Dict                # 模型路由信息
       permissions: Set[str]            # 用户权限集
       metadata: Dict[str, Any] = field(default_factory=dict)
   ```

2. **`core/kernel/agent_loop.py`** — 从 `chat_routes.py:840-911` 抽取 tool loop：
   - 输入：`KernelContext` + tool definitions + tool executors
   - 输出：`LoopResult(reply, tool_actions, rounds_used, grounded)`
   - 保持现有行为不变（5 轮上限、grounding verification）

3. **`core/kernel/checkpoint.py`** — tool loop 断点：
   - 每轮 tool 执行后保存 checkpoint（messages 前缀 hash + tool results）
   - 失败时可从最近 checkpoint 恢复（而非重头开始）
   - 存储：内存 dict（Phase 1），Phase 3 迁移到 DB

4. **`core/kernel/telemetry.py`** — 结构化遥测：
   ```python
   class TelemetryEvent:
       request_id: str
       phase: str          # "intent_resolve" | "tool_loop" | "grounding" | "response"
       duration_ms: float
       model: str
       tools_called: List[str]
       rounds: int
       success: bool
       error: Optional[str]
   ```
   - Phase 1：写入 logger + Event Bus
   - Phase 3：持久化到 `telemetry_events` 表

5. **`core/kernel/kernel.py`** — 主编排器：
   ```python
   class HarnessKernel:
       async def handle(self, ctx: KernelContext) -> KernelResponse:
           # 1. 意图解析 (deterministic → LLM fallback)
           # 2. 权限检查 (write tools 需要角色验证)
           # 3. Agent Loop 执行
           # 4. Checkpoint 保存
           # 5. Telemetry 上报
           # 6. 返回响应
   ```

**验证标准**：
- 现有 `/api/v1/chat` 端点行为不变（向后兼容）
- 新增 `/api/v1/chat/v2` 端点使用 Kernel 处理
- 两个端点返回相同结果（A/B 对比测试）

---

### Phase 2: Skill 模块化（3-5 天）

**目标**：将 `chat_tools_service.py` 的 35+ 工具拆分为独立 Skill 模块。

**目录结构**：
```
core/skills/
├── __init__.py
├── registry.py              # Skill 注册表 (复用 executor_registry 模式)
├── base.py                  # BaseSkill 接口
├── work_order/
│   ├── __init__.py
│   ├── skill.py             # query_work_orders, create_work_order, ...
│   └── schema.py            # 工具定义 (OpenAI function format)
├── inventory/
│   ├── skill.py
│   └── schema.py
├── production/
│   ├── skill.py
│   └── schema.py
├── quality/
│   ├── __init__.py
│   └── skill.py             # query_defects, query_spc_anomalies（已迁移）
├── pmc/
│   ├── skill.py
│   └── schema.py
├── bom/
│   ├── skill.py
│   └── schema.py
├── equipment/
│   ├── skill.py
│   └── schema.py
├── hr/
│   ├── skill.py
│   └── schema.py
├── simulation/
│   ├── skill.py
│   └── schema.py
└── workflow/
    ├── skill.py
    └── schema.py
```

**BaseSkill 接口**：
```python
class BaseSkill(ABC):
    @property
    def name(self) -> str: ...
    
    @property
    def module(self) -> str: ...  # "work_order", "inventory", etc.
    
    def get_tool_definitions(self) -> List[Dict]: ...
    
    async def execute(self, tool_name: str, args: Dict, ctx: KernelContext) -> Dict: ...
    
    def has_permission(self, tool_name: str, ctx: KernelContext) -> bool: ...
```

**具体动作**：

1. 从 `chat_tools_service.py` 提取 `TOOL_DEFINITIONS` 按 module 分组
2. 从 `chat_tools_service.py` 提取 `_TOOL_EXECUTORS` 对应函数
3. 每个 module 目录一个 Skill 类，继承 `BaseSkill`
4. `SkillRegistry` 自动发现 `core/skills/*/skill.py` 并注册
5. 删除 `chat_tools_service.py` 中已迁移的代码（保留未迁移的作为 fallback）

**验证标准**：
- 所有 35+ 工具可通过 SkillRegistry 发现和执行
- `chat_tools_service.py` 行数降至 <500（仅保留 fallback）
- 每个 Skill 可独立测试

---

### Phase 3: 会话持久化 + Trace/Replay（3-5 天）

**目标**：对话历史持久化，支撑 Trace/Replay/Eval。

**新增 DB 表**：
```sql
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factory_id VARCHAR(32) NOT NULL,
    user_id UUID REFERENCES users(id),
    title VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES chat_sessions(id),
    role VARCHAR(16) NOT NULL,           -- 'user' | 'assistant' | 'tool' | 'system'
    content TEXT,
    tool_calls JSONB,                    -- assistant 的 tool_calls
    tool_results JSONB,                  -- tool 执行结果
    model VARCHAR(64),
    tokens_used INT,
    duration_ms INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE chat_telemetry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id VARCHAR(64) NOT NULL,
    session_id UUID,
    phase VARCHAR(32),
    duration_ms FLOAT,
    model VARCHAR(64),
    tools_called JSONB,
    rounds INT,
    success BOOLEAN,
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**具体动作**：

1. 新增 `database/models.py`：`ChatSession`, `ChatMessage`, `ChatTelemetry`
2. 新增 `api/services/chat_persistence_service.py`：
   - `create_session()`, `append_message()`, `get_history()`
   - `save_telemetry()`, `get_trace()`
3. 修改 `core/kernel/context.py`：自动加载会话历史
4. 修改 `core/kernel/kernel.py`：每轮 tool 执行后 append message
5. 修改前端：传入 `session_id`（新建对话时后端创建，后续请求带入）

---

### Phase 4: Permission + Event Bus 持久化（2-3 天）

**目标**：权限门控 + 事件持久化。

**具体动作**：

1. **Permission 层** (`core/kernel/permission.py`)：
   ```python
   class PermissionGate:
       def check(self, skill: BaseSkill, tool_name: str, ctx: KernelContext) -> bool:
           # 1. 检查用户角色是否允许该工具
           # 2. 检查 write 工具的操作审计权限
           # 3. 检查 factory 作用域隔离
   ```
   - 从 `core/auth/roles.py` 的 `get_user_permissions()` 获取权限集
   - write 工具强制检查 `operator` 与 `current_user` 一致

2. **Event Bus 持久化** (`core/agent/event_bus.py` 扩展)：
   - 新增 `persist=True` 参数：emit 时同时写入 `chat_telemetry` 表
   - 新增 `replay(session_id)` 方法：从 DB 重建事件流
   - 保留内存环形缓冲作为热数据缓存

3. **Telemetry 持久化**：
   - `core/kernel/telemetry.py` 的 `TelemetryEvent` 写入 DB
   - 新增 `GET /api/v1/chat/trace/{request_id}` 端点

---

### Phase 5: Model Review + Evidence（2-3 天）

**目标**：grounding verification 升级为结构化 Evidence 链。

**具体动作**：

1. **Evidence 数据结构** (`core/kernel/evidence.py`)：
   ```python
   @dataclass
   class Evidence:
       tool_name: str
       tool_args: Dict
       tool_result: Dict
       confidence: float               # 工具返回的数据置信度
       source_tables: List[str]        # 数据来源表
       timestamp: str
   ```

2. **Model Review** (`core/kernel/model_review.py`)：
   - 现有 `_verify_grounded_reply()` 升级为结构化审查
   - 输出：`ReviewResult(verdict, issues[], evidence_chain[])`
   - verdict: `"grounded"` | `"partially_grounded"` | `"hallucinated"`

3. **Correction Loop**：
   - `hallucinated` → 自动重试（最多 2 次，带 evidence 约束）
   - `partially_grounded` → 标记 warning，返回用户
   - `grounded` → 正常返回

---

### Phase 6: Engineering Surface（2-3 天）

**目标**：运维侧可观测性。

**新增端点**：
```
GET  /api/v1/chat/trace/{request_id}     # 单次请求 trace
GET  /api/v1/chat/replay/{session_id}    # 会话回放
POST /api/v1/chat/eval                   # 批量评估
GET  /api/v1/chat/plugins                # Plugin Registry
GET  /api/v1/chat/version                # Harness 版本信息
POST /api/v1/chat/model-compare          # 模型对比测试
GET  /api/v1/chat/failures               # 失败分析
```

**具体动作**：

1. **Trace**：从 `chat_telemetry` + `chat_messages` 重建完整执行链
2. **Replay**：从 `chat_messages` 重放对话，可选重新执行 tool calls
3. **Eval**：
   - 新增 `chat_eval_cases` 表：预定义测试用例
   - `POST /eval` 批量跑用例，记录通过率/延迟/成本
4. **Plugin Registry**：`SkillRegistry.get_all()` 暴露为 API
5. **Model Comparison**：同一 prompt 路由到不同 model，对比结果
6. **Failure Analysis**：从 `chat_telemetry` 聚合失败模式

---

## 4. Migration Priority Matrix

| Phase | Value | Effort | Risk | Priority |
|-------|-------|--------|------|----------|
| Phase 1: Kernel Skeleton | 高（解耦入口） | 低（抽取不重写） | 低（向后兼容） | **P0** |
| Phase 2: Skill 模块化 | 高（可维护性） | 中 | 低 | **P0** |
| Phase 3: 会话持久化 | 高（Trace/Replay 基础） | 中 | 中（DB migration） | **P1** |
| Phase 4: Permission + Event | 中（安全性） | 低 | 低 | **P1** |
| Phase 5: Model Review | 中（质量保障） | 低 | 低 | **P2** |
| Phase 6: Engineering Surface | 中（运维可观测） | 中 | 低 | **P2** |

---

## 5. Dependency Graph

```
Phase 1 (Kernel) ──┬──→ Phase 2 (Skills) ──→ Phase 5 (Model Review)
                   │
                   └──→ Phase 3 (Persistence) ──→ Phase 6 (Engineering Surface)
                               │
                               └──→ Phase 4 (Permission + Events)
```

Phase 1 是所有后续阶段的基础。Phase 2 和 3 可并行。Phase 4 依赖 3。Phase 5 依赖 2。Phase 6 依赖 3+4。

---

## 6. Backward Compatibility Strategy

### 端点兼容
- 现有 `POST /api/v1/chat`（V1）保持不变，作为回退
- 新增 `POST /api/v1/chat/v2`（Chat V2）使用 Kernel
- 通过 feature flag（env `CHAT_V2_ENABLED=1`）切换
- Phase 2 完成后 v2 默认启用，v1 标记 deprecated，观察期后再下线
- CLI 独立不变，不参与 V2 迁移，仅复用 Skills 模块

### 工具兼容
- 所有 35+ 工具通过 `SkillRegistry` 注册，API 签名不变
- 前端无需修改（tool_calls 格式兼容 OpenAI function calling）

### 数据兼容
- Phase 3 的 DB migration 不影响现有表
- 前端增加 `session_id` 可选字段（向后兼容）

---

## 7. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Kernel 抽取引入 bug | v1/v2 双端点并行，A/B 对比验证 |
| Skill 拆分遗漏工具 | 自动化测试覆盖所有 35+ 工具 |
| DB migration 影响性能 | chat_messages 表按月分区，加 TTL |
| 事件持久化写放大 | 异步写入 + 批量提交 |
| Model Review 增加延迟 | 仅对 `hallucinated` 重试，限 2 次 |

---

## 8. Estimated Timeline

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 1: Kernel Skeleton | 2-3 天 | 2-3 天 |
| Phase 2: Skill 模块化 | 3-5 天 | 5-8 天 |
| Phase 3: 会话持久化 | 3-5 天 | 8-13 天 |
| Phase 4: Permission + Events | 2-3 天 | 10-16 天 |
| Phase 5: Model Review | 2-3 天 | 12-19 天 |
| Phase 6: Engineering Surface | 2-3 天 | 14-22 天 |

**总工期：3-4 周**（单人全职）

---

## 9. Quick Wins / Remaining Work（当前）

1. **启用 Checkpoint DB 冷存储**：代码已接入 `agent_checkpoints`，生产执行 084 migration 后设置 `CHECKPOINT_PERSISTENCE_ENABLED=1`。
2. **扩大 Skill 覆盖**：按质量、PMC、BOM、设备、HR、仿真、工作流等领域继续拆分，逐步减少 `chat_tools_service.py` fallback。
3. **将 Event Bus 持久化纳入所有生产环境**：确认 `AGENT_EVENT_PERSISTENCE_ENABLED=1` 并执行 083 migration。
4. **收敛 Engineering Surface**：把 Eval 扩展为批量用例，把 Replay 增加可选工具重执行，并让 model-compare 使用同一 V2 工具/审查链。
5. **端到端压测与断线恢复**：验证 stream/V2 的超时、重试、重复提交和大历史截断行为。
