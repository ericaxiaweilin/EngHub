import React, { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Space, Typography, Row, Col, Statistic, Progress, Empty,
} from 'antd'
import { DashboardOutlined, RiseOutlined, FallOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'

const { Title, Text } = Typography
const FACTORY = 'F001'

const OeeDashboard: React.FC = () => {
  const [summary, setSummary] = useState<any>(null)
  const [trend, setTrend] = useState<any>(null)

  useEffect(() => {
    api.get('/api/v1/equip-maint/oee/summary', { params: { factory_id: FACTORY } })
      .then((res: any) => setSummary(res)).catch(() => {})
    api.get('/api/v1/equip-maint/oee/trend', { params: { factory_id: FACTORY, days: 7 } })
      .then((res: any) => setTrend(res)).catch(() => {})
  }, [])

  const avgOee = summary?.avg_oee || 0
  const oeeColor = avgOee >= 85 ? '#52c41a' : avgOee >= 60 ? '#faad14' : '#f5222d'

  const columns: ColumnsType<any> = [
    { title: '设备', dataIndex: 'equipment_id', key: 'equip', width: 120 },
    { title: 'OEE', dataIndex: 'oee', key: 'oee', width: 80,
      render: (v: number) => <Text strong style={{ color: v >= 85 ? '#52c41a' : v >= 60 ? '#faad14' : '#f5222d' }}>{v}%</Text> },
    { title: '稼动率', dataIndex: 'availability', key: 'avail', width: 80, render: (v) => `${v}%` },
    { title: '性能率', dataIndex: 'performance', key: 'perf', width: 80, render: (v) => `${v}%` },
    { title: '良品率', dataIndex: 'quality', key: 'qual', width: 80, render: (v) => `${v}%` },
    { title: '停机(min)', dataIndex: 'downtime_minutes', key: 'down', width: 90,
      render: (v) => <Text type={v > 60 ? 'danger' : undefined}>{Math.round(v)}</Text> },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }}>
        <DashboardOutlined style={{ fontSize: 22, color: '#722ed1' }} />
        <Title level={4} style={{ margin: 0 }}>OEE 设备效率</Title>
        <Tag color="purple">世界级标准 85%</Tag>
      </Space>

      {/* 概览 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <div style={{ textAlign: 'center' }}>
              <Progress type="dashboard" percent={avgOee} strokeColor={oeeColor} size={100}
                format={() => `${avgOee}%`} />
              <div><Text type="secondary">工厂平均 OEE</Text></div>
            </div>
          </Card>
        </Col>
        <Col span={6}><Card size="small"><Statistic title="设备数" value={summary?.equipment_count || 0} prefix={<DashboardOutlined />} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="7天平均" value={trend?.avg_oee || 0} suffix="%" prefix={trend?.avg_oee >= 85 ? <RiseOutlined /> : <FallOutlined />} valueStyle={{ color: trend?.avg_oee >= 85 ? '#52c41a' : '#faad14' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="最差设备" value={summary?.worst_equipment?.oee || '—'} suffix={summary?.worst_equipment ? '%' : ''} valueStyle={{ color: '#f5222d' }} /></Card></Col>
      </Row>

      {/* 设备 OEE 表 */}
      <Card title="今日设备 OEE">
        {summary?.items?.length ? (
          <Table columns={columns} dataSource={summary.items} rowKey="equipment_id" size="small" pagination={false} />
        ) : (
          <Empty description="暂无 OEE 数据（需先计算日 OEE）" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Card>
    </div>
  )
}

export default OeeDashboard
