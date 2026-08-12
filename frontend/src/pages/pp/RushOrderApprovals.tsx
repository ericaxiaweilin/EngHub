import React, { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Timeline,
  Typography,
  message,
} from 'antd'
import {
  AuditOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  ReloadOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { apsApi, type RushApproval } from '../../services/aps'
import { getActiveFactoryId } from '../../utils/factory'

const { Text, Title, Paragraph } = Typography

const STATUS_META: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' },
  submitted: { label: '待审批', color: 'processing' },
  approved: { label: '已批准', color: 'warning' },
  executed: { label: '已执行', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
  cancelled: { label: '已撤销', color: 'default' },
}

const ACTION_META: Record<string, { label: string; color: string }> = {
  draft: { label: '生成草稿', color: 'default' },
  submit: { label: '提报', color: 'blue' },
  approve: { label: '审批通过', color: 'green' },
  execute: { label: '执行重排', color: 'cyan' },
  reject: { label: '驳回', color: 'red' },
  cancel: { label: '撤销', color: 'default' },
}

interface EvalResult {
  rush_order?: {
    product_id: string
    quantity: number
    priority: string
    due_date?: string
    due_feasible?: boolean
    process_hours: number
  }
  impact?: {
    affected_orders: number
    total_existing_orders: number
    max_delay_hours: number
    delayed_orders: Array<Record<string, any>>
  }
  recommendation?: string
  approval?: {
    id: string
    approval_code: string
    status: string
    level: number
    required_role: string
  }
}

export default function RushOrderApprovals() {
  const factoryId = getActiveFactoryId()
  const [items, setItems] = useState<RushApproval[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [detail, setDetail] = useState<RushApproval | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [evalOpen, setEvalOpen] = useState(false)
  const [evalLoading, setEvalLoading] = useState(false)
  const [evalResult, setEvalResult] = useState<EvalResult | null>(null)
  const [evalForm, setEvalForm] = useState({ product_id: '', quantity: 100, due_date: '', priority: 'urgent' })
  const [rejectModal, setRejectModal] = useState<{ id: string; code: string } | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  const [acting, setActing] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await apsApi.listRushApprovals({ factory_id: factoryId, status: statusFilter })
      setItems(res?.items || [])
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '插单审批单加载失败')
    } finally {
      setLoading(false)
    }
  }, [factoryId, statusFilter])

  useEffect(() => { load() }, [load])

  const openDetail = async (id: string) => {
    setDetailLoading(true)
    try {
      const res: any = await apsApi.getRushApproval(id)
      setDetail(res?.data || null)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '详情加载失败')
    } finally {
      setDetailLoading(false)
    }
  }

  const runEval = async () => {
    if (!evalForm.product_id || !evalForm.quantity) {
      message.warning('请填写产品和数量')
      return
    }
    setEvalLoading(true)
    setEvalResult(null)
    try {
      const res: any = await apsApi.rushOrderImpact({
        factory_id: factoryId,
        product_id: evalForm.product_id,
        quantity: evalForm.quantity,
        due_date: evalForm.due_date || undefined,
        priority: evalForm.priority,
        persist: true,
      })
      setEvalResult(res)
      if (res?.approval) {
        message.success(`审批单 ${res.approval.approval_code} 已生成（L${res.approval.level} · ${res.approval.required_role}）`)
        setEvalOpen(false)
        setEvalForm({ product_id: '', quantity: 100, due_date: '', priority: 'urgent' })
        setStatusFilter(undefined)
        load()
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '插单评估失败')
    } finally {
      setEvalLoading(false)
    }
  }

  const act = async (action: 'submit' | 'approve' | 'cancel', id: string, comment?: string) => {
    setActing(id)
    try {
      if (action === 'submit') await apsApi.submitRushApproval(id, comment)
      if (action === 'approve') await apsApi.approveRushApproval(id, comment)
      if (action === 'cancel') await apsApi.cancelRushApproval(id)
      message.success('操作成功')
      setDetail(null)
      load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败')
    } finally {
      setActing(null)
    }
  }

  const doReject = async () => {
    if (!rejectModal || !rejectReason.trim()) {
      message.warning('驳回必须填写原因')
      return
    }
    setActing(rejectModal.id)
    try {
      await apsApi.rejectRushApproval(rejectModal.id, rejectReason)
      message.success('已驳回')
      setRejectModal(null)
      setRejectReason('')
      setDetail(null)
      load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '驳回失败')
    } finally {
      setActing(null)
    }
  }

  const columns = [
    { title: '审批单', dataIndex: 'approval_code', key: 'code', width: 180, render: (v: string, r: RushApproval) => <a onClick={() => openDetail(r.id)}><Text code>{v}</Text></a> },
    { title: '产品', dataIndex: 'product_id', key: 'product', render: (v: string) => <Text strong>{v}</Text> },
    { title: '数量', dataIndex: 'quantity', key: 'qty', width: 80, align: 'right' as const },
    { title: '交期', dataIndex: 'due_date', key: 'due', width: 110, render: (v?: string) => v || '-' },
    { title: '优先级', dataIndex: 'rush_priority', key: 'pri', width: 90, render: (v: string) => <Tag color={v === 'emergency' ? 'red' : 'orange'}>{v === 'emergency' ? '紧急' : '加急'}</Tag> },
    { title: '影响', dataIndex: 'affected_orders', key: 'aff', width: 80, align: 'right' as const, render: (v: number, r: RushApproval) => `${v} 单 · ${r.max_delay_days} 天` },
    { title: '级别', dataIndex: 'approval_level', key: 'level', width: 70, render: (v: number) => <Tag color={v === 3 ? 'red' : v === 2 ? 'orange' : 'blue'}>L{v}</Tag> },
    { title: '审批人', dataIndex: 'required_role', key: 'role', width: 110, render: (v?: string) => v || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (v: string) => { const m = STATUS_META[v] || { label: v, color: 'default' }; return <Tag color={m.color}>{m.label}</Tag> } },
    { title: '申请人', dataIndex: 'applicant', key: 'applicant', width: 100, render: (v?: string) => v || '-' },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 150, render: (v?: string) => v ? String(v).replace('T', ' ').slice(0, 16) : '-' },
  ]

  const impactColumns = [
    { title: '工单', dataIndex: 'work_order_code', key: 'wo', render: (v: string) => <Text code>{v}</Text> },
    { title: '产品', dataIndex: 'product_id', key: 'product' },
    { title: '原交期', dataIndex: 'original_due', key: 'od' },
    { title: '新预计', dataIndex: 'new_estimated_end', key: 'ne' },
    { title: '延迟', dataIndex: 'delay_days', key: 'delay', render: (v: number) => <Tag color={v >= 3 ? 'red' : v >= 1 ? 'orange' : 'green'}>{v} 天</Tag> },
    { title: '优先级', dataIndex: 'priority', key: 'priority' },
  ]

  return (
    <div>
      <Card
        size="small"
        title={<Space><AuditOutlined />插单审批流<Tag color="blue">Q4</Tag></Space>}
        extra={<Space wrap>
          <Select
            allowClear placeholder="状态过滤" style={{ width: 130 }}
            value={statusFilter}
            onChange={(v) => setStatusFilter(v || undefined)}
            options={Object.entries(STATUS_META).map(([value, m]) => ({ value, label: m.label }))}
          />
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>
          <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => setEvalOpen(true)}>插单评估</Button>
        </Space>}
      >
        <Paragraph type="secondary" style={{ marginBottom: 12 }}>
          插单/急单统一走「评估 → 提报 → 审批 → 执行」闭环，按影响等级自动定级，审批人由角色矩阵决定（L1 计划主管 / L2 生产经理 / L3 生产处长·厂长）。全流程留痕。
        </Paragraph>
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={items}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          onRow={(record) => ({ onClick: () => openDetail(record.id) })}
          locale={{ emptyText: <Empty description="暂无插单审批单，点击右上角「插单评估」创建" /> }}
        />
      </Card>

      {/* 插单评估抽屉 */}
      <Drawer
        title="插单影响评估 → 生成审批单"
        width={520}
        open={evalOpen}
        onClose={() => setEvalOpen(false)}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <div>
            <Text strong>产品</Text>
            <Input
              placeholder="product_id"
              value={evalForm.product_id}
              onChange={(e) => setEvalForm((f) => ({ ...f, product_id: e.target.value }))}
            />
          </div>
          <div>
            <Text strong>数量</Text>
            <InputNumber min={1} style={{ width: '100%' }} value={evalForm.quantity}
              onChange={(v) => setEvalForm((f) => ({ ...f, quantity: v ?? 0 }))} />
          </div>
          <div>
            <Text strong>客户要求交期（可选）</Text>
            <Input placeholder="YYYY-MM-DD" value={evalForm.due_date}
              onChange={(e) => setEvalForm((f) => ({ ...f, due_date: e.target.value }))} />
          </div>
          <div>
            <Text strong>优先级</Text>
            <Select
              style={{ width: '100%' }}
              value={evalForm.priority}
              onChange={(v) => setEvalForm((f) => ({ ...f, priority: v }))}
              options={[
                { value: 'urgent', label: 'urgent · 加急（正常重排）' },
                { value: 'emergency', label: 'emergency · 紧急（全厂重排，强制 L3 审批）' },
              ]}
            />
          </div>
          <Button type="primary" icon={<ThunderboltOutlined />} loading={evalLoading} onClick={runEval} block>
            评估并生成审批单
          </Button>
          {evalResult && (
            <Alert
              type={evalResult.impact?.affected_orders ? 'warning' : 'success'}
              showIcon
              message="评估结果"
              description={
                <div>
                  <div>受影响订单：{evalResult.impact?.affected_orders || 0} 张，最大延迟 {((evalResult.impact?.max_delay_hours || 0) / 24).toFixed(1)} 天</div>
                  <div style={{ marginTop: 6 }}>{evalResult.recommendation}</div>
                </div>
              }
            />
          )}
        </Space>
      </Drawer>

      {/* 详情抽屉 */}
      <Drawer
        title={detail ? <Space>{detail.approval_code}<Tag color={(STATUS_META[detail.status] || { color: 'default' }).color}>{(STATUS_META[detail.status] || { label: detail.status }).label}</Tag></Space> : '审批单详情'}
        width={680}
        open={!!detail}
        onClose={() => setDetail(null)}
        loading={detailLoading}
        extra={detail && (
          <Space wrap>
            {detail.status === 'draft' && (
              <Button type="primary" loading={acting === detail.id} onClick={() => act('submit', detail.id)}>提报审批</Button>
            )}
            {detail.status === 'submitted' && (
              <>
                <Button danger loading={acting === detail.id} onClick={() => setRejectModal({ id: detail.id, code: detail.approval_code })}>驳回</Button>
                <Button type="primary" icon={<CheckCircleOutlined />} loading={acting === detail.id} onClick={() => act('approve', detail.id, '审批通过，触发重排')}>通过并执行</Button>
              </>
            )}
            {(detail.status === 'draft' || detail.status === 'submitted') && (
              <Popconfirm title="确定撤销该审批单？" onConfirm={() => act('cancel', detail.id)}>
                <Button icon={<StopOutlined />} loading={acting === detail.id}>撤销</Button>
              </Popconfirm>
            )}
          </Space>
        )}
      >
        {detail && (
          <Space direction="vertical" style={{ width: '100%' }} size={16}>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="产品">{detail.product_id}</Descriptions.Item>
              <Descriptions.Item label="数量">{detail.quantity}</Descriptions.Item>
              <Descriptions.Item label="交期">{detail.due_date || '-'}</Descriptions.Item>
              <Descriptions.Item label="优先级">
                <Tag color={detail.rush_priority === 'emergency' ? 'red' : 'orange'}>{detail.rush_priority}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="审批级别">
                <Tag color={detail.approval_level === 3 ? 'red' : detail.approval_level === 2 ? 'orange' : 'blue'}>
                  L{detail.approval_level} · {detail.required_role}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="申请人">{detail.applicant || '-'}</Descriptions.Item>
              <Descriptions.Item label="审批人">{detail.approver || '-'}</Descriptions.Item>
              <Descriptions.Item label="目标排程">{detail.target_schedule_id ? <Text code>{detail.target_schedule_id}</Text> : '-'}</Descriptions.Item>
              <Descriptions.Item label="加工工时">{detail.process_hours ?? '-'} h</Descriptions.Item>
            </Descriptions>

            {detail.reject_reason && (
              <Alert type="error" showIcon message={`驳回原因：${detail.reject_reason}`} />
            )}

            <Card size="small" title="系统建议" extra={<Tag color="blue">{detail.affected_orders} 单受影响 · {detail.max_delay_days} 天</Tag>}>
              <Text>{detail.recommendation || '无建议'}</Text>
            </Card>

            <Tabs
              size="small"
              items={[
                {
                  key: 'impact',
                  label: `受影响订单（${detail.impact_json?.delayed_orders?.length || 0}）`,
                  children: (
                    <Table rowKey="work_order_code" size="small" pagination={false}
                      columns={impactColumns} dataSource={detail.impact_json?.delayed_orders || []}
                      locale={{ emptyText: <Empty description="无受影响订单" /> }} />
                  ),
                },
                {
                  key: 'logs',
                  label: `审批日志（${detail.logs?.length || 0}）`,
                  children: (
                    <Timeline
                      items={(detail.logs || []).map((l) => ({
                        color: ACTION_META[l.action]?.color || 'gray',
                        children: (
                          <div>
                            <Text strong>{(ACTION_META[l.action] || { label: l.action }).label}</Text>
                            <Text type="secondary"> · {l.actor}{l.actor_role ? `（${l.actor_role}）` : ''} · {String(l.created_at).replace('T', ' ').slice(0, 19)}</Text>
                            {l.comment && <div><Text type="secondary">{l.comment}</Text></div>}
                          </div>
                        ),
                      }))}
                    />
                  ),
                },
              ]}
            />
          </Space>
        )}
      </Drawer>

      {/* 驳回弹窗 */}
      <Modal
        title={`驳回插单审批单 ${rejectModal?.code || ''}`}
        open={!!rejectModal}
        onOk={doReject}
        confirmLoading={acting === rejectModal?.id}
        onCancel={() => { setRejectModal(null); setRejectReason('') }}
        okText="确认驳回"
        okButtonProps={{ danger: true }}
      >
        <Text strong>驳回原因（必填）</Text>
        <Input.TextArea rows={3} value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} placeholder="请说明驳回理由，将随审批日志留痕" />
      </Modal>
    </div>
  )
}
