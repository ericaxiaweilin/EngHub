import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Table, Tag, Space, Row, Col, Statistic, Progress, Empty, Spin, Select, Tooltip,
} from 'antd'
import {
  BarChartOutlined, WarningOutlined, DashboardOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { apsApi, CapacityLoadData, CapacityResource } from '../../services/aps'

const FACTORY = 'F001'

const CapacityLoad: React.FC = () => {
  const [data, setData] = useState<CapacityLoadData | null>(null)
  const [loading, setLoading] = useState(false)
  const [days, setDays] = useState(7)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await apsApi.getCapacityLoad({ factory_id: FACTORY, days })
      setData(res)
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { loadData() }, [loadData])

  // 表格列定义
  const columns: ColumnsType<CapacityResource> = [
    {
      title: '工位/设备',
      dataIndex: 'station_id',
      key: 'station_id',
      width: 140,
      render: (v: string, r) => (
        <Space>
          <span style={{ fontWeight: 500 }}>{v}</span>
          {r.is_bottleneck && <Tag icon={<WarningOutlined />} color="error">瓶颈</Tag>}
        </Space>
      ),
    },
    {
      title: '平均利用率',
      dataIndex: 'avg_utilization',
      key: 'avg_utilization',
      width: 180,
      sorter: (a, b) => a.avg_utilization - b.avg_utilization,
      render: (v: number) => (
        <Progress
          percent={Math.min(v, 100)}
          size="small"
          status={v > 100 ? 'exception' : v > 85 ? 'active' : 'normal'}
          format={() => `${v.toFixed(1)}%`}
          strokeColor={v > 100 ? '#f5222d' : v > 85 ? '#faad14' : '#52c41a'}
        />
      ),
    },
    {
      title: '日负荷明细',
      key: 'daily_load',
      render: (_: any, r: CapacityResource) => (
        <Space wrap size={[4, 4]}>
          {r.daily_load.map(d => (
            <Tooltip key={d.date} title={`${d.date}: ${d.load_hours}h / ${d.capacity_hours}h (${d.utilization}%)`}>
              <Tag
                color={d.overloaded ? 'error' : d.utilization > 85 ? 'warning' : 'success'}
                style={{ fontSize: 10, margin: 0 }}
              >
                {d.date.slice(5)} {d.utilization.toFixed(0)}%
              </Tag>
            </Tooltip>
          ))}
        </Space>
      ),
    },
  ]

  return (
    <div>
      {/* 概览统计 */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="分析工位" value={data?.resources.length ?? 0} prefix={<DashboardOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="瓶颈工位"
              value={data?.bottleneck_count ?? 0}
              prefix={<WarningOutlined />}
              valueStyle={{ color: (data?.bottleneck_count ?? 0) > 0 ? '#f5222d' : '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="日标准产能" value={data?.daily_capacity_hours ?? 12} suffix="小时/天" />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Space>
              <span style={{ fontSize: 12, color: '#666' }}>分析窗口</span>
              <Select value={days} onChange={setDays} size="small" style={{ width: 80 }} options={[
                { value: 3, label: '3天' },
                { value: 7, label: '7天' },
                { value: 14, label: '14天' },
                { value: 30, label: '30天' },
              ]} />
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 负荷表格 */}
      <Card
        size="small"
        title={<Space><BarChartOutlined />产能负荷分析</Space>}
        extra={<Tag color="blue">标准 {data?.daily_capacity_hours ?? 12}h/天 (08:00-20:00)</Tag>}
      >
        <Spin spinning={loading}>
          {!data || data.resources.length === 0 ? (
            <Empty description="暂无排程负荷数据，请先生成排程方案" />
          ) : (
            <Table
              dataSource={data.resources}
              columns={columns}
              rowKey="station_id"
              size="small"
              pagination={false}
              scroll={{ y: 400 }}
            />
          )}
        </Spin>
      </Card>
    </div>
  )
}

export default CapacityLoad
