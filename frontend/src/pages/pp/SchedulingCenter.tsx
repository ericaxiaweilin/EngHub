import React, { useState, useEffect } from 'react'
import { Tabs, Card, Button, Select, Space, Tag, message, Alert, Row, Col, Statistic, Table, Typography, Descriptions, Divider } from 'antd'
import { FieldTimeOutlined, BarChartOutlined, ThunderboltOutlined, WarningOutlined, SwapOutlined, ReloadOutlined } from '@ant-design/icons'
import ScheduleGantt from './ScheduleGantt'
import CapacityLoad from './CapacityLoad'
import { apsApi } from '../../services/aps'
import { getActiveFactoryId } from '../../utils/factory'

const { Text } = Typography
const FACTORY = getActiveFactoryId()

const algorithms = [
  { value: 'EDD', label: 'EDD 最早交期优先' },
  { value: 'SPT', label: 'SPT 最短加工优先' },
  { value: 'CR', label: 'CR 关键比率优先' },
  { value: 'PRIORITY', label: '优先级优先' },
]

const algorithmNames: Record<string, string> = Object.fromEntries(
  algorithms.map(item => [item.value, item.label]),
)

const formatDateTime = (value?: string) => {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

/** Phase 2: APS 排程增强面板 */
const ApsEnhanced: React.FC = () => {
  const [algorithm, setAlgorithm] = useState('EDD')
  const [horizon, setHorizon] = useState(7)
  const [scheduling, setScheduling] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [conflicts, setConflicts] = useState<any[]>([])
  const [conflictTotal, setConflictTotal] = useState(0)
  const [conflictsChecked, setConflictsChecked] = useState(false)
  const [conflictsCheckedAt, setConflictsCheckedAt] = useState<string>()
  const [checkingConflicts, setCheckingConflicts] = useState(false)

  const handleSchedule = async () => {
    setScheduling(true)
    try {
      const res: any = await apsApi.scheduleWithAlgorithm({ factory_id: FACTORY, algorithm, horizon_days: horizon })
      setResult(res)
      message.success(`排程完成：${res.total_tasks || 0} 个任务，${res.unscheduled_count || 0} 个未排工单`)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '排程失败')
    } finally { setScheduling(false) }
  }

  const handleReschedule = async () => {
    setScheduling(true)
    try {
      const res: any = await apsApi.rescheduleV2({ factory_id: FACTORY, algorithm })
      setResult(res)
      message.success(res.note || '重排完成')
    } catch (e: any) {
      const detail = e?.response?.data?.detail || '重排失败'
      if (String(detail).includes('插单审批')) {
        message.warning('插单需先走审批流：请在 PMC 工作台 → 插单评估 生成审批单，审批通过后方可重排')
      } else {
        message.error(detail)
      }
    } finally { setScheduling(false) }
  }

  const handleCheckConflicts = async () => {
    setCheckingConflicts(true)
    try {
      const res: any = await apsApi.detectConflicts({ factory_id: FACTORY })
      setConflicts(res.conflicts || [])
      setConflictTotal(Number(res.total ?? res.conflicts?.length ?? 0))
      setConflictsCheckedAt(res.checked_at)
      setConflictsChecked(true)
    } catch {
      setConflictsChecked(false)
    } finally { setCheckingConflicts(false) }
  }

  useEffect(() => { handleCheckConflicts() }, [])

  const conflictColumns = [
    { title: '类型', dataIndex: 'type', key: 'type', render: (v: string) => (
      <Tag color={v === 'delivery_risk' ? 'red' : 'orange'}>{v === 'delivery_risk' ? '交期风险' : '无BOM'}</Tag>
    )},
    { title: '工单', dataIndex: 'work_order', key: 'wo' },
    { title: '详情', key: 'detail', render: (_: any, r: any) => (
      r.delay_hours ? <Text type="danger">延期 {r.delay_hours}h</Text> : <Text>{r.message}</Text>
    )},
  ]

  const summary = result?.input_summary || {}
  const metrics = result?.metrics || {}
  const diagnostics = result?.diagnostics || {}
  const issueRows = [
    ...(diagnostics.unscheduled || []).map((item: any) => ({
      ...item,
      issue_type: '未排工单',
      reason: (item.reasons || []).join('；'),
    })),
    ...(diagnostics.constraint_violations || []).map((item: any) => ({
      ...item,
      issue_type: '约束违规',
    })),
  ]

  const issueColumns = [
    { title: '类型', dataIndex: 'issue_type', key: 'issue_type', render: (value: string) => <Tag color={value === '未排工单' ? 'red' : 'orange'}>{value}</Tag> },
    { title: '工单', dataIndex: 'work_order_code', key: 'work_order_code', render: (value: string, row: any) => value || row.order_id || '-' },
    { title: '产品', dataIndex: 'product_id', key: 'product_id', render: (value: string) => value || '-' },
    { title: '原因', dataIndex: 'reason', key: 'reason', render: (value: string) => <Text type="danger">{value || '未满足排程约束'}</Text> },
  ]

  const stationColumns = [
    { title: '工位/资源', dataIndex: 'station_id', key: 'station_id' },
    { title: '任务数', dataIndex: 'task_count', key: 'task_count' },
    { title: '涉及工单', dataIndex: 'order_count', key: 'order_count' },
    { title: '占用工时', dataIndex: 'load_hours', key: 'load_hours', render: (value: number) => `${value || 0} h` },
    { title: '排程时间', key: 'time', render: (_: any, row: any) => `${formatDateTime(row.first_start)} - ${formatDateTime(row.last_end)}` },
  ]

  return (
    <div style={{ padding: 16 }}>
      {/* 排程控制 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select value={algorithm} onChange={setAlgorithm} options={algorithms} style={{ width: 200 }} />
          <Select value={horizon} onChange={setHorizon} options={[
            { value: 3, label: '3天' }, { value: 7, label: '7天' }, { value: 14, label: '14天' },
          ]} style={{ width: 80 }} />
          <Button type="primary" icon={<ThunderboltOutlined />} loading={scheduling} onClick={handleSchedule}>
            执行排程
          </Button>
          <Button icon={<SwapOutlined />} loading={scheduling} onClick={handleReschedule}>
            插单重排
          </Button>
          <Button icon={<WarningOutlined />} loading={checkingConflicts} onClick={handleCheckConflicts}>
            冲突检测
          </Button>
        </Space>
        <Divider style={{ margin: '12px 0' }} />
        <Text type="secondary">
          本次排程将读取当前工厂的可排工单、工艺路线、资源日历和设备可用性；执行后会保留草稿方案，确认/下达仍需人工操作。
        </Text>
      </Card>

      {/* 冲突预警 */}
      {conflictsChecked ? (
        <Alert
          type={conflictTotal > 0 ? 'warning' : 'success'}
          showIcon
          message={conflictTotal > 0 ? `当前规则检测到 ${conflictTotal} 个风险/冲突` : '当前规则未检测到风险/冲突'}
          style={{ marginBottom: 16 }}
          description={<Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Text type="secondary">检测时间：{formatDateTime(conflictsCheckedAt)}；检测范围：当前工厂已下达/执行中的工单。</Text>
            {conflicts.length > 0 && <Table columns={conflictColumns} dataSource={conflicts} rowKey={(_, i) => String(i)} size="small" pagination={false} style={{ marginTop: 8 }} />}
          </Space>}
        />
      ) : <Alert type="info" showIcon message="尚未完成冲突检测" description="点击“冲突检测”后，系统会把当前已发现的交期风险列在这里。" style={{ marginBottom: 16 }} />}

      {/* 排程结果 */}
      {result && (
        <Card title={<Space><ThunderboltOutlined />排程结果与依据</Space>} size="small">
          <Alert
            type={result.success ? 'success' : 'warning'}
            showIcon
            message={result.message || (result.success ? '排程成功' : '排程未完全成功')}
            description={<Space direction="vertical" size={2}>
              <Text>规则：{result.algorithm_name || algorithmNames[result.algorithm] || result.algorithm || 'EDD 最早交期优先'}</Text>
              <Text type="secondary">{result.rule_explanation || '系统按工单优先级、交期和资源约束生成方案。'}</Text>
            </Space>}
            style={{ marginBottom: 16 }}
          />

          <Descriptions title="本次排程输入与去向" bordered size="small" column={{ xs: 1, sm: 2, md: 3 }}>
            <Descriptions.Item label="输入工单">{summary.total_orders ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="有工艺路线">{summary.routable_orders ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="跳过工单">{summary.skipped_orders ?? 0}</Descriptions.Item>
            <Descriptions.Item label="已排工单">{summary.scheduled_orders ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="未排工单"><Text type={Number(summary.unscheduled_orders) > 0 ? 'danger' : undefined}>{summary.unscheduled_orders ?? 0}</Text></Descriptions.Item>
            <Descriptions.Item label="计划窗口">{formatDateTime(result.horizon_start)} - {formatDateTime(result.horizon_end)}（{result.horizon_days ?? horizon}天）</Descriptions.Item>
          </Descriptions>

          <Row gutter={[16, 16]} style={{ margin: '16px 0' }}>
            <Col xs={12} sm={8} md={4}><Statistic title="任务数" value={result.total_tasks ?? 0} /></Col>
            <Col xs={12} sm={8} md={4}><Statistic title="未排工单" value={result.unscheduled_count ?? 0} valueStyle={{ color: result.unscheduled_count > 0 ? '#f5222d' : '#52c41a' }} /></Col>
            <Col xs={12} sm={8} md={4}><Statistic title="约束违规" value={result.constraint_violation_count ?? result.conflict_count ?? 0} valueStyle={{ color: (result.constraint_violation_count ?? result.conflict_count ?? 0) > 0 ? '#f5222d' : '#52c41a' }} /></Col>
            <Col xs={12} sm={8} md={4}><Statistic title="准时率" value={metrics.on_time_delivery_rate ?? 0} suffix="%" /></Col>
            <Col xs={12} sm={8} md={4}><Statistic title="平均利用率" value={metrics.avg_resource_utilization ?? 0} suffix="%" /></Col>
            <Col xs={12} sm={8} md={4}><Statistic title="换型时间" value={metrics.total_setup_time ?? 0} suffix="分钟" /></Col>
          </Row>

          {issueRows.length > 0 && <Card type="inner" title="异常工单与约束原因" size="small" style={{ marginBottom: 16 }}>
            <Table columns={issueColumns} dataSource={issueRows} rowKey={(row: any, index) => `${row.issue_type}-${row.order_id || index}`} size="small" pagination={{ pageSize: 5, showSizeChanger: false }} />
          </Card>}

          {(result.station_loads || []).length > 0 && <Card type="inner" title="工位负荷明细" size="small" style={{ marginBottom: 16 }}>
            <Table columns={stationColumns} dataSource={result.station_loads} rowKey="station_id" size="small" pagination={{ pageSize: 5, showSizeChanger: false }} />
          </Card>}

          <Space wrap>
            <Tag color="blue">方案号：{result.schedule_code || '-'}</Tag>
            <Tag>状态：草稿，待确认</Tag>
            <Tag>算法目标：{result.optimize_for || 'delivery'}</Tag>
            <Button size="small" icon={<ReloadOutlined />} onClick={handleCheckConflicts} loading={checkingConflicts}>重新检测风险</Button>
          </Space>
        </Card>
      )}
    </div>
  )
}

const SchedulingCenter: React.FC = () => {
  return (
    <Tabs
      defaultActiveKey="gantt"
      size="small"
      items={[
        {
          key: 'gantt',
          label: <span><FieldTimeOutlined /> 排程甘特图</span>,
          children: <ScheduleGantt />,
        },
        {
          key: 'aps',
          label: <span><ThunderboltOutlined /> APS 智能排程</span>,
          children: <ApsEnhanced />,
        },
        {
          key: 'capacity',
          label: <span><BarChartOutlined /> 产能负荷</span>,
          children: <CapacityLoad />,
        },
      ]}
    />
  )
}

export default SchedulingCenter
