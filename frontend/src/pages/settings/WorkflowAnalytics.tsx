/**
 * 工作流分析 - Workflow Analytics
 * 对接后端 /api/v1/workflow-analytics/*
 * 功能：7条工作流全景、部门交叉、信息断点、物流全景、T+3交期管控
 * 注意：后端 overview.workflows / overdue.alerts / material-flow.flow 为 dict 结构，
 *       这里统一转数组并做 Array.isArray 兜底，防止 Table 崩溃白屏
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Card, Row, Col, Tag, Table, Space, Button, Typography, Statistic,
  Tabs, Progress, Alert, Spin, Badge, Empty,
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

/** 任意结构安全转数组 */
const asArray = (v: any): any[] => (Array.isArray(v) ? v : [])

const WorkflowAnalytics: React.FC = () => {
  const [overview, setOverview] = useState<any>(null)
  const [intersections, setIntersections] = useState<any>(null)
  const [gaps, setGaps] = useState<any>(null)
  const [materialFlow, setMaterialFlow] = useState<any>(null)
  const [countdown, setCountdown] = useState<any>(null)
  const [overdue, setOverdue] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    const params = { params: { factory_id: FACTORY } }
    try {
      const [ov, inter, gp, mf, cd, od] = await Promise.allSettled([
        api.get('/api/v1/workflow-analytics/overview', params),
        api.get('/api/v1/workflow-analytics/intersections', params),
        api.get('/api/v1/workflow-analytics/gaps', params),
        api.get('/api/v1/workflow-analytics/material-flow', params),
        api.get('/api/v1/workflow-analytics/t3/countdown', params),
        api.get('/api/v1/workflow-analytics/t3/overdue-alerts', params),
      ])
      if (ov.status === 'fulfilled') setOverview(ov.value)
      if (inter.status === 'fulfilled') setIntersections(inter.value)
      if (gp.status === 'fulfilled') setGaps(gp.value)
      if (mf.status === 'fulfilled') setMaterialFlow(mf.value)
      if (cd.status === 'fulfilled') setCountdown(cd.value)
      if (od.status === 'fulfilled') setOverdue(od.value)
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  // overview.workflows: dict {WF1_xxx: {description, total_*, ...状态数组}} → 数组
  const workflows = useMemo(() => {
    const wf = overview?.workflows
    if (Array.isArray(wf)) return wf
    if (wf && typeof wf === 'object') {
      return Object.entries(wf).map(([key, v]: [string, any]) => {
        const count = v?.total_orders ?? v?.total_po ?? v?.total_wo
          ?? v?.total_inspections ?? v?.total_transfers ?? null
        // 找第一个带 status/result 的数组字段作为状态分布
        const statusArr = Object.values(v || {}).find(
          (x: any) => Array.isArray(x) && x.length > 0 && (x[0]?.status || x[0]?.result || x[0]?.inspect_type || x[0]?.outbound_type || x[0]?.transaction_type),
        ) as any[] | undefined
        const dist: Record<string, number> = {}
        asArray(statusArr).forEach((s: any) => {
          const label = s.status || s.result || s.transaction_type || s.outbound_type || s.inspect_type || '其他'
          dist[label] = (dist[label] || 0) + (s.cnt || 0)
        })
        return {
          key, name: key.replace(/^WF\d+_/, ''), description: v?.description,
          count, status_distribution: Object.keys(dist).length ? dist : null,
          completion_rate: v?.completion_rate, defect_rate: v?.defect_rate,
        }
      })
    }
    return []
  }, [overview])

  const gapItems = useMemo(() => asArray(gaps?.gaps || gaps?.items), [gaps])
  const countdownItems = useMemo(() => asArray(countdown?.orders || countdown?.items), [countdown])
  const interItems = useMemo(() => asArray(intersections?.intersections || intersections?.items), [intersections])

  // overdue.alerts: dict {类型: {count, action, records[]}} → 逐条展开
  const overdueItems = useMemo(() => {
    const al = overdue?.alerts
    if (Array.isArray(al)) return al
    if (al && typeof al === 'object') {
      const rows: any[] = []
      Object.entries(al).forEach(([type, v]: [string, any]) => {
        asArray(v?.records).forEach((r: any, i: number) => {
          rows.push({
            _rk: `${type}-${i}`, type, action: v?.action,
            ref_no: r.work_order_code || r.po_code || r.order_code || '-',
            detail: r.product_id || r.product_name || r.material_code || r.supplier_name || r.customer_name || '-',
            qty: r.planned_qty ?? r.qty ?? r.quantity,
            due: (r.planned_due || r.expected_date || r.delivery_date || '').slice(0, 10),
            status: r.status,
          })
        })
      })
      return rows
    }
    return []
  }, [overdue])

  // material-flow.flow: dict {阶段: [明细]} → 阶段卡片
  const flowStages = useMemo(() => {
    const fl = materialFlow?.flow
    if (fl && typeof fl === 'object' && !Array.isArray(fl)) {
      return Object.entries(fl).map(([stage, items]: [string, any]) => ({
        stage,
        name: stage.replace(/^\w+_/, ''),
        count: asArray(items).reduce((s: number, it: any) => s + (it.total_qty || 0), 0),
        rows: asArray(items).length,
      }))
    }
    return asArray(materialFlow?.stages || materialFlow?.nodes)
  }, [materialFlow])

  const wfColumns = [
    { title: '工作流', dataIndex: 'name', key: 'name', width: 120, render: (v: string, r: any) => <Text strong>{v || r.key}</Text> },
    { title: '链路', dataIndex: 'description', key: 'desc', render: (v: string) => <Text type="secondary">{v || '-'}</Text> },
    { title: '单据量', dataIndex: 'count', key: 'count', width: 90, render: (v: any) => v ?? '-' },
    {
      title: '状态分布', dataIndex: 'status_distribution', key: 'status',
      render: (v: any) => v ? (
        <Space wrap>{Object.entries(v).map(([k, cnt]) => <Tag key={k}>{k}: {String(cnt)}</Tag>)}</Space>
      ) : '-',
    },
    {
      title: '完成率/不良率', key: 'rates', width: 150,
      render: (_: any, r: any) => (r.completion_rate != null || r.defect_rate != null) ? (
        <Space>
          {r.completion_rate != null && <Tag color="blue">完成 {r.completion_rate}%</Tag>}
          {r.defect_rate != null && <Tag color={r.defect_rate > 3 ? 'red' : 'green'}>不良 {r.defect_rate}%</Tag>}
        </Space>
      ) : '-',
    },
  ]

  const gapColumns = [
    { title: '断点', dataIndex: 'name', key: 'name', render: (v: string, r: any) => <Text strong>{v || r.location || r.gap_id}</Text> },
    { title: '描述', dataIndex: 'description', key: 'desc' },
    { title: '影响记录数', dataIndex: 'affected', key: 'affected', width: 110, render: (v: number) => <Tag color="orange">{v ?? '-'}</Tag> },
    { title: '解决方案', dataIndex: 'solution', key: 'solution', render: (v: string, r: any) => <Text type="secondary">{v || r.suggestion || '-'}</Text> },
  ]

  const countdownColumns = [
    { title: '订单', dataIndex: 'order_code', key: 'order', render: (v: string, r: any) => <Text strong>{v || r.order_no || r.id}</Text> },
    { title: '客户', dataIndex: 'customer', key: 'customer' },
    { title: '产品', dataIndex: 'product', key: 'product' },
    { title: '数量', dataIndex: 'quantity', key: 'qty', width: 90 },
    { title: '交期', dataIndex: 'delivery_date', key: 'date', width: 110, render: (v: string) => (v || '').slice(0, 10) },
    {
      title: '剩余天数', key: 'days', width: 110,
      render: (_: any, r: any) => {
        const v = r.days_left ?? r.days_remaining ?? 0
        const color = v <= 0 ? 'red' : v <= 3 ? 'orange' : 'green'
        return <Tag color={color}>{v <= 0 ? `超期${Math.abs(v)}天` : `${v}天`}</Tag>
      },
    },
    {
      title: '状态', dataIndex: 'light', key: 'light', width: 120,
      render: (v: string, r: any) => <Badge color={STATUS_COLOR[v] || '#999'} text={r.status_text || (v === 'red' ? '紧急' : v === 'yellow' ? '关注' : '正常')} />,
    },
  ]

  const overdueColumns = [
    { title: '类型', dataIndex: 'type', key: 'type', width: 130, render: (v: string) => <Tag color="volcano">{v}</Tag> },
    { title: '单号', dataIndex: 'ref_no', key: 'ref', render: (v: string) => <Text strong>{v}</Text> },
    { title: '对象', dataIndex: 'detail', key: 'detail' },
    { title: '数量', dataIndex: 'qty', key: 'qty', width: 90 },
    { title: '日期', dataIndex: 'due', key: 'due', width: 110 },
    { title: '处理动作', dataIndex: 'action', key: 'action', render: (v: string) => <Text type="secondary">{v || '-'}</Text> },
  ]

  const interColumns = [
    { title: '交叉点', dataIndex: 'name', key: 'name', render: (v: string, r: any) => <Text strong>{v || r.id}</Text> },
    { title: '触发场景', dataIndex: 'trigger', key: 'trigger' },
    { title: '交互量', dataIndex: 'volume', key: 'volume', width: 140, render: (v: number) => <Progress percent={Math.min((v || 0) / 4, 100)} size="small" format={() => String(v ?? 0)} /> },
    { title: '信息流', dataIndex: 'info_flow', key: 'flow', render: (v: string) => <Text type="secondary">{v || '-'}</Text> },
    { title: '纸单现状', dataIndex: 'paper', key: 'paper', render: (v: string) => v ? <Tag color="orange">{v}</Tag> : '-' },
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
              <Card size="small" title={<><ApartmentOutlined /> 部门交叉协作点</>}>
                {interItems.length > 0 ? (
                  <Table dataSource={interItems} columns={interColumns} size="small" pagination={false}
                    rowKey={(r) => r.id || r.name} />
                ) : <Empty description="暂无数据" />}
              </Card>
            ),
          },
          {
            key: 'gaps',
            label: '信息断点',
            children: (
              <Card size="small" title={<><DisconnectOutlined /> 信息断点分析</>}>
                <Table dataSource={gapItems} columns={gapColumns} rowKey={(r) => r.gap_id || r.name || r.id} size="small" pagination={false} />
              </Card>
            ),
          },
          {
            key: 'material',
            label: '物流全景',
            children: (
              <Card size="small" title={<><SwapOutlined /> 物流链路（进→存→产→出）</>}>
                {flowStages.length > 0 ? (
                  <Row gutter={16}>
                    {flowStages.map((s: any, i: number) => (
                      <Col span={6} key={i}>
                        <Card size="small" title={s.name || s.stage} style={{ textAlign: 'center' }}>
                          <Statistic value={s.count || s.quantity || 0} suffix="件" />
                          <Text type="secondary">{s.rows != null ? `${s.rows} 条明细` : ''}</Text>
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
                {countdown?.summary && (
                  <Row gutter={16}>
                    <Col span={6}><Card size="small"><Statistic title="活动订单" value={countdown.summary.total_active_orders ?? 0} /></Card></Col>
                    <Col span={6}><Card size="small"><Statistic title="红灯" value={countdown.summary.red ?? 0} valueStyle={{ color: '#f5222d' }} /></Card></Col>
                    <Col span={6}><Card size="small"><Statistic title="黄灯" value={countdown.summary.yellow ?? 0} valueStyle={{ color: '#faad14' }} /></Card></Col>
                    <Col span={6}><Card size="small"><Statistic title="准时率" value={countdown.summary.on_time_rate ?? 0} suffix="%" valueStyle={{ color: '#52c41a' }} /></Card></Col>
                  </Row>
                )}
                <Card size="small" title={<><ClockCircleOutlined /> 订单交期倒计时</>}>
                  <Table dataSource={countdownItems} columns={countdownColumns} rowKey={(r) => r.order_code || r.order_no || r.id} size="small" pagination={false} />
                </Card>
                <Card size="small" title={<><WarningOutlined /> 超期预警</>}>
                  {overdueItems.length > 0 ? (
                    <Table dataSource={overdueItems} columns={overdueColumns} rowKey={(r) => r._rk || r.ref_no} size="small" pagination={{ pageSize: 10 }} />
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
