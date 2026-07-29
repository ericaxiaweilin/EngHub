import api from './api'
import { API_ENDPOINTS } from '../config/api'

// ==================== 枚举 ====================

export type ProductionStrategy = 'mts' | 'mto'
export type Priority = 'low' | 'medium' | 'high' | 'urgent'

export const STRATEGY_LABEL: Record<ProductionStrategy, string> = {
  mts: 'MTS 备料平准',
  mto: 'MTO 订单驱动',
}

export const PRIORITY_LABEL: Record<Priority, string> = {
  low: '低',
  medium: '中',
  high: '高',
  urgent: '紧急',
}

export const PRIORITY_COLOR: Record<Priority, string> = {
  low: 'default',
  medium: 'blue',
  high: 'orange',
  urgent: 'red',
}

// ==================== 输入侧 ====================

export interface SectionConfig {
  section_id: string
  name: string
  workshop_id: string
  strategy: ProductionStrategy
  workers: number
  machines: number
  shifts_per_day: number
  hours_per_shift: number
  efficiency: number
  max_overtime_pct: number
  yield_rate: number
  role_name: string
  description: string
}

export interface WorkshopConfig {
  workshop_id: string
  name: string
  working_days_per_week: number // 5=双休 6=单休 7=全周
  description: string
}

export interface RoutingOperation {
  op_no: number
  name: string
  section_id: string
  setup_minutes: number
  cycle_seconds: number
  batch_size: number
  move_hours: number
}

export interface RoutingDef {
  routing_id: string
  product_id: string
  product_name: string
  operations: RoutingOperation[]
}

export interface OrderInput {
  order_id: string
  product_id: string
  quantity: number
  release_day: number
  due_day: number
  priority: Priority
}

export interface FactorySimConfig {
  horizon_days: number
  demand_variability_pct: number
  overtime_allowed: boolean
  seed: number
  workshops: WorkshopConfig[]
  sections: SectionConfig[]
  routings: RoutingDef[]
  orders: OrderInput[]
}

// ==================== 输出侧 ====================

export interface SectionDayLoad {
  day: number
  load_hours: number
  capacity_hours: number
  load_rate: number
  is_workday: boolean
  wip_qty: number
}

export interface SectionSummary {
  section_id: string
  name: string
  workshop_id: string
  workshop_name: string
  strategy: ProductionStrategy
  workers: number
  machines: number
  shifts_per_day: number
  hours_per_shift: number
  efficiency: number
  total_load_hours: number
  total_capacity_hours: number
  avg_load_rate: number
  peak_load_rate: number
  peak_day: number
  is_bottleneck: boolean
  overtime_used_hours: number
  series: SectionDayLoad[]
}

export interface OrderOpSchedule {
  op_no: number
  name: string
  section_id: string
  section_name: string
  strategy: ProductionStrategy
  start_day: number
  end_day: number
  work_hours: number
}

export interface OrderResult {
  order_id: string
  product_id: string
  product_name: string
  quantity: number
  priority: Priority
  release_day: number
  due_day: number
  completion_day: number
  delay_days: number
  on_time: boolean
  total_work_hours: number
  ops: OrderOpSchedule[]
}

export interface OrderSectionLoad {
  order_id: string
  section_id: string
  section_name: string
  work_hours: number
  share_pct: number
}

export interface WipPoint {
  day: number
  wip_qty: number
  active_orders: number
}

// ==================== 完整仿真扩展 ====================

export interface WorkerDef {
  worker_id: string
  name: string
  section_id: string
  section_name: string
  role: string
  skill_level: number
  shift: number
  attendance_rate: number
  gender?: string
  height_cm?: number
  weight_kg?: number
}

export interface SectionWorkforce {
  section_id: string
  name: string
  headcount: number
  per_shift: number
  shift_headcount: Record<string, number>
  avg_skill: number
  avg_attendance: number
  labor_utilization: number
  workers: WorkerDef[]
}

export interface OutputPoint {
  day: number
  output_qty: number
  good_qty: number
  scrap_qty: number
  cumulative: number
}

export interface SectionOutput {
  section_id: string
  name: string
  planned_qty: number
  good_qty: number
  scrap_qty: number
  yield_rate: number
}

export interface PoOpResult {
  op_no: number
  name: string
  section_id: string
  section_name: string
  start_day: number
  end_day: number
  qty: number
  good_qty: number
  scrap_qty: number
  status: string
  wait_days: number
}

export interface ProductionOrderResult {
  po_id: string
  order_id: string
  product_name: string
  quantity: number
  release_day: number
  start_day: number
  completion_day: number
  due_day: number
  status: string
  on_time: boolean
  good_qty: number
  scrap_qty: number
  current_section: string
  ops: PoOpResult[]
}

export interface TransferRecord {
  transfer_id: string
  order_id: string
  product_name: string
  from_section_id: string
  from_section_name: string
  to_section_id: string
  to_section_name: string
  qty: number
  depart_day: number
  arrive_day: number
}

// ==================== 全过程 / 卡点扩展 ====================

export type BlockingType = 'overload' | 'wip_buildup' | 'process_wait'

export const BLOCKING_TYPE_LABEL: Record<BlockingType, string> = {
  overload: '过载瓶颈',
  wip_buildup: 'WIP 积压',
  process_wait: '工序等待',
}

export const BLOCKING_TYPE_COLOR: Record<BlockingType, string> = {
  overload: 'red',
  wip_buildup: 'orange',
  process_wait: 'gold',
}

export interface BlockingPoint {
  rank: number
  section_id: string
  section_name: string
  workshop_name: string
  blocking_type: BlockingType
  severity: number
  peak_day: number
  peak_load_rate: number
  overload_days: number
  wip_peak: number
  avg_wait_days: number
  delayed_orders: number
  detail: string
}

export interface OutboundOrder {
  outbound_id: string
  order_id: string
  po_id: string
  product_name: string
  quantity: number
  good_qty: number
  outbound_day: number
  on_time: boolean
  warehouse: string
  status: string // shipped / pending
}

export interface FactoryAlert {
  level: 'critical' | 'warning' | 'info' | string
  category: 'overload' | 'delay' | 'bottleneck' | 'idle' | 'imbalance' | string
  title: string
  detail: string
  section_id?: string | null
  order_id?: string | null
  day?: number | null
}

export interface FactoryKPIs {
  total_work_hours: number
  total_capacity_hours: number
  avg_load_rate: number
  peak_load_rate: number
  on_time_rate: number
  delayed_orders: number
  bottleneck_sections: number
  wip_peak: number
  imbalance_index: number
  overtime_hours: number
  total_output: number
  good_output: number
  scrap_output: number
  avg_yield_rate: number
  headcount: number
  po_completed: number
  po_delayed: number
  blocking_point_count: number
  max_section_wip: number
  total_outbound: number
  pending_outbound: number
  avg_process_wait: number
}

export interface FactorySimResult {
  simulation_id: string
  created_at: string
  engine_version: string
  horizon_days: number
  workshop_count: number
  section_count: number
  order_count: number
  kpis: FactoryKPIs
  sections: SectionSummary[]
  orders: OrderResult[]
  order_section_loads: OrderSectionLoad[]
  wip_curve: WipPoint[]
  alerts: FactoryAlert[]
  workforce: SectionWorkforce[]
  daily_output: OutputPoint[]
  section_outputs: SectionOutput[]
  production_orders: ProductionOrderResult[]
  transfers: TransferRecord[]
  blocking_points: BlockingPoint[]
  outbound_orders: OutboundOrder[]
}

export interface FactorySimScenarioResponse {
  scenario_id: string
  scenario_name: string
  description: string
  hints: string[]
  tags: string[]
  config: FactorySimConfig
}

export interface FactoryScenarioMeta {
  scenario_id: string
  scenario_name: string
  description: string
  tags: string[]
  hints: string[]
}

// 仿真结果看板全量数据（与真实生产数据分离，is_simulation 恒为 true）
export interface SimDashboardFullResult extends FactorySimResult {
  is_simulation: boolean
  scenario_id: string
  scenario_name: string
}

// 生产看板全量数据（真实生产数据，is_simulation 恒为 false，与仿真结果同构以复用UI组件）
export interface ProductionDashboardResult extends FactorySimResult {
  is_simulation: false
  factory_id: string
  realtime: {
    active_work_orders: number
    running_equipment: number
    total_equipment: number
    equipment_utilization: number
    today_reports: number
    today_good_output: number
  }
}

// ==================== API ====================

export const getFactoryScenarios = () =>
  api.get<any, FactoryScenarioMeta[]>(API_ENDPOINTS.SIM_FACTORY_SCENARIOS)

export const getFactoryScenario = (scenarioId?: string) =>
  api.get<any, FactorySimScenarioResponse>(API_ENDPOINTS.SIM_FACTORY_SCENARIO(scenarioId))

export const runFactorySimulation = (config: FactorySimConfig) =>
  api.post<any, FactorySimResult>(API_ENDPOINTS.SIM_FACTORY_RUN, config)

export const getFactorySimDashboardResult = (scenarioId?: string) =>
  api.get<any, SimDashboardFullResult>(API_ENDPOINTS.SIM_FACTORY_DASHBOARD_SUMMARY(scenarioId))

// 生产看板聚合数据（真实生产数据，复用仿真结果组件渲染）
export const getProductionDashboardResult = (factoryId?: string, horizonDays?: number) =>
  api.get<any, ProductionDashboardResult>(API_ENDPOINTS.PRODUCTION_DASHBOARD_SUMMARY(factoryId, horizonDays))
