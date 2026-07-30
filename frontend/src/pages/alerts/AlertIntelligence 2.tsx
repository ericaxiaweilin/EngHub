/**
 * 预警情报审查页面（017）
 * - 预警审查列表（按严重度/来源/状态筛选）
 * - 每条审查卡片：预警摘要 + AI 严重度标签 + 根因假设 + 处置建议 + 推荐分派
 * - 操作按钮：确认(acknowledge) / 驳回(dismiss)
 * - 顶部统计：待处理/已确认/已驳回数量
 * - 主动巡检按钮
 */
import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Table, Tag, Button, Space, message, Statistic, Row, Col,
  Select, Badge, Tooltip, Typography, Empty, Popconfirm,
} from 'antd'
import {
  AlertOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ReloadOutlined, ThunderboltOutlined, RadarChartOutlined,
} from '@ant-design/icons'
import {
  getAlertReviews, getAlertSummary, acknowledgeAlertReview, runAlertPatrol,
  AlertReview,
} from '../../services/mes'
import { getStoredUser } from '../../services/auth'

const { Text } = Typography

const SEVERITY_CONFIG: Record<string, { color: string; text: string }> = {
  critical: { color: 'red', text: '紧急' },
  high: { color: 'orange', text: '高' },
  medium: { color: 'blue', text: '中' },
  low: { color: 'default', text: '低' },
}

const SOURCE_CONFIG: Record<string, { color: string; text: string }> = {
  andon: { color: 'volcano', text: '安灯工单' },
  defect: { color: 'magenta', text: '质量缺陷' },
  equipment: { color: 'purple', text: '设备故障' },
  wo_timeout: { color: 'gold', text: '工单超时' },
  inventory: { color: 'cyan', text: '库存预警' },
}

const STATUS_CONFIG: Record<string, { color: string; text: string }> = {
  pending: { color: 'processing', text: '待处理' },
  acknowledged: { color: 'success', text: '已确认' },
  dismissed: { color: 'default', text: '已驳回' },
  acted: { color: 'purple', text: '已处置' },
}

const AlertIntelligence: React.FC = () => {
  const user = getStoredUser()
  const factoryId = localStorage.getItem('active_factory_id') || user?.factory_id || ''
  const [loading, setLoading] = useState(false)
  const [reviews, setReviews] = useState<AlertReview[]>([])
  const [summary, setSummary] = useState<any>(null)
  const [filterSource, setFilterSource] = useState<string | undefined>()
  const [filterStatus, setFilterStatus] = useState<string | undefined>()
  const [patrolLoading, setPatrolLoading] = useState(false)

  const fetchData = useCallback(async () => {
    if (!factoryId) return
    setLoading(true)
    try {
      const [revRes, sumRes] = await Promise.all([
        getAlertReviews(factoryId, { source: filterSource, status: filterStatus, limit: 30 }),
        getAlertSummary(factoryId),
      ])
      setReviews(revRes.items || [])
      setSummary(sumRes)
    } catch (e: any) {
      message.error(e?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [factoryId, filterSource, filterStatus])

  useEffect(() => { fetchData() }, [fetchData])

  const handleAcknowledge = async (id: string, action: 'acknowledged' | 'dismissed') => {
    try {
      await acknowledgeAlertReview(id, action)
      message.success(action === 'acknowledged' ? '已确认' : '已驳回')
      fetchData()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败')
    }
  }

  const handlePatrol = async () => {
    setPatrolLoading(true)
    try {
      const res = await runAlertPatrol(factoryId)
      message.success(`巡检完成：发现 ${res.alerts_found} 条预警，创建 ${res.reviews_created} 条审查`)
      fetchData()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '巡检失败')
    } finally {
      setPatrolLoading(false)
    }
  }

  const columns = [
    {
      title: '严重度',
      dataIndex: 'severity_assessment',
      width: 80,
      render: (v: string) => {
        const cfg = SEVERITY_CONFIG[v] || SEVERITY_CONFIG.low
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    {
      title: '来源',
      dataIndex: 'alert_source',
      width: 100,
      render: (v: string) => {
        const cfg = SOURCE_CONFIG[v] || { color: 'default', text: v }
        return <Tag color={cfg.color}>{cfg.text}</Tag>
      },
    },
    {
      title: '关联编码',
      dataIndex: 'alert_ref_code',
      width: 160,
      ellipsis: true,
    },
    {
      title: '预警摘要',
      dataIndex: 'alert_summary',
      ellipsis: true,
      render: (v: string) => (
        <Tooltip title={v} placement="topLeft">
          <Text style={{ fontSize: 12 }}>{v?.split('\n')[0]}</Text>
        </Tooltip>
      ),
    },
    {
      title: '推荐分派',
      dataIndex: 'dispatch_recommendation',
      width: 120,
      ellipsis: true,
      render: (v: string) => v ? <Tag>{v}</Tag> : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => {
        const cfg = STATUS_CONFIG[v] || STATUS_CONFIG.pending
        return <Badge status={cfg.color as any} text={cfg.text} />
      },
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 130,
    },
    {
      title: '操作',
      width: 140,
      render: (_: any, record: AlertReview) => {
        if (record.status !== 'pending') return <Text type="secondary">{record.acknowledged_by}</Text>
        return (
          <Space size={4}>
            <Button size="small" type="primary" icon={<CheckCircleOutlined />}
              onClick={() => handleAcknowledge(record.id, 'acknowledged')}>
              确认
            </Button>
            <Popconfirm title="确认驳回此预警？" onConfirm={() => handleAcknowledge(record.id, 'dismissed')}>
              <Button size="small" danger icon={<CloseCircleOutlined />}>驳回</Button>
            </Popconfirm>
          </Space>
        )
      },
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="待处理" value={summary?.total_pending || 0}
              valueStyle={{ color: '#cf1322' }} prefix={<AlertOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="紧急/高" value={(summary?.by_severity?.critical || 0) + (summary?.by_severity?.high || 0)}
              valueStyle={{ color: '#fa541c' }} prefix={<ThunderboltOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="来源数" value={Object.keys(summary?.by_source || {}).length}
              prefix={<RadarChartOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small" style={{ textAlign: 'center' }}>
            <Button type="primary" icon={<RadarChartOutlined />} loading={patrolLoading}
              onClick={handlePatrol} block>
              主动巡检
            </Button>
          </Card>
        </Col>
      </Row>

      {/* 筛选 + 列表 */}
      <Card
        title={<Space><AlertOutlined /> 预警情报审查</Space>}
        extra={
          <Space>
            <Select allowClear placeholder="来源" style={{ width: 120 }} value={filterSource}
              onChange={setFilterSource}
              options={Object.entries(SOURCE_CONFIG).map(([k, v]) => ({ value: k, label: v.text }))} />
            <Select allowClear placeholder="状态" style={{ width: 100 }} value={filterStatus}
              onChange={setFilterStatus}
              options={Object.entries(STATUS_CONFIG).map(([k, v]) => ({ value: k, label: v.text }))} />
            <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
          </Space>
        }
      >
        {reviews.length === 0 && !loading ? (
          <Empty description="暂无预警审查记录" />
        ) : (
          <Table
            columns={columns}
            dataSource={reviews.map(r => ({ ...r, key: r.id }))}
            loading={loading}
            size="small"
            pagination={{ pageSize: 15, showTotal: (t) => `共 ${t} 条` }}
            expandable={{
              expandedRowRender: (record: AlertReview) => (
                <div style={{ padding: '8px 0' }}>
                  <div style={{ marginBottom: 8 }}>
                    <Text strong>根因假设：</Text>
                    {record.root_cause_hypothesis?.length > 0
                      ? record.root_cause_hypothesis.map((c, i) => <Tag key={i} color="orange">{c}</Tag>)
                      : <Text type="secondary">无</Text>}
                  </div>
                  <div>
                    <Text strong>处置建议：</Text>
                    <ul style={{ margin: '4px 0', paddingLeft: 20 }}>
                      {record.recommended_actions?.map((a, i) => <li key={i}>{a}</li>)}
                    </ul>
                  </div>
                </div>
              ),
            }}
          />
        )}
      </Card>
    </div>
  )
}

export default AlertIntelligence
