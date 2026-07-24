import React, { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Space, Button, message, Typography, Row, Col,
  Statistic, Badge, Progress, Empty,
} from 'antd'
import {
  AlertOutlined, CheckCircleOutlined, ReloadOutlined,
  WarningOutlined, StopOutlined, DashboardOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'

const { Title, Text } = Typography
const FACTORY = 'F001'

const alertTypeConfig: Record<string, { color: string; label: string; icon: React.ReactNode }> = {
  below_safety: { color: 'red', label: '低于安全库存', icon: <WarningOutlined /> },
  above_max: { color: 'orange', label: '超过最大库存', icon: <StopOutlined /> },
  dead_stock: { color: 'purple', label: '呆滞料', icon: <StopOutlined /> },
  expiring: { color: 'gold', label: '即将过期', icon: <WarningOutlined /> },
}

const severityColors: Record<string, string> = {
  critical: '#f5222d', warning: '#faad14', info: '#1890ff',
}

const StockAlerts: React.FC = () => {
  const [alerts, setAlerts] = useState<any[]>([])
  const [stats, setStats] = useState<any>({})
  const [health, setHealth] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [checking, setChecking] = useState(false)

  const loadAlerts = async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/wms/alerts', { params: { factory_id: FACTORY } })
      setAlerts(res?.items || [])
      setStats(res?.stats || {})
    } catch { /* ignore */ } finally { setLoading(false) }
  }

  const loadHealth = async () => {
    try {
      const res: any = await api.get('/api/v1/wms/health', { params: { factory_id: FACTORY } })
      setHealth(res)
    } catch { /* ignore */ }
  }

  useEffect(() => { loadAlerts(); loadHealth() }, [])

  const handleCheck = async () => {
    setChecking(true)
    try {
      const res: any = await api.post(`/api/v1/wms/alerts/check?factory_id=${FACTORY}`)
      message.success(`检查完成：${res.materials_checked} 种物料，新增 ${res.alerts_created} 条预警`)
      loadAlerts()
      loadHealth()
    } catch (e: any) {
      message.error('检查失败')
    } finally { setChecking(false) }
  }

  const handleResolve = async (id: string) => {
    try {
      await api.post(`/api/v1/wms/alerts/${id}/resolve`)
      message.success('已解决')
      loadAlerts()
    } catch { message.error('操作失败') }
  }

  const columns: ColumnsType<any> = [
    { title: '类型', dataIndex: 'alert_type', key: 'type', width: 130,
      render: (v: string) => {
        const cfg = alertTypeConfig[v]
        return cfg ? <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag> : <Tag>{v}</Tag>
      }},
    { title: '物料', key: 'material', width: 150,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text strong>{r.material_code}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{r.material_name}</Text>
        </Space>
      )},
    { title: '当前库存', dataIndex: 'current_qty', key: 'qty', width: 90, align: 'right',
      render: (v, r) => (
        <Text style={{ color: r.alert_type === 'below_safety' ? '#f5222d' : undefined }}>{v}</Text>
      )},
    { title: '阈值/天数', key: 'threshold', width: 100, align: 'right',
      render: (_, r) => r.alert_type === 'dead_stock'
        ? <Text type="danger">{r.days_inactive}天</Text>
        : <Text>{r.threshold_qty}</Text>
    },
    { title: '严重度', dataIndex: 'severity', key: 'severity', width: 80,
      render: (v: string) => (
        <Badge color={severityColors[v] || '#999'} text={v === 'critical' ? '严重' : v === 'warning' ? '警告' : '提示'} />
      )},
    { title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (v: string) => (
        <Tag color={v === 'open' ? 'red' : v === 'acknowledged' ? 'orange' : 'green'}>
          {v === 'open' ? '待处理' : v === 'acknowledged' ? '已确认' : '已解决'}
        </Tag>
      )},
    { title: '操作', key: 'action', width: 80,
      render: (_, r) => r.status !== 'resolved' && (
        <Button size="small" type="link" icon={<CheckCircleOutlined />} onClick={() => handleResolve(r.id)}>
          解决
        </Button>
      )},
  ]

  const healthScore = health?.health_score ?? 100

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <AlertOutlined style={{ fontSize: 22, color: '#faad14' }} />
            <Title level={4} style={{ margin: 0 }}>库存预警中心</Title>
          </Space>
        </Col>
        <Col>
          <Button type="primary" icon={<ReloadOutlined />} loading={checking} onClick={handleCheck}>
            执行预警检查
          </Button>
        </Col>
      </Row>

      {/* 健康度 + 统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <div style={{ textAlign: 'center' }}>
              <Progress
                type="dashboard"
                percent={healthScore}
                strokeColor={healthScore >= 80 ? '#52c41a' : healthScore >= 60 ? '#faad14' : '#f5222d'}
                size={100}
              />
              <div><Text type="secondary">库存健康度</Text></div>
            </div>
          </Card>
        </Col>
        <Col span={6}><Card size="small"><Statistic title="SKU 数" value={health?.sku_count || 0} prefix={<DashboardOutlined />} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="缺料预警" value={stats.critical || 0} valueStyle={{ color: '#f5222d' }} prefix={<WarningOutlined />} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="呆滞料" value={alerts.filter(a => a.alert_type === 'dead_stock' && a.status === 'open').length} valueStyle={{ color: '#722ed1' }} prefix={<StopOutlined />} /></Card></Col>
      </Row>

      {/* 预警列表 */}
      <Card title={<Space><AlertOutlined /> 预警列表 <Tag>{alerts.length}</Tag></Space>}>
        {alerts.length === 0 ? (
          <Empty description="暂无预警，库存状态良好" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <Table columns={columns} dataSource={alerts} rowKey="id" size="small"
            loading={loading} pagination={{ pageSize: 15 }} />
        )}
      </Card>
    </div>
  )
}

export default StockAlerts
