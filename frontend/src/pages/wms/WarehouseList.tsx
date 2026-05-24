import { Card, Table, Tag, Space, Statistic, Row, Col } from 'antd'
import { WarehouseOutlined, InboxOutlined, OutboxOutlined } from '@ant-design/icons'

interface Warehouse {
  id: number
  code: string
  name: string
  type: string
  location: string
  capacity: number
  current_stock: number
}

const mockData: Warehouse[] = [
  { id: 1, code: 'WH-RAW', name: '原材料仓', type: 'raw_material', location: 'A 区', capacity: 10000, current_stock: 6500 },
  { id: 2, code: 'WH-FG', name: '成品仓', type: 'finished_goods', location: 'B 区', capacity: 5000, current_stock: 3200 },
  { id: 3, code: 'WH-WIP', name: '在制品仓', type: 'wip', location: '车间', capacity: 2000, current_stock: 850 },
]

export default function WarehouseList() {
  const columns = [
    { title: '仓库编码', dataIndex: 'code', key: 'code' },
    { title: '仓库名称', dataIndex: 'name', key: 'name' },
    { 
      title: '类型', 
      dataIndex: 'type', 
      key: 'type',
      render: (type: string) => {
        const config: Record<string, { color: string; text: string }> = {
          raw_material: { color: 'blue', text: '原材料' },
          finished_goods: { color: 'green', text: '成品' },
          wip: { color: 'orange', text: '在制品' },
          spare_parts: { color: 'purple', text: '备品备件' },
        }
        const cfg = config[type] || { color: 'default', text: type }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      }
    },
    { title: '位置', dataIndex: 'location', key: 'location' },
    { 
      title: '容量', 
      dataIndex: 'capacity', 
      key: 'capacity',
      render: (val: number) => `${val.toLocaleString()} PCS`
    },
    { 
      title: '当前库存', 
      dataIndex: 'current_stock', 
      key: 'current_stock',
      render: (val: number, record: Warehouse) => {
        const usage = (val / record.capacity * 100).toFixed(1)
        return (
          <div>
            <span>{val.toLocaleString()} PCS</span>
            <div style={{ fontSize: 12, color: '#999' }}>使用率：{usage}%</div>
          </div>
        )
      }
    },
    {
      title: '操作',
      key: 'action',
      render: () => (
        <Space size="middle">
          <a>查看详情</a>
          <a>库存查询</a>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>仓库管理</h1>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="总仓库数"
              value={mockData.length}
              prefix={<WarehouseOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="总库容量"
              value={mockData.reduce((sum, w) => sum + w.capacity, 0)}
              prefix={<InboxOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="当前总库存"
              value={mockData.reduce((sum, w) => sum + w.current_stock, 0)}
              prefix={<OutboxOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
      </Row>

      <Card title="仓库列表">
        <Table
          columns={columns}
          dataSource={mockData}
          rowKey="id"
          pagination={false}
        />
      </Card>
    </div>
  )
}
