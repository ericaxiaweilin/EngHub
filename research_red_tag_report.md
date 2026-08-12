# 质量红单（Quality Red Tag）功能设计方案

## 1. 业务背景

**Red Tag（质量红单）** 是制造业质量管理中的关键工具，用于标识和隔离不合格品，防止非预期的使用或流转。在 QMS 模块当前缺少质量红单功能，需要与现有不良品（Defect）流程集成。

## 2. 业务流程

### 2.1 红单创建流程
1. **触发点**：在缺陷记录（Defect）创建后，或直接在检验环节触发
2. **红单编号**：系统自动生成，格式：`RT-YYYYMMDD-NNNN`（如 `RT-20260802-0001`）
3. **红单内容**：
   - 关联缺陷 ID
   - 关联检验记录 ID（可选）
   - 红单类型：来料 / 制程 / 成品 / 客户退货
   - 缺陷描述
   - 不合格数量
   - 批次号
   - 工序/工作站
   - 发现人
   - 发现时间
   - 严重等级（Critical / Major / Minor）
   - 照片/附件

### 2.2 红单处置流程
1. **隔离**：将不合格品移至隔离区（Quarantine）
2. **评审**：MRB（Material Review Board）评审
   - 判定方式：报废（Scrap）/ 返工（Rework）/ 让步接收（Use As Is）/ 退货（RTV）
3. **处置执行**：执行判定动作
4. **关闭**：更新缺陷状态为已处置

### 2.3 红单与不良品的关联
- 一个缺陷可以关联多个红单（分批处理）
- 红单必须关联缺陷记录
- 红单状态影响缺陷的 disposition 流程

## 3. 数据模型设计

### 3.1 QualityRedTag 表

```sql
CREATE TABLE quality_red_tag (
    id VARCHAR(36) PRIMARY KEY,
    factory_id VARCHAR(36) NOT NULL,
    red_tag_no VARCHAR(50) UNIQUE NOT NULL,  -- 红单编号 RT-YYYYMMDD-NNNN
    defect_id VARCHAR(36) NOT NULL,          -- 关联缺陷记录
    inspection_id VARCHAR(36),               -- 关联检验记录（可选）
    red_tag_type VARCHAR(20) NOT NULL,       -- INCOMING/IN_PROCESS/FINAL/CUSTOMER_RETURN
    defect_description TEXT,                 -- 缺陷描述
    nonconforming_qty DECIMAL(12,4) NOT NULL,-- 不合格数量
    batch_no VARCHAR(100),                   -- 批次号
    work_order_id VARCHAR(36),               -- 关联工单
    station_id VARCHAR(36),                  -- 关联工作站
    discovered_by VARCHAR(36),               -- 发现人
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    severity VARCHAR(20) DEFAULT 'MINOR',    -- CRITICAL/MAJOR/MINOR
    quarantine_status VARCHAR(20) DEFAULT 'SEATED', -- SEATED/QUARANTINED/RELEASED
    disposition VARCHAR(20),                 -- SCRAP/REWORK/USE_AS_IS/RTV/NO_DEFECT
    disposition_by VARCHAR(36),              -- 处置审批人
    disposition_date TIMESTAMP,              -- 处置日期
    disposition_notes TEXT,                  -- 处置说明
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    created_by VARCHAR(36),
    FOREIGN KEY (defect_id) REFERENCES defect_records(id) ON DELETE CASCADE,
    FOREIGN KEY (inspection_id) REFERENCES inspections(id) ON DELETE SET NULL,
    FOREIGN KEY (work_order_id) REFERENCES work_orders(id) ON DELETE SET NULL,
    FOREIGN KEY (station_id) REFERENCES stations(id) ON DELETE SET NULL
);
```

### 3.2 红单附件表

```sql
CREATE TABLE quality_red_tag_attachments (
    id VARCHAR(36) PRIMARY KEY,
    red_tag_id VARCHAR(36) NOT NULL,
    file_id VARCHAR(36) NOT NULL,            -- 关联 files 表
    attachment_type VARCHAR(20) DEFAULT 'PHOTO', -- PHOTO/DOCUMENT/INSPECTION_REPORT
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (red_tag_id) REFERENCES quality_red_tag(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);
```

## 4. API 设计

### 4.1 红单管理接口
- `POST /api/v1/qms/red-tags` - 创建红单
- `GET /api/v1/qms/red-tags` - 查询红单列表
- `GET /api/v1/qms/red-tags/{id}` - 获取红单详情
- `PUT /api/v1/qms/red-tags/{id}` - 更新红单
- `DELETE /api/v1/qms/red-tags/{id}` - 删除红单
- `POST /api/v1/qms/red-tags/{id}/disposition` - 提交处置
- `GET /api/v1/qms/red-tags/statistics` - 统计信息

### 4.2 缺陷关联接口
- `GET /api/v1/qms/defects/{id}/red-tags` - 获取缺陷关联的红单
- `POST /api/v1/qms/defects/{id}/red-tags` - 为缺陷创建红单
- `PUT /api/v1/qms/defects/{id}/red-tag/{red_tag_id}` - 更新红单与缺陷的关联

## 5. 前端页面设计

### 5.1 红单列表页
- 红单编号、类型、缺陷描述、数量、状态、处置方式、创建时间
- 筛选：类型、状态、时间范围、工厂
- 操作：创建、查看、编辑、处置、删除

### 5.2 红单详情页
- 基本信息
- 缺陷信息（可跳转到缺陷详情）
- 处置流程（隔离→评审→处置→关闭）
- 附件列表
- 操作按钮：隔离、提交处置、关闭

### 5.3 红单创建页
- 关联缺陷选择（可选）
- 红单类型选择
- 缺陷信息填写
- 不合格数量、批次号、工作站
- 照片上传

## 6. 集成到不良品流程

### 6.1 缺陷创建时自动触发红单
- 当缺陷被创建且 disposition 为 HOLD 时，自动创建红单
- 用户可以选择是否立即创建红单

### 6.2 红单状态联动缺陷状态
- 红单隔离 → 缺陷状态变为 QUARANTINE
- 红单处置 → 缺陷 disposition 更新
- 红单关闭 → 缺陷状态变为 RESOLVED

### 6.3 统计报表集成
- 红单数量统计
- 处置方式分布
- 严重程度分布
- 与 CAPA 流程联动

## 7. 实施计划

### Phase 1: 数据库与后端
- [ ] 创建迁移脚本
- [ ] 实现 RedTag Service
- [ ] 实现 RedTag API
- [ ] 集成到缺陷流程

### Phase 2: 前端
- [ ] 红单列表页
- [ ] 红单详情页
- [ ] 红单创建/编辑页
- [ ] 集成到缺陷管理流程

### Phase 3: 高级功能
- [ ] 红单统计报表
- [ ] CAPA 联动
- [ ] 审批流程
