import React, { useEffect, useState, useCallback } from 'react'
import {
  Table, Button, Input, Select, Tag, Space, Card, Modal, Form, InputNumber,
  DatePicker, Progress, message, Row, Col, Tooltip, Badge, Alert,
} from 'antd'
import {
  PlusOutlined, SearchOutlined, ReloadOutlined,
  PlayCircleOutlined, CheckCircleOutlined, StopOutlined, ScissorOutlined,
  PauseCircleOutlined, PlaySquareOutlined, InboxOutlined, WarningOutlined,
  FileTextOutlined, DashboardOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import { Link, useNavigate } from 'react-router-dom'
import dayjs from 'dayjs'
import {
  getWorkOrders, getWorkOrderStats, createWorkOrder, releaseWorkOrder, startWorkOrder,
  pauseWorkOrder, resumeWorkOrder, markPendingInbound, completeWorkOrder, closeWorkOrder,
  cancelWorkOrder, splitWorkOrder, WorkOrder, WorkOrderStats,
} from '../../services/mes'
import { getStoredUser, hasPermission } from '../../services/auth'

const { Option } = Select

const MOCK_WORK_ORDERS: any[] = [
  { id: 'wo-1', work_order_code: 'WO-2026-0701', product_id: 'PRD-001', product_name: '轴承座', quantity: 500, completed_quantity: 320, status: 'in_progress', priority: 'high', wo_type: 'main', factory_id: 'factory-sh-01', planned_start: '2026-07-10', planned_end: '2026-07-25', created_at: '2026-07-08' },
  { id: 'wo-2', work_order_code: 'WO-2026-0702', product_id: 'PRD-002', product_name: '电机外壳', quantity: 1000, completed_quantity: 0, status: 'released', priority: 'medium', wo_type: 'main', factory_id: 'factory-sh-01', planned_start: '2026-07-20', planned_end: '2026-08-05', created_at: '2026-07-15' },
  { id: 'wo-3', work_order_code: 'WO-2026-0703', product_id: 'PRD-003', product_name: 'PCB主板', quantity: 2000, completed_quantity: 2000, status: 'completed', priority: 'urgent', wo_type: 'main', factory_id: 'factory-sh-01', planned_start: '2026-07-01', planned_end: '2026-07-15', created_at: '2026-06-28' },
  { id: 'wo-4', work_order_code: 'WO-2026-0704', product_id: 'PRD-004', product_name: '齿轮箱', quantity: 300, completed_quantity: 0, status: 'pending', priority: 'low', wo_type: 'main', factory_id: 'factory-sh-01', planned_start: '2026-08-01', planned_end: '2026-08-20', created_at: '2026-07-18' },
  { id: 'wo-5', work_order_code: 'WO-2026-0705', product_id: 'PRD-005', product_name: '密封组件', quantity: 800, completed_quantity: 150, status: 'on_hold', priority: 'medium', wo_type: 'main', factory_id: 'factory-sh-01', planned_start: '2026-07-12', planned_end: '2026-07-30', created_at: '2026-07-10' },
]

// ============================================================
// 状态映射（含中文显示、颜色、图标）
// ============================================================
const STATUS_MAP: Record<string, { color: string; text: string; icon?: React.ReactNode }> = {
  draft: { color: 'default', text: '草稿' },
  pending: { color: 'processing', text: '待下发' },
  released: { color: 'blue', text: '已下达' },
  in_progress: { color: 'blue', text: '生产中' },
  on_hold: { color: 'warning', text: '暂停中' },
  pending_inbound: { color: 'cyan', text: '待入库' },
  completed: { color: 'success', text: '已完成' },
  closed: { color: 'default', text: '已关闭' },
  cancelled: { color: 'error', text: '已取消' },
}

const PRIORITY_MAP: Record<string, { color: string; text: string; dotColor: string }> = {
  low: { color: 'default', text: '低', dotColor: '#8c8c8c' },
  medium: { color: 'blue', text: '普通(中)', dotColor: '#1890ff' },
  high: { color: 'orange', text: '紧急(高)', dotColor: '#fa8c16' },
  urgent: { color: 'error', text: '加急(急)', dotColor: '#f5222d' },
}

const STATUS_FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'pending', label: '待下发' },
  { key: 'released', label: '已下达' },
  { key: 'in_progress', label: '生产中' },
  { key: 'on_hold', label: '暂停' },
  { key: 'pending_inbound', label: '待入库' },
  { key: 'completed', label: '完成' },
]

// 行业通用工序代码 -> 中文名称（与后端 work_order_coding.PROCESS_CODES 一致）
const PROCESS_NAME: Record<string, string> = {
  CUT: '下料', MACH: '机加', INJ: '注塑', EDM: '电火花', WCUT: '线切割',
  WELD: '焊接', PAINT: '涂装', ASSY: '组立', PKG: '包装', QC: '检验',
  SMT: '贴片', DIP: '插件', STMP: '冲压', CAST: '铸造', HT: '热处理',
  FIN: '表面处理', GRD: '研磨', SEW: '针车', FORM: '成型', GEN: '通用',
}

// ============================================================
// 操作按钮生成器（根据状态 + 权限动态渲染）
// ============================================================
const renderActionButtons = (record: WorkOrder, actions: any) => {
  const { release, start, pause, resume, inbound, complete, closeWo, cancel, split, detail } = actions
  const btnStyle = { padding: '4px 8px', fontSize: 12 }

  return (
    <Space size={2} wrap>
      {/* 草稿/待下发 → 已下达（后端审核门槛：管理角色 + 非创建人）*/}
      {['draft', 'pending'].includes(record.status) && release && (
        <Tooltip title="下发工单">
          <Button type="primary" size="small" icon={<PlayCircleOutlined />} style={btnStyle} onClick={() => release(record)}>
            下发
          </Button>
        </Tooltip>
      )}

      {/* 已下达 → 生产中 */}
      {record.status === 'released' && start && (
        <Tooltip title="开工">
          <Button type="primary" size="small" icon={<PlayCircleOutlined />} style={btnStyle} onClick={() => start(record)}>
            开工
          </Button>
        </Tooltip>
      )}

      {/* 生产中 → 暂停 / 待入库 / 完工 */}
      {record.status === 'in_progress' && (
        <>
          {pause && (
            <Tooltip title="暂停生产">
              <Button size="small" icon={<PauseCircleOutlined />} style={{ ...btnStyle, borderColor: '#faad14', color: '#faad14' }} onClick={() => pause(record)}>
                暂停
              </Button>
            </Tooltip>
          )}
          {inbound && (
            <Tooltip title="标记待入库">
              <Button size="small" icon={<InboxOutlined />} style={{ ...btnStyle, borderColor: '#1890ff', color: '#1890ff' }} onClick={() => inbound(record)}>
                待入库
              </Button>
            </Tooltip>
          )}
          {complete && (
            <Tooltip title="完工">
              <Button type="primary" size="small" icon={<CheckCircleOutlined />} style={btnStyle} onClick={() => complete(record)}>
                完工
              </Button>
            </Tooltip>
          )}
        </>
      )}

      {/* 暂停 → 恢复 */}
      {record.status === 'on_hold' && resume && (
        <Tooltip title="恢复生产">
          <Button type="primary" size="small" icon={<PlaySquareOutlined />} style={btnStyle} onClick={() => resume(record)}>
            恢复
          </Button>
        </Tooltip>
      )}

      {/* 待入库 → 完成 */}
      {record.status === 'pending_inbound' && complete && (
        <Tooltip title="确认完成">
          <Button type="primary" size="small" icon={<CheckCircleOutlined />} style={btnStyle} onClick={() => complete(record)}>
            完成
          </Button>
        </Tooltip>
      )}

      {/* 已完成 → 关闭 */}
      {record.status === 'completed' && closeWo && (
        <Tooltip title="关闭工单">
          <Button size="small" icon={<DashboardOutlined />} style={{ ...btnStyle, borderColor: '#d9d9d9' }} onClick={() => closeWo(record)}>
            关闭
          </Button>
        </Tooltip>
      )}

      {/* 拆分（草稿/待下发/已下达；拆分后新工单作为子工单挂在当前工单下）*/}
      {['draft', 'pending', 'released'].includes(record.status) && split && (
        <Tooltip title="拆分工单">
          <Button size="small" icon={<ScissorOutlined />} style={{ ...btnStyle, borderColor: '#d9d9d9' }} onClick={() => split(record)}>
            拆分
          </Button>
        </Tooltip>
      )}

      {/* 取消 */}
      {['draft', 'pending', 'released', 'in_progress', 'on_hold'].includes(record.status) && cancel && (
        <Tooltip title="取消工单">
          <Button size="small" danger icon={<StopOutlined />} style={{ ...btnStyle, borderColor: '#ff4d4f', color: '#ff4d4f' }} onClick={() => cancel(record)}>
            取消
          </Button>
        </Tooltip>
      )}

      {/* 详情（始终可见） */}
      {detail && (
        <Tooltip title="查看详情">
          <Button size="small" icon={<FileTextOutlined />} style={{ ...btnStyle, borderColor: '#d9d9d9' }} onClick={() => detail(record)}>
          </Button>
        </Tooltip>
      )}
    </Space>
  )
}

// ============================================================
// 主组件
// ============================================================
const WorkOrderList: React.FC = () => {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<WorkOrder[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [activeFilter, setActiveFilter] = useState('all')
  const [filters, setFilters] = useState<Record<string, any>>({})
  const [stats, setStats] = useState<WorkOrderStats | null>(null)

  // 工序工单下钻缓存（主工单id -> 其工序工单列表）
  const [opsCache, setOpsCache] = useState<Record<string, WorkOrder[]>>({})
  const [opsLoading, setOpsLoading] = useState<Record<string, boolean>>({})

  // Modals
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [splitModalOpen, setSplitModalOpen] = useState(false)
  const [splitTarget, setSplitTarget] = useState<WorkOrder | null>(null)
  const [cancelModalOpen, setCancelModalOpen] = useState(false)
  const [cancelTarget, setCancelTarget] = useState<WorkOrder | null>(null)
  const [cancelReason, setCancelReason] = useState('')
  const [pauseModalOpen, setPauseModalOpen] = useState(false)
  const [pauseTarget, setPauseTarget] = useState<WorkOrder | null>(null)
  const [pauseReason, setPauseReason] = useState('')

  const [form] = Form.useForm()
  const [splitForm] = Form.useForm()

  const user = getStoredUser()
  const factoryId = localStorage.getItem('active_factory_id') || user?.factory_id || 'F01'

  // ---- 权限检查 ----
  const canRelease = hasPermission('work_order', 'release')
  const canStart = hasPermission('work_order', 'start')
  const canPause = hasPermission('work_order', 'edit')
  const canResume = hasPermission('work_order', 'edit')
  const canInbound = hasPermission('work_order', 'edit')
  const canComplete = hasPermission('work_order', 'complete')
  const canClose = hasPermission('work_order', 'approve')
  const canCancel = hasPermission('work_order', 'cancel')
  const canSplit = hasPermission('work_order', 'edit')
  const canViewDetail = hasPermission('work_order', 'view')
  const canCreate = hasPermission('work_order', 'create')

  // ---- 加载数据 ----
  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, any> = {
        factory_id: factoryId,
        page,
        page_size: pageSize,
      }
      if (activeFilter !== 'all') params.status = activeFilter
      if (filters.product_id) params.product_id = filters.product_id
      if (filters.priority) params.priority = filters.priority
      const res = await getWorkOrders(params)
      const items = res.items || []
      setData(items)
      setTotal(res.total ?? items.length)
    } catch (err: any) {
      setData([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [factoryId, page, pageSize, activeFilter, filters])

  const fetchStats = useCallback(async () => {
    try {
      const res = await getWorkOrderStats(factoryId)
      setStats(res)
    } catch {
      // stats 失败不影响主列表
    }
  }, [factoryId])

  // 展开主工单时加载其派生的工序工单
  const loadOperations = useCallback(async (record: WorkOrder) => {
    setOpsLoading(l => ({ ...l, [record.id]: true }))
    try {
      const res = await getWorkOrders({
        factory_id: factoryId,
        wo_type: 'operation',
        parent_work_order_id: record.id,
        page_size: 100,
      })
      setOpsCache(c => ({ ...c, [record.id]: res.items || [] }))
    } catch {
      setOpsCache(c => ({ ...c, [record.id]: [] }))
    } finally {
      setOpsLoading(l => ({ ...l, [record.id]: false }))
    }
  }, [factoryId])

  useEffect(() => { fetchData() }, [fetchData])
  useEffect(() => { fetchStats() }, [fetchStats])

  // ---- 操作处理 ----
  const handleAction = async (action: string, record: WorkOrder, reason?: string) => {
    try {
      switch (action) {
        case 'release': await releaseWorkOrder(record.id); break
        case 'start': await startWorkOrder(record.id); break
        case 'pause': await pauseWorkOrder(record.id, reason); break
        case 'resume': await resumeWorkOrder(record.id, reason); break
        case 'inbound': await markPendingInbound(record.id); break
        case 'complete': await completeWorkOrder(record.id); break
        case 'close': await closeWorkOrder(record.id); break
      }
      message.success('操作成功')
      fetchData()
      fetchStats()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '操作失败')
    }
  }

  const handleCancel = async () => {
    if (!cancelTarget || !cancelReason.trim()) {
      message.warning('请填写取消原因')
      return
    }
    try {
      await cancelWorkOrder(cancelTarget.id, cancelReason)
      message.success('工单已取消')
      setCancelModalOpen(false); setCancelReason(''); setCancelTarget(null)
      fetchData(); fetchStats()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '取消失败')
    }
  }

  const handlePause = async () => {
    if (!pauseTarget || !pauseReason.trim()) {
      message.warning('请填写暂停原因')
      return
    }
    try {
      await pauseWorkOrder(pauseTarget.id, pauseReason)
      message.success('工单已暂停')
      setPauseModalOpen(false); setPauseReason(''); setPauseTarget(null)
      fetchData(); fetchStats()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '暂停失败')
    }
  }

  const handleSplit = async (values: any) => {
    if (!splitTarget) return
    try {
      const result = await splitWorkOrder(splitTarget.id, values.split_qty, values.remark)
      message.success(`拆分成功，新工单: ${result.new_work_order?.work_order_code}`)
      setSplitModalOpen(false); splitForm.resetFields(); setSplitTarget(null)
      fetchData(); fetchStats()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '拆分失败')
    }
  }

  const handleCreate = async (values: any) => {
    try {
      await createWorkOrder({
        factory_id: factoryId,
        product_id: values.product_id,
        planned_qty: values.planned_qty,
        planned_due: values.planned_due.format('YYYY-MM-DDTHH:mm:ss'),
        priority: values.priority || 'medium',
        station_id: values.station_id || undefined,
        bom_version: values.bom_version || undefined,
        remark: values.remark || undefined,
      })
      message.success('工单创建成功')
      setCreateModalOpen(false); form.resetFields(); fetchData(); fetchStats()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '创建失败')
    }
  }

  // ---- 进度条颜色 ----
  const getProgressColor = (record: WorkOrder) => {
    if (record.status === 'completed' || record.status === 'closed') return '#52c41a'
    if (record.is_overdue) return '#f5222d'
    if (record.status === 'on_hold') return '#faad14'
    return '#1890ff'
  }

  // ---- 列定义 ----
  const columns = [
    {
      title: '工单号', dataIndex: 'work_order_code', key: 'code', width: 200, fixed: 'left' as const,
      render: (text: string, record: WorkOrder) => (
        <Space size={4}>
          <Link to={`/work-orders/${record.id}`} style={{ fontWeight: 600, fontFamily: 'monospace', color: '#1890ff' }}>
            {text}
          </Link>
          {record.wo_type === 'operation' && <Tag color="purple" style={{ marginRight: 0 }}>工序</Tag>}
        </Space>
      ),
    },
    {
      title: '产品编码 / 名称', key: 'product', width: 180,
      render: (_: any, r: WorkOrder) => (
        <div>
          <div style={{ fontWeight: 600 }}>{r.product_id}</div>
          <div style={{ fontSize: 12, color: '#8c8c8c' }}>{r.sales_order_id || '-'}</div>
        </div>
      ),
    },
    {
      title: '计划/完成', key: 'qty', width: 130,
      render: (_: any, r: WorkOrder) => (
        <Space direction="vertical" size={0} style={{ width: '100%' }}>
          <span style={{ fontFamily: 'monospace', fontWeight: 600, color: r.status === 'completed' ? '#52c41a' : '#1890ff' }}>
            {r.completed_qty.toLocaleString()}
          </span>
          <span style={{ fontSize: 12, color: '#8c8c8c' }}>/ {r.planned_qty.toLocaleString()}</span>
        </Space>
      ),
    },
    {
      title: '生产进度', key: 'progress', width: 200,
      render: (_: any, r: WorkOrder) => {
        const rate = r.progress_rate ?? (r.planned_qty > 0 ? Math.round((r.completed_qty / r.planned_qty) * 100) : 0)
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, fontWeight: 600 }}>
              <span style={{ color: getProgressColor(r) }}>{rate}%</span>
              <span style={{ color: '#8c8c8c' }}>
                {r.status === 'in_progress' ? r.remaining_time ? `${r.remaining_time} 剩余` : '生产中' :
                 r.status === 'on_hold' ? '已暂停' :
                 r.status === 'completed' || r.status === 'closed' ? '已入库' : '未开始'}
              </span>
            </div>
            <Progress
              percent={rate}
              size="small"
              strokeColor={getProgressColor(r)}
              format={() => ''}
              showInfo={false}
            />
          </div>
        )
      },
    },
    {
      title: '良品率', key: 'yield', width: 80,
      render: (_: any, r: WorkOrder) => {
        const yieldRate = r.yield_rate ?? (r.completed_qty > 0 ? Math.round((r.good_qty / r.completed_qty) * 100) : 0)
        return <span style={{ color: yieldRate >= 98 ? '#52c41a' : yieldRate >= 95 ? '#fa8c16' : '#f5222d' }}>{yieldRate}%</span>
      },
    },
    {
      title: '优先级', dataIndex: 'priority', key: 'priority', width: 100,
      render: (p: string) => {
        const info = PRIORITY_MAP[p] || { color: 'default', text: p, dotColor: '#8c8c8c' }
        return (
          <Tag color={info.color} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: info.dotColor, display: 'inline-block' }} />
            {info.text}
          </Tag>
        )
      },
    },
    {
      title: '预计交期', dataIndex: 'planned_due', key: 'due', width: 110,
      render: (v: string, r: WorkOrder) => {
        if (!v) return '-'
        const isOverdue = r.is_overdue
        return (
          <span style={{ color: isOverdue ? '#f5222d' : undefined, fontWeight: isOverdue ? 600 : undefined }}>
            {dayjs(v).format('MM-DD')}
            {isOverdue && <Badge status="error" text="逾期" style={{ marginLeft: 4 }} />}
          </span>
        )
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => {
        const info = STATUS_MAP[s] || { color: 'default', text: s }
        return (
          <Tag color={info.color} style={{ borderRadius: 12, padding: '2px 10px' }}>
            {info.text}
          </Tag>
        )
      },
    },
    {
      title: '操作', key: 'action', width: 260, fixed: 'right' as const,
      render: (_: any, record: WorkOrder) => renderActionButtons(record, {
        release: canRelease ? () => handleAction('release', record) : undefined,
        start: canStart ? () => handleAction('start', record) : undefined,
        pause: canPause ? () => { setPauseTarget(record); setPauseModalOpen(true) } : undefined,
        resume: canResume ? () => handleAction('resume', record) : undefined,
        inbound: canInbound ? () => handleAction('inbound', record) : undefined,
        complete: canComplete ? () => handleAction('complete', record) : undefined,
        closeWo: canClose ? () => handleAction('close', record) : undefined,
        cancel: canCancel ? () => { setCancelTarget(record); setCancelModalOpen(true) } : undefined,
        split: canSplit ? () => { setSplitTarget(record); setSplitModalOpen(true) } : undefined,
        detail: canViewDetail ? () => navigate(`/work-orders/${record.id}`) : undefined,
      }),
    },
  ]

  // ---- 工序工单子表列（主工单下钻）----
  const opColumns = [
    {
      title: '工序工单号', dataIndex: 'work_order_code', key: 'code',
      render: (t: string, r: WorkOrder) => (
        <Link to={`/work-orders/${r.id}`} style={{ fontFamily: 'monospace', color: '#1890ff' }}>{t}</Link>
      ),
    },
    {
      title: '工序', key: 'process',
      render: (_: any, r: WorkOrder) => (
        <Tag color="geekblue">{r.process_code} · {PROCESS_NAME[r.process_code || ''] || r.process_code}</Tag>
      ),
    },
    { title: '道次', dataIndex: 'operation_seq', key: 'seq', width: 60, render: (v: number) => (v ? `#${v}` : '-') },
    {
      title: '计划/完成', key: 'qty', width: 110,
      render: (_: any, r: WorkOrder) => `${r.completed_qty} / ${r.planned_qty}`,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => {
        const info = STATUS_MAP[s] || { color: 'default', text: s }
        return <Tag color={info.color}>{info.text}</Tag>
      },
    },
  ]

  // ---- 统计卡片 ----
  const statCards = stats ? [
    {
      title: '今日新增工单', value: stats.today_new, icon: <FileTextOutlined />, color: '#1890ff', bgColor: 'rgba(24,144,255,0.1)',
    },
    {
      title: '进行中工单', value: stats.in_progress, icon: <ThunderboltOutlined />, color: '#1890ff', bgColor: 'rgba(24,144,255,0.1)',
    },
    {
      title: '待下发', value: stats.pending_release, icon: <PlayCircleOutlined />, color: '#faad14', bgColor: 'rgba(250,173,20,0.1)',
    },
    {
      title: '逾期风险', value: stats.overdue_risk, icon: <WarningOutlined />, color: '#f5222d', bgColor: 'rgba(245,34,45,0.1)',
    },
    {
      title: '24h 完成率', value: `${stats.completion_rate_24h}%`, icon: <CheckCircleOutlined />, color: '#52c41a', bgColor: 'rgba(82,196,26,0.1)',
    },
  ] : []

  return (
    <div>
      {/* 页面标题 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h2 style={{ margin: 0, fontWeight: 700 }}>工单管理</h2>
          <span style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4, display: 'block' }}>
            共 {total} 条工单 · 当前厂区 {factoryId}
          </span>
        </Col>
        <Col>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => { fetchData(); fetchStats() }}>刷新</Button>
            {canCreate && (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)}>
                发布工单
              </Button>
            )}
          </Space>
        </Col>
      </Row>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        {statCards.map((card, idx) => (
          <Col xs={12} sm={12} md={6} lg={4.8} key={idx}>
            <Card size="small" hoverable style={{ borderRadius: 8 }}>
              <Row gutter={12} align="middle">
                <Col>
                  <div style={{
                    width: 40, height: 40, borderRadius: '50%', background: card.bgColor,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: card.color, fontSize: 18,
                  }}>
                    {card.icon}
                  </div>
                </Col>
                <Col>
                  <div style={{ fontSize: 12, color: '#8c8c8c' }}>{card.title}</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: card.color, lineHeight: 1.2 }}>
                    {card.value}
                  </div>
                </Col>
              </Row>
            </Card>
          </Col>
        ))}
      </Row>

      {/* 操作栏 + 筛选 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col span={12}>
            <Space>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalOpen(true)} size="middle">
                发布工单
              </Button>
              <Button icon={<ScissorOutlined />} disabled>批量排产</Button>
              <Button icon={<SearchOutlined />} disabled>打印流转卡</Button>
            </Space>
          </Col>
          <Col span={12}>
            <Space wrap>
              {/* 状态筛选 Chips */}
              {STATUS_FILTERS.map(f => (
                <Button
                  key={f.key}
                  type={activeFilter === f.key ? 'primary' : 'default'}
                  size="small"
                  onClick={() => { setActiveFilter(f.key); setPage(1); fetchData() }}
                  style={{ borderRadius: 16 }}
                >
                  {f.label}
                </Button>
              ))}
            </Space>
          </Col>
        </Row>
        <Row gutter={16} style={{ marginTop: 12 }}>
          <Col span={6}>
            <Input
              placeholder="搜索产品编码 / 工单号" prefix={<SearchOutlined />} allowClear
              onChange={(e) => setFilters(f => ({ ...f, product_id: e.target.value || undefined }))}
              onPressEnter={() => { setPage(1); fetchData() }}
            />
          </Col>
          <Col span={4}>
            <Select
              placeholder="优先级" style={{ width: '100%' }} allowClear
              onChange={(v) => { setFilters(f => ({ ...f, priority: v || undefined })); setPage(1); fetchData() }}
            >
              {Object.entries(PRIORITY_MAP).map(([k, v]) => (
                <Option key={k} value={k}>{v.text}</Option>
              ))}
            </Select>
          </Col>
          <Col span={4}>
            <Select
              placeholder="状态" style={{ width: '100%' }} allowClear
              onChange={(v) => { setFilters(f => ({ ...f, status: v || undefined })); setPage(1); fetchData() }}
            >
              {Object.entries(STATUS_MAP).map(([k, v]) => (
                <Option key={k} value={k}>{v.text}</Option>
              ))}
            </Select>
          </Col>
          <Col span={2}>
            <Button type="primary" onClick={() => { setPage(1); fetchData() }}>查询</Button>
          </Col>
        </Row>
      </Card>

      {/* 工单表格 */}
      <Card size="small" style={{ borderRadius: 8 }}>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1600 }}
          size="middle"
          expandable={{
            expandedRowRender: (record: WorkOrder) => {
              const ops = opsCache[record.id] || []
              if (opsLoading[record.id]) {
                return <div style={{ padding: 12, color: '#8c8c8c' }}>加载工序工单…</div>
              }
              if (!ops.length) {
                return <div style={{ padding: 12, color: '#8c8c8c' }}>该主工单暂无派生工序工单（产品可能未配置工艺路线）</div>
              }
              return (
                <Table
                  columns={opColumns}
                  dataSource={ops}
                  rowKey="id"
                  size="small"
                  pagination={false}
                />
              )
            },
            rowExpandable: (record: WorkOrder) => record.wo_type !== 'operation',
            onExpand: (expanded, record) => { if (expanded) loadOperations(record) },
          }}
          pagination={{
            current: page, pageSize, total, showSizeChanger: true, showTotal: (t) => `共 ${t} 条`,
            showQuickJumper: true,
            onChange: (p, ps) => { setPage(p); setPageSize(ps) },
          }}
          locale={{ emptyText: '暂无工单数据' }}
        />
      </Card>

      {/* ========== 新建工单弹窗 ========== */}
      <Modal title="发布新工单" open={createModalOpen} onCancel={() => setCreateModalOpen(false)} footer={null} width={560}>
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="产品编码" name="product_id" rules={[{ required: true, message: '请输入产品编码' }]}>
                <Input placeholder="如 PCBA-A001" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="销售订单号" name="sales_order_id">
                <Input placeholder="可选" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item label="计划数量" name="planned_qty" rules={[{ required: true, message: '请输入数量' }]}>
                <InputNumber min={1} style={{ width: '100%' }} placeholder="pcs" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="优先级" name="priority" initialValue="medium">
                <Select>
                  <Option value="low">低</Option>
                  <Option value="medium">中</Option>
                  <Option value="high">高</Option>
                  <Option value="urgent">紧急</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item label="BOM版本" name="bom_version">
                <Input placeholder="如 v1.0" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="指定工位" name="station_id">
                <Input placeholder="可选，工位编码" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="计划交期" name="planned_due" rules={[{ required: true, message: '请选择交期' }]}>
                <DatePicker showTime style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item label="备注" name="remark">
            <Input.TextArea rows={2} placeholder="客户加急订单等" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>创建工单（草稿）</Button>
          </Form.Item>
        </Form>
      </Modal>

      {/* ========== 暂停原因弹窗 ========== */}
      <Modal
        title={`暂停工单: ${pauseTarget?.work_order_code || ''}`}
        open={pauseModalOpen}
        onCancel={() => { setPauseModalOpen(false); setPauseReason(''); setPauseTarget(null) }}
        onOk={handlePause}
        okText="确认暂停"
        okButtonProps={{ danger: true }}
      >
        <p>确定要暂停工单 <b>{pauseTarget?.work_order_code}</b> 吗？</p>
        <Input.TextArea rows={3} placeholder="请填写暂停原因（必填）" value={pauseReason} onChange={(e) => setPauseReason(e.target.value)} />
      </Modal>

      {/* ========== 拆分工单弹窗 ========== */}
      <Modal title={`拆分工单: ${splitTarget?.work_order_code || ''}`} open={splitModalOpen} onCancel={() => setSplitModalOpen(false)} footer={null} width={480}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="拆分后新工单将作为子工单挂在当前工单下，主工单进度由子工单自动汇总，子工单全部完工后主工单才能完工"
        />
        <Form form={splitForm} layout="vertical" onFinish={handleSplit}>
          <Form.Item label={`拆分数量 (当前计划: ${splitTarget?.planned_qty || 0})`} name="split_qty" rules={[{ required: true }]}>
            <InputNumber min={1} max={(splitTarget?.planned_qty || 1) - 1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="备注" name="remark">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>确认拆分</Button>
          </Form.Item>
        </Form>
      </Modal>

      {/* ========== 取消工单弹窗 ========== */}
      <Modal
        title="取消工单"
        open={cancelModalOpen}
        onCancel={() => { setCancelModalOpen(false); setCancelReason('') }}
        onOk={handleCancel}
        okText="确认取消"
        okButtonProps={{ danger: true }}
      >
        <p>确定要取消工单 <b>{cancelTarget?.work_order_code}</b> 吗？</p>
        <Input.TextArea rows={3} placeholder="请填写取消原因（必填）" value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} />
      </Modal>
    </div>
  )
}

export default WorkOrderList
