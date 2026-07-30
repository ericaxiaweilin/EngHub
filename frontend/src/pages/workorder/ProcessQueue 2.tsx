/**
 * 工序队列页面（016）
 * - 顶部：工序组 Tab 切换（下料/慢走丝/电火花/磨削/装配...），默认选中 user.work_center
 * - 列表：本工序组的工序工单（按优先级+交期排序）
 * - 操作：开工/完工（按权限显示）
 * - 统计卡片：待加工数/进行中数/已释放数/完工数
 */
import React, { useEffect, useState, useCallback } from 'react'
import { Table, Tag, Space, Card, Button, Tabs, Statistic, Row, Col, message, Tooltip } from 'antd'
import {
  PlayCircleOutlined, CheckCircleOutlined, ReloadOutlined,
  ThunderboltOutlined, ClockCircleOutlined, CheckSquareOutlined, HourglassOutlined,
} from '@ant-design/icons'
import { getProcessQueue, startWorkOrder, completeWorkOrder, WorkOrder } from '../../services/mes'
import { getStoredUser, hasPermission } from '../../services/auth'

// 行业通用工序代码
const PROCESS_TABS = [
  { key: '', label: '全部' },
  { key: 'CUT', label: '下料' },
  { key: 'MACH', label: '机加' },
  { key: 'GRD', label: '研磨' },
  { key: 'WCUT', label: '慢走丝' },
  { key: 'EDM', label: '电火花' },
  { key: 'HT', label: '热处理' },
  { key: 'WELD', label: '焊接' },
  { key: 'FIN', label: '表面处理' },
  { key: 'ASSY', label: '装配' },
  { key: 'QC', label: '检验' },
  { key: 'PKG', label: '包装' },
]

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '待释放' },
  released: { color: 'blue', text: '已释放' },
  in_progress: { color: 'processing', text: '加工中' },
  completed: { color: 'success', text: '已完工' },
  on_hold: { color: 'warning', text: '暂停' },
}

const PRIORITY_MAP: Record<string, { color: string; text: string }> = {
  low: { color: 'default', text: '低' },
  medium: { color: 'blue', text: '中' },
  high: { color: 'orange', text: '高' },
  urgent: { color: 'red', text: '急' },
}

const ProcessQueue: React.FC = () => {
  const user = getStoredUser()
  const factoryId = localStorage.getItem('active_factory_id') || user?.factory_id || ''
  const [activeTab, setActiveTab] = useState((user as any)?.work_center || '')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<WorkOrder[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<any>({})
  const [page, setPage] = useState(1)

  const fetchData = useCallback(async () => {
    if (!factoryId) return
    setLoading(true)
    try {
      const res = await getProcessQueue(factoryId, activeTab || undefined, undefined, page)
      setData(res.items || [])
      setTotal(res.total || 0)
      setStats(res.stats || {})
    } catch (e: any) {
      message.error(e?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [factoryId, activeTab, page])

  useEffect(() => { fetchData() }, [fetchData])

  const handleStart = async (record: WorkOrder) => {
    try {
      await startWorkOrder(record.id)
      message.success('已开工')
      fetchData()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '操作失败')
    }
  }

  const handleComplete = async (record: WorkOrder) => {
    try {
      await completeWorkOrder(record.id, { completed_qty: record.planned_qty, good_qty: record.planned_qty, defect_qty: 0 })
      message.success('已完工，后道工序已自动释放')
      fetchData()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || e?.message || '操作失败')
    }
  }

  const canStart = hasPermission('work_order', 'start')
  const canComplete = hasPermission('work_order', 'complete')

  const columns = [
    {
      title: '工序工单号', dataIndex: 'work_order_code', key: 'code', width: 220,
      render: (v: string) => <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{v}</span>,
    },
    {
      title: '工序', dataIndex: 'process_code', key: 'process', width: 80,
      render: (v: string) => <Tag>{PROCESS_TABS.find(t => t.key === v)?.label || v}</Tag>,
    },
    { title: '数量', dataIndex: 'planned_qty', key: 'qty', width: 70, align: 'center' as const },
    {
      title: '优先级', dataIndex: 'priority', key: 'priority', width: 70, align: 'center' as const,
      render: (v: string) => {
        const p = PRIORITY_MAP[v] || PRIORITY_MAP.medium
        return <Tag color={p.color}>{p.text}</Tag>
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => {
        const s = STATUS_MAP[v] || { color: 'default', text: v }
        return <Tag color={s.color}>{s.text}</Tag>
      },
    },
    {
      title: '交期', dataIndex: 'planned_due', key: 'due', width: 110,
      render: (v: string) => v ? v.slice(0, 10) : '-',
    },
    // ========== #2 工序依赖锁止 - 新增前序步骤状态列 ==========
    {
      title: '前序状态', key: 'prereq_status', width: 140,
      render: (_: any, record: WorkOrder) => {
        if (!record.current_routing_step || record.current_routing_step <= 1) return <Tag color="blue">第1步（无前置）</Tag>
        // 简化：实际应从后端API获取前序状态，这里展示占位提示
        return <Tag color="warning">需检查步骤{record.current_routing_step - 1}</Tag>
      }
    },
    {
      title: '备注', dataIndex: 'remark', key: 'remark', ellipsis: true },
    {
      title: '操作', key: 'action', width: 180, fixed: 'right' as const,
      render: (_: any, record: WorkOrder) => {
        let startButton = null
        let lockTip = null
        
        if (record.status === 'released' && canStart) {
          // 简易检查：若 current_routing_step > 1 则默认可能存在锁止（实际应由后端API返回can_start布尔值）
          const needsCheck = record.current_routing_step && record.current_routing_step > 1
          if (needsCheck) {
            lockTip = <Tooltip title="⚠ 前序步骤尚未开始：请等待步骤 N-1 开工后继续">🔒 工序锁止</Tooltip>
          }
          startButton = (
            <Tooltip title="开工">
              <Button type="primary" size="small" icon={<PlayCircleOutlined />} onClick={() => handleStart(record)} disabled={!!lockTip} />
            </Tooltip>
          )
        }
        
        return (
          <Space direction="vertical" align="center">
            {startButton}
            {lockTip}
            {record.status === 'in_progress' && canComplete && (
              <Tooltip title="完工">
                <Button type="primary" size="small" icon={<CheckCircleOutlined />} style={{ background: '#52c41a', borderColor: '#52c41a' }} onClick={() => handleComplete(record)} />
              </Tooltip>
            )}
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
          <Card size="small"><Statistic title="待释放" value={stats.pending || 0} prefix={<HourglassOutlined />} valueStyle={{ color: '#8c8c8c' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="已释放" value={stats.released || 0} prefix={<ClockCircleOutlined />} valueStyle={{ color: '#1890ff' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="加工中" value={stats.in_progress || 0} prefix={<ThunderboltOutlined />} valueStyle={{ color: '#fa8c16' }} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="已完工" value={stats.completed || 0} prefix={<CheckSquareOutlined />} valueStyle={{ color: '#52c41a' }} /></Card>
        </Col>
      </Row>

      {/* 工序组 Tab + 列表 */}
      <Card
        size="small"
        title={
          <Space>
            <span>工序队列</span>
            {activeTab && <Tag color="blue">{PROCESS_TABS.find(t => t.key === activeTab)?.label || activeTab}</Tag>}
          </Space>
        }
        extra={<Button icon={<ReloadOutlined />} size="small" onClick={fetchData}>刷新</Button>}
      >
        <Tabs
          activeKey={activeTab}
          onChange={(k) => { setActiveTab(k); setPage(1) }}
          size="small"
          items={PROCESS_TABS.map(t => ({ key: t.key, label: t.label }))}
          style={{ marginBottom: 12 }}
        />
        <Table
          rowKey="id"
          columns={columns}
          dataSource={data}
          loading={loading}
          size="small"
          scroll={{ x: 900 }}
          pagination={{
            current: page,
            total,
            pageSize: 50,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p) => setPage(p),
          }}
        />
      </Card>
    </div>
  )
}

export default ProcessQueue
