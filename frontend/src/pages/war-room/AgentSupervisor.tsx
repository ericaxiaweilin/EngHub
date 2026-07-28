/**
 * 智能体监督看板 - Agent Supervisor Dashboard
 * 
 * 实时展示8个智能体运行状态、任务进度、健康度、预测性预警
 * 对接后端 /api/v1/agent-supervisor/*
 */
import React, { useState, useEffect, useCallback } from 'react'
import {
  Card, Row, Col, Tag, Table, Statistic, Space, Button, Badge,
  Timeline, Alert, Typography, Tooltip, Progress, Tabs, message,
} from 'antd'
import {
  RobotOutlined, ReloadOutlined, CheckCircleOutlined,
  WarningOutlined, ClockCircleOutlined, ThunderboltOutlined,
  HeartOutlined, DashboardOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const { Text, Title } = Typography
const FACTORY = localStorage.getItem('active_factory_id') || 'FAC_MECH_001'

interface AgentStatus {
  key: string
  name: string
  description: string
  sensing: string
  last_action: any
  running_tasks: number
  stalled_tasks: number
  status: string
}

interface DashboardData {
  factory_id: string
  total_agents: number
  agents: AgentStatus[]
  recent_tasks: any[]
  health: { level: string; message: string; active: number; stalled: number; total: number }
}

const sensingMap: Record<string, { text: string; color: string }> = {
  'event': { text: '事件驱动', color: 'blue' },
  'schedule': { text: '定时扫描', color: 'green' },
  'event+schedule': { text: '事件+定时', color: 'purple' },
  'schedule+event': { text: '定时+事件', color: 'purple' },
  'schedule+prediction': { text: '定时+预测', color: 'orange' },
  'prediction': { text: '预测驱动', color: 'red' },
}

const AgentSupervisor: React.FC = () => {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [predictions, setPredictions] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [predictLoading, setPredictLoading] = useState(false)

  const loadDashboard = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get('/api/v1/agent-supervisor/dashboard', { params: { factory_id: FACTORY } })
      setDashboard(res)
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  const loadPredictions = useCallback(async () => {
    setPredictLoading(true)
    try {
      const res = await api.get('/api/v1/agent-supervisor/predict', { params: { factory_id: FACTORY } })
      setPredictions(res.predictions || [])
    } catch { /* ignore */ } finally { setPredictLoading(false) }
  }, [])

  useEffect(() => { loadDashboard(); loadPredictions() }, [loadDashboard, loadPredictions])

  const healthColor = dashboard?.health?.level === 'healthy' ? '#52c41a'
    : dashboard?.health?.level === 'warning' ? '#faad14' : '#f5222d'

  const taskColumns = [
    { title: '智能体', dataIndex: 'agent_name', key: 'agent', width: 120 },
    { title: '任务类型', dataIndex: 'task_type', key: 'type', width: 130 },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (s: string) => (
      <Tag color={s === 'completed' ? 'success' : s === 'running' ? 'processing' : s === 'stalled' ? 'error' : 'default'}>
        {s === 'completed' ? '完成' : s === 'running' ? '运行中' : s === 'stalled' ? '卡住' : s === 'failed' ? '失败' : s}
      </Tag>
    )},
    { title: '进度', dataIndex: 'progress_pct', key: 'pct', width: 120, render: (v: number) => (
      <Progress percent={v || 0} size="small" status={v >= 100 ? 'success' : 'active'} />
    )},
    { title: '开始时间', dataIndex: 'started_at', key: 'start', width: 160, render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-' },
    { title: '验证', dataIndex: 'verified', key: 'verified', width: 70, render: (v: boolean) => v ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <ClockCircleOutlined style={{ color: '#999' }} /> },
  ]

  return (
    <div style={{ padding: 16 }}>
      {/* 顶部健康度 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="系统健康度" value={dashboard?.health?.message || '加载中'}
              valueStyle={{ fontSize: 14, color: healthColor }}
              prefix={<HeartOutlined />} />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small"><Statistic title="智能体总数" value={dashboard?.total_agents || 8} prefix={<RobotOutlined />} /></Card>
        </Col>
        <Col span={4}>
          <Card size="small"><Statistic title="正常运行" value={dashboard?.health?.active || 0} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col span={4}>
          <Card size="small"><Statistic title="卡住" value={dashboard?.health?.stalled || 0} valueStyle={{ color: dashboard?.health?.stalled ? '#f5222d' : undefined }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => { loadDashboard(); loadPredictions() }} loading={loading}>刷新</Button>
              <Button icon={<ThunderboltOutlined />} onClick={loadPredictions} loading={predictLoading}>预测分析</Button>
            </Space>
          </Card>
        </Col>
      </Row>

      <Tabs defaultActiveKey="agents" items={[
        {
          key: 'agents',
          label: <span><RobotOutlined /> 智能体状态</span>,
          children: (
            <Row gutter={[12, 12]}>
              {(dashboard?.agents || []).map(agent => (
                <Col span={8} key={agent.key}>
                  <Card size="small" hoverable
                    title={<Space><Badge status={agent.status === 'active' ? 'success' : 'error'} />{agent.name}</Space>}
                    extra={<Tag color={sensingMap[agent.sensing]?.color}>{sensingMap[agent.sensing]?.text || agent.sensing}</Tag>}
                  >
                    <Text type="secondary" style={{ fontSize: 12 }}>{agent.description}</Text>
                    <div style={{ marginTop: 8 }}>
                      <Space size="large">
                        <Statistic title="运行中" value={agent.running_tasks} valueStyle={{ fontSize: 16 }} />
                        <Statistic title="卡住" value={agent.stalled_tasks} valueStyle={{ fontSize: 16, color: agent.stalled_tasks > 0 ? '#f5222d' : undefined }} />
                      </Space>
                    </div>
                    {agent.last_action && (
                      <div style={{ marginTop: 8, fontSize: 11, color: '#999' }}>
                        最近: {agent.last_action.action_taken} ({agent.last_action.trigger_type})
                      </div>
                    )}
                  </Card>
                </Col>
              ))}
            </Row>
          ),
        },
        {
          key: 'tasks',
          label: <span><DashboardOutlined /> 最近任务</span>,
          children: (
            <Table columns={taskColumns} dataSource={dashboard?.recent_tasks || []}
              rowKey={(_, i) => String(i)} size="small" pagination={{ pageSize: 10 }} loading={loading} />
          ),
        },
        {
          key: 'predictions',
          label: <span><WarningOutlined /> 预测预警 {predictions.length > 0 && <Badge count={predictions.length} />}</span>,
          children: (
            <div>
              {predictions.length === 0 ? (
                <Alert type="success" message="当前无预测性风险" showIcon />
              ) : (
                <Timeline items={predictions.map((p, i) => ({
                  key: i,
                  color: p.severity === 'high' ? 'red' : 'orange',
                  children: (
                    <div>
                      <Space>
                        <Tag color={p.severity === 'high' ? 'error' : 'warning'}>{p.severity === 'high' ? '高风险' : '中风险'}</Tag>
                        <Tag>{p.type === 'delivery_risk' ? '交期风险' : p.type === 'material_shortage' ? '物料短缺' : '设备PM'}</Tag>
                        <Text strong>{p.target}</Text>
                      </Space>
                      <div style={{ marginTop: 4 }}><Text>{p.prediction}</Text></div>
                      <div><Text type="secondary">{p.suggestion} → {p.auto_action}</Text></div>
                    </div>
                  ),
                }))} />
              )}
            </div>
          ),
        },
      ]} />
    </div>
  )
}

export default AgentSupervisor
