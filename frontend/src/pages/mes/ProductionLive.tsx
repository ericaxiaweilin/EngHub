import React, { useEffect, useState, useCallback, useRef } from 'react'
import {
  Card, Row, Col, Statistic, Tag, Space, Badge, Empty, Spin,
  Progress, Typography, Tooltip, Button,
} from 'antd'
import {
  DashboardOutlined, CheckCircleOutlined, WarningOutlined,
  ReloadOutlined, FullscreenOutlined, AlertOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../../services/api'

const { Title, Text } = Typography
const FACTORY = 'factory-sh-01'

const MOCK_LIVE = { total_output: 1250, target_output: 1500, oee: 78.5, active_stations: 8, total_stations: 12, defect_rate: 1.8, running_orders: 5 }
const MOCK_TREND = { hours: ['08:00','09:00','10:00','11:00','12:00','13:00','14:00'], output: [120,145,160,155,80,150,140], target: [150,150,150,150,100,150,150] }
const MOCK_GRID = { stations: [{ id: 'CNC-01', name: 'CNC-01', status: 'running' },{ id: 'CNC-02', name: 'CNC-02', status: 'idle' },{ id: 'WLD-01', name: '焊接-01', status: 'maintenance' },{ id: 'ASSY-01', name: '装配-01', status: 'running' }] }
const MOCK_ISSUES = { issues: [{ type: 'equipment', count: 3, label: '设备故障' },{ type: 'material', count: 2, label: '缺料' },{ type: 'quality', count: 1, label: '质量异常' }] }

// 工位状态色彩
const stationStatusConfig: Record<string, { color: string; bg: string; label: string }> = {
  running: { color: '#52c41a', bg: '#f6ffed', label: '运行' },
  idle: { color: '#1890ff', bg: '#e6f7ff', label: '空闲' },
  maintenance: { color: '#faad14', bg: '#fffbe6', label: '维护' },
  breakdown: { color: '#f5222d', bg: '#fff2f0', label: '故障' },
}

const ProductionLive: React.FC = () => {
  const [live, setLive] = useState<any>(null)
  const [trend, setTrend] = useState<any>(null)
  const [grid, setGrid] = useState<any>(null)
  const [issues, setIssues] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState(dayjs())
  const timerRef = useRef<any>(null)

  const loadAll = useCallback(async () => {
    try {
      const [liveRes, trendRes, gridRes, issuesRes]: any[] = await Promise.allSettled([
        api.get('/api/v1/dashboard/live', { params: { factory_id: FACTORY } }),
        api.get('/api/v1/dashboard/hourly-trend', { params: { factory_id: FACTORY } }),
        api.get('/api/v1/dashboard/station-grid', { params: { factory_id: FACTORY } }),
        api.get('/api/v1/dashboard/top-issues', { params: { factory_id: FACTORY } }),
      ])
      setLive(liveRes.status === 'fulfilled' ? (liveRes.value ?? null) : null)
      setTrend(trendRes.status === 'fulfilled' ? (trendRes.value ?? null) : null)
      setGrid(gridRes.status === 'fulfilled' ? (gridRes.value ?? null) : null)
      setIssues(issuesRes.status === 'fulfilled' ? (issuesRes.value ?? null) : null)
      setLastUpdate(dayjs())
    } catch { /* ignore */ } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAll()
    // 10秒自动刷新
    timerRef.current = setInterval(loadAll, 10000)
    return () => clearInterval(timerRef.current)
  }, [loadAll])

  if (loading && !live) {
    return <div style={{ textAlign: 'center', padding: 100 }}><Spin size="large" /></div>
  }

  const yieldColor = (live?.yield_rate || 0) >= 95 ? '#52c41a' : (live?.yield_rate || 0) >= 90 ? '#faad14' : '#f5222d'
  const achieveColor = (live?.achievement_rate || 0) >= 100 ? '#52c41a' : (live?.achievement_rate || 0) >= 80 ? '#faad14' : '#f5222d'

  return (
    <div style={{ padding: 24, background: '#f0f2f5', minHeight: '100vh' }}>
      {/* 标题栏 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 20 }}>
        <Col>
          <Space>
            <DashboardOutlined style={{ fontSize: 24, color: '#1890ff' }} />
            <Title level={3} style={{ margin: 0 }}>实时生产看板</Title>
            <Tag color="blue">{dayjs().format('YYYY-MM-DD')}</Tag>
          </Space>
        </Col>
        <Col>
          <Space>
            <Text type="secondary">更新: {lastUpdate.format('HH:mm:ss')}</Text>
            <Button icon={<ReloadOutlined />} size="small" onClick={loadAll}>刷新</Button>
            <Tooltip title="全屏模式（投屏到车间电视）">
              <Button icon={<FullscreenOutlined />} size="small" onClick={() => {
                document.documentElement.requestFullscreen?.()
              }} />
            </Tooltip>
          </Space>
        </Col>
      </Row>

      {/* 核心指标卡片 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={5}>
          <Card>
            <Statistic
              title="今日产出"
              value={live?.total_output || 0}
              valueStyle={{ fontSize: 32, fontWeight: 700, color: '#1890ff' }}
              suffix="件"
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Statistic
              title="目标达成率"
              value={live?.achievement_rate || 0}
              precision={1}
              valueStyle={{ fontSize: 32, fontWeight: 700, color: achieveColor }}
              suffix="%"
            />
            {live?.target_output > 0 && (
              <Progress
                percent={Math.min(live?.achievement_rate || 0, 100)}
                showInfo={false}
                strokeColor={achieveColor}
                size="small"
                style={{ marginTop: 8 }}
              />
            )}
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Statistic
              title="良品率"
              value={live?.yield_rate || 0}
              precision={2}
              valueStyle={{ fontSize: 32, fontWeight: 700, color: yieldColor }}
              suffix="%"
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card>
            <Statistic
              title="在制工单"
              value={live?.wip_count || 0}
              valueStyle={{ fontSize: 32, fontWeight: 700, color: '#722ed1' }}
              suffix="单"
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="未读预警"
              value={live?.unread_alerts || 0}
              valueStyle={{ fontSize: 32, fontWeight: 700, color: (live?.unread_alerts || 0) > 0 ? '#f5222d' : '#52c41a' }}
              prefix={(live?.unread_alerts || 0) > 0 ? <AlertOutlined /> : <CheckCircleOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        {/* 左侧：小时产出趋势 */}
        <Col span={14}>
          <Card title="小时产出趋势" size="small" style={{ marginBottom: 16 }}>
            {trend?.today?.length > 0 ? (
              <div style={{ display: 'flex', alignItems: 'flex-end', height: 160, gap: 4, padding: '0 8px' }}>
                {Array.from({ length: 16 }, (_, i) => i + 6).map(hour => {
                  const todayItem = trend.today.find((t: any) => t.hour === hour)
                  const yesterdayItem = trend.yesterday?.find((t: any) => t.hour === hour)
                  const maxVal = Math.max(...(trend.today.map((t: any) => t.output) || [1]), 1)
                  const h = todayItem ? Math.max((todayItem.output / maxVal) * 140, 4) : 4
                  const yh = yesterdayItem ? Math.max((yesterdayItem.output / maxVal) * 140, 2) : 0
                  return (
                    <Tooltip key={hour} title={`${hour}:00 | 今日: ${todayItem?.output || 0} | 昨日: ${yesterdayItem?.output || 0}`}>
                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                        <div style={{ position: 'relative', width: '100%', height: 140, display: 'flex', alignItems: 'flex-end', justifyContent: 'center' }}>
                          {yh > 0 && (
                            <div style={{ position: 'absolute', bottom: 0, width: '60%', height: yh, background: '#e8e8e8', borderRadius: 2 }} />
                          )}
                          <div style={{ width: '60%', height: h, background: todayItem ? '#1890ff' : '#f0f0f0', borderRadius: 2, position: 'relative', zIndex: 1 }} />
                        </div>
                        <Text style={{ fontSize: 10, color: '#999' }}>{hour}</Text>
                      </div>
                    </Tooltip>
                  )
                })}
              </div>
            ) : (
              <Empty description="暂无产出数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
            <div style={{ textAlign: 'center', marginTop: 8 }}>
              <Space>
                <Badge color="#1890ff" text="今日" />
                <Badge color="#e8e8e8" text="昨日" />
              </Space>
            </div>
          </Card>

          {/* 工位状态矩阵 */}
          <Card title="工位状态" size="small">
            {grid?.stations?.length > 0 ? (
              <Row gutter={[8, 8]}>
                {grid.stations.map((s: any) => {
                  const cfg = stationStatusConfig[s.status] || stationStatusConfig.idle
                  return (
                    <Col key={s.station_id} span={4}>
                      <Tooltip title={`${s.station_name} - ${cfg.label}`}>
                        <div style={{
                          padding: '12px 8px',
                          borderRadius: 8,
                          background: cfg.bg,
                          border: `1px solid ${cfg.color}33`,
                          textAlign: 'center',
                        }}>
                          <div style={{ width: 10, height: 10, borderRadius: '50%', background: cfg.color, margin: '0 auto 6px' }} />
                          <Text style={{ fontSize: 11 }} ellipsis>{s.station_name || s.station_id}</Text>
                          <br />
                          <Text style={{ fontSize: 10, color: cfg.color }}>{cfg.label}</Text>
                        </div>
                      </Tooltip>
                    </Col>
                  )
                })}
              </Row>
            ) : (
              <Empty description="暂无工位数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
            {grid?.summary && (
              <div style={{ marginTop: 12, textAlign: 'center' }}>
                <Space>
                  {Object.entries(grid.summary).map(([k, v]) => (
                    <Tag key={k} color={stationStatusConfig[k]?.color}>
                      {stationStatusConfig[k]?.label || k}: {v as number}
                    </Tag>
                  ))}
                </Space>
              </div>
            )}
          </Card>
        </Col>

        {/* 右侧：异常事件流 */}
        <Col span={10}>
          <Card
            title={<Space><WarningOutlined style={{ color: '#faad14' }} /> 异常事件</Space>}
            size="small"
            styles={{ body: { maxHeight: 420, overflow: 'auto' } }}
          >
            {issues?.items?.length > 0 ? (
              issues.items.map((item: any) => (
                <div
                  key={item.id}
                  style={{
                    padding: '10px 12px',
                    marginBottom: 8,
                    borderRadius: 8,
                    borderLeft: `3px solid ${item.severity === 'critical' ? '#f5222d' : '#faad14'}`,
                    background: item.severity === 'critical' ? '#fff2f0' : '#fffbe6',
                  }}
                >
                  <Row justify="space-between">
                    <Col>
                      <Text strong style={{ fontSize: 13 }}>{item.title}</Text>
                    </Col>
                    <Col>
                      <Tag color={item.severity === 'critical' ? 'red' : 'orange'} style={{ fontSize: 11 }}>
                        {item.severity === 'critical' ? '严重' : '警告'}
                      </Tag>
                    </Col>
                  </Row>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {item.message}
                  </Text>
                  <br />
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {item.triggered_at ? dayjs(item.triggered_at).format('HH:mm') : ''} | {item.source_id || ''}
                  </Text>
                </div>
              ))
            ) : (
              <div style={{ textAlign: 'center', padding: 40 }}>
                <CheckCircleOutlined style={{ fontSize: 40, color: '#52c41a' }} />
                <br />
                <Text type="secondary" style={{ marginTop: 8, display: 'block' }}>暂无异常，生产正常</Text>
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default ProductionLive
