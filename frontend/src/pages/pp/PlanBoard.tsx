import { Card, Table, Tag, Button, Space, Statistic, Row, Col } from 'antd'
import { ScheduleOutlined, CheckCircleOutlined, WarningOutlined } from '@ant-design/icons'

interface PlanItem {
  id: number
  code: string
  product_name: string
  planned_quantity: number
  completed_quantity: number
  status: string
  priority: string
  start_date: string
  end_date: string
}

const mockPlans: PlanItem[] = [
  { id: 1, code: 'PP-2024-001', product_name: '产品 A', planned_quantity: 5000, completed_quantity: 3200, status: 'in_progress', priority: 'high', start_date: '2024-01-15', end_date: '2024-01-25' },
  { id: 2, code: 'PP-2024-002', product_name: '产品 B', planned_quantity: 3000, completed_quantity: 3000, status: 'completed', priority: 'normal', start_date: '2024-01-10', end_date: '2024-01-20' },
  { id: 3, code: 'PP-2024-003', product_name: '产品 C', planned_quantity: 2000, completed_quantity: 0, status: 'pending', priority: 'low', start_date: '2024-01-20', end_date: '2024-01-30' },
]

export default function PlanBoard() {
  const columns = [
    { title: '计划号', dataIndex: 'code', key: 'code' },
    { title: '产品名称', dataIndex: 'product_name', key: 'product_name' },
    { 
      title: '计划数量', 
      dataIndex: 'planned_quantity', 
      key: 'planned_quantity',
      render: (val: number) => `${val.toLocaleString()} PCS`
    },
    { 
      title: '完成数量', 
      dataIndex: 'completed_quantity', 
      key: 'completed_quantity',
      render: (val: number, record: PlanItem) => (
        <span style={{ color: val >= record.planned_quantity ? '#52c41a' : '#1890ff' }}>
          {val.toLocaleString()} PCS
        </span>
      )
    },
    { 
      title: '完成率', 
      key: 'completion_rate',
      render: (_: any, record: PlanItem) => {
        const rate = record.planned_quantity > 0 
          ? ((record.completed_quantity / record.planned_quantity) * 100).toFixed(1)
          : 0
        return `${rate}%`
      }
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        const config: Record<string, { color: string; text: string }> = {
          pending: { color: 'orange', text: '待开始' },
          in_progress: { color: 'blue', text: '进行中' },
          completed: { color: 'green', text: '已完成' },
          delayed: { color: 'red', text: '已延期' },
        }
        const cfg = config[status] || { color: 'default', text: status }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    { title: '开始日期', dataIndex: 'start_date', key: 'start_date' },
    { title: '结束日期', dataIndex: 'end_date', key: 'end_date' },
    {
      title: '操作',
      key: 'action',
      render: () => (
        <Space size="middle">
          <Button type="link">查看</Button>
          <Button type="link">调整</Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>生产计划看板</h1>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="本月计划总数"
              value={156}
              prefix={<ScheduleOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="已完成计划"
              value={128}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="延期计划"
              value={3}
              prefix={<WarningOutlined />}
              valueStyle={{ color: '#ff4d4f' }}
            />
          </Card>
        </Col>
      </Row>

      <Card title="计划列表">
        <Table
          columns={columns}
          dataSource={mockPlans}
          rowKey="id"
          pagination={{ pageSize: 10 }}
          scroll={{ x: 1000 }}
        />
      </Card>
    </div>
  )
}
