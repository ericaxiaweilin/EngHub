import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Space, message, Empty, Row, Col } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'

interface MethodStudy {
  id: string
  factory_id: string
  product_id: string
  original_operation: string
  version: string
  is_basement_method: boolean
  is_optimal_method: boolean
  created_at: string
}

const MethodStudies: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<MethodStudy[]>([])
  const [loading, setLoading] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await fetch(`http://localhost:8000/api/v1/ie-advanced/method-studies?factory_id=${factory}&limit=50`)
      // Simplified - backend may return different structure
      const result = await res.json()
      setData(Array.isArray(result) ? result : [])
    } catch (e) {
      console.error('Error fetching method studies', e)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [factory])

  const columns = [
    { title: '工厂ID', dataIndex: 'factory_id', key: 'factory_id', width: 100 },
    { title: '产品ID', dataIndex: 'product_id', key: 'product_id', width: 120 },
    { title: '原始操作', dataIndex: 'original_operation', key: 'original_operation', width: 200 },
    { title: '版本', dataIndex: 'version', key: 'version', width: 80 },
    { title: '基础方法', dataIndex: 'is_basement_method', key: 'is_basement_method', width: 100, render: (val: boolean) => <Tag color={val ? 'green' : 'gray'}>{val ? '是' : '否'}</Tag> },
    { title: '最优方法', dataIndex: 'is_optimal_method', key: 'is_optimal_method', width: 100, render: (val: boolean) => <Tag color={val ? 'gold' : 'gray'}>{val ? '是' : '否'}</Tag> },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 120, render: (val: string) => dayjs(val).format('YYYY-MM-DD HH:mm') },
  ]

  return (
    <Card title="方法研究管理">
      <Row gutter={16} align="middle" style={{ marginBottom: 16 }}>
        <Col span={3}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => message.info('Create button not implemented yet')}>
            新增方案
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
        <Empty description={loading ? '加载中...' : '暂无方法研究方案'} style={{ margin: '40px 0' }} />
      )}
    </Card>
  )
}

export default MethodStudies