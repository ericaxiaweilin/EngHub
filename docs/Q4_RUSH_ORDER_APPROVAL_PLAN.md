# Q4 插单审批流改造方案

日期： 2026-08-11
范围： APS 插单决策全链路（评估 → 提报 → 审批 → 执行 → 留痕）
目标： 解决审计 Q4 判决——"插单谁拍板"从计划员个人裁量，变为**决策权分配 + 审批流 + 落库留痕**

---

## 1. 现状与根因（代码证据）

| 环节 | 现状 | 代码位置 | 问题 |
|---|---|---|---|
| 影响评估 | `/api/v1/aps/rush-order-impact` 只算不落库 | `aps_routes.py:873-972` | 结果不持久化，无单号、无状态、无审批人 |
| 紧急单处理 | `priority in (urgent, emergency)` → 直接 `auto_reschedule` 全厂重排 | `scheduling_agent_service.py:60-65` | **绕过审批**，可能冲掉别人交期无人审 |
| 普通插单 | `/reschedule` 直接生成新排程版本 | `aps_service.py:1018-1051` | 无决策审批，任何人 `pp.edit` 即可改 |
| 变更审批 | `plan_change_requests` 表 0 行 | `core/pp/change_management.py` | **纯内存实现**（`self._requests={}`），请求创建即丢，从不落库——这是 0 采用的根因 |
| 留痕基建 | `wo_status_logs` 表存在但 0 行 | `models.py:335-349` | 状态变更不写日志 |
| 权限基建 | `pp.approve` 已存在；`production_manager`/`production_director` 均持有 `pp.approve` | `006_rbac_tables.sql:142,193,223` | **可直接复用**，无需新建权限 |

**根因一句话**：评估工具是"算完就完"的无状态函数，决策动作没有对应的审批单据实体，审批又缺持久化引擎——三层都断，所以"谁拍板、怎么批、批了什么"全无痕。

---

## 2. 方案总览

新增一张审批单据表 `rush_order_approvals`（插单/急单统一走"评估→提报→审批→执行"闭环），同时：

1. **评估结果落库**：`rush-order-impact` 计算结果保存为审批单草稿（含受影响订单快照）
2. **决策权分配**：按影响等级 + 插单优先级绑定审批角色（见 §4 矩阵）
3. **审批引擎**：新建 `core/pp/rush_approval_service.py`（DB 持久化，修复 change_management 纯内存的历史问题）
4. **执行挂钩**：`scheduling_agent_service` 的紧急自动重排改为**先过审批单**；`/reschedule` 校验有已批审批单
5. **审批动作留痕**：写入 `wo_status_logs` + 审批记录，前端可查

状态机：

```
draft（评估完成，草稿）
  → submitted（计划员提报）
    → approved（审批人通过）→ executed（调度已执行重排）
    → rejected（审批人驳回）→ closed（可查看原因）
  → cancelled（计划员撤销）
```

---

## 3. 数据模型（新迁移 `068_rush_order_approvals.sql`）

```sql
CREATE TABLE IF NOT EXISTS rush_order_approvals (
    id                VARCHAR(36) PRIMARY KEY,
    approval_code     VARCHAR(50) NOT NULL UNIQUE,      -- RA-20260811-XXXXXX
    factory_id        VARCHAR(50) NOT NULL,
    -- 插单信息
    product_id        VARCHAR(50) NOT NULL,
    quantity          INTEGER NOT NULL,
    due_date          DATE,
    rush_priority     VARCHAR(20) NOT NULL DEFAULT 'urgent',  -- urgent / emergency
    -- 评估快照（rush-order-impact 结果）
    impact_json       JSONB,       -- 受影响订单清单+延迟，原始快照
    affected_orders   INTEGER DEFAULT 0,
    max_delay_days    NUMERIC(8,2) DEFAULT 0,
    process_hours     NUMERIC(10,2),
    recommendation    TEXT,
    -- 审批级别与决策权
    approval_level    INTEGER NOT NULL DEFAULT 2,   -- 1/2/3 对应 §4 矩阵
    required_role     VARCHAR(50),                  -- 审批人角色编码（决策权分配落库）
    -- 流程状态
    status            VARCHAR(20) NOT NULL DEFAULT 'draft',
    applicant         VARCHAR(50),                  -- 申请人（计划员 username）
    approver          VARCHAR(50),                  -- 审批人（username）
    approved_at       TIMESTAMP,
    reject_reason     TEXT,
    -- 执行挂钩
    target_schedule_id VARCHAR(36),                 -- 重排后的新排程版本
    target_wo_id      VARCHAR(36),                  -- 生成的插单工单
    executed_at       TIMESTAMP,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_roa_factory_status ON rush_order_approvals(factory_id, status);
CREATE INDEX IF NOT EXISTS idx_roa_applicant     ON rush_order_approvals(applicant);
CREATE INDEX IF NOT EXISTS idx_roa_required_role ON rush_order_approvals(required_role);
```

审批记录（多步/会签可选，先单级）：

```sql
CREATE TABLE IF NOT EXISTS rush_order_approval_logs (
    id           VARCHAR(36) PRIMARY KEY,
    approval_id  VARCHAR(36) NOT NULL REFERENCES rush_order_approvals(id),
    action       VARCHAR(20) NOT NULL,   -- submit / approve / reject / cancel / execute
    actor        VARCHAR(50) NOT NULL,   -- username
    actor_role   VARCHAR(50),
    comment      TEXT,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
```

> 说明：`rush_order_approvals` 是新审批单实体；复用 `wo_status_logs` 记工单状态动作，复用 `aps_schedules.approved_by/released_by` 记排程审批链。三张表共同构成"谁批了插单、批完执行了哪版排程、工单怎么变"的完整追溯。

---

## 4. 决策权分配矩阵（核心）

按 **插单优先级** × **影响等级** 决定审批人，映射到现有 RBAC 角色（全部已有 `pp.approve`，零新权限）：

| 影响等级 | 判定条件 | 审批人角色 | 对应角色 code |
|---|---|---|---|
| L1 | 无受影响订单 或 最大延迟 ≤ 24h，且插单自身可按期 | 计划主管（self-approve，需写原因） | `planner` / `production_manager` |
| L2 | 最大延迟 ≤ 72h（1-3 天） | 生产经理 | `production_manager` |
| L3 | 最大延迟 > 72h，**或插单为 emergency**，**或影响高客户等级订单** | 生产处长 / 厂长 | `production_director` / `factory_manager` |

规则：
- 影响等级由后端按评估快照自动计算并写 `approval_level`/`required_role`
- **紧急插单（emergency）无论影响大小，强制 L3**——因为全厂重排不可逆
- 审批人不得与申请人为同一人（防自我审批）；L1 例外需说明原因
- 审批通过后由系统按审批单执行重排，人工不能再绕过 `/reschedule`

---

## 5. API 设计（`aps_routes.py` 扩展）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/v1/aps/rush-order/approvals` | `pp.view` | 运行评估并生成**审批单草稿**（改造现有 rush-order-impact，落库 impact_json） |
| GET | `/api/v1/aps/rush-order/approvals` | `pp.view` | 分页列表，支持 `status`/`factory_id` 过滤，按申请人或待我审批视图 |
| GET | `/api/v1/aps/rush-order/approvals/{id}` | `pp.view` | 详情（含 impact_json 全量受影响订单） |
| POST | `/api/v1/aps/rush-order/approvals/{id}/submit` | `pp.create` | 计划员提报，锁定草稿进入待审 |
| POST | `/api/v1/aps/rush-order/approvals/{id}/approve` | `pp.approve` | 审批通过（校验角色 + 非本人）→ 触发重排 |
| POST | `/api/v1/aps/rush-order/approvals/{id}/reject` | `pp.approve` | 驳回，必填 reason |
| POST | `/api/v1/aps/rush-order/approvals/{id}/cancel` | `pp.edit` | 申请人撤销 |

审批通过动作（`approve` 内部）：
1. 校验 `required_role` 与当前用户角色
2. 校验 `approver != applicant`（L1 除外）
3. 调 `scheduling_agent_service.auto_reschedule`（紧急）或 `aps_service.reschedule` 生成新排程版本
4. 写 `target_schedule_id` + `status=executed` + 审批日志 + `wo_status_logs`

`/reschedule` 改造：要求 `body.approval_id` 存在且状态为 `executed` 才放行，否则 403——封死绕过路径。

`scheduling_agent_service` 改造（`on_work_order_released` 60-65 行）：
- urgent/emergency 工单不再直接重排，改为：查同产品/同单是否有已批 `rush_order_approvals`，有→执行；无→生成草稿并通知待审批人，**不重排**。

---

## 6. 前端改造

| 页面 | 改动 |
|---|---|
| `PmcWorkbench.tsx` | 新增"插单审批"Tab：待审列表（按 `required_role` 匹配当前用户）+ 草稿列表 + 详情抽屉（受影响订单表 + 建议）+ 通过/驳回/撤销按钮 |
| `SchedulingCenter.tsx` | "插单重排"按钮改为"插单评估→生成审批单"，展示审批单号与状态，审批通过前禁止直接重排 |
| `frontend/src/services/aps.ts` | 新增 7 个接口的 service 方法 |

---

## 7. 落地步骤与验证

1. **迁移**：新增 `068_rush_order_approvals.sql`，在测试库执行
2. **服务层**：`core/pp/rush_approval_service.py`（DB 持久化审批引擎，含状态机 + 角色校验 + 日志）
3. **API**：`aps_routes.py` 新增 7 端点；改造 rush-order-impact 落库；`/reschedule` 加审批校验
4. **调度挂钩**：`scheduling_agent_service.py` 紧急单改走审批单
5. **前端**：PmcWorkbench Tab + SchedulingCenter 按钮改造
6. **测试**：新增 `tests/test_rush_approval_flow.py`，覆盖状态机全路径 + 角色越权 403 + 自我审批拒绝 + 紧急单无审批不重排
7. **验收**：跑一条流程——建草稿→提报→生产经理批→确认重排→`wo_status_logs` 有记录；紧急单未批不触发 auto_reschedule

> ⚠️ **前置清理**：当前工作区未提交改动污染（85 个文件 M，分支 `codex/pmc-workbench-data-closure`）。落地前建议先 `git stash` 或提交，避免与运行版（git HEAD 完整版）混线，误 rebuild 丢 PMC 功能。

---

## 8. 风险与后续

- **风险**：紧急单改为"先批后排"会增加响应延迟（从秒级到分钟级）——若客户要极速插单，可加"先占产能后补审批"的 parallel 模式（L2 内）
- **关联项**：本方案与 Q2（ATP 校准）、Q6（统一计划视图）共享 `impact_json` 快照数据，后续主计划驾驶舱可直接引用
- **长期**：审批通过数据可回流校准插单评估模型（真实延迟 vs 预估延迟），闭环迭代
