import axios from 'axios';
import { message } from 'antd';

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
    message.error(msg);
    return Promise.reject(error);
  }
);

export default api;
