/**
 * 任务中心：暂时无法一次完成的任务挂账跟进
 * - 智能体按用户设置的频率定期扫描核实进展（后台自动）
 * - 支持手动"立即跟进"、调整频率、查看跟进时间线、关单
 */
import React, { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Col, Drawer, Form, Input, InputNumber, Modal, Popconfirm,
  Progress, Row, Select, Space, Statistic, Table, Tag, Timeline, Tooltip, Typography, message,
} from 'antd'
import {
  CarryOutOutlined, ClockCircleOutlined, DeleteOutlined, HistoryOutlined,
  PlusOutlined, ReloadOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const { Text, Paragraph } = Typography

interface FollowupTask {
  id: string
  title: string
  description?: string
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
  created_by: string
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
  const [agents, setAgents] = useState<AgentOption[]>([])
  const [loading, setLoading] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [createOpen, setCreateOpen] = useState(false)
  const [editTask, setEditTask] = useState<FollowupTask | null>(null)
  const [logsTask, setLogsTask] = useState<FollowupTask | null>(null)
  const [logs, setLogs] = useState<TaskLog[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [followingId, setFollowingId] = useState<string>('')
  const [createForm] = Form.useForm()
  const [editForm] = Form.useForm()

  const loadTasks = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/task-center/tasks', {
        params: statusFilter ? { status: statusFilter } : {},
      })
      setTasks(res.tasks || [])
    } catch { /* 拦截器已提示 */ } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => { loadTasks() }, [loadTasks])

  useEffect(() => {
    api.get('/api/v1/chat/agents')
      .then((res: any) => setAgents(res.agents || []))
      .catch(() => {})
  }, [])

  const openCount = tasks.filter(t => t.status === 'open').length
  const blockedCount = tasks.filter(t => t.status === 'blocked').length
  const doneCount = tasks.filter(t => t.status === 'done').length

  const handleCreate = async () => {
    const values = await createForm.validateFields()
    try {
      await api.post('/api/v1/task-center/tasks', values)
      message.success('任务已挂入任务中心，将按设定频率自动跟进')
      setCreateOpen(false)
      createForm.resetFields()
      loadTasks()
    } catch { /* 拦截器已提示 */ }
  }

  const handleEdit = async () => {
    if (!editTask) return
    const values = await editForm.validateFields()
    try {
      await api.put(`/api/v1/task-center/tasks/${editTask.id}`, values)
      message.success('任务已更新')
      setEditTask(null)
      loadTasks()
    } catch { /* 拦截器已提示 */ }
  }

  const handleFollowNow = async (task: FollowupTask) => {
    setFollowingId(task.id)
    try {
      const res: any = await api.post(
        `/api/v1/task-center/tasks/${task.id}/follow-now`, {}, { timeout: 120000 },
      )
      message.success(`跟进完成：${res.note || res.status}`)
      loadTasks()
    } catch { /* 拦截器已提示 */ } finally {
      setFollowingId('')
    }
  }

  const handleClose = async (task: FollowupTask, status: 'done' | 'cancelled') => {
    try {
      await api.put(`/api/v1/task-center/tasks/${task.id}`, { status })
      message.success(status === 'done' ? '任务已标记完成' : '任务已取消')
      loadTasks()
    } catch { /* 拦截器已提示 */ }
  }

  const handleDelete = async (task: FollowupTask) => {
    try {
      await api.delete(`/api/v1/task-center/tasks/${task.id}`)
      message.success('任务已删除')
      loadTasks()
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
      width: 260,
      render: (v: string, r: FollowupTask) => (
        <Space direction="vertical" size={0}>
          <Text strong>{v}</Text>
          <Space size={4}>
            {r.source === 'chatbot' && <Tag color="purple">对话挂入</Tag>}
            {r.block_reason && (
              <Tooltip title={r.block_reason}>
                <Tag color="orange" style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {r.block_reason}
                </Tag>
              </Tooltip>
            )}
          </Space>
        </Space>
      ),
    },
    {
      title: '智能体',
      dataIndex: 'agent_name',
      key: 'agent_name',
      width: 110,
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
      width: 130,
      render: (v: number, r: FollowupTask) => (
        <Progress percent={v || 0} size="small" status={r.status === 'blocked' ? 'exception' : undefined} />
      ),
    },
    {
      title: '跟进频率',
      dataIndex: 'follow_interval_minutes',
      key: 'interval',
      width: 100,
      render: (v: number) => {
        const opt = INTERVAL_OPTIONS.find(o => o.value === v)
        return <Text>{opt ? opt.label : `${v} 分钟`}</Text>
      },
    },
    {
      title: '下次跟进',
      dataIndex: 'next_follow_at',
      key: 'next_follow_at',
      width: 150,
      render: (v: string, r: FollowupTask) =>
        r.status === 'open' ? (
          <Space size={4}><ClockCircleOutlined style={{ color: '#1677ff' }} /><Text>{fmtTime(v)}</Text></Space>
        ) : <Text type="secondary">-</Text>,
    },
    {
      title: '最近跟进结论',
      dataIndex: 'last_follow_note',
      key: 'last_follow_note',
      render: (v: string, r: FollowupTask) => (
        <Tooltip title={v}>
          <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0, maxWidth: 320 }}>
            {v || <Text type="secondary">（尚未跟进，已跟进 {r.follow_count} 次）</Text>}
          </Paragraph>
        </Tooltip>
      ),
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

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small"><Statistic title="跟进中" value={openCount} prefix={<CarryOutOutlined />} valueStyle={{ color: '#1677ff' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="受阻" value={blockedCount} valueStyle={{ color: '#faad14' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="已完成" value={doneCount} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="全部任务" value={tasks.length} /></Card>
        </Col>
      </Row>

      <Card
        title={<Space><CarryOutOutlined />任务中心<Text type="secondary" style={{ fontSize: 12, fontWeight: 400 }}>暂时无法完成的任务挂账，智能体按频率定期跟进</Text></Space>}
        extra={
          <Space>
            <Select
              value={statusFilter}
              onChange={setStatusFilter}
              style={{ width: 120 }}
              options={[
                { value: '', label: '全部状态' },
                { value: 'open', label: '跟进中' },
                { value: 'blocked', label: '受阻' },
                { value: 'done', label: '已完成' },
                { value: 'cancelled', label: '已取消' },
              ]}
            />
            <Button icon={<ReloadOutlined />} onClick={loadTasks} />
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>挂账任务</Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns as any}
          dataSource={tasks}
          pagination={{ pageSize: 10, showTotal: t => `共 ${t} 条` }}
        />
      </Card>

      {/* 新建任务 */}
      <Modal
        title="挂账跟进任务"
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
