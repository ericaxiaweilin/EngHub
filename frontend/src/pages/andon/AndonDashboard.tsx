

import { useState, useEffect } from 'react'
import { Card, Table, Tag, Button, Modal, Form, Input, message, Descriptions, Space } from 'antd'
import { PlusOutlined, RiseOutlined } from '@ant-design/icons'
import api from '../../services/api'

const FACTORY = 'F001'

const CATEGORY_META: Record<string, { label: string; color: string; icon: string }> = {
  equipment_repair: { label: '设备维修', color: 'orange', icon: '🔧' },
  material_call: { label: '物料呼叫', color: 'blue', icon: '📦' },
  quality_issue: { label: '质量异常', color: 'red', icon: '⚠️' },
  tech_support: { label: '技术支持', color: 'purple', icon: '💡' },
  admin_matter: { label: '行政事务', color: 'default', icon: '📋' },
}

const STATUS_META: Record<string, { label: string; color: string }> = {
  open: { label: '开放中', color: 'green' },
  assigned: { label: '已指派', color: 'cyan' },
  claimed: { label: '已认领', color: 'blue' },
  upgrading: { label: '升级中', color: 'orange' },
  in_progress: { label: '处理中', color: 'processing' },
  resolved: { label: '已解决', color: 'success' },
  closed: { label: '已关闭', color: 'default' },
  cancelled: { label: '已取消', color: 'error' },
}

export default function Andon2Dashboard() {
  const [tickets, setTickets] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [form] = Form.useForm()
  const [selectedCategory] = useState('equipment_repair')

  const fetchTickets = async () => {
    setLoading(true)
    try {
      const data: any = await api.get('/api/v1/andon/tickets', { params: { factory_id: FACTORY } })
      setTickets(data.items || [])
    } catch (err) {
      console.error('获取安灯工单失败:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTickets()
    // 每30秒自动刷新一次
    const timer = setInterval(fetchTickets, 30000)
    return () => clearInterval(timer)
  }, [])

  const handleCreateTicket = async () => {
    try {
      const values = await form.validateFields()
      await api.post('/api/v1/andon/tickets', {
        factory_id: FACTORY,
        category_code: selectedCategory,
        title: values.title,
        description: values.description,
      })
      message.success('安灯工单创建成功')
      form.resetFields()
      setModalVisible(false)
      fetchTickets()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '创建失败')
    }
  }

  const columns = [
    {
      title: '工单号',
      dataIndex: 'ticket_code',
      key: 'ticket_code',
      fixed: 'left' as const,
      width: 180,
    },
    {
      title: '类别',
      key: 'category_code',
      render: (val: string) => {
        const meta = CATEGORY_META[val] || { label: val, color: 'default' }
        return <Tag icon={<span>{meta.icon}</span>} color={meta.color}>{meta.label}</Tag>
      },
      width: 120,
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      render: (val: string) => <Tag color={val === 'urgent' ? 'red' : val === 'high' ? 'orange' : 'default'}>{val}</Tag>,
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (val: string) => {
        const meta = STATUS_META[val] || { label: val, color: 'default' }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
      width: 100,
    },
    {
      title: '升级级别',
      dataIndex: 'escalation_level',
      key: 'escalation_level',
      render: (val: number) => val > 0 ? <Tag color="red">L{val}</Tag> : '-',
      width: 90,
    },
    {
      title: '负责人',
      dataIndex: 'assigned_to',
      key: 'assigned_to',
      width: 100,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
    },
  ]

  return (
    <Card
      title="🏭 Andon 2.0 智能小工单系统"
      extra={
        <Space>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalVisible(true)}>
            新建安灯工单
          </Button>
          <Button icon={<RiseOutlined />} onClick={fetchTickets}>
            刷新
          </Button>
        </Space>
      }
    >
      {/* 统计卡片 */}
      <Descriptions column={4} size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="开放中">{tickets.filter(t => t.status === 'open').length}</Descriptions.Item>
        <Descriptions.Item label="处理中">{tickets.filter(t => ['assigned', 'claimed', 'in_progress'].includes(t.status)).length}</Descriptions.Item>
        <Descriptions.Item label="升级中">{tickets.filter(t => ['upgrading', 'escalated'].includes(t.status)).length}</Descriptions.Item>
        <Descriptions.Item label="今日解决">{tickets.filter(t => t.status === 'resolved').length}</Descriptions.Item>
      </Descriptions>

      <Table
        dataSource={tickets}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
        scroll={{ x: 1200 }}
      />

      {/* 新建工单弹窗 */}
      <Modal
        title="新建安灯工单"
        open={modalVisible}
        onOk={handleCreateTicket}
        onCancel={() => setModalVisible(false)}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="例：CNC-001 主轴异响，需维修" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} placeholder="详细描述问题现象、影响范围..." />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}


