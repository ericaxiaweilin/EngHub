import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, InputNumber,
  message, Row, Col, Statistic, Popconfirm, Tooltip, Progress,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ExperimentOutlined,
  ClockCircleOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'

interface TimeStudy {
  id: string
  factory_id: string
  station_id: string
  operation_name: string
  operator_id: string
  average_time: number
  normal_time: number
  allowed_time: number
  status: string
  created_at: string
}

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  completed: { color: 'green', text: '已完成' },
  in_progress: { color: 'blue', text: '进行中' },
  pending: { color: 'default', text: '待开始' },
  draft: { color: 'orange', text: '草稿' },
}

const TimeStudies: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<TimeStudy[]>([])
  const [loading, setLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<TimeStudy | null>(null)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.get(API_ENDPOINTS.IE_TIME_STUDIES, {
        params: { factory_id: factory, limit: 500 },
      })
      setData(res.items || res || [])
    } catch {
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [factory])

  const filteredData = data.filter(item =>
    (item.operation_name || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
    (item.station_id || '').toLowerCase().includes(searchTerm.toLowerCase())
  )

  const completedCount = data.filter(d => d.status === 'completed').length
  const avgAllowed = data.length > 0
    ? (data.reduce((s, d) => s + (d.allowed_time || 0), 0) / data.length).toFixed(2)
    : '0'

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      if (editing) {
        await api.put(`${API_ENDPOINTS.IE_TIME_STUDIES}/${editing.id}`, values)
        message.success('更新成功')
      } else {
        await api.post(API_ENDPOINTS.IE_TIME_STUDIES, { ...values, factory_id: factory })
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
      await api.delete(`${API_ENDPOINTS.IE_TIME_STUDIES}/${id}`)
      message.success('已删除')
      fetchData()
    } catch {
      message.error('删除失败')
    }
  }

  const columns: ColumnsType<TimeStudy> = [
    { title: '工位', dataIndex: 'station_id', key: 'station_id', width: 100 },
    { title: '作业名称', dataIndex: 'operation_name', key: 'operation_name', width: 160, ellipsis: true },
    { title: '操作员', dataIndex: 'operator_id', key: 'operator_id', width: 100, render: v => v || '-' },
    {
      title: '平均时间(s)', dataIndex: 'average_time', key: 'average_time', width: 110,
      sorter: (a, b) => a.average_time - b.average_time,
      render: v => <span style={{ fontWeight: 600 }}>{(v || 0).toFixed(2)}</span>,
    },
    {
      title: '正常时间(s)', dataIndex: 'normal_time', key: 'normal_time', width: 110,
      render: v => (v || 0).toFixed(2),
    },
    {
      title: '允许时间(s)', dataIndex: 'allowed_time', key: 'allowed_time', width: 110,
      render: v => <span style={{ color: '#1890ff', fontWeight: 600 }}>{(v || 0).toFixed(2)}</span>,
    },
    {
      title: '宽放率', key: 'allowance', width: 100,
      render: (_, r) => {
        const rate = r.normal_time > 0 ? ((r.allowed_time - r.normal_time) / r.normal_time * 100) : 0
        return <Progress percent={Math.round(rate)} size="small" strokeColor={rate > 20 ? '#faad14' : '#52c41a'} format={p => `${p}%`} />
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: v => {
        const s = STATUS_MAP[v] || { color: 'default', text: v || '-' }
        return <Tag color={s.color}>{s.text}</Tag>
      },
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 110,
      render: v => v ? dayjs(v).format('YYYY-MM-DD') : '-',
    },
    {
      title: '操作', key: 'action', width: 100, fixed: 'right',
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title="编辑">
            <Button type="link" size="small" icon={<EditOutlined />} onClick={() => { setEditing(record); form.setFieldsValue(record); setModalOpen(true) }} />
          </Tooltip>
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
          <Card size="small"><Statistic title="研究记录" value={data.length} prefix={<ExperimentOutlined />} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="已完成" value={completedCount} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="平均允许时间" value={avgAllowed} suffix="s" prefix={<ClockCircleOutlined />} valueStyle={{ color: '#1890ff' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="进行中" value={data.filter(d => d.status === 'in_progress').length} valueStyle={{ color: '#faad14' }} /></Card>
        </Col>
      </Row>

      <Card
        title="时间研究"
        extra={
          <Space>
            <Select value={factory} onChange={setFactory} style={{ width: 120 }} size="small">
              <Select.Option value="F001">F001 厂区</Select.Option>
              <Select.Option value="F01">F01 厂区</Select.Option>
            </Select>
            <Input.Search placeholder="搜索作业/工位..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} allowClear style={{ width: 180 }} size="small" />
            <Button type="primary" icon={<PlusOutlined />} size="small" onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true) }}>新增</Button>
          </Space>
        }
      >
        <Table dataSource={filteredData} columns={columns} loading={loading} rowKey="id" scroll={{ x: 1100 }} size="middle"
          pagination={{ pageSize: 15, showTotal: t => `共 ${t} 条`, showSizeChanger: true }} />
      </Card>

      <Modal title={editing ? '编辑时间研究' : '新增时间研究'} open={modalOpen} onOk={handleSave}
        onCancel={() => { setModalOpen(false); setEditing(null) }} width={520} okText="保存" cancelText="取消">
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="station_id" label="工位ID" rules={[{ required: true }]}>
                <Input placeholder="如 ST-01" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="operator_id" label="操作员ID">
                <Input placeholder="可选" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="operation_name" label="作业名称" rules={[{ required: true }]}>
            <Input placeholder="如 装配轴承" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="average_time" label="平均时间(s)" rules={[{ required: true }]}>
                <InputNumber min={0} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="normal_time" label="正常时间(s)" rules={[{ required: true }]}>
                <InputNumber min={0} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="allowed_time" label="允许时间(s)" rules={[{ required: true }]}>
                <InputNumber min={0} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="status" label="状态" initialValue="pending">
            <Select>
              <Select.Option value="pending">待开始</Select.Option>
              <Select.Option value="in_progress">进行中</Select.Option>
              <Select.Option value="completed">已完成</Select.Option>
              <Select.Option value="draft">草稿</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default TimeStudies
