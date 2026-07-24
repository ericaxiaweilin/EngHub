import React, { useEffect, useState } from 'react'
import {
  Card, Table, Tag, Space, Button, Modal, Form, Input, InputNumber,
  Select, DatePicker, message, Typography, Row, Col, Statistic, Tooltip,
} from 'antd'
import {
  ShoppingCartOutlined, PlusOutlined, SplitCellsOutlined,
  CheckCircleOutlined, WarningOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import api from '../../services/api'

const { Title, Text } = Typography
const FACTORY = 'F001'

const statusConfig: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待处理' },
  planning: { color: 'processing', label: '计划中' },
  released: { color: 'blue', label: '已下达' },
  in_progress: { color: 'orange', label: '生产中' },
  completed: { color: 'green', label: '已完成' },
  cancelled: { color: 'red', label: '已取消' },
}

const priorityConfig: Record<string, { color: string; label: string }> = {
  urgent: { color: 'red', label: '紧急' },
  high: { color: 'orange', label: '高' },
  medium: { color: 'blue', label: '中' },
  low: { color: 'default', label: '低' },
}

const OrderManagement: React.FC = () => {
  const [orders, setOrders] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [createVisible, setCreateVisible] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm()

  const loadOrders = async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/orders', { params: { factory_id: FACTORY } })
      setOrders(res?.items || [])
    } catch { /* ignore */ } finally { setLoading(false) }
  }

  useEffect(() => { loadOrders() }, [])

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      setCreating(true)
      await api.post('/api/v1/orders', {
        ...values,
        factory_id: FACTORY,
        delivery_date: values.delivery_date?.format('YYYY-MM-DD'),
      })
      message.success('订单创建成功')
      setCreateVisible(false)
      form.resetFields()
      loadOrders()
    } catch (e: any) {
      if (e?.response) message.error(e.response.data?.detail || '创建失败')
    } finally { setCreating(false) }
  }

  const handleDecompose = async (orderId: string) => {
    try {
      const res: any = await api.post(`/api/v1/orders/${orderId}/decompose`)
      message.success(`拆分成功：生成 ${res.total_work_orders} 个工单`)
      loadOrders()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '拆分失败')
    }
  }

  const handleMaterialCheck = async (orderId: string) => {
    try {
      const res: any = await api.get(`/api/v1/orders/${orderId}/material-check`)
      if (res.ready) {
        message.success('物料齐套，可以开工')
      } else {
        message.warning(`缺料 ${res.shortage_count} 项，请检查`)
      }
      loadOrders()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '检查失败')
    }
  }

  const columns: ColumnsType<any> = [
    { title: '订单号', dataIndex: 'order_code', key: 'code', width: 150,
      render: (v: string) => <Text strong>{v}</Text> },
    { title: '客户', dataIndex: 'customer_name', key: 'customer', width: 100,
      render: (v: string) => v || <Text type="secondary">—</Text> },
    { title: '产品', dataIndex: 'product_name', key: 'product', width: 120 },
    { title: '数量', dataIndex: 'quantity', key: 'qty', width: 80, align: 'right' },
    { title: '交期', dataIndex: 'delivery_date', key: 'delivery', width: 110,
      render: (v: string) => {
        if (!v) return <Text type="secondary">—</Text>
        const isLate = dayjs(v).isBefore(dayjs(), 'day')
        return <Text style={{ color: isLate ? '#f5222d' : undefined }}>{dayjs(v).format('MM/DD')}</Text>
      }},
    { title: '优先级', dataIndex: 'priority', key: 'priority', width: 80,
      render: (v: string) => <Tag color={priorityConfig[v]?.color}>{priorityConfig[v]?.label || v}</Tag> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => <Tag color={statusConfig[v]?.color}>{statusConfig[v]?.label || v}</Tag> },
    { title: '齐套', dataIndex: 'material_ready', key: 'material', width: 70, align: 'center',
      render: (v: boolean, record) => {
        if (record.status === 'pending') return <Text type="secondary">—</Text>
        return v ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <WarningOutlined style={{ color: '#faad14' }} />
      }},
    { title: '操作', key: 'action', width: 180,
      render: (_, record) => (
        <Space size="small">
          {!record.decomposed && record.status === 'pending' && (
            <Tooltip title="拆分为工单">
              <Button size="small" icon={<SplitCellsOutlined />} onClick={() => handleDecompose(record.id)}>拆分</Button>
            </Tooltip>
          )}
          {record.decomposed && (
            <Tooltip title="物料齐套检查">
              <Button size="small" icon={<CheckCircleOutlined />} onClick={() => handleMaterialCheck(record.id)}>齐套</Button>
            </Tooltip>
          )}
        </Space>
      )},
  ]

  const pendingCount = orders.filter(o => o.status === 'pending').length
  const planningCount = orders.filter(o => o.status === 'planning').length

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <ShoppingCartOutlined style={{ fontSize: 22, color: '#1890ff' }} />
            <Title level={4} style={{ margin: 0 }}>销售订单</Title>
            <Tag>{orders.length} 单</Tag>
          </Space>
        </Col>
        <Col>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateVisible(true)}>
            新建订单
          </Button>
        </Col>
      </Row>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="待处理" value={pendingCount} valueStyle={{ color: '#faad14' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="计划中" value={planningCount} valueStyle={{ color: '#1890ff' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="已拆分" value={orders.filter(o => o.decomposed).length} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="物料齐套" value={orders.filter(o => o.material_ready).length} valueStyle={{ color: '#722ed1' }} /></Card></Col>
      </Row>

      <Card>
        <Table
          columns={columns}
          dataSource={orders}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ pageSize: 20 }}
        />
      </Card>

      {/* 新建订单弹窗 */}
      <Modal
        title="新建销售订单"
        open={createVisible}
        onOk={handleCreate}
        onCancel={() => setCreateVisible(false)}
        confirmLoading={creating}
        width={520}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="customer_name" label="客户名称">
                <Input placeholder="客户名称" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="product_id" label="产品编码" rules={[{ required: true }]}>
                <Input placeholder="如: PRD-001" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="product_name" label="产品名称">
                <Input placeholder="产品名称" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="quantity" label="数量" rules={[{ required: true }]}>
                <InputNumber min={1} style={{ width: '100%' }} placeholder="订单数量" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="delivery_date" label="交货日期">
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="priority" label="优先级" initialValue="medium">
                <Select options={[
                  { value: 'urgent', label: '紧急' },
                  { value: 'high', label: '高' },
                  { value: 'medium', label: '中' },
                  { value: 'low', label: '低' },
                ]} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="remark" label="备注">
            <Input.TextArea rows={2} placeholder="备注信息" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default OrderManagement
