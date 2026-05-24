import axios from 'axios'

const API_BASE_URL = '/api'

// 创建 axios 实例
const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器 - 添加认证 token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器 - 处理错误
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token 过期，跳转到登录页
      localStorage.removeItem('access_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default apiClient

// MES 工单服务
export const workOrderService = {
  getList: (params?: any) => apiClient.get('/mes/work-orders', { params }),
  getById: (id: number) => apiClient.get(`/mes/work-orders/${id}`),
  create: (data: any) => apiClient.post('/mes/work-orders', data),
  update: (id: number, data: any) => apiClient.put(`/mes/work-orders/${id}`, data),
  delete: (id: number) => apiClient.delete(`/mes/work-orders/${id}`),
  issue: (id: number) => apiClient.post(`/mes/work-orders/${id}/issue`),
  complete: (id: number) => apiClient.post(`/mes/work-orders/${id}/complete`),
}

// 生产报工服务
export const productionReportService = {
  getList: (params?: any) => apiClient.get('/mes/production-reports', { params }),
  create: (data: any) => apiClient.post('/mes/production-reports', data),
}

// PP 生产计划服务
export const planService = {
  getList: (params?: any) => apiClient.get('/pp/plans', { params }),
  getById: (id: number) => apiClient.get(`/pp/plans/${id}`),
  create: (data: any) => apiClient.post('/pp/plans', data),
  update: (id: number, data: any) => apiClient.put(`/pp/plans/${id}`, data),
  runMPS: (data: any) => apiClient.post('/pp/plans/run-mps', data),
  runMRP: (planId: number) => apiClient.post(`/pp/plans/${planId}/run-mrp`),
}

// QMS 检验服务
export const inspectionService = {
  getList: (params?: any) => apiClient.get('/qms/inspections', { params }),
  getById: (id: number) => apiClient.get(`/qms/inspections/${id}`),
  create: (data: any) => apiClient.post('/qms/inspections', data),
  execute: (id: number, data: any) => apiClient.post(`/qms/inspections/${id}/execute`, data),
}

// WMS 仓库服务
export const warehouseService = {
  getList: (params?: any) => apiClient.get('/wms/warehouses', { params }),
  getById: (id: number) => apiClient.get(`/wms/warehouses/${id}`),
  getInventory: (warehouseId: number) => apiClient.get(`/wms/warehouses/${warehouseId}/inventory`),
}
