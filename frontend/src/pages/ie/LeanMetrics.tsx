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

const MOCK_DATA: LeanMetric[] = [
  { id: 'lm-1', factory_id: 'factory-sh-01', metric_name: 'OEE综合设备效率', metric_category: 'efficiency', value: 82.5, target_value: 85, unit: '%', period: '月度', status: 'at_risk', recorded_at: '2026-07-01' },
  { id: 'lm-2', factory_id: 'factory-sh-01', metric_name: '一次通过率', metric_category: 'quality', value: 97.2, target_value: 98, unit: '%', period: '周', status: 'at_risk', recorded_at: '2026-07-15' },
  { id: 'lm-3', factory_id: 'factory-sh-01', metric_name: '准时交付率', metric_category: 'delivery', value: 94.8, target_value: 95, unit: '%', period: '月度', status: 'on_track', recorded_at: '2026-07-01' },
  { id: 'lm-4', factory_id: 'factory-sh-01', metric_name: '单位产品成本', metric_category: 'cost', value: 12.5, target_value: 12.0, unit: '元', period: '月度', status: 'behind', recorded_at: '2026-07-01' },
  { id: 'lm-5', factory_id: 'factory-sh-01', metric_name: '库存周转率', metric_category: 'efficiency', value: 8.2, target_value: 8.0, unit: '次', period: '季度', status: 'on_track', recorded_at: '2026-07-01' },
  { id: 'lm-6', factory_id: 'factory-sh-01', metric_name: '安全事故数', metric_category: 'safety', value: 0, target_value: 0, unit: '起', period: '月度', status: 'on_track', recorded_at: '2026-07-01' },
  { id: 'lm-7', factory_id: 'factory-sh-01', metric_name: '换线时间', metric_category: 'efficiency', value: 18.5, target_value: 15.0, unit: 'min', period: '周', status: 'behind', recorded_at: '2026-07-15' },
]

const LeanMetrics: React.FC = () => {
  const [factory, setFactory] = useState('factory-sh-01')
  const [data, setData] = useState<LeanMetric[]>([])
  const [loading, setLoading] = useState(false)

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.get(API_ENDPOINTS.IE_LEAN_METRICS, { params: { factory_id: factory, limit: 200 } })
      const items = res.items || res || []
      setData(items)
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
        <Select value={factory} onChange={setFactory} style={{ width: 140 }} size="small">
          <Select.Option value="factory-sh-01">上海工厂</Select.Option>
          <Select.Option value="FAC_ELEC_DEMO_2026">电子工厂</Select.Option>
          <Select.Option value="FAC_MECH_001">机械工厂</Select.Option>
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
