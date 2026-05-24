import { Card, Table, Tag, Button, Space, Modal, Form, Input, Select, message } from 'antd'
import { PlusOutlined, EyeOutlined } from '@ant-design/icons'
import { useState } from 'react'

interface Inspection {
  id: number
  code: string
  type: string
  work_order_code: string
  product_name: string
  quantity: number
  status: string
  inspector: string
  inspection_date: string
}

const mockData: Inspection[] = [
  { id: 1, code: 'IQC-2024-001', type: 'IQC', work_order_code: 'PO-2024-001', product_name: '原材料 A', quantity: 500, status: 'pending', inspector: '-', inspection_date: '2024-01-15' },
  { id: 2, code: 'IPQC-2024-005', type: 'IPQC', work_order_code: 'WO-2024-002', product_name: '产品 B', quantity: 200, status: 'completed', inspector: '张三', inspection_date: '2024-01-16' },
  { id: 3, code: 'FQC-2024-003', type: 'FQC', work_order_code: 'WO-2024-001', product_name: '产品 A', quantity: 1000, status: 'in_progress', inspector: '李四', inspection_date: '2024-01-16' },
  { id: 4, code: 'OQC-2024-002', type: 'OQC', work_order_code: 'SO-2024-001', product_name: '产品 C', quantity: 800, status: 'completed', inspector: '王五', inspection_date: '2024-01-15' },
]

const typeMap: Record<string, { color: string; text: string }> = {
  IQC: { color: 'blue', text: '来料检验' },
  IPQC: { color: 'green', text: '过程检验' },
  FQC: { color: 'purple', text: '最终检验' },
  OQC: { color: 'orange', text: '出货检验' },
}

const statusMap: Record<string, { color: string; text: string }> = {
  pending: { color: 'orange', text: '待检验' },
  in_progress: { color: 'blue', text: '检验中' },
  completed: { color: 'green', text: '已完成' },
  rejected: { color: 'red', text: '已拒收' },
}

export default function InspectionList() {
  const [data] = useState<Inspection[]>(mockData)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [currentInspection, setCurrentInspection] = useState<Inspection | null>(null)
  const [form] = Form.useForm()

  const columns = [
    { title: '检验单号', dataIndex: 'code', key: 'code' },
    { 
      title: '类型', 
      dataIndex: 'type', 
      key: 'type',
      render: (type: string) => {
        const config = typeMap[type] || { color: 'default', text: type }
        return <Tag color={config.color}>{config.text}</Tag>
      }
    },
    { title: '关联单号', dataIndex: 'work_order_code', key: 'work_order_code' },
    { title: '产品名称', dataIndex: 'product_name', key: 'product_name' },
    { title: '检验数量', dataIndex: 'quantity', key: 'quantity' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const config = statusMap[status] || { color: 'default', text: status }
        return <Tag color={config.color}>{config.text}</Tag>
      },
    },
    { title: '检验员', dataIndex: 'inspector', key: 'inspector' },
    { title: '检验日期', dataIndex: 'inspection_date', key: 'inspection_date' },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: Inspection) => (
        <Space size="middle">
          <Button 
            type="link" 
            icon={<EyeOutlined />}
            onClick={() => handleView(record)}
          >
            查看
          </Button>
          {record.status === 'pending' && (
            <Button type="link" onClick={() => handleExecute(record)}>
              执行
            </Button>
          )}
        </Space>
      ),
    },
  ]

  const handleView = (record: Inspection) => {
    setCurrentInspection(record)
    setIsModalOpen(true)
  }

  const handleExecute = (record: Inspection) => {
    message.info(`开始执行检验：${record.code}`)
    // 跳转到检验录入页面
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h1>质量检验</h1>
        <Button type="primary" icon={<PlusOutlined />}>
          新建检验单
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
        title="检验单详情"
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        footer={null}
        width={600}
      >
        {currentInspection && (
          <div>
            <p><strong>检验单号:</strong> {currentInspection.code}</p>
            <p><strong>类型:</strong> {typeMap[currentInspection.type]?.text}</p>
            <p><strong>关联单号:</strong> {currentInspection.work_order_code}</p>
            <p><strong>产品名称:</strong> {currentInspection.product_name}</p>
            <p><strong>检验数量:</strong> {currentInspection.quantity} PCS</p>
            <p><strong>状态:</strong> {statusMap[currentInspection.status]?.text}</p>
            <p><strong>检验员:</strong> {currentInspection.inspector}</p>
            <p><strong>检验日期:</strong> {currentInspection.inspection_date}</p>
          </div>
        )}
      </Modal>
    </div>
  )
}
