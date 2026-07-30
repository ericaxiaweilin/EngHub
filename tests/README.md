# 🧪 单元测试目录结构

```
tests/
├── unit/                 ← 单元测试（本目录）
│   ├── conftest.py       ← pytest fixture 配置
│   ├── mes/              ← MES模块测试
│   │   └── test_workorder_lifecycle.py ← 工单生命周期（P0优先级）
│   ├── bom/              ← BOM模块测试
│   │   └── test_bom_service.py
│   ├── pp/               ← PP计划模块测试
│   │   └── test_plan_service.py
│   └── wms/              ← WMS模块测试（待扩展）
├── integration/          ← API集成测试（待创建）
├── fixtures/             ← 测试数据fixture（待创建）
├── run_quick_start.py    ← 快速运行脚本
└── README.md             ← 本文件
```

## 🚀 快速开始

### 1. 安装依赖

```bash
cd /Users/thanhhuyennguyen/Desktop/EngHub
pip install pytest pytest-asyncio pytest-mock pytest-cov
```

### 2. 运行测试

**方式一：直接运行pytest**
```bash
pytest tests/unit -v --cov=api --cov-report=html
```

**方式二：使用快捷脚本**
```bash
python tests/run_quick_start.py
```

### 3. 查看覆盖率报告

测试完成后，打开浏览器查看：
```
open htmlcov/index.html
```

## 📋 测试覆盖规划

| 模块 | 优先级 | 状态 | 文件 |
|------|--------|------|------|
| MES工单流转 | 🔴 P0 | ✅ 已完成 | `test_workorder_lifecycle.py` |
| BOM服务 | 🟠 P1 | ✅ 已完成 | `test_bom_service.py` |
| PP计划操作 | 🟠 P1 | ✅ 已完成 | `test_plan_service.py` |
| **APS排程** | 🔴 P0 | ✅ **已完成** | `test_aps_engine.py`, `test_aps_service.py` |
| **QMS缺陷处置** | 🟠 P1 | ✅ **已完成** | `test_defect_disposition.py` |
| QMS质检DELETE端点 | 🟠 P1 | ✅ **已完成** | `test_qms_delete_endpoints.py` (integration) |
| WMS仓储 | 🟡 P2 | ⏳ 待建 | — |
| API端点集成 | 🟢 P3 | 🟡 进行中 | `integration/` |

## 🛠️ 编写新测试指南

1. **创建文件**: `tests/unit/<module>/test_<feature>.py`
2. **添加fixture**: 在conftest.py中共享常用的mock对象
3. **使用@pytest.mark.asyncio**: 所有测试函数标记为async
4. **遵循AAA模式**: Arrange（准备）→ Act（执行）→ Assert（断言）
5. **保持孤立**: 每个测试只验证一个行为，使用mock隔离依赖

## 💡 最佳实践

- **测试粒度**: 小的、独立的测试函数（每个≤20行）
- **命名清晰**: 测试名描述`_方法_条件_预期结果`，如 `test_workorder_release_non_draft_fail`
- **边界覆盖**: 正常值 + 空值 + 非法值 + 异常路径
- **Mock真实依赖**: 数据库、外部API、耗时服务都用mock替代
- **覆盖率目标**: 核心业务模块 ≥70%，边缘模块 ≥50%

---

*此测试体系为生产质量保驾护航，建议每次PR合并前必跑全套测试！*