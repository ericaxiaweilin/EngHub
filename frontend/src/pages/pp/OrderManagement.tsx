import React, { useEffect, useState, useMemo } from 'react'
import {
  Card, Table, Tag, Space, Button, Modal, Form, Input, InputNumber,
  Select, DatePicker, message, Typography, Row, Col, Statistic, Tooltip,
  Alert, Spin,
} from 'antd'
import {
  ShoppingCartOutlined, PlusOutlined, SplitCellsOutlined,
  CheckCircleOutlined, WarningOutlined, EyeOutlined,
  CalculatorOutlined, AuditOutlined, SafetyCertificateOutlined,
  CloseCircleOutlined, InfoCircleOutlined,
} from '@ant-design/icons'
import { Column, Pie } from '@ant-design/charts'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import api from '../../services/api'
import DrillDownDrawer from '../../components/trace/DrillDownDrawer'
import { useTranslation } from 'react-i18next'
import i18n from '../../i18n'

const t0 = i18n.t.bind(i18n)
const { Title, Text } = Typography
const FACTORY = localStorage.getItem('active_factory_id') || 'FAC_MECH_001'

const statusConfig: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: t0('待处理') },
  planning: { color: 'processing', label: t0('计划中') },
  confirmed: { color: 'blue', label: t0('已确认') },
  released: { color: 'blue', label: t0('已下达') },
  in_progress: { color: 'orange', label: t0('生产中') },
  in_production: { color: 'orange', label: t0('生产中') },
  shipped: { color: 'cyan', label: t0('已发货') },
  completed: { color: 'green', label: t0('已完成') },
  cancelled: { color: 'red', label: t0('已取消') },
}

const priorityConfig: Record<string, { color: string; label: string }> = {
  urgent: { color: 'red', label: t0('紧急') },
  high: { color: 'orange', label: t0('高') },
  medium: { color: 'blue', label: t0('中') },
  low: { color: 'default', label: t0('低') },
}

const reviewConfig: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: t0('待评审') },
  approved: { color: 'green', label: t0('已承诺') },
  conditional: { color: 'orange', label: t0('有条件') },
  rejected: { color: 'red', label: t0('拒绝承诺') },
}

const riskConfig: Record<string, { color: string; label: string }> = {
  low: { color: 'green', label: t0('低风险') },
  medium: { color: 'orange', label: t0('中风险') },
  high: { color: 'red', label: t0('高风险') },
}

const OrderManagement: React.FC = () => {
  const { t } = useTranslation()
  const [orders, setOrders] = useState<any[]>([])
  const [board, setBoard] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [boardLoading, setBoardLoading] = useState(false)
  const [createVisible, setCreateVisible] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm()
  const [reviewForm] = Form.useForm()
  const navigate = useNavigate()
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [priorityFilter, setPriorityFilter] = useState<string | undefined>(undefined)
  const [riskFilter, setRiskFilter] = useState<string | undefined>(undefined)
  const [reviewTarget, setReviewTarget] = useState<any | null>(null)
  const [reviewSaving, setReviewSaving] = useState(false)
  const [reviewPack, setReviewPack] = useState<any | null>(null)
  const [reviewPackLoading, setReviewPackLoading] = useState(false)
  const [drill, setDrill] = useState<{ title: string; headline: React.ReactNode; formula?: string; columns: ColumnsType<any>; records: any[] } | null>(null)

  const loadOrders = async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/orders', { params: { factory_id: FACTORY, status: statusFilter } })
      setOrders(res?.items || [])
    } catch { /* ignore */ } finally { setLoading(false) }
  }

  const loadBoard = async () => {
    setBoardLoading(true)
    try {
      const res: any = await api.get('/api/v1/orders/review-board', { params: { factory_id: FACTORY } })
      setBoard(res || null)
    } catch { /* ignore */ } finally { setBoardLoading(false) }
  }

  useEffect(() => { loadOrders() }, [statusFilter])
  useEffect(() => { loadBoard() }, [])

  const displayOrders = useMemo(() => {
    let rows = orders
    if (priorityFilter) rows = rows.filter(o => o.priority === priorityFilter)
    if (riskFilter) {
      if (riskFilter === 'unreviewed') rows = rows.filter(o => !o.review_status)
      else rows = rows.filter(o => o.risk_level === riskFilter)
    }
    return rows
  }, [orders, priorityFilter, riskFilter])

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      setCreating(true)
      await api.post('/api/v1/orders', {
        ...values,
        factory_id: FACTORY,
        delivery_date: values.delivery_date?.format('YYYY-MM-DD'),
      })
      message.success(t('订单创建成功'))
      setCreateVisible(false)
      form.resetFields()
      loadOrders()
      loadBoard()
    } catch (e: any) {
      if (e?.response) message.error(e.response.data?.detail || t('创建失败'))
    } finally { setCreating(false) }
  }

  const handleDecompose = async (orderId: string) => {
    try {
      const res: any = await api.post(`/api/v1/orders/${orderId}/decompose`)
      message.success(`拆分成功：生成 ${res.total_work_orders} 个工单`)
      loadOrders()
      loadBoard()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('拆分失败'))
    }
  }

  const handleMaterialCheck = async (orderId: string) => {
    try {
      const res: any = await api.get(`/api/v1/orders/${orderId}/material-check`)
      if (res.ready) {
        message.success(t('物料齐套，可以开工'))
      } else {
        message.warning(`缺料 ${res.shortage_count} 项，请检查`)
      }
      loadOrders()
      loadBoard()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || t('检查失败'))
    }
  }

  const closeReview = () => {
    setReviewTarget(null)
    setReviewPack(null)
    reviewForm.resetFields()
  }

  const openReview = async (record: any) => {
    setReviewTarget(record)
    setReviewPack(null)
    setReviewPackLoading(true)
    reviewForm.setFieldsValue({
      review_status: record.review_status || 'conditional',
      risk_level: record.risk_level || 'medium',
      committed_delivery: record.committed_delivery ? dayjs(record.committed_delivery) : (record.delivery_date ? dayjs(record.delivery_date) : undefined),
      review_note: record.review_note || '',
      review_items: [],
    })
    try {
      const pack: any = await api.get(`/api/v1/orders/${record.id}/review-pack`)
      setReviewPack(pack)
      if (!record.review_status) {
        reviewForm.setFieldsValue({
          review_status: pack?.recommendation?.review_status || 'conditional',
          risk_level: pack?.recommendation?.risk_level || 'medium',
          review_items: pack?.recommended_items || [],
        })
      }
    } catch (e: any) {
      message.warning(e?.response?.data?.detail || t('评审数据加载失败，请依据订单原始资料评审'))
    } finally {
      setReviewPackLoading(false)
    }
  }

  const handleReviewSubmit = async () => {
    if (!reviewTarget) return
    try {
      const values = await reviewForm.validateFields()
      setReviewSaving(true)
      await api.post(`/api/v1/orders/${reviewTarget.id}/review`, {
        review_status: values.review_status,
        risk_level: values.risk_level,
        committed_delivery: values.committed_delivery?.format('YYYY-MM-DD'),
        review_note: values.review_note,
        review_items: values.review_items || [],
      })
      message.success(t('订单评审完成'))
      closeReview()
      loadOrders()
      loadBoard()
    } catch (e: any) {
      if (e?.response) message.error(e.response.data?.detail || t('评审保存失败'))
    } finally { setReviewSaving(false) }
  }

  const columns: ColumnsType<any> = [
    { title: t('订单号'), dataIndex: 'order_code', key: 'code', width: 150,
      render: (v: string, r: any) => (
        <a
          onClick={(e) => { e.stopPropagation(); navigate(`/orders/${encodeURIComponent(v || r.id)}`) }}
          style={{ fontFamily: 'monospace', fontWeight: 600 }}
        >{v}</a>
      ) },
    { title: t('客户'), dataIndex: 'customer_name', key: 'customer', width: 100,
      render: (v: string) => v || <Text type="secondary">—</Text> },
    { title: t('产品'), dataIndex: 'product_name', key: 'product', width: 110,
      render: (v: string, r: any) => v || r?.product_id || '-' },
    { title: t('数量'), dataIndex: 'quantity', key: 'qty', width: 70, align: 'right' },
    { title: t('交期'), dataIndex: 'delivery_date', key: 'delivery', width: 100,
      render: (v: string) => {
        if (!v) return <Text type="secondary">—</Text>
        const isLate = dayjs(v).isBefore(dayjs(), 'day')
        return <Text style={{ color: isLate ? 'var(--color-error)' : undefined }}>{dayjs(v).format('MM/DD')}</Text>
      }},
    { title: t('金额'), dataIndex: 'total_amount', key: 'amount', width: 100, align: 'right' as const,
      render: (v: number, r: any) => v != null ? <span style={{ fontWeight: 500 }}>¥{v.toLocaleString()}</span> : <Text type="secondary">—</Text> },
    { title: t('优先级'), dataIndex: 'priority', key: 'priority', width: 70,
      render: (v: string) => <Tag color={priorityConfig[v]?.color}>{priorityConfig[v]?.label || v}</Tag> },
    { title: t('状态'), dataIndex: 'status', key: 'status', width: 80,
      render: (v: string) => <Tag color={statusConfig[v]?.color}>{statusConfig[v]?.label || v}</Tag> },
    { title: t('评审'), dataIndex: 'review_status', key: 'review', width: 80,
      render: (v: string, r: any) => (
        <Space size={2}>
          <Tag color={reviewConfig[v]?.color}>{reviewConfig[v]?.label || t('待评审')}</Tag>
          {r.risk_level && <Tag color={riskConfig[r.risk_level]?.color}>{riskConfig[r.risk_level]?.label}</Tag>}
        </Space>
      ) },
    { title: t('承诺交期'), dataIndex: 'committed_delivery', key: 'com_delivery', width: 90,
      render: (v: string) => v ? dayjs(v).format('MM/DD') : <Text type="secondary">—</Text> },
    { title: t('齐套'), dataIndex: 'material_ready', key: 'material', width: 60, align: 'center',
      render: (v: boolean, record) => {
        if (record.status === 'pending') return <Text type="secondary">—</Text>
        return v ? <CheckCircleOutlined style={{ color: 'var(--color-success)' }} /> : <WarningOutlined style={{ color: 'var(--color-warning)' }} />
      }},
    { title: t('操作'), key: 'action', width: 260,
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title={t('查看详情')}>
            <Button size="small" icon={<EyeOutlined />} onClick={() => navigate(`/orders/${encodeURIComponent(record.order_code || record.id)}`)}>{t('详情')}</Button>
          </Tooltip>
          <Button size="small" type={record.review_status ? 'default' : 'primary'} icon={<AuditOutlined />} onClick={() => openReview(record)}>
            {record.review_status ? t('改评审') : t('评审')}
          </Button>
          {!record.decomposed && record.status === 'pending' && (
            <Tooltip title={t('拆分为工单')}>
              <Button size="small" icon={<SplitCellsOutlined />} onClick={() => handleDecompose(record.id)}>{t('拆分')}</Button>
            </Tooltip>
          )}
          {record.decomposed && (
            <Tooltip title={t('物料齐套检查')}>
              <Button size="small" icon={<CheckCircleOutlined />} onClick={() => handleMaterialCheck(record.id)}>{t('齐套')}</Button>
            </Tooltip>
          )}
          <Tooltip title={t('交期倒推分析（五节点）')}>
            <Button size="small" icon={<CalculatorOutlined />} onClick={() => navigate(`/pmc-backward?qty=${record.quantity || ''}&delivery=${encodeURIComponent(record.delivery_date || '')} 08:00&product=${encodeURIComponent(record.product_code || '')}`)}>{t('倒推')}</Button>
          </Tooltip>
        </Space>
      )},
  ]

  const pendingCount = orders.filter(o => o.status === 'pending').length
  const planningCount = orders.filter(o => o.status === 'planning').length

  // ===== 穿透：统计卡 → 订单明细 =====
  const drillCols: ColumnsType<any> = [
    { title: t('订单号'), dataIndex: 'order_code', width: 170, render: (v: string, r: any) => (
      <a onClick={(e) => { e.stopPropagation(); navigate(`/orders/${encodeURIComponent(v || r.id)}`) }} style={{ fontFamily: 'monospace', fontWeight: 600 }}>{v}</a>
    ) },
    { title: t('客户'), dataIndex: 'customer_name', width: 120, render: (v: string) => v || '—' },
    { title: t('产品'), dataIndex: 'product_name', width: 130, render: (v?: string, r?: any) => v || r?.product_id || '—' },
    { title: t('数量'), dataIndex: 'quantity', width: 80, align: 'right' as const, render: (v: number) => v?.toLocaleString() ?? '-' },
    { title: t('交期'), dataIndex: 'delivery_date', width: 100, render: (v?: string) => v || '—' },
    { title: t('优先级'), dataIndex: 'priority', width: 80, render: (v: string) => <Tag color={priorityConfig[v]?.color}>{priorityConfig[v]?.label || v}</Tag> },
    { title: t('状态'), dataIndex: 'status', width: 90, render: (v: string) => <Tag color={statusConfig[v]?.color}>{statusConfig[v]?.label || v}</Tag> },
  ]
  const statDrills = {
    pending: (): any => ({ title: `${t('待处理')}订单 · 穿透`, headline: `${pendingCount} 单`, formula: `${t('待处理')} ${pendingCount} 单 / ${t('共')} ${orders.length} 单`, columns: drillCols, records: orders.filter(o => o.status === 'pending') }),
    planning: (): any => ({ title: `${t('计划中')}订单 · 穿透`, headline: `${planningCount} 单`, formula: `${t('计划中')} ${planningCount} 单 / ${t('共')} ${orders.length} 单`, columns: drillCols, records: orders.filter(o => o.status === 'planning') }),
    decomposed: (): any => ({ title: `${t('已拆分')}订单 · 穿透`, headline: `${orders.filter(o => o.decomposed).length} 单`, formula: `${t('已拆分')} ${orders.filter(o => o.decomposed).length} 单 / ${t('共')} ${orders.length} 单`, columns: drillCols, records: orders.filter(o => o.decomposed) }),
    ready: (): any => ({ title: `${t('物料齐套')}订单 · 穿透`, headline: `${orders.filter(o => o.material_ready).length} 单`, formula: `${t('物料齐套')} ${orders.filter(o => o.material_ready).length} 单 / ${t('共')} ${orders.length} 单`, columns: drillCols, records: orders.filter(o => o.material_ready) }),
    unreviewed: (): any => ({ title: `${t('待评审')}订单 · 穿透`, headline: `${orders.filter(o => !o.review_status).length} 单`, formula: `${t('待评审')} ${orders.filter(o => !o.review_status).length} 单 / ${t('共')} ${orders.length} 单`, columns: drillCols, records: orders.filter(o => !o.review_status) }),
  }

  // ===== 图表配置 =====
  const fmtYen = (v: number) => v != null ? `¥${(v / 10000).toFixed(1)}万` : ''
  const fmtCount = (v: number) => `${v} 单`

  const statusChartData = (board?.status || []).map((s: any) => ({
    status: statusConfig[s.name]?.label || s.name,
    key: s.name,
    count: s.count,
    amount: s.amount,
  }))

  const statusChart: any = {
    data: statusChartData,
    xField: 'status',
    yField: 'count',
    height: 190,
    style: { fill: 'var(--color-primary)', maxWidth: 40, radiusTopLeft: 4, radiusTopRight: 4 },
    scale: { color: { range: ['#1677ff'] } },
    label: { text: (d: any) => d.count, position: 'top', style: { fontSize: 10 } },
    tooltip: { title: (d: any) => d.status, items: [{ channel: 'y', name: '单数' }, { channel: 'y', valueFormatter: (v: any) => fmtYen(v) }] },
    onReady: ({ chart }: any) => {
      chart.on('element:click', (ev: any) => {
        const d = ev?.data?.data || ev?.data
        if (d?.key) setStatusFilter(d.key)
      })
    },
  }

  const priorityChartData = (board?.priority || []).map((s: any) => ({ priority: priorityConfig[s.name]?.label || s.name, key: s.name, count: s.count, amount: s.amount }))
  const priorityChart: any = {
    data: priorityChartData,
    angleField: 'count',
    colorField: 'priority',
    innerRadius: 0.6,
    radius: 0.92,
    height: 190,
    style: { stroke: '#fff', lineWidth: 2 },
    scale: { color: { range: ['#fa8c16', '#1677ff', '#d9d9d9', '#ff4d4f'] } },
    legend: { color: { position: 'bottom', layout: { justifyContent: 'center' } } },
    label: { position: 'outside', text: (d: any) => d.count, style: { fontSize: 10 } },
    tooltip: { items: [{ channel: 'y', name: '单数' }] },
    onReady: ({ chart }: any) => {
      chart.on('element:click', (ev: any) => {
        const d = ev?.data?.data || ev?.data
        if (d?.key) setPriorityFilter(d.key)
      })
    },
  }

  const customerChartData = (board?.customers || []).map((c: any) => ({ customer: c.name, count: c.count, amount: c.amount }))
  const customerChart: any = {
    data: customerChartData,
    xField: 'customer',
    yField: 'amount',
    height: 190,
    style: { fill: '#52c41a', maxWidth: 34, radiusTopLeft: 4, radiusTopRight: 4 },
    label: { text: (d: any) => fmtYen(d.amount), position: 'top', style: { fontSize: 9 } },
    axis: { x: { labelAutoRotate: true, labelAutoHide: true } },
    tooltip: { title: (d: any) => d.customer, items: [{ channel: 'y', name: '订单金额', valueFormatter: (v: any) => fmtYen(v) }] },
    onReady: ({ chart }: any) => {
      chart.on('element:click', (ev: any) => {
        const d = ev?.data?.data || ev?.data
        if (d?.customer) setDrill({ title: `${d.customer} · 订单穿透`, headline: `${d.count} 单 · ${fmtYen(d.amount)}`, columns: drillCols, records: orders.filter(o => (o.customer_name || o.customer_code) === d.customer) })
      })
    },
  }

  const deliveryChartData = (board?.delivery_buckets || []).map((b: any) => ({ name: b.name, count: b.count, amount: b.amount }))
  const deliveryChart: any = {
    data: deliveryChartData,
    xField: 'name',
    yField: 'count',
    height: 190,
    colorField: 'name',
    scale: { color: { range: ['#ff4d4f', '#fa8c16', '#faad14', '#1890ff', '#52c41a'] } },
    style: { maxWidth: 34, radiusTopLeft: 4, radiusTopRight: 4 },
    label: { text: (d: any) => d.count, position: 'top', style: { fontSize: 10 } },
    tooltip: { title: (d: any) => d.name, items: [{ channel: 'y', name: '单数' }, { channel: 'y', valueFormatter: (v: any) => fmtYen(v) }] },
    onReady: ({ chart }: any) => {
      chart.on('element:click', (ev: any) => {
        const d = ev?.data?.data || ev?.data
        if (d?.name) {
          setRiskFilter(undefined)
          setPriorityFilter(undefined)
          setStatusFilter(undefined)
        }
      })
    },
  }

  const bkExtract = (list: any[], key: string) => (list || []).reduce((acc, r) => acc + (r[key] || 0), 0)

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <ShoppingCartOutlined style={{ fontSize: 22, color: 'var(--color-primary)' }} />
            <Title level={4} style={{ margin: 0 }}>{t('销售订单')}</Title>
            <Tag>{board?.totals?.total ?? orders.length} 单 · {fmtYen(board?.totals?.amount ?? 0)}</Tag>
          </Space>
        </Col>
        <Col>
          <Space>
            <Select
              value={statusFilter}
              onChange={(v) => { setStatusFilter(v) }}
              allowClear
              placeholder={t('状态')}
              style={{ width: 110 }}
              options={Object.entries(statusConfig).map(([v, cfg]) => ({ value: v, label: cfg.label }))}
            />
            <Select
              value={priorityFilter}
              onChange={(v) => { setPriorityFilter(v) }}
              allowClear
              placeholder={t('优先级')}
              style={{ width: 100 }}
              options={Object.entries(priorityConfig).map(([v, cfg]) => ({ value: v, label: cfg.label }))}
            />
            <Select
              value={riskFilter}
              onChange={(v) => { setRiskFilter(v) }}
              allowClear
              placeholder={t('风险')}
              style={{ width: 110 }}
              options={[
                { value: 'unreviewed', label: t('未评审') },
                ...Object.entries(riskConfig).map(([v, cfg]) => ({ value: v, label: cfg.label })),
              ]}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateVisible(true)}>
              {t('新建订单')}
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 订单评审看板：分类 + 图表 */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small" hoverable loading={boardLoading} onClick={() => setDrill(statDrills.pending())}><Statistic title={t('待处理')} value={pendingCount} valueStyle={{ color: 'var(--color-warning)' }} /><div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 4 }}>{t('点击穿透')}</div></Card></Col>
        <Col span={6}><Card size="small" hoverable loading={boardLoading} onClick={() => setDrill(statDrills.planning())}><Statistic title={t('计划中')} value={planningCount} valueStyle={{ color: 'var(--color-primary)' }} /><div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 4 }}>{t('点击穿透')}</div></Card></Col>
        <Col span={6}><Card size="small" hoverable loading={boardLoading} onClick={() => setDrill(statDrills.decomposed())}><Statistic title={t('已拆分')} value={orders.filter(o => o.decomposed).length} valueStyle={{ color: 'var(--color-success)' }} /><div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 4 }}>{t('点击穿透')}</div></Card></Col>
        <Col span={6}><Card size="small" hoverable loading={boardLoading} onClick={() => setDrill(statDrills.ready())}><Statistic title={t('物料齐套')} value={orders.filter(o => o.material_ready).length} valueStyle={{ color: 'var(--color-purple)' }} /><div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginTop: 4 }}>{t('点击穿透')}</div></Card></Col>
      </Row>

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}>
          <Card size="small" title={<Space><AuditOutlined />{t('订单评审')}</Space>} loading={boardLoading}
            extra={<a onClick={() => setDrill(statDrills.unreviewed())}>{t('点击穿透')}</a>}>
            <Row gutter={8}>
              <Col span={8}><Statistic title={t('待评审')} value={board?.totals?.pending_review ?? orders.filter(o => !o.review_status).length} valueStyle={{ fontSize: 20, color: 'var(--color-warning)' }} /></Col>
              <Col span={16}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {(board?.review || []).slice(0, 3).map((r: any) => (
                    <div key={r.name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                      <Tag color={reviewConfig[r.name]?.color} style={{ margin: 0 }}>{reviewConfig[r.name]?.label || r.name}</Tag>
                      <span style={{ fontWeight: 600 }}>{r.count} 单</span>
                    </div>
                  ))}
                </div>
              </Col>
            </Row>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" title={t('订单状态分布')} loading={boardLoading} extra={<Text type="secondary" style={{ fontSize: 11 }}>{t('点击柱状过滤')}</Text>}>
            {(board?.status || []).length ? <Column {...statusChart} /> : <Text type="secondary">{t('暂无数据')}</Text>}
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" title={t('优先级占比')} loading={boardLoading} extra={<Text type="secondary" style={{ fontSize: 11 }}>{t('点击饼图过滤')}</Text>}>
            {(board?.priority || []).length ? <Pie {...priorityChart} /> : <Text type="secondary">{t('暂无数据')}</Text>}
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" title={t('交期风险分桶')} loading={boardLoading} extra={<Text type="secondary" style={{ fontSize: 11 }}>{t('未发货单')}</Text>}>
            {(board?.delivery_buckets || []).length ? <Column {...deliveryChart} /> : <Text type="secondary">{t('暂无数据')}</Text>}
          </Card>
        </Col>
      </Row>

      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card size="small" title={t('客户订单金额 Top 6')} loading={boardLoading} extra={<Text type="secondary" style={{ fontSize: 11 }}>{t('点击查看该客户订单')}</Text>}>
            {(board?.customers || []).length ? <Column {...customerChart} /> : <Text type="secondary">{t('暂无数据')}</Text>}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title={t('订单全局指标')} loading={boardLoading}>
            <Row gutter={8}>
              <Col span={8}><Statistic title={t('订单总额')} value={board?.totals?.amount ?? 0} precision={0} prefix="¥" /></Col>
              <Col span={8}><Statistic title={t('缺料风险单')} value={board?.totals?.material_risk ?? 0} valueStyle={{ color: 'var(--color-error)' }} /></Col>
              <Col span={8}><Statistic title={t('已评审/总')} value={`${bkExtract(board?.review, 'count')}/${board?.totals?.total ?? 0}`} /></Col>
            </Row>
            <div style={{ marginTop: 10 }}>
              {(board?.products || []).slice(0, 4).map((p: any) => (
                <div key={p.product_id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, padding: '2px 0' }}>
                  <Text ellipsis style={{ maxWidth: '60%' }}>{p.name}</Text>
                  <span style={{ color: 'var(--color-text-secondary)' }}>{p.count} 单 · {fmtYen(p.amount)}</span>
                </div>
              ))}
            </div>
          </Card>
        </Col>
      </Row>

      <Card>
        <Table
          columns={columns}
          dataSource={displayOrders}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ pageSize: 20, showTotal: (total: number) => t('共 {{count}} 条', { count: total }) }}
        />
      </Card>

      {/* 穿透：统计卡 → 订单明细 */}
      <DrillDownDrawer
        open={!!drill}
        onClose={() => setDrill(null)}
        title={drill?.title || ''}
        headline={drill?.headline}
        formula={drill?.formula}
        columns={drill?.columns || []}
        records={drill?.records || []}
      />

      {/* 订单评审弹窗 */}
      <Modal
        title={<Space><SafetyCertificateOutlined />{t('订单评审')} {reviewTarget?.order_code ? ` · ${reviewTarget.order_code}` : ''}</Space>}
        open={!!reviewTarget}
        onOk={handleReviewSubmit}
        onCancel={closeReview}
        confirmLoading={reviewSaving}
        width={980}
        destroyOnClose
      >
        {reviewTarget && (
          <React.Fragment>
            <Descriptions2 order={reviewTarget} />
            {reviewPackLoading && (
              <div style={{ textAlign: 'center', padding: '28px 0' }}><Spin tip={t('正在读取物料、产能和质量数据')} /></div>
            )}
            {!reviewPackLoading && reviewPack && (
              <React.Fragment>
                <Alert
                  style={{ marginTop: 12 }}
                  type={reviewPack.recommendation?.review_status === 'rejected' ? 'error' : reviewPack.recommendation?.review_status === 'conditional' ? 'warning' : 'success'}
                  showIcon
                  message={<Space wrap><Text strong>{t('系统评审建议')}</Text><Tag color={reviewConfig[reviewPack.recommendation?.review_status]?.color}>{reviewConfig[reviewPack.recommendation?.review_status]?.label || reviewPack.recommendation?.review_status}</Tag><Tag color={riskConfig[reviewPack.recommendation?.risk_level]?.color}>{riskConfig[reviewPack.recommendation?.risk_level]?.label || reviewPack.recommendation?.risk_level}</Tag></Space>}
                  description={reviewPack.recommendation?.reason}
                />
                <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 8 }}>
                  {(reviewPack.checks || []).map((check: any) => {
                    const color = check.status === 'pass' ? 'green' : check.status === 'fail' ? 'red' : 'orange'
                    const icon = check.status === 'pass' ? <CheckCircleOutlined /> : check.status === 'fail' ? <CloseCircleOutlined /> : <InfoCircleOutlined />
                    return (
                      <Card key={check.key} size="small" style={{ borderTop: `3px solid ${color === 'green' ? '#52c41a' : color === 'red' ? '#ff4d4f' : '#faad14'}` }}>
                        <Space size={4} style={{ marginBottom: 6 }}><span style={{ color: color === 'green' ? '#52c41a' : color === 'red' ? '#ff4d4f' : '#faad14' }}>{icon}</span><Text strong>{check.label}</Text></Space>
                        <div><Tag color={color}>{check.value}</Tag></div>
                        <Text type="secondary" style={{ display: 'block', fontSize: 12, lineHeight: 1.45, marginTop: 4 }}>{check.detail}</Text>
                        <Text type="secondary" style={{ display: 'block', fontSize: 10, marginTop: 6 }}>来源：{check.source}</Text>
                      </Card>
                    )
                  })}
                </div>
                <Row gutter={8} style={{ marginTop: 12 }}>
                  <Col span={6}><Card size="small"><Statistic title={t('预计最早完工')} value={String(reviewPack.delivery?.estimate?.earliest_delivery || '未估算').slice(0, 10)} valueStyle={{ fontSize: 18 }} /></Card></Col>
                  <Col span={6}><Card size="small"><Statistic title={t('产能利用率')} value={reviewPack.capacity?.utilization ?? '-'} suffix={reviewPack.capacity?.utilization != null ? '%' : t('无路线，未计算')} valueStyle={{ fontSize: 18 }} /></Card></Col>
                  <Col span={6}><Card size="small"><Statistic title={t('同产品在制')} value={reviewPack.wip?.open_qty ?? 0} suffix={t('件')} valueStyle={{ fontSize: 18 }} /></Card></Col>
                  <Col span={6}><Card size="small"><Statistic title={t('历史不良率')} value={reviewPack.quality?.defect_rate ?? 0} suffix={reviewPack.quality?.defect_rate != null ? '%' : '暂无'} valueStyle={{ fontSize: 18 }} /></Card></Col>
                </Row>
                <Text type="secondary" style={{ display: 'block', fontSize: 12, marginTop: 8 }}>
                  {t('产能口径')}：{reviewPack.capacity?.station_count ?? 0} {t('个工位合计日产能')}{' '}
                  {reviewPack.capacity?.daily_capacity_pieces ?? 0} {t('件/日')}
                  {reviewPack.delivery?.estimate?.capacity_basis ? ` · ${reviewPack.delivery.estimate.capacity_basis}` : ''}
                  {reviewPack.delivery?.estimate?.note ? ` · ${reviewPack.delivery.estimate.note}` : ''}
                </Text>
                {!!reviewPack.materials?.items?.length && (
                  <Card size="small" title={<Space><WarningOutlined />{t('物料明细')}</Space>} style={{ marginTop: 12 }}>
                    <Table
                      size="small"
                      pagination={false}
                      rowKey={(row: any) => row.material_code}
                      dataSource={reviewPack.materials.items}
                      scroll={{ y: 170 }}
                      columns={[
                        { title: t('物料'), dataIndex: 'material_name', render: (v: string, r: any) => <span>{v} <Text type="secondary">({r.material_code})</Text></span> },
                        { title: t('需求'), dataIndex: 'required', align: 'right' as const },
                        { title: t('可用'), dataIndex: 'available', align: 'right' as const },
                        { title: t('缺口'), dataIndex: 'shortage', align: 'right' as const, render: (v: number) => <Text type={v > 0 ? 'danger' : undefined}>{v}</Text> },
                        { title: t('状态'), dataIndex: 'ready', align: 'center' as const, render: (v: boolean) => v ? <Tag color="green">{t('齐套')}</Tag> : <Tag color="red">{t('缺料')}</Tag> },
                      ]}
                    />
                  </Card>
                )}
              </React.Fragment>
            )}
            <Form form={reviewForm} layout="vertical" style={{ marginTop: 12 }}>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item name="review_status" label={t('评审结论')} rules={[{ required: true }]}>
                    <Select options={[
                      { value: 'approved', label: t('同意承诺交期') },
                      { value: 'conditional', label: t('有条件承诺') },
                      { value: 'rejected', label: t('拒绝承诺') },
                    ]} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="risk_level" label={t('风险等级')} rules={[{ required: true }]}>
                    <Select options={Object.entries(riskConfig).map(([v, cfg]) => ({ value: v, label: cfg.label }))} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="committed_delivery" label={t('承诺交期')}>
                    <DatePicker style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="review_items" label={t('待确认事项')} extra={t('可输入多项，回车分隔；系统建议会显示在上方')}>
                <Select mode="tags" tokenSeparators={[',', '，', ';', '；']} placeholder={t('例如：确认采购到料日、确认外协产能')} options={[]} />
              </Form.Item>
              <Form.Item name="review_note" label={t('评审意见 / 待确认事项')}>
                <Input.TextArea rows={3} placeholder={t('记录客户特殊要求、跨部门结论和承诺边界')} />
              </Form.Item>
            </Form>
          </React.Fragment>
        )}
      </Modal>

      {/* 新建订单弹窗 */}
      <Modal
        title={t('新建销售订单')}
        open={createVisible}
        onOk={handleCreate}
        onCancel={() => setCreateVisible(false)}
        confirmLoading={creating}
        width={520}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="customer_name" label={t('客户名称')}>
                <Input placeholder={t('客户名称')} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="product_id" label={t('产品编码')} rules={[{ required: true }]}>
                <Input placeholder={t('如: PRD-001')} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="product_name" label={t('产品名称')}>
                <Input placeholder={t('产品名称')} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="quantity" label={t('数量')} rules={[{ required: true }]}>
                <InputNumber min={1} style={{ width: '100%' }} placeholder={t('订单数量')} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="delivery_date" label={t('交货日期')}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="priority" label={t('优先级')} initialValue="medium">
                <Select options={[
                  { value: 'urgent', label: t('紧急') },
                  { value: 'high', label: t('高') },
                  { value: 'medium', label: t('中') },
                  { value: 'low', label: t('低') },
                ]} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="remark" label={t('备注')}>
            <Input.TextArea rows={2} placeholder={t('备注信息')} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

const Descriptions2: React.FC<{ order: any }> = ({ order }) => {
  const t = t0
  const m = (order.material_risk as any) || { at_risk: false }
  return (
    <Card size="small" type="inner" style={{ marginTop: 8 }}>
      <Row gutter={12}>
        <Col span={12}><div style={{ fontSize: 12 }}>{t('客户')}：<Text strong>{order.customer_name || '—'}</Text></div></Col>
        <Col span={12}><div style={{ fontSize: 12 }}>{t('产品')}：<Text strong>{order.product_name || order.product_id || '—'}</Text></div></Col>
        <Col span={6} style={{ marginTop: 6 }}><div style={{ fontSize: 12 }}>{t('数量')}：{order.quantity ?? '-'} {order.unit || ''}</div></Col>
        <Col span={6} style={{ marginTop: 6 }}><div style={{ fontSize: 12 }}>{t('金额')}：¥{(order.total_amount ?? 0).toLocaleString()}</div></Col>
        <Col span={6} style={{ marginTop: 6 }}><div style={{ fontSize: 12 }}>{t('交期')}：{order.delivery_date || '—'}</div></Col>
        <Col span={6} style={{ marginTop: 6 }}><div style={{ fontSize: 12 }}>{t('优先级')}：<Tag color={priorityConfig[order.priority]?.color} style={{ margin: 0 }}>{priorityConfig[order.priority]?.label || order.priority}</Tag></div></Col>
      </Row>
      <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <Tag color={statusConfig[order.status]?.color} style={{ margin: 0 }}>{statusConfig[order.status]?.label || order.status}</Tag>
        {order.decomposed ? <Tag color="blue" style={{ margin: 0 }}>{t('已拆分')}</Tag> : null}
        {m.at_risk ? <Tag color="red" icon={<WarningOutlined />} style={{ margin: 0 }}>{t('物料风险')}：缺 {m.shortage_count} 项 / 最大缺口 {m.max_gap}</Tag> : <Tag color="green" style={{ margin: 0 }}>{t('物料齐套')}</Tag>}
      </div>
    </Card>
  )
}

export default OrderManagement
