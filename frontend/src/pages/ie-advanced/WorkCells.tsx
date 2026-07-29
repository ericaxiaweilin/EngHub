import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, InputNumber,
  message, Row, Col, Statistic, Popconfirm,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, ClusterOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'

interface WorkCell {
  id: string
  factory_id: string
  cell_name: string
  cell_type: string
  capacity_per_hour: number
  num_operators: number
  num_machines: number
  product_family: string
  status: string
  created_at: string
}

const MOCK_DATA: WorkCell[] = [
  { id: 'wc-1', factory_id: 'factory-sh-01', cell_name: 'CNC加工单元', cell_type: 'machining', capacity_per_hour: 12, num_operators: 2, num_machines: 4, product_family: '轴类件', status: 'active', created_at: '2026-05-01' },
  { id: 'wc-2', factory_id: 'factory-sh-01', cell_name: '装配单元A', cell_type: 'assembly', capacity_per_hour: 30, num_operators: 4, num_machines: 2, product_family: '电机总成', status: 'active', created_at: '2026-05-10' },
  { id: 'wc-3', factory_id: 'factory-sh-01', cell_name: '焊接单元', cell_type: 'welding', capacity_per_hour: 20, num_operators: 3, num_machines: 3, product_family: '结构件', status: 'active', created_at: '2026-06-01' },
  { id: 'wc-4', factory_id: 'factory-sh-01', cell_name: '检测包装单元', cell_type: 'inspection', capacity_per_hour: 50, num_operators: 2, num_machines: 1, product_family: '成品', status: 'maintenance', created_at: '2026-06-15' },
]

const WorkCells: React.FC = () => {
  const [factory, setFactory] = useState('factory-sh-01')
  const [data, setData] = useState<WorkCell[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<WorkCell | null>(null)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.get(API_ENDPOINTS.IE_ADVANCED_WORK_CELLS, { params: { factory_id: factory, limit: 200 } })
      const items = res.items || res || []
      setData(items)
    } catch { setData([]) } finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [factory])

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      if (editing) {
        await api.put(`${API_ENDPOINTS.IE_ADVANCED_WORK_CELLS}/${editing.id}`, values)
        message.success('更新成功')
      } else {
        await api.post(API_ENDPOINTS.IE_ADVANCED_WORK_CELLS, { ...values, factory_id: factory })
        message.success('创建成功')
      }
      setModalOpen(false); form.resetFields(); setEditing(null); fetchData()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    try { await api.delete(`${API_ENDPOINTS.IE_ADVANCED_WORK_CELLS}/${id}`); message.success('已删除'); fetchData() }
    catch { message.error('删除失败') }
  }

  const columns: ColumnsType<WorkCell> = [
    { title: '单元名称', dataIndex: 'cell_name', key: 'cell_name', width: 140, ellipsis: true },
    { title: '类型', dataIndex: 'cell_type', key: 'cell_type', width: 90, render: v => <Tag>{v || '-'}</Tag> },
    { title: '产品族', dataIndex: 'product_family', key: 'product_family', width: 120, ellipsis: true, render: v => v || '-' },
    { title: '产能/时', dataIndex: 'capacity_per_hour', key: 'capacity_per_hour', width: 90, render: v => <span style={{ fontWeight: 600 }}>{v || 0}</span> },
    { title: '操作员', dataIndex: 'num_operators', key: 'num_operators', width: 80 },
    { title: '设备数', dataIndex: 'num_machines', key: 'num_machines', width: 80 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: v => <Tag color={v === 'active' ? 'green' : v === 'maintenance' ? 'orange' : 'default'}>{v === 'active' ? '运行' : v === 'maintenance' ? '维护' : v || '-'}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 100, render: v => v ? dayjs(v).format('YYYY-MM-DD') : '-' },
    {
      title: '操作', key: 'action', width: 90, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => { setEditing(r); form.setFieldsValue(r); setModalOpen(true) }} />
          <Popconfirm title="确认删除?" onConfirm={() => handleDelete(r.id)}><Button type="link" size="small" danger icon={<DeleteOutlined />} /></Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card size="small"><Statistic title="工作单元" value={data.length} prefix={<ClusterOutlined />} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="运行中" value={data.filter(d => d.status === 'active').length} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="总操作员" value={data.reduce((s, d) => s + (d.num_operators || 0), 0)} valueStyle={{ color: '#1890ff' }} /></Card></Col>
      </Row>

      <Card title="工作单元布局" extra={
        <Space>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }} size="small">
            <Select.Option value="factory-sh-01">上海工厂</Select.Option><Select.Option value="FAC_ELEC_DEMO_2026">电子工厂</Select.Option><Select.Option value="FAC_MECH_001">机械工厂</Select.Option>
          </Select>
          <Button type="primary" icon={<PlusOutlined />} size="small" onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true) }}>新增</Button>
        </Space>
      }>
        <Table dataSource={data} columns={columns} loading={loading} rowKey="id" scroll={{ x: 1000 }} size="middle" pagination={{ pageSize: 15, showTotal: t => `共 ${t} 条` }} />
      </Card>

      <Modal title={editing ? '编辑工作单元' : '新增工作单元'} open={modalOpen} onOk={handleSave} onCancel={() => { setModalOpen(false); setEditing(null) }} okText="保存" cancelText="取消">
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="cell_name" label="单元名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="cell_type" label="类型" initialValue="assembly"><Select><Select.Option value="assembly">装配</Select.Option><Select.Option value="machining">加工</Select.Option><Select.Option value="testing">测试</Select.Option><Select.Option value="packaging">包装</Select.Option></Select></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="capacity_per_hour" label="产能/时"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="num_operators" label="操作员数"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="num_machines" label="设备数"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="product_family" label="产品族"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="status" label="状态" initialValue="active"><Select><Select.Option value="active">运行</Select.Option><Select.Option value="maintenance">维护</Select.Option><Select.Option value="inactive">停用</Select.Option></Select></Form.Item></Col>
          </Row>
        </Form>
      </Modal>
    </div>
  )
}

export default WorkCells
