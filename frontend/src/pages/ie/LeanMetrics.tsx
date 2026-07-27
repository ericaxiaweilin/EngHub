import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Empty, Row, Col, Statistic,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'

interface LeanProcess {
  operation: string
  va: number
  nva: number
  ratio: number
  efficiency: number
}

interface LeanMetricsData {
  factory_id: string
  product_id?: string
  total_value_added_time: number
  total_non_value_added_time: number
  overall_va_ratio: number
  analysis_count: number
  processes: LeanProcess[]
}

const LeanMetrics: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [metrics, setMetrics] = useState<LeanMetricsData | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchMetrics = async () => {
    setLoading(true)
    try {
      const res = await fetch(`http://localhost:8000/api/v1/ie/lean-metrics?factory_id=${factory}&limit=500`)
      const data = await res.json()
      setMetrics(data as LeanMetricsData | null)
    } catch (e) {
      console.error('Error fetching lean metrics', e)
      setMetrics(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchMetrics() }, [factory])

  const columns: ColumnsType<LeanProcess> = [
    {
      title: '工序',
      dataIndex: 'operation',
      key: 'operation',
      width: 200,
    },
    {
      title: '增值时间(min)',
      dataIndex: 'va',
      key: 'va',
      width: 140,
      render: (val) => val.toFixed(2),
    },
    {
      title: '非增值时间(min)',
      dataIndex: 'nva',
      key: 'nva',
      width: 140,
      render: (val) => val.toFixed(2),
    },
    {
      title: '增值比率(%)',
      dataIndex: 'ratio',
      key: 'ratio',
      width: 120,
      render: (val) => <Tag color={val > 0.7 ? 'green' : val > 0.4 ? 'blue' : 'red'}>{(val * 100).toFixed(1)}%</Tag>,
    },
    {
      title: '效率评分',
      dataIndex: 'efficiency',
      key: 'efficiency',
      width: 100,
      render: (val) => val.toFixed(1),
    },
  ]

  return (
    <Card title="精益指标看板">
      <Row gutter={16} align="middle" style={{ marginBottom: 24 }}>
        <Col span={3}>
          <Button type="primary" icon={<ReloadOutlined />} onClick={fetchMetrics} loading={loading}>
            刷新数据
          </Button>
        </Col>
        <Col span={4}>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }}>
            <Select.Option value="F001">F001 厂区</Select.Option>
          </Select>
        </Col>
      </Row>

      {!metrics || loading ? (
        <Empty description={loading ? '加载中...' : '暂无数据'} style={{ margin: '40px 0' }} />
      ) : (
        <>
          <Row gutter={24} style={{ marginBottom: 24 }}>
            <Col span={6}>
              <Statistic
                title="总增值时间"
                unit="min"
                value={metrics.total_value_added_time}
                precision={2}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="总非增值时间"
                unit="min"
                value={metrics.total_non_value_added_time}
                precision={2}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="增值比率"
                unit="%"
                value={metrics.overall_va_ratio * 100}
                precision={1}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="分析工序数"
                value={metrics.analysis_count}
              />
            </Col>
          </Row>

          {metrics.processes.length > 0 ? (
            <Table
              dataSource={metrics.processes}
              columns={columns}
              pagination={{ pageSize: 10 }}
              rowKey="operation"
            />
          ) : (
            <Empty description={metrics.analysis_count === 0 ? '暂无工序分析数据' : '无详细过程数据'} style={{ margin: '40px 0' }} />
          )}
        </>
      )}
    </Card>
  )
}

export default LeanMetrics