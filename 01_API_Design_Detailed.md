# EngHub MES 系统 - API 详细设计

---

## 一、API 架构概览

### 1.1 RESTful vs GraphQL 对比与建议

| 维度 | RESTful | GraphQL | 推荐方案 |
|------|---------|---------|---------|
| **学习曲线** | 简单 | 中等 | RESTful |
| **开发速度** | 快 (CRUD模板多) | 中 (需定义schema) | RESTful |
| **性能** | 好 (资源导向) | 中 (易过度查询) | RESTful |
| **over-fetching** | 常见 | 避免 | GraphQL优势 |
| **缓存** | 好 (HTTP缓存) | 困难 | RESTful优势 |
| **实时推送** | 需额外方案 | WebSocket原生支持 | GraphQL优势 |
| **团队技能** | 通用 | 需学习 | RESTful优势 |
| **监控/告警** | 易 (URL体现资源) | 难 (单端点) | RESTful优势 |

### 1.2 最终建议：混合方案

```
├─ 前端Web/H5: RESTful API (稳定、易缓存)
├─ 移动端/第三方: GraphQL API (灵活、减少网络)
└─ 内部实时服务: WebSocket + 事件驱动

理由:
├─ RESTful: MES系统大多是CRUD操作，RESTful足够且性能更好
├─ GraphQL: 仅用于复杂报表查询和移动端需要精准字段的场景
└─ WebSocket: 看板实时推送、大屏更新
```

---

## 二、RESTful API 设计规范

### 2.1 API 版本管理

```
版本管理方案: URL Path 版本 (推荐)

格式: /api/v1/resource
├── /api/v1/... (当前版本，稳定)
├── /api/v2/... (新功能版本，开发中)
└── /api/v0/... (废弃版本，3个月后下线)

版本升级流程:
1. v1 处于稳定运营
2. 开发v2新功能，同时v1继续维护bug修复
3. v2经过UAT后，通知客户切换到v2
4. v1维护3个月后，发送下线通知，6个月后关闭
5. 各版本独立部署 (可选) 或 业务逻辑兼容多版本
```

### 2.2 HTTP 方法规范

```
GET     /api/v1/work-orders           # 列表查询
GET     /api/v1/work-orders/{id}      # 详情查询
POST    /api/v1/work-orders           # 创建资源
PUT     /api/v1/work-orders/{id}      # 完全替换资源
PATCH   /api/v1/work-orders/{id}      # 部分更新资源
DELETE  /api/v1/work-orders/{id}      # 删除资源

非RESTful操作 (动词化):
POST    /api/v1/work-orders/{id}/start        # 启动工单
POST    /api/v1/work-orders/{id}/complete    # 完成工单
POST    /api/v1/work-orders/{id}/split       # 拆分工单
POST    /api/v1/production-reports/confirm   # 确认报工
POST    /api/v1/inspections/{id}/approve     # 批准检验
```

### 2.3 URL 命名规范

```
资源名用复数形式 (collection):
✓ /api/v1/work-orders
✗ /api/v1/work-order
✗ /api/v1/workOrder

子资源 (嵌套):
/api/v1/work-orders/{wo_id}/production-reports
/api/v1/production-reports/{pr_id}/attachments

查询参数:
/api/v1/work-orders?status=in_progress&factory_id=sh-01&page=1&limit=20
/api/v1/production-reports?from=2026-02-01&to=2026-02-28&group_by=shift

查询参数规范:
├── 排序: sort=+created_at 或 sort=-created_at
├── 分页: page=1&limit=20 (limit≤100)
├── 过滤: status=active&priority=high
├── 搜索: q=search_keyword
└── 包含关系字段: include=product,station
```

---

## 三、完整的 API 端点设计

### 3.1 工单管理 API (Work Order)

#### 3.1.1 创建工单

```
POST /api/v1/work-orders

Request Headers:
├── Authorization: Bearer <token>
├── Content-Type: application/json
├── X-Factory-ID: factory-sh-01        # 必需，多工厂隔离
└── X-Request-ID: req-20260224-001     # 用于幂等性

Request Body:
{
  "sales_order_id": "SO-20260224-001",
  "product_id": "PROD-A001",
  "planned_qty": 1000,
  "unit": "pcs",
  "planned_start": "2026-02-24T08:00:00Z",
  "planned_due": "2026-02-25T17:00:00Z",
  "priority": "high",  // low/medium/high/urgent
  "routing_id": "RT-20260224-001",     // 工艺路线ID (可选，自动获取)
  "bom_version": "V2.0",               // BOM版本 (可选，默认最新)
  "remark": "客户加急订单"
}

Response (201 Created):
{
  "id": "WO-20260224-001",
  "sales_order_id": "SO-20260224-001",
  "product_id": "PROD-A001",
  "product_name": "PCB板-A001",
  "planned_qty": 1000,
  "completed_qty": 0,
  "good_qty": 0,
  "defect_qty": 0,
  "status": "pending",         // pending/in_progress/pending_inbound/completed/closed
  "priority": "high",
  "routing": {
    "id": "RT-20260224-001",
    "steps": [
      {
        "seq": 1,
        "operation": "SMT贴片",
        "station_id": "ST-SMT-01",
        "standard_time": 120,  // 秒
        "setup_time": 300
      },
      {
        "seq": 2,
        "operation": "组装",
        "station_id": "ST-ASM-01",
        "standard_time": 180,
        "setup_time": 0
      }
    ]
  },
  "created_by": "emp-001",
  "created_at": "2026-02-24T08:15:00Z",
  "updated_at": "2026-02-24T08:15:00Z"
}

错误响应:
400 Bad Request:
{
  "code": "INVALID_PRODUCT_ID",
  "message": "产品ID不存在或未启用",
  "details": {
    "product_id": "PROD-A001"
  }
}

422 Unprocessable Entity:
{
  "code": "PPAP_NOT_APPROVED",
  "message": "某物料未通过PPAP认证，无法下达工单",
  "details": {
    "material_id": "MAT-001",
    "material_name": "电容-100nF"
  }
}

409 Conflict:
{
  "code": "INSUFFICIENT_CAPACITY",
  "message": "产能不足，无法容纳该工单",
  "details": {
    "required_capacity": 1000,
    "available_capacity": 500,
    "station_id": "ST-SMT-01"
  }
}
```

#### 3.1.2 查询工单列表

```
GET /api/v1/work-orders?status=in_progress&factory_id=sh-01&sort=-created_at&limit=20

Query Parameters:
├── status: pending/in_progress/pending_inbound/completed (逗号分隔多个)
├── factory_id: 工厂ID
├── product_id: 产品ID
├── station_id: 工位ID (过滤该工位的工单)
├── priority: low/medium/high/urgent
├── created_by: 创建人ID
├── from_date: 2026-02-01 (开始日期)
├── to_date: 2026-02-28 (结束日期)
├── q: 搜索关键字 (工单号、订单号、产品名)
├── sort: -created_at,+status (多列排序)
├── page: 1 (从1开始)
├── limit: 20 (最多100)
└── include: product,station,routing (包含关联对象)

Response (200 OK):
{
  "code": "SUCCESS",
  "data": [
    {
      "id": "WO-20260224-001",
      "sales_order_id": "SO-20260224-001",
      "product": {
        "id": "PROD-A001",
        "name": "PCB板-A001",
        "sku": "SKU-001"
      },
      "planned_qty": 1000,
      "completed_qty": 350,
      "good_qty": 340,
      "defect_qty": 10,
      "defect_rate": 0.029,  // 2.9%
      "status": "in_progress",
      "current_step": {
        "seq": 1,
        "operation": "SMT贴片",
        "station_id": "ST-SMT-01",
        "station_name": "SMT贴片线-1"
      },
      "progress_rate": 0.35,  // 35% 完成
      "days_overdue": 0,
      "planned_due": "2026-02-25T17:00:00Z",
      "priority": "high"
    },
    ...
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 150,
    "total_pages": 8
  }
}
```

#### 3.1.3 获取工单详情

```
GET /api/v1/work-orders/{id}?include=routing,bom,reports

Response:
{
  "id": "WO-20260224-001",
  "sales_order_id": "SO-20260224-001",
  "product": {...},
  "status": "in_progress",
  "planned_qty": 1000,
  "completed_qty": 350,
  "good_qty": 340,
  "defect_qty": 10,
  
  "routing": {
    "id": "RT-20260224-001",
    "steps": [
      {
        "seq": 1,
        "operation": "SMT贴片",
        "station": {
          "id": "ST-SMT-01",
          "name": "SMT贴片线-1",
          "capacity": 500  // 产能
        },
        "status": "completed",
        "report_qty": 350,
        "completed_at": "2026-02-24T15:00:00Z"
      },
      {
        "seq": 2,
        "operation": "组装",
        "station": {
          "id": "ST-ASM-01",
          "name": "组装线"
        },
        "status": "pending"
      }
    ]
  },
  
  "bom": {
    "version": "V2.0",
    "materials": [
      {
        "material_id": "MAT-001",
        "material_name": "电容-100nF",
        "qty_per_unit": 10,
        "unit": "pcs",
        "required_qty": 10000,
        "received_qty": 10000,
        "available_qty": 10000
      }
    ]
  },
  
  "production_reports": [
    {
      "id": "PR-20260224-001",
      "report_time": "2026-02-24T14:30:00Z",
      "operator": "emp-001",
      "station_id": "ST-SMT-01",
      "shift": "day",
      "good_qty": 350,
      "defect_qty": 10,
      "defects": [
        {"type": "短路", "qty": 5},
        {"type": "漏焊", "qty": 5}
      ]
    }
  ],
  
  "timeline": [
    {
      "event": "created",
      "timestamp": "2026-02-24T08:15:00Z",
      "actor": "emp-001"
    },
    {
      "event": "started",
      "timestamp": "2026-02-24T08:30:00Z",
      "actor": "emp-002"
    }
  ]
}
```

#### 3.1.4 更新工单

```
PATCH /api/v1/work-orders/{id}

Request:
{
  "planned_qty": 1200,      // 修改计划数量
  "priority": "urgent",      // 提升优先级
  "planned_due": "2026-02-26T17:00:00Z",  // 延期
  "remark": "新增200pcs应急订单"
}

Response:
{
  "id": "WO-20260224-001",
  "planned_qty": 1200,
  "priority": "urgent",
  "planned_due": "2026-02-26T17:00:00Z",
  "updated_at": "2026-02-24T10:00:00Z",
  "updated_by": "emp-001"
}

注意: 
├─ 已开工工单: 只允许修改优先级、due_date、remark
├─ 已完工工单: 不允许修改任何字段
└─ 修改记录: 自动记录在审计日志
```

#### 3.1.5 工单状态转移

```
POST /api/v1/work-orders/{id}/start

Request:
{
  "assigned_to": "emp-001",
  "station_id": "ST-SMT-01",
  "remark": "分配给SMT线1"
}

Response: 200 OK
{
  "id": "WO-20260224-001",
  "status": "in_progress",
  "start_time": "2026-02-24T08:30:00Z"
}

POST /api/v1/work-orders/{id}/complete

Request:
{
  "actual_qty": 1000,
  "remark": "正常完成"
}

Response: 200 OK
{
  "id": "WO-20260224-001",
  "status": "pending_inbound",
  "completed_qty": 1000
}

POST /api/v1/work-orders/{id}/cancel

Request:
{
  "reason": "订单取消",
  "remark": "客户要求取消"
}

Response: 200 OK
{
  "id": "WO-20260224-001",
  "status": "closed"
}
```

---

### 3.2 生产报工 API (Production Reporting)

#### 3.2.1 新增报工

```
POST /api/v1/production-reports

Request:
{
  "work_order_id": "WO-20260224-001",
  "station_id": "ST-SMT-01",
  "shift": "day",              // day/night/overtime
  "report_type": "normal",     // normal/补料/返工
  "good_qty": 100,
  "defect_qty": 5,
  "defect_details": [
    {
      "type": "短路",
      "qty": 3,
      "remark": "焊接质量问题"
    },
    {
      "type": "漏焊",
      "qty": 2,
      "remark": "设备异常"
    }
  ],
  "operator_id": "emp-001",
  "equipment_id": "EQ-SMT-001",
  "report_time": "2026-02-24T14:30:00Z",
  "remark": "正常生产"
}

Response (201 Created):
{
  "id": "PR-20260224-001",
  "work_order_id": "WO-20260224-001",
  "good_qty": 100,
  "defect_qty": 5,
  "status": "submitted",       // submitted/confirmed/rejected
  "created_at": "2026-02-24T14:30:00Z",
  "created_by": "emp-001"
}

业务规则校验:
├─ work_order_id 必须存在且状态为 in_progress
├─ good_qty + defect_qty ≤ (计划数 - 已报工数)
├─ 不允许重复报工 (同一工单同班次): 通过幂等性key检测
├─ 工单已完工后: 不允许报工
├─ 缺陷数 > 0: 需要说明缺陷类型
└─ 返工报工: 关联原始工单PR_ID

幂等性:
├─ 使用 X-Request-ID 头部
├─ 如果重复请求，返回200而非201
└─ 关键: 数据库中唯一索引: (work_order_id, shift, station_id, report_time)
```

#### 3.2.2 查询报工记录

```
GET /api/v1/production-reports?work_order_id=WO-20260224-001&sort=-report_time

Query Parameters:
├── work_order_id: 工单ID
├── station_id: 工位ID
├── operator_id: 操作人ID
├── shift: day/night/overtime
├── from_time: 2026-02-24T00:00:00Z
├── to_time: 2026-02-24T23:59:59Z
├── include: work_order,operator,defects
└── limit: 100

Response:
{
  "data": [
    {
      "id": "PR-20260224-001",
      "work_order": {
        "id": "WO-20260224-001",
        "product_name": "PCB板-A001"
      },
      "good_qty": 100,
      "defect_qty": 5,
      "defect_rate": 0.048,  // 4.8%
      "operator": {"id": "emp-001", "name": "张三"},
      "station_id": "ST-SMT-01",
      "shift": "day",
      "report_time": "2026-02-24T14:30:00Z",
      "defects": [
        {"type": "短路", "qty": 3},
        {"type": "漏焊", "qty": 2}
      ]
    }
  ],
  "pagination": {...}
}
```

#### 3.2.3 报工确认 (仅限主管)

```
POST /api/v1/production-reports/{id}/confirm

Request:
{
  "approved": true,    // true/false
  "remark": "批准通过"
}

Response: 200 OK
{
  "id": "PR-20260224-001",
  "status": "confirmed",
  "approved_by": "emp-002",
  "approved_at": "2026-02-24T15:00:00Z"
}
```

---

### 3.3 检验管理 API (QMS)

#### 3.3.1 创建检验单

```
POST /api/v1/inspections

Request:
{
  "inspection_type": "IQC",  // IQC/IPQC/FQC/OQC
  "material_id": "MAT-001",  // IQC时必需
  "work_order_id": "WO-20260224-001",  // IPQC/FQC/OQC时必需
  "batch_id": "BATCH-20260224-001",
  "batch_size": 1000,
  "aql": 2.5,              // AQL等级 (GB/T 2828)
  "sample_size": 50,
  "inspection_items": [
    {
      "item": "外观",
      "standard": "无划伤、无污渍",
      "measurement_type": "visual"
    },
    {
      "item": "尺寸",
      "standard": "10±0.1mm",
      "measurement_type": "measurement"
    }
  ]
}

Response (201 Created):
{
  "id": "INS-20260224-001",
  "status": "draft",         // draft/inspecting/completed/passed/failed
  "created_at": "2026-02-24T10:00:00Z"
}
```

#### 3.3.2 提交检验结果

```
POST /api/v1/inspections/{id}/submit

Request:
{
  "inspector_id": "emp-001",
  "inspection_results": [
    {
      "item_id": "item-001",
      "item": "外观",
      "result": "pass",      // pass/fail
      "remark": "合格"
    },
    {
      "item_id": "item-002",
      "item": "尺寸",
      "result": "fail",
      "measured_value": 10.15,
      "remark": "超差0.05mm"
    }
  ],
  "defect_qty": 5,
  "good_qty": 95,
  "overall_result": "pass"  // pass/fail (按AQL判定)
}

Response: 200 OK
{
  "id": "INS-20260224-001",
  "status": "completed",
  "overall_result": "pass",
  "passed_at": "2026-02-24T10:30:00Z"
}

业务规则:
├─ AQL判定: 缺陷数 ≤ AQL对应的接收数 → pass
├─ IQC不合格: 自动创建不良品单
├─ IPQC不合格: 可选择返工/报废
├─ OQC不合格: 无法出货
└─ 检验报告: 自动生成并保存
```

#### 3.3.3 查询检验记录

```
GET /api/v1/inspections?inspection_type=IPQC&work_order_id=WO-20260224-001&sort=-created_at

Query Parameters:
├── inspection_type: IQC/IPQC/FQC/OQC
├── work_order_id
├── material_id
├── result: pass/fail
├── from_date
├── to_date
└── limit

Response:
{
  "data": [
    {
      "id": "INS-20260224-001",
      "inspection_type": "IPQC",
      "work_order": {
        "id": "WO-20260224-001",
        "product_name": "PCB板-A001"
      },
      "batch_size": 1000,
      "sample_size": 50,
      "good_qty": 95,
      "defect_qty": 5,
      "defect_rate": 0.05,   // 5%
      "overall_result": "pass",
      "inspector": {"id": "emp-001", "name": "张三"},
      "completed_at": "2026-02-24T10:30:00Z"
    }
  ]
}
```

---

### 3.4 不良品管理 API

#### 3.4.1 创建不良品单

```
POST /api/v1/defects

Request:
{
  "work_order_id": "WO-20260224-001",
  "defect_type": "短路",
  "defect_qty": 5,
  "defect_location": "焊接端",
  "root_cause": "设备温度异常",
  "discovery_time": "2026-02-24T14:30:00Z",
  "inspection_id": "INS-20260224-001",
  "remark": "需要返工处理"
}

Response (201 Created):
{
  "id": "DEF-20260224-001",
  "status": "open",          // open/in_repair/rejected/reworked/scrapped/accepted
  "created_at": "2026-02-24T14:30:00Z"
}
```

#### 3.4.2 处理不良品

```
POST /api/v1/defects/{id}/process

Request:
{
  "disposition": "rework",  // rework/repair/scrap/accept(特采)
  "remark": "返工处理",
  "assigned_to": "emp-002"
}

Response: 200 OK
{
  "id": "DEF-20260224-001",
  "status": "in_repair",
  "disposition": "rework"
}

可选: 触发OCAP
├─ 如果缺陷严重等级 = 高
├─ 自动创建纠正措施 OCAP-20260224-001
└─ 分配给品质经理
```

---

### 3.5 工艺路线 API (Routing)

#### 3.5.1 创建工艺路线

```
POST /api/v1/routings

Request:
{
  "product_id": "PROD-A001",
  "version": "V2.0",
  "steps": [
    {
      "seq": 1,
      "operation": "SMT贴片",
      "station_id": "ST-SMT-01",
      "setup_time": 300,      // 秒
      "standard_time": 120,
      "tools": ["贴片机-1", "烤箱-1"],
      "materials": ["焊膏", "助焊剂"],
      "parameter": {
        "temperature": 260,
        "duration": 240,
        "speed": 500
      }
    },
    {
      "seq": 2,
      "operation": "组装",
      "station_id": "ST-ASM-01",
      "setup_time": 0,
      "standard_time": 180
    }
  ]
}

Response:
{
  "id": "RT-20260224-001",
  "product_id": "PROD-A001",
  "version": "V2.0",
  "status": "active"
}
```

#### 3.5.2 查询工艺路线

```
GET /api/v1/routings?product_id=PROD-A001

Response:
{
  "data": [
    {
      "id": "RT-20260224-001",
      "product_id": "PROD-A001",
      "version": "V2.0",
      "status": "active",
      "steps": [...]
    }
  ]
}
```

---

### 3.6 工位/产线管理 API

#### 3.6.1 创建工位

```
POST /api/v1/stations

Request:
{
  "station_id": "ST-SMT-01",
  "station_name": "SMT贴片线-1",
  "factory_id": "factory-sh-01",
  "workshop_id": "workshop-01",
  "station_type": "production",  // production/inspection/warehouse
  "capacity": 500,               // 单位时间内产能
  "capacity_unit": "pcs/hour",
  "available_shifts": ["day", "night", "overtime"],
  "equipment": [
    {
      "equipment_id": "EQ-SMT-001",
      "equipment_name": "贴片机-1"
    }
  ]
}

Response:
{
  "id": "ST-SMT-01",
  "station_name": "SMT贴片线-1",
  "capacity": 500
}
```

---

### 3.7 报表查询 API

#### 3.7.1 日报表

```
GET /api/v1/reports/daily?date=2026-02-24&factory_id=factory-sh-01

Response:
{
  "report_date": "2026-02-24",
  "factory": "factory-sh-01",
  "summary": {
    "work_orders_completed": 5,
    "total_produced": 5000,
    "total_defects": 150,
    "defect_rate": 0.03,       // 3%
    "equipment_oee": 0.85,     // 综合效率
    "on_time_delivery": 0.95   // 准时交付率
  },
  "by_station": [
    {
      "station_id": "ST-SMT-01",
      "station_name": "SMT贴片线",
      "produced": 2000,
      "defects": 60,
      "defect_rate": 0.03,
      "capacity_utilization": 0.92,
      "oee": 0.85
    }
  ],
  "by_shift": [
    {
      "shift": "day",
      "produced": 2500,
      "defects": 75,
      "defect_rate": 0.03
    },
    {
      "shift": "night",
      "produced": 2500,
      "defects": 75,
      "defect_rate": 0.03
    }
  ],
  "defect_analysis": [
    {
      "defect_type": "短路",
      "count": 80,
      "percentage": 0.533
    },
    {
      "defect_type": "漏焊",
      "count": 70,
      "percentage": 0.467
    }
  ]
}
```

#### 3.7.2 月报表

```
GET /api/v1/reports/monthly?year=2026&month=02&factory_id=factory-sh-01

Response:
{
  "report_period": "2026-02",
  "summary": {
    "total_work_orders": 120,
    "completed_work_orders": 115,
    "completion_rate": 0.958,
    "total_produced": 150000,
    "total_defects": 4500,
    "defect_rate": 0.03,
    "average_oee": 0.85,
    "on_time_delivery": 0.96,
    "cost_per_unit": 25.5
  },
  "trend": [
    {
      "date": "2026-02-01",
      "produced": 5000,
      "defect_rate": 0.025
    },
    ...
  ]
}
```

---

## 四、GraphQL Schema 设计 (可选方案)

### 4.1 GraphQL vs REST 的使用场景划分

```
REST API 适用场景:
├─ 标准的CRUD操作 (工单、报工)
├─ 需要HTTP缓存优化
└─ 前端需要统一的数据格式

GraphQL 适用场景:
├─ 复杂的多层关联查询 (工单→报工→缺陷)
├─ 移动端需要精确的字段选择
├─ 第三方集成需要灵活的数据返回
└─ 实时仪表板需要WebSocket订阅
```

### 4.2 GraphQL Schema 示例

```graphql
type Query {
  # 工单查询
  workOrder(id: ID!): WorkOrder
  workOrders(
    status: WorkOrderStatus
    factoryId: String!
    limit: Int = 20
    offset: Int = 0
    sort: String = "-createdAt"
  ): WorkOrderConnection!
  
  # 生产报工查询
  productionReports(
    workOrderId: ID
    stationId: String
    fromTime: DateTime
    toTime: DateTime
  ): [ProductionReport!]!
  
  # 检验查询
  inspections(
    inspectionType: InspectionType!
    result: InspectionResult
    limit: Int = 20
  ): [Inspection!]!
  
  # 统计报表
  dailyReport(date: Date!, factoryId: String!): DailyReport!
  monthlyReport(year: Int!, month: Int!, factoryId: String!): MonthlyReport!
}

type Mutation {
  # 工单操作
  createWorkOrder(input: CreateWorkOrderInput!): WorkOrder!
  updateWorkOrder(id: ID!, input: UpdateWorkOrderInput!): WorkOrder!
  startWorkOrder(id: ID!): WorkOrder!
  completeWorkOrder(id: ID!, actualQty: Int!): WorkOrder!
  
  # 报工操作
  submitProductionReport(input: ProductionReportInput!): ProductionReport!
  confirmProductionReport(id: ID!): ProductionReport!
  
  # 检验操作
  submitInspection(id: ID!, input: InspectionResultInput!): Inspection!
}

type Subscription {
  # 实时推送
  workOrderStatusChanged(factoryId: String!): WorkOrder!
  productionReported(stationId: String!): ProductionReport!
  defectDetected(factoryId: String!): Defect!
  shiftBoardUpdated(shift: String!): ShiftBoard!
}

type WorkOrder {
  id: ID!
  salesOrderId: String!
  product: Product!
  plannedQty: Int!
  completedQty: Int!
  goodQty: Int!
  defectQty: Int!
  status: WorkOrderStatus!
  priority: Priority!
  routing: Routing!
  bom: [Material!]!
  productionReports: [ProductionReport!]!
  currentStep: RoutingStep
  progressRate: Float!
  plannedDue: DateTime!
  createdAt: DateTime!
  updatedAt: DateTime!
}

type ProductionReport {
  id: ID!
  workOrder: WorkOrder!
  goodQty: Int!
  defectQty: Int!
  defects: [Defect!]!
  operator: User!
  station: Station!
  shift: String!
  reportTime: DateTime!
  status: ReportStatus!
}

enum WorkOrderStatus {
  PENDING
  IN_PROGRESS
  PENDING_INBOUND
  COMPLETED
  CLOSED
}

enum Priority {
  LOW
  MEDIUM
  HIGH
  URGENT
}
```

---

## 五、错误处理规范

### 5.1 HTTP 状态码使用

```
200 OK                # 成功的GET/PATCH请求
201 Created           # 成功的POST请求，返回新创建的资源
204 No Content        # 成功的DELETE请求
400 Bad Request       # 请求参数错误
401 Unauthorized      # 未认证 (缺少或无效的JWT)
403 Forbidden         # 已认证但权限不足
404 Not Found         # 资源不存在
409 Conflict          # 业务冲突 (如产能不足)
422 Unprocessable Entity  # 业务规则校验失败
429 Too Many Requests     # 限流
500 Internal Server Error # 服务器错误
503 Service Unavailable   # 依赖服务不可用
```

### 5.2 错误响应格式

```json
{
  "code": "WORK_ORDER_NOT_FOUND",
  "message": "工单不存在或已删除",
  "status": 404,
  "timestamp": "2026-02-24T10:00:00Z",
  "request_id": "req-20260224-001",
  "details": {
    "work_order_id": "WO-20260224-001"
  },
  "help_url": "https://docs.enghub.com/errors/work_order_not_found"
}
```

---

## 六、请求/响应头设计

### 6.1 Request Headers

```
Authorization: Bearer <JWT_TOKEN>
├─ 格式: "Bearer eyJhbGciOiJIUzI1NiIs..."
├─ 过期: 24小时
└─ Refresh Token: 长期有效

X-Factory-ID: factory-sh-01
├─ 必需: 多工厂隔离
└─ 用户可以访问多个工厂

X-Request-ID: req-20260224-001
├─ 可选: 用于幂等性和日志追踪
└─ 由客户端生成或由网关添加

X-API-Version: v1
├─ 可选: 指定API版本
└─ 默认使用URL中的版本

Content-Type: application/json

Idempotency-Key: key-20260224-001
├─ 用于重复请求的幂等性处理
└─ 关键: 防止重复报工
```

### 6.2 Response Headers

```
X-Request-ID: req-20260224-001
├─ 与请求对应，用于日志追踪

X-RateLimit-Limit: 100
X-RateLimit-Remaining: 85
X-RateLimit-Reset: 1645525200
├─ 限流信息

Cache-Control: max-age=300, public
├─ 缓存策略
├─ 列表API: public, max-age=60
├─ 详情API: private, max-age=300
└─ POST/PATCH/DELETE: no-cache

Content-Type: application/json; charset=utf-8

X-API-Version: v1

Server: EngHub/1.0
```

---

## 七、分页设计

### 7.1 Offset-Based Pagination (推荐用于REST)

```
GET /api/v1/work-orders?page=1&limit=20

Response:
{
  "data": [...],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 500,
    "total_pages": 25,
    "has_next": true,
    "has_prev": false
  }
}

优点: 简单易用
缺点: 深分页时性能差 (如 page=100&limit=20)
```

### 7.2 Cursor-Based Pagination (用于大数据量)

```
GET /api/v1/production-reports?limit=20&cursor=abc123

Response:
{
  "data": [
    {"id": "PR-001", "...": "..."},
    {"id": "PR-002", "...": "..."}
  ],
  "pagination": {
    "limit": 20,
    "cursor": "def456",
    "has_next": true
  }
}

优点: 高性能，适合大数据量
缺点: 实现复杂，不支持跳页

实现建议:
├─ 生产报工: 使用Cursor (高频操作)
├─ 工单列表: 使用Offset (用户通常不翻页)
└─ 报表数据: 使用Cursor (海量数据)
```

---

## 八、速率限制 (Rate Limiting)

### 8.1 限流规则

```
全局限制:
├── 普通用户: 100请求/分钟
├── VIP用户: 1000请求/分钟
└── API Key: 10000请求/分钟

端点级限制:
├── POST /api/v1/work-orders: 10请求/分钟 (创建工单)
├── POST /api/v1/production-reports: 200请求/分钟 (高频报工)
├── GET /api/v1/reports/*: 50请求/分钟 (报表查询)
└── GET /api/v1/work-orders: 100请求/分钟 (列表查询)

限流算法: Token Bucket (令牌桶)
├─ 每个用户维护一个令牌桶
├─ 每秒补充令牌
├─ 请求消耗令牌
└─ 无令牌时返回 429

响应示例:
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1645525200
Retry-After: 30

{
  "code": "RATE_LIMIT_EXCEEDED",
  "message": "请求过于频繁，请在30秒后重试",
  "retry_after": 30
}
```

---

## 九、API 安全设计

### 9.1 认证与授权

```
JWT 认证流程:
1. 登录: POST /api/v1/auth/login
   Request: {username, password}
   Response: {access_token, refresh_token, expires_in}

2. 使用Token: 每个请求加 Authorization: Bearer <token>

3. Token刷新: POST /api/v1/auth/refresh
   Request: {refresh_token}
   Response: {access_token, expires_in}

4. 权限检查: RBAC (基于角色的访问控制)
   ├─ 用户 → 角色 → 权限
   ├─ 如: 员工工单查看 (permission: work_order:read)
   └─ 网关在授权中间件检查

权限示例:
├── 工单创建: work_order:create
├── 工单编辑: work_order:edit
├── 工单删除: work_order:delete
├── 报工提交: production_report:create
├── 报工确认: production_report:confirm
├── 检验审批: inspection:approve
└── 导出报表: report:export
```

### 9.2 字段级访问控制

```
示例: 成本字段对普通员工隐藏

GET /api/v1/work-orders/WO-001

普通员工看到:
{
  "id": "WO-001",
  "product_name": "PCB板",
  "planned_qty": 1000,
  "status": "in_progress"
  # 成本字段不返回
}

管理员看到:
{
  "id": "WO-001",
  "product_name": "PCB板",
  "planned_qty": 1000,
  "status": "in_progress",
  "cost": 25500,         # 包含成本
  "cost_per_unit": 25.5
}

实现:
├─ 响应拦截器检查用户权限
├─ 根据权限动态包含/排除字段
└─ 查询时直接SELECT需要的字段
```

---

## 十、API 文档生成 (Swagger/OpenAPI)

### 10.1 自动生成文档

```python
# FastAPI 自动生成 OpenAPI/Swagger 文档

from fastapi import FastAPI, Body
from pydantic import BaseModel

app = FastAPI(
    title="EngHub MES API",
    description="电子制造生产执行系统",
    version="1.0.0",
    docs_url="/api/v1/docs",          # Swagger UI
    redoc_url="/api/v1/redoc",        # ReDoc
    openapi_url="/api/v1/openapi.json"
)

class WorkOrderCreate(BaseModel):
    """创建工单请求体"""
    sales_order_id: str
    product_id: str
    planned_qty: int

@app.post(
    "/api/v1/work-orders",
    response_model=WorkOrder,
    status_code=201,
    summary="创建工单",
    tags=["Work Orders"]
)
async def create_work_order(
    body: WorkOrderCreate = Body(
        ...,
        example={
            "sales_order_id": "SO-20260224-001",
            "product_id": "PROD-A001",
            "planned_qty": 1000
        }
    ),
    factory_id: str = Header(..., description="工厂ID")
):
    """
    创建生产工单
    
    - **sales_order_id**: 销售订单ID
    - **product_id**: 产品ID
    - **planned_qty**: 计划数量
    
    返回201状态码和新创建的工单信息
    """
    pass
```

访问: http://localhost:8000/api/v1/docs

---

## 总结：RESTful API 最佳实践

| 方面 | 最佳实践 |
|------|---------|
| **版本管理** | URL路径版本 (/api/v1) |
| **资源命名** | 复数名词 + 子资源嵌套 |
| **HTTP方法** | GET/POST/PATCH/DELETE对应C/R/U/D |
| **分页** | Offset(小数据) + Cursor(大数据) |
| **缓存** | Cache-Control头 + ETag |
| **错误处理** | 统一格式 + 错误码 + 详情 |
| **限流** | Token Bucket算法 |
| **认证** | JWT + Refresh Token |
| **幂等性** | Idempotency-Key + 唯一索引 |
| **文档** | OpenAPI/Swagger自动生成 |
