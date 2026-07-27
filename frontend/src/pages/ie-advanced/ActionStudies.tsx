import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Space, message, Empty, Row, Col } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

interface ActionStudy {
  id: string
  factory_id: string
  product_id: string
  operation_name: string
  station_id?: string
  method_type: string
  study_date: string
  created_at: string
}

const ActionStudies: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<ActionStudy[]>([])
  const [loading, setLoading] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await fetch(`http://localhost:8000/api/v1/ie-advanced/action-studies?factory_id=${factory}&limit=50`)
      const result = await res.json()
      setData(result || [])
    } catch (e) {
      console.error('Error fetching action studies', e)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [factory])

  const columns = [
    { title: '工厂ID', dataIndex: 'factory_id', key: 'factory_id', width: 100 },
    { title: '产品ID', dataIndex: 'product_id', key: 'product_id', width: 120 },
    { title: '操作名称', dataIndex: 'operation_name', key: 'operation_name', width: 180 },
    { title: '工位', dataIndex: 'station_id', key: 'station_id', width: 100 },
    { title: '方法类型', dataIndex: 'method_type', key: 'method_type', width: 100 },
    { title: '研究日期', dataIndex: 'study_date', key: 'study_date', width: 120, render: (val: string) => dayjs(val).format('YYYY-MM-DD') },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 120, render: (val: string) => dayjs(val).format('YYYY-MM-DD HH:mm') },
  ]

  return (
    <Card title="动作研究管理">
      <Row gutter={16} align="middle" style={{ marginBottom: 16 }}>
        <Col span={3}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => message.info('Create button not implemented yet')}>
            新增研究
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
        <Empty description={loading ? '加载中...' : '暂无动作研究记录'} style={{ margin: '40px 0' }} />
      )}
    </Card>
  )
}

export default ActionStudies