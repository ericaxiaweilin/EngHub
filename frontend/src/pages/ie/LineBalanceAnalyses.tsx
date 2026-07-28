import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, InputNumber,
  message, Row, Col, Statistic, Popconfirm, Tooltip, Progress,
} from 'antd'
import { PlusOutlined, DeleteOutlined, PlayCircleOutlined, DashboardOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'

interface LineBalance {
  id: string
  factory_id: string
  line_id: string
  product_id: string
  takt_time: number
  cycle_time: number
  balance_efficiency: number
  num_stations: number
  total_workload: number
  status: string
  created_at: string
}

const MOCK_DATA: LineBalance[] = [
  { id: 'lb-1', factory_id: 'factory-sh-01', line_id: 'LINE-01', product_id: 'PRD-001', takt_time: 60.0, cycle_time: 55.2, balance_efficiency: 0.92, num_stations: 6, total_workload: 331.2, status: 'completed', created_at: '2026-06-01' },
  { id: 'lb-2', factory_id: 'factory-sh-01', line_id: 'LINE-02', product_id: 'PRD-002', takt_time: 45.0, cycle_time: 42.8, balance_efficiency: 0.88, num_stations: 5, total_workload: 214.0, status: 'completed', created_at: '2026-06-05' },
  { id: 'lb-3', factory_id: 'factory-sh-01', line_id: 'LINE-03', product_id: 'PRD-003', takt_time: 90.0, cycle_time: 78.5, balance_efficiency: 0.72, num_stations: 8, total_workload: 628.0, status: 'running', created_at: '2026-06-10' },
  { id: 'lb-4', factory_id: 'factory-sh-01', line_id: 'LINE-01', product_id: 'PRD-004', takt_time: 30.0, cycle_time: 28.1, balance_efficiency: 0.95, num_stations: 4, total_workload: 112.4, status: 'completed', created_at: '2026-06-15' },
  { id: 'lb-5', factory_id: 'factory-sh-01', line_id: 'LINE-04', product_id: 'PRD-005', takt_time: 120.0, cycle_time: 98.0, balance_efficiency: 0.65, num_stations: 10, total_workload: 980.0, status: 'completed', created_at: '2026-06-20' },
]

const LineBalanceAnalyses: React.FC = () => {
  const [factory, setFactory] = useState('factory-sh-01')
  const [data, setData] = useState<LineBalance[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.get(API_ENDPOINTS.IE_LINE_BALANCE_ANALYSES, { params: { factory_id: factory, limit: 200 } })
      const items = res.items || res || []
      setData(items.length > 0 ? items : MOCK_DATA)
    } catch { setData(MOCK_DATA) } finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [factory])

  const avgEff = data.length > 0 ? (data.reduce((s, d) => s + (d.balance_efficiency || 0), 0) / data.length).toFixed(1) : '0'

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      await api.post(API_ENDPOINTS.IE_LINE_BALANCE_ANALYSES, { ...values, factory_id: factory })
      message.success('分析已创建')
      setModalOpen(false)
      form.resetFields()
      fetchData()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '创建失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`${API_ENDPOINTS.IE_LINE_BALANCE_ANALYSES}/${id}`)
      message.success('已删除')
      fetchData()
    } catch { message.error('删除失败') }
  }

  const columns: ColumnsType<LineBalance> = [
    { title: '产线', dataIndex: 'line_id', key: 'line_id', width: 100 },
    { title: '产品', dataIndex: 'product_id', key: 'product_id', width: 110, ellipsis: true },
    {
      title: '节拍时间(s)', dataIndex: 'takt_time', key: 'takt_time', width: 110,
      render: v => <span style={{ fontWeight: 600 }}>{(v || 0).toFixed(1)}</span>,
    },
    {
      title: '周期时间(s)', dataIndex: 'cycle_time', key: 'cycle_time', width: 110,
      render: v => (v || 0).toFixed(1),
    },
    { title: '工位数', dataIndex: 'num_stations', key: 'num_stations', width: 80 },
    {
      title: '平衡效率', dataIndex: 'balance_efficiency', key: 'balance_efficiency', width: 140,
      sorter: (a, b) => a.balance_efficiency - b.balance_efficiency,
      render: v => {
        const pct = Math.round((v || 0) * 100)
        return <Progress percent={pct} size="small" strokeColor={pct >= 85 ? '#52c41a' : pct >= 70 ? '#faad14' : '#ff4d4f'} />
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: v => <Tag color={v === 'completed' ? 'green' : v === 'running' ? 'blue' : 'default'}>{v === 'completed' ? '完成' : v === 'running' ? '运行中' : v || '-'}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 110, render: v => v ? dayjs(v).format('YYYY-MM-DD') : '-' },
    {
      title: '操作', key: 'action', width: 70, fixed: 'right',
      render: (_, r) => (
        <Popconfirm title="确认删除?" onConfirm={() => handleDelete(r.id)}>
          <Tooltip title="删除"><Button type="link" size="small" danger icon={<DeleteOutlined />} /></Tooltip>
        </Popconfirm>
      ),
    },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="分析记录" value={data.length} prefix={<DashboardOutlined />} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="平均平衡效率" value={avgEff} suffix="%" valueStyle={{ color: '#1890ff' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="达标(≥85%)" value={data.filter(d => (d.balance_efficiency || 0) >= 0.85).length} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="需改善(<70%)" value={data.filter(d => (d.balance_efficiency || 0) < 0.7).length} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
      </Row>

      <Card title="产线平衡分析" extra={
        <Space>
          <Select value={factory} onChange={setFactory} style={{ width: 140 }} size="small">
            <Select.Option value="factory-sh-01">上海工厂</Select.Option>
            <Select.Option value="FAC_ELEC_DEMO_2026">电子工厂</Select.Option>
            <Select.Option value="FAC_MECH_001">机械工厂</Select.Option>
          </Select>
          <Button type="primary" icon={<PlayCircleOutlined />} size="small" onClick={() => { form.resetFields(); setModalOpen(true) }}>执行新分析</Button>
        </Space>
      }>
        <Table dataSource={data} columns={columns} loading={loading} rowKey="id" scroll={{ x: 1000 }} size="middle"
          pagination={{ pageSize: 15, showTotal: t => `共 ${t} 条` }} />
      </Card>

      <Modal title="执行线平衡分析" open={modalOpen} onOk={handleCreate} onCancel={() => setModalOpen(false)} okText="开始分析" cancelText="取消">
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="line_id" label="产线ID" rules={[{ required: true }]}><Input placeholder="如 LINE-01" /></Form.Item>
          <Form.Item name="product_id" label="产品ID" rules={[{ required: true }]}><Input placeholder="如 PRD-001" /></Form.Item>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="takt_time" label="节拍时间(s)" rules={[{ required: true }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item name="num_stations" label="工位数" initialValue={4}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>
    </div>
  )
}

export default LineBalanceAnalyses
