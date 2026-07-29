import api from './api'

// ============== Types ==============

export interface ApsSchedule {
  id: string
  schedule_code: string
  factory_id: string
  mode: string
  optimize_for: string
  status: string
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
  daily_capacity_hours: number
  resources: CapacityResource[]
  bottleneck_count: number
}

// ============== API ==============

export const apsApi = {
  /** 生成排程方案 */
  generate(params: { factory_id: string; mode?: string; horizon_days?: number; optimize_for?: string }) {
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
  releaseSchedule(id: string) {
    return api.post(`/api/v1/aps/schedules/${id}/release`)
  },

  /** 插单重排 */
  reschedule(params: { factory_id: string; insert_wo_id?: string }) {
    return api.post('/api/v1/aps/reschedule', params)
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
}
