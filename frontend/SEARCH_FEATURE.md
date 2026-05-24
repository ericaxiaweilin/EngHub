# 🔍 MES 企业级搜索功能

## 概述
类似 Atlassian Rovo 的成熟站内数据搜索引擎，支持全局搜索所有业务数据。

## 核心特性

### 1. 全局快捷键
- **Ctrl+K** (Windows/Linux) 或 **Cmd+K** (Mac) 唤起搜索
- **ESC** 关闭搜索
- 任意页面可用

### 2. 搜索范围
支持 9 种数据类型：
- 📋 工单 (work_order)
- 🏭 工位 (station)
- ⚙️ 设备 (device)
- 📦 物料 (material)
- 📊 质量报告 (quality_report)
- 📖 SOP (sop)
- 🔧 维护计划 (maintenance)
- 📈 库存 (inventory)
- 👤 用户 (user)

### 3. 智能过滤
- 按数据类型筛选
- 按状态/优先级/负责人等元数据过滤
- 实时搜索结果

### 4. 深度链接
- 点击结果直接跳转到对应详情页
- 面包屑导航显示位置
- 保留搜索上下文

### 5. 富媒体展示
- 类型标签和图标
- 关键元数据展示 (状态、优先级、负责人)
- 高亮匹配关键词

## 技术架构

### 前端 (TypeScript + React)
```
frontend/src/
├── components/Search/
│   ├── SearchModal.tsx      # 搜索模态框
│   ├── SearchButton.tsx     # 搜索按钮
│   ├── SearchProvider.tsx   # 全局搜索提供者
│   └── index.ts             # 导出
├── hooks/
│   └── useSearch.ts         # 搜索 Hook
└── types/
    └── search.ts            # TypeScript 类型定义
```

### 后端 (Python FastAPI)
```
core/search_engine/
├── engine.py                # 搜索核心引擎
├── data_loader.py           # 数据加载器
├── config.py                # 配置管理
└── __init__.py              # 模块导出

api/v1/endpoints/search/
└── search.py                # REST API 端点
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/search/search` | GET/POST | 搜索 |
| `/api/v1/search/stats` | GET | 统计信息 |
| `/api/v1/search/suggest` | GET | 查询建议 |
| `/api/v1/search/index` | POST | 索引数据 |
| `/api/v1/search/health` | GET | 健康检查 |

## 使用示例

### 前端使用
```tsx
import { SearchButton, useSearch } from '@/components/Search';

// 按钮触发
<SearchButton onClick={() => setIsSearchOpen(true)} />

// Hook 使用
const { results, loading, search } = useSearch();
await search({ q: 'iPhone', types: ['work_order'], limit: 10 });
```

### API 调用
```bash
# 简单搜索
curl "http://localhost:8000/api/v1/search/search?q=iPhone"

# 高级搜索
curl -X POST http://localhost:8000/api/v1/search/search \
  -H "Content-Type: application/json" \
  -d '{
    "q": "良率低",
    "types": ["work_order", "quality_report"],
    "filters": {"status": "active"},
    "limit": 10
  }'
```

## 下一步

1. **权限集成**: 根据用户 RBAC 权限过滤搜索结果
2. **搜索历史**: 记录最近搜索和热门搜索
3. **个性化推荐**: 基于用户角色和行为推荐相关内容
4. **实时同步**: WebSocket 推送数据变更更新索引
5. **分析仪表板**: 搜索热度、零结果查询分析

## 启动测试

```bash
# 后端
cd /workspace
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 前端
cd /workspace/frontend
npm run dev

# 访问 http://localhost:5173 按 Ctrl+K 测试搜索
```
