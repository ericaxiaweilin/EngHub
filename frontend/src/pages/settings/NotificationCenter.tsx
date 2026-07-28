/**
 * 通知中心 - Notification Center
 * 对接后端 /api/v1/notifications/*
 * 功能：通知列表（分类过滤）、未读Badge、标记已读、全部已读
 */
import React, { useState, useEffect, useCallback } from 'react'
import {
  Card, List, Tag, Button, Space, Badge, Select, Typography,
  Empty, message, Row, Col, Statistic, Tooltip,
} from 'antd'
import {
  BellOutlined, CheckOutlined, CheckCircleOutlined,
  ReloadOutlined, AlertOutlined, FileTextOutlined,
  NotificationOutlined, ToolOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const { Text, Title } = Typography
const FACTORY = localStorage.getItem('active_factory_id') || 'FAC_MECH_001'

const CATEGORY_CONFIG: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  report: { color: 'blue', icon: <FileTextOutlined />, label: '报告' },
  anomaly: { color: 'red', icon: <AlertOutlined />, label: '异常' },
  system: { color: 'default', icon: <NotificationOutlined />, label: '系统' },
  andon: { color: 'orange', icon: <ToolOutlined />, label: '安灯' },
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: 'red', high: 'orange', medium: 'blue', low: 'default',
}

const NotificationCenter: React.FC = () => {
  const [items, setItems] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [unreadCount, setUnreadCount] = useState(0)
  const [category, setCategory] = useState<string | undefined>(undefined)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [loading, setLoading] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params: any = { factory_id: FACTORY, limit: 50 }
      if (category) params.category = category
      if (unreadOnly) params.unread_only = true
      const res: any = await api.get('/api/v1/notifications', { params })
      setItems(res.items || [])
      setTotal(res.total || 0)
    } catch { /* ignore */ }
    setLoading(false)
  }, [category, unreadOnly])

  const fetchUnread = useCallback(async () => {
    try {
      const res: any = await api.get('/api/v1/notifications/unread-count', { params: { factory_id: FACTORY } })
      setUnreadCount(res.unread_count || 0)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchData(); fetchUnread() }, [fetchData, fetchUnread])

  const markRead = async (id: string) => {
    try {
      await api.put(`/api/v1/notifications/${id}/read`)
      message.success('已标记已读')
      fetchData(); fetchUnread()
    } catch { message.error('操作失败') }
  }

  const markAllRead = async () => {
    try {
      const res: any = await api.put('/api/v1/notifications/read-all', null, { params: { factory_id: FACTORY } })
      message.success(`已标记 ${res.updated} 条为已读`)
      fetchData(); fetchUnread()
    } catch { message.error('操作失败') }
  }

  return (
    <div style={{ padding: 24 }}>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small"><Statistic title="全部通知" value={total} prefix={<BellOutlined />} /></Card>
        </Col>
        <Col span={6}>
          <Card size="small"><Statistic title="未读" value={unreadCount} prefix={<Badge count={unreadCount} dot />} valueStyle={{ color: unreadCount > 0 ? '#cf1322' : undefined }} /></Card>
        </Col>
        <Col span={12}>
          <Card size="small" style={{ display: 'flex', alignItems: 'center', height: '100%' }}>
            <Space>
              <Select allowClear placeholder="分类" style={{ width: 120 }} value={category} onChange={setCategory}
                options={Object.entries(CATEGORY_CONFIG).map(([k, v]) => ({ value: k, label: v.label }))} />
              <Button type={unreadOnly ? 'primary' : 'default'} onClick={() => setUnreadOnly(!unreadOnly)}>
                仅未读
              </Button>
              <Button icon={<CheckCircleOutlined />} onClick={markAllRead}>全部已读</Button>
              <Button icon={<ReloadOutlined />} onClick={() => { fetchData(); fetchUnread() }}>刷新</Button>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card title={<><BellOutlined /> 通知列表</>} size="small">
        {items.length === 0 ? (
          <Empty description="暂无通知" />
        ) : (
          <List
            dataSource={items}
            renderItem={(item: any) => {
              const cat = CATEGORY_CONFIG[item.category] || CATEGORY_CONFIG.system
              return (
                <List.Item
                  style={{ background: item.is_read ? undefined : '#f6ffed', padding: '12px 16px' }}
                  actions={[
                    !item.is_read && (
                      <Tooltip title="标记已读" key="read">
                        <Button size="small" icon={<CheckOutlined />} onClick={() => markRead(item.id)} />
                      </Tooltip>
                    ),
                  ].filter(Boolean)}
                >
                  <List.Item.Meta
                    avatar={<Badge dot={!item.is_read}>{cat.icon}</Badge>}
                    title={
                      <Space>
                        <Tag color={cat.color}>{cat.label}</Tag>
                        {item.severity && <Tag color={SEVERITY_COLOR[item.severity] || 'default'}>{item.severity}</Tag>}
                        <Text strong={!item.is_read}>{item.title}</Text>
                      </Space>
                    }
                    description={
                      <Space direction="vertical" size={0}>
                        <Text type="secondary">{item.content}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {item.created_at ? new Date(item.created_at).toLocaleString('zh-CN') : ''}
                          {item.source_type ? ` · 来源: ${item.source_type}` : ''}
                        </Text>
                      </Space>
                    }
                  />
                </List.Item>
              )
            }}
          />
        )}
      </Card>
    </div>
  )
}

export default NotificationCenter
