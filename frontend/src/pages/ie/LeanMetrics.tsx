import React, { useEffect, useState } from 'react'
import {
  Card, Table, Tag, Space, Select, Row, Col, Statistic, Progress, Empty,
} from 'antd'
import {
  DashboardOutlined, ClockCircleOutlined, ThunderboltOutlined, WarningOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'

interface LeanMetric {
  id: string
  factory_id: string
  metric_name: string
  metric_category: string
  value: number
  target_value: number
  unit: string
  period: string
  status: string
  recorded_at: string
}

const CATEGORY_MAP: Record<string, { color: string; text: string }> = {
  quality: { color: 'green', text: '质量' },
  cost: { color: 'blue', text: '成本' },
  delivery: { color: 'purple', text: '交期' },
  efficiency: { color: 'orange', text: '效率' },
  safety: { color: 'red', text: '安全' },
}

const LeanMetrics: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<LeanMetric[]>([])
  const [loading, setLoading] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.get(API_ENDPOINTS.IE_LEAN_METRICS, { params: { factory_id: factory, limit: 200 } })
      setData(res.items || res || [])
    } catch { setData([]) } finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [factory])

  const onTarget = data.filter(d => d.value >= d.target_value).length
  const avgAchieve = data.length > 0
    ? (data.reduce((s, d) => s + (d.target_value > 0 ? d.value / d.target_value : 0), 0) / data.length * 100).toFixed(0)
    : '0'

  const columns: ColumnsType<LeanMetric> = [
    { title: '指标名称', dataIndex: 'metric_name', key: 'metric_name', width: 160, ellipsis: true },
    {
      title: '类别', dataIndex: 'metric_category', key: 'metric_category', width: 80,
      filters: Object.entries(CATEGORY_MAP).map(([k, v]) => ({ text: v.text, value: k })),
      onFilter: (v, r) => r.metric_category === v,
      render: v => { const c = CATEGORY_MAP[v] || { color: 'default', text: v }; return <Tag color={c.color}>{c.text}</Tag> },
    },
    {
      title: '当前值', dataIndex: 'value', key: 'value', width: 100,
      render: (v, r) => <span style={{ fontWeight: 600, color: v >= r.target_value ? '#52c41a' : '#ff4d4f' }}>{v}{r.unit}</span>,
    },
    { title: '目标值', dataIndex: 'target_value', key: 'target_value', width: 100, render: (v, r) => `${v}${r.unit}` },
    {
      title: '达成率', key: 'achievement', width: 140,
      sorter: (a, b) => (a.value / a.target_value) - (b.value / b.target_value),
      render: (_, r) => {
        const pct = r.target_value > 0 ? Math.round(r.value / r.target_value * 100) : 0
        return <Progress percent={Math.min(pct, 100)} size="small" strokeColor={pct >= 100 ? '#52c41a' : pct >= 80 ? '#faad14' : '#ff4d4f'} format={() => `${pct}%`} />
      },
    },
    { title: '周期', dataIndex: 'period', key: 'period', width: 90 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: v => <Tag color={v === 'on_track' ? 'green' : v === 'at_risk' ? 'orange' : 'red'}>{v === 'on_track' ? '达标' : v === 'at_risk' ? '风险' : '落后'}</Tag>,
    },
    { title: '记录时间', dataIndex: 'recorded_at', key: 'recorded_at', width: 110, render: v => v ? dayjs(v).format('YYYY-MM-DD') : '-' },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="指标总数" value={data.length} prefix={<DashboardOutlined />} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="达标指标" value={onTarget} prefix={<ThunderboltOutlined />} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="平均达成率" value={avgAchieve} suffix="%" prefix={<ClockCircleOutlined />} valueStyle={{ color: '#1890ff' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="落后指标" value={data.filter(d => d.status === 'behind').length} prefix={<WarningOutlined />} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
      </Row>

      <Card title="精益指标看板" extra={
        <Select value={factory} onChange={setFactory} style={{ width: 120 }} size="small">
          <Select.Option value="F001">F001 厂区</Select.Option>
          <Select.Option value="F01">F01 厂区</Select.Option>
        </Select>
      }>
        {data.length > 0 ? (
          <Table dataSource={data} columns={columns} loading={loading} rowKey="id" scroll={{ x: 1000 }} size="middle"
            pagination={{ pageSize: 15, showTotal: t => `共 ${t} 条` }} />
        ) : (
          <Empty description={loading ? '加载中...' : '暂无精益指标数据'} style={{ margin: '40px 0' }} />
        )}
      </Card>
    </div>
  )
}

export default LeanMetrics
