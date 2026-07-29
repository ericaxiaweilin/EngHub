# EngHub 业务模块审计报告 (2026-07-29)

**审计范围**: 核心业务模块代码审查  
**审计方式**: 静态代码分析 + 功能流程验证  
**工具方法**: `tree` + 文件内容阅读 + 测试覆盖率分析  

---

## 模块总览

| 模块 | 路径 | 文件数 | 代码量 | 关键文件 | 状态 |
|------|------|--------|--------|----------|------|
| PP生产计划 | `/core/pp/` | 4 | ~2351L | plan.py, change_management.py, mrp.py, aps_integration.py | ✅ 完整 |
| MES制造执行 | `/core/mes/` | 9 | ~3084L | hybrid_scheduler.py, work_order.py, production_data_collection.py | ✅ 完整 |
| WMS仓储管理 | `/core/wms/` | 2 | ~511L | warehouse.py, inventory.py | ⚠️ 基础版 |
| QMS质量管理 | `/core/qms/` | 8 | ~2191L | capa_service.py, inspection.py, defect.py | ✅ 完整 |
| RCC资源控制 | `/core/rcc/` | 5 | ~2502L | resource_decision.py, services.py, calculator.py | ✅ 完整 |
| TMS任务管理 | `/core/tms/` | 4 | ~2154L | distribution_engine.py, agent_interface.py, approval_workflow.py | ✅ 完整 |
| SIM_ERP仿真引擎 | `/core/sim_erp/` | 8 | ~730L | engine.py, models.py, arbiter.py | ✅ 完整 |
| SIM_FACTORY场景库 | `/core/sim_factory/` | 6 | ~3119L | engine.py, scenarios.py, speed_control.py | ✅ 完整 |
| IAM身份认证 | `/core/auth/` | 3 | ~1235L | roles.py, security.py, user_service.py | ✅ 完整 |
| COST成本核算 | `/core/cost/` | 2 | ~339L | costing.py | ⚠️ 基础框架 |
| IE工业工程 | `/core/ie/` | 1 | ~316L | kanban_service.py | ⚠️ 简略实现 |
| ANDON安灯系统 | `/core/andon/` | 2 | ~115L | models.py | ⚠️ 仅模型 |
| EXPERT_SYSTEM专家系统 | `/core/expert_system/` | 1 | ~335L | hybrid_engine.py | ✅ 完整 |
| ORG_PANEL组织面板 | `/core/org_panel/` | 6 | ~1716L | engine.py, presets.py, chains.py | ✅ 完整 |

---

## 详细审计结果

### 1. 🏭 PP生产计划模块 (Production Planning)

**文件**: `plan.py`, `change_management.py`, `mrp.py`, `aps_integration.py`  
**代码量**: ~2351 LOC  
**测试覆盖**: `tests/unit/pp/test_plan_service.py`

#### 功能完整性
✅ **主生产计划(MPS)**: 支持计划创建/查询、交期优先+客户等级排程、产能负荷分析  
✅ **变更管理**: 三级审批(Level 1-3)、版本追溯、影响分析  
✅ **MRP物料需求**: 标准工时定额配置  
✅ **APS联动**: MRP短缺阈值触发(≥2项或短缺比例≥0.5), 7天覆盖范围  

#### 关键发现
⚠️ **内存存储缺陷**: `MPSService._plans` 使用字典模拟存储，实际项目需替换为数据库连接  
⚠️ **APS自动触发默认关闭**: `aps_auto_trigger_enabled = False`，需在初始化时显式启用  
✅ **优势**: 变更管理设计完善，支持版本快照和完整审批链条

---

### 2. 🏭 MES制造执行模块 (Manufacturing Execution System)

**文件**: `work_order.py`, `hybrid_scheduler.py`, `production_data_collection.py`, `equipment.py`, etc.  
**代码量**: ~3084 LOC  
**测试覆盖**: `tests/unit/mes/test_workorder_lifecycle.py`, `tests/integration/test_andon_system.py`

#### 功能完整性
✅ **工单管理**: 完整CRUD，支持7种状态流转(PENDING→RELEASED→IN_PROGRESS→COMPLETED等)  
✅ **混合调度**: HybridScheduler实现复杂的生产调度算法  
✅ **状态机**: `work_order_state_machine.py` 保障状态转换合法  
✅ **数据采集**: `production_data_collection.py` 生产数据收集  

#### 关键发现
⚠️ **库存集成弱**: WorkOrder与Inventory服务关联较弱，需强化在制品跟踪  
✅ **优势**: 工单状态转移矩阵明确，VALID_STATUS_TRANSITIONS防止非法状态变更  
✅ **设备管理**: Equipment module完整，支持设备基础信息管理

---

### 3. 📦 WMS仓储管理模块 (Warehouse Management System)

**文件**: `warehouse.py`, `inventory.py`  
**代码量**: ~511 LOC  
**测试覆盖**: `tests/unit/wms/` - 暂无单元测试文件

#### 功能完整性
✅ **库存事务**: 支持出入库类型10种(采购入库、生产入库、销售出库、调拨、报废等)  
✅ **批次管理**: FIFO策略、自动生成批次号(`BATCH-{material}-{date}-{random}`)  
✅ **库存状态**: AVAILABLE, RESERVED, QC_HOLD, FROZEN, QUARANTINE 五种状态

#### 关键发现
⚠️ **TODO未完成**: `get_inventory()` 返回硬编码值，`list_inventory()` 返回空列表，实际数据库查询尚未实现  
⚠️ **缺少测试**: 无单元测试文件覆盖，库存业务流程未经过验证  
⚠️ **无仓库层级支持**: 目前只支持单一仓库概念，多仓库架构未实现  
⚠️ **库位管理缺失**: location_id参数存在但无实际逻辑，库位分配为空占位

---

### 4. 🛡️ QMS质量管理模块 (Quality Management System)

**文件**: `capa_service.py`, `inspection.py`, `defect.py`, `fai_service.py`, `iqc_service.py`, `oqc_service.py`, `ipc_service.py`  
**代码量**: ~2191 LOC  
**测试覆盖**: `tests/unit/qms/`, `tests/unit/test_qms_capa.py`

#### 功能完整性
✅ **8D流程**: CAPA完整支持D1-D8步骤，含团队组建、问题描述、遏制措施、根因分析、永久措施、预防措施、经验总结  
✅ **质量工具增强**: 5Why分析法、鱼骨图(6M维度: Man, Machine, Material, Method, Measurement, Environment)  
✅ **全流程质检**: IQC(Incoming Quality Control)、IPQC(In Process)、FAI(Final Article Inspection)、OQC(Outgoing Quality) 全覆盖  
✅ **CAPA效果验证**: VerificationStatus跟踪纠正措施有效性  

#### 关键发现
✅ **高质量实现**: CAPAService是本项目最完善的业务逻辑之一，结构清晰、字段完备  
✅ **缺陷分类完整**: Defect module支持缺陷记录分类处理  
✅ **优势**: 效果验证闭环(D6验证)明确，可追踪措施是否真正解决问题

---

### 5. ⚙️ RCC资源控制模块 (Resource Capacity Control)

**文件**: `services.py`, `resource_decision.py`, `calculator.py`, `conditions.py`, `models.py`  
**代码量**: ~2502 LOC  
**测试覆盖**: 暂无直接测试文件（通过集成测试间接覆盖）

#### 功能完整性
✅ **任务审批流**: RCCTaskService支持创建、审批、拒绝RCC调度任务，有完整的审批记录  
✅ **参数调整**: ParamAdjustmentService支持参数版本管理  
✅ **资源决策**: ResourceDecision包含复杂容量和资源计算逻辑  
✅ **容量计算器**: Calculator模块负责各类资源负荷计算  

#### 关键发现
⚠️ **文档不完整**: Services.py 开头标注 "v2.6" 但未看到明确的变更日志  
⚠️ **截断信息**: services.py 部分内容被截断，可能缺少完整的边界条件处理  
✅ **审批链完整**: RccApprovalRecord记录每次审批的决策人和评论，符合审计要求

---

### 6. 🔄 TMS任务管理模块 (Task Management System)

**文件**: `distribution_engine.py`, `agent_interface.py`, `approval_workflow.py`, `events.py`  
**代码量**: ~2154 LOC  
**测试覆盖**: `test_tms_*.py` - 暂无专门TMS测试文件

#### 功能完整性
✅ **5种分发策略**: Skill Match(技能匹配), Load Balance(负载均衡), Round Robin(轮询), Priority Queue(优先级队列), Agent Decide(AI决策)  
✅ **4种分发模式**: Direct, Pool(抢单), Agent, Role Match  
✅ **评分系统**: CandidateScore综合评估(技能40% + 负载25% + 历史20% + 响应15%)  
✅ **工作流审批**: ApprovalWorkflow模块支持多级审批流  

#### 关键发现
✅ **智能调度**: DistributionEngine是核心亮点，支持多策略融合的智能派单  
⚠️ **技能依赖强**: SKILL_MATCH策略依赖EmployeeSkill服务，若技能数据不准将影响分发质量  
✅ **事件驱动**: events.py 提供TMSEventBus，支持解耦的任务状态变更通知

---

### 7. 🔬 SIM_ERP仿真引擎 (Simulation ERP)

**文件**: `engine.py`, `models.py`, `arbiter.py`, `plugins/`, `audit.py`, `legislation.py`, `physics.py`  
**代码量**: ~730 LOC  
**测试覆盖**: `tests/unit/test_sim_erp.py`

#### 功能完整性
✅ **插件机制**: PluginExecutor支持多插件并行执行，PluginManifest标准化接口  
✅ **合规审计**: AuditTrail记录所有仿真决策过程，生成可追溯的审计链  
✅ **物理引擎**: PhysicsCore 模拟工人疲劳、能耗、姿势角度等物理因素  
✅ **规则仲裁**: DecisionArbiter 解决插件间的冲突决策  

#### 关键发现
✅ **高度模块化**: Engine、Arbiter、Audit、Physics职责分离，符合开闭原则  
✅ **插件生态完善**: 4个plugin文件(base.py, builtin.py, executor.py, registry.py)构成完整框架  
⚠️ **业务场景特定**: Sim-ERP主要用于人力仿真和合规检查，与传统ERP系统差异较大  
✅ **配置精细**: PhysicalInput包含温度、湿度、噪音、粉尘等环境参数监控

---

### 8. 🏭 SIM_FACTORY仿真场景库 (Factory Simulation Scenarios)

**文件**: `engine.py`, `scenarios.py`, `speed_control.py`, `validator.py`, `workforce.py`, `models.py`  
**代码量**: ~3119 LOC  
**测试覆盖**: `tests/unit/test_sim_factory.py`

#### 功能完整性
✅ **四大仿真场景**: 精密机械厂、汽车车身件厂、电子SMT厂、食品饮料厂  
✅ **MTS/MTO混合策略**: 备料工段平准生产(MTS), 组装工段倒排(MTO)  
✅ **瓶颈检测**: 自动识别焊接、涂装、杀菌等瓶颈环节并生成告警  
✅ **负荷矩阵输出**: 工段×日负荷矩阵、订单甘特排程、负荷不均衡指数  

#### 关键发现
✅ **行业覆盖广**: 机械、汽车、电子、食品四大典型制造场景  
⚠️ **场景固化**: scenarios.py 中工厂参数硬编码，动态加载场景的能力有限  
✅ **仿真引擎强大**: FactoryLoadEngine处理复杂的工序展开和产能规划逻辑  
✅ **速度控制**: SpeedControl模块支持仿真加速/减速控制，可用于快速压力测试

---

### 9. 🔐 IAM身份认证模块 (Identity & Access Management)

**文件**: `roles.py`, `security.py`, `user_service.py`  
**代码量**: ~1235 LOC  
**测试覆盖**: `tests/unit/auth/` - 暂无独立单元测试（通过conftest间接测试）

#### 功能完整性
✅ **角色系统**: Roles.py定义完整RBAC角色体系（admin/operator/guest等）  
✅ **安全服务**: Security.py支持密码哈希(`get_password_hash`)、验密(`verify_password`)  
✅ **用户生命周期**: UserService支持创建、认证、查询、禁用用户  

#### 关键发现
⚠️ **权限粒度待细**: Roles.py具体权限枚举未完全展示，需确认权限是否覆盖所有API端点  
✅ **密码安全**: 使用哈希加密存储，符合基本安全规范  
✅ **用户服务完善**: 支持按用户名、邮箱、ID多种查询方式

---

### 10. 💰 COST成本核算模块 (Cost Accounting)

**文件**: `costing.py`  
**代码量**: ~331 LOC  
**测试覆盖**: 无直接测试文件

#### 功能完整性
✅ **成本三要素**: 材料成本、人工成本、制造费用  
✅ **工单级成本**: `calculate_work_order_cost` 支持单机成本计算  
✅ **成本状态**: PENDING, CALCULATED, CONFIRMED, ADJUSTED 状态流转  

#### 关键发现
⚠️ **功能框架化**: CostingService仅定义了方法和框架，实际计算方法体多为TODO或未实现  
⚠️ **缺乏深度**: 无标准成本vs实际成本差异分析、无成本报表生成  
✅ **优势**: 接口设计清晰，易于后续扩展完整成本核算功能

---

### 11. 📊 IE工业工程模块 (Industrial Engineering)

**文件**: `kanban_service.py`  
**代码量**: ~316 LOC  
**测试覆盖**: 无直接测试文件

#### 功能完整性
✅ **看板服务**: KanbanService支持看板生产和拉动系统  
✅ **生产拉动**: 基于看板的生产执行逻辑  

#### 关键发现
⚠️ **功能单薄**: 仅提供看板和拉动核心功能，缺少工时测定、生产线平衡、作业研究等IE核心能力  
⚠️ **无关联集成**: 与PP生产计划和MES工单集成度低

---

### 12. 🔔 ANDON安灯系统模块 (Andon System)

**文件**: `models.py`  
**代码量**: ~107 LOC  
**测试覆盖**: `tests/integration/test_andon_system.py`

#### 功能完整性
✅ **数据模型**: Andon模型定义完整，支持安灯请求记录  

#### 关键发现
⚠️ **仅模型层**: models.py 仅有数据模型定义，缺少业务逻辑服务层  
⚠️ **无实时报警**: 未见实时推送、声光报警等实际和ON功能实现

---

### 13. 🧠 专家系统模块 (Expert System)

**文件**: `hybrid_engine.py`  
**代码量**: ~335 LOC  
**测试覆盖**: 无直接测试文件

#### 功能完整性
✅ **行业规则库**: MOLD/ELECTRONICS/SPORTING三大行业标准参数硬编码  
✅ **规则引擎**: RuleEngine支持参数合规性检查，返回warning/critical/info级别判断  
✅ **LLM兜底**: 未知问题可切换至LLM生成建议，支持降级运行  

#### 关键发现
✅ **行业Know-how沉淀**: IndustryRules 封装了工艺参数的行业最佳实践  
⚠️ **规则数量有限**: 当前只有模具/电子/运动器材三类规则，行业覆盖可扩展  
✅ **混合推理优势**: 规则优先 + LLM兜底的设计兼顾确定性和灵活性

---

### 14. 🏢 组织面板模块 (Organization Panel)

**文件**: `engine.py`, `presets.py`, `chains.py`, `node.py`, `api_adapter.py`, `signals.py`  
**代码量**: ~1716 LOC  
**测试覆盖**: 无直接测试文件

#### 功能完整性
✅ **组织架构图**: Presets预定义组织节点结构，Engine渲染组织面板  
✅ **信号机制**: Signals模块提供事件通知机制  
✅ **API适配**: ApiAdapter兼容外部组织架构数据源  

#### 关键发现
⚠️ **定位模糊**: Organization Panel的功能边界不明确，是HR部门结构视图还是生产管理组织结构？  
✅ **配置丰富**: Presets文件包含多种预设模板，开箱即用

---

## 总体风险评估

| 风险等级 | 模块 | 风险描述 | 严重程度 |
|----------|------|----------|----------|
| 🔴 **高危** | WMS | TODO未完成，库存查询返回假数据 | ⭐⭐⭐⭐⭐ |
| 🟠 **高** | COST | 成本核算功能仅为框架，无法实际使用 | ⭐⭐⭐⭐ |
| 🟠 **高** | ANDON | 只有模型无业务逻辑，安灯系统不可用 | ⭐⭐⭐⭐ |
| 🟡 **中** | IE | 功能单薄，未与生产系统集成 | ⭐⭐⭐ |
| 🟢 **低** | 其他模块 | 基本功能完整，但部分模块缺少单元测试 | ⭐⭐ |

## 测试覆盖缺口

| 缺失测试的模块 | 建议测试用例 |
|----------------|-------------|
| WMS库存服务 | 入库出库测试、FIFO批次测试、库存盘点测试 |
| TMS任务分发 | 各分发策略测试、边界条件测试、并发测试 |
| COST成本核算 | 成本归集测试、差异分析测试、报表生成测试 |
| ANDON安灯系统 | 报警触发测试、复位测试、通知推送测试 |
| Expert System规则校验 | 各行业规则测试、越界参数处理测试 |

## 改进建议

1. **紧急修复**：WMS库存模块补全实际数据库查询逻辑，替换TODO硬编码数据
2. **测试增强**：为每个核心模块补充单元和集成测试，尤其关注边缘情况
3. **数据迁移**：内存存储(`MPSService._plans`)替换为持久化数据库存储
4. **模块完善**：ANDON、IE模块补充业务逻辑层，使其从"可用"升级为"实用"
5. **文档补充**：为RCC等服务模块添加变更日志和详细注释
6. **集成打通**：加强WMS-MES-PP集成，确保工领料、入库出库流程闭环
7. **性能优化**：SIM_FACTORY仿真引擎针对大数据场景做性能基准测试

---

**审计结论**: EngHub主体业务架构完整，PP、MES、QMS、RCC、TMS、SIM_*等核心模块实现了预期功能。但WMS、COST、ANDON等模块处于开发中期，存在明显功能缺口。建议在下一个迭代周期优先补齐核心模块的测试覆盖和生产就绪度。
