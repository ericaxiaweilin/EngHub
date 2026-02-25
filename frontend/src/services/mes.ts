import api from './api';
import { API_ENDPOINTS } from '../config/api';

// Types
export interface WorkOrder {
  id: string;
  work_order_code: string;
  product_id: string;
  planned_qty: number;
  completed_qty: number;
  status: string;
  priority: string;
  created_at: string;
}

export interface ProductionReport {
  id: string;
  work_order_id: string;
  station_id: string;
  good_qty: number;
  defect_qty: number;
  report_type: string;
  created_at: string;
}

export interface Inspection {
  id: string;
  inspection_type: string;
  product_id: string;
  batch_size: number;
  inspected_qty: number;
  result: string;
  created_at: string;
}

// Work Orders
export const getWorkOrders = (params?: Record<string, any>) => 
  api.get<any, { items: WorkOrder[]; total: number }>(API_ENDPOINTS.WORK_ORDERS, { params });

export const getWorkOrder = (id: string) => 
  api.get<any, WorkOrder>(API_ENDPOINTS.WORK_ORDER(id));

export const createWorkOrder = (data: Partial<WorkOrder>) => 
  api.post(API_ENDPOINTS.WORK_ORDERS, data);

export const updateWorkOrder = (id: string, data: Partial<WorkOrder>) => 
  api.put(API_ENDPOINTS.WORK_ORDER(id), data);

export const splitWorkOrder = (id: string, splitQty: number) => 
  api.post(`${API_ENDPOINTS.WORK_ORDER(id)}/split`, { split_qty: splitQty });

// Production Reports
export const getProductionReports = (params?: Record<string, any>) => 
  api.get<any, { items: ProductionReport[]; total: number }>(API_ENDPOINTS.PRODUCTION_REPORTS, { params });

export const createProductionReport = (data: Partial<ProductionReport>) => 
  api.post(API_ENDPOINTS.PRODUCTION_REPORTS, data);

// Inspections
export const getInspections = (params?: Record<string, any>) => 
  api.get<any, { items: Inspection[]; total: number }>(API_ENDPOINTS.INSPECTIONS, { params });

export const createInspection = (data: Partial<Inspection>) => 
  api.post(API_ENDPOINTS.INSPECTIONS, data);

// Defects
export const getDefects = (params?: Record<string, any>) => 
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.DEFECTS, { params });

// Inventory
export const getInventory = (params?: Record<string, any>) => 
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.INVENTORY, { params });

// Plans
export const getPlans = (params?: Record<string, any>) => 
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.PLANS, { params });

export const createPlan = (data: any) => 
  api.post(API_ENDPOINTS.PLANS, data);
