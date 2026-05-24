import { Card, Table, Button, Tag, Space, Modal, Form, Input, Select, message } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import { useState } from 'react'

const { TextArea } = Input

interface WorkOrder {
  id: number
  code: string
  product_name: string
  quantity: number
  status: string
  priority: string
  planned_start_date: string
  planned_end_date: string
}

const mockData: WorkOrder[] = [
  { id: 1, code: 'WO-2024-001', product_name: '产品 A', quantity: 1000, status: 'pending', priority: 'high', planned_start_date: '2024-01-15', planned_end_date: '2024-01-20' },
  { id: 2, code: 'WO-2024-002', product_name: '产品 B', quantity: 500, status: 'in_progress', priority: 'normal', planned_start_date: '2024-01-16', planned_end_date: '2024-01-22' },
  { id: 3, code: 'WO-2024-003', product_name: '产品 C', quantity: 800, status: 'completed', priority: 'low', planned_start_date: '2024-01-10', planned_end_date: '2024-01-15' },
]

const statusMap: Record<string, { color: string; text: string }> = {
  pending: { color: 'orange', text: '待下发' },
  in_progress: { color: 'blue', text: '进行中' },
  completed: { color: 'green', text: '已完成' },
  cancelled: { color: 'red', text: '已取消' },
}

export default function WorkOrderList() {
  const [data] = useState<WorkOrder[]>(mockData)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [form] = Form.useForm()

  const columns = [
    {
      title: '工单号',
      dataIndex: 'code',
      key: 'code',
    },
    {
      title: '产品名称',
      dataIndex: 'product_name',
      key: 'product_name',
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      key: 'quantity',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const config = statusMap[status] || { color: 'default', text: status }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      render: (priority: string) => {
        const colorMap: Record<string, string> = {
          high: 'red',
          normal: 'blue',
          low: 'green',
        }
        return <Tag color={colorMap[priority] || 'default'}>{priority}</Tag>
      },
    },
    {
      title: '计划开始',
      dataIndex: 'planned_start_date',
      key: 'planned_start_date',
    },
    {
      title: '计划结束',
      dataIndex: 'planned_end_date',
      key: 'planned_end_date',
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: WorkOrder) => (
        <Space size="middle">
          <Button type="link" icon={<EditOutlined />}>编辑</Button>
          <Button type="link" danger icon={<DeleteOutlined />}>删除</Button>
        </Space>
      ),
    },
  ]

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      console.log('创建工单:', values)
      message.success('工单创建成功！')
      setIsModalOpen(false)
      form.resetFields()
    } catch (error) {
      console.error('验证失败:', error)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h1>工单管理</h1>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsModalOpen(true)}>
          新建工单
        </Button>
      </div>

      <Card>
        <Table
          columns={columns}
          dataSource={data}
          rowKey="id"
          pagination={{ pageSize: 10 }}
        />
      </Card>

      <Modal
        title="新建工单"
        open={isModalOpen}
        onOk={handleCreate}
        onCancel={() => setIsModalOpen(false)}
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="code" label="工单号" rules={[{ required: true }]}>
            <Input placeholder="请输入工单号" />
          </Form.Item>
          <Form.Item name="product_name" label="产品名称" rules={[{ required: true }]}>
            <Input placeholder="请输入产品名称" />
          </Form.Item>
          <Form.Item name="quantity" label="数量" rules={[{ required: true }]}>
            <Input type="number" placeholder="请输入数量" />
          </Form.Item>
          <Form.Item name="priority" label="优先级" rules={[{ required: true }]}>
            <Select>
              <Select.Option value="high">高</Select.Option>
              <Select.Option value="normal">中</Select.Option>
              <Select.Option value="low">低</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="remark" label="备注">
            <TextArea rows={4} placeholder="请输入备注" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
