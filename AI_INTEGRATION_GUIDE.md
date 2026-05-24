# EngHub MES AI 集成指南

## ✅ 集成完成状态

已成功将外部 AI 服务集成到 EngHub MES 系统中：

### 1. 模型服务网关 (Model Gateway)
- **地址**: `http://100.96.188.77:14041`
- **用途**: 后端调用 AI 能力 (排程优化/缺陷预测/质量分析)
- **集成方式**: 通过 `core/ai_service.py` 异步客户端

### 2. Chatbot 智能助手
- **地址**: `http://100.96.188.77:3000`
- **用途**: 前端嵌入或跳转，提供自然语言交互
- **集成方式**: 
  - 后端 API: `/api/v1/ai/chat` (代理模式)
  - 前端直接访问 (iframe 或新窗口)

---

## 📁 新增文件清单

| 文件 | 说明 |
|------|------|
| `core/config.py` | 配置管理中心 (含 AI 服务地址) |
| `core/ai_service.py` | AI 服务客户端 (调用模型网关) |
| `api/routes/ai_routes.py` | AI 服务 API 路由 (5 个端点) |
| `.env.production` | 生产环境配置 (含外部服务地址) |

---

## 🔌 API 端点

新增 5 个 AI 相关端点：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/v1/ai/health` | GET | 检查 AI 网关健康状态 |
| `/api/v1/ai/optimize/schedule` | POST | 生产排程优化 |
| `/api/v1/ai/predict/defects` | POST | 不良品率预测 |
| `/api/v1/ai/analyze/quality` | POST | 质量趋势分析 |
| `/api/v1/ai/chat` | POST | 智能助手对话 |

**总路由数**: 89 个 (原 84 个 + 新增 5 个)

---

## 🔧 配置说明

### 环境变量 (.env.production)

```bash
# AI 服务配置
MODEL_GATEWAY_URL=http://100.96.188.77:14041
CHATBOT_URL=http://100.96.188.77:3000
```

### 调用示例

#### 1. 生产排程优化
```bash
curl -X POST http://localhost:8000/api/v1/ai/optimize/schedule \
  -H "Content-Type: application/json" \
  -d '{
    "work_orders": [{"id": "WO-001", "quantity": 100}],
    "constraints": {"capacity": 500, "materials": ["M1", "M2"]}
  }'
```

#### 2. 不良品预测
```bash
curl -X POST http://localhost:8000/api/v1/ai/predict/defects \
  -H "Content-Type: application/json" \
  -d '{
    "process_params": {"temperature": 250, "pressure": 5.2, "speed": 100}
  }'
```

#### 3. 智能对话
```bash
curl -X POST http://localhost:8000/api/v1/ai/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "今天有哪些待完成的工单？",
    "context": {"user_role": "operator"}
  }'
```

---

## 🎨 前端集成建议

### 方案 A: iframe 嵌入 Chatbot
```html
<!-- 在 React 组件中 -->
<iframe 
  src="http://100.96.188.77:3000" 
  style={{ width: '400px', height: '600px', border: 'none' }}
  title="AI Assistant"
/>
```

### 方案 B: 悬浮球 + API 调用
```typescript
// 使用 /api/v1/ai/chat 端点
const response = await fetch('/api/v1/ai/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ message: userInput })
});
```

---

## ⚠️ 注意事项

1. **网络连通性**: 确保后端服务器能访问 `100.96.188.77` 的 14041 和 3000 端口
2. **超时设置**: AI 服务调用超时设为 30 秒，长任务需异步处理
3. **降级策略**: 当 AI 网关不可用时，系统会返回友好提示而非报错
4. **安全认证**: 生产环境建议在网关层添加 API Key 认证

---

## 🚀 下一步

1. **测试连通性**: 启动服务后访问 `/api/v1/ai/health` 验证
2. **前端开发**: 在 Dashboard 添加 AI 助手入口
3. **场景对接**: 根据实际业务需求调整 prompt 和参数格式

**系统集成已完成！现在 EngHub MES 具备完整的 AI 原生能力。** 🎉
