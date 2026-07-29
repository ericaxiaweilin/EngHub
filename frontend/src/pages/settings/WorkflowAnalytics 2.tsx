/**
 * 工作流分析 - Workflow Analytics
 * 对接后端 /api/v1/workflow-analytics/*
 * 功能：7条工作流全景、部门交叉热力图、信息断点、物流全景、T+3交期管控
 */
import React, { useState, useEffect, useCallback } from 'react'
import {
  Card, Row, Col, Tag, Table, Space, Button, Typography, Statistic,
  Tabs, Progress, Alert, Spin, Timeline, Badge, Empty,
} from 'antd'
import {
  FundOutlined, ApartmentOutlined, DisconnectOutlined,
  SwapOutlined, ClockCircleOutlined, ReloadOutlined,
  WarningOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const { Text, Title } = Typography
const FACTORY = localStorage.getItem('active_factory_id') || 'FAC_MECH_001'

const STATUS_COLOR: Record<string, string> = {
  green: '#52c41a', yellow: '#faad14', red: '#f5222d',
}

const WorkflowAnalytics: React.FC = () => {
  const [overview, setOverview] = useState<any>(null)
  const [intersections, setIntersections] = useState<any>(null)
  const [gaps, setGaps] = useState<any>(null)
  const [materialFlow, setMaterialFlow] = useState<any>(null)
  const [countdown, setCountdown] = useState<any>(null)
  const [progress, setProgress] = useState<any>(null)
  const [overdue, setOverdue] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    const params = { params: { factory_id: FACTORY } }
    try {
      const [ov, inter, gp, mf, cd, prog, od] = await Promise.allSettled([
        api.get('/api/v1/workflow-analytics/overview', params),
        api.get('/api/v1/workflow-analytics/intersections', params),
        api.get('/api/v1/workflow-analytics/gaps', params),
        api.get('/api/v1/workflow-analytics/material-flow', params),
        api.get('/api/v1/workflow-analytics/t3/countdown', params),
        api.get('/api/v1/workflow-analytics/t3/realtime-progress', params),
        api.get('/api/v1/workflow-analytics/t3/overdue-alerts', params),
      ])
      if (ov.status === 'fulfilled') setOverview(ov.value)
      if (inter.status === 'fulfilled') setIntersections(inter.value)
      if (gp.status === 'fulfilled') setGaps(gp.value)
      if (mf.status === 'fulfilled') setMaterialFlow(mf.value)
      if (cd.status === 'fulfilled') setCountdown(cd.value)
      if (prog.status === 'fulfilled') setProgress(prog.value)
      if (od.status === 'fulfilled') setOverdue(od.value)
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const workflows = overview?.workflows || overview?.items || []
  const gapItems = gaps?.gaps || gaps?.items || []
  const countdownItems = countdown?.orders || countdown?.items || []
  const overdueItems = overdue?.alerts || overdue?.items || []

  const wfColumns = [
    { title: '工作流', dataIndex: 'name', key: 'name', render: (v: string, r: any) => <Text strong>{v || r.key}</Text> },
    { title: '单据量', dataIndex: 'count', key: 'count' },
    {
      title: '状态分布', dataIndex: 'status_distribution', key: 'status',
      render: (v: any) => v ? (
        <Space>{Object.entries(v).map(([k, cnt]) => <Tag key={k}>{k}: {String(cnt)}</Tag>)}</Space>
      ) : '-',
    },
    {
      title: '瓶颈', dataIndex: 'bottleneck', key: 'bottleneck',
      render: (v: string) => v ? <Tag color="red">{v}</Tag> : <Tag color="green">畅通</Tag>,
    },
  ]

  const gapColumns = [
    { title: '断点', dataIndex: 'location', key: 'loc', render: (v: string, r: any) => <Text strong>{v || r.name}</Text> },
    { title: '描述', dataIndex: 'description', key: 'desc' },
    { title: '影响', dataIndex: 'impact', key: 'impact', render: (v: string) => <Tag color="orange">{v || '中'}</Tag> },
    { title: '建议', dataIndex: 'suggestion', key: 'sug', render: (v: string) => <Text type="secondary">{v || '-'}</Text> },
  ]

  const countdownColumns = [
    { title: '订单', dataIndex: 'order_no', key: 'order', render: (v: string, r: any) => <Text strong>{v || r.id}</Text> },
    { title: '客户', dataIndex: 'customer', key: 'customer' },
    {
      title: '剩余天数', dataIndex: 'days_remaining', key: 'days',
      render: (v: number) => {
        const color = v <= 0 ? 'red' : v <= 3 ? 'orange' : 'green'
        return <Tag color={color}>{v <= 0 ? `超期${Math.abs(v)}天` : `${v}天`}</Tag>
      },
    },
    {
      title: '进度', dataIndex: 'progress_pct', key: 'progress',
      render: (v: number) => <Progress percent={v || 0} size="small" style={{ width: 100 }} />,
    },
    {
      title: '灯', dataIndex: 'light', key: 'light',
      render: (v: string) => <Badge color={STATUS_COLOR[v] || '#999'} text={v === 'red' ? '紧急' : v === 'yellow' ? '关注' : '正常'} />,
    },
  ]

  const overdueColumns = [
    { title: '类型', dataIndex: 'type', key: 'type', render: (v: string) => <Tag color="volcano">{v}</Tag> },
    { title: '单号', dataIndex: 'ref_no', key: 'ref', render: (v: string, r: any) => v || r.id },
    { title: '超期天数', dataIndex: 'overdue_days', key: 'days', render: (v: number) => <Text type="danger">{v}天</Text> },
    { title: '责任部门', dataIndex: 'department', key: 'dept' },
    { title: '建议', dataIndex: 'action', key: 'action', render: (v: string) => <Text type="secondary">{v || '-'}</Text> },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}><FundOutlined /> 工作流分析</Title>
        <Button icon={<ReloadOutlined />} onClick={fetchAll}>刷新</Button>
      </Space>

      <Spin spinning={loading}>
        <Tabs items={[
          {
            key: 'overview',
            label: '工作流全景',
            children: (
              <Card size="small">
                <Table dataSource={workflows} columns={wfColumns} rowKey={(r) => r.key || r.name} size="small" pagination={false} />
              </Card>
            ),
          },
          {
            key: 'intersections',
            label: '部门交叉',
            children: (
              <Card size="small" title={<><ApartmentOutlined /> 部门交互热力图</>}>
                {intersections?.matrix || intersections?.items ? (
                  <Table dataSource={intersections.items || intersections.matrix || []} size="small" pagination={false}
                    rowKey={(r) => r.from || r.department_a || r.key}
                    columns={[
                      { title: '部门A', dataIndex: 'from', key: 'from', render: (v: string, r: any) => v || r.department_a },
                      { title: '部门B', dataIndex: 'to', key: 'to', render: (v: string, r: any) => v || r.department_b },
                      { title: '交互频次', dataIndex: 'frequency', key: 'freq', render: (v: number) => <Progress percent={Math.min(v * 10, 100)} size="small" format={() => String(v)} /> },
                      { title: '需要协调', dataIndex: 'needs_coordinator', key: 'coord', render: (v: boolean) => v ? <Tag color="orange">是</Tag> : <Tag color="green">否</Tag> },
                    ]}
                  />
                ) : <Empty description="暂无数据" />}
              </Card>
            ),
          },
          {
            key: 'gaps',
            label: '信息断点',
            children: (
              <Card size="small" title={<><DisconnectOutlined /> 信息断点分析</>}>
                <Table dataSource={gapItems} columns={gapColumns} rowKey={(r) => r.location || r.name || r.id} size="small" pagination={false} />
              </Card>
            ),
          },
          {
            key: 'material',
            label: '物流全景',
            children: (
              <Card size="small" title={<><SwapOutlined /> 物流链路（进→存→产→出）</>}>
                {materialFlow?.stages || materialFlow?.nodes ? (
                  <Row gutter={16}>
                    {(materialFlow.stages || materialFlow.nodes || []).map((s: any, i: number) => (
                      <Col span={6} key={i}>
                        <Card size="small" title={s.name || s.stage} style={{ textAlign: 'center' }}>
                          <Statistic value={s.count || s.quantity || 0} suffix={s.unit || '件'} />
                          {s.bottleneck && <Tag color="red" style={{ marginTop: 8 }}>{s.bottleneck}</Tag>}
                        </Card>
                      </Col>
                    ))}
                  </Row>
                ) : <Empty description="暂无数据" />}
              </Card>
            ),
          },
          {
            key: 't3',
            label: 'T+3交期',
            children: (
              <Space direction="vertical" style={{ width: '100%' }} size={16}>
                <Card size="small" title={<><ClockCircleOutlined /> 订单交期倒计时</>}>
                  <Table dataSource={countdownItems} columns={countdownColumns} rowKey={(r) => r.order_no || r.id} size="small" pagination={false} />
                </Card>
                <Card size="small" title={<><WarningOutlined /> 超期预警</>}>
                  {overdueItems.length > 0 ? (
                    <Table dataSource={overdueItems} columns={overdueColumns} rowKey={(r) => r.ref_no || r.id} size="small" pagination={false} />
                  ) : <Alert type="success" message="当前无超期项目" showIcon icon={<CheckCircleOutlined />} />}
                </Card>
              </Space>
            ),
          },
        ]} />
      </Spin>
    </div>
  )
}

export default WorkflowAnalytics
