import api from './api';
import { API_ENDPOINTS } from '../config/api';

// ============== Types ==============

export interface WorkOrder {
  id: string;
  work_order_code: string;
  factory_id: string;
  sales_order_id?: string;
  product_id: string;
  routing_id?: string;
  planned_qty: number;
  unit: string;
  completed_qty: number;
  good_qty: number;
  defect_qty: number;
  scrap_qty: number;
  status: string;
  status_text?: string;
  priority: string;
  priority_text?: string;
  planned_start?: string;
  planned_due?: string;
  actual_start?: string;
  actual_complete?: string;
  assigned_station_id?: string;
  current_routing_step: number;
  bom_version?: string;
  created_by?: string;
  updated_by?: string;
  remark?: string;
  created_at: string;
  updated_at?: string;
  production_reports?: ProductionReport[];
  // 进度信息（后端计算）
  progress_rate?: number;
  yield_rate?: number;
  remaining_qty?: number;
  remaining_time?: string;
  is_overdue?: boolean;
}

export interface WorkOrderStats {
  total: number;
  today_new: number;
  in_progress: number;
  overdue_risk: number;
  completed_today: number;
  pending_release: number;
  completion_rate_24h: number;
}

export interface ProductionReport {
  id: string;
  report_code: string;
  work_order_id: string;
  station_id: string;
  good_qty: number;
  defect_qty: number;
  scrap_qty: number;
  report_type: string;
  shift: string;
  operator_id?: string;
  remark?: string;
  is_modified: boolean;
  modified_at?: string;
  created_by?: string;
  created_at: string;
}

export interface Station {
  id: string;
  station_code: string;
  station_name: string;
  station_type: string;
  workshop_id?: string;
  capacity_per_hour: number;
  equipment_ids: string[];
  status: string;
  created_at?: string;
}

export interface Routing {
  id: string;
  routing_code: string;
  product_id: string;
  version: string;
  steps: RoutingStep[];
  steps_count?: number;
  is_active: boolean;
}

export interface RoutingStep {
  step_no: number;
  name: string;
  station_id?: string;
  duration_min?: number;
  description?: string;
}

export interface Equipment {
  id: string;
  equipment_code: string;
  equipment_name: string;
  equipment_type?: string;
  station_id?: string;
  status: string;
  last_maintenance_date?: string;
  next_maintenance_date?: string;
  spec: Record<string, any>;
  created_at?: string;
}

export interface Product {
  id: string;
  product_code: string;
  product_name: string;
  factory_id?: string;
  category?: string;
  unit?: string;
  status?: string;
  current_bom_version?: string;
  created_at?: string;
}

export interface Inspection {
  id: string;
  inspection_code?: string;
  inspection_type: string;
  material_id?: string;
  product_id?: string;
  work_order_id?: string;
  batch_id?: string;
  batch_size?: number;
  aql?: number;
  aql_level?: string;
  sample_size?: number;
  status?: string;
  overall_result?: string;
  good_qty?: number;
  defect_qty?: number;
  defect_rate?: number;
  inspector?: { id: string; name: string };
  completed_at?: string;
  created_at?: string;
}

export interface Defect {
  id: string;
  defect_code?: string;
  work_order_id?: string;
  defect_type: string;
  description?: string;
  severity?: string;
  quantity?: number;
  defect_qty: number;
  defect_location?: string;
  station_id?: string;
  root_cause?: string;
  discovery_time?: string;
  inspection_id?: string;
  status?: string;
  disposition?: string;
  created_at?: string;
}

export interface InventoryItem {
  id: string;
  material_id: string;
  material_code: string;
  factory_id: string;
  warehouse_id: string;
  location_id?: string;
  batch_code?: string;
  total_qty: number;
  available_qty: number;
  reserved_qty: number;
  unit_cost?: number;
  status: string;
  created_at?: string;
}

export interface Warehouse {
  id: string;
  warehouse_code: string;
  warehouse_name: string;
  factory_id: string;
  warehouse_type: string;
  address?: string;
  status: string;
  created_at?: string;
}

export interface Plan {
  id: string;
  plan_code: string;
  factory_id: string;
  product_id: string;
  planned_qty: number;
  status: string;
  priority: string;
  planned_start?: string;
  planned_due?: string;
  created_at?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ============== Work Order APIs ==============

export const getWorkOrders = (params?: Record<string, any>) =>
  api.get<any, PaginatedResponse<WorkOrder>>(API_ENDPOINTS.WORK_ORDERS, { params });

export const getWorkOrderStats = (factory_id: string) =>
  api.get<any, WorkOrderStats>(`${API_ENDPOINTS.WORK_ORDERS}/stats`, { params: { factory_id } });

export const getWorkOrder = (id: string) =>
  api.get<any, WorkOrder>(API_ENDPOINTS.WORK_ORDER(id));

export const createWorkOrder = (data: {
  factory_id: string;
  product_id: string;
  planned_qty: number;
  planned_due: string;
  priority?: string;
  station_id?: string;
  bom_version?: string;
  remark?: string;
}) => api.post(API_ENDPOINTS.WORK_ORDERS, data);

export const updateWorkOrder = (id: string, data: Record<string, any>) =>
  api.patch(API_ENDPOINTS.WORK_ORDER(id), data);

export const releaseWorkOrder = (id: string) =>
  api.post(`${API_ENDPOINTS.WORK_ORDER(id)}/release`);

export const startWorkOrder = (id: string) =>
  api.post(`${API_ENDPOINTS.WORK_ORDER(id)}/start`);

export const pauseWorkOrder = (id: string, reason?: string) =>
  api.post(`${API_ENDPOINTS.WORK_ORDER(id)}/pause`, { reason });

export const resumeWorkOrder = (id: string, reason?: string) =>
  api.post(`${API_ENDPOINTS.WORK_ORDER(id)}/resume`, { reason });

export const markPendingInbound = (id: string) =>
  api.post(`${API_ENDPOINTS.WORK_ORDER(id)}/pending-inbound`);

export const completeWorkOrder = (id: string, data?: { completed_qty?: number; good_qty?: number; defect_qty?: number }) =>
  api.post(`${API_ENDPOINTS.WORK_ORDER(id)}/complete`, data || {});

export const closeWorkOrder = (id: string) =>
  api.post(`${API_ENDPOINTS.WORK_ORDER(id)}/close`);

export const cancelWorkOrder = (id: string, reason: string) =>
  api.post(`${API_ENDPOINTS.WORK_ORDER(id)}/cancel`, null, { params: { reason } });

export const splitWorkOrder = (id: string, splitQty: number, remark?: string) =>
  api.post<any, { new_work_order?: WorkOrder; [k: string]: any }>(`${API_ENDPOINTS.WORK_ORDER(id)}/split`, { split_qty: splitQty, remark });

// ============== Production Reports ==============

export const getProductionReports = (params?: Record<string, any>) =>
  api.get<any, PaginatedResponse<ProductionReport>>(API_ENDPOINTS.PRODUCTION_REPORTS, { params });

export const getProductionReport = (id: string) =>
  api.get<any, ProductionReport>(`${API_ENDPOINTS.PRODUCTION_REPORTS}/${id}`);

export const createProductionReport = (data: {
  factory_id: string;
  work_order_id: string;
  station_id: string;
  good_qty: number;
  defect_qty?: number;
  report_type?: string;
  shift?: string;
  operator_id?: string;
  remark?: string;
}) => api.post(API_ENDPOINTS.PRODUCTION_REPORTS, data);

export const modifyProductionReport = (id: string, data: Record<string, any>) =>
  api.patch(`${API_ENDPOINTS.PRODUCTION_REPORTS}/${id}`, data);

export const addReportComment = (id: string, comment: string) =>
  api.post(`${API_ENDPOINTS.PRODUCTION_REPORTS}/${id}/comments`, { comment });

// ============== Stations ==============

export const listStations = (params?: Record<string, any>) =>
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.STATIONS, { params });

export const getStations = (params?: Record<string, any>) =>
  api.get<any, PaginatedResponse<Station>>(API_ENDPOINTS.STATIONS, { params });

export const getStation = (id: string) =>
  api.get<any, Station>(`${API_ENDPOINTS.STATIONS}/${id}`);

export const createStation = (data: Record<string, any>) =>
  api.post(API_ENDPOINTS.STATIONS, data);

export const deleteStation = (id: string) =>
  api.delete(`${API_ENDPOINTS.STATIONS}/${id}`);

// ============== Routings ==============

export const listRoutings = (params?: Record<string, any>) =>
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.ROUTINGS, { params });

export const getRoutings = (params?: Record<string, any>) =>
  api.get<any, PaginatedResponse<Routing>>(API_ENDPOINTS.ROUTINGS, { params });

export const getRouting = (id: string) =>
  api.get<any, Routing>(`${API_ENDPOINTS.ROUTINGS}/${id}`);

export const deactivateRouting = (id: string) =>
  api.patch(`${API_ENDPOINTS.ROUTINGS}/${id}`, { is_active: false });

// ============== Equipment ==============

export const listEquipment = (params?: Record<string, any>) =>
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.EQUIPMENT, { params });

export const getEquipment = (params?: Record<string, any>) =>
  api.get<any, PaginatedResponse<Equipment>>(API_ENDPOINTS.EQUIPMENT, { params });

export const createEquipment = (data: Record<string, any>) =>
  api.post(API_ENDPOINTS.EQUIPMENT, data);

export const updateEquipmentStatus = (id: string, status: string) =>
  api.patch(`${API_ENDPOINTS.EQUIPMENT}/${id}`, { status });

// ============== Products ==============

export const getProducts = (params?: Record<string, any>) =>
  api.get<any, PaginatedResponse<Product>>(API_ENDPOINTS.PRODUCTS, { params });

// ============== PP / Plans ==============

export const listPlans = (factory_id: string, params?: Record<string, any>) =>
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.PLANS, { params: { factory_id, ...params } });

export const createPlan = (data: Record<string, any>) =>
  api.post(API_ENDPOINTS.PLANS, data);

export const confirmPlan = (id: string) => api.post(API_ENDPOINTS.PLAN_CONFIRM(id), {});
export const releasePlan = (id: string) => api.post(API_ENDPOINTS.PLAN_RELEASE(id), {});
export const checkCapacityConflict = (id: string) =>
  api.get<any, { has_conflict: boolean; conflicts: any[] }>(API_ENDPOINTS.PLAN_CAPACITY_CONFLICT(id));
export const calculateMrp = (plan_id: string) =>
  api.post<any, { id: string; status: string; items: any[] }>(`${API_ENDPOINTS.MRP_CALCULATE}?plan_id=${plan_id}`, {});

// ============== QMS ==============

export const listInspections = (params?: Record<string, any>) =>
  api.get<any, any[]>(API_ENDPOINTS.INSPECTIONS, { params });

export const getInspections = (params?: Record<string, any>) =>
  api.get<any, PaginatedResponse<Inspection>>(API_ENDPOINTS.INSPECTIONS, { params });

export const createInspection = (data: Record<string, any>) =>
  api.post(API_ENDPOINTS.INSPECTIONS, data);

export const submitInspection = (id: string, data: Record<string, any>) =>
  api.post(`${API_ENDPOINTS.INSPECTIONS}/${id}/submit`, data);

export const listDefects = (params?: Record<string, any>) =>
  api.get<any, any[]>(API_ENDPOINTS.DEFECTS, { params });

export const getDefects = (params?: Record<string, any>) =>
  api.get<any, PaginatedResponse<Defect>>(API_ENDPOINTS.DEFECTS, { params });

export const createDefect = (data: Record<string, any>) =>
  api.post(API_ENDPOINTS.DEFECTS, data);

export const processDefect = (id: string, data: Record<string, any>) =>
  api.post(`${API_ENDPOINTS.DEFECTS}/${id}/process`, data);

// ============== WMS ==============

export const listWarehouses = (params?: Record<string, any>) =>
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.WAREHOUSES, { params });

export const getWarehouses = (params?: Record<string, any>) =>
  api.get<any, PaginatedResponse<Warehouse>>(API_ENDPOINTS.WAREHOUSES, { params });

export const listInventory = (params?: Record<string, any>) =>
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.INVENTORY, { params });

export const getInventory = (params?: Record<string, any>) =>
  api.get<any, PaginatedResponse<InventoryItem>>(API_ENDPOINTS.INVENTORY, { params });

// ============== HR ==============

export const listSkills = () => api.get<any, any[]>(API_ENDPOINTS.SKILLS);
export const getSkillMatrix = (params?: Record<string, any>) =>
  api.get<any, any[]>(API_ENDPOINTS.SKILL_MATRIX, { params });
export const getExpiringCerts = (params?: Record<string, any>) =>
  api.get<any, any>(API_ENDPOINTS.EXPIRING_CERTS, { params });

// ============== AI ==============

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ChatResponse {
  reply: string;
  model: string;
  degraded: boolean;
}

export const sendChat = (messages: ChatMessage[]) =>
  api.post<any, ChatResponse>(API_ENDPOINTS.CHAT, { messages });

export const getChatHealth = () =>
  api.get<any, { configured: boolean; reachable: boolean; model: string; gateway: string; detail: string }>(
    API_ENDPOINTS.CHAT_HEALTH,
  );
