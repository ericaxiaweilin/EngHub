# EngHub MES系统 - 架构设计补充方案

---

## 一、整体架构分层设计

### 1.1 推荐架构模式：微服务 + 事件驱动混合

```
┌─────────────────────────────────────────────────────────────┐
│                        前端层 (Frontend)                      │
│  PC端(管理后台) | 移动端(报工/检验) | 大屏看板(可视化)      │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                    API网关 (API Gateway)                      │
│  - 请求路由、限流、认证、日志记录                            │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│              微服务层 (Microservices)                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ MES      │ │ PP       │ │ QMS      │ │ EAM      │       │
│  │ Service  │ │ Service  │ │ Service  │ │ Service  │ ...   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│                                                               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ User     │ │ Notif    │ │ Report   │ ...                │
│  │ Service  │ │ Service  │ │ Service  │                    │
│  └──────────┘ └──────────┘ └──────────┘                    │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
┌───────▼──────┐  ┌──────▼──────┐  ┌──────▼──────────┐
│  事件驱动总线  │  │ 缓存层       │  │ 数据库层         │
│ (Message Bus) │  │(Redis)      │  │(PostgreSQL)     │
│ - RabbitMQ   │  │ - Session   │  │ - 主从复制       │
│ - Kafka      │  │ - Cache     │  │ - 分表分库       │
└───────┬──────┘  └──────┬──────┘  │ - 行级安全(RLS)  │
        │                │         └──────┬──────────┘
        │                │                │
        └────────────────┼────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
    ┌───▼────┐                    ┌──────▼──────┐
    │ 文件存储 │                    │ 监控告警     │
    │ (S3/OSS)│                   │系统(ELK/    │
    │         │                   │Prometheus)  │
    └─────────┘                   └─────────────┘
```

---

## 二、关键组件设计

### 2.1 API网关设计

```
API Gateway 职责:
├── 请求路由 (根据URL/域名转发到对应微服务)
├── 速率限制 (防止刷单: 工单API 100req/min, 报工API 200req/min)
├── 认证授权 (JWT验证、权限检查)
├── 请求日志 (所有API调用记录)
├── 熔断降级 (下游服务故障时的降级策略)
└── 请求重写 (如添加租户ID、工厂ID等上下文)

实现方式:
- Nginx + Lua (轻量、高性能)
- 或 Kong/Envoy (功能完整)
```

### 2.2 微服务划分

```
MES Service (生产执行)
├── work_order_service
│   ├── 工单CRUD
│   ├── 工单状态机管理
│   ├── 工单与订单关联
│   └── 发布事件: WorkOrderCreated, WorkOrderStarted, WorkOrderCompleted
├── reporting_service
│   ├── 产量报工
│   ├── 报工验证 (数量校验、工单状态校验)
│   ├── 报工冲突检测
│   └── 发布事件: ProductionReported, DefectReported
├── routing_service
│   ├── 工艺路线管理
│   ├── 工序定义
│   └── 标准工时维护
└── station_service
    ├── 工位/产线配置
    ├── 班次管理
    └── 产能定义

PP Service (生产计划)
├── mps_service (主生产计划)
├── mrp_service (物料需求)
└── capacity_service (产能规划)

QMS Service (品质管理)
├── inspection_service (来料/过程/成品检验)
├── defect_service (不良品管理)
└── ocap_service (纠正措施)

EAM Service (设备管理)
├── equipment_service (设备台账)
├── maintenance_service (维保计划)
└── oee_service (OEE计算)

共享服务 (与luaguage共享/接口调用)
├── user_service (权限认证)
├── bom_service (物料清单)
├── notification_service (通知)
└── document_service (文档管理)
```

---

## 三、事件驱动架构设计

### 3.1 核心事件流

```
典型流程: 创建工单 → 报工 → 质量检验 → 完工入库

1. WorkOrderCreated (工单创建)
   ├─> PP Service 订阅 → 生成MRP建议采购
   ├─> MES Service → 分配工位产能
   └─> Notification Service → 发送给生管通知

2. ProductionReported (生产报工)
   ├─> MES Service → 更新工单进度
   ├─> QMS Service → 触发IPQC检验
   ├─> Report Service → 汇总日报数据
   └─> Cache → 更新看板缓存

3. DefectReported (不良品报告)
   ├─> QMS Service → 记录不良类型统计
   ├─> OCAP Service → 判断是否触发纠正措施
   ├─> Notification Service → 通知品质主管
   └─> SQE Service → 更新供应商评分

4. WorkOrderCompleted (工单完成)
   ├─> Warehouse Service → 生成成品入库建议
   ├─> Cost Service → 计算工单成本
   ├─> Report Service → 生成完工报告
   └─> ERP/Sales → 反馈订单状态
```

### 3.2 事件消息格式

```json
{
  "event_id": "evt-20260224-001",
  "event_type": "ProductionReported",
  "timestamp": "2026-02-24T10:30:00Z",
  "tenant_id": "tenant-001",
  "factory_id": "factory-sh-01",
  "source_service": "reporting_service",
  "data": {
    "work_order_id": "WO-20260224-001",
    "product_id": "PROD-A001",
    "good_qty": 100,
    "defect_qty": 5,
    "defect_types": ["短路", "漏焊"],
    "produced_by": "emp-001",
    "station_id": "ST-SMT-01",
    "shift": "day",
    "report_time": "2026-02-24T10:25:00Z"
  },
  "version": "1.0"
}
```

### 3.3 消息队列选型

```
RabbitMQ (推荐用于微服务间的同步/异步通信)
├── 优点: 可靠性高、事务支持、管理界面完善
├── 用途: MES工单报工、工单状态通知
└── 配置: 3个实例集群 + 消息持久化

Kafka (推荐用于高吞吐量的事件流)
├── 优点: 超高吞吐量、分布式、天然支持事件追溯
├── 用途: 生产报工大量数据、品质统计分析
└── 配置: 3 Broker + 3 Zookeeper + Topic分区

Redis Streams (可选，轻量级事件流)
├── 优点: 部署简单、与缓存共用Redis
├── 用途: 看板实时更新、用户活动追踪
└── 配置: 与Redis缓存一起部署
```

---

## 四、数据流架构设计

### 4.1 读写分离设计

```
MySQL主从结构:
┌─────────────┐
│ Master DB   │ (写操作)
│ PostgreSQL  │
└────────┬────┘
         │ 主从复制
    ┌────▼─────────────────────┐
    │                           │
┌───▼──────┐           ┌────────▼───┐
│ Slave-1  │           │ Slave-2    │ (读操作)
│ (只读)   │           │ (只读)     │
└──────────┘           └────────────┘

应用层:
├── 写操作: 直接连Master
│   - 工单创建/编辑
│   - 报工记录
│   - 检验结果
├── 强一致性读: Master
│   - 工单详情查询 (刚创建后立即查询)
│   - 库存查询 (需精确)
└── 最终一致性读: Slave
    - 报表查询 (容忍1-2秒延迟)
    - 看板数据 (容忍3-5秒延迟)
    - 分析统计
```

### 4.2 缓存分层设计

```
L1 - Redis缓存 (业务数据缓存)
├── 工单基本信息: key=work_order:{wo_id}
├── 工单产能: key=station_capacity:{station_id}:{date}
├── 当前班次看板: key=shift_board:{shift_id}:{date}
├── 员工信息: key=user:{user_id}
└── 产品BOM: key=product_bom:{product_id}:{version}
    超时: 热数据 30分钟，冷数据 2小时

L2 - 本地内存缓存 (配置/字典缓存)
├── 不良类型字典 (加载一次，应用启动)
├── 班次定义 (变更频率低)
├── 权限检查 (应用级缓存)
└── 超时: 应用内 5分钟 + 热更新

L3 - CDN缓存 (前端资源)
├── 静态文件 (JS/CSS/图片)
└── 超时: 1小时 + 版本管理

缓存失效策略:
├── TTL自动过期
├── 主动更新: 工单编辑时删除相关缓存
├── 事件驱动: 监听消息队列更新缓存
└── 预热: 应用启动时加载热数据
```

### 4.3 数据流向示例

```
场景: 用户报工

1. 前端发起报工请求
   POST /api/v1/production/report
   {workOrderId, goodQty, defectQty, ...}

2. API Gateway
   ├─ 认证 (JWT验证)
   ├─ 鉴权 (检查工单查看权限)
   └─ 请求转发到 reporting_service

3. Reporting Service (业务逻辑)
   ├─ 查询工单信息 (从Redis缓存读)
   ├─ 数量校验 (不超过计划数)
   ├─ 工单状态校验 (必须在生产中)
   ├─ 存储报工记录 (写入Master DB)
   ├─ 发布事件 (发送ProductionReported到消息队列)
   └─ 返回结果

4. 事件驱动链
   ├─ MES Service 消费事件
   │   └─> 更新工单完成度 (写Master DB)
   │   └─> 删除缓存: key=work_order:{wo_id}
   ├─ QMS Service 消费事件
   │   └─> 如有不良，创建检验任务
   ├─ Report Service 消费事件
   │   └─> 生成日报汇总数据 (写Reporter DB)
   └─ Cache Service 消费事件
       └─> 更新看板缓存 key=shift_board:{shift}

5. 前端看板获取数据
   GET /api/v1/dashboard/shift-board
   ├─ 从Redis读看板缓存 (毫秒级)
   └─ 返回JSON给前端展示
```

---

## 五、数据库架构设计

### 5.1 表设计规范 (分表策略)

```
大表分表策略 (按时间/业务维度分表):

production_reports (生产报工) - 按月分表
├── production_reports_202601
├── production_reports_202602
├── production_reports_202603
└── 目的: 降低单表大小、提升查询性能

inspection_records (检验记录) - 按季度分表
├── inspection_records_q1_2026
├── inspection_records_q2_2026
└── 目的: 支持大量检验数据

defects (不良品记录) - 按工厂/产线分表
├── defects_factory_sh_01
├── defects_factory_bj_01
└── 目的: 多工厂隔离，支持分布式

inventory (库存) - 不分表但加分区索引
├── 按warehouse_id+location_id建立覆盖索引
└── 支持并发查询库存
```

### 5.2 索引设计

```
work_orders 表:
├── 主键: id (聚集索引)
├── 索引1: (factory_id, status, due_date) - 工单查询
├── 索引2: (sales_order_id) - 订单关联
├── 索引3: (product_id, created_at) - 产品历史查询
├── 索引4: (station_id, start_time) - 工位排程

production_reports 表:
├── 主键: id
├── 索引1: (work_order_id, report_time) - 工单报工查询
├── 索引2: (user_id, created_at) - 员工报工统计
├── 索引3: (station_id, shift_date, shift) - 班次看板
├── 索引4: (factory_id, created_at) - 工厂日报

inventory 表:
├── 主键: (warehouse_id, material_id, location_id)
├── 索引1: (material_id, warehouse_id) - 物料库存查询
├── 索引2: (batch_id) - 批次追溯
└── 索引3: (supplier_id) - 供应商追溯
```

### 5.3 分布式事务处理

```
场景: 报工成功后，需同时更新 work_orders 和 production_reports

方案选择: 最终一致性 (推荐)

实现:
1. 报工数据先写入production_reports (主表)
   ├─ 返回成功给前端
   └─ 发布ProductionReported事件

2. 异步更新相关表
   ├─ work_orders (工单进度)
   ├─ work_centers (工位产能)
   └─ 如果事务失败，通过补偿机制修复

补偿机制:
├─ 如果work_orders更新失败
│  └─> 发布补偿事件，重试3次 (指数退避)
├─ 超过3次重试
│  └─> 人工干预，记录告警日志
└─ 保证最终一致性 (通常在1分钟内)

避免分布式锁:
├─ 尽量用版本号(乐观锁)
├─ 不用悲观锁(影响性能)
└─ 冲突日志记录供后续分析
```

---

## 六、集成架构设计 (与luaguage)

### 6.1 集成拓扑图

```
                    ┌──────────────┐
                    │  luaguage    │
                    │  (ERP主系统) │
                    └──────┬───────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
        ┌───▼────┐  ┌──────▼────┐  ┌─────▼────┐
        │  BOM   │  │  PPAP     │  │   权限    │
        │ Service│  │ Service   │  │ Service  │
        └────────┘  └───────────┘  └──────────┘
            │              │              │
      ┌─────┴──────┬───────┴──┬─────────┬┘
      │            │          │         │
  ┌───▼────┐  ┌────▼──┐  ┌────▼──┐  ┌──▼───┐
  │ EngHub │  │ Cache │  │ Queue │  │ Log  │
  │ MES    │  │ Sync  │  │ Sync  │  │ Sync │
  └────────┘  └───────┘  └───────┘  └──────┘
      │
      └─────────────> 多个工厂实例部署
```

### 6.2 集成接口规范

```
接口1: BOM信息查询 (实时同步)
GET /api/v1/bom/product/{product_id}/version/{version}
Response:
{
  "product_id": "PROD-A001",
  "bom_version": "V2.0",
  "materials": [
    {"material_id": "MAT-001", "qty": 10, "unit": "pcs"},
    {"material_id": "MAT-002", "qty": 5, "unit": "pcs"}
  ]
}
缓存: 30分钟 (BOM变更频率低)

接口2: PPAP认证状态查询 (定时同步)
GET /api/v1/ppap/material/{material_id}
Response:
{
  "material_id": "MAT-001",
  "ppap_status": "APPROVED",  // APPROVED/PENDING/REJECTED
  "approval_date": "2025-12-01"
}
缓存: 2小时

接口3: 用户权限查询 (实时同步+缓存)
GET /api/v1/auth/user/{user_id}/permissions
Response:
{
  "user_id": "emp-001",
  "roles": ["production_manager"],
  "factories": ["factory-sh-01", "factory-bj-01"],
  "permissions": ["work_order:create", "report:view"]
}
缓存: 5分钟

接口4: 发送工单完成通知 (推送)
POST /api/v1/notifications/send
Body:
{
  "type": "work_order_completed",
  "recipient_id": "emp-001",
  "data": {
    "work_order_id": "WO-20260224-001",
    "completion_rate": 95
  }
}
```

### 6.3 集成容错方案

```
luaguage服务故障时的降级策略:

1. BOM Service 不可用
   ├─ 使用本地缓存BOM
   ├─ 允许继续报工(已启动的工单)
   ├─ 禁止创建新工单
   └─ 告警通知管理员

2. PPAP Service 不可用
   ├─ 默认认为未通过认证
   ├─ 不允许采购新物料
   ├─ 禁止下达包含新物料的工单
   └─ 记录日志，待恢复后检查

3. 权限Service不可用
   ├─ 使用上次缓存的权限
   ├─ 允许继续操作(基于缓存权限)
   ├─ 不允许权限变更操作
   └─ 超过5分钟未恢复则要求重新登录

重试策略: 3次重试 + 指数退避
├── 第1次: 立即
├── 第2次: 延迟2秒
├── 第3次: 延迟4秒
└── 失败后降级处理
```

---

## 七、部署架构设计

### 7.1 容器化部署 (Docker + Kubernetes)

```
Kubernetes集群架构:

┌───────────────────────────────────────────┐
│  Kubernetes Cluster (3 Master Nodes)      │
├───────────────────────────────────────────┤
│  ┌─────────────────────────────────────┐ │
│  │  Namespace: EngHub-Prod             │ │
│  ├─────────────────────────────────────┤ │
│  │  Deployment: MES Service (3副本)    │ │
│  │  Deployment: PP Service (2副本)     │ │
│  │  Deployment: QMS Service (2副本)    │ │
│  │  Deployment: API Gateway (3副本)    │ │
│  │  StatefulSet: PostgreSQL (1主2从)   │ │
│  │  StatefulSet: Redis (1主2从)        │ │
│  │  StatefulSet: RabbitMQ (3集群)      │ │
│  │  DaemonSet: Prometheus Agent        │ │
│  └─────────────────────────────────────┘ │
│                                           │
│  ┌─────────────────────────────────────┐ │
│  │  Namespace: Monitoring              │ │
│  ├─────────────────────────────────────┤ │
│  │  ELK Stack (Elasticsearch/Logstash) │ │
│  │  Prometheus + Grafana               │ │
│  │  Jaeger (分布式追踪)                 │ │
│  └─────────────────────────────────────┘ │
└───────────────────────────────────────────┘

Ingress Layer:
├── Nginx Ingress Controller (SSL终止)
├── 域名路由 (api.enghub.com, dashboard.enghub.com)
└── 跨域处理 (CORS)

存储:
├── PVC (持久化卷): PostgreSQL数据
├── S3/MinIO: 文件存储(文档、报表)
└── ConfigMap: 配置文件(环境变量)
```

### 7.2 多工厂部署方案

```
方案A: 单一部署 (共享资源)
├── 一套系统 + 数据库
├── 数据通过 tenant_id/factory_id 隔离
├── 优点: 维护简单、成本低
├── 缺点: 一个工厂故障可能影响全部
└── 推荐: 小规模企业、联合制造

方案B: 半隔离部署 (推荐)
├── 共享: API网关、认证、缓存
├── 隔离: 各工厂独立 PostgreSQL 主从
├── 隔离: 各工厂独立 RabbitMQ Vhost
├── 优点: 平衡成本和可靠性
├── 缺点: 管理复杂度中等
└── 推荐: 中等规模企业

方案C: 完全隔离部署
├── 每个工厂完整的 K8s 命名空间
├── 独立的 DB、缓存、消息队列、监控
├── 优点: 最高隔离性、故障影响小
├── 缺点: 成本高、维护复杂
└── 推荐: 大型集团、多独立工厂
```

---

## 八、监控、日志与追踪架构

### 8.1 可观测性三支柱

```
┌─────────────────────────────────────────┐
│         应用性能监控 (APM)               │
├─────────────────────────────────────────┤
│ Metrics (指标)                          │
│ ├─ 系统指标: CPU、内存、磁盘、网络      │
│ ├─ 应用指标:                            │
│ │  ├─ 工单创建率 (工单数/分钟)         │
│ │  ├─ 报工延迟 (秒)                    │
│ │  ├─ API响应时间 (p50/p95/p99)        │
│ │  ├─ 数据库连接池使用率                │
│ │  └─ 消息队列堆积深度                  │
│ └─ 告警规则:
│    ├─ CPU > 80% (warning)
│    ├─ API响应 > 1000ms (critical)
│    ├─ 队列深度 > 10000 (warning)
│    └─ DB连接数 > 80% (warning)
│
│ Logs (日志)                             │
│ ├─ 应用日志:                            │
│ │  ├─ 工单创建/编辑操作日志             │
│ │  ├─ 报工异常日志                      │
│ │  └─ 权限检查失败日志                  │
│ ├─ 审计日志:                            │
│ │  ├─ 谁在什么时间操作了什么            │
│ │  └─ 敏感数据访问                      │
│ └─ 传输: ELK (Elasticsearch/Logstash)   │
│
│ Traces (链路追踪)                       │
│ ├─ 分布式追踪: Jaeger/Zipkin           │
│ ├─ 追踪报工全流程:                      │
│ │  ├─ API Gateway (1ms)                │
│ │  ├─ Reporting Service (50ms)         │
│ │  ├─ MES Service (20ms)               │
│ │  ├─ QMS Service (30ms)               │
│ │  └─ DB Write (15ms)                  │
│ └─ 识别性能瓶颈
└─────────────────────────────────────────┘
```

### 8.2 日志级别设计

```
ERROR: 
├─ 数据库连接失败
├─ 消息队列服务不可用
├─ 权限认证失败 (安全告警)

WARN:
├─ API响应超过3秒
├─ 报工数量超过产能110%
├─ luaguage服务响应缓慢

INFO:
├─ 工单创建/完成
├─ 生产报工记录
├─ 检验任务创建

DEBUG:
├─ 工单状态变更详情
├─ 缓存命中率
├─ SQL执行计划
```

### 8.3 告警规则示例

```
告警规则1: 报工吞吐量告警
├─ 条件: 每分钟报工数 > 100
├─ 严重性: WARNING
├─ 通知: 发送给MES运维
└─ 处理: 检查报工服务性能

告警规则2: 工单卡住告警
├─ 条件: 工单处于生产中状态 > 24小时且未完工
├─ 严重性: CRITICAL
├─ 通知: 生管主管、班长
└─ 处理: 人工检查原因

告警规则3: 品质异常告警
├─ 条件: 某工序合格率 < 85% (或低于历史平均)
├─ 严重性: WARNING
├─ 通知: 品质经理、工艺
└─ 处理: 启动OCAP调查

告警规则4: 数据同步延迟
├─ 条件: luaguage数据延迟 > 5分钟
├─ 严重性: WARNING
├─ 通知: 系统管理员
└─ 处理: 检查网络/API延迟
```

---

## 九、关键业务流程的架构设计

### 9.1 工单报工流程 (核心高频流程)

```
时序图: 报工流程

用户                API Gateway         Reporting Svc      MES Svc         QMS Svc
  │                     │                    │               │              │
  ├─报工请求────────────>│                    │               │              │
  │                     │ 认证/限流          │               │              │
  │                     ├─检查速率限制 (200/min) │               │              │
  │                     ├─验证JWT令牌        │               │              │
  │                     │ ✓通过             │               │              │
  │                     │ 路由到Reporting Svc│               │              │
  │                     ├────────请求────────>│               │              │
  │                     │                    ├─查询缓存(工单信息) │              │
  │                     │                    ├─数量校验        │              │
  │                     │                    ├─写DB(Master)  │              │
  │                     │                    ├─发布事件────────────────>│              │
  │                     │                    ├─删除缓存        │              │
  │                     │                    │                │ 消费事件     │
  │                     │                    │                ├─检查合格率  │
  │                     │                    │                │ ✓创建检验单 │
  │                     │<──返回成功─────────┤                │              │
  │<────返回JSON────────┤                    │                │─创建检验单────>│
  │                     │                    │                │              │
后台: MES Svc更新工单进度 (异步)
  │                                         │                │              │
  │                                         │                ├─异步消费事件   │
  │                                         │                ├─更新工单完成度 │
  │                                         │                └─删除缓存      │

耗时分解:
├─ API网关: 5ms
├─ 业务逻辑: 30ms (缓存命中)
├─ DB写入: 15ms
├─ 消息发送: 5ms
└─ 总耗时: ~55ms (SLA: <500ms) ✓
```

### 9.2 库存查询流程 (读密集型)

```
场景: 查询某物料的库存

方案: 多层缓存 + 读写分离

1. 前端请求
   GET /api/v1/inventory?material_id=MAT-001

2. 缓存查询链
   ├─ L1 Redis缓存 (key=inventory:MAT-001)
   │  └─ Hit: 直接返回, 耗时 <1ms
   │  └─ Miss: 继续下一层
   └─ L2 Slave DB (只读副本)
      ├─ 查询库存表
      ├─ 更新Redis缓存 (TTL=10分钟)
      └─ 返回结果, 耗时 ~50ms

3. 写操作时主动更新缓存
   ├─ 入库/出库时写Master DB
   └─ 同时删除Redis缓存 key=inventory:*

优势:
├─ 大多数查询命中缓存 (<1ms)
├─ 缓存失败后从Slave DB读 (不加重Master压力)
├─ 支持高并发查询 (>1000 req/s)
```

---

## 十、扩展性与未来架构演进

### 10.1 水平扩展设计

```
微服务水平扩展:
├── 无状态设计
│   └─ 所有服务实例可互换 (工单服务可横向扩展)
├── 会话存储 (Redis)
│   └─ 用户登录信息存储在Redis，可被任意实例访问
└── 分布式锁 (Redis)
    └─ 某些操作需要分布式锁来防止竞态 (如库存扣减)

消息队列扩展:
├── Kafka Topic 分区
│   └─ 同一工单的消息发到同一分区，保证顺序
├── RabbitMQ Vhost
│   └─ 多工厂的消息隔离在不同Vhost
└── 消费者组扩展
    └─ 消费者数量可随需增减

数据库扩展:
├── 读副本扩展 (Master-Slave-Slave-...)
│   └─ 支持更多的查询并发
├── 分布式事务 (Saga模式)
│   └─ 避免分布式锁，使用补偿事务
└── 跨库JOIN优化
    └─ 缓存热数据，避免跨库JOIN
```

### 10.2 功能演进方向

```
Phase 1 (现在): 基础MES
├── 工单、报工、品质检验
└── 单工厂部署

Phase 2 (6个月): 增强MES + SPC
├── 生产计划PP
├── 统计过程控制 (SPC)
├── 多工厂部署
└── BI大屏

Phase 3 (12个月): IoT + AI
├── 设备数据采集 (IIoT)
├── 实时预测模型 (预测产能、预测缺陷)
├── 自动优化排程
└── 智能告警

Phase 4 (18个月): 供应链数字化
├── 供应商协同平台
├── 端到端物流可视化
├── 供应链金融
└── 全球工厂网络
```

---

## 十一、关键技术栈选型

```
后端:
├── 框架: FastAPI (Python) / Spring Boot (Java)
│   └─ 选择: FastAPI (原型快、性能足够)
├── ORM: SQLAlchemy / Alembic
├── API文档: OpenAPI/Swagger
├── 测试: pytest + coverage

消息队列:
├── RabbitMQ (微服务间通信)
├── Kafka (高吞吐量事件流)
└── Redis Streams (轻量级)

缓存:
├── Redis (主要缓存)
├── Memcached (可选)
└── 本地缓存: @functools.lru_cache

数据库:
├── PostgreSQL 14+ (主数据库)
├── 备选: MySQL 8.0 (兼容性考虑)
└── TimescaleDB (可选，时序数据)

前端:
├── React 18 + TypeScript
├── 状态管理: Redux/Zustand
├── 图表: ECharts / Recharts
├── UI: Ant Design / Material-UI

部署:
├── 容器: Docker
├── 编排: Kubernetes
├── CI/CD: GitLab CI / Jenkins
├── 监控: Prometheus + Grafana
└── 日志: ELK Stack
```

---

## 总结：架构核心原则

| 原则 | 说明 | 实践 |
|------|------|------|
| **可扩展性** | 支持业务快速增长 | 微服务、无状态、水平扩展 |
| **高可用性** | 99.9% 可用性 SLA | 多副本、主从备份、故障自动转移 |
| **数据一致性** | 最终一致性 + 补偿机制 | 事件驱动、异步处理、补偿日志 |
| **性能** | API 响应 <500ms | 多层缓存、读写分离、异步处理 |
| **可运维性** | 易于排查和维护 | 完整的日志、链路追踪、告警 |
| **安全性** | 防止数据泄露、权限控制 | RBAC、审计日志、敏感数据加密 |

---

**建议后续行动**：
1. 选择技术栈后，制定详细的API设计文档
2. 确定事件定义和消息格式规范
3. 制定数据库迁移(Alembic)脚本模板
4. 建立 DevOps 和部署流程
