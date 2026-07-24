import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Row, Col, Tabs, Table, Tag, Space, Statistic, DatePicker,
  Button, Empty, Spin, Typography, Progress,
} from 'antd'
import {
  FileTextOutlined, BarChartOutlined, DownloadOutlined,
  CalendarOutlined, RiseOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import api from '../../services/api'

const { Title, Text } = Typography
const FACTORY = 'F001'

const ReportCenter: React.FC = () => {
  const [activeTab, setActiveTab] = useState('daily')
  const [dailyData, setDailyData] = useState<any>(null)
  const [weeklyData, setWeeklyData] = useState<any>(null)
  const [monthlyData, setMonthlyData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [selectedDate, setSelectedDate] = useState(dayjs())

  const loadDaily = useCallback(async (dateStr?: string) => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/reports-center/daily', {
        params: { factory_id: FACTORY, date: dateStr || dayjs().format('YYYY-MM-DD') }
      })
      setDailyData(res)
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  const loadWeekly = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/reports-center/weekly', {
        params: { factory_id: FACTORY }
      })
      setWeeklyData(res)
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  const loadMonthly = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/reports-center/monthly', {
        params: { factory_id: FACTORY }
      })
      setMonthlyData(res)
    } catch { /* ignore */ } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (activeTab === 'daily') loadDaily()
    else if (activeTab === 'weekly') loadWeekly()
    else if (activeTab === 'monthly') loadMonthly()
  }, [activeTab])

  // 工单完成表
  const woColumns: ColumnsType<any> = [
    { title: '工单号', dataIndex: 'work_order_code', key: 'code', width: 140 },
    { title: '产品', dataIndex: 'product_id', key: 'product', width: 100 },
    { title: '计划数', dataIndex: 'planned_qty', key: 'planned', width: 80, align: 'right' },
    { title: '今日产出', dataIndex: 'today_output', key: 'output', width: 90, align: 'right',
      render: (v: number) => <Text strong>{v}</Text> },
    { title: '良品', dataIndex: 'today_good', key: 'good', width: 70, align: 'right',
      render: (v: number) => <Text style={{ color: '#52c41a' }}>{v}</Text> },
    { title: '不良', dataIndex: 'today_defect', key: 'defect', width: 70, align: 'right',
      render: (v: number) => v > 0 ? <Text style={{ color: '#f5222d' }}>{v}</Text> : <Text type="secondary">0</Text> },
    { title: '累计完成', dataIndex: 'completed_qty', key: 'completed', width: 90, align: 'right' },
    { title: '达成率', dataIndex: 'achievement', key: 'rate', width: 100,
      render: (v: number) => (
        <Space>
          <Progress percent={Math.min(v, 100)} size="small" style={{ width: 60 }} showInfo={false}
            strokeColor={v >= 100 ? '#52c41a' : v >= 80 ? '#faad14' : '#f5222d'} />
          <Text style={{ color: v >= 100 ? '#52c41a' : v >= 80 ? '#faad14' : '#f5222d' }}>{v}%</Text>
        </Space>
      ) },
  ]

  // 工位排名表
  const stationColumns: ColumnsType<any> = [
    { title: '排名', key: 'rank', width: 60, render: (_, __, i) => (
      <Tag color={i === 0 ? 'gold' : i === 1 ? 'blue' : i === 2 ? 'green' : 'default'}>{i + 1}</Tag>
    )},
    { title: '工位', dataIndex: 'station_id', key: 'station' },
    { title: '产出', dataIndex: 'output', key: 'output', align: 'right',
      sorter: (a, b) => a.output - b.output },
    { title: '良品', dataIndex: 'good', key: 'good', align: 'right' },
    { title: '良品率', dataIndex: 'yield_rate', key: 'yield', align: 'right',
      render: (v: number) => <Text style={{ color: v >= 95 ? '#52c41a' : '#faad14' }}>{v}%</Text> },
    { title: '报工次数', dataIndex: 'reports', key: 'reports', align: 'right' },
  ]

  const renderDaily = () => {
    if (!dailyData) return <Empty />
    const s = dailyData.summary || {}
    return (
      <div>
        {/* 汇总指标 */}
        <Row gutter={16} style={{ marginBottom: 20 }}>
          <Col span={4}><Card size="small"><Statistic title="总产出" value={s.total_output} suffix="件" valueStyle={{ color: '#1890ff' }} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="良品" value={s.good_qty} suffix="件" valueStyle={{ color: '#52c41a' }} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="不良" value={s.defect_qty} suffix="件" valueStyle={{ color: '#f5222d' }} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="良品率" value={s.yield_rate} suffix="%" precision={2} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="停机" value={s.downtime_minutes} suffix="min" valueStyle={{ color: s.downtime_minutes > 60 ? '#f5222d' : '#333' }} /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="预警" value={s.alert_count} valueStyle={{ color: s.alert_count > 0 ? '#faad14' : '#52c41a' }} /></Card></Col>
        </Row>

        {/* 工单完成情况 */}
        <Card title="工单完成情况" size="small" style={{ marginBottom: 16 }}>
          <Table
            columns={woColumns}
            dataSource={dailyData.work_orders || []}
            rowKey="work_order_id"
            size="small"
            pagination={false}
            scroll={{ y: 240 }}
          />
        </Card>

        <Row gutter={16}>
          {/* 工位排名 */}
          <Col span={12}>
            <Card title="工位产出排名" size="small">
              <Table
                columns={stationColumns}
                dataSource={dailyData.station_ranking || []}
                rowKey="station_id"
                size="small"
                pagination={false}
              />
            </Card>
          </Col>
          {/* 异常事件 */}
          <Col span={12}>
            <Card title="异常事件" size="small">
              {(dailyData.alerts || []).length > 0 ? (
                (dailyData.alerts || []).map((a: any, i: number) => (
                  <div key={i} style={{ padding: '6px 0', borderBottom: '1px solid #f5f5f5' }}>
                    <Space>
                      <Tag color={a.severity === 'critical' ? 'red' : 'orange'}>
                        {a.severity === 'critical' ? '严重' : '警告'}
                      </Tag>
                      <Text>{a.title}</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {a.triggered_at ? dayjs(a.triggered_at).format('HH:mm') : ''}
                      </Text>
                    </Space>
                  </div>
                ))
              ) : (
                <Empty description="无异常" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </Card>
          </Col>
        </Row>
      </div>
    )
  }

  const renderWeekly = () => {
    if (!weeklyData) return <Empty />
    const s = weeklyData.summary || {}
    return (
      <div>
        <Row gutter={16} style={{ marginBottom: 20 }}>
          <Col span={5}><Card size="small"><Statistic title="周产出" value={s.total_output} suffix="件" /></Card></Col>
          <Col span={5}><Card size="small"><Statistic title="平均良品率" value={s.avg_yield_rate} suffix="%" precision={2} /></Card></Col>
          <Col span={5}><Card size="small"><Statistic title="日均产出" value={s.avg_daily_output} suffix="件" /></Card></Col>
          <Col span={5}><Card size="small"><Statistic title="工作天数" value={s.working_days} suffix="天" /></Card></Col>
          <Col span={4}><Card size="small"><Statistic title="周期" value={weeklyData.week || ''} valueStyle={{ fontSize: 16 }} /></Card></Col>
        </Row>
        <Card title="每日产出趋势" size="small">
          <div style={{ display: 'flex', alignItems: 'flex-end', height: 180, gap: 8, padding: '0 16px' }}>
            {(weeklyData.daily_trend || []).map((d: any) => {
              const maxVal = Math.max(...(weeklyData.daily_trend || []).map((x: any) => x.output), 1)
              const h = Math.max((d.output / maxVal) * 150, 4)
              return (
                <div key={d.date} style={{ flex: 1, textAlign: 'center' }}>
                  <Text style={{ fontSize: 11 }}>{d.output}</Text>
                  <div style={{ height: h, background: '#1890ff', borderRadius: 4, margin: '4px auto', width: '70%' }} />
                  <Text style={{ fontSize: 10, color: '#999' }}>{dayjs(d.date).format('MM/DD')}</Text>
                  <br />
                  <Text style={{ fontSize: 10, color: d.yield_rate >= 95 ? '#52c41a' : '#faad14' }}>{d.yield_rate}%</Text>
                </div>
              )
            })}
          </div>
        </Card>
      </div>
    )
  }

  const renderMonthly = () => {
    if (!monthlyData) return <Empty />
    const s = monthlyData.summary || {}
    return (
      <div>
        <Row gutter={16} style={{ marginBottom: 20 }}>
          <Col span={6}><Card size="small"><Statistic title="月产出" value={s.total_output} suffix="件" /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="平均良品率" value={s.avg_yield_rate} suffix="%" precision={2} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="良品总数" value={s.good_qty} suffix="件" valueStyle={{ color: '#52c41a' }} /></Card></Col>
          <Col span={6}><Card size="small"><Statistic title="不良总数" value={s.defect_qty} suffix="件" valueStyle={{ color: '#f5222d' }} /></Card></Col>
        </Row>
        <Card title="周产出趋势" size="small">
          <div style={{ display: 'flex', alignItems: 'flex-end', height: 160, gap: 12, padding: '0 16px' }}>
            {(monthlyData.weekly_trend || []).map((w: any) => {
              const maxVal = Math.max(...(monthlyData.weekly_trend || []).map((x: any) => x.output), 1)
              const h = Math.max((w.output / maxVal) * 130, 4)
              return (
                <div key={w.week} style={{ flex: 1, textAlign: 'center' }}>
                  <Text style={{ fontSize: 11 }}>{w.output}</Text>
                  <div style={{ height: h, background: '#722ed1', borderRadius: 4, margin: '4px auto', width: '60%' }} />
                  <Text style={{ fontSize: 10, color: '#999' }}>W{w.week}</Text>
                </div>
              )
            })}
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <FileTextOutlined style={{ fontSize: 22, color: '#1890ff' }} />
            <Title level={4} style={{ margin: 0 }}>生产报表中心</Title>
          </Space>
        </Col>
        <Col>
          <Space>
            {activeTab === 'daily' && (
              <DatePicker
                value={selectedDate}
                onChange={(d) => {
                  if (d) { setSelectedDate(d); loadDaily(d.format('YYYY-MM-DD')) }
                }}
                allowClear={false}
              />
            )}
            <Button icon={<DownloadOutlined />}>导出 Excel</Button>
          </Space>
        </Col>
      </Row>

      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            { key: 'daily', label: <Space><CalendarOutlined />日报</Space>, children: <Spin spinning={loading}>{renderDaily()}</Spin> },
            { key: 'weekly', label: <Space><BarChartOutlined />周报</Space>, children: <Spin spinning={loading}>{renderWeekly()}</Spin> },
            { key: 'monthly', label: <Space><RiseOutlined />月报</Space>, children: <Spin spinning={loading}>{renderMonthly()}</Spin> },
          ]}
        />
      </Card>
    </div>
  )
}

export default ReportCenter
