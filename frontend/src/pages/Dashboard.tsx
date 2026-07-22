import React, { useEffect, useState, useCallback } from 'react'
import { Row, Col, Card, Statistic, Table, Tag, Spin, Progress, message, List, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  RiseOutlined, CheckCircleOutlined, ToolOutlined, AlertOutlined,
  ExperimentOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import {
  getWorkOrders, getProductionReports, getEquipment, getStations, getProducts,
  WorkOrder, ProductionReport, Equipment, Station, Product,
} from '../services/mes'
import { getFactorySimDashboardSummary, FactorySimDashboardSummary, BLOCKING_TYPE_LABEL, BLOCKING_TYPE_COLOR, BlockingType } from '../services/factorySim'
import { getStoredUser } from '../services/auth'
import DrillDownDrawer from '../components/trace/DrillDownDrawer'
import RecordDetailDrawer, { DetailField } from '../components/trace/RecordDetailDrawer'
import { makeStationResolver, makeWorkOrderResolver, makeProductResolver } from '../components/trace/resolvers'

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '待下达' },
  released: { color: 'processing', text: '已下达' },
  in_progress: { color: 'blue', text: '生产中' },
  pending_inbound: { color: 'cyan', text: '待入库' },
  completed: { color: 'success', text: '已完成' },
  cancelled: { color: 'error', text: '已取消' },
  on_hold: { color: 'warning', text: '暂停' },
}

const EQUIPMENT_STATUS: Record<string, { color: string; text: string }> = {
  available: { color: '#52c41a', text: '可用' },
  running: { color: '#1890ff', text: '运行中' },
  maintenance: { color: '#faad14', text: '保养中' },
  fault: { color: '#f5222d', text: '故障' },
  idle: { color: '#8c8c8c', text: '空闲' },
}

interface DrillConfig {
  title: string
  headline?: React.ReactNode
  formula?: string
  columns: ColumnsType<any>
  records: any[]
  onRowClick?: (r: any) => void
}

/* ==================== 仿真结果摘要视图（与真实生产数据完全分离） ==================== */
const SimSummaryView: React.FC<{ summary: FactorySimDashboardSummary; pct: (v: number, d?: number) => string }> = ({ summary, pct }) => {
  const k = summary.kpis
  const items: { title: string; value: string; suffix?: string; color: string; tip?: string }[] = [
    { title: '平均负荷率', value: pct(k.avg_load_rate), color: k.avg_load_rate > 0.9 ? '#fa8c16' : '#1890ff' },
    { title: '峰值负荷率', value: pct(k.peak_load_rate, 0), color: k.peak_load_rate > 1 ? '#f5222d' : '#52c41a' },
    { title: '订单准时率', value: pct(k.on_time_rate, 0), color: k.on_time_rate >= 0.8 ? '#52c41a' : '#f5222d' },
    { title: '延期订单', value: `${k.delayed_orders}`, suffix: `/ ${summary.order_count}`, color: k.delayed_orders > 0 ? '#f5222d' : '#52c41a' },
    { title: '瓶颈工段', value: `${k.bottleneck_sections}`, color: k.bottleneck_sections > 0 ? '#f5222d' : '#52c41a' },
    { title: '负荷不均衡指数', value: k.imbalance_index.toFixed(2), color: k.imbalance_index > 0.4 ? '#fa8c16' : '#52c41a', tip: '各工段平均负荷率的极差' },
    { title: '加班工时', value: k.overtime_hours.toFixed(0), suffix: 'h', color: '#722ed1' },
    { title: 'WIP 峰值', value: `${k.wip_peak}`, suffix: '件', color: '#13c2c2' },
    { title: '成品产出', value: `${k.total_output.toLocaleString()}`, suffix: '件', color: '#52c41a' },
    { title: '综合良品率', value: pct(k.avg_yield_rate), color: k.avg_yield_rate >= 0.97 ? '#52c41a' : '#fa8c16' },
    { title: '在岗人数', value: `${k.headcount}`, suffix: '人', color: '#2f54eb' },
    { title: 'PO 完工/延期', value: `${k.po_completed}/${k.po_delayed}`, color: k.po_delayed > 0 ? '#f5222d' : '#52c41a' },
    { title: '卡点工段', value: `${k.blocking_point_count}`, color: k.blocking_point_count > 0 ? '#f5222d' : '#52c41a' },
    { title: '峰值积压', value: `${k.max_section_wip.toLocaleString()}`, suffix: '件', color: '#fa8c16' },
    { title: '出库总量', value: `${k.total_outbound.toLocaleString()}`, suffix: '件', color: '#52c41a' },
  ]

  return (
    <div>
      {/* 场景信息行 */}
      <div style={{ marginBottom: 12, color: '#8c8c8c', fontSize: 12 }}>
        <ThunderboltOutlined style={{ marginRight: 4 }} />
        场景 {summary.scenario_name} · 计划期 {summary.horizon_days} 天 · {summary.order_count} 订单 · {summary.section_count} 工段
        {summary.critical_alert_count > 0 && <Tag color="red" style={{ marginLeft: 8 }}>{summary.critical_alert_count} 条严重预警</Tag>}
        <span style={{ marginLeft: 8 }}>生成于 {dayjs(summary.created_at).format('MM-DD HH:mm')}</span>
      </div>

      {/* 仿真 KPI 卡片 */}
      <Row gutter={[12, 12]}>
        {items.map((it) => (
          <Col span={6} xl={3} key={it.title}>
            <Card size="small" styles={{ body: { padding: '10px 14px' } }}>
              <Tooltip title={it.tip}>
                <div style={{ fontSize: 11, color: '#8c8c8c' }}>{it.title}</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: it.color, lineHeight: 1.3 }}>
                  {it.value}
                  {it.suffix && <span style={{ fontSize: 12, fontWeight: 400, marginLeft: 2 }}>{it.suffix}</span>}
                </div>
              </Tooltip>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 卡点排行 Top5 */}
      {summary.blocking_points.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            <AlertOutlined style={{ color: '#f5222d', marginRight: 4 }} />
            卡点排行（Top {summary.blocking_points.length}）
          </div>
          <Row gutter={[12, 12]}>
            {summary.blocking_points.map((bp) => (
              <Col span={8} key={`${bp.section_id}-${bp.rank}`}>
                <Card size="small" styles={{ body: { padding: '8px 12px' } }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600 }}>#{bp.rank} {bp.section_name}</span>
                    <Tag color={BLOCKING_TYPE_COLOR[bp.blocking_type as BlockingType]} style={{ margin: 0 }}>
                      {BLOCKING_TYPE_LABEL[bp.blocking_type as BlockingType] || bp.blocking_type}
                    </Tag>
                  </div>
                  <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>
                    严重度 {bp.severity.toFixed(0)} · 峰值 {Math.round(bp.peak_load_rate * 100)}% · WIP {bp.wip_peak.toLocaleString()} 件 · 延期 {bp.delayed_orders} 单
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        </div>
      )}
    </div>
  )
}

const Dashboard: React.FC = () => {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])
  const [reports, setReports] = useState<ProductionReport[]>([])
  const [equipment, setEquipment] = useState<Equipment[]>([])
  const [stations, setStations] = useState<Station[]>([])
  const [products, setProducts] = useState<Product[]>([])

  // 追溯交互状态：KPI 下钻抽屉 / 报工原始记录详情 / 设备详情
  const [drill, setDrill] = useState<DrillConfig | null>(null)
  const [reportDetail, setReportDetail] = useState<ProductionReport | null>(null)
  const [equipDetail, setEquipDetail] = useState<Equipment | null>(null)

  // 仿真结果（与真实生产数据分离，独立加载，互不影响）
  const [simSummary, setSimSummary] = useState<FactorySimDashboardSummary | null>(null)
  const [simLoading, setSimLoading] = useState(false)

  const user = getStoredUser()
  const factoryId = user?.factory_id || 'F01'

  // 仿真 KPI 百分比格式化
  const pct = (v: number, digits = 1) => `${(v * 100).toFixed(digits)}%`

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      // 用 allSettled：单个接口失败不会拖垮其他看板数据的展示
      const [woRes, rptRes, eqRes, stRes, pdRes] = await Promise.allSettled([
        getWorkOrders({ factory_id: factoryId, page_size: 50 }),
        getProductionReports({ factory_id: factoryId, page_size: 50 }),
        getEquipment({ factory_id: factoryId, page_size: 50 }),
        getStations({ factory_id: factoryId, page_size: 50 }),
        getProducts(),
      ])
      setWorkOrders(woRes.status === 'fulfilled' ? (woRes.value.items || []) : [])
      setReports(rptRes.status === 'fulfilled' ? (rptRes.value.items || []) : [])
      setEquipment(eqRes.status === 'fulfilled' ? (eqRes.value.items || []) : [])
      setStations(stRes.status === 'fulfilled' ? (stRes.value.items || []) : [])
      setProducts(pdRes.status === 'fulfilled' ? (pdRes.value.items || []) : [])
      if (woRes.status === 'rejected') {
        message.error('获取工单数据失败')
      }
    } finally {
      setLoading(false)
    }
  }, [factoryId])

  useEffect(() => { fetchData() }, [fetchData])

  // 仿真结果独立加载：仿真接口失败不影响真实生产看板
  const fetchSim = useCallback(async () => {
    setSimLoading(true)
    try {
      const res = await getFactorySimDashboardSummary()
      setSimSummary(res)
    } catch {
      // 静默失败：仿真为辅助决策数据，不阻断看板
      setSimSummary(null)
    } finally {
      setSimLoading(false)
    }
  }, [])

  useEffect(() => { fetchSim() }, [fetchSim])

  // 统计计算
  const activeOrders = workOrders.filter(wo => wo.status === 'in_progress')
  // created_at 存的是 naive UTC（无时区后缀），补 'Z' 让 dayjs 按 UTC 时刻解析，
  // 再换算到本地时区比对“今天”，避免把 UTC 时间当本地时间导致日期错位
  const asLocalDay = (ts: string) => dayjs(ts && !ts.endsWith('Z') ? `${ts}Z` : ts)
  const todayReports = reports.filter(r => asLocalDay(r.created_at).isSame(dayjs(), 'day'))
  const todayOutput = todayReports.reduce((s, r) => s + r.good_qty, 0)
  const todayDefect = todayReports.reduce((s, r) => s + r.defect_qty, 0)
  const yieldRate = todayOutput + todayDefect > 0
    ? (todayOutput / (todayOutput + todayDefect) * 100).toFixed(1)
    : '100.0'
  const runningEquipment = equipment.filter(e => e.status === 'running').length
  const equipmentUtilization = equipment.length > 0
    ? Math.round(runningEquipment / equipment.length * 100)
    : 0

  // ===== 追溯：ID 可读化（裸 UUID → 工位名/工单号/产品名）=====
  const stationLabel = makeStationResolver(stations)
  const woLabel = makeWorkOrderResolver(workOrders)
  const productLabel = makeProductResolver(products)

  // ===== 追溯：报工原始记录详情字段（唯一编号/时间/经手人/修改痕迹）=====
  const reportFields: DetailField[] = [
    { label: '报工单号', key: 'report_code' },
    {
      label: '所属工单', key: 'work_order_id',
      render: (v: string) => (
        <a onClick={() => { setReportDetail(null); navigate(`/work-orders/${v}`) }}>{woLabel(v)}</a>
      ),
    },
    { label: '工位', key: 'station_id', render: (v: string) => stationLabel(v) },
    { label: '操作人', key: 'operator_id', render: (v: string) => v || '-' },
    { label: '良品数', key: 'good_qty', render: (v: number) => <span style={{ color: '#52c41a', fontWeight: 600 }}>{v}</span> },
    { label: '不良数', key: 'defect_qty', render: (v: number) => <span style={{ color: '#faad14', fontWeight: 600 }}>{v}</span> },
    { label: '报废数', key: 'scrap_qty', render: (v: number) => <span style={{ color: '#f5222d' }}>{v}</span> },
    { label: '报工类型', key: 'report_type' },
    { label: '班次', key: 'shift', render: (v: string) => (v === 'day' ? '白班' : v === 'night' ? '夜班' : v) },
    { label: '报工人', key: 'created_by', render: (v: string) => v || '-' },
    { label: '报工时间', key: 'created_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-') },
    {
      label: '修改痕迹', key: 'is_modified',
      render: (v: boolean, r: ProductionReport) =>
        v
          ? <span style={{ color: '#faad14' }}>已修改{r.modified_at ? `（${dayjs(r.modified_at).format('MM-DD HH:mm')}）` : ''}</span>
          : '未修改',
    },
    { label: '备注', key: 'remark', span: 2, render: (v: string) => v || '-' },
  ]

  // ===== 追溯：设备详情字段 =====
  const equipFields: DetailField[] = [
    { label: '设备编码', key: 'equipment_code' },
    { label: '设备名称', key: 'equipment_name' },
    { label: '设备类型', key: 'equipment_type', render: (v: string) => v || '-' },
    {
      label: '当前状态', key: 'status',
      render: (v: string) => {
        const info = EQUIPMENT_STATUS[v] || { color: '#8c8c8c', text: v }
        return <Tag color={info.color}>{info.text}</Tag>
      },
    },
    { label: '所属工位', key: 'station_id', render: (v: string) => stationLabel(v) },
    { label: '上次保养', key: 'last_maintenance_date', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD') : '-') },
    { label: '下次保养', key: 'next_maintenance_date', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD') : '-') },
    { label: '创建时间', key: 'created_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-') },
  ]

  // ===== 追溯：报工下钻共用列 =====
  const reportDrillColumns: ColumnsType<any> = [
    { title: '报工单号', dataIndex: 'report_code', key: 'code', width: 160 },
    { title: '工单号', dataIndex: 'work_order_id', key: 'wo', render: (v: string) => woLabel(v) },
    { title: '工位', dataIndex: 'station_id', key: 'st', render: (v: string) => stationLabel(v) },
    { title: '良品', dataIndex: 'good_qty', key: 'good', width: 70, render: (v: number) => <span style={{ color: '#52c41a' }}>{v}</span> },
    { title: '不良', dataIndex: 'defect_qty', key: 'defect', width: 70, render: (v: number) => <span style={{ color: '#faad14' }}>{v}</span> },
    { title: '时间', dataIndex: 'created_at', key: 'time', width: 80, render: (v: string) => dayjs(v).format('HH:mm') },
    { title: '报工人', dataIndex: 'created_by', key: 'by', width: 90, render: (v: string) => v || '-' },
  ]

  // ===== 追溯：4 个 KPI 的下钻配置（数字 → 构成它的原始记录 + 计算公式）=====
  const kpiDrills = {
    output: (): DrillConfig => ({
      title: '今日良品产出 · 追溯',
      headline: `${todayOutput} 件`,
      formula: todayReports.length > 0
        ? `${todayOutput} = ${todayReports.map(r => r.good_qty).join(' + ')}（${todayReports.length} 条报工）`
        : '今日暂无报工',
      columns: reportDrillColumns,
      records: todayReports,
      onRowClick: (r) => setReportDetail(r),
    }),
    yieldKpi: (): DrillConfig => ({
      title: '今日良品率 · 追溯',
      headline: `${yieldRate}%`,
      formula: `良品 ${todayOutput} ÷（良品 ${todayOutput} + 不良 ${todayDefect}）= ${yieldRate}%`,
      columns: [
        { title: '报工单号', dataIndex: 'report_code', key: 'code', width: 160 },
        { title: '工单号', dataIndex: 'work_order_id', key: 'wo', render: (v: string) => woLabel(v) },
        { title: '良品', dataIndex: 'good_qty', key: 'good', width: 70, render: (v: number) => <span style={{ color: '#52c41a' }}>{v}</span> },
        { title: '不良', dataIndex: 'defect_qty', key: 'defect', width: 70, render: (v: number) => <span style={{ color: '#faad14' }}>{v}</span> },
        {
          title: '单条良率', key: 'rate', width: 90,
          render: (_: any, r: ProductionReport) => {
            const tot = r.good_qty + r.defect_qty
            return tot > 0 ? `${(r.good_qty / tot * 100).toFixed(1)}%` : '-'
          },
        },
      ],
      records: todayReports,
      onRowClick: (r) => setReportDetail(r),
    }),
    orders: (): DrillConfig => ({
      title: '在制工单 · 追溯',
      headline: `${activeOrders.length} 个`,
      formula: `${activeOrders.length} 在制 / ${workOrders.length} 总工单`,
      columns: [
        { title: '工单号', dataIndex: 'work_order_code', key: 'code', width: 160 },
        { title: '产品', dataIndex: 'product_id', key: 'prod', ellipsis: true, render: (v: string) => productLabel(v) },
        { title: '完成/计划', key: 'qty', width: 100, render: (_: any, r: WorkOrder) => `${r.completed_qty}/${r.planned_qty}` },
        {
          title: '良/不良', key: 'q', width: 90,
          render: (_: any, r: WorkOrder) => (
            <span><span style={{ color: '#52c41a' }}>{r.good_qty}</span>/<span style={{ color: '#faad14' }}>{r.defect_qty}</span></span>
          ),
        },
        {
          title: '状态', dataIndex: 'status', key: 'status', width: 90,
          render: (s: string) => { const i = STATUS_MAP[s] || { color: 'default', text: s }; return <Tag color={i.color}>{i.text}</Tag> },
        },
        { title: '交期', dataIndex: 'planned_due', key: 'due', width: 90, render: (v: string) => (v ? dayjs(v).format('MM-DD') : '-') },
      ],
      records: activeOrders,
      onRowClick: (r) => navigate(`/work-orders/${r.id}`),
    }),
    equip: (): DrillConfig => ({
      title: '设备稼动率 · 追溯',
      headline: `${equipmentUtilization}%`,
      formula: `运行 ${runningEquipment} ÷ 总 ${equipment.length} = ${equipmentUtilization}%`,
      columns: [
        { title: '设备编码', dataIndex: 'equipment_code', key: 'code', width: 140 },
        { title: '设备名称', dataIndex: 'equipment_name', key: 'name' },
        {
          title: '状态', dataIndex: 'status', key: 'status', width: 100,
          render: (s: string) => { const i = EQUIPMENT_STATUS[s] || { color: '#8c8c8c', text: s }; return <Tag color={i.color}>{i.text}</Tag> },
        },
      ],
      records: equipment,
      onRowClick: (r) => setEquipDetail(r),
    }),
  }

  const woColumns = [
    {
      title: '工单号', dataIndex: 'work_order_code', key: 'code',
      render: (text: string, record: WorkOrder) => (
        <Link to={`/work-orders/${record.id}`} style={{ fontWeight: 500 }}>{text}</Link>
      ),
    },
    { title: '产品', dataIndex: 'product_id', key: 'product', render: (v: string) => productLabel(v) },
    {
      title: '进度', key: 'progress', width: 140,
      render: (_: any, r: WorkOrder) => (
        <Progress
          percent={r.planned_qty > 0 ? Math.round(r.completed_qty / r.planned_qty * 100) : 0}
          size="small"
        />
      ),
    },
    {
      title: '良品/不良', key: 'quality', width: 100,
      render: (_: any, r: WorkOrder) => (
        <span>
          <span style={{ color: '#52c41a' }}>{r.good_qty}</span> / <span style={{ color: '#faad14' }}>{r.defect_qty}</span>
        </span>
      ),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => {
        const info = STATUS_MAP[s] || { color: 'default', text: s }
        return <Tag color={info.color}>{info.text}</Tag>
      },
    },
    {
      title: '交期', dataIndex: 'planned_due', key: 'due', width: 100,
      render: (v: string) => {
        if (!v) return '-'
        const overdue = dayjs(v).isBefore(dayjs())
        return <span style={{ color: overdue ? '#f5222d' : undefined }}>{dayjs(v).format('MM-DD')}</span>
      },
    },
  ]

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col><h2 style={{ margin: 0 }}>生产看板</h2></Col>
        <Col style={{ color: '#8c8c8c', fontSize: 13 }}>
          厂区 {factoryId} · {dayjs().format('YYYY-MM-DD ddd')}
        </Col>
      </Row>

      <Spin spinning={loading}>
        {/* 统计卡片：可点击下钻到构成该数字的原始记录 */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small" hoverable onClick={() => setDrill(kpiDrills.output())}>
              <Statistic
                title="今日良品产出" value={todayOutput} suffix="件"
                valueStyle={{ color: '#1890ff' }}
                prefix={<RiseOutlined />}
              />
              <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>今日报工 {todayReports.length} 次 · 点击追溯</div>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" hoverable onClick={() => setDrill(kpiDrills.yieldKpi())}>
              <Statistic
                title="今日良品率" value={yieldRate} suffix="%"
                valueStyle={{ color: Number(yieldRate) >= 98 ? '#52c41a' : '#faad14' }}
                prefix={<CheckCircleOutlined />}
              />
              <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>不良 {todayDefect} 件 · 点击追溯</div>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" hoverable onClick={() => setDrill(kpiDrills.orders())}>
              <Statistic
                title="在制工单" value={activeOrders.length} suffix="个"
                valueStyle={{ color: '#722ed1' }}
                prefix={<ToolOutlined />}
              />
              <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>总工单 {workOrders.length} 个 · 点击追溯</div>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" hoverable onClick={() => setDrill(kpiDrills.equip())}>
              <Statistic
                title="设备稼动率" value={equipmentUtilization} suffix="%"
                valueStyle={{ color: equipmentUtilization >= 60 ? '#52c41a' : '#faad14' }}
                prefix={<AlertOutlined />}
              />
              <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>运行 {runningEquipment} / {equipment.length} 台 · 点击追溯</div>
            </Card>
          </Col>
        </Row>

        <Row gutter={16}>
          {/* 在制工单 */}
          <Col span={14}>
            <Card title="在制工单" size="small" extra={<Link to="/work-orders">查看全部</Link>}>
              <Table
                columns={woColumns}
                dataSource={activeOrders.slice(0, 8).map((wo, i) => ({ ...wo, key: wo.id || i }))}
                pagination={false}
                size="small"
              />
            </Card>
          </Col>

          <Col span={10}>
            {/* 最近报工 */}
            <Card title="最近报工" size="small" style={{ marginBottom: 16 }} extra={<Link to="/production-report">更多</Link>}>
              <List
                size="small"
                dataSource={reports.slice(0, 5)}
                renderItem={(r) => (
                  <List.Item style={{ padding: '6px 0', cursor: 'pointer' }} onClick={() => setReportDetail(r)}>
                    <span style={{ fontWeight: 500 }}>{r.report_code}</span>
                    <span style={{ color: '#8c8c8c', margin: '0 8px' }}>{stationLabel(r.station_id)}</span>
                    <Tag color="green" style={{ margin: 0 }}>良 {r.good_qty}</Tag>
                    {r.defect_qty > 0 && <Tag color="orange" style={{ marginLeft: 4 }}>不良 {r.defect_qty}</Tag>}
                    <span style={{ marginLeft: 'auto', color: '#8c8c8c', fontSize: 12 }}>
                      {dayjs(r.created_at).format('HH:mm')}
                    </span>
                  </List.Item>
                )}
              />
            </Card>

            {/* 设备状态 */}
            <Card title="设备状态" size="small" extra={<Link to="/base-data">更多</Link>}>
              <List
                size="small"
                dataSource={equipment.slice(0, 5)}
                renderItem={(e) => {
                  const info = EQUIPMENT_STATUS[e.status] || { color: '#8c8c8c', text: e.status }
                  return (
                    <List.Item style={{ padding: '6px 0', cursor: 'pointer' }} onClick={() => setEquipDetail(e)}>
                      <span style={{ fontWeight: 500 }}>{e.equipment_code}</span>
                      <span style={{ color: '#8c8c8c', margin: '0 8px' }}>{e.equipment_name}</span>
                      <span style={{ marginLeft: 'auto' }}>
                        <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: info.color, marginRight: 6 }} />
                        {info.text}
                      </span>
                    </List.Item>
                  )
                }}
              />
            </Card>
          </Col>
        </Row>
      </Spin>

      {/* ==================== 仿真结果看板（独立分区，与真实生产数据严格分离） ==================== */}
      <Card
        size="small"
        style={{ marginTop: 16, border: '1px dashed #722ed1', background: 'linear-gradient(180deg, #faf5ff 0%, #ffffff 60%)' }}
        title={
          <span>
            <ExperimentOutlined style={{ color: '#722ed1', marginRight: 6 }} />
            仿真结果看板
            <Tag color="purple" style={{ marginLeft: 8 }}>仿真数据</Tag>
            <Tag color="default">与实时生产分离</Tag>
          </span>
        }
        extra={
          <Link to="/simulation">查看完整仿真 →</Link>
        }
      >
        <Spin spinning={simLoading}>
          {simSummary ? (
            <SimSummaryView summary={simSummary} pct={pct} />
          ) : (
            !simLoading && <div style={{ color: '#8c8c8c', textAlign: 'center', padding: 24 }}>暂无仿真数据，请前往「仿真引擎」运行场景</div>
          )}
        </Spin>
      </Card>

      {/* 追溯：KPI 数字下钻抽屉 */}
      {drill && (
        <DrillDownDrawer
          open
          onClose={() => setDrill(null)}
          title={drill.title}
          headline={drill.headline}
          formula={drill.formula}
          columns={drill.columns}
          records={drill.records}
          onRowClick={drill.onRowClick}
        />
      )}

      {/* 追溯：报工原始记录详情 */}
      <RecordDetailDrawer
        open={!!reportDetail}
        onClose={() => setReportDetail(null)}
        title="报工原始记录"
        record={reportDetail}
        fields={reportFields}
        extra={reportDetail?.is_modified ? <Tag color="orange">已修改</Tag> : <Tag>未修改</Tag>}
      />

      {/* 追溯：设备详情 */}
      <RecordDetailDrawer
        open={!!equipDetail}
        onClose={() => setEquipDetail(null)}
        title="设备详情"
        record={equipDetail}
        fields={equipFields}
      />
    </div>
  )
}

export default Dashboard
