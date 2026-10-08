import api from './api'
import { API_ENDPOINTS } from '../config/api'

// ---------------- Sim-ERP 仿真引擎 ----------------
export interface SimEnvironment {
  temperature_c: number
  humidity_percent: number
  noise_db?: number | null
  dust_mg_m3?: number | null
  terrain?: string
  floor_incline_percent?: number
}

export interface SimWorkContext {
  worker_ref: string
  shift_id: string
  task_type: string
  zone_id: string
  skill_level?: string | null
  ppe_status?: string | null
  machine_risk_level?: string | null
  action_type?: string
}

export interface SimulationRequest {
  time_step_minutes: number
  step_count: number
  load_weight_kg: number
  posture_angle_deg: number
  continuous_work_minutes: number
  distance_meters: number
  environment: SimEnvironment
  work_context: SimWorkContext
  plugin_names: string[]
  // 出勤基线取哪个厂的 attendance 台账；不带就只报缺勤增量
  factory_id?: string
}

export interface RuleEvidence {
  field: string
  observed_value: any
  expected?: string | null
  source?: string | null
}

export interface RequiredAction {
  action_code: string
  description: string
  break_minutes: number
  metadata: Record<string, any>
}

export interface RuleDecision {
  plugin_name: string
  plugin_version: string
  rule_code: string
  rule_version: string
  decision_type: string
  priority: string
  message: string
  blocking: boolean
  required_break_minutes: number
  cost_delta: number
  penalty_score: number
  evidence: RuleEvidence[]
  required_actions: RequiredAction[]
}

export interface PluginRecord {
  plugin_name: string
  plugin_version: string
  rule_version: string
  priority: string
  legislation_pack?: string | null
  timeout_ms: number
  duration_ms: number
  status: string
  error?: string | null
  decisions: RuleDecision[]
}

export interface SimSnapshot {
  timestamp: string
  worker_ref: string
  shift_id: string
  task_type: string
  zone_id: string
  action_type: string
  distance_meters: number
  step_count: number
  load_weight_kg: number
  posture_angle_deg: number
  continuous_work_minutes: number
  fatigue_score: number
  energy_kcal: number
  temperature_c: number
  humidity_percent: number
  noise_db?: number | null
  terrain: string
  floor_incline_percent: number
  skill_level?: string | null
  ppe_status?: string | null
  machine_risk_level?: string | null
  // 热应力与工况读数（没有规则包时为 null = 没折算过，不是"没有热风险"）
  wbgt_c?: number | null
  wet_bulb_c?: number | null
  tlv_wbgt_c?: number | null
  thermal_exceedance_c?: number | null
  metabolic_level?: string | null
  required_rest_fraction?: number | null
  max_allowable_work_minutes_per_hour?: number | null
  comfort_center_c?: number | null
  comfort_band_c?: number[] | null
  work_efficiency?: number | null
  energy_cost_multiplier?: number | null
  attendance_impact?: Record<string, any>
  thermal_basis?: Record<string, any>
  intensity_basis?: Record<string, any>
}

export interface SimulationResult {
  simulation_id: string
  final_status: string
  legal_blocked: boolean
  fatigue_score: number
  energy_kcal: number
  total_cost_delta: number
  max_required_break_minutes: number
  blocking_rules: string[]
  warnings: string[]
  // --- 扩展工程字段 ---
  total_penalty_score: number
  winning_priority?: string | null
  physics_core_version: string
  arbiter_version: string
  snapshot?: SimSnapshot | null
  plugin_records: PluginRecord[]
  applied_actions: RequiredAction[]
  all_decisions: RuleDecision[]
}

export interface PluginManifest {
  plugin_name: string
  plugin_version: string
  rule_version: string
  priority: string
  legislation_pack?: string | null
  timeout_ms: number
}

export const getSimPlugins = () =>
  api.get<any, PluginManifest[]>(API_ENDPOINTS.SIM_ERP_PLUGINS)

export const getSimStatus = () =>
  api.get<any, { status: string; engine: string; physics_model: string }>(API_ENDPOINTS.SIM_ERP_STATUS)

export const runSimulation = (data: SimulationRequest) =>
  api.post<any, SimulationResult>(API_ENDPOINTS.SIM_ERP_SIMULATE, data)

export interface WorkingConditionImpactRequest {
  temperature_c: number
  humidity_percent?: number
  task_type?: string
  factory_id?: string
  model_code?: string
  units?: number
  due_in_days?: number
}

export const runWorkingConditionImpact = (data: WorkingConditionImpactRequest) =>
  api.post<any, Record<string, any>>(API_ENDPOINTS.SIM_ERP_WC_IMPACT, data)

export const runHighHeatScenario = (data: Record<string, any>) =>
  api.post<any, SimulationResult>(API_ENDPOINTS.SIM_ERP_SCENARIO_HHO, data)

// ---------------- 生产计划 / MRP ----------------
export const listPlans = (factory_id: string, params?: Record<string, any>) =>
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.PLANS, { params: { factory_id, ...params } })

export const createPlan = (data: Record<string, any>) =>
  api.post(API_ENDPOINTS.PLANS, data)

export const confirmPlan = (id: string) => api.post(API_ENDPOINTS.PLAN_CONFIRM(id), {})
export const releasePlan = (id: string) => api.post(API_ENDPOINTS.PLAN_RELEASE(id), {})
export const checkCapacityConflict = (id: string) =>
  api.get<any, { has_conflict: boolean; conflicts: any[] }>(API_ENDPOINTS.PLAN_CAPACITY_CONFLICT(id))
export const calculateMrp = (plan_id: string) =>
  api.post<any, { id: string; status: string; items: any[] }>(`${API_ENDPOINTS.MRP_CALCULATE}?plan_id=${plan_id}`, {})

// ---------------- 基础数据: 工位/工艺/设备 ----------------
export const listStations = (params?: Record<string, any>) =>
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.STATIONS, { params })
export const listRoutings = (params?: Record<string, any>) =>
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.ROUTINGS, { params })
export const listEquipment = (params?: Record<string, any>) =>
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.EQUIPMENT, { params })

// ---------------- 员工技能矩阵 ----------------
export const listSkills = () => api.get<any, any[]>(API_ENDPOINTS.SKILLS)
export const getSkillMatrix = (params?: Record<string, any>) =>
  api.get<any, any[]>(API_ENDPOINTS.SKILL_MATRIX, { params })
export const getExpiringCerts = (params?: Record<string, any>) =>
  api.get<any, any>(API_ENDPOINTS.EXPIRING_CERTS, { params })

// ---------------- 仓库 ----------------
export const listWarehouses = (params?: Record<string, any>) =>
  api.get<any, { items: any[]; total: number }>(API_ENDPOINTS.WAREHOUSES, { params })

// ---------------- AI 助手 ----------------
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}
export interface ChatResponse {
  reply: string
  model: string
  degraded: boolean
}
export const sendChat = (messages: ChatMessage[]) =>
  api.post<any, ChatResponse>(API_ENDPOINTS.CHAT, { messages })
export const getChatHealth = () =>
  api.get<any, { configured: boolean; reachable: boolean; model: string; gateway: string; detail: string }>(
    API_ENDPOINTS.CHAT_HEALTH,
  )
