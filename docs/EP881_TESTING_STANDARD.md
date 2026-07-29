# EP881 单元测试建设标准规范

## 目录

1. [规范概述](#1-规范概述)
2. [测试分类体系](#2-测试分类体系)
3. [文件命名与目录结构](#3-文件命名与目录结构)
4. [测试代码编写规范](#4-测试代码编写规范)
5. [断言与验证规范](#5-断言与验证规范)
6. [Fixture 与依赖注入规范](#6-fixture与依赖注入规范)
7. [Mock 策略与工具使用规范](#7-mock策略与工具使用规范)
8. [测试配置要求](#8-测试配置要求)
9. [覆盖率要求](#9-覆盖率要求)
10. [CI/CD 集成规范](#10-cicd集成规范)
11. [异常与错误处理规范](#11-异常与错误处理规范)
12. [性能与执行时间规范](#12-性能与执行时间规范)
13. [遗留测试迁移指南](#13-遗留测试迁移指南)

---

## 1. 规范概述

### 1.1 适用范围

本规范适用于 EngHub 平台所有 Python 项目的单元测试体系建设，包括但不限于：

- `core/` 下的所有业务模块
- `api/` 下的所有 API 路由层
- 各集成模块（sim_erp、sim_factory、rcc、mes、qms 等）

### 1.2 目标

- ✅ **自动化**：测试需完全自动化，支持一键执行
- ✅ **快速性**：单元测试套件执行时间 ≤ 5 分钟
- ✅ **独立性**：测试之间无状态依赖，可并行运行
- ✅ **可重复性**：相同输入下结果确定性一致
- ✅ **清晰性**：失败时提供明确的错误定位信息

### 1.3 版本信息

| 版本号 | 日期 | 修改人 | 说明 |
|--------|------|--------|------|
| 1.0.0  | 2026-07-29 | AgnesCode | 初始版本 |

---

## 2. 测试分类体系

### 2.1 三级测试金字塔

```
                            E2E / 端到端测试 (10%)
                              ↑
                    集成测试 / Integration Test (30%)
                              ↑
                单元测试 / Unit Test (60%)
```

### 2.2 单元测试 (Unit Test) - 优先级最高

**定义**：对最小可测试单元（函数、方法、类）进行的隔离测试。

**特征**：
- 不依赖外部系统（数据库、网络、文件系统）
- 执行速度快（单个测试 < 100ms）
- 使用 Mock/Fake 替代所有外部依赖
- 每个测试只验证一个行为点

**适用场景**：
- 纯函数计算逻辑
- 业务规则判断
- 算法实现
- 数据处理转换
- 异常路径验证

### 2.3 集成测试 (Integration Test)

**定义**：验证多个单元组件协同工作的正确性。

**特征**：
- 允许连接真实数据库（使用 test database）
- 可调用实际 API 接口
- 需要更多 Setup/Cleanup 成本
- 执行速度中等（单个测试 1-5 秒）

**适用场景**：
- 多模块交互流程
- 数据库 CRUD 操作
- API 端点验证
- 第三方服务集成
- 事务边界测试

### 2.4 端到端测试 (End-to-End Test)

**定义**：模拟用户完整业务流程的测试。

**特征**：
- 需要完整的运行环境（应用 + 数据库 + 缓存 + MQ）
- 执行速度慢（单个测试 10-30 秒）
- 仅覆盖核心业务主线

**适用场景**：
- 关键用户路径（如工单创建→审批→执行）
- 跨系统数据同步
- 复杂工作流引擎

> ⚠️ **EP881 建议**：单元测试覆盖率应 ≥ 80%，集成测试覆盖率 ≥ 60%。

---

## 3. 文件命名与目录结构

### 3.1 命名规范

| 测试类型 | 文件命名模式 | 示例 |
|----------|-------------|------|
| 单元测试 | `test_<module_name>.py` | `test_sim_erp.py` |
| 集成测试 | `integration_test_<module_name>.py` | `integration_test_api_auth.py` |
| E2E 测试 | `e2e_<workflow_name>.py` | `e2e_order_workflow.py` |

> ✅ **强制要求**：文件名必须以 `test_` 开头或 `_test.py` 结尾。

### 3.2 目录结构

```bash
project_root/
├── src/                  # 源代码（生产环境）
│   └── core/
│       ├── sim_erp/
│       ├── sim_factory/
│       └── ...
├── tests/                # 所有测试代码（分目录管理）
│   ├── __init__.py
│   ├── conftest.py       # 全局 fixture 配置
│   │
│   ├── unit/             # 单元测试集
│   │   ├── __init__.py
│   │   ├── test_sim_erp.py
│   │   ├── test_sim_factory.py
│   │   └── ...
│   │
│   ├── integration/      # 集成测试集
│   │   ├── __init__.py
│   │   ├── test_andon_system.py
│   │   ├── test_rcc_decisions.py
│   │   └── ...
│   │
│   ├── e2e/            # 端到端测试集
│   │   ├── __init__.py
│   │   └── ...
│   └── fixtures/       # 共享测试数据 fixtures
│       ├── __init__.py
│       ├── factory_objects.py
│       └── mock_services.py
│
├── test.config          # 测试配置文件
├── .coveragerc         # coverage.py 配置
├── pytest.ini          # pytest 配置
└── requirements-dev.txt  # 开发依赖
```

### 3.3 模块级测试文件映射

对于 `core/<module_name>/` 目录下的模块，应创建对应的测试文件：

```
core/sim_erp/           → tests/unit/test_sim_erp.py
core/sim_factory/       → tests/unit/test_sim_factory.py
core/mes/               → tests/unit/test_mes_core.py
core/rcc/               → tests/unit/test_rcc_resource_decision.py
core/qms/               → tests/unit/test_qms_capa.py
api/routes/auth_routes.py → tests/integration/test_api_auth.py
```

---

## 4. 测试代码编写规范

### 4.1 AAA 模式（Arrange-Act-Assert）

所有单元测试必须遵循 **AAA 模式**，代码结构清晰：

```python
class TestCalculator:

    def test_add_positive_numbers(self):
        # Arrange
        calc = Calculator()
        a = 5
        b = 3
        expected = 8

        # Act
        result = calc.add(a, b)

        # Assert
        assert result == expected
```

#### 4.1.1 分区注释

使用分隔线注释标记三个阶段：

```python
def test_calculate_discount(self):
    # ============================================ #
    # 1. Arrange（准备阶段）                       #
    # ============================================ #
    customer = Customer(membership_level=VIP)
    product = Product(price=1000)

    # ============================================ #
    # 2. Act（执行阶段）                           #
    # ============================================ #
    discount = discount_engine.calculate(customer, product)

    # ============================================ #
    # 3. Assert（断言阶段）                        #
    # ============================================ #
    assert discount == 200
```

### 4.2 测试类与方法命名规范

| 原则 | 格式 | 示例 |
|------|------|------|
| 测试类名 | `Test<ModuleUnderTest>` | `TestSimERP`, `TestAndonSystem` |
| 测试方法名 | `should_<条件>_<预期行为>` 或 `test_<方法名>_<场景>` | `test_add_negative_numbers_raises_error` |
| 描述性命名 | 反映测试目的 | `test_duplicate_username_raises_conflict_error` |

**❌ 不推荐的命名**：
```python
def test_function_one(self): pass              # ❌ 无意义
def test_case_1(self): pass                   # ❌ 过于抽象
def check_login(self): pass                   # ❌ 缺少 test_前缀
```

**✅ 推荐的命名**：
```python
def test_valid_credentials_allow_login(self): pass
def test_invalid_password_rejects_login(self): pass
```

### 4.3 测试组织原则

- 每个测试文件对应一个模块/类的测试
- 相关测试用例归入同一个测试类
- 不同功能区域用 `class` 分组
- 使用 `@pytest.mark.parametrize` 参数化多种场景

```python
class TestPaymentProcessor:
    
    class TestSuccessCases:
        def test_credit_card_payment(self): pass
        def test_paypal_payment(self): pass
    
    class TestFailureCases:
        def test_insufficient_funds(self): pass
        def test_expired_card(self): pass
    
    class TestEdgeCases:
        def test_zero_amount_payment(self): pass
```

---

## 5. 断言与验证规范

### 5.1 单一断言原则

每个测试方法应只包含 **一个主要断言点**，如果有多重验证，拆分为多个测试方法：

```python
# ❌ 反例：多重验证合并
def test_user_creation(self):
    user = create_user(...)
    assert user.id is not None
    assert user.email == "test@example.com"
    assert user.role == "user"
    assert created_at is not None

# ✅ 正例：拆分测试
def test_user_has_id(self): pass
def test_user_email_set_correctly(self): pass
def test_user_default_role_is_user(self): pass
def test_user_created_at_set(self): pass
```

### 5.2 常用断言工具

```python
import pytest

# 基本断言
assert result is not None
assert isinstance(result, dict)

# 异常断言
with pytest.raises(ValueError):
    process_invalid_input()

# 浮点数精度比较
assert result == pytest.approx(0.1 + 0.2, rel=1e-9)

# 集合匹配
assert actual_set == expected_set

# 字典子集匹配
assert actual_dict.items() >= expected_dict.items()

# 断言包含
assert "error" in log_message.lower()

# 断言数量
assert len(items) == 5

# 顺序检查
assert sequence == [1, 2, 3]
```

### 5.3 错误消息自定义

在复杂断言中提供自定义错误信息，帮助快速定位问题：

```python
assert actual == expected, f"\n期望值: {expected}\n实际值: {actual}\n差异: {actual - expected}"

# 或使用 unittest.TestCase 风格的 assertEqual（如果使用）
self.assertEqual(actual, expected, f"计算结果不一致: expected={expected}, got={actual}")
```

---

## 6. Fixture 与依赖注入规范

### 6.1 Fixture 作用域选择

| 作用域 | 用途 | 风险 |
|--------|------|------|
| `function` (默认) | 每次测试创建新实例 | ✅ 最安全 |
| `class` | 同组测试复用 | ⚠️ 注意状态污染 |
| `module` | 整个文件复用 | ⚠️ 谨慎使用 |
| `session` | 全局复用（如 DB 连接） | ⚠️ 仅限惰性资源 |

**✅ 推荐**：默认使用 `function` 作用域，除非有明确的性能优化需求。

### 6.2 Fixture 命名规范

| Fixture 类型 | 命名模式 | 示例 |
|--------------|----------|------|
| 数据库连接 | `db_session` | `@pytest.fixture` |
| Mock 对象 | `mock_<service>` | `mock_external_api` |
| 测试数据 | `<entity>_factory` | `user_factory` |
| 系统上下文 | `app_context` | `@pytest.fixture(scope="session")` |

### 6.3 Fixture 依赖关系

允许 fixture 之间形成依赖链，但应保持清晰的流向：

```python
@pytest.fixture
def db_session():
    # 创建测试数据库会话
    return DatabaseSession()

@pytest.fixture
def mock_db(mock_db_connection):
    """基于 fixture 构建的 mock 对象"""
    return MockDatabase(mock_db_connection)

@pytest.fixture
def user_service(mock_db):
    return UserService(db=mock_db)
```

### 6.4 共享 Fixture 位置

- **全局 fixture**（所有测试共用）放在 `conftest.py`
- **模块专属 fixture** 放在对应测试文件或该目录下的 `conftest.py`

```python
# tests/conftest.py （全局 fixture）
import pytest

@pytest.fixture
def app_config():
    return load_test_config()

@pytest.fixture
def mock_logger():
    return MagicMock()
```

---

## 7. Mock 策略与工具使用规范

### 7.1 Mock 使用原则

| 情况 | 处理方式 |
|------|----------|
| 纯函数计算 | 直接调用，无需 Mock |
| 依赖外部系统 | 必须 Mock（DB、HTTP、文件、邮件等） |
| 依赖确定性服务 | 使用真实服务或固定返回（如 UUID v4） |
| 随机依赖 | 使用固定 seed 或通过 Mock 控制返回值 |

### 7.2 Mock 工具选择

| 场景 | 推荐工具 |
|------|----------|
| Python 标准库 mocking | `unittest.mock` |
| FastAPI 请求 mock | `httpx.AsyncClient` + `pytest-mock` |
| 异步函数 mock | `pytest-mock` + `AsyncMock` |
| 复杂对象构造 | `factory_boy` 或手动构建工厂函数 |

### 7.3 Mock 最佳实践

```python
from unittest.mock import patch, MagicMock, AsyncMock

# ✅ 正确：精确指定要 mock 的路径
@patch("mymodule.services.external_api_call", new_callable=MagicMock)
def test_process_data_with_mock_api(self, mock_api):
    mock_api.return_value = {"data": "test"}
    result = process_data()
    assert result["status"] == "success"

# ❌ 避免：过度泛化的 mock
@patch("mymodule.*")  # 这会意外 mock 太多东西

# ✅ 异步 mock
@patch("mymodule.async_service.fetch_data", new_callable=AsyncMock)
async def test_fetch_async(self, mock_fetch):
    mock_fetch.return_value = {"id": 1}
    result = await fetch_data_wrapper()
```

### 7.4 Mock 验证规范

所有 mock 调用都应进行验证：

```python
def test_api_call_arguments(self, mock_api):
    # Arrange
    mock_api.return_value = {"ok": True}

    # Act
    process_data({"id": 123})

    # Assert：验证调用参数
    mock_api.assert_called_once_with(id=123, timeout=30)
    # 或者
    assert mock_api.called
    call_args = mock_api.call_args_list
    assert len(call_args) == 1
```

---

## 8. 测试配置要求

### 8.1 pytest.ini 配置

```ini
# project_root/pytest.ini
[pytest]
addopts = -v --tb=short -q           # 默认启动参数
python_files = test_*.py              # 测试文件匹配模式
python_classes = Test*                # 测试类命名模式
python_functions = test_*             # 测试函数命名模式
asyncio_mode = auto                   # 自动检测 async/await
filterwarnings =
    error                           # 将警告视为错误
    ignore:DeprecationWarning       # 忽略特定警告
```

### 8.2 .coveragerc 配置

```ini
# project_root/.coveragerc
[run]
source = src, core                      # 要覆盖的源代码目录
omit = */tests/*, */migrations/*, */venv/*, /*.py  # 排除目录
parallel = true                         # 并行收集覆盖率数据

[report]
show_missing = true                     # 显示未覆盖的行
fail_under = 80                         # 覆盖率低于此值则失败（EP881 最低标准）
minimum_lines = 80                      # 最小代码行覆盖率要求
exclude_lines =
    pragma no cover
    raise NotImplementedError
    if TYPE_CHECKING

[html]
title = 测试覆盖率报告                  # HTML 报告标题
```

### 8.3 完整项目根配置文件

请确保项目根目录包含以下文件：

```
project_root/
├── pytest.ini
├── .coveragerc
├── requirements-dev.txt
└── tests/
    └── conftest.py
```

---

## 9. 覆盖率要求

### 9.1 覆盖率指标

根据 EP881 标准，单元测试覆盖率需达到以下指标：

| 模块类别 | 最低覆盖率 | 目标覆盖率 |
|----------|-----------|-----------|
| 核心业务逻辑（sim_erp, sim_factory, rcc） | 85% | 90%+ |
| API 路由层 | 70% | 80% |
| 工具函数/辅助模块 | 80% | 85% |
| 模型/DTO 类 | 60* | 70* |
| 配置初始化代码 | N/A* | N/A* |

> *模型类主要通过集成测试验证，单元测试侧重业务逻辑

### 9.2 覆盖率门禁设置

在 CI 流水线中添加覆盖率检查步骤：

```yaml
# GitHub Actions 示例
- name: Run tests with coverage
  run: pytest tests/ --cov=src --cov-report=xml
  
- name: Check coverage threshold
  run: |
    coverage report --format=table | tail -1 | awk '{print $4}' | grep -qP '^\d{1,2}\.\d+$' || exit 1
    # 或使用 coverage fail_under 在 .coveragerc 中直接设置
```

### 9.3 豁免规则

以下情况可豁免覆盖率要求，但需在代码中明确标注：

```python
# pragma: no cover - 无需覆盖的分支
if TYPE_CHECKING:  # type checking only code
    from typing import Any

# raise NotImplementedError - 待实现的功能
# unused configuration/code - 确实无人使用的遗留代码
```

---

## 10. CI/CD 集成规范

### 10.1 GitHub Actions 测试流水线

```yaml
# .github/workflows/unit-tests.yml

name: Unit Tests (EP881 Compliance)

on:
  pull_request:
    branches: [ main, develop ]
  push:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.10", "3.11"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev.txt

      - name: Run linter (optional)
        run: pip install black flake8 && flake8 src/ tests/ --max-line-length=120

      - name: Run tests with coverage
        run: pytest tests/ --cov=src --cov-report=xml

      - name: Upload coverage report
        uses: codecov/codecov@v3
        with:
          files: ./coverage.xml
          flags: unittests

      - name: Fail if coverage below threshold
        run: |
          COVERAGE=$(coverage report --format=summary | tail -1 | tr -d '%')
          if (( $(echo "$COVERAGE < 80" | bc -l) )); then
            echo "Coverage ${COVERAGE}% below EP881 threshold of 80%"
            exit 1
          fi
```

### 10.2 本地测试命令

开发者应执行以下命令来验证本地测试：

```bash
# 运行全部测试
pytest tests/ -v

# 运行单元测试
pytest tests/unit/ -v

# 带覆盖率报告
pytest tests/unit/ --cov=src --cov-report=term-missing

# 只运行失败的测试
pytest tests/unit/ --lf

# 筛选特定测试（按标记）
pytest tests/unit/ -v "test_sim*"

# 查看详细覆盖率报告
coverage html
# 打开 html/open.html 查看可视化报告
```

---

## 11. 异常与错误处理规范

### 11.1 测试中的异常捕获

```python
# ✅ 正确：使用 pytest.raises 验证异常
def test_divide_by_zero_raises(self):
    with pytest.raises(ZeroDivisionError, match="division by zero"):
        divide(10, 0)

# ✅ 也可捕获异常对象
def test_exception_details(self):
    with pytest.raises(ValueError) as excinfo:
        validate_email("invalid")
    assert "invalid email format" in str(excinfo.value)

# ❌ 错误：不应在生产测试代码中 try-except 正常业务异常
try:
    result = risky_operation()
except ValueError:
    result = None
assert result is None  # 应使用上面的 pytest.raises
```

### 11.2 测试数据清理

确保每次测试后不会留下残留数据：

```python
@pytest.fixture
def clean_database(db_session):
    """确保测试前后数据库处于干净状态"""
    # 保存原始状态或在事务中自动回滚
    yield
    db_session.rollback()  # 每个测试后回滚事务
```

或使用 pytest 的事务回滚特性：

```python
@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()
```

---

## 12. 性能与执行时间规范

### 12.1 单次测试执行时间

| 测试级别 | 最大执行时间 |
|----------|-------------|
| 单元测试 | ≤ 100 ms |
| 集成测试 | ≤ 5 s |
| E2E 测试 | ≤ 30 s |

### 12.2 超时保护

对于可能挂起的测试，添加超时装饰器：

```python
import pytest
from pytest_timeout import timeout

@timeout(5, method="thread")  # 5秒超时
def test_might_block(self):
    # 测试内容
    pass
```

### 12.3 性能基准监控

对于关键性能敏感的测试（如仿真引擎），记录执行时间：

```python
import time

def test_simulator_performance(self):
    start = time.time()
    result = engine.run(config)
    elapsed = time.time() - start
    
    assert elapsed < 2.0, f"仿真耗时 {elapsed:.2f}s，超过阈值 2s"
```

---

## 13. 遗留测试迁移指南

### 13.1 现状分析

当前项目测试结构（基于 `/Users/thanhhuyennguyen/Desktop/EngHub/tests`）：

```
tests/
├── __init__.py
├── test_andon_system.py              # ⚠️ 位于根目录，应移至 integration/
├── test_data_driven_scheduling.py    # ⚠️ 位于根目录，应移至 integration/
└── unit/
    ├── __init__.py
    ├── test_sim_erp.py               # ✅ 符合规范
    └── test_sim_factory.py           # ✅ 符合规范
```

迁移优先级排序（从高到低）：

1. **重构现有测试到正确目录**（test_andon_system.py → tests/integration/）
2. **为缺失模块补全单元测试**（所有 core/ 下的模块应有对应 test_*.py）
3. **添加 conftest.py** 统一管理 fixture
4. **配置 pytest.ini 和 .coveragerc**
5. **添加 pre-commit 钩子** 保证提交质量

### 13.2 迁移步骤

#### 步骤 1：移动并重命名测试文件

```bash
mv tests/test_andon_system.py tests/integration/
mv tests/test_data_driven_scheduling.py tests/integration/
```

#### 步骤 2：创建 conftest.py

```python
# tests/conftest.py
"""全局测试配置与共享 fixture"""

import pytest
from unittest.mock import MagicMock, patch

@pytest.fixture
def mock_db_connection():
    """模拟数据库连接"""
    return MagicMock()

@pytest.fixture
def fake_current_user():
    """模拟当前登录用户"""
    return MagicMock(user_id="test-user", roles=["admin"])

# 加载测试配置
@pytest.fixture(scope="module")
def test_config():
    from core.db.config import TestingConfig
    return TestingConfig()
```

#### 步骤 3：添加新模块的单元测试模板

对于每一个尚未有测试的核心模块，创建模板文件：

```bash
# 示例：为 qms 模块创建单元测试
mkdir -p tests/unit/test_qms.py
```

参考已有的 test_sim_erp.py 和 test_sim_factory.py 的风格编写。

#### 步骤 4：添加 pre-commit 钩子

安装 pre-commit 并配置钩子：

```bash
pip install pre-commit pre-commit-hooks
pre-commit install
```

创建 `.pre-commit-config.yaml`：

```yaml
repos:
  - repo: local
    hooks:
      - id: pytest-unit
        name: Run unit tests
        entry: pytest tests/unit/ -v
        language: system
        types: [python]
        
      - id: flake8
        name: Lint code
        entry: flake8 --max-line-length=120
        language: system
        types: [python]

      - id: black
        name: Format code
        entry: black --check
        language: system
        types: [python]
```

---

## 附录 A：参考资源

### A.1 优秀测试范例

```bash
# 查看现有的良好测试范例
cat tests/unit/test_sim_erp.py
cat tests/unit/test_sim_factory.py
```

### A.2 相关文档

- [pytest 官方文档](https://docs.pytest.org/)
- [coverage.py 文档](https://coverage.readthedocs.io/)
- [unittest.mock 文档](https://docs.python.org/zh-cn/3/library/unittest.mock.html)

---

## 📋 实施清单

完成 EP881 单元测试体系建设后，请对照以下清单：

- [ ] `pytest.ini` 已配置
- [ ] `.coveragerc` 已配置且 fail_under=80
- [ ] `requirements-dev.txt` 包含 pytest, pytest-cov, pytest-asyncio
- [ ] `tests/conftest.py` 已创建且包含共享 fixture
- [ ] 所有测试文件已移动到 correct 目录（unit/integration/e2e）
- [ ] 测试命名遵循 test_<name> 规范
- [ ] 测试类采用 Test<Module> 命名
- [ ] 测试方法遵循 should_<condition>_<expected> 命名
- [ ] 所有测试使用 AAA 模式编写
- [ ] 覆盖率报告显示整体 ≥ 80%
- [ ] GitHub Actions 测试流水线配置完毕
- [ ] pre-commit 钩子已安装并配置
- [ ] 遗留测试已验证且通过

---

*© 2026 Sapiens AI - EP881 标准文档*
