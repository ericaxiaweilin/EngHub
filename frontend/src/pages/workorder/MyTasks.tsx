/**
 * 我的任务页面（016）
 * - 极简列表：只展示 assigned_to=me 的工序工单
 * - 大按钮操作：开工/完工
 * - 适合操作工在车间平板使用
 */
import React, { useEffect, useState, useCallback } from 'react'
import { List, Tag, Button, Card, Space, message, Empty, Badge, Typography } from 'antd'
import {
  PlayCircleOutlined, CheckCircleOutlined, ReloadOutlined,
  ThunderboltOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import { getMyTasks, startWorkOrder, completeWorkOrder, WorkOrder } from '../../services/mes'
import { getStoredUser, hasPermission } from '../../services/auth'

const { Title, Text } = Typography

const PROCESS_NAME: Record<string, string> = {
  CUT: '下料', MACH: '机加', INJ: '注塑', EDM: '电火花', WCUT: '慢走丝',
  WELD: '焊接', PAINT: '涂装', ASSY: '装配', PKG: '包装', QC: '检验',
  HT: '热处理', FIN: '表面处理', GRD: '研磨',
}

const STATUS_CONFIG: Record<string, { color: string; text: string; badge: 'default' | 'processing' | 'success' | 'warning' | 'error' }> = {
  pending: { color: '#8c8c8c', text: '待释放', badge: 'default' },
  released: { color: '#1890ff', text: '已释放 · 可开工', badge: 'processing' },
  in_progress: { color: '#fa8c16', text: '加工中', badge: 'warning' },
  completed: { color: '#52c41a', text: '已完工', badge: 'success' },
  on_hold: { color: '#faad14', text: '暂停', badge: 'warning' },
}

const MyTasks: React.FC = () => {
  const user = getStoredUser()
  const factoryId = localStorage.getItem('active_factory_id') || user?.factory_id || ''
  const [loading, setLoading] = useState(false)
  const [tasks, setTasks] = useState<WorkOrder[]>([])

  const fetchTasks = useCallback(async () => {
    if (!factoryId) return
    setLoading(true)
    try {
      const res = await getMyTasks(factoryId)
      setTasks(res.items || [])
    } catch (e: any) {
      message.error(e?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [factoryId])

  useEffect(() => { fetchTasks() }, [fetchTasks])

  const handleStart = async (task: WorkOrder) => {
    try {
      await startWorkOrder(task.id)
      message.success('已开工')
      fetchTasks()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败')
    }
  }

  const handleComplete = async (task: WorkOrder) => {
    try {
      await completeWorkOrder(task.id, { completed_qty: task.planned_qty, good_qty: task.planned_qty, defect_qty: 0 })
      message.success('已完工')
      fetchTasks()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '操作失败')
    }
  }

  const canStart = hasPermission('work_order', 'start')
  const canComplete = hasPermission('work_order', 'complete')

  // 分组：进行中 > 已释放 > 其他
  const activeTasks = tasks.filter(t => t.status === 'in_progress')
  const readyTasks = tasks.filter(t => t.status === 'released')
  const otherTasks = tasks.filter(t => !['in_progress', 'released'].includes(t.status))

  const renderTask = (task: WorkOrder) => {
    const sc = STATUS_CONFIG[task.status] || STATUS_CONFIG.pending
    return (
      <List.Item
        key={task.id}
        actions={[
          task.status === 'released' && canStart && (
            <Button type="primary" size="large" icon={<PlayCircleOutlined />} onClick={() => handleStart(task)}>
              开工
            </Button>
          ),
          task.status === 'in_progress' && canComplete && (
            <Button type="primary" size="large" icon={<CheckCircleOutlined />} style={{ background: '#52c41a', borderColor: '#52c41a' }} onClick={() => handleComplete(task)}>
              完工
            </Button>
          ),
        ].filter(Boolean)}
      >
        <List.Item.Meta
          avatar={<Badge status={sc.badge} />}
          title={
            <Space>
              <Text strong>{task.remark || task.work_order_code}</Text>
              <Tag>{PROCESS_NAME[task.process_code || ''] || task.process_code}</Tag>
              <Tag color={task.priority === 'urgent' ? 'red' : task.priority === 'high' ? 'orange' : 'blue'}>
                {task.priority === 'urgent' ? '加急' : task.priority === 'high' ? '紧急' : '普通'}
              </Tag>
            </Space>
          }
          description={
            <Space size={16}>
              <Text type="secondary">数量: {task.planned_qty}</Text>
              <Text type="secondary">交期: {task.planned_due?.slice(0, 10) || '-'}</Text>
              <Text style={{ color: sc.color }}>{sc.text}</Text>
            </Space>
          }
        />
      </List.Item>
    )
  }

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      <Card
        title={<Space><ThunderboltOutlined /> 我的任务</Space>}
        extra={<Button icon={<ReloadOutlined />} onClick={fetchTasks} size="small">刷新</Button>}
      >
        {tasks.length === 0 && !loading ? (
          <Empty description="暂无分配的任务" />
        ) : (
          <>
            {activeTasks.length > 0 && (
              <>
                <Title level={5} style={{ color: '#fa8c16' }}><ClockCircleOutlined /> 加工中 ({activeTasks.length})</Title>
                <List dataSource={activeTasks} renderItem={renderTask} loading={loading} />
              </>
            )}
            {readyTasks.length > 0 && (
              <>
                <Title level={5} style={{ color: '#1890ff', marginTop: 16 }}><PlayCircleOutlined /> 待开工 ({readyTasks.length})</Title>
                <List dataSource={readyTasks} renderItem={renderTask} />
              </>
            )}
            {otherTasks.length > 0 && (
              <>
                <Title level={5} style={{ color: '#8c8c8c', marginTop: 16 }}>其他 ({otherTasks.length})</Title>
                <List dataSource={otherTasks} renderItem={renderTask} />
              </>
            )}
          </>
        )}
      </Card>
    </div>
  )
}

export default MyTasks
