import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, message, Empty, Row, Col,
  Progress,
} from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'

interface ProcessAnalysis {
  id: string
  factory_id: string
  product_id: string
  operation_code: string
  va_ratio: number
  efficiency_score: number
  created_at: string
}

const ProcessAnalyses: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<ProcessAnalysis[]>([])
  const [loading, setLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await fetch(`http://localhost:8000/api/v1/ie/process-analyses?factory_id=${factory}&limit=500`)
      const data = await res.json()
      setData(Array.isArray(data) ? data : [])
    } catch (e) {
      console.error('Error fetching process analyses', e)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [factory, searchTerm])

  const filteredData = data.filter(item =>
    item.operation_code.toLowerCase().includes(searchTerm.toLowerCase()) ||
    item.product_id.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const columns: ColumnsType<ProcessAnalysis> = [
    {
      title: '工厂ID',
      dataIndex: 'factory_id',
      key: 'factory_id',
      width: 100,
    },
    {
      title: '产品ID',
      dataIndex: 'product_id',
      key: 'product_id',
      width: 120,
    },
    {
      title: '工序代码',
      dataIndex: 'operation_code',
      key: 'operation_code',
      width: 140,
    },
    {
      title: '增值比率(%)',
      dataIndex: 'va_ratio',
      key: 'va_ratio',
      width: 120,
      render: (val) => (
        <Space direction="vertical" align="center">
          <Progress type="circle" percent={val * 100} status={val > 0.7 ? 'success' : val > 0.4 ? 'warning' : 'danger'} />
          <Tag>{(val * 100).toFixed(1)}%</Tag>
        </Space>
      ),
    },
    {
      title: '效率评分',
      dataIndex: 'efficiency_score',
      key: 'efficiency_score',
      width: 100,
      render: (val) => <Tag color={val > 80 ? 'green' : val > 60 ? 'blue' : 'red'}>{val.toFixed(1)}</Tag>,
    },
    {
      title: '创建日期',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (val) => dayjs(val).format('YYYY-MM-DD'),
    },
  ]

  return (
    <Card title="工序价值分析">
      <Row gutter={16} align="middle" style={{ marginBottom: 16 }}>
        <Col span={3}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => message.info('Create button not implemented yet')}>
            新增分析
          </Button>
        </Col>
        <Col span={4}>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }}>
            <Select.Option value="F001">F001 厂区</Select.Option>
          </Select>
        </Col>
        <Col span={8}>
          <Input
            placeholder="搜索工序代码或产品..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            prefix={<SearchOutlined />}
          />
        </Col>
      </Row>

      {filteredData.length > 0 ? (
        <Table
          dataSource={filteredData}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 10 }}
          rowKey="id"
        />
      ) : (
        <Empty description={loading ? '加载中...' : '暂无分析数据'} style={{ margin: '40px 0' }} />
      )}
    </Card>
  )
}

export default ProcessAnalyses