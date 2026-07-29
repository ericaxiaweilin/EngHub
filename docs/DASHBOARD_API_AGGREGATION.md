# Dashboard 聚合 API 设计文档

## 1. 背景与问题

生产看板前端在加载时需要同时调用多个独立 API 端点获取不同维度的数据：

| 端点 | 用途 | 返回数据量 |
|------|------|-----------|
| `/summary` | 完整生产汇总（KPI、分区、订单、流转等） | 大 |
| `/live-summary` | 当日实时精简指标（大屏顶部卡片） | 小 |
| `/stations-grid` | 工位运行状态矩阵（热力图） | 中 |
| `/top-issues` | 未解决异常列表（告警面板） | 小 |
| `/hourly-trend` | 小时产出趋势（折线图） | 小 |

**存在的问题：**
- **多次 HTTP 请求**：页面加载时发起 4-5 次并发请求，增加网络 RTT 累积延迟
- **重复查询**：每个端点都可能单独执行相同的数据库批量拉取操作
- **前端耦合复杂**：前端需处理 `Promise.all()` 的失败、超时、状态合并逻辑
- **移动端弱网敏感**：在 3G/弱 WiFi 环境下首屏加载时间显著延长

---

## 2. 解决方案：`/aggregate` 聚合端点

新增单一入口 `/api/v1/production-dashboard/aggregate`，一次性聚合所有看板数据。

### 2.1 接口定义

```http
GET /api/v1/production-dashboard/aggregate?factory_id=F01&horizon_days=7
```

### 2.2 查询参数

| 参数 | 类型 | 默认值 | 描述 |
|------|------|--------|------|
| factory_id | string | "F01" | 厂区 ID |
| horizon_days | int | 14 | 详细视图的时间窗口 (7-30) |
| include_live | bool | true | 是否包含实时精简视图 |
| include_grid | bool | true | 是否包含工位状态矩阵 |
| include_trend | bool | false | 是否包含小时趋势（按需加载） |
| include_issues | bool | true | 是否包含异常列表 |

### 2.3 响应结构

```json
{
  "full_summary": { /* 完整数据，同 /summary */ },
  "live_dashboard": { /* 实时数据，同 /live-summary */ },
  "stations_grid": { /* 工位矩阵，同 /stations-grid */ },
  "top_issues": { /* 异常列表，同 /top-issues */ },
  "hourly_trend": { /* 小时趋势，同 /hourly-trend（可选）*/ },
  "timestamp": "2026-07-29T08:13:00Z",
  "aggregated_fields": ["full_summary", "live_dashboard", "stations_grid", "top_issues"]
}
```

任一子端点出错时返回对应 `_error` 字段，不影响整体返回。

---

## 3. 实现原理

### 3.1 架构图

```
前端
  ↓ (1 次 HTTP)
聚合端点 /aggregate
  ├─→ 调用 summary()    [DB: WorkOrder+Report+Station...]
  ├─→ 调用 live_summary() [DB: 今日聚合查询]
  ├─→ 调用 stations_grid() [DB: 设备+报工时间戳]
  └─→ 调用 top_issues()   [DB: ProductionAlert]
      ↓ (统一 JSON 返回)
  ↑ (1 次 HTTP)
前端
```

对比原方案：

```
前端
  ↓ (4 次并行 HTTP)
├─→ /summary
├─→ /live-summary
├─→ /stations-grid
└─→ /top_issues
  ↑ (各分别 DB 查询)
```

### 3.2 关键优化点

1. **连接复用**：聚合端点在同一个 DB session 内批量拉取数据，避免重复 `SELECT`
2. **事务隔离**：所有子查询在同一事务上下文中读取一致时间点的数据
3. **错误隔离**：单个子查询失败不阻塞整体返回（带 `_error` 标记）
4. **可扩展性**：新增数据维度只需添加 `include_xxx` 参数和对应函数

---

## 4. 性能收益预估

| 指标 | 原方案 | 新聚合方案 | 提升 |
|------|--------|-----------|------|
| HTTP 请求数 | 4-5 | 1 | **75% 减少** |
| 网络 RTT 总耗时 | ~300-600ms (×N) | ~80-150ms (单次) | **60-75% 降低** |
| DB 查询重复度 | 高（summary 已包含部分 live 数据） | 低（批次化） | **30% 减少** |
| 前端代码复杂度 | Promise.all + 错误处理 | 单对象直接解构 | **简化 50%** |
| 首屏加载时间 | 慢（等待最后一个请求） | 快（一次性响应） | **提升 40%+** |

---

## 5. 向后兼容性

**原有端点保持不变**，完全兼容现有客户端调用：

- `/summary` → 继续可用
- `/live-summary` → 继续可用  
- `/stations-grid` → 继续可用
- `/top-issues` → 继续可用

新端点 `/aggregate` 为**仅新增**，无破坏性变更。

---

## 6. 使用示例

### 6.1 JavaScript/Fetch 用法

```javascript
// 推荐：使用聚合端点（单一请求）
async function loadDashboard(factoryId = 'F01') {
  const res = await fetch(
    `/api/v1/production-dashboard/aggregate?factory_id=${factoryId}&include_live=true&include_grid=true`
  );
  const data = await res.json();

  // 直接使用聚合后的数据
  const kpis = data.full_summary.kpis;
  const sections = data.full_summary.sections;
  const activeOrders = data.realtime.active_work_orders;
  const alerts = data.top_issues.items;

  return { kpis, sections, alerts };
}

// 或按需只加载部分数据（节省带宽）
async loadLightDashboard() {
  const res = await fetch(
    '/api/v1/production-dashboard/aggregate?include_live=true&include_grid=false&include_issues=false'
  );
  // 只返回 live_dashboard 和 full_summary
}
```

### 6.2 React Hook 封装

```typescript
import { useState, useEffect } from 'react';

useDashboardFactory({ factoryId = 'F01' }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`/api/v1/production-dashboard/aggregate?factory_id=${factoryId}&include_live=true`)
      .then(r => r.json())
      .then(setData)
      .finally(() => setLoading(false));
  }, [factoryId]);

  return { ...data, loading };
}
```

---

## 7. 测试验证

执行测试脚本验证端点功能：

```bash
python test_dashboard_aggregate.py
```

预期输出：

```
============================================================
生产看板聚合 API - 测试执行时间: 2026-07-29T08:13:00
============================================================

[1] 测试 /summary (原有端点)...
   ✓ summary 正常返回...

[2] 测试 /live-summary (精简实时端点)...
   ✓ live-summary 正常返回...

[3] 测试 /stations-grid (工位矩阵端点)...
   ✓ stations-grid 正常返回...

[4] 测试 /top-issues (异常列表端点)...
   ✓ top-issues 正常返回...

[5] 测试 /aggregate (聚合端点 - 核心特性)...
   ✓ aggregate 正常返回!
   - 聚合字段: ['full_summary', 'live_dashboard', 'stations_grid', 'top_issues']
   - ✅ 聚合端点全部验证通过!

============================================================
测试完成!
============================================================
```

---

## 8. 未来扩展建议

1. **缓存层**：对 `/aggregate` 结果设置 30s-1min 的 Redis 缓存（仪表盘适合近实时的读多写少场景）
2. **增量更新**：WebSocket 推送关键指标变化（如告警、工位状态），聚合端点仅提供初始快照
3. **客户端分片**：前端可传入 `fields=` 参数精确指定所需字段，进一步减少传输体积
4. **多厂区聚合**：支持 `factory_ids=F01,F02` 跨厂区汇总视图

---

*文档生成日期：2026-07-29 | EngHub MES v2.5.0*