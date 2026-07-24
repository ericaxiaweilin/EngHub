import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Row, Col, Tag, Space, Statistic, Empty, Spin, Badge, Tooltip,
  Progress, Button,
} from 'antd'
import {
  ToolOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ClockCircleOutlined, ThunderboltOutlined, ReloadOutlined,
  DashboardOutlined, WarningOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../../services/api'

const FACTORY = 'F001'

// 状态色彩系统（参考 ERPNext Workstation Status）
const statusConfig: Record<string, { color: string; bg: string; border: string; icon: React.ReactNode; label: string }> = {
  running: { color: '#52c41a', bg: '#f6ffed', border: '#b7eb8f', icon: <ThunderboltOutlined />, label: '运行中' },
  idle: { color: '#1890ff', bg: '#e6f7ff', border: '#91d5ff', icon: <ClockCircleOutlined />, label: '空闲' },
  maintenance: { color: '#faad14', bg: '#fffbe6', border: '#ffe58f', icon: <ToolOutlined />, label: '维护中' },
  breakdown: { color: '#f5222d', bg: '#fff2f0', border: '#ffccc7', icon: <CloseCircleOutlined />, label: '故障' },
  available: { color: '#1890ff', bg: '#e6f7ff', border: '#91d5ff', icon: <CheckCircleOutlined />, label: '可用' },
}

interface WorkstationCard {
  id: string
  station_id: string
  station_name: string
  status: string
  current_wo?: string
  current_product?: string
  operator?: string
  oee?: number
  last_downtime?: string
  running_minutes?: number
}

const PlantFloor: React.FC = () => {
  const [stations, setStations] = useState<WorkstationCard[]>([])
  const [loading, setLoading] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/equipment', { params: { factory_id: FACTORY } })
      const equips = res?.items || res || []

      // 转换为工位卡片
      const cards: WorkstationCard[] = (Array.isArray(equips) ? equips : []).map((eq: any) => ({
        id: eq.id,
        station_id: eq.station_id || eq.equipment_code,
        station_name: eq.equipment_name || eq.station_id || eq.equipment_code,
        status: eq.status || 'available',
        current_wo: eq.current_wo,
        current_product: eq.current_product,
        operator: eq.operator,
        oee: eq.oee,
        running_minutes: eq.running_minutes,
      }))

      setStations(cards)
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData])

  // 状态分布统计
  const statusCounts = stations.reduce((acc: any, s) => {
    acc[s.status] = (acc[s.status] || 0) + 1
    return acc
  }, {})

  const totalStations = stations.length
  const runningCount = statusCounts['running'] || 0
  const utilization = totalStations > 0 ? Math.round((runningCount / totalStations) * 100) : 0

  return (
    <div>
      {/* 顶部 KPI 条 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={5}>
          <Card size="small" style={{ borderRadius: 8 }}>
            <Statistic
              title="工位总数"
              value={totalStations}
              prefix={<DashboardOutlined style={{ color: '#1890ff' }} />}
              valueStyle={{ fontSize: 28, fontWeight: 700 }}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small" style={{ borderRadius: 8, background: '#f6ffed', border: '1px solid #b7eb8f' }}>
            <Statistic
              title="运行中"
              value={runningCount}
              prefix={<ThunderboltOutlined style={{ color: '#52c41a' }} />}
              valueStyle={{ fontSize: 28, fontWeight: 700, color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small" style={{ borderRadius: 8 }}>
            <Statistic
              title="设备利用率"
              value={utilization}
              suffix="%"
              prefix={<ToolOutlined style={{ color: '#722ed1' }} />}
              valueStyle={{ fontSize: 28, fontWeight: 700, color: '#722ed1' }}
            />
          </Card>
        </Col>
        <Col span={5}>
          <Card size="small" style={{ borderRadius: 8, background: statusCounts['breakdown'] ? '#fff2f0' : undefined, border: statusCounts['breakdown'] ? '1px solid #ffccc7' : undefined }}>
            <Statistic
              title="故障"
              value={statusCounts['breakdown'] || 0}
              prefix={<WarningOutlined style={{ color: '#f5222d' }} />}
              valueStyle={{ fontSize: 28, fontWeight: 700, color: '#f5222d' }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small" style={{ borderRadius: 8, height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
              刷新
            </Button>
          </Card>
        </Col>
      </Row>

      {/* 车间楼层网格 */}
      <Spin spinning={loading}>
        {stations.length === 0 ? (
          <Empty description="暂无工位数据，请在基础数据中添加设备" style={{ marginTop: 80 }} />
        ) : (
          <Row gutter={[16, 16]}>
            {stations.map((station) => {
              const cfg = statusConfig[station.status] || statusConfig['available']
              return (
                <Col key={station.id} xs={12} sm={8} md={6} lg={4}>
                  <Card
                    size="small"
                    hoverable
                    style={{
                      borderRadius: 10,
                      border: `2px solid ${cfg.border}`,
                      background: cfg.bg,
                      transition: 'all 0.3s',
                    }}
                    bodyStyle={{ padding: '14px 16px' }}
                  >
                    {/* 状态指示条 */}
                    <div style={{
                      position: 'absolute', top: 0, left: 0, right: 0, height: 4,
                      background: cfg.color, borderRadius: '10px 10px 0 0',
                    }} />

                    <Space direction="vertical" size={6} style={{ width: '100%' }}>
                      {/* 工位名 + 状态 */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontWeight: 700, fontSize: 14 }}>{station.station_name}</span>
                        <Badge status={station.status === 'running' ? 'processing' : station.status === 'breakdown' ? 'error' : 'default'} />
                      </div>

                      {/* 状态标签 */}
                      <Tag
                        icon={cfg.icon}
                        color={cfg.color}
                        style={{ borderRadius: 4, fontWeight: 600 }}
                      >
                        {cfg.label}
                      </Tag>

                      {/* 当前工单 */}
                      {station.current_wo && (
                        <div style={{ fontSize: 12, color: '#595959' }}>
                          <div>📋 {station.current_wo}</div>
                          {station.current_product && <div>📦 {station.current_product}</div>}
                        </div>
                      )}

                      {/* OEE 进度 */}
                      {station.oee !== undefined && station.oee !== null && (
                        <Tooltip title={`OEE: ${station.oee}%`}>
                          <Progress
                            percent={Math.round(station.oee)}
                            size="small"
                            strokeColor={station.oee >= 85 ? '#52c41a' : station.oee >= 60 ? '#faad14' : '#f5222d'}
                            format={(p) => `${p}%`}
                          />
                        </Tooltip>
                      )}
                    </Space>
                  </Card>
                </Col>
              )
            })}
          </Row>
        )}
      </Spin>

      {/* 底部图例 */}
      <Card size="small" style={{ marginTop: 20, borderRadius: 8 }}>
        <Space size={24}>
          {Object.entries(statusConfig).map(([key, cfg]) => (
            <Space key={key} size={4}>
              <div style={{ width: 12, height: 12, borderRadius: 3, background: cfg.color }} />
              <span style={{ fontSize: 12, color: '#595959' }}>{cfg.label}</span>
            </Space>
          ))}
          <span style={{ fontSize: 12, color: '#999', marginLeft: 16 }}>
            最后更新: {dayjs().format('HH:mm:ss')}
          </span>
        </Space>
      </Card>
    </div>
  )
}

export default PlantFloor
