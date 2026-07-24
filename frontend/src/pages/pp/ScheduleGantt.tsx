import React, { useEffect, useState, useMemo, useCallback } from 'react'
import {
  Card, Button, Select, Space, Tag, message, Drawer, Descriptions,
  Row, Col, Statistic, Empty, Spin, Tooltip, Modal, InputNumber,
} from 'antd'
import {
  ThunderboltOutlined, CheckCircleOutlined, SendOutlined,
  ReloadOutlined, LockOutlined, UnlockOutlined, FieldTimeOutlined,
  ScheduleOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { apsApi, ApsSchedule, GanttData, ApsTask } from '../../services/aps'

const FACTORY = 'F001'

const statusColorMap: Record<string, string> = {
  draft: 'default',
  confirmed: 'processing',
  released: 'success',
  archived: 'warning',
}
const statusTextMap: Record<string, string> = {
  draft: '草稿',
  confirmed: '已确认',
  released: '已下达',
  archived: '已归档',
}

// 优先级颜色
const priorityColors: string[] = [
  '#1890ff', '#52c41a', '#faad14', '#f5222d', '#722ed1',
  '#13c2c2', '#eb2f96', '#fa8c16', '#2f54eb', '#a0d911',
]

const ScheduleGantt: React.FC = () => {
  const [schedules, setSchedules] = useState<ApsSchedule[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [gantt, setGantt] = useState<GanttData | null>(null)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [taskDrawer, setTaskDrawer] = useState<ApsTask | null>(null)
  const [genModal, setGenModal] = useState(false)
  const [horizonDays, setHorizonDays] = useState(7)
  const [mode, setMode] = useState('hybrid')

  // 加载方案列表
  const loadSchedules = useCallback(async () => {
    try {
      const res: any = await apsApi.listSchedules({ factory_id: FACTORY, page_size: 50 })
      setSchedules(res.items || [])
      if (res.items?.length && !selectedId) {
        setSelectedId(res.items[0].id)
      }
    } catch { /* ignore */ }
  }, [selectedId])

  // 加载甘特图
  const loadGantt = useCallback(async (id: string) => {
    setLoading(true)
    try {
      const res: any = await apsApi.getGantt(id)
      setGantt(res)
    } catch {
      setGantt(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadSchedules() }, [loadSchedules])
  useEffect(() => { if (selectedId) loadGantt(selectedId) }, [selectedId, loadGantt])

  // 生成排程
  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const res: any = await apsApi.generate({ factory_id: FACTORY, mode, horizon_days: horizonDays })
      message.success(`排程完成：${res.total_tasks} 个任务`)
      setGenModal(false)
      await loadSchedules()
      if (res.schedule_id) setSelectedId(res.schedule_id)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '排程失败')
    } finally {
      setGenerating(false)
    }
  }

  // 确认
  const handleConfirm = async () => {
    if (!selectedId) return
    try {
      const res: any = await apsApi.confirmSchedule(selectedId)
      message.success(res.message || '已确认')
      loadSchedules()
      loadGantt(selectedId)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '确认失败')
    }
  }

  // 下达
  const handleRelease = async () => {
    if (!selectedId) return
    try {
      const res: any = await apsApi.releaseSchedule(selectedId)
      message.success(res.message || '已下达')
      loadSchedules()
      loadGantt(selectedId)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '下达失败')
    }
  }

  // 重排
  const handleReschedule = async () => {
    setGenerating(true)
    try {
      const res: any = await apsApi.reschedule({ factory_id: FACTORY })
      message.success(`重排完成：${res.total_tasks} 个任务`)
      await loadSchedules()
      if (res.schedule_id) setSelectedId(res.schedule_id)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '重排失败')
    } finally {
      setGenerating(false)
    }
  }

  // 甘特图时间计算
  const ganttMeta = useMemo(() => {
    if (!gantt) return null
    const start = dayjs(gantt.horizon_start)
    const end = dayjs(gantt.horizon_end)
    const totalHours = end.diff(start, 'hour', true)
    const stations = Object.keys(gantt.resources).sort()
    return { start, end, totalHours, stations }
  }, [gantt])

  const currentSchedule = schedules.find(s => s.id === selectedId)

  // 时间刻度（每12小时一格）
  const timeTicks = useMemo(() => {
    if (!ganttMeta) return []
    const ticks: { label: string; offset: number }[] = []
    let cur = ganttMeta.start.startOf('day').add(8, 'hour')
    while (cur.isBefore(ganttMeta.end)) {
      const offset = cur.diff(ganttMeta.start, 'hour', true) / ganttMeta.totalHours * 100
      if (offset >= 0 && offset <= 100) {
        ticks.push({ label: cur.format('MM/DD HH:mm'), offset })
      }
      cur = cur.add(12, 'hour')
    }
    return ticks
  }, [ganttMeta])

  // 任务色块位置
  const getTaskStyle = (task: ApsTask, idx: number) => {
    if (!ganttMeta) return {}
    const tStart = dayjs(task.planned_start)
    const tEnd = dayjs(task.planned_end)
    const left = Math.max(0, tStart.diff(ganttMeta.start, 'hour', true) / ganttMeta.totalHours * 100)
    const width = Math.max(0.5, tEnd.diff(tStart, 'hour', true) / ganttMeta.totalHours * 100)
    return {
      left: `${left}%`,
      width: `${width}%`,
      backgroundColor: priorityColors[idx % priorityColors.length],
    }
  }

  return (
    <div style={{ padding: '0' }}>
      {/* 操作栏 */}
      <Card size="small" style={{ marginBottom: 12 }}>
        <Row justify="space-between" align="middle" gutter={[12, 8]}>
          <Col>
            <Space wrap>
              <ScheduleOutlined style={{ fontSize: 18, color: '#1890ff' }} />
              <Select
                value={selectedId}
                onChange={setSelectedId}
                style={{ width: 260 }}
                placeholder="选择排程方案"
                options={schedules.map(s => ({
                  value: s.id,
                  label: `${s.schedule_code} (${statusTextMap[s.status] || s.status})`,
                }))}
              />
              {currentSchedule && (
                <Tag color={statusColorMap[currentSchedule.status]}>
                  {statusTextMap[currentSchedule.status] || currentSchedule.status}
                </Tag>
              )}
            </Space>
          </Col>
          <Col>
            <Space wrap>
              <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => setGenModal(true)}>
                生成排程
              </Button>
              <Button icon={<CheckCircleOutlined />} onClick={handleConfirm}
                disabled={!currentSchedule || currentSchedule.status !== 'draft'}>
                确认
              </Button>
              <Button icon={<SendOutlined />} onClick={handleRelease}
                disabled={!currentSchedule || currentSchedule.status !== 'confirmed'}>
                下达
              </Button>
              <Button icon={<ReloadOutlined />} onClick={handleReschedule} loading={generating}>
                插单重排
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {/* KPI 卡片 */}
      {currentSchedule && (
        <Row gutter={12} style={{ marginBottom: 12 }}>
          <Col span={4}>
            <Card size="small"><Statistic title="准时交付率" value={currentSchedule.on_time_rate ?? 0} suffix="%" precision={1} /></Card>
          </Col>
          <Col span={4}>
            <Card size="small"><Statistic title="平均利用率" value={currentSchedule.avg_utilization ?? 0} suffix="%" precision={1} /></Card>
          </Col>
          <Col span={4}>
            <Card size="small"><Statistic title="换型时间" value={currentSchedule.total_setup_minutes ?? 0} suffix="min" precision={0} /></Card>
          </Col>
          <Col span={4}>
            <Card size="small"><Statistic title="平均周期" value={currentSchedule.avg_cycle_hours ?? 0} suffix="h" precision={1} /></Card>
          </Col>
          <Col span={4}>
            <Card size="small"><Statistic title="排程任务" value={currentSchedule.total_tasks} /></Card>
          </Col>
          <Col span={4}>
            <Card size="small"><Statistic title="未排入" value={currentSchedule.unscheduled_count} valueStyle={{ color: currentSchedule.unscheduled_count > 0 ? '#f5222d' : undefined }} /></Card>
          </Col>
        </Row>
      )}

      {/* 甘特图 */}
      <Card
        size="small"
        title={<Space><FieldTimeOutlined />排程甘特图</Space>}
        extra={gantt && <Tag>{gantt.total_tasks} 个任务 · {ganttMeta?.stations.length} 个工位</Tag>}
      >
        <Spin spinning={loading}>
          {!gantt || !ganttMeta || ganttMeta.stations.length === 0 ? (
            <Empty description="暂无排程数据，请先生成排程方案" />
          ) : (
            <div style={{ overflowX: 'auto' }}>
              {/* 时间轴 */}
              <div style={{ position: 'relative', height: 28, marginLeft: 120, marginBottom: 4, borderBottom: '1px solid #f0f0f0' }}>
                {timeTicks.map((tick, i) => (
                  <span key={i} style={{
                    position: 'absolute', left: `${tick.offset}%`, fontSize: 10,
                    color: '#999', transform: 'translateX(-50%)', whiteSpace: 'nowrap',
                  }}>
                    {tick.label}
                  </span>
                ))}
              </div>

              {/* 资源行 */}
              {ganttMeta.stations.map((station, sIdx) => (
                <div key={station} style={{
                  display: 'flex', alignItems: 'center', height: 40,
                  borderBottom: '1px solid #fafafa',
                  backgroundColor: sIdx % 2 === 0 ? '#fff' : '#fafafa',
                }}>
                  {/* 工位标签 */}
                  <div style={{
                    width: 120, flexShrink: 0, fontSize: 12, fontWeight: 500,
                    paddingLeft: 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    <Tooltip title={station}>{station}</Tooltip>
                  </div>
                  {/* 任务条 */}
                  <div style={{ flex: 1, position: 'relative', height: 28 }}>
                    {(gantt.resources[station] || []).map((task, tIdx) => (
                      <Tooltip
                        key={task.id}
                        title={`${task.order_code || task.product_code} | OP${task.operation_seq} | ${dayjs(task.planned_start).format('HH:mm')}-${dayjs(task.planned_end).format('HH:mm')}`}
                      >
                        <div
                          onClick={() => setTaskDrawer(task)}
                          style={{
                            position: 'absolute',
                            top: 4,
                            height: 20,
                            borderRadius: 3,
                            cursor: 'pointer',
                            opacity: 0.85,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: 9,
                            color: '#fff',
                            overflow: 'hidden',
                            whiteSpace: 'nowrap',
                            border: task.is_locked ? '2px solid #333' : '1px solid rgba(255,255,255,0.3)',
                            ...getTaskStyle(task, sIdx * 3 + tIdx),
                          }}
                        >
                          {task.order_code?.slice(-4) || task.product_code?.slice(-4)}
                          {task.is_locked && <LockOutlined style={{ marginLeft: 2, fontSize: 8 }} />}
                        </div>
                      </Tooltip>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Spin>
      </Card>

      {/* 生成排程 Modal */}
      <Modal
        title="生成排程方案"
        open={genModal}
        onOk={handleGenerate}
        onCancel={() => setGenModal(false)}
        confirmLoading={generating}
        okText="开始排程"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>排程模式</div>
            <Select value={mode} onChange={setMode} style={{ width: '100%' }} options={[
              { value: 'forward', label: '正排（从当前时间向后）' },
              { value: 'backward', label: '倒排（从交期向前）' },
              { value: 'hybrid', label: '混合（推荐）' },
            ]} />
          </div>
          <div>
            <div style={{ marginBottom: 4, fontWeight: 500 }}>排程天数</div>
            <InputNumber value={horizonDays} onChange={v => setHorizonDays(v || 7)} min={1} max={30} style={{ width: '100%' }} addonAfter="天" />
          </div>
        </Space>
      </Modal>

      {/* 任务详情 Drawer */}
      <Drawer
        title="排程任务详情"
        open={!!taskDrawer}
        onClose={() => setTaskDrawer(null)}
        width={380}
      >
        {taskDrawer && (
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="工单编码">{taskDrawer.order_code || '-'}</Descriptions.Item>
            <Descriptions.Item label="产品">{taskDrawer.product_code || '-'}</Descriptions.Item>
            <Descriptions.Item label="工序">{taskDrawer.operation_name || `OP${taskDrawer.operation_seq}`}</Descriptions.Item>
            <Descriptions.Item label="工位">{taskDrawer.station_id}</Descriptions.Item>
            <Descriptions.Item label="计划开始">{dayjs(taskDrawer.planned_start).format('YYYY-MM-DD HH:mm')}</Descriptions.Item>
            <Descriptions.Item label="计划结束">{dayjs(taskDrawer.planned_end).format('YYYY-MM-DD HH:mm')}</Descriptions.Item>
            <Descriptions.Item label="换型时间">{((taskDrawer.setup_seconds || 0) / 60).toFixed(1)} 分钟</Descriptions.Item>
            <Descriptions.Item label="加工时间">{((taskDrawer.run_seconds || 0) / 60).toFixed(1)} 分钟</Descriptions.Item>
            <Descriptions.Item label="数量">{taskDrawer.quantity || '-'}</Descriptions.Item>
            <Descriptions.Item label="优先级">
              <Tag color={taskDrawer.priority >= 4 ? 'red' : taskDrawer.priority >= 3 ? 'orange' : 'blue'}>
                P{taskDrawer.priority}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag>{taskDrawer.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="锁定">
              {taskDrawer.is_locked ? <Tag icon={<LockOutlined />} color="error">已锁定</Tag> : <Tag icon={<UnlockOutlined />} color="success">可调整</Tag>}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  )
}

export default ScheduleGantt
