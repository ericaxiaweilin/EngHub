# EngHub MES 开发更新报告

## 本次开发内容

### 1. 数据库模型扩展 (database/models.py)

新增以下核心数据表：

#### PP (生产计划) 模块
- **ProductionPlan**: 主生产计划 (MPS) 表
  - 支持计划状态流转：draft → confirmed → released → in_progress → completed
  - 优先级评分系统 (交期紧迫度 + 客户等级 + 原始优先级)
  - 客户等级分类：VIP/A/B/C
  
- **MRPResult**: 物料需求计划结果表
  - 关联生产计划
  - 记录总短缺量和总价值
  
- **MRPItem**: MRP 明细项表
  - BOM 展开的物料需求
  - 采购建议 (数量、日期、优先级)

#### QMS (质量管理) 模块
- **Inspection**: 检验单表
  - 支持 IQC/IPQC/FQC/OQC 四种检验类型
  - AQL 检验水平配置
  - 样本大小自动计算
  
- **Defect**: 不良品单表
  - 批次级追溯 (batch_id, work_order_id, station_id)
  - 处置方式：返工/返修/报废/特采/退货
  - OCAP 触发状态跟踪
  
- **OCAP**: 纠正预防措施表
  - 根本原因分析
  - 纠正/预防措施记录

#### Cost (成本核算) 模块
- **WorkOrderCost**: 工单成本表
  - 材料成本 + 人工成本 + 制造费用
  - 单位成本计算
  
- **ProductStandardCost**: 产品标准成本表
  - 标准成本 vs 实际成本差异分析基础

### 2. API 路由增强

#### PP Routes (api/routes/pp_routes.py)
已集成完整的生产计划 API:
- `POST /api/v1/plans` - 创建生产计划
- `GET /api/v1/plans` - 获取计划列表 (按优先级排序)
- `GET /api/v1/plans/{plan_id}` - 获取计划详情
- `POST /api/v1/plans/{plan_id}/confirm` - 确认计划
- `POST /api/v1/plans/{plan_id}/release` - 下达计划
- `POST /api/v1/mrp/calculate` - 计算 MRP
- `GET /api/v1/capacity/analysis` - 产能负荷分析

#### QMS Routes (api/routes/qms_routes.py)
已集成完整的质量管理 API:
- `POST /api/v1/inspections` - 创建检验单 (自动验证必填字段)
- `POST /api/v1/inspections/{id}/submit` - 提交检验结果 (自动 AQL 判定)
- `POST /api/v1/inspections/{id}/associate` - IQC 关联工单
- `GET /api/v1/defects` - 获取不良品列表
- `POST /api/v1/defects/{id}/disposition` - 提交处置方案
- `POST /api/v1/defects/{id}/ocap` - 触发 OCAP
- `GET /api/v1/defects/batch/{batch_id}/trace` - 批次追溯

### 3. 服务层实现 (api/services/pp_service.py)

新增 PPService 服务类，提供:
- 异步数据库操作 (使用 SQLAlchemy 2.0 async)
- 生产计划 CRUD 操作
- 计划状态流转控制
- MRP 计算与结果管理
- 产能负荷分析接口

### 4. 核心业务逻辑

#### 优先级评分算法
```
优先级分数 = 交期紧迫度 (0-100) + 客户等级权重 (0-50) + 原始优先级 (0-50)
```

#### AQL 判定逻辑
- 根据批量大小自动查表获取样本大小代码
- 根据 AQL 等级获取 Ac/Re 判定数
- 自动判定合格/不合格

#### OCAP 触发规则
- CRITICAL 级别缺陷 → 必须触发
- MAJOR 级别 ≥ 5 件 → 触发
- 工艺/材料不良 ≥ 3 件 → 触发

## 技术栈更新

- **后端**: FastAPI + SQLAlchemy 2.0 (Async)
- **数据库**: PostgreSQL (推荐) / SQLite (开发)
- **认证**: JWT + python-jose
- **密码加密**: passlib + bcrypt

## API 端点统计

| 模块 | 端点数量 | 状态 |
|------|---------|------|
| PP (生产计划) | 11 | ✅ 已完成 |
| QMS (质量管理) | 13 | ✅ 已完成 |
| MES (工单管理) | 20+ | ✅ 已完成 |
| WMS (仓库管理) | 15+ | ✅ 已完成 |
| Auth (认证) | 5 | ✅ 已完成 |

## 下一步建议

1. **前端页面开发**
   - 生产计划排程看板
   - 检验单录入界面
   - 不良品处理工作流
   - 成本报表展示

2. **数据库迁移脚本**
   - 使用 Alembic 管理 schema 变更
   - 初始化数据种子

3. **单元测试**
   - PP 服务层测试
   - QMS 业务逻辑测试
   - API 集成测试

4. **文档完善**
   - API 文档 (Swagger/OpenAPI)
   - 用户操作手册

## 验证结果

✅ 所有模块导入成功
✅ 应用启动正常
✅ 路由注册完成 (24 个 PP+QMS 端点)
✅ 数据库模型验证通过

---
*生成时间：2026-01-XX*
*EngHub MES Team*
