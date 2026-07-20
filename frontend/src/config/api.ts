// API Configuration
// Use relative paths when behind nginx proxy, absolute when direct
const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export const API_ENDPOINTS = {
  // Auth
  AUTH_LOGIN: `${API_BASE_URL}/api/v1/auth/login`,
  AUTH_ME: `${API_BASE_URL}/api/v1/auth/me`,
  AUTH_REFRESH: `${API_BASE_URL}/api/v1/auth/refresh`,

  // MES
  WORK_ORDERS: `${API_BASE_URL}/api/v1/work-orders`,
  WORK_ORDER: (id: string) => `${API_BASE_URL}/api/v1/work-orders/${id}`,
  PRODUCTION_REPORTS: `${API_BASE_URL}/api/v1/production-reports`,
  ROUTINGS: `${API_BASE_URL}/api/v1/routings`,
  STATIONS: `${API_BASE_URL}/api/v1/stations`,
  EQUIPMENT: `${API_BASE_URL}/api/v1/equipment`,
  
  // PP
  PLANS: `${API_BASE_URL}/api/v1/plans`,
  PLAN: (id: string) => `${API_BASE_URL}/api/v1/plans/${id}`,
  PLAN_CONFIRM: (id: string) => `${API_BASE_URL}/api/v1/plans/${id}/confirm`,
  PLAN_RELEASE: (id: string) => `${API_BASE_URL}/api/v1/plans/${id}/release`,
  PLAN_CAPACITY_CONFLICT: (id: string) => `${API_BASE_URL}/api/v1/plans/${id}/capacity-conflict`,
  MRP: `${API_BASE_URL}/api/v1/mrp`,
  MRP_CALCULATE: `${API_BASE_URL}/api/v1/mrp/calculate`,
  CAPACITY_ANALYSIS: `${API_BASE_URL}/api/v1/capacity/analysis`,
  INVENTORY_ALERTS: `${API_BASE_URL}/api/v1/inventory/alerts`,
  
  // QMS
  INSPECTIONS: `${API_BASE_URL}/api/v1/inspections`,
  DEFECTS: `${API_BASE_URL}/api/v1/defects`,
  
  // WMS
  WAREHOUSES: `${API_BASE_URL}/api/v1/warehouses`,
  INVENTORY: `${API_BASE_URL}/api/v1/inventory`,
  INVENTORY_TRANSACTIONS: `${API_BASE_URL}/api/v1/inventory/transactions`,

  // Sim-ERP
  SIM_ERP_STATUS: `${API_BASE_URL}/api/v1/sim-erp/status`,
  SIM_ERP_PLUGINS: `${API_BASE_URL}/api/v1/sim-erp/plugins`,
  SIM_ERP_SIMULATE: `${API_BASE_URL}/api/v1/sim-erp/simulate`,
  SIM_ERP_SCENARIO_HHO: `${API_BASE_URL}/api/v1/sim-erp/scenarios/high-heat-overtime`,
  SIM_ERP_AUDITS: `${API_BASE_URL}/api/v1/sim-erp/audits`,
  SIM_ERP_AUDIT_LATEST: `${API_BASE_URL}/api/v1/sim-erp/audits/latest`,
  SIM_ERP_AUDIT: (simulationId: string) => `${API_BASE_URL}/api/v1/sim-erp/audits/${simulationId}`,

  // Employee Skills (HR)
  SKILLS: `${API_BASE_URL}/api/v1/skills`,
  SKILL_MATRIX: `${API_BASE_URL}/api/v1/skill-matrix`,
  QUALIFIED_EMPLOYEES: `${API_BASE_URL}/api/v1/qualified-employees`,
  EXPIRING_CERTS: `${API_BASE_URL}/api/v1/expiring-certifications`,
  TRAINING_RECORDS: `${API_BASE_URL}/api/v1/training-records`,
  EMPLOYEE_SKILLS: (userId: string) => `${API_BASE_URL}/api/v1/employees/${userId}/skills`,

  // AI Assistant
  CHAT: `${API_BASE_URL}/api/v1/chat`,
  CHAT_HEALTH: `${API_BASE_URL}/api/v1/chat/health`,
};

export default API_BASE_URL;
