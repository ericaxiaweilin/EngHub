import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  InputNumber,
  List,
  Progress,
  Select,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  ApartmentOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  ReloadOutlined,
  RocketOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../../services/api'
import { getWorkOrders, type WorkOrder } from '../../services/mes'
import { getActiveFactoryId } from '../../utils/factory'
import RushOrderApprovals from './RushOrderApprovals'

const { Text, Title, Paragraph } = Typography

interface PmcOptionDefinition {
  group: string
  key: string
  label: string
  type: 'boolean' | 'select' | 'number'
  options?: Array<{ value: string; label: string }>
  min?: number
  max?: number
  step?: number
  unit?: string
  description?: string
  business_talk?: string
}

const STATUS_META: Record<string, { label: string; color: string }> = {
  ready_for_mps: { label: '可进入 MPS 草案', color: 'success' },
  conditional: { label: '条件放行', color: 'warning' },
  blocked: { label: '阻塞', color: 'error' },
  needs_evidence: { label: '需要补证据', color: 'processing' },
  ready: { label: '已就绪', color: 'success' },
  missing: { label: '缺失', color: 'error' },
  unknown: { label: '待确认', color: 'default' },
  warning: { label: '需关注', color: 'warning' },
}

const SCENARIO_GROUP_META: Record<string, { code: string; color: string; caption: string }> = {
  '时间锤': { code: 'T', color: '#1677ff', caption: '日历 / 班次' },
  '物料锤': { code: 'M', color: '#722ed1', caption: 'IQC / 供应' },
  '生产锤': { code: 'P', color: '#13a8a8', caption: '良率 / 产能' },
  '出货锤': { code: 'S', color: '#d46b08', caption: '装柜 / 关务' },
  '紧急锤': { code: 'E', color: '#cf1322', caption: '加急 / 外协' },
}

const valueText = (value: unknown, unit?: string) => {
  if (value === null || value === undefined || value === '') return '-'
  return `${String(value)}${unit ? ` ${unit}` : ''}`
}

export default function PmcWorkbench() {
  const navigate = useNavigate()
  const factoryId = getActiveFactoryId()
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])
  const [selectedCode, setSelectedCode] = useState('')
  const [matrix, setMatrix] = useState<any>(null)
  const [capabilities, setCapabilities] = useState<any[]>([])
  // 现场规则与执行：候选规律要人点头才生效，做法要能被核对 —— 这两件事都在这一栏里
  const [ruleFlow, setRuleFlow] = useState<any>(null)
  const [ruleBusy, setRuleBusy] = useState('')
  const [priority, setPriority] = useState<any>(null)
  const [answer, setAnswer] = useState<Record<string, string>>({})
  const [options, setOptions] = useState<Record<string, any>>({})
  const [ordersLoading, setOrdersLoading] = useState(true)
  const [matrixLoading, setMatrixLoading] = useState(false)
  const [recalculating, setRecalculating] = useState(false)
  const [error, setError] = useState('')
  const [attendance, setAttendance] = useState<any>(null)

  const loadMatrix = useCallback(async (workOrderCode: string) => {
    if (!workOrderCode) return
    setMatrixLoading(true)
    setError('')
    try {
      const response: any = await api.get('/api/v1/pmc/work-matrix', {
        params: { factory_id: factoryId, work_order_code: workOrderCode },
      })
      if (response?.error) {
        setMatrix(null)
        setOptions({})
        setError(response.hint || response.error)
        return
      }
      setMatrix(response)
      setOptions(response.options || {})
    } catch (err: any) {
      setMatrix(null)
      setError(err?.response?.data?.detail || 'PMC 工作矩阵加载失败')
    } finally {
      setMatrixLoading(false)
    }
  }, [factoryId])

  const loadOrders = useCallback(async () => {
    setOrdersLoading(true)
    try {
      const response = await getWorkOrders({ factory_id: factoryId, page: 1, page_size: 100 })
      const candidates = (response.items || []).filter((item) => item.wo_type !== 'operation')
      setWorkOrders(candidates)
      const nextCode = candidates[0]?.work_order_code || ''
      setSelectedCode(nextCode)
      if (nextCode) await loadMatrix(nextCode)
    } catch {
      setWorkOrders([])
      setMatrix(null)
      setError('工单列表加载失败，请检查工厂权限或工单接口。')
    } finally {
      setOrdersLoading(false)
    }
  }, [factoryId, loadMatrix])

  const loadRuleFlow = useCallback(async () => {
    try {
      const [q, e]: any = await Promise.all([
        api.get('/api/v1/pmc/open-rule-questions', { params: { factory_id: factoryId } }),
        api.get('/api/v1/pmc/execution-events', { params: { factory_id: factoryId, days: 30 } }),
      ])
      const pr: any = await api.get('/api/v1/pmc/measurement-priority', {
        params: { factory_id: factoryId, units: 1200 } })
      setRuleFlow({ questions: q?.open_questions || [], pending: q?.pending_candidates || [],
                   census: q?.workforce_census || null, events: e?.events || [] })
      setPriority({ parts: pr?.total_parts_in_critical_tiers ?? null,
                    ratio: pr?.calibration?.median_ratio ?? null,
                    n: pr?.calibration?.n_materials ?? 0,
                    per_model: (pr?.per_model || []).slice(0, 4) })
    } catch {
      setRuleFlow({ error: '规则与执行读数加载失败' })
    }
  }, [factoryId])

  const decideRule = useCallback(async (ruleId: string, agree: boolean) => {
    setRuleBusy(ruleId)
    try {
      const r: any = await api.post('/api/v1/pmc/confirm-rule', {
        factory_id: factoryId, rule_id: ruleId, agree,
      })
      if (r?.error) message.error(r.error)
      else message.success(agree ? '这条规律已升为正式规则，引擎下一轮起按它过滤候选动作'
                                 : '已驳回，记录留着，不再反复问')
      await loadRuleFlow()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '确认失败')
    } finally {
      setRuleBusy('')
    }
  }, [factoryId, loadRuleFlow])

  const answerQuestion = useCallback(async (action: string, verdict: 'allowed' | 'forbidden') => {
    const text = (answer[action] || '').trim()
    if (!text) { message.warning('先写一句现场的说法（含条件），再定允许或禁止'); return }
    setRuleBusy(`q:${action}`)
    try {
      const r: any = await api.post('/api/v1/pmc/factory-rules', {
        factory_id: factoryId, subject: action, verdict, statement: text,
        status: 'declared', source: 'human_ui',
      })
      if (r?.error) { message.error(r.error); return }
      message.success('已落成厂规，引擎下一轮推演就按它过滤候选动作')
      await loadRuleFlow()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '登记失败')
    } finally {
      setRuleBusy('')
    }
  }, [answer, factoryId, loadRuleFlow])

  const loadCapabilities = useCallback(async () => {
    try {
      const response: any = await api.get('/api/v1/pmc/capabilities')
      setCapabilities(response?.capabilities || [])
    } catch {
      // 工作台仍可由工单矩阵运行；能力清单加载失败不掩盖主评审结果。
      setCapabilities([])
    }
  }, [])

  const loadAttendance = useCallback(async () => {
    try {
      const response: any = await api.get('/api/v1/pmc/expected-attendance', {
        params: { factory_id: factoryId },
      })
      setAttendance(response)
    } catch {
      // 取不到依据就不在界面上装成有数：宁可这一栏不出现。
      setAttendance(null)
    }
  }, [factoryId])

  useEffect(() => { loadOrders() }, [loadOrders])
  useEffect(() => { loadCapabilities() }, [loadCapabilities])
  useEffect(() => { loadRuleFlow() }, [loadRuleFlow])
  useEffect(() => { loadAttendance() }, [loadAttendance])

  const recalculate = async () => {
    if (!selectedCode) return
    setRecalculating(true)
    try {
      const response: any = await api.post('/api/v1/pmc/work-matrix/scenario', {
        factory_id: factoryId,
        work_order_code: selectedCode,
        options,
      })
      if (response?.error) {
        throw new Error(response.hint || response.error)
      }
      setMatrix(response)
      setOptions(response.options || options)
      message.success('PMC 沙盘已按当前参数重算')
    } catch (err: any) {
      message.error(err?.response?.data?.detail || 'PMC 沙盘重算失败')
    } finally {
      setRecalculating(false)
    }
  }

  const chooseRandomOrder = () => {
    if (!workOrders.length) return
    const pool = workOrders.filter((item) => item.work_order_code !== selectedCode)
    const target = (pool.length ? pool : workOrders)[Math.floor(Math.random() * (pool.length || workOrders.length))]
    setSelectedCode(target.work_order_code)
    loadMatrix(target.work_order_code)
  }

  const optionSchema: PmcOptionDefinition[] = matrix?.option_schema || []
  const optionGroups = useMemo(
    () => Array.from(new Set(optionSchema.map((item) => item.group))),
    [optionSchema],
  )
  const optionsByGroup = useMemo(
    () => Object.fromEntries(optionGroups.map((group) => [group, optionSchema.filter((item) => item.group === group)])),
    [optionGroups, optionSchema],
  )
  const parameters = matrix?.parameters || []
  const parameterMap = useMemo(
    () => Object.fromEntries(parameters.map((item: any) => [item.key, item])),
    [parameters],
  )
  const judgement = matrix?.judgement || {}
  const status = STATUS_META[judgement.overall] || { label: judgement.overall || '等待评审', color: 'default' }
  const kitRate = Number(parameterMap.inventory_kit_rate?.value || 0)

  const renderOption = (definition: PmcOptionDefinition, compact = false) => {
    const value = options[definition.key]
    if (definition.type === 'boolean') {
      return <Switch checked={Boolean(value)} onChange={(next) => setOptions((current) => ({ ...current, [definition.key]: next }))} />
    }
    if (definition.type === 'select') {
      return (
        <Select
          value={value}
          style={{ width: compact ? '100%' : undefined, minWidth: compact ? undefined : 150 }}
          options={definition.options || []}
          onChange={(next) => setOptions((current) => ({ ...current, [definition.key]: next }))}
        />
      )
    }
    const isYield = definition.key === 'yield_rate'
    const numericValue = isYield ? Math.round(Number(value ?? 0.97) * 100) : Number(value ?? definition.min ?? 0)
    return (
      <InputNumber
        style={compact ? { width: '100%' } : undefined}
        value={numericValue}
        min={isYield ? Math.round(Number(definition.min ?? 0.5) * 100) : definition.min}
        max={isYield ? Math.round(Number(definition.max ?? 1) * 100) : definition.max}
        step={isYield ? 1 : definition.step}
        addonAfter={isYield ? '%' : definition.unit}
        onChange={(next) => setOptions((current) => ({
          ...current,
          [definition.key]: isYield ? Number(next || 0) / 100 : Number(next || 0),
        }))}
      />
    )
  }

  const applyScenarioPreset = (preset: 'baseline' | 'protect_delivery' | 'cost_control') => {
    const baseline = matrix?.options || {}
    if (preset === 'baseline') {
      setOptions(baseline)
      message.info('已恢复接口返回的基准假设')
      return
    }
    setOptions({
      ...baseline,
      ...options,
      ...(preset === 'protect_delivery'
        ? { shift_mode: 'double', yield_rate: 0.97, line_occupancy: 'exclusive', container_hours: 2, customs_mode: 'none' }
        : { shift_mode: 'single', yield_rate: 0.97, line_occupancy: 'shared_50', enable_air_freight: false, accept_subcontracting: false }),
    })
    message.info(preset === 'protect_delivery' ? '已载入“保交付”沙盘假设，请点击重算确认影响' : '已载入“控成本”沙盘假设，请点击重算确认影响')
  }

  const parameterColumns = [
    { title: '参数', dataIndex: 'label', key: 'label', width: 190, render: (value: string) => <Text strong>{value}</Text> },
    { title: '当前值', dataIndex: 'value', key: 'value', width: 180, render: (value: unknown, row: any) => valueText(value, row.unit) },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (value: string) => <Tag color={(STATUS_META[value] || { color: 'default' }).color}>{(STATUS_META[value] || { label: value }).label}</Tag>,
    },
    { title: '数据来源', dataIndex: 'source', key: 'source', ellipsis: true },
  ]

  const materialColumns = [
    { title: '物料', dataIndex: 'material_code', key: 'material_code', width: 150, render: (value: string) => <Text code>{value}</Text> },
    { title: '需求', dataIndex: 'required_qty', key: 'required_qty', align: 'right' as const },
    { title: '合格可用', dataIndex: 'qualified_available_qty', key: 'qualified_available_qty', align: 'right' as const },
    { title: '在途', dataIndex: 'in_transit_qty', key: 'in_transit_qty', align: 'right' as const },
    { title: '未收 PO', dataIndex: 'on_order_qty', key: 'on_order_qty', align: 'right' as const },
    { title: '预计缺口', dataIndex: 'projected_shortage_qty', key: 'projected_shortage_qty', align: 'right' as const, render: (value: number) => value > 0 ? <Tag color="error">{value}</Tag> : <Tag color="success">0</Tag> },
    { title: '供应商 LT', dataIndex: 'supplier_lead_days', key: 'supplier_lead_days', render: (value: number, row: any) => (
      <Space size={4}>
        <Tooltip title={value != null ? '来自供应商报价/绑定表' : (row?.ledger_lead_time_days != null ? `供应商报价没有这个件，显示台账 materials.lead_time_days=${row.ledger_lead_time_days} 天` : '供应商报价与台账都没有这个件的提前期')}>
          <span>{value != null ? `${value} 天` : (row?.ledger_lead_time_days != null ? `${row.ledger_lead_time_days} 天(台账)` : '-')}</span>
        </Tooltip>
        {row?.lead_evidence === 'unverified_default' && <Tooltip title={`台账写 ${row?.ledger_lead_time_days ?? '-'} 天，但同组几十~几千个料号共用这一个取值，且没有一条实测到货（判据在 core/mes/data_evidence）`}><Tag color="volcano">没量过</Tag></Tooltip>}
        {row?.lead_evidence === 'no_ledger_row' && <Tooltip title="台账 materials 里没有这个料号，提前期无从可取"><Tag color="volcano">无台账</Tag></Tooltip>}
        {row?.lead_evidence === 'ledger_default_conflicts_with_measured' && <Tooltip title={`台账 ${row?.ledger_lead_time_days ?? '-'} 天，但采购实测中位 ${row?.lead_measured_median_days} 天（${row?.lead_measured_n} 单）；建议按 ${row?.lead_suggested_days} 天去核对`}><Tag color="error">实测 {row?.lead_measured_median_days} 天</Tag></Tooltip>}
        {(row?.lead_evidence === 'measured' || row?.lead_evidence === 'measured_over_default') && <Tooltip title={`${row?.lead_measured_n} 单采购实测，中位 ${row?.lead_measured_median_days} 天`}><Tag color="green">实测 {row?.lead_measured_median_days} 天</Tag></Tooltip>}
        {row?.lead_evidence === 'evidence_query_failed' && <Tooltip title="提前期出处普查本次查询失败，这一轮不知道出处"><Tag color="orange">出处未知</Tag></Tooltip>}
      </Space>
    ) },
  ]

  const capacityColumns = [
    { title: '工位', dataIndex: 'station_id', key: 'station_id', width: 150, render: (value: string) => <Text code>{value}</Text> },
    { title: '名称', dataIndex: 'station_name', key: 'station_name' },
    { title: '可加工时间', dataIndex: 'available_machining_hours', key: 'available_machining_hours', render: (value: number) => `${value || 0} h` },
    { title: '需求工时', dataIndex: 'required_hours', key: 'required_hours', render: (value: number) => value == null ? '-' : `${value} h` },
    { title: '利用率', dataIndex: 'utilization_pct', key: 'utilization_pct', width: 170, render: (value: number) => value == null ? '-' : <Progress percent={Math.min(value, 100)} size="small" status={value > 100 ? 'exception' : 'normal'} format={() => `${value}%`} /> },
    { title: '结论', dataIndex: 'status', key: 'status', render: (value: string) => <Tag color={value === 'overloaded' ? 'error' : value === 'available' ? 'success' : 'default'}>{value === 'overloaded' ? '超载' : value === 'available' ? '可用' : '待确认'}</Tag> },
  ]

  return (
    <div className="pmc-workbench-shell" style={{ minHeight: '100%', background: '#f5f7fb', padding: 24 }}>
      <div style={{ width: '100%', maxWidth: 1480, margin: '0 auto' }}>
        <div style={{ background: 'linear-gradient(135deg, #0b1f33 0%, #123e63 58%, #1677ff 130%)', borderRadius: 14, padding: '22px 24px', marginBottom: 16, color: '#fff' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
            <div>
              <Space size={8} wrap><Tag color="cyan" style={{ margin: 0, border: 0 }}>PMC WORKBENCH</Tag><Tag style={{ margin: 0 }}>工厂 {factoryId}</Tag></Space>
              <Title level={2} style={{ color: '#fff', margin: '10px 0 4px' }}>生产与物料控制工作台</Title>
              <Text style={{ color: 'rgba(255,255,255,.72)' }}>以工单为主线，把需求、RDD、物料、产能、风险和下一步交付物闭环。</Text>
            </div>
            <Space wrap>
              <Button ghost icon={<ApartmentOutlined />} onClick={() => navigate('/work-orders')}>工单中心</Button>
              <Button ghost icon={<FileSearchOutlined />} onClick={() => navigate('/pmc/forms')}>PMC 表单中心</Button>
              <Button ghost icon={<ThunderboltOutlined />} onClick={() => document.getElementById('rush-approval-anchor')?.scrollIntoView({ behavior: 'smooth' })}>插单审批</Button>
              <Button ghost icon={<ReloadOutlined />} onClick={loadOrders} loading={ordersLoading}>刷新数据</Button>
              <Button type="primary" icon={<ExperimentOutlined />} onClick={() => navigate('/pmc/position-trainer')}>职位训练器</Button>
            </Space>
          </div>
        </div>

        <Card size="small" style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <Text strong>当前评审工单</Text>
            <Select
              showSearch
              optionFilterProp="label"
              value={selectedCode || undefined}
              loading={ordersLoading}
              placeholder="选择工单"
              style={{ minWidth: 330, flex: '0 1 500px' }}
              options={workOrders.map((item) => ({ value: item.work_order_code, label: `${item.work_order_code} · ${item.product_id} · ${item.planned_qty} ${item.unit || ''}` }))}
              onChange={(code) => { setSelectedCode(code); loadMatrix(code) }}
            />
            <Button icon={<RocketOutlined />} disabled={!workOrders.length} onClick={chooseRandomOrder}>随机一张真实工单</Button>
            <Text type="secondary">参数来自接口；缺数据明确标记，不用虚构值补齐。</Text>
          </div>
        </Card>

        {attendance && (
          <Card size="small" style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
              <Text strong>今日预计出勤</Text>
              <Text>在册 <Text strong>{attendance.roster_active}</Text> 人</Text>
              <Text>预计到岗 <Text strong style={{ color: '#1677ff' }}>{attendance.expected_present}</Text> 人</Text>
              <Text>缺勤 <Text strong style={{ color: '#d4380d' }}>{attendance.expected_absent}</Text> 人</Text>
              <Tag color={attendance.weather?.condition === 'storm' ? 'red' : attendance.weather?.condition === 'rain' ? 'orange' : 'green'}>
                {attendance.weather?.condition === 'storm' ? '暴雨 70%' : attendance.weather?.condition === 'rain' ? '雨 92%' : '好天 97%'}
              </Tag>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {attendance.basis}
                {(attendance.real_attendance?.stale_days ?? 0) > 7
                  ? ` · 现场打卡表已 ${attendance.real_attendance.stale_days} 天没更新，这里不是打卡实测`
                  : ''}
              </Text>
            </div>
            <Tooltip title={attendance.verdict}>
              <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 6 }}>
                排产的人力项与闲置台账都按这一栏折算（人没来不算空闲产能）
              </Text>
            </Tooltip>
          </Card>
        )}

        {(ordersLoading || matrixLoading) && <Card><div style={{ minHeight: 240, display: 'grid', placeItems: 'center' }}><Spin tip="正在汇总 PMC 评审证据" /></div></Card>}
        {!ordersLoading && !matrixLoading && error && <Alert type="error" showIcon message="PMC 工作台未形成闭环" description={error} action={<Button onClick={() => selectedCode ? loadMatrix(selectedCode) : loadOrders()}>重试</Button>} />}
        {!ordersLoading && !matrixLoading && !error && !matrix && <Card><Empty description="当前工厂没有可评审的主工单" /></Card>}

        {!ordersLoading && !matrixLoading && matrix && <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 12, marginBottom: 16 }}>
            <Card size="small"><Statistic title="需求数量" value={parameterMap.demand_qty?.value ?? '-'} suffix={parameterMap.demand_qty?.unit} /></Card>
            <Card size="small"><Statistic title="RDD / 需求交期" value={String(parameterMap.rdd?.value || '-').slice(0, 10)} valueStyle={{ fontSize: 22 }} /></Card>
            <Card size="small"><Statistic title="库存齐套率" value={parameterMap.inventory_kit_rate?.value ?? '-'} suffix="%" valueStyle={{ color: kitRate < 100 ? '#d46b08' : '#389e0d' }} /></Card>
            <Card size="small"><Statistic title="可加工时间" value={parameterMap.available_machining_hours?.value ?? '-'} suffix="h" /></Card>
            <Card size="small"><Statistic title="预计 ETA" value={String(parameterMap.estimated_eta?.value || '-').replace('T', ' ').slice(0, 16)} valueStyle={{ color: judgement.rdd_feasible === false ? '#cf1322' : '#0958d9', fontSize: 20 }} /></Card>
          </div>

          {!!capabilities.length && <Card size="small" title="PMC 流程能力清单" extra={<Tag color="blue">{capabilities.length} 个接口能力</Tag>} style={{ marginBottom: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 8 }}>
              {capabilities.map((item) => <div key={item.key} style={{ padding: '9px 10px', border: '1px solid #edf2f7', borderRadius: 8, background: '#fafcff' }}>
                <Space size={6}><Tag color={item.mode === 'simulation' ? 'purple' : item.mode === 'training' ? 'cyan' : 'blue'}>{item.mode === 'simulation' ? '沙盘' : item.mode === 'training' ? '训练' : '证据'}</Tag><Text strong>{item.name}</Text></Space>
                <Text type="secondary" style={{ display: 'block', marginTop: 5, fontSize: 12 }}>{item.path}</Text>
              </div>)}
            </div>
          </Card>}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 360px), 1fr))', gap: 16, marginBottom: 16 }}>
          {!!ruleFlow && (
          <Card size="small" style={{ marginBottom: 16 }}
            title={<Space><SafetyCertificateOutlined />现场规则与执行</Space>}
            extra={<Tag color={(ruleFlow.pending || []).length ? 'volcano' : 'default'}>
              待确认 {(ruleFlow.pending || []).length} 条 · 近 30 天执行 {(ruleFlow.events || []).length} 次
            </Tag>}>
            {(ruleFlow.error || '') && <Text type="danger">{ruleFlow.error}</Text>}
            {(ruleFlow.pending || []).length === 0 && (ruleFlow.questions || []).length === 0 && (
              <Text type="secondary">没有待确认的候选规律，也没有空白规则要问现场。</Text>
            )}
            {(ruleFlow.pending || []).length > 0 && (
              <List size="small" dataSource={ruleFlow.pending} rowKey={(r: any) => r.rule_id}
                renderItem={(r: any) => (
                  <List.Item actions={[
                    <Button key="ok" size="small" type="link" disabled={ruleBusy === r.rule_id}
                      onClick={() => decideRule(r.rule_id, true)}>同意设为规则</Button>,
                    <Button key="no" size="small" type="link" danger disabled={ruleBusy === r.rule_id}
                      onClick={() => decideRule(r.rule_id, false)}>驳回</Button>,
                  ]}>
                    <Space direction="vertical" size={0}>
                      <Text>{r.statement || `${r.subject} → ${r.verdict}`}</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        来源 {r.source === 'pattern_mining' ? '决策台账挖掘' : r.source === 'derived' ? '从花名册/技能台账推算' : r.source}
                        · 依据 {JSON.stringify(r.evidence || {}).slice(0, 90)}
                      </Text>
                    </Space>
                  </List.Item>
                )} />
            )}
            {!!priority && (
              <div style={{ marginTop: 8 }}>
                <Text strong style={{ fontSize: 12 }}>该先量的件（按决定开工日那一档给，不是一个点）</Text>
                <div><Text type="secondary" style={{ fontSize: 12 }}>
                  临界档合计 {priority.parts} 个料号 · 校准比 {priority.ratio ?? '—'}×
                  （{priority.n} 个料号有采购实测；没有实测时这个倍数只是量级演示）
                </Text></div>
                {(priority.per_model || []).map((p: any) => (
                  <div key={p.model_code}><Text type="secondary" style={{ fontSize: 12 }}>
                    {p.model_code}：第 {p.critical_tier_days ?? '—'} 天那一档 {p.critical_part_count ?? 0} 个件
                    · 量出来值 {p.swing_days_if_measured ?? '—'} 天（{p.baseline_finish ?? '—'} → {p.stressed_finish ?? '—'}）
                  </Text></div>
                ))}
              </div>
            )}
            {(ruleFlow.questions || []).length > 0 && (
              <div style={{ marginTop: 8 }}>
                <Text strong style={{ fontSize: 12 }}>还没写规则的 —— 当场答一句就成厂规（引擎立刻按它过滤）</Text>
                {(ruleFlow.questions || []).map((q: any, i: number) => (
                  <div key={i} style={{ marginTop: 6 }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>• {q.question}</Text>
                    <Space.Compact style={{ width: '100%', marginTop: 2 }}>
                      <Input size="small" placeholder="现场的说法，例如：暴雨也不许外发，必须内部消化"
                        value={answer[q.action] || ''}
                        onChange={(ev: any) => setAnswer((prev: any) => ({ ...prev, [q.action]: ev.target.value }))} />
                      <Button size="small" loading={ruleBusy === `q:${q.action}`}
                        onClick={() => answerQuestion(q.action, 'allowed')}>允许</Button>
                      <Button size="small" danger loading={ruleBusy === `q:${q.action}`}
                        onClick={() => answerQuestion(q.action, 'forbidden')}>禁止</Button>
                    </Space.Compact>
                  </div>
                ))}
              </div>
            )}
            {(ruleFlow.events || []).length > 0 && (
              <div style={{ marginTop: 8 }}>
                <Text strong style={{ fontSize: 12 }}>最近的现场执行（用来核对厂规有没有被超出）</Text>
                {(ruleFlow.events || []).slice(0, 5).map((e: any) => (
                  <div key={e.id}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {String(e.at || '').slice(0, 16)} · {e.action} · {e.line_code || e.section || '-'}
                      {e.hours ? ` · ${e.hours}h` : ''}{e.people ? ` · ${e.people}人` : ''} · 记录人 {e.actor}
                    </Text>
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

          <Card size="small" title={<Space><FileSearchOutlined />评审判断标准</Space>} extra={<Tag color={status.color}>{status.label}</Tag>}>
              <List size="small" dataSource={[
                ['RDD', judgement.rdd_present ? (judgement.rdd_feasible === false ? 'ETA 晚于 RDD' : '已提供且可评估') : '缺少 RDD'],
                ['物料', judgement.material_ready === true ? '库存齐套' : judgement.projected_material_ready === true ? '依赖 PO/在途条件齐套' : '存在缺口'],
                ['产能', judgement.capacity_feasible === true ? '可加工时间满足' : judgement.capacity_feasible === false ? '产能超载' : '缺少产能证据'],
                ['日历', matrix.calendar?.configured ? `${matrix.calendar.code} 已配置` : 'VN 法定工作日历未配置'],
              ]} renderItem={(item: any) => <List.Item><Text strong>{item[0]}</Text><Text type="secondary">{item[1]}</Text></List.Item>} />
            </Card>
            <Card size="small" title={<Space><ThunderboltOutlined />接下来要做什么</Space>}>
              <List size="small" dataSource={matrix.next_focus || []} renderItem={(item: string, index) => <List.Item><Space align="start"><Tag color="blue">{index + 1}</Tag><Text>{item}</Text></Space></List.Item>} />
            </Card>
            <Card size="small" title={<Space><SafetyCertificateOutlined />本节点交付物</Space>}>
              <List size="small" dataSource={matrix.deliverables || []} renderItem={(item: string) => <List.Item><Text>✓ {item}</Text></List.Item>} />
            </Card>
          </div>

          {!!(matrix.risk_flags || []).length && <Alert type="warning" showIcon icon={<WarningOutlined />} message="当前风险与假设" description={<Space direction="vertical" size={2}>{matrix.risk_flags.map((item: string, index: number) => <Text key={index}>• {item}</Text>)}</Space>} style={{ marginBottom: 16 }} />}

          <Card
            size="small"
            title={<Space><ThunderboltOutlined />预排程决策矩阵<Tag color="blue">接口重算 · 不覆盖主数据</Tag></Space>}
            extra={<Space wrap><Button size="small" onClick={() => applyScenarioPreset('baseline')}>基准</Button><Button size="small" onClick={() => applyScenarioPreset('cost_control')}>控成本</Button><Button size="small" onClick={() => applyScenarioPreset('protect_delivery')}>保交付</Button><Button type="primary" icon={<ReloadOutlined />} loading={recalculating} onClick={recalculate}>重算沙盘</Button></Space>}
            style={{ marginBottom: 16 }}
          >
            <Paragraph type="secondary" style={{ margin: '0 0 12px' }}>
              横向比较五类决策杠杆：调整任一单元后，统一通过沙盘接口计算对交期、齐套、产能与出货的影响。
            </Paragraph>
            <div style={{ overflowX: 'auto', border: '1px solid #d9e5f5', borderRadius: 12, background: '#fff' }}>
              <div style={{ minWidth: 1240, display: 'grid', gridTemplateColumns: `repeat(${Math.max(optionGroups.length, 1)}, minmax(0, 1fr))` }}>
                {optionGroups.map((group, index) => {
                  const meta = SCENARIO_GROUP_META[group] || { code: String(index + 1), color: '#1677ff', caption: '预排程假设' }
                  const groupOptions = optionsByGroup[group] || []
                  return <div key={group} style={{ minWidth: 0, borderRight: index < optionGroups.length - 1 ? '1px solid #d9e5f5' : undefined }}>
                    <div style={{ padding: '12px 14px', background: `${meta.color}0d`, borderBottom: `3px solid ${meta.color}` }}>
                      <Space size={8}><span style={{ display: 'inline-grid', placeItems: 'center', width: 24, height: 24, borderRadius: 6, color: '#fff', background: meta.color, fontSize: 12, fontWeight: 700 }}>{meta.code}</span><div><Text strong>{group}</Text><br /><Text type="secondary" style={{ fontSize: 12 }}>{meta.caption} · {groupOptions.length} 项</Text></div></Space>
                    </div>
                    <div style={{ padding: '0 14px' }}>
                      {groupOptions.map((definition, itemIndex) => <div key={definition.key} style={{ padding: '13px 0', minHeight: 126, borderBottom: itemIndex < groupOptions.length - 1 ? '1px solid #edf2f7' : undefined }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
                          <Text strong>{definition.label}</Text>
                          {definition.type === 'boolean' ? renderOption(definition, true) : <span style={{ flex: '0 1 148px' }}>{renderOption(definition, true)}</span>}
                        </div>
                        {definition.description && <Text type="secondary" style={{ display: 'block', fontSize: 12, lineHeight: 1.55 }}>{definition.description}</Text>}
                        {definition.business_talk && <Tooltip title="面试/汇报话术"><Text style={{ display: 'block', marginTop: 6, color: meta.color, fontSize: 12, lineHeight: 1.5 }}>影响提示：{definition.business_talk}</Text></Tooltip>}
                      </div>)}
                    </div>
                  </div>
                })}
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginTop: 12, padding: '10px 12px', background: '#f6faff', borderRadius: 8 }}>
              <Text type="secondary">当前沙盘：{options.shift_mode === 'double' ? '双班 20h' : '单班 10h'} · 良率 {Math.round(Number(options.yield_rate ?? 0.97) * 100)}% · {options.enable_air_freight ? '空运' : '海运'} · {options.accept_subcontracting ? '接受外协' : '不启用外协'}</Text>
              <Text type="secondary">点击“重算沙盘”后，结果会回写到上方 ETA、齐套率和评审结论。</Text>
            </div>
          </Card>

          <Card size="small">
            <Tabs items={[
              { key: 'matrix', label: `参数证据矩阵（${parameters.length}）`, children: <Table rowKey="key" size="small" scroll={{ x: 760 }} pagination={false} columns={parameterColumns} dataSource={parameters} /> },
              { key: 'materials', label: `物料齐套（${matrix.materials?.length || 0}）`, children: <Table rowKey="material_code" size="small" scroll={{ x: 900 }} pagination={{ pageSize: 8 }} columns={materialColumns} dataSource={matrix.materials || []} /> },
              { key: 'capacity', label: `产能证据（${matrix.capacity?.length || 0}）`, children: <Table rowKey="station_id" size="small" scroll={{ x: 850 }} pagination={false} columns={capacityColumns} dataSource={matrix.capacity || []} /> },
            ]} />
          </Card>
        </>}

        <div id="rush-approval-anchor" style={{ marginTop: 16 }}>
          <RushOrderApprovals />
        </div>
      </div>
    </div>
  )
}
