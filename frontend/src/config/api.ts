// API Configuration
// Use relative paths when behind nginx proxy, absolute when direct
const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export const API_ENDPOINTS = {
  // MES
  WORK_ORDERS: `${API_BASE_URL}/api/v1/work-orders`,
  WORK_ORDER: (id: string) => `${API_BASE_URL}/api/v1/work-orders/${id}`,
  PRODUCTION_REPORTS: `${API_BASE_URL}/api/v1/production-reports`,
  ROUTINGS: `${API_BASE_URL}/api/v1/routings`,
  STATIONS: `${API_BASE_URL}/api/v1/stations`,
  EQUIPMENT: `${API_BASE_URL}/api/v1/equipment`,
  
  // PP
  PLANS: `${API_BASE_URL}/api/v1/plans`,
  MRP: `${API_BASE_URL}/api/v1/mrp`,
  
  // QMS
  INSPECTIONS: `${API_BASE_URL}/api/v1/inspections`,
  DEFECTS: `${API_BASE_URL}/api/v1/defects`,
  
  // WMS
  WAREHOUSES: `${API_BASE_URL}/api/v1/warehouses`,
  INVENTORY: `${API_BASE_URL}/api/v1/inventory`,
  INVENTORY_TRANSACTIONS: `${API_BASE_URL}/api/v1/inventory/transactions`,
};

export default API_BASE_URL;
