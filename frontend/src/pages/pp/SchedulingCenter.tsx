import React, { useState, useEffect } from 'react'
import { Tabs, Card, Button, Select, Space, Tag, message, Alert, Row, Col, Statistic, Table, Typography } from 'antd'
import { FieldTimeOutlined, BarChartOutlined, ThunderboltOutlined, WarningOutlined, SwapOutlined } from '@ant-design/icons'
import ScheduleGantt from './ScheduleGantt'
import CapacityLoad from './CapacityLoad'
import { apsApi } from '../../services/aps'

const { Text } = Typography
const FACTORY = localStorage.getItem('active_factory_id') || 'FAC_MECH_001'

const algorithms = [
  { value: 'EDD', label: 'EDD 最早交期优先' },
  { value: 'SPT', label: 'SPT 最短加工优先' },
  { value: 'CR', label: 'CR 关键比率优先' },
  { value: 'PRIORITY', label: '优先级优先' },
]

/** Phase 2: APS 排程增强面板 */
const ApsEnhanced: React.FC = () => {
  const [algorithm, setAlgorithm] = useState('EDD')
  const [horizon, setHorizon] = useState(7)
  const [scheduling, setScheduling] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [conflicts, setConflicts] = useState<any[]>([])
  const [checkingConflicts, setCheckingConflicts] = useState(false)

  const handleSchedule = async () => {
    setScheduling(true)
    try {
      const res: any = await apsApi.scheduleWithAlgorithm({ factory_id: FACTORY, algorithm, horizon_days: horizon })
      setResult(res)
      message.success(`排程完成：${res.total_tasks} 个任务，${res.conflict_count} 个冲突`)
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
      message.error(e?.response?.data?.detail || '重排失败')
    } finally { setScheduling(false) }
  }

  const handleCheckConflicts = async () => {
    setCheckingConflicts(true)
    try {
      const res: any = await apsApi.detectConflicts({ factory_id: FACTORY })
      setConflicts(res.conflicts || [])
    } catch { /* ignore */ } finally { setCheckingConflicts(false) }
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
      </Card>

      {/* 冲突预警 */}
      {conflicts.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message={`发现 ${conflicts.length} 个排程冲突`}
          style={{ marginBottom: 16 }}
          description={
            <Table columns={conflictColumns} dataSource={conflicts} rowKey={(_, i) => String(i)}
              size="small" pagination={false} style={{ marginTop: 8 }} />
          }
        />
      )}

      {/* 排程结果 */}
      {result && (
        <Card title="排程结果" size="small">
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col span={6}><Statistic title="任务数" value={result.total_tasks} /></Col>
            <Col span={6}><Statistic title="冲突数" value={result.conflict_count} valueStyle={{ color: result.conflict_count > 0 ? '#f5222d' : '#52c41a' }} /></Col>
            <Col span={6}><Statistic title="算法" value={result.algorithm_name || result.algorithm} /></Col>
            <Col span={6}><Statistic title="排程范围" value={result.horizon} /></Col>
          </Row>
          {result.station_utilization && (
            <>
              <Text strong>工位利用率：</Text>
              <Space style={{ marginTop: 8 }}>
                {Object.entries(result.station_utilization).map(([sid, util]) => (
                  <Tag key={sid} color={Number(util) > 80 ? 'red' : Number(util) > 50 ? 'orange' : 'green'}>
                    {sid}: {String(util)}%
                  </Tag>
                ))}
              </Space>
            </>
          )}
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
