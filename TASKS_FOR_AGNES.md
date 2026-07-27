# 任务指派 - 来自 Qoder (主集成智能体)

> 协作方式：完成后 git commit & push，我会 pull 后做集成验证。
> 日期：2026-07-24

---

## 你的能力评估（基于你之前提交的 IE 模块代码）

**擅长：**
- 模块脚手架搭建（routes/services/schemas 三件套结构清晰）
- 业务逻辑设计（IE 精益生产的领域建模思路正确）
- 批量 CRUD 端点编写

**需要改进（我已帮你修了以下系统性错误）：**
- ❌ `await query` → ✅ `await self.db.execute(query)` （SQLAlchemy async 必须用 session.execute）
- ❌ `.from_pydict()` → Pydantic v2 没有这个方法，用 `Model(**dict)` 或直接返回 dict
- ❌ 引用模型不存在的字段（如 `EmployeeSkill.is_active`）→ 写之前先查 `database/models.py`
- ❌ 缺少 import（BaseModel, select, or_ 等）→ 写完自查 import 完整性
- ❌ `func.date(col, '+N days')` → PostgreSQL 不支持，用 Python `timedelta`

---

## 本次任务：IE 模块数据种子脚本

### 目标
创建 `scripts/seed_ie_data.py`，为 IE 精益生产模块填充演示数据。

### 要求

1. **连接方式**（复制此模式，不要改）：
```python
import asyncio
import sys
sys.path.insert(0, ".")

from database.db_config import db_config
from database.models import Base

async def main():
    await db_config.initialize()
    async with db_config.session_factory() as session:
        # 你的逻辑
        await session.commit()
    await db_config.close()

if __name__ == "__main__":
    asyncio.run(main())
```

2. **需要填充的表**（参考 `database/models.py` 中的定义）：
   - `standard_operation_times`：至少 10 条，覆盖 factory-sh-01 的 3 个产品
   - `time_study_records`：至少 8 条，关联上面的标准工时
   - `line_balance_analyses`：至少 3 条
   - `process_analyses`：至少 5 条
   - `action_studies`：至少 4 条
   - `work_cell_layouts`：至少 2 条

3. **数据要合理**：
   - `standard_time` 范围 30~300 秒
   - `performance_rating` 范围 0.85~1.15
   - `line_balance_rate` 范围 0.65~0.95
   - 时间字段用 `datetime.utcnow()`
   - factory_id 统一用 `"factory-sh-01"`

4. **禁止事项**：
   - 不要修改 `database/models.py`
   - 不要修改任何已有路由/服务文件
   - 不要创建新的路由或服务
   - 不要使用 `await query`，必须 `await session.execute(query)`

5. **验证**：写完后运行 `python scripts/seed_ie_data.py`，确保无报错。

### 交付物
- `scripts/seed_ie_data.py`（一个文件即可）

---

## 未来任务预告（本次不用做）

- IE 模块前端页面（React + Ant Design，参考 `frontend/src/` 现有结构）
- 5S 审计和 Kanban 的 CRUD 完善
- 单元测试 `tests/test_ie_module.py`

---

## 集成规则

1. 你的代码我会做以下检查：
   - `python -c "from scripts.seed_ie_data import main"` 无 ImportError
   - 实际运行脚本无异常
   - 数据确实写入数据库
2. 如果有问题我会在此文件追加反馈，你 pull 后查看
3. commit message 格式：`feat(ie): seed demo data for IE module`
