/**
 * 任务中心（统一工作台）：把需要用户关注的事情汇到一处，能自动办的不打扰用户
 * - AI 跟进：暂时无法完成的任务挂账，智能体按频率定期扫描核实进展
 * - 他人指派：其他同事指派给我的任务（含截止时间，指派时自动通知）
 * - 会议纪要 / 邮件 / 备忘：粘贴接入 → AI 自动分诊（摘要/行动项/紧急度），
 *   纯知会内容自动归档，需跟进的进自动跟进循环，必须本人处理的才提醒用户
 * - 指派给我的工单、未读系统通知一并聚合展示，通知可一键转为跟进任务
 */
import React, { useCallback, useEffect, useState } from 'react'
import {
  Alert, Badge, Button, Card, Col, DatePicker, Drawer, Form, Input, InputNumber,
  List, Modal, Popconfirm, Progress, Row, Select, Space, Statistic, Table, Tabs,
  Tag, Timeline, Tooltip, Typography, message,
} from 'antd'
import {
  BellOutlined, CarryOutOutlined, ClockCircleOutlined, DeleteOutlined,
  HistoryOutlined, ImportOutlined, PlusOutlined, ReloadOutlined,
  RobotOutlined, ThunderboltOutlined, ToolOutlined, UserSwitchOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const { Text, Paragraph } = Typography

interface FollowupTask {
  id: string
  title: string
  description?: string
  item_type: string
  assigned_to?: string
  agent_key?: string
  agent_name?: string
  status: string
  block_reason?: string
  source?: string
  follow_interval_minutes: number
  next_follow_at?: string
  last_follow_at?: string
  last_follow_note?: string
  follow_count: number
  max_follows: number
  progress_pct: number
  result_summary?: string
  ai_summary?: string
  ai_suggestion?: string
  due_at?: string
  created_by: string
  created_at: string
}

interface MyWorkOrder {
  id: string
  work_order_code: string
  status: string
  priority?: number
  planned_qty?: number
  planned_due?: string
  process_code?: string
  remark?: string
}

interface InboxNotification {
  id: string
  category?: string
  title: string
  content?: string
  severity?: string
  source_type?: string
  source_id?: string
  created_at: string
}

interface TaskLog {
  id: string
  trigger_type: string
  note?: string
  status_after?: string
  progress_pct?: number
  created_by?: string
  created_at: string
}

interface AgentOption { key: string; name: string; description?: string }

const STATUS_META: Record<string, { color: string; label: string }> = {
  open: { color: 'processing', label: '跟进中' },
  blocked: { color: 'warning', label: '受阻' },
  done: { color: 'success', label: '已完成' },
  cancelled: { color: 'default', label: '已取消' },
}

const ITEM_TYPE_META: Record<string, { color: string; label: string }> = {
  followup: { color: 'blue', label: 'AI跟进' },
  assigned: { color: 'geekblue', label: '他人指派' },
  meeting: { color: 'purple', label: '会议纪要' },
  email: { color: 'cyan', label: '邮件' },
  note: { color: 'default', label: '备忘' },
}

const DISPOSITION_META: Record<string, { color: string; label: string }> = {
  info_only: { color: 'default', label: '纯知会，已自动归档' },
  follow_up: { color: 'blue', label: '已挂入自动跟进' },
  user_action: { color: 'orange', label: '需你亲自处理' },
}

const WO_STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待下达' },
  released: { color: 'blue', label: '已下达' },
  in_progress: { color: 'processing', label: '生产中' },
  on_hold: { color: 'warning', label: '暂停' },
}

const INTERVAL_OPTIONS = [
  { value: 30, label: '30 分钟' },
  { value: 60, label: '1 小时' },
  { value: 120, label: '2 小时' },
  { value: 240, label: '4 小时' },
  { value: 480, label: '8 小时' },
  { value: 1440, label: '24 小时' },
]

const fmtTime = (v?: string) => (v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '-')

const TaskCenter: React.FC = () => {
  const [tasks, setTasks] = useState<FollowupTask[]>([])
  const [workOrders, setWorkOrders] = useState<MyWorkOrder[]>([])
  const [notifications, setNotifications] = useState<InboxNotification[]>([])
  const [agents, setAgents] = useState<AgentOption[]>([])
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState('all')
  const [createOpen, setCreateOpen] = useState(false)
  const [ingestOpen, setIngestOpen] = useState(false)
  const [ingesting, setIngesting] = useState(false)
  const [triageResult, setTriageResult] = useState<any>(null)
  const [editTask, setEditTask] = useState<FollowupTask | null>(null)
  const [logsTask, setLogsTask] = useState<FollowupTask | null>(null)
  const [logs, setLogs] = useState<TaskLog[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [followingId, setFollowingId] = useState<string>('')
  const [createForm] = Form.useForm()
  const [ingestForm] = Form.useForm()
  const [editForm] = Form.useForm()

  const loadInbox = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/task-center/inbox')
      setTasks(res.tasks || [])
      setWorkOrders(res.work_orders || [])
      setNotifications(res.notifications || [])
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadInbox() }, [loadInbox])

  useEffect(() => {
    api.get('/api/v1/chat/agents')
      .then((res: any) => setAgents(res.agents || []))
      .catch(() => {})
  }, [])

  const openCount = tasks.filter(t => t.status === 'open' || t.status === 'blocked').length
  const doneCount = tasks.filter(t => t.status === 'done').length
  const typeCount = (t: string) => tasks.filter(x => x.item_type === t).length

  const visibleTasks = activeTab === 'all'
    ? tasks
    : tasks.filter(t => t.item_type === activeTab)

  const handleCreate = async () => {
    const values = await createForm.validateFields()
    const payload = {
      ...values,
      due_at: values.due_at ? values.due_at.toISOString() : undefined,
      item_type: values.assigned_to ? 'assigned' : 'followup',
    }
    try {
      await api.post('/api/v1/task-center/tasks', payload)
      message.success(values.assigned_to
        ? `任务已指派给 ${values.assigned_to}，并已站内通知对方`
        : '任务已挂入任务中心，将按设定频率自动跟进')
      setCreateOpen(false)
      createForm.resetFields()
      loadInbox()
    } catch { /* 拦截器已提示 */ }
  }

  const handleIngest = async () => {
    const values = await ingestForm.validateFields()
    setIngesting(true)
    try {
      const res: any = await api.post('/api/v1/task-center/ingest', values, { timeout: 120000 })
      setTriageResult(res.triage || {})
      ingestForm.resetFields()
      loadInbox()
    } catch { /* 拦截器已提示 */ } finally {
      setIngesting(false)
    }
  }

  const handleEdit = async () => {
    if (!editTask) return
    const values = await editForm.validateFields()
    try {
      await api.put(`/api/v1/task-center/tasks/${editTask.id}`, {
        ...values,
        assigned_to: values.assigned_to || undefined,
        due_at: values.due_at ? values.due_at.toISOString() : undefined,
      })
      message.success('任务已更新')
      setEditTask(null)
      loadInbox()
    } catch { /* 拦截器已提示 */ }
  }

  const handleFollowNow = async (task: FollowupTask) => {
    setFollowingId(task.id)
    try {
      const res: any = await api.post(
        `/api/v1/task-center/tasks/${task.id}/follow-now`, {}, { timeout: 120000 },
      )
      message.success(`跟进完成：${res.note || res.status}`)
      loadInbox()
    } catch { /* 拦截器已提示 */ } finally {
      setFollowingId('')
    }
  }

  const handleClose = async (task: FollowupTask, status: 'done' | 'cancelled') => {
    try {
      await api.put(`/api/v1/task-center/tasks/${task.id}`, { status })
      message.success(status === 'done' ? '任务已标记完成' : '任务已取消')
      loadInbox()
    } catch { /* 拦截器已提示 */ }
  }

  const handleDelete = async (task: FollowupTask) => {
    try {
      await api.delete(`/api/v1/task-center/tasks/${task.id}`)
      message.success('任务已删除')
      loadInbox()
    } catch { /* 拦截器已提示 */ }
  }

  const handleNotifRead = async (n: InboxNotification) => {
    try {
      await api.put(`/api/v1/notifications/${n.id}/read`)
      setNotifications(prev => prev.filter(x => x.id !== n.id))
    } catch { /* 拦截器已提示 */ }
  }

  const handleNotifToTask = async (n: InboxNotification) => {
    try {
      await api.post(`/api/v1/task-center/notifications/${n.id}/to-task`)
      message.success('已转为跟进任务，AI 将定期核实进展')
      loadInbox()
    } catch { /* 拦截器已提示 */ }
  }

  const openLogs = async (task: FollowupTask) => {
    setLogsTask(task)
    setLogsLoading(true)
    try {
      const res: any = await api.get(`/api/v1/task-center/tasks/${task.id}/logs`)
      setLogs(res.logs || [])
    } catch { /* 拦截器已提示 */ } finally {
      setLogsLoading(false)
    }
  }

  const columns = [
    {
      title: '任务',
      dataIndex: 'title',
      key: 'title',
      width: 280,
      render: (v: string, r: FollowupTask) => {
        const tm = ITEM_TYPE_META[r.item_type] || ITEM_TYPE_META.followup
        return (
          <Space direction="vertical" size={0}>
            <Text strong>{v}</Text>
            <Space size={4} wrap>
              <Tag color={tm.color}>{tm.label}</Tag>
              {r.assigned_to && <Tag icon={<UserSwitchOutlined />}>{r.assigned_to}</Tag>}
              {r.source === 'chatbot' && <Tag color="purple">对话挂入</Tag>}
              {r.source === 'notification' && <Tag color="gold">通知转入</Tag>}
              {r.due_at && (
                <Tag color={new Date(r.due_at) < new Date() && r.status !== 'done' ? 'red' : 'default'}>
                  截止 {fmtTime(r.due_at)}
                </Tag>
              )}
              {r.block_reason && (
                <Tooltip title={r.block_reason}>
                  <Tag color="orange" style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {r.block_reason}
                  </Tag>
                </Tooltip>
              )}
            </Space>
          </Space>
        )
      },
    },
    {
      title: '智能体',
      dataIndex: 'agent_name',
      key: 'agent_name',
      width: 100,
      render: (v?: string) => (v ? <Tag color="blue">{v}</Tag> : <Tag>通用</Tag>),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (v: string) => {
        const meta = STATUS_META[v] || { color: 'default', label: v }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '进度',
      dataIndex: 'progress_pct',
      key: 'progress_pct',
      width: 120,
      render: (v: number, r: FollowupTask) => (
        <Progress percent={v || 0} size="small" status={r.status === 'blocked' ? 'exception' : undefined} />
      ),
    },
    {
      title: '下次跟进',
      dataIndex: 'next_follow_at',
      key: 'next_follow_at',
      width: 150,
      render: (v: string, r: FollowupTask) =>
        r.status === 'open' && v ? (
          <Space size={4}><ClockCircleOutlined style={{ color: '#1677ff' }} /><Text>{fmtTime(v)}</Text></Space>
        ) : <Text type="secondary">-</Text>,
    },
    {
      title: 'AI 摘要 / 最近结论',
      key: 'summary',
      render: (_: unknown, r: FollowupTask) => {
        const txt = r.last_follow_note || r.ai_summary
        return (
          <Tooltip title={txt}>
            <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0, maxWidth: 320 }}>
              {r.ai_summary && !r.last_follow_note && <RobotOutlined style={{ color: '#722ed1', marginRight: 4 }} />}
              {txt || <Text type="secondary">（尚未跟进，已跟进 {r.follow_count} 次）</Text>}
            </Paragraph>
          </Tooltip>
        )
      },
    },
    {
      title: '操作',
      key: 'actions',
      width: 230,
      render: (_: unknown, r: FollowupTask) => (
        <Space size={4} wrap>
          {(r.status === 'open' || r.status === 'blocked') && (
            <Button
              size="small" type="primary" ghost icon={<ThunderboltOutlined />}
              loading={followingId === r.id}
              onClick={() => handleFollowNow(r)}
            >
              立即跟进
            </Button>
          )}
          <Button size="small" icon={<HistoryOutlined />} onClick={() => openLogs(r)}>时间线</Button>
          {(r.status === 'open' || r.status === 'blocked') && (
            <>
              <Button
                size="small"
                onClick={() => {
                  setEditTask(r)
                  editForm.setFieldsValue({
                    follow_interval_minutes: r.follow_interval_minutes,
                    agent_key: r.agent_key || undefined,
                    progress_pct: r.progress_pct,
                    block_reason: r.block_reason || '',
                    assigned_to: r.assigned_to || '',
                  })
                }}
              >
                编辑
              </Button>
              <Popconfirm title="标记为已完成？" onConfirm={() => handleClose(r, 'done')}>
                <Button size="small">完成</Button>
              </Popconfirm>
            </>
          )}
          <Popconfirm title="删除该任务及跟进历史？" onConfirm={() => handleDelete(r)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const woColumns = [
    { title: '工单号', dataIndex: 'work_order_code', key: 'code', width: 180, render: (v: string) => <Text strong>{v}</Text> },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (v: string) => {
        const m = WO_STATUS_META[v] || { color: 'default', label: v }
        return <Tag color={m.color}>{m.label}</Tag>
      },
    },
    { title: '工序', dataIndex: 'process_code', key: 'process', width: 120, render: (v?: string) => v || '-' },
    { title: '计划数量', dataIndex: 'planned_qty', key: 'qty', width: 100 },
    { title: '优先级', dataIndex: 'priority', key: 'priority', width: 80, render: (v?: number) => (v && v >= 8 ? <Tag color="red">{v}</Tag> : v ?? '-') },
    { title: '计划完工', dataIndex: 'planned_due', key: 'due', width: 160, render: (v?: string) => fmtTime(v) },
    { title: '备注', dataIndex: 'remark', key: 'remark', render: (v?: string) => v || '-' },
  ]

  const taskTable = (
    <Table
      rowKey="id"
      size="small"
      loading={loading}
      columns={columns as any}
      dataSource={visibleTasks}
      pagination={{ pageSize: 10, showTotal: t => `共 ${t} 条` }}
      expandable={{
        rowExpandable: (r: FollowupTask) => !!(r.description || r.ai_summary || r.ai_suggestion || r.result_summary),
        expandedRowRender: (r: FollowupTask) => (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            {r.ai_summary && (
              <Alert type="info" showIcon icon={<RobotOutlined />} message="AI 分诊摘要"
                description={<Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{r.ai_summary}</Paragraph>} />
            )}
            {r.ai_suggestion && (
              <Alert type="warning" showIcon icon={<ThunderboltOutlined />} message="AI 建议 / 行动项"
                description={<Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{r.ai_suggestion}</Paragraph>} />
            )}
            {r.description && <Paragraph style={{ marginBottom: 0 }}><Text type="secondary">详情：</Text>{r.description}</Paragraph>}
            {r.result_summary && <Paragraph style={{ marginBottom: 0 }}><Text type="secondary">结果：</Text>{r.result_summary}</Paragraph>}
          </Space>
        ),
      }}
    />
  )

  const tabItems = [
    { key: 'all', label: <span>全部任务 <Badge count={tasks.length} color="#1677ff" size="small" /></span>, children: taskTable },
    ...(['followup', 'assigned', 'meeting', 'email', 'note'] as const).map(t => ({
      key: t,
      label: <span>{ITEM_TYPE_META[t].label} {typeCount(t) > 0 && <Badge count={typeCount(t)} color="#8c8c8c" size="small" />}</span>,
      children: taskTable,
    })),
    {
      key: 'workorders',
      label: <span><ToolOutlined /> 指派工单 <Badge count={workOrders.length} color="#fa8c16" size="small" /></span>,
      children: (
        <Table
          rowKey="id" size="small" loading={loading}
          columns={woColumns as any} dataSource={workOrders}
          pagination={{ pageSize: 10, showTotal: t => `共 ${t} 条` }}
        />
      ),
    },
    {
      key: 'notifications',
      label: <span><BellOutlined /> 未读通知 <Badge count={notifications.length} size="small" /></span>,
      children: (
        <List
          size="small"
          loading={loading}
          dataSource={notifications}
          locale={{ emptyText: '没有未读通知' }}
          renderItem={(n: InboxNotification) => (
            <List.Item
              actions={[
                <Button key="task" size="small" type="link" onClick={() => handleNotifToTask(n)}>转跟进任务</Button>,
                <Button key="read" size="small" type="link" onClick={() => handleNotifRead(n)}>已读</Button>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={6}>
                    {n.severity === 'error' || n.severity === 'warning'
                      ? <Tag color={n.severity === 'error' ? 'red' : 'orange'}>{n.severity === 'error' ? '严重' : '警告'}</Tag>
                      : <Tag>{n.category || '通知'}</Tag>}
                    <Text strong>{n.title}</Text>
                  </Space>
                }
                description={
                  <Space direction="vertical" size={0}>
                    <Text type="secondary">{n.content}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>{fmtTime(n.created_at)}</Text>
                  </Space>
                }
              />
            </List.Item>
          )}
        />
      ),
    },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small"><Statistic title="待处理任务" value={openCount} prefix={<CarryOutOutlined />} valueStyle={{ color: '#1677ff' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="指派给我的工单" value={workOrders.length} prefix={<ToolOutlined />} valueStyle={{ color: '#fa8c16' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="未读通知" value={notifications.length} prefix={<BellOutlined />} valueStyle={{ color: notifications.length ? '#cf1322' : undefined }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="已完成" value={doneCount} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
      </Row>

      <Card
        title={<Space><CarryOutOutlined />任务中心<Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>统一工作台：AI 跟进 · 他人指派 · 会议/邮件接入自动分诊 · 工单与通知聚合</Text></Space>}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadInbox} />
            <Button icon={<ImportOutlined />} onClick={() => setIngestOpen(true)}>接入会议/邮件</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建/指派任务</Button>
          </Space>
        }
      >
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      </Card>

      {/* 新建 / 指派任务 */}
      <Modal
        title="新建 / 指派任务"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        okText="挂入任务中心"
        destroyOnClose
      >
        <Form form={createForm} layout="vertical" initialValues={{ follow_interval_minutes: 120 }}>
          <Form.Item name="title" label="任务标题" rules={[{ required: true, message: '请输入任务标题' }]}>
            <Input placeholder="如：跟进 WO-20260730-001 缺料到货" maxLength={200} />
          </Form.Item>
          <Form.Item name="description" label="任务详情">
            <Input.TextArea rows={3} placeholder="任务背景/原始指令，可选" maxLength={2000} />
          </Form.Item>
          <Form.Item name="assigned_to" label="指派给（用户名，留空则自己跟进）">
            <Input placeholder="如：eric（指派后自动站内通知对方）" maxLength={64} />
          </Form.Item>
          <Form.Item name="due_at" label="截止时间">
            <DatePicker showTime style={{ width: '100%' }} placeholder="可选" />
          </Form.Item>
          <Form.Item name="block_reason" label="当前受阻原因">
            <Input placeholder="如：等供应商交货 / 等审批 / 设备维修中" maxLength={500} />
          </Form.Item>
          <Form.Item name="agent_key" label="负责智能体（不选则自动归类）">
            <Select
              allowClear
              placeholder="自动归类"
              options={agents.map(a => ({ value: a.key, label: a.name }))}
            />
          </Form.Item>
          <Form.Item name="follow_interval_minutes" label="跟进频率" rules={[{ required: true }]}>
            <Select options={INTERVAL_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 接入会议纪要 / 邮件 / 备忘 → AI 分诊 */}
      <Modal
        title={<Space><RobotOutlined />接入内容（AI 自动分诊）</Space>}
        open={ingestOpen}
        onOk={handleIngest}
        onCancel={() => { setIngestOpen(false); setTriageResult(null) }}
        okText="接入并分诊"
        confirmLoading={ingesting}
        destroyOnClose
        width={640}
      >
        <Alert
          type="info" showIcon style={{ marginBottom: 12 }}
          message="粘贴会议纪要、邮件正文或备忘，AI 自动生成摘要、提取行动项并判断处理方式：纯知会内容自动归档不打扰你；需跟进的挂入自动跟进；必须你处理的才提醒你。"
        />
        <Form form={ingestForm} layout="vertical" initialValues={{ item_type: 'meeting', follow_interval_minutes: 120 }}>
          <Form.Item name="item_type" label="内容类型" rules={[{ required: true }]}>
            <Select options={[
              { value: 'meeting', label: '会议纪要' },
              { value: 'email', label: '邮件' },
              { value: 'note', label: '备忘' },
            ]} />
          </Form.Item>
          <Form.Item name="title" label="标题（留空由 AI 生成）">
            <Input maxLength={200} placeholder="可选" />
          </Form.Item>
          <Form.Item name="content" label="正文内容" rules={[{ required: true, message: '请粘贴内容' }]}>
            <Input.TextArea rows={8} maxLength={20000} showCount placeholder="粘贴会议纪要 / 邮件全文…" />
          </Form.Item>
          <Form.Item name="follow_interval_minutes" label="若需跟进，跟进频率">
            <Select options={INTERVAL_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 分诊结果 */}
      <Modal
        title={<Space><RobotOutlined />AI 分诊结果</Space>}
        open={!!triageResult}
        onOk={() => { setTriageResult(null); setIngestOpen(false) }}
        onCancel={() => setTriageResult(null)}
        okText="知道了"
        cancelButtonProps={{ style: { display: 'none' } }}
      >
        {triageResult && (
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Space>
              <Tag color={(DISPOSITION_META[triageResult.disposition] || {}).color || 'default'}>
                {(DISPOSITION_META[triageResult.disposition] || { label: triageResult.disposition }).label}
              </Tag>
              {triageResult.urgency === 'high' && <Tag color="red">高紧急度</Tag>}
              {triageResult.urgency === 'low' && <Tag>低紧急度</Tag>}
            </Space>
            {triageResult.title && <Text strong>{triageResult.title}</Text>}
            {triageResult.summary && <Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{triageResult.summary}</Paragraph>}
            {Array.isArray(triageResult.action_items) && triageResult.action_items.length > 0 && (
              <Alert
                type="warning" showIcon message="提取的行动项"
                description={<ul style={{ margin: 0, paddingLeft: 18 }}>{triageResult.action_items.map((a: string, i: number) => <li key={i}>{a}</li>)}</ul>}
              />
            )}
          </Space>
        )}
      </Modal>

      {/* 编辑任务 */}
      <Modal
        title={`编辑：${editTask?.title || ''}`}
        open={!!editTask}
        onOk={handleEdit}
        onCancel={() => setEditTask(null)}
        okText="保存"
        destroyOnClose
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="follow_interval_minutes" label="跟进频率">
            <Select options={INTERVAL_OPTIONS} />
          </Form.Item>
          <Form.Item name="agent_key" label="负责智能体">
            <Select allowClear placeholder="通用" options={agents.map(a => ({ value: a.key, label: a.name }))} />
          </Form.Item>
          <Form.Item name="assigned_to" label="指派给（用户名）">
            <Input maxLength={64} placeholder="留空则不变更" />
          </Form.Item>
          <Form.Item name="due_at" label="截止时间">
            <DatePicker showTime style={{ width: '100%' }} placeholder="留空则不变更" />
          </Form.Item>
          <Form.Item name="progress_pct" label="进度（%）">
            <InputNumber min={0} max={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="block_reason" label="受阻原因">
            <Input maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 跟进时间线 */}
      <Drawer
        title={`跟进时间线：${logsTask?.title || ''}`}
        open={!!logsTask}
        onClose={() => setLogsTask(null)}
        width={520}
      >
        {logsLoading ? <Text type="secondary">加载中…</Text> : (
          <Timeline
            items={logs.map(l => ({
              color: l.status_after === 'done' ? 'green' : l.status_after === 'blocked' ? 'orange' : 'blue',
              children: (
                <Space direction="vertical" size={0}>
                  <Space size={6}>
                    <Tag color={l.trigger_type === 'schedule' ? 'blue' : l.trigger_type === 'manual' ? 'purple' : 'default'}>
                      {l.trigger_type === 'schedule' ? '定期扫描' : l.trigger_type === 'manual' ? '手动跟进' : '状态变更'}
                    </Tag>
                    {l.status_after && (
                      <Tag color={(STATUS_META[l.status_after] || {}).color}>{(STATUS_META[l.status_after] || { label: l.status_after }).label}</Tag>
                    )}
                    {typeof l.progress_pct === 'number' && <Text type="secondary">{l.progress_pct}%</Text>}
                  </Space>
                  <Text>{l.note || '-'}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>{fmtTime(l.created_at)} · {l.created_by || 'system'}</Text>
                </Space>
              ),
            }))}
          />
        )}
        {!logsLoading && logs.length === 0 && <Text type="secondary">暂无跟进记录</Text>}
      </Drawer>
    </div>
  )
}

export default TaskCenter
