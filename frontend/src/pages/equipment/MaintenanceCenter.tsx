import React, { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Space, Button, Modal, Form, Input, InputNumber, Select,
  message, Typography, Row, Col, Statistic, Badge, Alert,
} from 'antd'
import {
  ToolOutlined, PlusOutlined, ThunderboltOutlined, ScheduleOutlined,
  CheckCircleOutlined, WarningOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'

const { Title, Text } = Typography
const FACTORY = 'F001'

const typeConfig: Record<string, { color: string; label: string }> = {
  inspection: { color: 'blue', label: '点检' },
  lubrication: { color: 'cyan', label: '润滑' },
  repair: { color: 'red', label: '维修' },
  overhaul: { color: 'purple', label: '大修' },
  calibration: { color: 'green', label: '校准' },
}
const statusConfig: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待执行' },
  in_progress: { color: 'processing', label: '执行中' },
  completed: { color: 'success', label: '已完成' },
  overdue: { color: 'error', label: '逾期' },
}

const MaintenanceCenter: React.FC = () => {
  const [tasks, setTasks] = useState<any[]>([])
  const [predictions, setPredictions] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [createVisible, setCreateVisible] = useState(false)
  const [form] = Form.useForm()

  const loadTasks = async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/equip-maint/tasks', { params: { factory_id: FACTORY } })
      setTasks(res?.items || [])
    } catch { /* ignore */ } finally { setLoading(false) }
  }

  const loadPredictions = async () => {
    try {
      const res: any = await api.get('/api/v1/equip-maint/fault-prediction', { params: { factory_id: FACTORY } })
      setPredictions(res?.predictions || [])
    } catch { /* ignore */ }
  }

  useEffect(() => { loadTasks(); loadPredictions() }, [])

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      await api.post('/api/v1/equip-maint/task', { ...values, factory_id: FACTORY })
      message.success('维保任务创建成功')
      setCreateVisible(false)
      form.resetFields()
      loadTasks()
    } catch (e: any) {
      if (e?.response) message.error(e.response.data?.detail || '创建失败')
    }
  }

  const handleStart = async (taskId: string) => {
    await api.post(`/api/v1/equip-maint/${taskId}/start`)
    message.success('开始执行')
    loadTasks()
  }

  const handleAutoSchedule = async () => {
    try {
      const res: any = await api.post(`/api/v1/equip-maint/auto-schedule?factory_id=${FACTORY}`)
      message.success(res.message || '自动排程完成')
      loadTasks()
    } catch { message.error('排程失败') }
  }

  const columns: ColumnsType<any> = [
    { title: '任务号', dataIndex: 'task_code', key: 'code', width: 150, render: (v) => <Text strong>{v}</Text> },
    { title: '类型', dataIndex: 'task_type', key: 'type', width: 70,
      render: (v: string) => <Tag color={typeConfig[v]?.color}>{typeConfig[v]?.label || v}</Tag> },
    { title: '设备', dataIndex: 'equipment_name', key: 'equip', width: 120,
      render: (v, r) => v || r.equipment_id },
    { title: '计划日期', dataIndex: 'planned_date', key: 'date', width: 100 },
    { title: '优先级', dataIndex: 'priority', key: 'pri', width: 70,
      render: (v: string) => <Tag color={v === 'urgent' ? 'red' : v === 'high' ? 'orange' : 'default'}>{v}</Tag> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (v: string) => <Tag color={statusConfig[v]?.color}>{statusConfig[v]?.label || v}</Tag> },
    { title: '来源', dataIndex: 'source', key: 'source', width: 80,
      render: (v: string) => v === 'auto_schedule' ? <Tag color="geekblue">自动</Tag> : v === 'prediction' ? <Tag color="volcano">预测</Tag> : <Tag>手动</Tag> },
    { title: '操作', key: 'action', width: 80,
      render: (_, r) => r.status === 'pending' && <Button size="small" onClick={() => handleStart(r.id)}>开始</Button> },
  ]

  const highRisk = predictions.filter(p => p.risk_level === 'high')
  const pendingCount = tasks.filter(t => t.status === 'pending').length

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <ToolOutlined style={{ fontSize: 22, color: '#fa8c16' }} />
            <Title level={4} style={{ margin: 0 }}>设备维护中心</Title>
          </Space>
        </Col>
        <Col>
          <Space>
            <Button icon={<ScheduleOutlined />} onClick={handleAutoSchedule}>自动排程</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateVisible(true)}>新建任务</Button>
          </Space>
        </Col>
      </Row>

      {/* 统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="待执行" value={pendingCount} valueStyle={{ color: '#faad14' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="执行中" value={tasks.filter(t => t.status === 'in_progress').length} valueStyle={{ color: '#1890ff' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="已完成" value={tasks.filter(t => t.status === 'completed').length} valueStyle={{ color: '#52c41a' }} prefix={<CheckCircleOutlined />} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="高风险设备" value={highRisk.length} valueStyle={{ color: '#f5222d' }} prefix={<WarningOutlined />} /></Card></Col>
      </Row>

      {/* 故障预测预警 */}
      {highRisk.length > 0 && (
        <Alert type="error" showIcon style={{ marginBottom: 16 }}
          message={`${highRisk.length} 台设备故障风险高`}
          description={highRisk.map(p => `${p.equipment_id}: 30天停机${p.breakdown_count_30d}次/${p.total_downtime_min}分钟`).join('；')}
        />
      )}

      <Card>
        <Table columns={columns} dataSource={tasks} rowKey="id" loading={loading} size="small" pagination={{ pageSize: 15 }} />
      </Card>

      {/* 新建任务 */}
      <Modal title="新建维保任务" open={createVisible} onOk={handleCreate} onCancel={() => setCreateVisible(false)} width={500}>
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="task_type" label="任务类型" rules={[{ required: true }]}>
                <Select options={Object.entries(typeConfig).map(([k, v]) => ({ value: k, label: v.label }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="equipment_id" label="设备ID" rules={[{ required: true }]}>
                <Input placeholder="设备ID" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="equipment_name" label="设备名称">
                <Input placeholder="设备名称" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="priority" label="优先级" initialValue="medium">
                <Select options={[{ value: 'urgent', label: '紧急' }, { value: 'high', label: '高' }, { value: 'medium', label: '中' }, { value: 'low', label: '低' }]} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="planned_date" label="计划日期">
            <Input placeholder="YYYY-MM-DD（默认今天）" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default MaintenanceCenter
