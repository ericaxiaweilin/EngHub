import axios from 'axios';
import { message } from 'antd';

const recentServerErrors = new Map<string, number>();

const api = axios.create({
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor
api.interceptors.request.use(
  (config) => {
    // Add auth token if available
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    // 全局工厂切换（开发账户切换后存入 localStorage）
    const factoryId = localStorage.getItem('active_factory_id');
    if (factoryId) {
      config.headers['X-Factory-Id'] = factoryId;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status;
    // 未认证/登录过期：清除 token 并跳转登录页（保留记住密码供自动填充）
    if (status === 401) {
      localStorage.removeItem('token');
      localStorage.removeItem('refresh_token');
      localStorage.removeItem('user');
      localStorage.removeItem('login_at');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
      return Promise.reject(error);
    }
    const detail = error.response?.data?.detail;
    // FastAPI 422 返回的 detail 是对象数组，提取 msg 字段避免渲染报错
    const msg = Array.isArray(detail)
      ? detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ')
      : (detail || error.message || 'Request failed');
    if (status && status >= 500) {
      const key = `${error.config?.method || 'GET'} ${error.config?.url || ''}`;
      const now = Date.now();
      const last = recentServerErrors.get(key) || 0;
      if (now - last > 10000) {
        recentServerErrors.set(key, now);
        message.error(`服务器异常，已保留当前页面数据：${msg}`);
      }
    } else {
      message.error(msg);
    }
    return Promise.reject(error);
  }
);

export default api;
