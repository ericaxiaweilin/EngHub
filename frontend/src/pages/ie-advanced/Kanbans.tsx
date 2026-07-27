import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, InputNumber,
  message, Row, Col, Statistic, Popconfirm,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, AppstoreOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'

interface Kanban {
  id: string
  factory_id: string
  kanban_id: string
  part_number: string
  part_name: string
  quantity_per_container: number
  num_containers: number
  replenishment_time_hours: number
  status: string
  created_at: string
}

const Kanbans: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<Kanban[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Kanban | null>(null)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.get(API_ENDPOINTS.IE_ADVANCED_KANBANS, { params: { factory_id: factory, limit: 200 } })
      setData(res.items || res || [])
    } catch { setData([]) } finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [factory])

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      if (editing) {
        await api.put(`${API_ENDPOINTS.IE_ADVANCED_KANBANS}/${editing.id}`, values)
        message.success('更新成功')
      } else {
        await api.post(API_ENDPOINTS.IE_ADVANCED_KANBANS, { ...values, factory_id: factory })
        message.success('创建成功')
      }
      setModalOpen(false); form.resetFields(); setEditing(null); fetchData()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    try { await api.delete(`${API_ENDPOINTS.IE_ADVANCED_KANBANS}/${id}`); message.success('已删除'); fetchData() }
    catch { message.error('删除失败') }
  }

  const columns: ColumnsType<Kanban> = [
    { title: '看板号', dataIndex: 'kanban_id', key: 'kanban_id', width: 120 },
    { title: '零件号', dataIndex: 'part_number', key: 'part_number', width: 110, ellipsis: true },
    { title: '零件名', dataIndex: 'part_name', key: 'part_name', width: 140, ellipsis: true },
    { title: '容器容量', dataIndex: 'quantity_per_container', key: 'quantity_per_container', width: 90, render: v => <span style={{ fontWeight: 600 }}>{v || 0}</span> },
    { title: '容器数', dataIndex: 'num_containers', key: 'num_containers', width: 80 },
    {
      title: '总库存量', key: 'total', width: 90,
      render: (_, r) => <span style={{ color: '#1890ff' }}>{(r.quantity_per_container || 0) * (r.num_containers || 0)}</span>,
    },
    { title: '补货周期(h)', dataIndex: 'replenishment_time_hours', key: 'replenishment_time_hours', width: 100, render: v => (v || 0).toFixed(1) },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: v => <Tag color={v === 'active' ? 'green' : v === 'empty' ? 'red' : 'orange'}>{v === 'active' ? '正常' : v === 'empty' ? '空箱' : v || '-'}</Tag>,
    },
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
        <Col span={8}><Card size="small"><Statistic title="看板总数" value={data.length} prefix={<AppstoreOutlined />} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="正常" value={data.filter(d => d.status === 'active').length} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="空箱(需补货)" value={data.filter(d => d.status === 'empty').length} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
      </Row>

      <Card title="Kanban看板管理" extra={
        <Space>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }} size="small">
            <Select.Option value="F001">F001 厂区</Select.Option><Select.Option value="F01">F01 厂区</Select.Option>
          </Select>
          <Button type="primary" icon={<PlusOutlined />} size="small" onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true) }}>新增</Button>
        </Space>
      }>
        <Table dataSource={data} columns={columns} loading={loading} rowKey="id" scroll={{ x: 1000 }} size="middle" pagination={{ pageSize: 15, showTotal: t => `共 ${t} 条` }} />
      </Card>

      <Modal title={editing ? '编辑看板' : '新增看板'} open={modalOpen} onOk={handleSave} onCancel={() => { setModalOpen(false); setEditing(null) }} okText="保存" cancelText="取消">
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="kanban_id" label="看板号" rules={[{ required: true }]}><Input placeholder="如 KB-001" /></Form.Item></Col>
            <Col span={12}><Form.Item name="part_number" label="零件号" rules={[{ required: true }]}><Input /></Form.Item></Col>
          </Row>
          <Form.Item name="part_name" label="零件名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="quantity_per_container" label="容器容量" rules={[{ required: true }]}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="num_containers" label="容器数" rules={[{ required: true }]}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="replenishment_time_hours" label="补货周期(h)"><InputNumber min={0} step={0.5} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Form.Item name="status" label="状态" initialValue="active">
            <Select><Select.Option value="active">正常</Select.Option><Select.Option value="empty">空箱</Select.Option><Select.Option value="transit">在途</Select.Option></Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default Kanbans
