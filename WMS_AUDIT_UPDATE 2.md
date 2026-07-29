# WMS 模块优化报告 (2026-07-29)

## 问题诊断

在业务模块审计中发现 WMS 库存服务存在以下严重问题：

| 问题 | 文件 | 行号 | 描述 |
|------|------|------|------|
| `get_inventory()` 返回硬编码值 | `/core/wms/inventory.py` | ~58-73 | 完全未查询数据库，返回假数据 `{total_qty: 10000, available_qty: 9500, ...}` |
| `list_inventory()` 返回空列表 | `/core/wms/inventory.py` | ~75-87 | 没有实际查询逻辑，总是返回 `[]` |
| `_get_fifo_batches()` 使用示例数据 | `/core/wms/inventory.py` | ~142-156 | 注释 TODO 仍存在，使用硬编码示例而非真实批次数据 |
| `inbound()` 只创建内存记录 | `/core/wms/inventory.py` | ~90-120 | 入库操作未持久化到数据库，重启即丢失 |
| `outbound()` 未更新库存余额 | `/core/wms/inventory.py` | ~122-140 | 出库只创建记录，不扣减 Inventory 表余额 |
| `warehouse.py` 大部分功能未实现 | `/core/wms/warehouse.py` | 多个方法 | `list_warehouses()`, `list_locations()` 等返回空列表或 None |

## 修复方案

### 1. inventory.py - 完整重写为数据库集成版

**核心变更**:

- ✅ **构造函数注入**: `__init__(self, db_session: AsyncSession)` — 依赖注入 AsyncSession，符合项目中其他服务的模式
- ✅ **get_inventory()**: 从 `Inventory` 表查询，按 material_id 和 warehouse_id 过滤，返回聚合数据和批次信息
- ✅ **list_inventory()**: 支持 factory_id、warehouse_id、material_id、status 多条件过滤，返回完整的库存记录列表
- ✅ **inbound()**: 
  - 创建 `InboundOrder` 入库订单持久化存储
  - 检查并更新现有 `Inventory` 记录（累加 qty），或新建库存记录
  - 设置正确的 status 和 last_movement_at
- ✅ **outbound()**: 
  - FIFO 策略：从 `Inventory` 表按 created_at ASC 获取可用批次
  - 扣减库存：减少 available_qty 和 total_qty
  - 创建 `OutboundOrder` 出库订单持久化存储
- ✅ **_get_fifo_batches()**: 实际查询 `Inventory` 表，按接收日期排序，排除指定批次
- ✅ **get_material_trace()**: 追溯物料历史，包括 inbound_orders + outbound_order 流 + 当前库位
- ✅ **保留原有功能**: reserve_inventory, create_inventory_count, submit_count_result 等保持不变（这些本来就没有 DB 交互）

### 2. warehouse.py - 添加 TODO 占位符和查询模板

虽然仓库服务仍使用内存实现（因仓库表初始化为空），但添加了查询注释模板，便于后续直接替换为真实 DB 查询。

## 使用的数据库模型

```
Inventory       ← 库存主表 (总库量、可用量、预留量、批次码、状态)
InboundOrder    ← 入库订单记录
OutboundOrder   ← 出库订单记录
Warehouses      ← 仓库表 (已定义在 models.py 待填充)
Locations       ← 库位表 (已定义在 models.py 待填充)
```

## 使用方法示例

```python
from core.wms.inventory import InventoryService, TransactionType

# 在路由或服务中传入 db session
inventory_service = InventoryService(db_session)

# 入库
await inventory_service.inbound(
    factory_id="FACT-001",
    warehouse_id="WH-001",
    material_id="MAT-001",
    material_code="MAT-001",
    quantity=1000,
    unit_cost=10.5,
    supplier_id="SUP-001",
    purchase_order_id="PO-2026001",
    created_by="user001"
)

# 查询库存
inventory = await inventory_service.get_inventory("MAT-001", "WH-001")
print(inventory)  # {"material_id": "MAT-001", "total_qty": 1000, "available_qty": 1000, ...}

# 出库 (FIFO)
await inventory_service.outbound(
    factory_id="FACT-001",
    warehouse_id="WH-001",
    material_id="MAT-001",
    quantity=500,
    work_order_id="WO-2026001",
    created_by="user001"
)

# 追溯
trace = await inventory_service.get_material_trace("MAT-001")
print(trace["inbound_records"])  # 所有入库历史
print(trace["outbound_records"]) # 所有出库历史
```

## 下一步建议

1. **补充测试用例**: 创建 `tests/unit/wms/test_inventory_service.py`，覆盖：
   - 入库后查询库存验证
   - FIFO 出库顺序验证
   - 库存不足异常处理
   - 物料追溯完整性

2. **完善 warehouse.py**: 将 TODO 部分替换为真实的 SQLAlchemy 查询，使用 Warehouse 和 Location 模型

3. **集成到 API 路由**: 更新 `wms_routes.py` 和 `wms_phase3_routes.py` 传递 db_session 给 service

4. **数据迁移**: 若有旧数据需迁移到 InboundOrder/OutboundOrder/Inventory 表

5. **添加仓库种子数据**: 通过 seed 脚本初始化几个测试仓库和库位
