# EngHub MES 前端开发说明

## ⚠️ 重要提示

由于当前运行环境磁盘空间有限 (504MB)，**不建议在容器内直接安装依赖和构建**。

推荐使用 **Docker 多阶段构建**方式，让 Docker 在构建过程中临时使用空间，构建完成后只保留最终的静态文件。

## 🚀 推荐部署方式

### 方式一：使用 Docker Compose (推荐)

```bash
cd /workspace
docker-compose up -d --build
```

此方式会自动：
1. 在临时容器中安装 npm 依赖
2. 构建 React 生产版本
3. 将构建产物复制到 Nginx 容器
4. 丢弃临时的 node_modules，不占用主机空间

### 方式二：本地开发 (需要额外空间)

如果需要在本地开发调试，请确保有至少 500MB 可用空间：

```bash
cd /workspace/frontend

# 安装依赖
npm install --legacy-peer-deps

# 启动开发服务器
npm run dev
```

访问 http://localhost:5173

## 📁 项目结构

```
frontend/
├── src/
│   ├── main.tsx          # 应用入口
│   ├── App.tsx           # 路由配置
│   ├── components/       # 通用组件
│   │   └── Layout.tsx    # 主布局 (侧边栏 + 顶栏)
│   ├── pages/            # 页面组件
│   │   ├── Login.tsx     # 登录页
│   │   ├── Dashboard.tsx # 工作台
│   │   ├── mes/          # MES 模块页面
│   │   ├── pp/           # PP 模块页面
│   │   ├── qms/          # QMS 模块页面
│   │   └── wms/          # WMS 模块页面
│   ├── services/         # API 服务层
│   │   └── api.ts        # Axios 配置 + 模块服务
│   ├── stores/           # 状态管理 (Zustand)
│   │   └── authStore.ts  # 认证状态
│   ├── types/            # TypeScript 类型定义
│   └── utils/            # 工具函数
├── package.json          # 依赖配置
├── tsconfig.json         # TypeScript 配置
├── vite.config.ts        # Vite 构建配置
├── Dockerfile            # 多阶段构建配置
└── nginx.conf            # Nginx 配置
```

## 🔧 技术栈

- **React 18** - UI 框架
- **TypeScript** - 类型安全
- **Vite** - 构建工具
- **Ant Design 5** - UI 组件库
- **React Router 6** - 路由管理
- **Zustand** - 状态管理
- **Axios** - HTTP 客户端
- **ECharts** - 数据可视化

## 📊 已实现页面

| 页面 | 路径 | 功能 |
|------|------|------|
| 登录 | `/login` | JWT 认证、记住密码 |
| 工作台 | `/` | 关键指标、待办事项、快捷入口 |
| 工单管理 | `/mes/work-orders` | 工单列表、创建、编辑、状态流转 |
| 生产报工 | `/mes/report` | 良品/不良品录入、记录查询 |
| 计划看板 | `/pp/plans` | MPS/MRP 可视化、产能分析 |
| 质量检验 | `/qms/inspections` | IQC/IPQC/FQC/OQC 录入与查询 |
| 仓库管理 | `/wms/warehouses` | 库存查询、容量监控 |

## 🔐 API 集成

所有 API 请求通过 `src/services/api.ts` 统一管理：

- **基础 URL**: `/api/` (开发环境代理到后端 8000 端口)
- **JWT Token**: 自动从 localStorage 读取并添加到请求头
- **错误处理**: 统一拦截 401/403/500 错误

### 示例调用

```typescript
import { workOrderApi } from '@/services/api';

// 获取工单列表
const orders = await workOrderApi.getList({ status: 'pending' });

// 创建工单
const newOrder = await workOrderApi.create({
  product_code: 'PROD-001',
  quantity: 100,
  due_date: '2024-12-31'
});
```

## 🎨 UI 设计规范

- **主色调**: 蓝色 (#1890ff - Ant Design 默认)
- **字体**: 系统默认字体栈
- **响应式**: 支持桌面端和平板端
- **主题**: 支持亮色/暗色模式 (待实现)

## 📝 下一步开发建议

1. **完善表单验证** - 使用 Zod 或 Yup 进行前端验证
2. **添加图表** - 在 Dashboard 和计划看板中集成 ECharts
3. **移动端适配** - 优化 PDA/手持设备体验
4. **WebSocket 实时通知** - 工单状态变更、质量报警
5. **国际化** - i18n 多语言支持

---

**EngHub MES Frontend 1.0.0**
