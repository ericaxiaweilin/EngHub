import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Space, message, Empty, Row, Col } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

interface WorkCell {
  id: string
  factory_id: string
  work_cell_id: string
  product_family_id: string
  last_updated: string
}

const WorkCells: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<WorkCell[]>([])
  const [loading, setLoading] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await fetch(`http://localhost:8000/api/v1/ie-advanced/work-cells?factory_id=${factory}&limit=50`)
      // Simplified - backend may return different structure
      const result = await res.json()
      setData(Array.isArray(result) ? result : [])
    } catch (e) {
      console.error('Error fetching work cells', e)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [factory])

  const columns = [
    { title: '工厂ID', dataIndex: 'factory_id', key: 'factory_id', width: 100 },
    { title: '工站ID', dataIndex: 'work_cell_id', key: 'work_cell_id', width: 140 },
    { title: '产品族ID', dataIndex: 'product_family_id', key: 'product_family_id', width: 140 },
    { title: '最后更新', dataIndex: 'last_updated', key: 'last_updated', width: 140, render: (val: string) => dayjs(val).format('YYYY-MM-DD HH:mm') },
  ]

  return (
    <Card title="工站布局管理">
      <Row gutter={16} align="middle" style={{ marginBottom: 16 }}>
        <Col span={3}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => message.info('Create button not implemented yet')}>
            新增布局
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
        <Empty description={loading ? '加载中...' : '暂无工站布局记录'} style={{ margin: '40px 0' }} />
      )}
    </Card>
  )
}

export default WorkCells