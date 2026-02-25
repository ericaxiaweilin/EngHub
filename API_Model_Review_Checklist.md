# EngHub MES - API 接口模型评审与锁定清单

---

## 一、当前API设计状态评估

### 1.1 已完成的部分 ✅

```
核心业务域API:
├─ ✅ 工单管理 (Work Order)
│  ├─ 创建工单 POST /api/v1/work-orders
│  ├─ 查询工单列表 GET /api/v1/work-orders
│  ├─ 获取工单详情 GET /api/v1/work-orders/{id}
│  ├─ 更新工单 PATCH /api/v1/work-orders/{id}
│  ├─ 状态转移 (启动/完成/取消)
│  └─ 物料清单关联
│
├─ ✅ 生产报工 (Production Reporting)
│  ├─ 新增报工 POST /api/v1/production-reports
│  ├─ 查询报工 GET /api/v1/production-reports
│  ├─ 报工确认 (主管审批)
│  └─ 缺陷明细
│
├─ ✅ 检验管理 (Quality Inspection)
│  ├─ 创建检验单 POST /api/v1/inspections
│  ├─ 提交检验结果
│  ├─ 查询检验记录
│  └─ AQL判定逻辑
│
├─ ✅ 不良品管理 (Defect)
│  ├─ 创建不良品单
│  ├─ 处理不良品 (返工/返修/报废/特采)
│  └─ OCAP触发
│
├─ ✅ 工艺路线 (Routing)
│  ├─ 创建/查询工艺路线
│  ├─ 工序定义
│  └─ 参数配置
│
├─ ✅ 工位管理 (Station)
│  ├─ 工位配置
│  ├─ 产能定义
│  └─ 班次管理
│
└─ ✅ 报表查询 (Reports)
   ├─ 日报表
   ├─ 月报表
   └─ 分析统计
```

### 1.2 需要确认的部分 ❓

```
1. 工单拆分/合并 API
   - POST /api/v1/work-orders/{id}/split
   - POST /api/v1/work-orders/merge
   - 当前未详细设计，需要业务确认

2. 库存管理 API
   - 库存查询、出入库、盘点
   - 当前只有基础表结构，API未设计

3. 采购单据 API
   - 与ERP的采购单接口
   - 当前未设计

4. 成本核算 API
   - 工单成本查询
   - 产品成本分析
   - 当前未设计

5. 生产计划 (PP) API
   - MPS/MRP计算接口
   - 当前未详细设计

6. 设备管理 (EAM) API
   - 设备台账、维保计划、OEE计算
   - 当前未设计

7. 与luaguage系统的接口
   - BOM变更同步
   - PPAP状态查询
   - 用户权限同步
   - 当前为概念设计，需要具体API定义

8. 移动端/第三方集成
   - 简化的移动端API
   - OpenAPI/GraphQL接口
   - 当前未设计
```

### 1.3 API 完成度评分

```
工单系统:        ████████░░ 85% (核心功能完成，但拆分/合并待设计)
报工系统:        ██████████ 95% (基本完成)
检验系统:        ████████░░ 85% (基本功能完成)
不良品系统:      ████████░░ 80% (流程完成，处置规则待细化)
工艺管理:        ██████████ 90% (基础完成)
库存系统:        ██░░░░░░░░ 20% (只有表结构，API未设计)
采购/成本:       █░░░░░░░░░ 10% (概念设计)
生产计划:        ███░░░░░░░ 30% (概念设计)
设备管理:        ██░░░░░░░░ 20% (概念设计)
ERP集成:         ███░░░░░░░ 30% (概念方案)

整体完成度:      ███████░░░ 62%
```

---

## 二、API 设计确认清单

### 2.1 必须确认的关键点

#### A. 工单操作 (Priority: 🔴 Critical)

```
Q1: 工单是否支持拆分？
   Current: 未设计
   Options:
   a) 不支持 (简单但功能受限)
   b) 支持拆分为子工单 (推荐)
   c) 支持部分数量拆分
   
   建议: 选择 b (生产中常见需求)
   API设计:
   POST /api/v1/work-orders/{id}/split
   {
     "split_qty": 500,  // 拆分出去的数量
     "remark": "需要单独排产"
   }

Q2: 工单修改后是否需要重新排程？
   Current: 需要手动触发
   Options:
   a) 手动确认后重新排程
   b) 自动重新排程 (可能影响其他工单)
   c) 提示冲突但由用户决定
   
   建议: 选择 c (给用户控制权)
   Response需要包含: "需要重新排程" 的标志

Q3: 工单完成时是否自动生成入库建议？
   Current: 支持，但未详细设计
   Options:
   a) 自动生成入库建议
   b) 人工确认后生成
   c) 不生成，由WMS系统处理
   
   建议: 选择 b (保留控制权)
```

#### B. 报工操作 (Priority: 🔴 Critical)

```
Q1: 报工后是否自动扣减库存？
   Current: 否，库存独立管理
   Options:
   a) 报工自动扣减 (简单，风险大)
   b) 生成领料建议，WMS手动确认 (推荐)
   c) 完全独立 (灵活但复杂)
   
   建议: 选择 b
   API: POST /api/v1/production-reports/{id}/confirm
   Response需要包含: "生成领料建议"

Q2: 报工是否支持撤回或修改？
   Current: 提交后不能修改
   Options:
   a) 不支持修改 (简单)
   b) 24小时内可修改
   c) 需要主管批准才能修改 (推荐)
   
   建议: 选择 c
   API: PATCH /api/v1/production-reports/{id}
   需要权限: production_report:edit
```

#### C. 检验操作 (Priority: 🟠 High)

```
Q1: 检验是否必须挂在生产报工上？
   Current: 可以独立创建，也可关联报工
   Options:
   a) 必须关联报工
   b) 可以独立创建
   c) IPQC必须关联，IQC独立 (推荐)
   
   建议: 选择 c
   API约束: 
   - IQC: work_order_id 可为空
   - IPQC/FQC/OQC: work_order_id 必填

Q2: 不合格品是否自动创建不良品单？
   Current: 是
   Options:
   a) 自动创建 (推荐)
   b) 需要人工确认
   c) 可配置
   
   建议: 选择 a (自动化程度高)
```

#### D. 数据隔离 (Priority: 🔴 Critical)

```
Q1: 多工厂数据隔离级别？
   Current: 通过 factory_id + 查询过滤
   Options:
   a) 完全隔离，不同DB
   b) 同DB但行级安全 (当前方案)
   c) 应用层过滤
   
   建议: 保持当前方案 b
   实施: 每个查询都加 factory_id 过滤

Q2: 用户是否可以跨工厂操作？
   Current: 用户可以配置多个工厂权限
   Options:
   a) 同时只能操作一个工厂 (当前)
   b) 可以跨工厂，但要明确选择 (推荐)
   
   建议: 选择 b
   实施: Header中必须包含 X-Factory-ID
```

#### E. 错误处理 (Priority: 🟠 High)

```
Q1: API错误是否使用自定义错误码？
   Current: 使用了 (WORK_ORDER_NOT_FOUND 等)
   Options:
   a) 保持当前方案 (推荐)
   b) 改用HTTP标准码
   c) 混合使用
   
   建议: 保持当前方案

Q2: 业务规则违反时返回什么状态码？
   Current: 422 Unprocessable Entity
   Options:
   a) 400 Bad Request
   b) 422 Unprocessable Entity (当前)
   c) 409 Conflict
   
   建议: 保持当前方案
   例: 工单产能不足 → 409 Conflict
       输入参数错误 → 400 Bad Request
       业务规则违反 → 422 Unprocessable Entity
```

---

## 三、需要补充设计的 API

### 3.1 优先级 P0 (必须)

#### 库存管理 API (Inventory)

```
当前状态: 只有数据库设计，无API设计

需要设计的端点:

1. 库存查询
   GET /api/v1/inventory?material_id=MAT-001&warehouse_id=WH-01
   Response:
   {
     "material_id": "MAT-001",
     "warehouse_id": "WH-01",
     "qty": 1000,           // 总数量
     "available_qty": 950,  // 可用数量 = 总数 - 预留数
     "reserved_qty": 50,    // 预留数量 (已分配给工单)
     "batches": [
       {
         "batch_id": "BATCH-001",
         "qty": 500,
         "supplier_id": "SUP-001",
         "receive_date": "2026-02-20"
       }
     ]
   }

2. 出库
   POST /api/v1/inventory/outbound
   {
     "warehouse_id": "WH-01",
     "material_id": "MAT-001",
     "qty": 100,
     "batch_id": "BATCH-001",    // 可选，不指定则自动FIFO
     "purpose": "production",     // 生产领料
     "work_order_id": "WO-001"
   }

3. 入库
   POST /api/v1/inventory/inbound
   {
     "warehouse_id": "WH-01",
     "material_id": "MAT-001",
     "qty": 1000,
     "batch_id": "BATCH-001",
     "supplier_id": "SUP-001",
     "purchase_order_id": "PO-001",
     "cost_price": 10.5
   }

4. 库存盘点
   POST /api/v1/inventory/count
   {
     "warehouse_id": "WH-01",
     "count_date": "2026-02-24",
     "items": [
       {
         "location_id": "A-01-01",
         "material_id": "MAT-001",
         "counted_qty": 480,  // 盘点数
         "system_qty": 500    // 系统数
       }
     ]
   }
```

#### 工单拆分/合并 API

```
1. 工单拆分
   POST /api/v1/work-orders/{id}/split
   {
     "split_qty": 500,       // 拆分出来的数量
     "remark": "单独排产"
   }
   Response:
   {
     "original_work_order_id": "WO-001",
     "new_work_order_id": "WO-002",
     "original_qty": 500,
     "split_qty": 500
   }

2. 工单合并
   POST /api/v1/work-orders/merge
   {
     "work_order_ids": ["WO-002", "WO-003"],
     "target_work_order_id": "WO-001"  // 合并到哪个工单
   }
   Response:
   {
     "merged_to": "WO-001",
     "merged_from": ["WO-002", "WO-003"],
     "total_qty": 1500
   }
```

### 3.2 优先级 P1 (重要)

#### 与luaguage的同步 API

```
当前状态: 概念设计，需要具体实现

1. BOM同步/查询
   GET /api/v1/bom/products/{product_id}
   Response:
   {
     "product_id": "PROD-001",
     "bom_version": "V2.0",
     "created_at": "2026-02-01",
     "materials": [
       {
         "material_id": "MAT-001",
         "qty": 10,
         "ppap_status": "APPROVED"
       }
     ]
   }

2. BOM变更通知
   当luaguage中BOM更新时，是否需要主动通知？
   Options:
   a) Webhook回调
   b) 定时轮询 (简单)
   c) 消息队列事件
   
   建议: 选择 c (最可靠)

3. PPAP认证状态查询
   GET /api/v1/ppap/material/{material_id}
   Response:
   {
     "material_id": "MAT-001",
     "ppap_status": "APPROVED",
     "approval_date": "2025-12-01"
   }

4. 权限同步
   是否每个API调用都检查luaguage权限？
   Options:
   a) 每次都查询 (安全但慢)
   b) 本地缓存5分钟
   c) 事件驱动更新 (推荐)
   
   建议: 选择 c
```

#### 生产计划 (PP) API

```
1. 计划查询
   GET /api/v1/plans?from_date=2026-03-01&to_date=2026-03-31

2. MRP建议
   GET /api/v1/mrp/suggestions?plan_id=PLAN-001
   Response包含: 采购建议、库存预警

3. 产能规划
   GET /api/v1/capacity/analysis?from_date=...&to_date=...
   Response: 各工位的负荷分析、瓶颈工序
```

### 3.3 优先级 P2 (可选)

```
- 设备管理 (EAM) API
- 成本核算 API
- 供应商协作 API
- 移动端简化API
- GraphQL接口
```

---

## 四、API 契约确认矩阵

### 4.1 需要与业务方确认的 API 设计

| # | API 类型 | 当前状态 | 是否已确认 | 备注 |
|---|---------|--------|---------|------|
| 1 | 工单CRUD | 完整 | ❓ 需确认 | 是否支持拆分/合并 |
| 2 | 报工 | 完整 | ❓ 需确认 | 是否支持修改/撤回 |
| 3 | 检验 | 完整 | ❓ 需确认 | IQC是否独立创建 |
| 4 | 不良品 | 完整 | ❓ 需确认 | 处置流程是否完整 |
| 5 | 库存 | 无 | ❌ 未设计 | 需要补充 |
| 6 | BOM同步 | 概念 | ❌ 未确认 | 同步方式待定 |
| 7 | 成本计算 | 无 | ❌ 未设计 | 需要业务规则 |
| 8 | 生产计划 | 无 | ❌ 未设计 | 需要补充 |
| 9 | 权限控制 | 部分 | ❓ 需确认 | 细粒度权限模型 |
| 10 | 数据隔离 | 完整 | ✅ 已确认 | 多工厂/多租户 |

---

## 五、锁定 API 设计的步骤

### 5.1 建议的流程 (2-3周)

#### Week 1: 内部评审
```
Day 1-2: 
  - 技术团队内部评审当前API设计
  - 识别缺口和问题
  - 准备评审文档

Day 3-5:
  - 完成补充设计 (库存、工单拆分等)
  - 准备API规范文档 (OpenAPI/Swagger)
  - 准备demo系统
```

#### Week 2: 业务方评审
```
Day 1-2:
  - 与业务方讨论关键业务流程
  - 确认API设计是否满足业务需求
  - 收集反馈和修改建议

Day 3-5:
  - 修改API设计
  - 再次评审
  - 签署API契约
```

#### Week 3: 最终锁定
```
Day 1-3:
  - 完成OpenAPI文档
  - 生成API Mock服务
  - 前后端开发人员培训

Day 4-5:
  - 冻结API (锁定版本)
  - 开始开发
```

### 5.2 需要产出的文档

```
[] 1. API 规范文档 (OpenAPI 3.0 YAML)
   - 所有端点的完整定义
   - 请求/响应 schema
   - 错误码定义
   
[] 2. API 业务规则文档
   - 各API的前置条件
   - 后置条件
   - 约束条件
   
[] 3. API 集成指南
   - 认证方法
   - 错误处理
   - 重试策略
   
[] 4. API 评审意见单
   - 业务方签名确认
   - 已解决的问题列表
   
[] 5. API Mock 服务
   - 用于前端开发
   - 用于测试
```

---

## 六、API 设计决策记录

### 6.1 已做出的决策 ✅

```
✅ 使用 RESTful API (不使用GraphQL)
✅ 使用 JWT 认证
✅ 使用工厂ID (X-Factory-ID) 进行多租户隔离
✅ 使用 422 状态码表示业务规则违反
✅ API 版本化: /api/v1/
✅ 使用 ISO 8601 时间格式
✅ 使用 PascalCase 的错误码
```

### 6.2 待决策项目

```
❓ 是否支持工单拆分/合并？
   优先级: 🔴 Critical
   deadline: 必须在第一周确认   支持
   
❓ 库存扣减时机（报工时还是生成报工单时）？
   优先级: 🔴 Critical
   deadline: 必须在第一周确认。    报工单时
   
❓ BOM变更是否自动同步到已下达工单？
   优先级: 🟠 High
   deadline: 第一周确认     批准 
   
❓ 是否需要工单审批流程？
   优先级: 🟠 High
   deadline: 第一周确认   批准 
   
❓ OCAP是否自动触发还是手动创建？
   优先级: 🟡 Medium
   deadline: 第二周确认    自动
```

---

## 七、建议行动计划

### 立即行动 (今天)

```
1. ✅ 与product owner/业务主管确认:
   - API设计的完成度是否可以接受
   - 是否需要补充库存、采购等API
   - 最优先需要完成的API是什么
   
2. ✅ 准备evaluation sheet:
   - 列出当前完成的所有API
   - 列出待补充的API
   - 预估完成周期

3. ✅ 确认开发优先级:
   P0 (必须): 工单、报工、检验、库存
   P1 (重要): 不良品、计划、成本
   P2 (可选): 设备、供应商、移动端
```

### Week 1 行动

```
1. 完成缺失API的详细设计 (库存、拆分等)
2. 生成完整的 OpenAPI 规范
3. 与业务方进行第一轮评审
4. 根据反馈修改设计
```

### Week 2-3 行动

```
1. 最终确认API设计
2. 生成API文档和Mock服务
3. 前后端开发培训
4. 开始编码实现
```

---

## 八、API 模型冻结检查清单

```
API 设计完整性:
  [ ] 核心业务流程 (工单→报工→检验→入库) 完整
  [ ] 所有CRUD操作都已定义
  [ ] 状态转移逻辑明确
  [ ] 错误处理完整

API 文档完整性:
  [ ] OpenAPI 规范 v3.0 已生成
  [ ] 所有参数已文档化
  [ ] 所有返回值已定义
  [ ] 错误码已列举

业务规则清晰:
  [ ] 权限控制规则明确
  [ ] 数据隔离策略明确
  [ ] 业务约束条件明确
  [ ] 数据校验规则明确

与系统集成:
  [ ] 与luaguage的接口明确
  [ ] 消息队列事件定义明确
  [ ] 缓存策略明确
  [ ] 日志记录规范明确

团队对齐:
  [ ] 前端团队已理解API设计
  [ ] 后端团队已确认实现方案
  [ ] QA团队已准备测试用例
  [ ] 业务方已确认并签署
```

---

## 总结：API 设计状态

| 方面 | 当前状态 | 建议 |
|------|--------|------|
| **核心MES API** | ✅ 85%完成 | 可以开始开发 |
| **库存/采购API** | ❌ 0%完成 | 需要本周内补充 |
| **业务规则** | ⚠️ 部分不清晰 | 需要业务确认 |
| **文档完整度** | ⚠️ 需要OpenAPI | 需要本周内生成 |
| **模型锁定** | ❌ 未锁定 | 建议Week 2锁定 |

**建议:** 
1. **本周内** 与业务方确认上述8个关键问题
2. **下周一** 完成库存、拆分等缺失API设计
3. **下周三** 完成OpenAPI文档并评审
4. **下周五** 冻结API，开始开发
