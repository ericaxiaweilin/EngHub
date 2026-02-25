# EngHub MES 系统 - 数据库设计 (ERD)

---

## 一、数据库总体设计

### 1.1 核心表关系图

```
                          系统核心表关系

┌──────────────────┐
│   factories      │  (工厂)
└────────┬─────────┘
         │
    ┌────┴─────────────────┐
    │                      │
┌───▼──────────┐    ┌─────▼─────────┐
│  workshops   │    │   stations    │  (车间/工位)
└───┬──────────┘    └─────┬─────────┘
    │                     │
    │                 ┌───┴──────┐
    │                 │          │
┌───▼──────────────────┬──┐  ┌──┴─────────────┐
│   work_orders        │  │  │ production     │
│ (工单-核心表)        │  │  │ _reports       │
└───┬──────────────────┘  │  │ (报工-核心表)  │
    │                     │  └────┬───────────┘
    │                     │       │
    │  ┌──────────────────┘  ┌────▼──────────┐
    │  │                     │  defects      │
    │  │                     │ (不良品)       │
┌───▼──▼──────────────┐     └─────┬─────────┘
│   routing_steps     │           │
│ (工艺路线-工序)      │    ┌──────┴──────────┐
└───┬──────────────────┘    │                 │
    │                   ┌───▼──────────┐  ┌──▼──────────┐
    │                   │ inspections  │  │ ocaps       │
    │                   │ (检验单)     │  │ (纠正措施)   │
    │                   └──────────────┘  └─────────────┘
    │
┌───▼──────────────────┐
│    products         │
│ (产品基本信息)       │
└──────────────────────┘
```

---

## 二、完整的表结构设计

### 2.1 基础表

#### factories (工厂)

```sql
CREATE TABLE factories (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    code VARCHAR(50) NOT NULL UNIQUE,
    location VARCHAR(256),
    contact_person VARCHAR(128),
    contact_phone VARCHAR(20),
    address VARCHAR(256),
    country VARCHAR(64) DEFAULT 'China',
    status VARCHAR(20) DEFAULT 'active',  -- active/inactive
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by VARCHAR(32),
    updated_by VARCHAR(32)
) COMMENT='工厂表';

CREATE INDEX idx_factories_code ON factories(code);
CREATE INDEX idx_factories_status ON factories(status);
```

#### workshops (车间)

```sql
CREATE TABLE workshops (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    manager_id VARCHAR(32),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (factory_id) REFERENCES factories(id)
) COMMENT='车间表';

CREATE INDEX idx_workshops_factory_id ON workshops(factory_id);
CREATE INDEX idx_workshops_status ON workshops(status);
```

#### stations (工位/产线)

```sql
CREATE TABLE stations (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    workshop_id VARCHAR(32) NOT NULL,
    station_code VARCHAR(50) NOT NULL,
    station_name VARCHAR(128) NOT NULL,
    station_type VARCHAR(50) NOT NULL,  -- production/inspection/warehouse
    capacity INT NOT NULL,              -- 产能数值
    capacity_unit VARCHAR(50),          -- pcs/hour, meters/hour
    equipment_count INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (workshop_id) REFERENCES workshops(id)
) COMMENT='工位/产线表';

CREATE INDEX idx_stations_factory_id ON stations(factory_id);
CREATE INDEX idx_stations_workshop_id ON stations(workshop_id);
CREATE UNIQUE INDEX idx_stations_code ON stations(factory_id, station_code);
```

#### products (产品)

```sql
CREATE TABLE products (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32),             -- 可选，支持全公司级产品
    product_code VARCHAR(50) NOT NULL,
    product_name VARCHAR(256) NOT NULL,
    sku VARCHAR(100),
    category VARCHAR(100),
    description TEXT,
    unit VARCHAR(20),                  -- pcs, meters, kg
    standard_cost DECIMAL(18, 6),
    selling_price DECIMAL(18, 6),
    bom_id VARCHAR(32),                -- 关联luaguage的BOM_ID
    current_bom_version VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (factory_id) REFERENCES factories(id)
) COMMENT='产品表';

CREATE INDEX idx_products_factory_id ON products(factory_id);
CREATE UNIQUE INDEX idx_products_code ON products(factory_id, product_code);
CREATE INDEX idx_products_status ON products(status);
```

---

### 2.2 工单表 (核心)

#### work_orders (工单)

```sql
CREATE TABLE work_orders (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    sales_order_id VARCHAR(50),
    work_order_code VARCHAR(50) NOT NULL,
    product_id VARCHAR(32) NOT NULL,
    routing_id VARCHAR(32),
    planned_qty INT NOT NULL,
    unit VARCHAR(20),
    completed_qty INT DEFAULT 0,
    good_qty INT DEFAULT 0,
    defect_qty INT DEFAULT 0,
    scrap_qty INT DEFAULT 0,
    
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  
    -- 状态: pending(待生产) → in_progress(生产中) → pending_inbound(待入库) → completed(已完成) → closed(已关闭)
    
    priority VARCHAR(20) DEFAULT 'medium',  -- low/medium/high/urgent
    
    planned_start DATETIME,
    planned_due DATETIME,
    actual_start DATETIME,
    actual_complete DATETIME,
    
    assigned_station_id VARCHAR(32),
    assigned_to VARCHAR(32),            -- 分配给的员工
    
    current_routing_step INT DEFAULT 0,
    bom_version VARCHAR(50),
    
    created_by VARCHAR(32) NOT NULL,
    updated_by VARCHAR(32),
    remark TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP NULL,          -- 软删除
    
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (product_id) REFERENCES products(id),
    FOREIGN KEY (routing_id) REFERENCES routings(id),
    FOREIGN KEY (assigned_station_id) REFERENCES stations(id)
) COMMENT='生产工单主表' ENGINE=InnoDB;

-- 关键索引
CREATE INDEX idx_work_orders_factory_id ON work_orders(factory_id);
CREATE INDEX idx_work_orders_status ON work_orders(status);
CREATE INDEX idx_work_orders_code ON work_orders(factory_id, work_order_code);
CREATE INDEX idx_work_orders_sales_order_id ON work_orders(sales_order_id);
CREATE INDEX idx_work_orders_product_id ON work_orders(product_id);
CREATE INDEX idx_work_orders_created_at ON work_orders(factory_id, created_at DESC);
CREATE INDEX idx_work_orders_due_date ON work_orders(planned_due);
CREATE INDEX idx_work_orders_station ON work_orders(assigned_station_id);
-- 组合索引：查询工厂+状态+日期
CREATE INDEX idx_work_orders_composite ON work_orders(factory_id, status, created_at DESC);
```

#### work_order_materials (工单物料清单)

```sql
CREATE TABLE work_order_materials (
    id VARCHAR(32) PRIMARY KEY,
    work_order_id VARCHAR(32) NOT NULL,
    material_id VARCHAR(32),
    material_code VARCHAR(50),
    material_name VARCHAR(256),
    qty_per_unit INT,                   -- 每件产品需要的数量
    required_qty INT,                   -- 总需求 = qty_per_unit * work_order_qty
    unit VARCHAR(20),
    received_qty INT DEFAULT 0,
    available_qty INT DEFAULT 0,
    shortage_qty INT DEFAULT 0,
    remark TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (work_order_id) REFERENCES work_orders(id)
) COMMENT='工单物料清单';

CREATE INDEX idx_work_order_materials_wo_id ON work_order_materials(work_order_id);
CREATE INDEX idx_work_order_materials_material_id ON work_order_materials(material_id);
```

---

### 2.3 工艺路线表

#### routings (工艺路线主表)

```sql
CREATE TABLE routings (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    product_id VARCHAR(32) NOT NULL,
    version VARCHAR(50),
    status VARCHAR(20) DEFAULT 'active',  -- active/inactive/archived
    remark TEXT,
    created_by VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
) COMMENT='工艺路线';

CREATE INDEX idx_routings_factory_id ON routings(factory_id);
CREATE INDEX idx_routings_product_id ON routings(product_id);
```

#### routing_steps (工序)

```sql
CREATE TABLE routing_steps (
    id VARCHAR(32) PRIMARY KEY,
    routing_id VARCHAR(32) NOT NULL,
    sequence INT NOT NULL,              -- 工序序号 1,2,3...
    operation_name VARCHAR(256) NOT NULL,
    operation_code VARCHAR(50),
    station_id VARCHAR(32) NOT NULL,
    setup_time INT DEFAULT 0,          -- 秒
    standard_time INT NOT NULL,        -- 秒
    tools TEXT,                         -- JSON: ["工具1", "工具2"]
    materials TEXT,                     -- JSON: ["材料1", "材料2"]
    parameters TEXT,                    -- JSON: {"temperature": 260, ...}
    quality_check TINYINT DEFAULT 0,   -- 是否需要质检
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (routing_id) REFERENCES routings(id),
    FOREIGN KEY (station_id) REFERENCES stations(id)
) COMMENT='工艺路线详情-工序';

CREATE INDEX idx_routing_steps_routing_id ON routing_steps(routing_id);
CREATE INDEX idx_routing_steps_station_id ON routing_steps(station_id);
CREATE UNIQUE INDEX idx_routing_steps_seq ON routing_steps(routing_id, sequence);
```

---

### 2.4 生产报工表 (核心)

#### production_reports (生产报工)

```sql
CREATE TABLE production_reports (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    work_order_id VARCHAR(32) NOT NULL,
    station_id VARCHAR(32) NOT NULL,
    
    report_type VARCHAR(50) NOT NULL,  -- normal(正常)/补料/返工
    
    good_qty INT NOT NULL,
    defect_qty INT NOT NULL,
    scrap_qty INT DEFAULT 0,
    
    shift VARCHAR(20),                 -- day(日班)/night(夜班)/overtime(加班)
    shift_date DATE,                   -- 班次日期
    
    operator_id VARCHAR(32),
    equipment_id VARCHAR(32),
    
    standard_time INT,                 -- 秒
    actual_time INT,                   -- 秒
    time_efficiency DECIMAL(5,2),      -- 时间效率 = standard_time / actual_time
    
    report_time DATETIME NOT NULL,
    
    status VARCHAR(20) DEFAULT 'submitted',  -- submitted(提交)/confirmed(确认)/rejected(驳回)
    
    approved_by VARCHAR(32),
    approved_at DATETIME,
    
    remark TEXT,
    attachment_id VARCHAR(32),        -- 附件ID
    
    created_by VARCHAR(32),
    updated_by VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (work_order_id) REFERENCES work_orders(id),
    FOREIGN KEY (station_id) REFERENCES stations(id)
) COMMENT='生产报工';

-- 分表策略：按月分表 (production_reports_202601, production_reports_202602...)
CREATE INDEX idx_production_reports_wo_id ON production_reports(work_order_id);
CREATE INDEX idx_production_reports_station_id ON production_reports(station_id);
CREATE INDEX idx_production_reports_shift ON production_reports(shift_date, shift);
CREATE INDEX idx_production_reports_created_at ON production_reports(created_at DESC);
-- 复合索引：用于班次看板查询
CREATE INDEX idx_production_reports_shift_board ON production_reports(
    station_id, shift_date, shift, created_at DESC
);
-- 唯一索引：防止重复报工 (同一工单同班次同工位不能重复报)
-- 注：这需要业务逻辑配合处理，不建议数据库层强制
```

#### production_report_defects (报工缺陷明细)

```sql
CREATE TABLE production_report_defects (
    id VARCHAR(32) PRIMARY KEY,
    production_report_id VARCHAR(32) NOT NULL,
    defect_type VARCHAR(100) NOT NULL,  -- 短路/漏焊/冷焊
    qty INT NOT NULL,
    severity VARCHAR(20),              -- high/medium/low
    remark TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (production_report_id) REFERENCES production_reports(id)
) COMMENT='报工缺陷明细';

CREATE INDEX idx_report_defects_report_id ON production_report_defects(production_report_id);
CREATE INDEX idx_report_defects_type ON production_report_defects(defect_type);
```

---

### 2.5 检验表

#### inspections (检验单)

```sql
CREATE TABLE inspections (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    
    inspection_type VARCHAR(50) NOT NULL,  -- IQC/IPQC/FQC/OQC
    
    -- 关联物料或工单
    material_id VARCHAR(32),               -- IQC时填
    work_order_id VARCHAR(32),             -- IPQC/FQC/OQC时填
    
    batch_id VARCHAR(50),
    batch_size INT,
    sample_size INT,
    
    -- AQL检验标准
    aql DECIMAL(5,2),  -- 2.5%, 1.0% 等
    accept_number INT, -- 接收数
    reject_number INT, -- 拒收数
    
    -- 检验结果
    overall_result VARCHAR(20),         -- pass/fail
    good_qty INT,
    defect_qty INT,
    
    -- 检验人员和时间
    inspector_id VARCHAR(32),
    inspection_time DATETIME,
    
    status VARCHAR(20) DEFAULT 'draft',  -- draft/inspecting/completed/passed/failed
    
    created_by VARCHAR(32),
    updated_by VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (work_order_id) REFERENCES work_orders(id)
) COMMENT='检验单主表';

CREATE INDEX idx_inspections_factory_id ON inspections(factory_id);
CREATE INDEX idx_inspections_type ON inspections(inspection_type);
CREATE INDEX idx_inspections_work_order_id ON inspections(work_order_id);
CREATE INDEX idx_inspections_material_id ON inspections(material_id);
CREATE INDEX idx_inspections_created_at ON inspections(created_at DESC);
```

#### inspection_items (检验项目)

```sql
CREATE TABLE inspection_items (
    id VARCHAR(32) PRIMARY KEY,
    inspection_id VARCHAR(32) NOT NULL,
    item_name VARCHAR(256) NOT NULL,   -- 外观/尺寸/性能
    standard VARCHAR(512),             -- 检验标准
    measurement_type VARCHAR(50),      -- visual(目检)/measurement(测量)/functional(功能)
    result VARCHAR(20),                -- pass/fail
    measured_value VARCHAR(100),       -- 实际测量值
    remark TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (inspection_id) REFERENCES inspections(id)
) COMMENT='检验项目明细';

CREATE INDEX idx_inspection_items_inspection_id ON inspection_items(inspection_id);
```

---

### 2.6 不良品表

#### defects (不良品)

```sql
CREATE TABLE defects (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    
    work_order_id VARCHAR(32),
    defect_type VARCHAR(100) NOT NULL,
    defect_level VARCHAR(20),          -- A(严重)/B(重)/C(一般)
    defect_qty INT,
    
    root_cause TEXT,                   -- 根本原因
    discovery_location VARCHAR(256),   -- 发现位置：贴片/组装/测试
    
    inspection_id VARCHAR(32),         -- 关联的检验单
    production_report_id VARCHAR(32),
    
    status VARCHAR(20) DEFAULT 'open',
    -- open(打开) → in_repair(处理中) → closed(已关闭)
    
    disposition VARCHAR(50),           -- 处置：rework(返工)/repair(返修)/scrap(报废)/accept(特采)
    
    assigned_to VARCHAR(32),
    discovered_by VARCHAR(32),
    handled_by VARCHAR(32),
    
    discovered_at DATETIME,
    handled_at DATETIME,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (work_order_id) REFERENCES work_orders(id),
    FOREIGN KEY (inspection_id) REFERENCES inspections(id)
) COMMENT='不良品登记表';

CREATE INDEX idx_defects_factory_id ON defects(factory_id);
CREATE INDEX idx_defects_work_order_id ON defects(work_order_id);
CREATE INDEX idx_defects_status ON defects(status);
CREATE INDEX idx_defects_type ON defects(defect_type);
CREATE INDEX idx_defects_created_at ON defects(created_at DESC);
```

---

### 2.7 纠正措施表 (OCAP)

#### ocaps (纠正措施)

```sql
CREATE TABLE ocaps (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    
    ocap_number VARCHAR(50) NOT NULL UNIQUE,
    
    defect_id VARCHAR(32),             -- 关联的缺陷
    trigger_reason TEXT,               -- 触发原因
    
    root_cause_analysis TEXT,          -- RCA分析
    
    corrective_action TEXT,            -- 纠正措施
    responsible_person VARCHAR(32),
    target_due_date DATE,
    
    verification_method VARCHAR(256),  -- 验证方法
    effectiveness_check TEXT,          -- 有效性检查
    
    status VARCHAR(20) DEFAULT 'open', -- open/in_progress/completed/verified/closed
    
    priority VARCHAR(20),              -- high/medium/low
    
    created_by VARCHAR(32),
    updated_by VARCHAR(32),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at DATETIME,
    
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (defect_id) REFERENCES defects(id)
) COMMENT='纠正措施 (OCAP)';

CREATE INDEX idx_ocaps_factory_id ON ocaps(factory_id);
CREATE INDEX idx_ocaps_defect_id ON ocaps(defect_id);
CREATE INDEX idx_ocaps_status ON ocaps(status);
CREATE INDEX idx_ocaps_due_date ON ocaps(target_due_date);
```

---

### 2.8 库存表

#### inventory (库存)

```sql
CREATE TABLE inventory (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    warehouse_id VARCHAR(32) NOT NULL,
    location_id VARCHAR(100),          -- 库位 A-01-01
    
    material_id VARCHAR(32),
    material_code VARCHAR(50),
    material_name VARCHAR(256),
    
    qty INT DEFAULT 0,                 -- 库存数量
    available_qty INT DEFAULT 0,       -- 可用数量
    reserved_qty INT DEFAULT 0,        -- 预留数量
    
    unit VARCHAR(20),
    cost_price DECIMAL(18, 6),
    total_cost DECIMAL(18, 6),
    
    batch_id VARCHAR(50),              -- 批次号
    supplier_id VARCHAR(32),
    
    receive_date DATE,
    expiry_date DATE,
    
    status VARCHAR(20) DEFAULT 'normal',  -- normal/quarantine/damaged/obsolete
    
    last_count_at DATETIME,
    last_counted_by VARCHAR(32),
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (warehouse_id) REFERENCES stations(id)  -- warehouse是特殊的station
) COMMENT='库存表';

CREATE INDEX idx_inventory_factory_warehouse ON inventory(factory_id, warehouse_id);
CREATE INDEX idx_inventory_material_id ON inventory(material_id);
CREATE INDEX idx_inventory_batch_id ON inventory(batch_id);
CREATE UNIQUE INDEX idx_inventory_composite ON inventory(
    warehouse_id, location_id, material_id, batch_id
);
```

#### inventory_movements (库存流水)

```sql
CREATE TABLE inventory_movements (
    id VARCHAR(32) PRIMARY KEY,
    
    movement_type VARCHAR(50) NOT NULL,  -- in/out
    
    material_id VARCHAR(32),
    batch_id VARCHAR(50),
    qty INT,
    
    warehouse_id VARCHAR(32),
    location_id VARCHAR(100),
    
    -- 关联单据
    work_order_id VARCHAR(32),
    purchase_order_id VARCHAR(50),
    
    operator_id VARCHAR(32),
    movement_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    remark TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (material_id) REFERENCES products(id)  -- 物料也可以是product
) COMMENT='库存流水账';

CREATE INDEX idx_inventory_movements_material_id ON inventory_movements(material_id);
CREATE INDEX idx_inventory_movements_movement_time ON inventory_movements(movement_time DESC);
CREATE INDEX idx_inventory_movements_work_order_id ON inventory_movements(work_order_id);
```

---

### 2.9 设备管理表

#### equipment (设备)

```sql
CREATE TABLE equipment (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32) NOT NULL,
    
    equipment_code VARCHAR(50) NOT NULL,
    equipment_name VARCHAR(256),
    equipment_type VARCHAR(100),       -- 生产/检测/辅助
    
    manufacturer VARCHAR(256),
    model VARCHAR(100),
    serial_number VARCHAR(100),
    
    station_id VARCHAR(32),
    purchase_date DATE,
    warranty_expire_date DATE,
    
    status VARCHAR(20) DEFAULT 'running',  -- running/maintenance/idle/scrap
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (factory_id) REFERENCES factories(id),
    FOREIGN KEY (station_id) REFERENCES stations(id)
) COMMENT='设备表';

CREATE INDEX idx_equipment_factory_id ON equipment(factory_id);
CREATE INDEX idx_equipment_station_id ON equipment(station_id);
```

#### equipment_maintenance (设备维保)

```sql
CREATE TABLE equipment_maintenance (
    id VARCHAR(32) PRIMARY KEY,
    equipment_id VARCHAR(32) NOT NULL,
    
    maintenance_type VARCHAR(50),      -- preventive/corrective
    maintenance_date DATE,
    
    maintenance_items TEXT,            -- JSON
    
    performed_by VARCHAR(32),
    duration_hours INT,                -- 维保耗时小时
    
    parts_replaced TEXT,
    cost DECIMAL(18, 6),
    
    next_maintenance_date DATE,
    
    remark TEXT,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
) COMMENT='设备维保记录';

CREATE INDEX idx_equipment_maintenance_equipment_id ON equipment_maintenance(equipment_id);
CREATE INDEX idx_equipment_maintenance_date ON equipment_maintenance(maintenance_date DESC);
```

---

### 2.10 用户权限表

#### users (用户)

```sql
CREATE TABLE users (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32),            -- 可以跨工厂
    
    username VARCHAR(128) NOT NULL UNIQUE,
    email VARCHAR(256) UNIQUE,
    password_hash VARCHAR(256),
    
    real_name VARCHAR(128),
    phone VARCHAR(20),
    
    role_id VARCHAR(32),
    
    status VARCHAR(20) DEFAULT 'active',  -- active/inactive/locked
    
    last_login DATETIME,
    login_count INT DEFAULT 0,
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (factory_id) REFERENCES factories(id)
) COMMENT='用户表';

CREATE UNIQUE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_factory_id ON users(factory_id);
```

#### roles (角色)

```sql
CREATE TABLE roles (
    id VARCHAR(32) PRIMARY KEY,
    factory_id VARCHAR(32),
    
    role_name VARCHAR(128) NOT NULL,
    description TEXT,
    
    status VARCHAR(20) DEFAULT 'active',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (factory_id) REFERENCES factories(id)
) COMMENT='角色表';

CREATE INDEX idx_roles_factory_id ON roles(factory_id);
```

#### role_permissions (角色权限)

```sql
CREATE TABLE role_permissions (
    id VARCHAR(32) PRIMARY KEY,
    role_id VARCHAR(32) NOT NULL,
    permission_id VARCHAR(32) NOT NULL,
    
    FOREIGN KEY (role_id) REFERENCES roles(id),
    UNIQUE KEY uk_role_permission (role_id, permission_id)
) COMMENT='角色权限关联';
```

---

## 三、分区与索引策略

### 3.1 分表方案

```sql
-- 按月分表：production_reports
production_reports_202601  (2026年1月)
production_reports_202602  (2026年2月)
production_reports_202603  (2026年3月)

-- 按季度分表：inspections
inspections_q1_2026
inspections_q2_2026

-- 按工厂分表：defects
defects_factory_sh_01
defects_factory_bj_01

-- 应用层实现：分表路由
def get_table_name(table_base, date_or_factory_id):
    if table_base == 'production_reports':
        month = date_or_factory_id.strftime('%Y%m')
        return f'{table_base}_{month}'
    elif table_base == 'defects':
        return f'{table_base}_{factory_id}'
    return table_base
```

### 3.2 核心索引设计总结

| 表名 | 索引 | 用途 |
|------|------|------|
| work_orders | (factory_id, status, created_at) | 工单查询 |
| work_orders | (sales_order_id) | 订单关联 |
| work_orders | (assigned_station_id) | 工位排程 |
| production_reports | (station_id, shift_date, shift) | 班次看板 |
| production_reports | (work_order_id, report_time) | 工单报工 |
| inspections | (work_order_id) | 工单检验 |
| defects | (defect_type, created_at) | 缺陷统计 |
| inventory | (warehouse_id, material_id) | 库存查询 |
| inventory | (batch_id) | 批次追溯 |

---

## 四、数据一致性约束

### 4.1 业务规则约束

```sql
-- CHECK 约束：确保数据有效性

ALTER TABLE work_orders
ADD CONSTRAINT chk_work_order_qty 
CHECK (completed_qty <= planned_qty);

ALTER TABLE work_orders
ADD CONSTRAINT chk_work_order_date 
CHECK (actual_start <= actual_complete);

ALTER TABLE production_reports
ADD CONSTRAINT chk_production_report_qty 
CHECK (good_qty + defect_qty + scrap_qty > 0);

ALTER TABLE inventory
ADD CONSTRAINT chk_inventory_qty 
CHECK (available_qty <= qty AND reserved_qty <= qty);
```

### 4.2 引用完整性

```sql
-- 工单删除时的级联处理
ALTER TABLE production_reports
ADD CONSTRAINT fk_production_reports_wo
FOREIGN KEY (work_order_id) REFERENCES work_orders(id)
ON DELETE RESTRICT  -- 防止删除有报工的工单
ON UPDATE CASCADE;

-- 工艺路线删除时
ALTER TABLE work_orders
ADD CONSTRAINT fk_work_orders_routing
FOREIGN KEY (routing_id) REFERENCES routings(id)
ON DELETE SET NULL
ON UPDATE CASCADE;
```

---

## 五、视图设计

### 5.1 统计视图

#### v_work_order_progress (工单进度视图)

```sql
CREATE VIEW v_work_order_progress AS
SELECT
    wo.id,
    wo.work_order_code,
    p.product_name,
    wo.planned_qty,
    wo.completed_qty,
    wo.good_qty,
    wo.defect_qty,
    ROUND(wo.completed_qty * 100.0 / wo.planned_qty, 2) AS progress_rate,
    ROUND(wo.good_qty * 100.0 / wo.completed_qty, 2) AS pass_rate,
    wo.status,
    wo.planned_due,
    DATEDIFF(wo.planned_due, CURDATE()) AS days_remaining
FROM work_orders wo
LEFT JOIN products p ON wo.product_id = p.id
WHERE wo.deleted_at IS NULL;
```

#### v_shift_board (班次看板视图)

```sql
CREATE VIEW v_shift_board AS
SELECT
    s.id AS station_id,
    s.station_name,
    CURDATE() AS shift_date,
    'day' AS shift,
    COUNT(pr.id) AS report_count,
    SUM(pr.good_qty) AS total_good,
    SUM(pr.defect_qty) AS total_defect,
    ROUND(SUM(pr.defect_qty) * 100.0 / 
        SUM(pr.good_qty + pr.defect_qty), 2) AS defect_rate,
    s.capacity,
    ROUND(SUM(pr.good_qty + pr.defect_qty) * 100.0 / s.capacity, 2) AS capacity_util
FROM stations s
LEFT JOIN production_reports pr ON s.id = pr.station_id
    AND pr.shift_date = CURDATE()
    AND pr.shift = 'day'
GROUP BY s.id, s.station_name;
```

#### v_defect_summary (缺陷统计视图)

```sql
CREATE VIEW v_defect_summary AS
SELECT
    d.defect_type,
    d.defect_level,
    COUNT(*) AS defect_count,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM defects WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)), 2) AS percentage
FROM defects d
WHERE d.created_at >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
GROUP BY d.defect_type, d.defect_level
ORDER BY defect_count DESC;
```

---

## 六、数据库参数配置

### 6.1 PostgreSQL 配置 (推荐)

```sql
-- 连接配置
max_connections = 500
max_prepared_transactions = 500

-- 内存配置
shared_buffers = 8GB              -- 物理内存的 25%
effective_cache_size = 24GB       -- 物理内存的 75%
work_mem = 32MB                   -- per operation
maintenance_work_mem = 1GB

-- WAL 日志
wal_buffers = 16MB
wal_writer_delay = 200ms

-- 查询优化
random_page_cost = 1.1            -- SSD硬盘设置
effective_io_concurrency = 200
```

### 6.2 MySQL 配置 (如果选择MySQL)

```ini
[mysqld]
# 连接
max_connections=500
max_allowed_packet=64M

# 内存
innodb_buffer_pool_size=8G        # 物理内存的 75%
innodb_log_file_size=2G
tmp_table_size=128M
max_heap_table_size=128M

# 优化
innodb_flush_log_at_trx_commit=2  # 性能和安全的平衡
query_cache_type=0                # 禁用查询缓存，用Redis替代
query_cache_size=0

# 主从复制
binlog_format=ROW
log_bin=mysql-bin
relay-log=mysql-relay-bin
server-id=1                       # Master: 1, Slave: 2,3
```

---

## 七、数据库迁移脚本 (Alembic)

### 7.1 创建初始迁移

```python
# alembic/versions/001_initial_schema.py

from alembic import op
import sqlalchemy as sa

def upgrade():
    # 创建factories表
    op.create_table(
        'factories',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('code', sa.String(50), nullable=False, unique=True),
        sa.Column('status', sa.String(20), default='active'),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )
    op.create_index('idx_factories_code', 'factories', ['code'])
    
    # 创建其他表...
    pass

def downgrade():
    op.drop_table('factories')
    pass
```

### 7.2 执行迁移

```bash
# 初始化迁移目录
alembic init alembic

# 创建新迁移
alembic revision --autogenerate -m "add work_orders table"

# 执行迁移到最新
alembic upgrade head

# 回滚迁移
alembic downgrade -1
```

---

## 八、ER图（文本表示）

```
┌─────────────────────────────────────────────────────────────────┐
│                      EngHub MES 数据库ER图                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐                                               │
│  │  factories   │◄─────────────────┐                            │
│  ├──────────────┤                  │                            │
│  │ id (PK)      │                  │                            │
│  │ name         │                  │                            │
│  │ code (UQ)    │                  │                            │
│  └──────────────┘                  │                            │
│         │                          │                            │
│         ├──────┬──────────┬────────┼──────────┐                 │
│         │      │          │        │          │                 │
│    ┌────▼──┐ ┌─▼────┐ ┌──▼────┐ ┌─▼───────┐ │                 │
│    │  ..   │ │  .   │ │  ..   │ │   ..    │ │                 │
│    └───────┘ └──────┘ └───────┘ └────────┘ │                 │
│                                             │                 │
│  ┌────────────────────┐  ┌──────────────┐  │                 │
│  │   work_orders      │  │   stations   │◄─┘                 │
│  ├────────────────────┤  ├──────────────┤                     │
│  │ id (PK)            │  │ id (PK)      │                     │
│  │ product_id (FK)    │  │ station_code │                     │
│  │ routing_id (FK)    │  │ capacity     │                     │
│  │ planned_qty        │  └──────────────┘                     │
│  │ completed_qty      │         ▲                             │
│  │ status             │         │                             │
│  │ priority           │  ┌──────┴──────────┐                  │
│  └────────┬───────────┘  │                 │                  │
│           │         ┌────▼──────────┐ ┌───▼────────┐          │
│           │         │ routing_steps │ │ equipment  │          │
│           │         ├───────────────┤ ├────────────┤          │
│           │         │ routing_id    │ │ station_id │          │
│           │         │ sequence      │ └────────────┘          │
│           │         │ operation     │                         │
│           │         │ setup_time    │                         │
│           │         │ standard_time │                         │
│           │         └───────────────┘                         │
│           │                                                    │
│    ┌──────▼───────────────────────┐                          │
│    │  production_reports          │                          │
│    ├──────────────────────────────┤                          │
│    │ id (PK)                      │                          │
│    │ work_order_id (FK)           │                          │
│    │ station_id (FK)              │                          │
│    │ good_qty, defect_qty         │                          │
│    │ shift, shift_date            │                          │
│    │ status                       │                          │
│    │ report_time                  │                          │
│    └──────┬──────────────────────┘                          │
│           │                                                  │
│    ┌──────▼──────────────────┐                              │
│    │ production_report_      │                              │
│    │ defects                 │                              │
│    ├─────────────────────────┤                              │
│    │ defect_type             │                              │
│    │ qty                     │                              │
│    │ severity                │                              │
│    └────────────────────────┘                              │
│                                                              │
│  ┌────────────────────┐    ┌──────────────┐               │
│  │  inspections       │    │   defects    │               │
│  ├────────────────────┤    ├──────────────┤               │
│  │ id (PK)            │    │ id (PK)      │               │
│  │ inspection_type    │    │ defect_type  │               │
│  │ work_order_id      │    │ work_order   │               │
│  │ sample_size        │    │ status       │               │
│  │ overall_result     │    │ disposition  │               │
│  └────────┬───────────┘    └──────┬───────┘               │
│           │                       │                        │
│    ┌──────▼─────────┐      ┌─────▼──────────┐            │
│    │ inspection_    │      │     ocaps      │            │
│    │ items          │      ├────────────────┤            │
│    ├────────────────┤      │ ocap_number    │            │
│    │ item_name      │      │ root_cause     │            │
│    │ result         │      │ corrective_act │            │
│    │ measured_value │      │ status         │            │
│    └────────────────┘      └────────────────┘            │
│                                                            │
│  ┌─────────────────┐      ┌──────────────────┐           │
│  │   inventory     │      │ inventory_       │           │
│  ├─────────────────┤      │ movements        │           │
│  │ id (PK)         │      ├──────────────────┤           │
│  │ material_id     │      │ material_id      │           │
│  │ warehouse_id    │      │ movement_type    │           │
│  │ qty             │      │ qty              │           │
│  │ batch_id        │      │ movement_time    │           │
│  └─────────────────┘      └──────────────────┘           │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## 总结：数据库设计原则

| 原则 | 实践 |
|------|------|
| **规范化** | 3NF设计，避免冗余 |
| **性能** | 合理索引、分表分库、读写分离 |
| **扩展性** | 支持多工厂、多租户的字段设计 |
| **安全性** | 外键约束、检查约束、软删除 |
| **可维护性** | 清晰的命名、充分的注释、版本控制 |
| **可追踪性** | 审计字段 (created_at/updated_at/created_by) |
