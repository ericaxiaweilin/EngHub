# EngHub API 只读巡检报告（2026-07-28）

## 范围

- 目标：`http://100.96.188.77:18888`
- 身份：现有有效用户，工厂 `F01`
- OpenAPI GET 路由：211
- 无路径参数路由：177，全部扫描
- 带路径参数路由：34
  - 有真实数据库样本并完成扫描：16
  - 因底表为空或目标表缺失，无法构造合法详情 ID：18
- 未调用 POST、PUT、PATCH、DELETE。

## 静态 GET 扫描结果

| 结果 | 数量 | 说明 |
|---|---:|---|
| 200 | 126 | 接口返回成功 |
| 500 | 38 | 包含独立缺陷以及事务污染造成的连带失败 |
| 422 | 6 | 巡检样本参数类型不匹配，不计为服务端缺陷 |
| 400 | 2 | 缺少业务必填条件或前序 SQL 事务失败 |
| 404 | 1 | 没有审计记录，属于正常空数据 |
| 连接中断 | 4 | 并发扫描期间服务端连接被关闭，需串行复测 |

## 已确认的独立 500 根因

### 缺表

- `plans`
- `warehouses`
- `maintenance_plans`
- `maintenance_orders`
- `inventory_counts`

受影响接口包括：

- `/api/v1/plans`
- `/api/v1/warehouses`
- `/api/v1/equipment/maintenance`
- `/api/v1/equipment/maintenance-plans`
- `/api/v1/inventory/count`

### 代码引用了数据库中不存在的列

- `roles.role_code`
- `work_order_templates.module`
- `inventory.location_id`
- `inventory_transactions.inventory_id`
- `equipment_downtime.downtime_category`
- `aps_schedule_tasks.work_order_id`
- `updated_at`
- `planned_date`
- `batch_code`
- `material_code`

主要受影响模块：

- 角色管理
- 工单模板
- 库存
- 设备停机/维护
- APS
- WMS
- 自动化等级
- RCC

### UUID 与 VARCHAR 类型漂移

日志中同时存在：

- `uuid = character varying`
- `character varying = uuid`

主要影响：

- 工单详情、子工单、状态日志、全局流程
- 生产看板
- 工作流分析
- 员工资质/认证
- 工位详情
- 数据一致性对账

### 明确的 Python 代码错误

- `NameError: AndonService is not defined`
- `NameError: BomItem is not defined`
- `NameError: get_db is not defined`
- `TypeError: 'async_generator' object is not an iterator`

主要影响：

- Andon 分类
- 订单物料检查/数据一致性
- Agent/部分依赖注入接口

### 会话错误放大

部分 SQL 错误后没有正确回滚或关闭 SQLAlchemy 会话，导致后续请求出现：

- `current transaction is aborted`
- `IllegalStateChangeError: close() can't be called here`

因此首轮的 38 个 500 不能全部视为独立根因；需要先修复上述 schema/代码错误及事务边界，再做第二轮串行扫描。

## 返回 200 但为空的主要页面

以下为空是接口正常返回，但没有业务数据或当前 `F01` 没有数据：

- 产品：`products` 表 0 行
- 技能与技能矩阵：`skills`、`employee_skills`、`hr_employee_skills` 均为 0 行
- TMS：任务、审批、分配、Agent Action 均为 0 行
- Andon：`andon_tickets` 0 行
- APS：排程和排程任务 0 行
- QMS：检验、缺陷、8D、SPC、质量目标相关表大多为 0 行
- WMS：仓库、库位、批次、汇总、交易、盘点、预留均为 0 行
- 设备维护：维护任务、停机记录、设备读数均为 0 行
- 文件：`files` 0 行
- 工艺路线模板步骤：`routing_template_steps` 0 行
- 自动化等级配置：`automation_config` 0 行
- 生产线、班次、小时产出：均为 0 行
- 成本模块：人工费率、制造费用、标准成本、工单成本、差异分析均为 0 行

本次数据库共发现 358 张业务表：

- 187 张空表
- 171 张非空表

## 有数据但接口仍返回空的重点

这些更可能是工厂编码、字段映射或查询条件不一致：

- `/api/v1/stations` 返回 0，但 `stations` 表有 17 行
- `/api/v1/inspections` 返回 0，但 `inspection_tasks` 表有 105 行
- `/api/v1/orders` 返回 0，但 `sales_orders` 表有 40 行
- `/api/v1/skills` 返回空；相关员工主表有数据，但技能基础表为空
- 库存接口报错，但 `inventory` 有 25 行、`inventory_transactions` 有 89 行

## 建议修复顺序

1. 补齐或对齐数据库 migration：缺表、缺列。
2. 统一 UUID/VARCHAR 外键策略，并为历史编码数据增加兼容迁移。
3. 修复 3 个 `NameError` 和 async generator 依赖错误。
4. 所有请求级数据库会话在异常时显式 rollback，避免连带 500。
5. 对有数据但页面为空的接口统一工厂编码（当前同时出现 `F01`、`F001`、`FAC_MECH_001`）。
6. 补种产品、技能、TMS、WMS、QMS、维护等演示数据。
7. 完成修复后重新执行 211 个 GET 路由的串行回归扫描。
