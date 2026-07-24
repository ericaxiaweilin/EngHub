import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Descriptions, Tag, Button, Space, Table, Steps, Statistic, Row, Col,
  Progress, message, Spin, Modal, Input, Divider, Timeline, Tooltip, Alert,
} from 'antd'
import {
  ArrowLeftOutlined, PlayCircleOutlined, CheckCircleOutlined, StopOutlined,
  AuditOutlined, ApartmentOutlined, HistoryOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getWorkOrder, releaseWorkOrder, startWorkOrder, completeWorkOrder,
  closeWorkOrder, cancelWorkOrder, getStations, getRouting, getProducts,
  getWorkOrderStatusLogs, getWorkOrderChildren, getFlowDetail,
  WorkOrder, ProductionReport, Station, Routing, Product, WoStatusLog, FlowStep,
} from '../../services/mes'
import { getStoredUser } from '../../services/auth'
import RecordDetailDrawer, { DetailField } from '../../components/trace/RecordDetailDrawer'
import { makeStationResolver, makeProductResolver } from '../../components/trace/resolvers'

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  pending: { color: 'processing', text: '待下发' },
  released: { color: 'processing', text: '已下达' },
  in_progress: { color: 'blue', text: '生产中' },
  pending_inbound: { color: 'cyan', text: '待入库' },
  completed: { color: 'success', text: '已完成' },
  closed: { color: 'default', text: '已关闭' },
  cancelled: { color: 'error', text: '已取消' },
  on_hold: { color: 'warning', text: '暂停' },
}

// 状态操作日志：动作/角色显示名（与后端 ACTION_ROLE_GATES 配套）
const ACTION_LABELS: Record<string, string> = {
  create: '创建', release: '下达', start: '开工', pause: '暂停', resume: '恢复',
  pending_inbound: '标记待入库', complete: '完工确认', close: '关闭', cancel: '取消', split: '拆分',
}
const ROLE_NAMES: Record<string, string> = {
  admin: '管理员', factory_manager: '厂长', production_manager: '生产经理',
  quality_manager: '品质经理', operator: '操作员',
}
// 动作角色门槛（与后端 ACTION_ROLE_GATES 一致）
const ACTION_ROLES: Record<string, string[]> = {
  release: ['factory_manager', 'production_manager', 'admin'],
  complete: ['factory_manager', 'quality_manager', 'admin'],
  close: ['factory_manager', 'admin'],
}

const PRIORITY_MAP: Record<string, { color: string; text: string }> = {
  low: { color: 'default', text: '低' },
  medium: { color: 'blue', text: '中' },
  high: { color: 'orange', text: '高' },
  urgent: { color: 'red', text: '紧急' },
}

const STATUS_STEPS = ['pending', 'released', 'in_progress', 'completed']
const STEP_LABELS: Record<string, string> = {
  pending: '创建', released: '下达', in_progress: '开工', completed: '完工',
}

const WorkOrderDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const currentUser = getStoredUser()
  const [loading, setLoading] = useState(true)
  const [wo, setWo] = useState<WorkOrder | null>(null)
  const [cancelModalOpen, setCancelModalOpen] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
  const [stations, setStations] = useState<Station[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [routing, setRouting] = useState<Routing | null>(null)
  const [reportDetail, setReportDetail] = useState<ProductionReport | null>(null)
  const [children, setChildren] = useState<WorkOrder[]>([])
  const [statusLogs, setStatusLogs] = useState<WoStatusLog[]>([])
  const [flowSteps, setFlowSteps] = useState<FlowStep[]>([])
  const [flowDone, setFlowDone] = useState(0)
  const [flowCurrent, setFlowCurrent] = useState(0)

  // 角色门槛（与后端一致）：superuser 或角色在允许列表
  const hasRole = (action: string): boolean => {
    if (!currentUser) return false
    if (currentUser.is_superuser) return true
    return (ACTION_ROLES[action] || []).includes(currentUser.role)
  }

  const fetchDetail = async () => {
    if (!id) return
    setLoading(true)
    try {
      const res = await getWorkOrder(id)
      setWo(res)
      // 追溯：拉取工艺路线，让“当前工序第 N 步”可追溯到具体工序
      if (res.routing_id) {
        getRouting(res.routing_id).then(setRouting).catch(() => setRouting(null))
      }
      // 子工单 + 状态操作日志（审核追溯）
      getWorkOrderChildren(id).then((r) => setChildren(r.items || [])).catch(() => setChildren([]))
      getWorkOrderStatusLogs(id).then((r) => setStatusLogs(r.items || [])).catch(() => setStatusLogs([]))
      // 工序流转视图（016）
      getFlowDetail(id).then((r) => {
        setFlowSteps(r.flow_steps || [])
        setFlowDone(r.done_steps || 0)
        setFlowCurrent(r.current_step != null ? r.current_step - 1 : (r.flow_steps?.length || 0))
      }).catch(() => setFlowSteps([]))
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '获取工单详情失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchDetail() }, [id])

  // 追溯：拉取工位用于名称解析
  const factoryId = wo?.factory_id
  useEffect(() => {
    if (factoryId) {
      getStations({ factory_id: factoryId, page_size: 50 })
        .then((res) => setStations(res.items || []))
        .catch(() => setStations([]))
    }
  }, [factoryId])

  // 追溯：拉取产品用于产品编码解析（不按厂区过滤，避免跨厂区引用解析不到）
  useEffect(() => {
    getProducts()
      .then((res) => setProducts(res.items || []))
      .catch(() => setProducts([]))
  }, [])

  const handleAction = async (action: string) => {
    if (!wo) return
    try {
      switch (action) {
        case 'release': await releaseWorkOrder(wo.id); break
        case 'start': await startWorkOrder(wo.id); break
        case 'complete': await completeWorkOrder(wo.id); break
        case 'close': await closeWorkOrder(wo.id); break
      }
      message.success('操作成功')
      fetchDetail()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '操作失败')
    }
  }

  const handleCancel = async () => {
    if (!wo || !cancelReason.trim()) { message.warning('请填写取消原因'); return }
    try {
      await cancelWorkOrder(wo.id, cancelReason)
      message.success('工单已取消')
      setCancelModalOpen(false)
      fetchDetail()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '取消失败')
    }
  }

  if (loading) return <Spin size="large" style={{ display: 'block', margin: '100px auto' }} />
  if (!wo) return <div>工单不存在</div>

  const completionRate = wo.planned_qty > 0 ? Math.round(wo.completed_qty / wo.planned_qty * 100) : 0
  const yieldRate = wo.completed_qty > 0 ? (wo.good_qty / wo.completed_qty * 100).toFixed(1) : '0.0'
  const scrapRate = wo.completed_qty > 0 ? (wo.scrap_qty / wo.completed_qty * 100).toFixed(1) : '0.0'
  const statusInfo = STATUS_MAP[wo.status] || { color: 'default', text: wo.status }
  const priorityInfo = PRIORITY_MAP[wo.priority] || { color: 'default', text: wo.priority }

  const currentStepIndex = STATUS_STEPS.indexOf(wo.status)
  const stepCurrent = wo.status === 'cancelled' || wo.status === 'on_hold' ? currentStepIndex : Math.max(currentStepIndex, 0)

  // 审核机制派生状态：创建人 / 子工单完成情况 / 角色门槛
  const isCreator = !!currentUser && !!wo.created_by && wo.created_by === currentUser.username
  const hasChildren = children.length > 0
  const childrenAllDone = hasChildren && children.every((c) => ['completed', 'closed'].includes(c.status))
  const canRelease = hasRole('release')
  const canComplete = hasRole('complete')
  const canClose = hasRole('close')

  // 追溯：工位名/产品名解析
  const stationLabel = makeStationResolver(stations)
  const productLabel = makeProductResolver(products)

  // 追溯：报工原始记录详情字段（唯一编号/时间/经手人/修改痕迹）
  const reportFields: DetailField[] = [
    { label: '报工单号', key: 'report_code' },
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

  const reportColumns = [
    { title: '报工单号', dataIndex: 'report_code', key: 'code', width: 150 },
    { title: '工位', dataIndex: 'station_id', key: 'station', width: 130, render: (v: string) => stationLabel(v) },
    { title: '操作人', dataIndex: 'operator_id', key: 'operator', width: 90, render: (v: string) => v || '-' },
    { title: '良品', dataIndex: 'good_qty', key: 'good', width: 70, render: (v: number) => <span style={{ color: '#52c41a' }}>{v}</span> },
    { title: '不良', dataIndex: 'defect_qty', key: 'defect', width: 70, render: (v: number) => <span style={{ color: '#faad14' }}>{v}</span> },
    { title: '报废', dataIndex: 'scrap_qty', key: 'scrap', width: 70, render: (v: number) => <span style={{ color: '#f5222d' }}>{v}</span> },
    { title: '班次', dataIndex: 'shift', key: 'shift', width: 70, render: (v: string) => v === 'day' ? '白班' : v === 'night' ? '夜班' : v },
    { title: '类型', dataIndex: 'report_type', key: 'type', width: 80 },
    { title: '时间', dataIndex: 'created_at', key: 'time', width: 140, render: (v: string) => v ? dayjs(v).format('MM-DD HH:mm') : '-' },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/work-orders')}>返回</Button>
        <h2 style={{ margin: 0 }}>{wo.work_order_code}</h2>
        <Tag color={statusInfo.color}>{statusInfo.text}</Tag>
        <Tag color={priorityInfo.color}>优先级: {priorityInfo.text}</Tag>
      </Space>

      {/* 状态流转步骤条 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Steps
          current={stepCurrent}
          status={wo.status === 'cancelled' ? 'error' : undefined}
          items={STATUS_STEPS.map((s) => ({ title: STEP_LABELS[s] }))}
        />
        <Divider style={{ margin: '12px 0' }} />
        <Space wrap>
          {['draft', 'pending'].includes(wo.status) && canRelease && (
            <Tooltip title={isCreator ? '职责分离：创建人不能下达自己创建的工单' : ''}>
              <Button type="primary" icon={<AuditOutlined />} disabled={isCreator} onClick={() => handleAction('release')}>下达</Button>
            </Tooltip>
          )}
          {wo.status === 'released' && !hasChildren && <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => handleAction('start')}>开工</Button>}
          {(wo.status === 'in_progress' || wo.status === 'pending_inbound' || (hasChildren && childrenAllDone && wo.status === 'released')) && canComplete && (
            <Button type="primary" icon={<CheckCircleOutlined />} onClick={() => handleAction('complete')}>完工</Button>
          )}
          {wo.status === 'completed' && canClose && <Button icon={<CheckCircleOutlined />} onClick={() => handleAction('close')}>关闭</Button>}
          {['draft', 'pending', 'released'].includes(wo.status) && <Button danger icon={<StopOutlined />} onClick={() => setCancelModalOpen(true)}>取消工单</Button>}
        </Space>
        {!canRelease && ['draft', 'pending'].includes(wo.status) && (
          <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>下达需由生产经理/厂长操作，且创建人不能下达自己创建的工单</div>
        )}
        {hasChildren && !canComplete && ['released', 'in_progress', 'pending_inbound'].includes(wo.status) && (
          <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>完工需品质确认（厂长/品质经理）</div>
        )}
      </Card>

      {/* 进度统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small"><Statistic title="完成率" value={completionRate} suffix="%" valueStyle={{ color: completionRate >= 100 ? '#52c41a' : '#1890ff' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="良品率" value={yieldRate} suffix="%" valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="报废率" value={scrapRate} suffix="%" valueStyle={{ color: '#f5222d' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <div style={{ marginBottom: 4, color: '#666', fontSize: 14 }}>完成进度</div>
            <Progress percent={completionRate} status={wo.status === 'completed' ? 'success' : 'active'} />
          </Card>
        </Col>
      </Row>

      {/* 基本信息 */}
      <Card title="工单信息" size="small" style={{ marginBottom: 16 }}>
        <Descriptions bordered column={3} size="small">
          <Descriptions.Item label="工单号">{wo.work_order_code}</Descriptions.Item>
          <Descriptions.Item label="产品编码">{productLabel(wo.product_id)}</Descriptions.Item>
          <Descriptions.Item label="BOM版本">{wo.bom_version || '-'}</Descriptions.Item>
          <Descriptions.Item label="计划数量">{wo.planned_qty} {wo.unit}</Descriptions.Item>
          <Descriptions.Item label="完成数量">{wo.completed_qty} {wo.unit}</Descriptions.Item>
          <Descriptions.Item label="良品数">{wo.good_qty}</Descriptions.Item>
          <Descriptions.Item label="不良数">{wo.defect_qty}</Descriptions.Item>
          <Descriptions.Item label="报废数">{wo.scrap_qty}</Descriptions.Item>
          <Descriptions.Item label="工艺路线">{routing ? `${routing.routing_code} v${routing.version}` : (wo.routing_id || '-')}</Descriptions.Item>
          <Descriptions.Item label="当前工序步骤">第 {wo.current_routing_step} 步</Descriptions.Item>
          <Descriptions.Item label="指定工位">{stationLabel(wo.assigned_station_id)}</Descriptions.Item>
          <Descriptions.Item label="销售订单">{wo.sales_order_id || '-'}</Descriptions.Item>
          <Descriptions.Item label="计划开工">{wo.planned_start ? dayjs(wo.planned_start).format('YYYY-MM-DD HH:mm') : '-'}</Descriptions.Item>
          <Descriptions.Item label="计划交期">{wo.planned_due ? dayjs(wo.planned_due).format('YYYY-MM-DD HH:mm') : '-'}</Descriptions.Item>
          <Descriptions.Item label="实际开工">{wo.actual_start ? dayjs(wo.actual_start).format('YYYY-MM-DD HH:mm') : '-'}</Descriptions.Item>
          <Descriptions.Item label="实际完工">{wo.actual_complete ? dayjs(wo.actual_complete).format('YYYY-MM-DD HH:mm') : '-'}</Descriptions.Item>
          <Descriptions.Item label="创建人">{wo.created_by || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{wo.created_at ? dayjs(wo.created_at).format('YYYY-MM-DD HH:mm') : '-'}</Descriptions.Item>
          <Descriptions.Item label="下达人">{wo.released_by || '-'}</Descriptions.Item>
          <Descriptions.Item label="完工确认人">{wo.completed_by || '-'}</Descriptions.Item>
          <Descriptions.Item label="备注" span={3}>{wo.remark || '-'}</Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 子工单面板（主工单拆分后显示：子工单未完工时主工单不可完工）*/}
      {hasChildren && (
        <Card
          title={<span><ApartmentOutlined /> 子工单（{children.length}）</span>}
          size="small"
          style={{ marginBottom: 16 }}
        >
          {!childrenAllDone && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message="子工单未全部完工，主工单不可完工；主工单进度由子工单自动汇总"
            />
          )}
          <Table
            size="small"
            pagination={false}
            dataSource={children.map((c) => ({ ...c, key: c.id }))}
            columns={[
              {
                title: '子工单号', dataIndex: 'work_order_code', key: 'code', width: 200,
                render: (v: string, r: WorkOrder) => <a onClick={() => navigate(`/work-orders/${r.id}`)}>{v}</a>,
              },
              {
                title: '状态', dataIndex: 'status', key: 'status', width: 100,
                render: (v: string) => {
                  const info = STATUS_MAP[v] || { color: 'default', text: v }
                  return <Tag color={info.color}>{info.text}</Tag>
                },
              },
              { title: '计划量', dataIndex: 'planned_qty', key: 'planned', width: 90 },
              { title: '完成量', dataIndex: 'completed_qty', key: 'completed', width: 90 },
              {
                title: '进度', key: 'progress',
                render: (_: any, r: WorkOrder) => (
                  <Progress
                    percent={r.planned_qty > 0 ? Math.round(r.completed_qty / r.planned_qty * 100) : 0}
                    size="small"
                    status={['completed', 'closed'].includes(r.status) ? 'success' : 'active'}
                  />
                ),
              },
            ]}
          />
        </Card>
      )}

      {/* 工艺路线（追溯：当前工序第 N 步 → 具体工序）*/}
      {routing && routing.steps && routing.steps.length > 0 && (
        <Card title={`工艺路线 ${routing.routing_code}（共 ${routing.steps.length} 道工序）`} size="small" style={{ marginBottom: 16 }}>
          <Steps
            current={Math.max((wo.current_routing_step || 1) - 1, 0)}
            size="small"
            items={routing.steps.map((s) => ({
              title: s.name,
              description: s.station_id ? stationLabel(s.station_id) : (s.duration_min ? `${s.duration_min}min` : undefined),
            }))}
          />
        </Card>
      )}

      {/* 工序流转视图（016） */}
      {flowSteps.length > 0 && (
        <Card title={<span><ApartmentOutlined /> 工序流转 ({flowDone}/{flowSteps.length})</span>} size="small" style={{ marginTop: 16 }}>
          <Steps
            size="small"
            current={flowCurrent}
            items={flowSteps.map((s) => ({
              title: s.remark || s.process_code,
              description: s.status === 'completed' ? `✓ ${s.completed_by || ''}` : s.status === 'in_progress' ? '加工中' : s.status === 'released' ? '已释放' : '待释放',
              status: s.status === 'completed' || s.status === 'closed' ? 'finish'
                : s.status === 'in_progress' ? 'process'
                : s.status === 'released' ? 'process' : 'wait',
              icon: s.is_qc_gate ? <AuditOutlined style={{ color: s.status === 'completed' ? '#52c41a' : '#ff4d4f' }} /> : undefined,
            }))}
          />
          <Progress percent={flowSteps.length ? Math.round(flowDone / flowSteps.length * 100) : 0} size="small" style={{ marginTop: 12 }} />
        </Card>
      )}

      {/* 报工记录 */}
      <Card title={`报工记录 (${wo.production_reports?.length || 0})`} size="small">
        <Table
          columns={reportColumns}
          dataSource={(wo.production_reports || []).map((r: ProductionReport, i: number) => ({ ...r, key: r.id || i }))}
          pagination={false}
          size="small"
          scroll={{ x: 900 }}
          onRow={(r) => ({ onClick: () => setReportDetail(r), style: { cursor: 'pointer' } })}
        />
      </Card>

      {/* 状态操作记录（审核追溯：谁/什么角色/何时/做了什么）*/}
      <Card title={<span><HistoryOutlined /> 状态记录 ({statusLogs.length})</span>} size="small" style={{ marginTop: 16 }}>
        {statusLogs.length === 0 ? (
          <div style={{ color: '#999' }}>暂无状态操作记录</div>
        ) : (
          <Timeline
            style={{ marginTop: 16 }}
            items={[...statusLogs].reverse().map((log) => ({
              color: log.action === 'complete' ? 'green' : log.action === 'release' ? 'blue' : log.action === 'cancel' ? 'red' : 'gray',
              children: (
                <div>
                  <div>
                    <b>{ACTION_LABELS[log.action] || log.action}</b>
                    {log.from_status && (
                      <span style={{ color: '#999' }}>
                        {' '}({(STATUS_MAP[log.from_status] || { text: log.from_status }).text} → {(STATUS_MAP[log.to_status] || { text: log.to_status }).text})
                      </span>
                    )}
                  </div>
                  <div style={{ color: '#666', fontSize: 12 }}>
                    {log.operator}
                    {log.operator_role ? `（${ROLE_NAMES[log.operator_role] || log.operator_role}）` : ''}
                    {log.created_at ? ` · ${dayjs(log.created_at).format('YYYY-MM-DD HH:mm:ss')}` : ''}
                  </div>
                  {log.comment && <div style={{ color: '#999', fontSize: 12 }}>{log.comment}</div>}
                </div>
              ),
            }))}
          />
        )}
      </Card>

      {/* 取消 Modal */}
      <Modal title="取消工单" open={cancelModalOpen} onCancel={() => { setCancelModalOpen(false); setCancelReason('') }} onOk={handleCancel} okText="确认取消" okButtonProps={{ danger: true }}>
        <p>确定要取消工单 <b>{wo.work_order_code}</b> 吗？此操作不可逆。</p>
        <Input.TextArea rows={3} placeholder="请填写取消原因（必填）" value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} />
      </Modal>

      {/* 追溯：报工原始记录详情 */}
      <RecordDetailDrawer
        open={!!reportDetail}
        onClose={() => setReportDetail(null)}
        title="报工原始记录"
        record={reportDetail}
        fields={reportFields}
        extra={reportDetail?.is_modified ? <Tag color="orange">已修改</Tag> : <Tag>未修改</Tag>}
      />
    </div>
  )
}

export default WorkOrderDetail
