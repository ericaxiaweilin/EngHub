# EngHub MES 前端初始化脚本

echo "🚀 开始创建 EngHub MES 前端项目..."

# 使用 Vite 创建 React + TypeScript 项目
npm create vite@latest frontend -- --template react-ts

cd frontend

# 安装核心依赖
npm install
npm install axios react-router-dom @tanstack/react-query zustand
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p

# 安装 UI 组件库 (Ant Design)
npm install antd @ant-design/icons
npm install echarts react-echarts

# 安装开发工具
npm install -D @types/node @vitejs/plugin-react

echo "✅ 前端项目骨架创建完成！"
echo "📂 项目结构:"
echo "   frontend/"
echo "   ├── src/"
echo "   │   ├── components/  # 通用组件"
echo "   │   ├── pages/       # 页面组件"
echo "   │   ├── services/    # API 服务"
echo "   │   ├── stores/      # 状态管理"
echo "   │   ├── types/       # TypeScript 类型"
echo "   │   └── utils/       # 工具函数"
echo "   ├── public/"
echo "   └── package.json"
echo ""
echo "🎯 下一步:"
echo "   1. cd frontend && npm run dev"
echo "   2. 访问 http://localhost:5173"
