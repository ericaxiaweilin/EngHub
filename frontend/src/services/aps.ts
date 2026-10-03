import api from './api'

// ============== Types ==============

export interface ApsSchedule {
  id: string
  schedule_code: string
  factory_id: string
  mode: string
  optimize_for: string
  status: string
  version_number?: number
  is_current?: boolean
  supersedes_schedule_id?: string
  change_reason?: string
  horizon_start: string
  horizon_end: string
  on_time_rate?: number
  avg_utilization?: number
  total_setup_minutes?: number
  avg_cycle_hours?: number
  total_tasks: number
  unscheduled_count: number
  created_by?: string
  confirmed_by?: string
  created_at?: string
}

export interface ApsTask {
  id: string
  work_order_id?: string
  order_code?: string
  product_code?: string
  operation_seq: number
  operation_name?: string
  station_id: string
  planned_start: string
  planned_end: string
  setup_seconds?: number
  run_seconds?: number
  quantity?: number
  status: string
  is_locked: boolean
  priority: number
  material_ready?: boolean
}

export interface GanttData {
  schedule_id: string
  schedule_code: string
  status: string
  horizon_start: string
  horizon_end: string
  resources: Record<string, ApsTask[]>
  total_tasks: number
}

export interface CapacityResource {
  station_id: string
  avg_utilization: number
  is_bottleneck: boolean
  daily_load: {
    date: string
    load_hours: number
    capacity_hours: number
    utilization: number
    overloaded: boolean
  }[]
}

export interface CapacityLoadData {
  factory_id: string
  horizon_days: number
  daily_capacity_hours: number | null
  resources: CapacityResource[]
  bottleneck_count: number
}

// ============== 插单审批流 (Q4) ==============

export interface RushApproval {
  id: string
  approval_code: string
  factory_id: string
  product_id: string
  quantity: number
  due_date?: string | null
  rush_priority: string
  impact_json?: {
    affected_orders: number
    total_existing_orders: number
    max_delay_hours: number
    delayed_orders?: Array<Record<string, any>>
    rush_feasible?: boolean
  }
  affected_orders: number
  max_delay_days: string | number
  process_hours?: string | number
  recommendation?: string
  approval_level: number
  required_role?: string
  status: string
  applicant?: string
  approver?: string
  approved_at?: string
  reject_reason?: string
  target_schedule_id?: string
  created_at?: string
  logs?: Array<{
    id: string
    action: string
    actor: string
    actor_role?: string
    comment?: string
    created_at: string
  }>
}

// ============== API ==============

export const apsApi = {
  /** 生成排程方案 */
  generate(params: { factory_id: string; mode?: string; horizon_days?: number; optimize_for?: string; reason?: string }) {
    return api.post('/api/v1/aps/generate', params)
  },

  /** 排程方案列表 */
  listSchedules(params: { factory_id: string; status?: string; page?: number; page_size?: number }) {
    return api.get('/api/v1/aps/schedules', { params })
  },

  /** 方案详情 */
  getSchedule(id: string) {
    return api.get(`/api/v1/aps/schedules/${id}`)
  },

  /** 确认方案 */
  confirmSchedule(id: string) {
    return api.post(`/api/v1/aps/schedules/${id}/confirm`)
  },

  /** 下达方案 */
  /** 下达方案：allow_partial=true 表示计划员确认只下达已排产部分 */
  releaseSchedule(id: string, data?: { allow_partial?: boolean; note?: string }) {
    return api.post(`/api/v1/aps/schedules/${id}/release`, data ?? {})
  },

  /** 插单重排：带 insert_wo_id 需要已批准的 approval_id；不带则是整盘重排 */
  reschedule(params: { factory_id: string; insert_wo_id?: string; reason?: string; approval_id?: string }) {
    return api.post('/api/v1/aps/reschedule', params)
  },

  /** 钉住/放开某道工序：锁定行在后续重排中原样保留 */
  lockTask(taskId: string, data: { locked: boolean; note?: string }) {
    return api.post(`/api/v1/aps/tasks/${taskId}/lock`, data)
  },

  /** PMC 手工改派工序的工位/时刻（后端校验班次与占用，改完自动钉住） */
  overrideTask(taskId: string, data: { station_id?: string; planned_start?: string; planned_end?: string; note?: string }) {
    return api.patch(`/api/v1/aps/tasks/${taskId}`, data)
  },

  /** 甘特图数据 */
  getGantt(id: string): Promise<GanttData> {
    return api.get(`/api/v1/aps/gantt/${id}`)
  },

  /** KPI 指标 */
  getKpi(id: string) {
    return api.get(`/api/v1/aps/kpi/${id}`)
  },

  /** 工作日历列表 */
  listCalendars(params: { factory_id: string; resource_id?: string }) {
    return api.get('/api/v1/aps/calendars', { params })
  },

  /** 创建工作日历 */
  createCalendar(data: any) {
    return api.post('/api/v1/aps/calendars', data)
  },

  /** 产能负荷分析 */
  getCapacityLoad(params: { factory_id: string; days?: number }): Promise<CapacityLoadData> {
    return api.get('/api/v1/aps/capacity-load', { params })
  },

  /** Phase 2: 有限产能排程（算法选择） */
  scheduleWithAlgorithm(params: { factory_id: string; algorithm?: string; horizon_days?: number }) {
    return api.post('/api/v1/aps/schedule', params)
  },

  /** Phase 2: 插单重排（锁定在制） */
  rescheduleV2(params: { factory_id: string; insert_wo_id?: string; algorithm?: string }) {
    return api.post('/api/v1/aps/reschedule', params)
  },

  /** Phase 2: 冲突检测 */
  detectConflicts(params: { factory_id: string }) {
    return api.get('/api/v1/aps/conflicts', { params })
  },

  // ===== 插单审批流 (Q4) =====

  /** 插单评估并生成审批单草稿（persist=true 落库） */
  rushOrderImpact(params: { factory_id: string; product_id: string; quantity: number; due_date?: string; priority?: string; persist?: boolean }) {
    return api.post('/api/v1/aps/rush-order-impact', params)
  },

  /** 插单审批单列表 */
  listRushApprovals(params: { factory_id: string; status?: string; mine?: boolean }) {
    return api.get('/api/v1/aps/rush-order/approvals', { params })
  },

  /** 插单审批单详情 */
  getRushApproval(id: string) {
    return api.get(`/api/v1/aps/rush-order/approvals/${id}`)
  },

  /** 提报 */
  submitRushApproval(id: string, comment?: string) {
    return api.post(`/api/v1/aps/rush-order/approvals/${id}/submit`, { comment })
  },

  /** 审批通过（触发重排） */
  approveRushApproval(id: string, comment?: string) {
    return api.post(`/api/v1/aps/rush-order/approvals/${id}/approve`, { comment })
  },

  /** 驳回 */
  rejectRushApproval(id: string, reason: string) {
    return api.post(`/api/v1/aps/rush-order/approvals/${id}/reject`, { reason })
  },

  /** 撤销 */
  cancelRushApproval(id: string) {
    return api.post(`/api/v1/aps/rush-order/approvals/${id}/cancel`, {})
  },
}
