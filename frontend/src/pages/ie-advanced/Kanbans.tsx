import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Space, message, Empty, Row, Col } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

interface Kanban {
  id: string
  factory_id: string
  kanban_id: string
  card_status: string
  current_card_count: number
}

const Kanbans: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<Kanban[]>([])
  const [loading, setLoading] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await fetch(`http://localhost:8000/api/v1/ie-advanced/kanbans?factory_id=${factory}&limit=50`)
      // Simplified - backend may return different structure
      const result = await res.json()
      setData(Array.isArray(result) ? result : [])
    } catch (e) {
      console.error('Error fetching kanbans', e)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [factory])

  const columns = [
    { title: '工厂ID', dataIndex: 'factory_id', key: 'factory_id', width: 100 },
    { title: '看板ID', dataIndex: 'kanban_id', key: 'kanban_id', width: 120 },
    { title: '卡片状态', dataIndex: 'card_status', key: 'card_status', width: 120, render: (val: string) => <Tag color="blue">{val}</Tag> },
    { title: '当前卡片数', dataIndex: 'current_card_count', key: 'current_card_count', width: 120 },
  ]

  return (
    <Card title="Kanban看板管理">
      <Row gutter={16} align="middle" style={{ marginBottom: 16 }}>
        <Col span={3}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => message.info('Create button not implemented yet')}>
            新增看板
          </Button>
        </Col>
        <Col span={4}>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }}>
            <Select.Option value="F001">F001 厂区</Select.Option>
          </Select>
        </Col>
      </Row>
      {data.length > 0 ? (
        <Table dataSource={data} columns={columns} loading={loading} pagination={{ pageSize: 10 }} rowKey="id" />
      ) : (
        <Empty description={loading ? '加载中...' : '暂无Kanban记录'} style={{ margin: '40px 0' }} />
      )}
    </Card>
  )
}

export default Kanbans