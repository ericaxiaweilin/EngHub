import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Descriptions, Tag, Button, Space, Table, Steps, Statistic, Row, Col,
  Progress, message, Spin, Modal, Input, Divider,
} from 'antd'
import {
  ArrowLeftOutlined, PlayCircleOutlined, CheckCircleOutlined, StopOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getWorkOrder, releaseWorkOrder, startWorkOrder, completeWorkOrder,
  cancelWorkOrder, getStations, getRouting, getProducts,
  WorkOrder, ProductionReport, Station, Routing, Product,
} from '../../services/mes'
import RecordDetailDrawer, { DetailField } from '../../components/trace/RecordDetailDrawer'
import { makeStationResolver, makeProductResolver } from '../../components/trace/resolvers'

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '待下达' },
  released: { color: 'processing', text: '已下达' },
  in_progress: { color: 'blue', text: '生产中' },
  pending_inbound: { color: 'cyan', text: '待入库' },
  completed: { color: 'success', text: '已完成' },
  cancelled: { color: 'error', text: '已取消' },
  on_hold: { color: 'warning', text: '暂停' },
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
  const [loading, setLoading] = useState(true)
  const [wo, setWo] = useState<WorkOrder | null>(null)
  const [cancelModalOpen, setCancelModalOpen] = useState(false)
  const [cancelReason, setCancelReason] = useState('')
  const [stations, setStations] = useState<Station[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [routing, setRouting] = useState<Routing | null>(null)
  const [reportDetail, setReportDetail] = useState<ProductionReport | null>(null)

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
        <Space>
          {wo.status === 'pending' && <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => handleAction('release')}>下达</Button>}
          {wo.status === 'released' && <Button type="primary" icon={<PlayCircleOutlined />} onClick={() => handleAction('start')}>开工</Button>}
          {wo.status === 'in_progress' && <Button type="primary" icon={<CheckCircleOutlined />} onClick={() => handleAction('complete')}>完工</Button>}
          {['pending', 'released'].includes(wo.status) && <Button danger icon={<StopOutlined />} onClick={() => setCancelModalOpen(true)}>取消工单</Button>}
        </Space>
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
          <Descriptions.Item label="备注" span={3}>{wo.remark || '-'}</Descriptions.Item>
        </Descriptions>
      </Card>

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
