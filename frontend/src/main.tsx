import React from 'react'
import ReactDOM from 'react-dom/client'
import axios from 'axios'
import App from './App'

// 历史页面（设备 TPM、QMS 等）直接用裸 axios，请求里没有 Authorization，
// 接口一律 401，界面显示"暂无数据"——看着像库里没数据，其实是没带登录凭证。
// 这里给默认实例补一次凭证，且只对本机 /api 前缀生效，绝不把 token 发给第三方地址。
axios.interceptors.request.use((config) => {
  const url = String(config.url || '')
  const isOwnApi = url.startsWith('/api/') || /^https?:\/\/[^/]+\/api\//.test(url)
  if (!isOwnApi) return config
  const headers = config.headers as Record<string, unknown>
  const token = localStorage.getItem('token')
  if (token && !headers.Authorization) headers.Authorization = `Bearer ${token}`
  const factoryId = localStorage.getItem('active_factory_id')
  if (factoryId && !headers['X-Factory-Id']) headers['X-Factory-Id'] = factoryId
  return config
})
import './index.css'
import './i18n' // 初始化多语言（业务文案 i18n，需在渲染前加载）

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
