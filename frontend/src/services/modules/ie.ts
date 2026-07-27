import api from '../api';
import { API_ENDPOINTS } from '../../config/api';

// ==================== Standard Time Management ====================

export interface StandardTimeCreate {
  factory_id: string;
  product_id: string;
  routing_step: string;
  operation_name: string;
  station_id?: string;
  standard_time_min: number;
  setup_time_min: number;
  batch_size: number;
  rating_factor: number;
  allowance_rate: number;
  validity_start: string;
  validity_end?: string;
}

export interface StandardTimeResponse {
  id: string;
  factory_id: string;
  product_id: string;
  routing_step: string;
  operation_name: string;
  station_id?: string;
  standard_time_min: number;
  effective_standard_time: number;
  version: string;
  is_active: boolean;
  validity_start: string;
  created_at: string;
}

export const listStandardTimes = (factory_id: string, params?: Record<string, any>) =>
  api.get<any, { items: StandardTimeResponse[]; total: number }>(
    API_ENDPOINTS.IE_STANDARD_TIMES,
    { params: { factory_id, ...params } },
  );

export const getStandardTime = (id: string) =>
  api.get<StandardTimeResponse>(API_ENDPOINTS.IE_STANDARD_TIME(id));

export const createStandardTime = (data: StandardTimeCreate) =>
  api.post(API_ENDPOINTS.IE_STANDARD_TIMES, data);

export const updateStandardTime = (id: string, data: StandardTimeCreate) =>
  api.put(API_ENDPOINTS.IE_STANDARD_TIME(id), data);

export const deleteStandardTime = (id: string) =>
  api.delete(API_ENDPOINTS.IE_STANDARD_TIME(id));

export const getStandardTimesByProduct = (product_id: string, factory_id: string) =>
  api.get<any[]>(API_ENDPOINTS.IE_STANDARD_TIMES_BY_PRODUCT(product_id, factory_id));

// ==================== Time Study Management ====================

export interface TimeStudyCreate {
  factory_id: string;
  product_id: string;
  station_id: string;
  operation_name: string;
  operator_id: string;
  observer_id: string;
  observation_date: string;
  observed_cycles: number[];
  rating_factor: number;
  method: string;
}

export interface TimeStudyResponse {
  id: string;
  factory_id: string;
  station_id: string;
  operation_name: string;
  operator_id: string;
  average_time: number;
  normal_time: number;
  allowed_time: number;
  status: string;
  created_at: string;
}

export const listTimeStudies = (factory_id: string, params?: Record<string, any>) =>
  api.get<any, { items: TimeStudyResponse[]; total: number }>(
    API_ENDPOINTS.IE_TIME_STUDIES,
    { params: { factory_id, ...params } },
  );

export const createTimeStudy = (data: TimeStudyCreate) =>
  api.post(API_ENDPOINTS.IE_TIME_STUDIES, data);

// ==================== Line Balance Analysis ====================

export interface LineBalanceAnalysis {
  id: string;
  factory_id: string;
  line_id: string;
  product_id: string;
  balance_rate: number;
  takt_time_min: number;
  bottleneck_station?: string;
  created_at: string;
  recommendations?: string[];
}

export const listLineBalanceAnalyses = (factory_id: string, params?: Record<string, any>) =>
  api.get<any, { items: LineBalanceAnalysis[]; total: number }>(
    API_ENDPOINTS.IE_LINE_BALANCE_ANALYSES,
    { params: { factory_id, ...params } },
  );

export const analyzeLineBalance = (data: Record<string, any>) =>
  api.post(API_ENDPOINTS.IE_LINE_BALANCE_ANALYSES, data);

// ==================== Process Analysis ====================

export interface ProcessAnalysis {
  id: string;
  factory_id: string;
  product_id: string;
  operation_code: string;
  va_ratio: number;
  efficiency_score: number;
  created_at: string;
}

export const listProcessAnalyses = (factory_id: string, params?: Record<string, any>) =>
  api.get<any, { items: ProcessAnalysis[]; total: number }>(
    API_ENDPOINTS.IE_PROCESS_ANALYSES,
    { params: { factory_id, ...params } },
  );

export const createProcessAnalysis = (data: Record<string, any>) =>
  api.post(API_ENDPOINTS.IE_PROCESS_ANALYSES, data);

// ==================== Lean Metrics ====================

export interface LeanMetrics {
  factory_id: string;
  product_id?: string;
  total_value_added_time: number;
  total_non_value_added_time: number;
  overall_va_ratio: number;
  analysis_count: number;
  processes: Array<{
    operation: string;
    va: number;
    nva: number;
    ratio: number;
    efficiency: number;
  }>;
}

export const getLeanMetrics = (factory_id: string, params?: Record<string, any>) =>
  api.get<LeanMetrics>(API_ENDPOINTS.IE_LEAN_METRICS, { params: { factory_id, ...params } });

// ==================== Advanced IE - Action Studies ====================

export interface ActionStudyCreate {
  factory_id: string;
  product_id: string;
  operation_name: string;
  station_id?: string;
  operator_id: string;
  method_type: string;
  recorded_by: string;
  study_date: string;
  motions: Record<string, any>[];
  total_time_cycles: number;
}

export interface ActionStudyResponse {
  id: string;
  factory_id: string;
  product_id: string;
  operation_name: string;
  station_id?: string;
  operator_id: string;
  method_type: string;
  recorded_by: string;
  study_date: string;
  created_at: string;
}

export const listActionStudies = (factory_id: string) =>
  api.get<any, { items: ActionStudyResponse[]; total: number }>(
    API_ENDPOINTS.IE_ADVANCED_ACTION_STUDIES,
    { params: { factory_id } },
  );

export const createActionStudy = (data: ActionStudyCreate) =>
  api.post(API_ENDPOINTS.IE_ADVANCED_ACTION_STUDIES, data);

// ==================== Advanced IE - Method Studies ====================

export interface MethodStudyCreate {
  factory_id: string;
  product_id: string;
  original_operation: string;
  version: string;
  is_basement_method: boolean;
  is_optimal_method: boolean;
  description: string;
  action_sequence: Record<string, any>[];
  setup_time_min: number;
  cycle_time_min: number;
  total_standard_time_min: number;
  validity_start: string;
  validity_end?: string;
  created_by: string;
}

export interface MethodStudyResponse {
  id: string;
  factory_id: string;
  product_id: string;
  original_operation: string;
  version: string;
  is_basement_method: boolean;
  is_optimal_method: boolean;
  created_at: string;
}

export const createMethodStudy = (data: MethodStudyCreate) =>
  api.post(API_ENDPOINTS.IE_ADVANCED_METHOD_STUDIES, data);

// ==================== Advanced IE - Work Cells ====================

export interface WorkCellLayoutInput {
  factory_id: string;
  work_cell_id: string;
  product_family_id: string;
  material_flow_path: string[];
  operator_movement_path: string[];
  takt_time_alignment: string;
}

export const createWorkCell = (data: WorkCellLayoutInput) =>
  api.post(API_ENDPOINTS.IE_ADVANCED_WORK_CELLS, data);

// ==================== Advanced IE - Kanban ====================

export interface KanbanCreate {
  factory_id: string;
  kanban_id: string;
  kanban_type: string;
  upstream_station?: string;
  downstream_station?: string;
  product_id: string;
  part_number?: string;
  max_card_count: number;
}

export const createKanban = (data: KanbanCreate) =>
  api.post(API_ENDPOINTS.IE_ADVANCED_KANBANS, data);

// ==================== Advanced IE - 5S Audits ====================

export interface FiveSAuditInput {
  factory_id: string;
  work_center_id: string;
  audit_date: string;
  auditor_id: string;
  seiri_score: number;
  seiton_score: number;
  seiso_score: number;
  seiketsu_score: number;
  shitsuke_score: number;
}

export const createFiveSAudit = (data: FiveSAuditInput) =>
  api.post(API_ENDPOINTS.IE_ADVANCED_5S_AUDITS, data);

export const listFiveSAuditsByCenter = (work_center_id: string, factory_id?: string) =>
  api.get<any[]>(API_ENDPOINTS.IE_ADVANCED_5S_AUDITS_BY_CENTER(work_center_id), {
    params: factory_id ? { factory_id } : {},
  });