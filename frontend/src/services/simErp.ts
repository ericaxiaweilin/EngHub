import api from './api'
import { API_ENDPOINTS } from '../config/api'

export interface SimERPAuditSummary {
  simulation_id: string
  final_status: string
  legal_blocked: boolean
  created_at: string
  total_cost_delta: number
  max_required_break_minutes: number
  blocking_rules: string[]
  warnings: string[]
}

export interface SimERPAuditDetail extends SimERPAuditSummary {
  worker_ref: string
  shift_id: string
  task_type: string
  zone_id: string
  total_penalty_score: number
  snapshot_payload: Record<string, unknown>
  plugin_records_payload: Array<Record<string, unknown>>
  arbiter_result_payload: Record<string, unknown>
}

export interface SimERPAuditQuery {
  page?: number
  page_size?: number
  worker_ref?: string
  final_status?: string
  created_from?: string
  created_to?: string
}

export interface SimERPAuditListResponse {
  items: SimERPAuditSummary[]
  total: number
  page: number
  page_size: number
}

export const getSimErpAudits = (params?: SimERPAuditQuery) =>
  api.get<any, SimERPAuditListResponse>(API_ENDPOINTS.SIM_ERP_AUDITS, { params })

export const getLatestSimErpAudit = () =>
  api.get<any, SimERPAuditSummary>(API_ENDPOINTS.SIM_ERP_AUDIT_LATEST)

export const getSimErpAuditDetail = (simulationId: string) =>
  api.get<any, SimERPAuditDetail>(API_ENDPOINTS.SIM_ERP_AUDIT(simulationId))
