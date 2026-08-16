/**
 * RCC 调度任务中心 — 智能体提交的调度任务审批流 + Chatbot 资源工单流转
 * 审批通过 → 自动回写 followup_tasks 解除阻塞（core/rcc/services.py approve_task 已接）
 */
import { useEffect, useState } from 'react'
import { Card, Table, Tag, Button, Space, message, Timeline, Badge, Input, Popconfirm, Statistic } from 'antd'
import { CheckOutlined, CloseOutlined, RobotOutlined, CarryOutOutlined, ReloadOutlined } from '@ant-design/icons'
import axios from '../../services/api'
import { COLORS } from './RCCCommandCenter'

const API = '/api/v1/rcc'

const TASK_STATUS_META: Record<string, { label: string; color: string }> = {
  pending: { label: '待审批', color: 'gold' },
  approved: { label: '已批准', color: 'green' },
  rejected: { label: '已拒绝', color: 'red' },
  executing: { label: '执行中', color: 'blue' },
  completed: { label: '已完成', color: 'green' },
  failed: { label: '失败', color: 'red' },
  escalated: { label: '已升级', color: 'volcano' },
}

const TICKET_STATUS_META: Record<string, { label: string; color: string }> = {
  open: { label: '待处理', color: 'gold' },
  routed: { label: '已路由', color: 'blue' },
  resolved: { label: '已解决', color: 'green' },
  closed: { label: '已关闭', color: 'default' },
}

const TYPE_LABEL: Record<string, string> = {
  resource_allocation: '资源分配', supplier_followup: '供应商跟催', equipment_maintenance: '设备维修',
  approval: '审批', manpower: '人力调度', data_fix: '数据修复', dispatch: '派工', scheduling: '排程',
  resource_request: '资源请求', equipment_request: '设备请求', manpower_request: '人力请求', material_request: '物料请求',
}

export default function RCCDispatchCenter() {
  const [tasks, setTasks] = useState<any[]>([])
  const [tickets, setTickets] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [approver, setApprover] = useState('eric')

  const fetchAll = async () => {
    setLoading(true)
    try {
      const [t, tk] = await Promise.allSettled([
        axios.get(`${API}/tasks`),
        axios.get(`${API}/chatbot/tickets`),
      ])
      if (t.status === 'fulfilled') setTasks((t.value as any)?.items || (t.value as any) || [])
      if (tk.status === 'fulfilled') setTickets((tk.value as any)?.items || (tk.value as any) || [])
    } finally { setLoading(false) }
  }

  useEffect(() => { fetchAll() }, [])

  const approve = async (taskId: string) => {
    try {
      await axios.post(`${API}/tasks/${taskId}/approve`, null, { params: { comment: `由 ${approver} 审批通过`, approver_id: approver } })
      message.success('已批准，关联任务将解除阻塞重新跟进')
      fetchAll()
    } catch (e: any) { message.error(`审批失败: ${e.response?.data?.detail || e.message}`) }
  }

  const reject = async (taskId: string) => {
    const reason = prompt('拒绝原因：') || '未说明'
    try {
      await axios.post(`${API}/tasks/${taskId}/reject`, null, { params: { reason, approver_id: approver } })
      message.success('已拒绝')
      fetchAll()
    } catch (e: any) { message.error(`拒绝失败: ${e.response?.data?.detail || e.message}`) }
  }

  const taskColumns = [
    { title: '任务编号', dataIndex: 'task_code', key: 'code', width: 180, render: (v: string) => <span style={{ color: COLORS.accent, fontFamily: 'monospace' }}>{v}</span> },
    { title: '类型', dataIndex: 'task_type', key: 'type', width: 110, render: (v: string) => <Tag color="blue">{TYPE_LABEL[v] || v}</Tag> },
    { title: '标题', dataIndex: 'title', key: 'title', render: (v: string) => <span style={{ color: COLORS.text }}>{v}</span> },
    { title: '请求方', dataIndex: 'requested_by', key: 'req', width: 130, render: (v: string) => <Tag icon={<RobotOutlined />}>{v || '-'}</Tag> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 100, render: (v: string) => { const m = TASK_STATUS_META[v] || { label: v, color: 'default' }; return <Tag color={m.color}>{m.label}</Tag> } },
    { title: '影响说明', dataIndex: 'expected_impact_summary', key: 'impact', width: 220, ellipsis: true, render: (v: string) => <span style={{ color: COLORS.textDim, fontSize: 12 }}>{v || '-'}</span> },
    {
      title: '操作', key: 'op', width: 160,
      render: (_: any, r: any) => r.status === 'pending' ? (
        <Space size={4}>
          <Button size="small" type="primary" icon={<CheckOutlined />} onClick={() => approve(r.id)}
            style={{ background: COLORS.success, borderColor: COLORS.success }}>批准</Button>
          <Button size="small" danger icon={<CloseOutlined />} onClick={() => reject(r.id)}>拒绝</Button>
        </Space>
      ) : (
        <Tag color="default">{r.approved_by ? `审批: ${r.approved_by}` : '-'}</Tag>
      ),
    },
  ]

  const ticketColumns = [
    { title: '工单号', dataIndex: 'ticket_code', key: 'code', width: 200, render: (v: string) => <span style={{ color: COLORS.accentBlue, fontFamily: 'monospace' }}>{v}</span> },
    { title: '类型', dataIndex: 'ticket_type', key: 'type', width: 110, render: (v: string) => <Tag color="purple">{TYPE_LABEL[v] || v}</Tag> },
    { title: '请求人', dataIndex: 'requester_id', key: 'req', width: 120 },
    { title: '需求内容', dataIndex: 'raw_message', key: 'msg', render: (v: string) => <span style={{ color: COLORS.text }}>{v}</span> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (v: string) => { const m = TICKET_STATUS_META[v] || { label: v, color: 'default' }; return <Tag color={m.color}>{m.label}</Tag> } },
    { title: '路由目标', key: 'route', width: 160, render: (_: any, r: any) => r.routed_to_position ? <Tag>{r.routed_to_position}@{r.routed_to_org_unit?.slice(0, 8)}</Tag> : <Tag color="default">未路由</Tag> },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {/* 状态卡 */}
      <Space size={16}>
        <Card size="small" style={{ background: COLORS.bgCard, borderColor: COLORS.border, minWidth: 160 }}>
          <Statistic value={tasks.filter(t => t.status === 'pending').length} title="待审批调度任务" prefix={<CarryOutOutlined />} valueStyle={{ color: COLORS.warning }} />
        </Card>
        <Card size="small" style={{ background: COLORS.bgCard, borderColor: COLORS.border, minWidth: 160 }}>
          <Statistic value={tickets.filter(t => t.status === 'open').length} title="待处理资源工单" prefix={<CarryOutOutlined />} valueStyle={{ color: COLORS.accentBlue }} />
        </Card>
        <Input value={approver} onChange={e => setApprover(e.target.value)} style={{ width: 120, background: COLORS.bg, borderColor: COLORS.border, color: COLORS.text }} placeholder="审批人" />
        <Button icon={<ReloadOutlined spin={loading} />} onClick={fetchAll} style={{ borderColor: COLORS.border, color: COLORS.textDim }}>刷新</Button>
      </Space>

      {/* 调度任务审批流（智能体 → RCC） */}
      <Card size="small" title={<Space><Badge color={COLORS.warning} />调度任务审批流（智能体受阻自动提交）</Space>}
        style={{ background: COLORS.bgCard, borderColor: COLORS.border }}
        styles={{ header: { color: COLORS.text, borderBottom: `1px solid ${COLORS.border}` } }}>
        <Table rowKey="id" size="small" loading={loading} columns={taskColumns as any} dataSource={tasks}
          pagination={{ pageSize: 8 }} locale={{ emptyText: '暂无调度任务（智能体受阻时会自动提交）' }} />
      </Card>

      {/* Chatbot 资源工单流转（员工 → RCC） */}
      <Card size="small" title={<Space><Badge color={COLORS.accentBlue} />Chatbot 资源工单流转（员工个人 chatbot → RCC）</Space>}
        style={{ background: COLORS.bgCard, borderColor: COLORS.border }}
        styles={{ header: { color: COLORS.text, borderBottom: `1px solid ${COLORS.border}` } }}>
        <Table rowKey="id" size="small" loading={loading} columns={ticketColumns as any} dataSource={tickets}
          pagination={{ pageSize: 8 }} locale={{ emptyText: '暂无资源工单（员工在个人 chatbot 提交资源需求后显示）' }} />
      </Card>
    </Space>
  )
}
