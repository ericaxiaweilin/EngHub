import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Tabs, Table, Button, Tag, Space, Row, Col, Statistic, Modal, Form,
  Input, Select, message, Empty, Spin,
} from 'antd'
import {
  ToolOutlined, DashboardOutlined, PlusOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const FACTORY = 'F001'

// ============== 设备看板 ==============
const EquipDashboard: React.FC = () => {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    (async () => {
      setLoading(true)
      try {
        const res: any = await api.get('/api/v1/equipment/dashboard', { params: { factory_id: FACTORY } })
        setData(res)
      } catch { /* */ } finally { setLoading(false) }
    })()
  }, [])

  if (loading) return <Spin />
  if (!data) return <Empty description="暂无设备数据" />

  const statusColors: Record<string, string> = { available: 'success', running: 'processing', maintenance: 'warning', broken: 'error', idle: 'default' }
  const statusText: Record<string, string> = { available: '可用', running: '运行中', maintenance: '维护中', broken: '故障', idle: '空闲' }

  return (
    <div>
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={5}><Card size="small"><Statistic title="设备总数" value={data.total_equipment} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="OEE (7天)" value={data.oee_7d?.oee} suffix="%" valueStyle={{ color: (data.oee_7d?.oee || 0) >= 85 ? '#52c41a' : '#faad14' }} /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="可用率" value={data.oee_7d?.availability} suffix="%" /></Card></Col>
        <Col span={5}><Card size="small"><Statistic title="待处理维护" value={data.open_maintenance_orders} valueStyle={{ color: data.open_maintenance_orders > 0 ? '#f5222d' : undefined }} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="停机(7天)" value={data.oee_7d?.downtime_minutes} suffix="min" /></Card></Col>
      </Row>

      <Row gutter={12}>
        <Col span={12}>
          <Card size="small" title="设备状态分布">
            <Space wrap>
              {Object.entries(data.status_distribution || {}).map(([k, v]) => (
                <Tag key={k} color={statusColors[k] || 'default'}>{statusText[k] || k}: {v as number}</Tag>
              ))}
            </Space>
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="近7天停机分类">
            {data.downtime_7d?.length ? (
              <Space direction="vertical" style={{ width: '100%' }}>
                {data.downtime_7d.map((d: any, i: number) => (
                  <div key={i} style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <Tag color={d.category === 'breakdown' ? 'error' : 'warning'}>{d.category}</Tag>
                    <span>{d.count}次 / {d.total_minutes}min</span>
                  </div>
                ))}
              </Space>
            ) : <Empty description="无停机记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

// ============== 维护工单 ==============
const MaintenancePanel: React.FC = () => {
  const [orders, setOrders] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [createModal, setCreateModal] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/equipment/maintenance', { params: { factory_id: FACTORY } })
      setOrders(res.items || [])
    } catch { /* */ } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const handleCreate = async () => {
    const vals = await form.validateFields()
    try {
      await api.post('/api/v1/equipment/maintenance', { ...vals, factory_id: FACTORY })
      message.success('维护工单已创建')
      setCreateModal(false); form.resetFields(); load()
    } catch (e: any) { message.error(e?.response?.data?.detail || '失败') }
  }

  const statusColor: Record<string, string> = { open: 'error', in_progress: 'processing', completed: 'success', cancelled: 'default' }
  const typeText: Record<string, string> = { preventive: '预防', corrective: ' corrective', predictive: '预测' }

  return (
    <div>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)} style={{ marginBottom: 12 }}>新建维护工单</Button>
      <Table dataSource={orders} rowKey="id" size="small" loading={loading} pagination={{ pageSize: 10 }}
        columns={[
          { title: '工单号', dataIndex: 'order_code', width: 180 },
          { title: '类型', dataIndex: 'maintenance_type', width: 80, render: (v: string) => <Tag>{typeText[v] || v}</Tag> },
          { title: '优先级', dataIndex: 'priority', width: 80, render: (v: string) => <Tag color={v === 'high' ? 'red' : v === 'medium' ? 'orange' : 'default'}>{v}</Tag> },
          { title: '状态', dataIndex: 'status', width: 100, render: (v: string) => <Tag color={statusColor[v]}>{v}</Tag> },
          { title: '描述', dataIndex: 'description', ellipsis: true },
          { title: '创建时间', dataIndex: 'created_at', width: 110, render: (v: string) => v?.slice(0, 10) },
        ]}
      />
      <Modal title="新建维护工单" open={createModal} onOk={handleCreate} onCancel={() => setCreateModal(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="equipment_id" label="设备ID" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="maintenance_type" label="类型" initialValue="corrective">
            <Select options={[{ value: 'corrective', label: '纠正性维护' }, { value: 'preventive', label: '预防性维护' }, { value: 'predictive', label: '预测性维护' }]} />
          </Form.Item>
          <Form.Item name="priority" label="优先级" initialValue="medium">
            <Select options={[{ value: 'high', label: '高' }, { value: 'medium', label: '中' }, { value: 'low', label: '低' }]} />
          </Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ============== 主页面 ==============
const EquipmentCenter: React.FC = () => {
  return (
    <Tabs size="small" defaultActiveKey="dashboard" items={[
      { key: 'dashboard', label: <span><DashboardOutlined /> 设备看板</span>, children: <EquipDashboard /> },
      { key: 'maintenance', label: <span><ToolOutlined /> 维护工单</span>, children: <MaintenancePanel /> },
    ]} />
  )
}

export default EquipmentCenter
