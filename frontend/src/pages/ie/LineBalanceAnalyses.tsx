import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, message, DatePicker, Empty, Row, Col,
  InputNumber,
} from 'antd'
import { PlusOutlined, SyncOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'

interface LineBalanceAnalysis {
  id: string
  factory_id: string
  line_id: string
  product_id: string
  balance_rate: number
  takt_time_min: number
  bottleneck_station?: string
  created_at: string
}

const LineBalanceAnalyses: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [product, setProduct] = useState('')
  const [data, setData] = useState<LineBalanceAnalysis[]>([])
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [showForm, setShowForm] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({ factory_id: factory })
      if (product) params.set('product_id', product)
      const res = await fetch(`http://localhost:8000/api/v1/ie/line-balance-analyses?${params.toString()}&limit=500`)
      const data = await res.json()
      setData(Array.isArray(data) ? data : [])
    } catch (e) {
      console.error('Error fetching line balance analyses', e)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  const analyzeBalance = async () => {
    setAnalyzing(true)
    try {
      const res = await fetch('http://localhost:8000/api/v1/ie/line-balance-analyses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ factory_id: factory, product_id: product, line_id: 'LINE-001' }),
      })
      const result = await res.json()
      message.success('分析完成！')
      fetchData()
    } catch (e) {
      console.error('Line balance analysis failed', e)
      message.error('分析失败')
    } finally {
      setAnalyzing(false)
      setShowForm(false)
    }
  }

  useEffect(() => { fetchData() }, [factory, product])

  const columns: ColumnsType<LineBalanceAnalysis> = [
    {
      title: '工厂ID',
      dataIndex: 'factory_id',
      key: 'factory_id',
      width: 100,
    },
    {
      title: '产线ID',
      dataIndex: 'line_id',
      key: 'line_id',
      width: 120,
    },
    {
      title: '产品ID',
      dataIndex: 'product_id',
      key: 'product_id',
      width: 120,
    },
    {
      title: '平衡率(%)',
      dataIndex: 'balance_rate',
      key: 'balance_rate',
      width: 100,
      render: (val) => <Tag color={val > 80 ? 'green' : val > 60 ? 'blue' : 'orange'}>{(val * 100).toFixed(1)}%</Tag>,
    },
    {
      title: '节拍时间(min)',
      dataIndex: 'takt_time_min',
      key: 'takt_time_min',
      width: 120,
      render: (val) => val.toFixed(2),
    },
    {
      title: '瓶颈工位',
      dataIndex: 'bottleneck_station',
      key: 'bottleneck_station',
      width: 140,
    },
    {
      title: '创建日期',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (val) => dayjs(val).format('YYYY-MM-DD HH:mm'),
    },
  ]

  return (
    <Card title="产线平衡分析">
      <Row gutter={16} align="middle" style={{ marginBottom: 16 }}>
        <Col span={3}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowForm(true)}>
            执行分析
          </Button>
        </Col>
        <Col span={3}>
          <Button type="link" icon={<SyncOutlined />} onClick={fetchData}>
            刷新列表
          </Button>
        </Col>
        <Col span={4}>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }}>
            <Select.Option value="F001">F001 厂区</Select.Option>
          </Select>
        </Col>
        <Col span={4}>
          <Select value={product} onChange={setProduct} placeholder="选择产品" style={{ width: 150 }}>
            <Select.Option value="P001">P001 产品A</Select.Option>
            <Select.Option value="P002">P002 产品B</Select.Option>
          </Select>
        </Col>
      </Row>

      {showForm && (
        <Modal
          title="执行产线平衡分析"
          open={true}
          okText="分析"
          onCancel={() => setShowForm(false)}
          onOk={analyzeBalance}
          footer={(_, { OkBtn }) => (
            <Space>
              <OkBtn loading={analyzing} />
            </Space>
          )}
        >
          <p>请输入产线和分析参数</p>
          <InputNumber
            label="产线ID"
            value={undefined}
            placeholder="输入产线ID"
            style={{ width: 200 }}
          />
        </Modal>
      )}

      {data.length > 0 ? (
        <Table
          dataSource={data}
          columns={columns}
          loading={loading || analyzing}
          pagination={{ pageSize: 10 }}
          rowKey="id"
        />
      ) : (
        <Empty description={loading ? '加载中...' : '暂无分析记录'} style={{ margin: '40px 0' }} />
      )}
    </Card>
  )
}

export default LineBalanceAnalyses