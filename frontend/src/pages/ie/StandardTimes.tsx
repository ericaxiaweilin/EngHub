import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, InputNumber,
  message, Row, Col, Statistic, Popconfirm, Tooltip,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ClockCircleOutlined,
  CheckCircleOutlined, FieldTimeOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'

interface StandardTime {
  id: string
  factory_id: string
  product_id: string
  routing_step: string
  operation_name: string
  station_id?: string
  standard_time_min: number
  effective_standard_time: number
  version: string
  is_active: boolean
  validity_start: string
  created_at: string
}

const MOCK_DATA: StandardTime[] = [
  { id: 'mock-1', factory_id: 'factory-sh-01', product_id: 'PRD-001', routing_step: 'OP10', operation_name: '精车外圆', station_id: 'ST-01', standard_time_min: 2.35, effective_standard_time: 2.12, version: 'v1', is_active: true, validity_start: '2026-01-01', created_at: '2026-01-01' },
  { id: 'mock-2', factory_id: 'factory-sh-01', product_id: 'PRD-001', routing_step: 'OP20', operation_name: '铣平面', station_id: 'ST-02', standard_time_min: 3.80, effective_standard_time: 3.42, version: 'v1', is_active: true, validity_start: '2026-01-01', created_at: '2026-01-01' },
  { id: 'mock-3', factory_id: 'factory-sh-01', product_id: 'PRD-002', routing_step: 'OP10', operation_name: '钻孔', station_id: 'ST-03', standard_time_min: 1.55, effective_standard_time: 1.40, version: 'v2', is_active: true, validity_start: '2026-02-01', created_at: '2026-02-01' },
  { id: 'mock-4', factory_id: 'factory-sh-01', product_id: 'PRD-002', routing_step: 'OP30', operation_name: '磨削精加工', station_id: 'ST-04', standard_time_min: 4.20, effective_standard_time: 3.78, version: 'v1', is_active: true, validity_start: '2026-01-15', created_at: '2026-01-15' },
  { id: 'mock-5', factory_id: 'factory-sh-01', product_id: 'PRD-003', routing_step: 'OP10', operation_name: '组装前检验', station_id: 'ST-05', standard_time_min: 0.85, effective_standard_time: 0.77, version: 'v1', is_active: false, validity_start: '2025-12-01', created_at: '2025-12-01' },
  { id: 'mock-6', factory_id: 'factory-sh-01', product_id: 'PRD-003', routing_step: 'OP20', operation_name: '总装', station_id: 'ST-06', standard_time_min: 5.60, effective_standard_time: 5.04, version: 'v1', is_active: true, validity_start: '2026-03-01', created_at: '2026-03-01' },
  { id: 'mock-7', factory_id: 'factory-sh-01', product_id: 'PRD-001', routing_step: 'OP30', operation_name: '动平衡检测', station_id: 'ST-07', standard_time_min: 1.20, effective_standard_time: 1.08, version: 'v1', is_active: true, validity_start: '2026-01-01', created_at: '2026-01-01' },
  { id: 'mock-8', factory_id: 'factory-sh-01', product_id: 'PRD-004', routing_step: 'OP10', operation_name: '下料', station_id: 'ST-01', standard_time_min: 0.45, effective_standard_time: 0.41, version: 'v1', is_active: true, validity_start: '2026-04-01', created_at: '2026-04-01' },
]

const StandardTimes: React.FC = () => {
  const [factory, setFactory] = useState('factory-sh-01')
  const [data, setData] = useState<StandardTime[]>([])
  const [loading, setLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<StandardTime | null>(null)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.get(API_ENDPOINTS.IE_STANDARD_TIMES, {
        params: { factory_id: factory, limit: 500 },
      })
      const items = res.items || res || []
      setData(items)
    } catch {
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [factory])

  const filteredData = data.filter(item =>
    (item.operation_name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
    (item.product_id || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
    (item.routing_step || '').toLowerCase().includes(searchTerm.toLowerCase())
  )

  const activeCount = data.filter(d => d.is_active).length
  const avgTime = data.length > 0
    ? (data.reduce((s, d) => s + (d.standard_time_min || 0), 0) / data.length).toFixed(2)
    : '0'

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      if (editing) {
        await api.put(API_ENDPOINTS.IE_STANDARD_TIME(editing.id), values)
        message.success('更新成功')
      } else {
        await api.post(API_ENDPOINTS.IE_STANDARD_TIMES, { ...values, factory_id: factory })
        message.success('创建成功')
      }
      setModalOpen(false)
      form.resetFields()
      setEditing(null)
      fetchData()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await api.delete(API_ENDPOINTS.IE_STANDARD_TIME(id))
      message.success('已删除')
      fetchData()
    } catch {
      message.error('删除失败')
    }
  }

  const openEdit = (record: StandardTime) => {
    setEditing(record)
    form.setFieldsValue(record)
    setModalOpen(true)
  }

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setModalOpen(true)
  }

  const columns: ColumnsType<StandardTime> = [
    { title: '产品ID', dataIndex: 'product_id', key: 'product_id', width: 110, ellipsis: true },
    { title: '工序', dataIndex: 'routing_step', key: 'routing_step', width: 80 },
    { title: '作业名称', dataIndex: 'operation_name', key: 'operation_name', width: 160, ellipsis: true },
    { title: '工位', dataIndex: 'station_id', key: 'station_id', width: 90, render: v => v || '-' },
    {
      title: '标准时间(min)', dataIndex: 'standard_time_min', key: 'standard_time_min', width: 120,
      sorter: (a, b) => a.standard_time_min - b.standard_time_min,
      render: v => <span style={{ fontWeight: 600, color: '#1890ff' }}>{(v || 0).toFixed(2)}</span>,
    },
    {
      title: '有效工时', dataIndex: 'effective_standard_time', key: 'effective_standard_time', width: 100,
      render: v => (v || 0).toFixed(2),
    },
    { title: '版本', dataIndex: 'version', key: 'version', width: 60, render: v => <Tag>{v || 'v1'}</Tag> },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active', width: 70,
      render: bool => <Tag color={bool ? 'green' : 'default'}>{bool ? '有效' : '停用'}</Tag>,
    },
    {
      title: '生效日期', dataIndex: 'validity_start', key: 'validity_start', width: 110,
      render: v => v ? dayjs(v).format('YYYY-MM-DD') : '-',
    },
    {
      title: '操作', key: 'action', width: 100, fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title="编辑"><Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} /></Tooltip>
          <Popconfirm title="确认删除?" onConfirm={() => handleDelete(record.id)}>
            <Tooltip title="删除"><Button type="link" size="small" danger icon={<DeleteOutlined />} /></Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small"><Statistic title="工时记录总数" value={data.length} prefix={<FieldTimeOutlined />} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="有效记录" value={activeCount} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="平均标准时间" value={avgTime} suffix="min" prefix={<ClockCircleOutlined />} valueStyle={{ color: '#1890ff' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="停用记录" value={data.length - activeCount} valueStyle={{ color: '#999' }} /></Card>
        </Col>
      </Row>

      <Card
        title="标准工时管理"
        extra={
          <Space>
            <Select value={factory} onChange={setFactory} style={{ width: 140 }} size="small">
              <Select.Option value="factory-sh-01">上海工厂</Select.Option>
              <Select.Option value="FAC_ELEC_DEMO_2026">电子工厂</Select.Option>
              <Select.Option value="FAC_MECH_001">机械工厂</Select.Option>
            </Select>
            <Input.Search placeholder="搜索作业/产品..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} allowClear style={{ width: 200 }} size="small" />
            <Button type="primary" icon={<PlusOutlined />} size="small" onClick={openCreate}>新增</Button>
          </Space>
        }
      >
        <Table
          dataSource={filteredData}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 15, showTotal: t => `共 ${t} 条`, showSizeChanger: true }}
          rowKey="id"
          scroll={{ x: 1100 }}
          size="middle"
        />
      </Card>

      <Modal
        title={editing ? '编辑标准工时' : '新增标准工时'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => { setModalOpen(false); setEditing(null) }}
        width={560}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="product_id" label="产品ID" rules={[{ required: true, message: '请输入产品ID' }]}>
                <Input placeholder="如 PRD-001" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="routing_step" label="工序步骤" rules={[{ required: true, message: '请输入工序' }]}>
                <Input placeholder="如 OP10" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="operation_name" label="作业名称" rules={[{ required: true, message: '请输入作业名称' }]}>
            <Input placeholder="如 精车外圆" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="station_id" label="工位ID">
                <Input placeholder="可选" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="standard_time_min" label="标准时间(min)" rules={[{ required: true, message: '必填' }]}>
                <InputNumber min={0} step={0.01} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="effective_standard_time" label="有效工时(min)">
                <InputNumber min={0} step={0.01} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="version" label="版本" initialValue="v1">
                <Input />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="is_active" label="状态" initialValue={true}>
                <Select>
                  <Select.Option value={true}>有效</Select.Option>
                  <Select.Option value={false}>停用</Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="validity_start" label="生效日期">
                <Input placeholder="2026-01-01" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  )
}

export default StandardTimes
