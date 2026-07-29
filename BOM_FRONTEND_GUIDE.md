# BOM 前端开发指引

## 模块状态

- **后端**: ✅ 已实现完整 API (`api/routes/bom_routes.py`, 8个端点)
- **前端**: ❌ 缺失 (`frontend/src/pages/bom/` 不存在)

## 后端 API 清单

| HTTP | 路径 | 描述 |
|------|------|------|
| GET | `/api/v1/bom/models` | 获取所有已同步的产品型号列表 |
| GET | `/api/v1/bom/tree/{model_name}` | BOM 树形展开 |
| GET | `/api/v1/bom/search` | 物料搜索（支持关键词、型号、分类过滤） |
| GET | `/api/v1/bom/material/{part_number}` | 物料详情 |
| POST | `/api/v1/bom/sync` | 触发 BOM 同步 (full/incremental) |
| GET | `/api/v1/bom/sync/status` | 获取同步状态 |
| GET | `/api/v1/bom/compare` | BOM 版本对比 (两个时间点) |
| GET | `/api/v1/bom/work-order/{work_order_id}` | 工单关联 BOM |

## 开发建议步骤

### 1. 创建目录结构

```bash
mkdir -p frontend/src/pages/bom
```

### 2. 创建基础页面组件

参考现有页面模式（如 `frontend/src/pages/mes/PlantFloor.tsx`），创建以下文件：

- `BOMManager.tsx` - 主页面（含产品选择、BOM树展示、同步控制）
- `BOMTree.tsx` - 树形展开组件
- `BOMCompare.tsx` - 版本对比页面
- `MaterialSearch.tsx` - 物料搜索组件

### 3. 示例：BOM列表页面最小实现

```tsx
// frontend/src/pages/bom/BOMManager.tsx
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';

const API_BASE = '/api/v1/bom';

export function BOMManager() {
  const { data: models, isLoading } = useQuery(['bomModels'], 
    async () => (await axios.get(`${API_BASE}/models`)).data
  );

  if (isLoading) return <div>Loading...</div>;

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-4">BOM 管理</h1>
      <select className="border p-2 rounded">
        {models?.map(model => (
          <option key={model.name}>{model.name}</option>
        ))}
      </select>
    </div>
  );
}
```

### 4. 注册路由和菜单

编辑 `frontend/src/App.tsx` 添加 BOM 路由：
```tsx
<Route path="/bom" element={<BOMManager />} />
```

在菜单配置中添加 BOM 入口（参考 `ie` 或 `mes` 模块）。

### 5. 样式参照

使用 Ant Design + Tailwind CSS，参考：
- `frontend/src/pages/mes/ReportTerminal.tsx`
- `frontend/src/pages/pp/PlanList.tsx`

## 所需工作量估算

| 页面 | 估算工时 |
|------|---------|
| BOM 主页面（列表+树形） | 4-6 小时 |
| BOM 版本对比 | 2-4 小时 |
| 物料搜索页 | 2-3 小时 |
| 路由和菜单集成 | 1-2 小时 |
| **总计** | **9-15 小时** |

## 紧急程度

🔴 **P0 - 阻塞**：后端已实现但无法使用，用户无法访问BOM核心功能。建议优先安排开发。
