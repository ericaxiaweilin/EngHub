/**
 * AI 助手浮窗 + 内网 IM 联系人
 * 可拖拽移动、最小化/最大化，参考 luaguage ChatbotWidget 交互模式
 */
import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Tabs, Input, Button, List, Avatar, Badge, Tag, Typography, Space, Spin, Tooltip } from 'antd'
import {
  RobotOutlined, TeamOutlined, SendOutlined, MinusOutlined,
  ExpandOutlined, CompressOutlined, CloseOutlined,
  ToolOutlined, SafetyCertificateOutlined, DesktopOutlined, ApiOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { getStoredUser } from '../services/auth'

const { Text } = Typography
const { TextArea } = Input

// ---------- IM 联系人（内网工厂人员） ----------
interface Contact {
  id: string
  name: string
  role: string
  dept: string
  color: string
  icon: React.ReactNode
  online: boolean
  tasks: number  // 当前负责的任务/工单数
}

const FACTORY_CONTACTS: Contact[] = [
  { id: 'c1', name: '系统管理员', role: '超级管理员', dept: 'IT部', color: '#1677ff', icon: <DesktopOutlined />, online: true, tasks: 2 },
  { id: 'c2', name: '王品保', role: '品保主管', dept: '品质部', color: '#52c41a', icon: <SafetyCertificateOutlined />, online: true, tasks: 5 },
  { id: 'c3', name: '李生产', role: '生产主管', dept: '生产部', color: '#fa8c16', icon: <ApiOutlined />, online: true, tasks: 8 },
  { id: 'c4', name: '张维修', role: '设备维修工程师', dept: '设备部', color: '#f5222d', icon: <ToolOutlined />, online: false, tasks: 3 },
  { id: 'c5', name: '陈工艺', role: '工艺工程师', dept: '工程部', color: '#722ed1', icon: <ApiOutlined />, online: true, tasks: 4 },
  { id: 'c6', name: '刘计划', role: 'PMC计划员', dept: '计划部', color: '#13c2c2', icon: <DesktopOutlined />, online: false, tasks: 6 },
]

// ---------- 聊天消息 ----------
interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  time: string
  degraded?: boolean
}

const now = () => new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

export default function AIAssistantWidget() {
  const [open, setOpen] = useState(false)
  const [maximized, setMaximized] = useState(false)
  const [tab, setTab] = useState('ai')
  // 拖拽
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const dragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number } | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  // 聊天
  const [messages, setMessages] = useState<ChatMsg[]>([
    { role: 'assistant', content: '你好！我是 EngHub MES 智能助手，可以回答生产工单、报工、检验、不良品、库存、计划等问题。', time: now() },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  // IM 未读
  const [unread, setUnread] = useState<Record<string, number>>({ c2: 1, c3: 2 })
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null)

  const user = getStoredUser()

  // 自动滚动到底部
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messages, loading])

  // ---------- 拖拽逻辑 ----------
  const onHeaderMouseDown = useCallback((e: React.MouseEvent) => {
    if (maximized) return
    const rect = panelRef.current?.getBoundingClientRect()
    if (!rect) return
    dragRef.current = { startX: e.clientX, startY: e.clientY, baseX: rect.left, baseY: rect.top }
    const onMove = (ev: MouseEvent) => {
      const d = dragRef.current
      if (!d) return
      const nx = Math.max(0, Math.min(window.innerWidth - 390, d.baseX + ev.clientX - d.startX))
      const ny = Math.max(0, Math.min(window.innerHeight - 60, d.baseY + ev.clientY - d.startY))
      setPos({ x: nx, y: ny })
    }
    const onUp = () => {
      dragRef.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [maximized])

  // ---------- 发送消息 ----------
  const sendMessage = async () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    const history = [...messages, { role: 'user' as const, content: text, time: now() }]
    setMessages(history)
    setLoading(true)
    try {
      const payload = {
        messages: history.slice(-10).map(m => ({ role: m.role, content: m.content })),
      }
      const res: any = await api.post('/api/v1/chat', payload)
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: res.reply || '抱歉，暂时无法回答。',
        time: now(),
        degraded: res.degraded,
      }])
    } catch {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '网络异常，请稍后重试。',
        time: now(),
        degraded: true,
      }])
    } finally {
      setLoading(false)
    }
  }

  // ---------- 面板样式 ----------
  const panelStyle: React.CSSProperties = maximized
    ? { position: 'fixed', inset: 0, width: '100vw', height: '100vh', borderRadius: 0, zIndex: 1000 }
    : {
        position: 'fixed',
        width: 380,
        height: 520,
        borderRadius: 12,
        zIndex: 1000,
        ...(pos
          ? { left: pos.x, top: pos.y }
          : { right: 24, bottom: 90 }),
      }

  const totalUnread = Object.values(unread).reduce((a, b) => a + b, 0)

  return (
    <>
      {/* 悬浮按钮 */}
      {!open && (
        <Tooltip title="AI 助手 / 内网通讯" placement="left">
          <Button
            type="primary"
            shape="circle"
            size="large"
            icon={<RobotOutlined />}
            onClick={() => setOpen(true)}
            style={{
              position: 'fixed', right: 24, bottom: 24, zIndex: 1000,
              width: 52, height: 52, boxShadow: '0 4px 12px rgba(22,119,255,0.4)',
            }}
          />
        </Tooltip>
      )}

      {/* 面板 */}
      {open && (
        <div
          ref={panelRef}
          style={{
            ...panelStyle,
            background: '#fff',
            boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            border: '1px solid #f0f0f0',
          }}
        >
          {/* 头部（拖拽区域） */}
          <div
            onMouseDown={onHeaderMouseDown}
            style={{
              padding: '10px 14px',
              background: 'linear-gradient(135deg, #1677ff 0%, #4096ff 100%)',
              color: '#fff',
              cursor: maximized ? 'default' : 'move',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              userSelect: 'none',
              flexShrink: 0,
            }}
          >
            <Space size={8}>
              <RobotOutlined />
              <Text strong style={{ color: '#fff' }}>EngHub 智能助手</Text>
            </Space>
            <Space size={4}>
              <Button type="text" size="small" icon={<MinusOutlined />} style={{ color: '#fff' }}
                onClick={() => setOpen(false)} />
              <Button type="text" size="small"
                icon={maximized ? <CompressOutlined /> : <ExpandOutlined />}
                style={{ color: '#fff' }}
                onClick={() => { setMaximized(!maximized); setPos(null) }} />
              <Button type="text" size="small" icon={<CloseOutlined />} style={{ color: '#fff' }}
                onClick={() => setOpen(false)} />
            </Space>
          </div>

          {/* Tabs */}
          <Tabs
            activeKey={tab}
            onChange={setTab}
            size="small"
            centered
            style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
            items={[
              {
                key: 'ai',
                label: <span><RobotOutlined /> AI 助手</span>,
                children: (
                  <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                    {/* 消息列表 */}
                    <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: '12px 14px' }}>
                      {messages.map((m, i) => (
                        <div key={i} style={{
                          display: 'flex',
                          justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
                          marginBottom: 10,
                        }}>
                          {m.role === 'assistant' && (
                            <Avatar size={28} icon={<RobotOutlined />} style={{ background: '#1677ff', marginRight: 8, flexShrink: 0 }} />
                          )}
                          <div style={{
                            maxWidth: '75%',
                            padding: '8px 12px',
                            borderRadius: 10,
                            background: m.role === 'user' ? '#1677ff' : '#f5f5f5',
                            color: m.role === 'user' ? '#fff' : '#333',
                            fontSize: 13,
                            lineHeight: 1.5,
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                          }}>
                            {m.content}
                            {m.degraded && m.role === 'assistant' && (
                              <div style={{ marginTop: 4 }}>
                                <Tag color="orange" style={{ fontSize: 10 }}>离线降级模式</Tag>
                              </div>
                            )}
                            <div style={{
                              fontSize: 10,
                              color: m.role === 'user' ? 'rgba(255,255,255,0.7)' : '#999',
                              marginTop: 4,
                              textAlign: 'right',
                            }}>{m.time}</div>
                          </div>
                          {m.role === 'user' && (
                            <Avatar size={28} style={{ background: '#87d068', marginLeft: 8, flexShrink: 0 }}>
                              {(user?.full_name || user?.username || '我')[0]}
                            </Avatar>
                          )}
                        </div>
                      ))}
                      {loading && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                          <Avatar size={28} icon={<RobotOutlined />} style={{ background: '#1677ff' }} />
                          <Spin size="small" />
                          <Text type="secondary" style={{ fontSize: 12 }}>思考中...</Text>
                        </div>
                      )}
                    </div>
                    {/* 输入区 */}
                    <div style={{ padding: '8px 12px', borderTop: '1px solid #f0f0f0', flexShrink: 0 }}>
                      <Space.Compact style={{ width: '100%' }}>
                        <TextArea
                          value={input}
                          onChange={e => setInput(e.target.value)}
                          onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); sendMessage() } }}
                          placeholder="输入问题，Enter 发送..."
                          autoSize={{ minRows: 1, maxRows: 3 }}
                          style={{ borderRadius: '8px 0 0 8px' }}
                        />
                        <Button
                          type="primary"
                          icon={<SendOutlined />}
                          onClick={sendMessage}
                          loading={loading}
                          style={{ borderRadius: '0 8px 8px 0', height: 'auto' }}
                        />
                      </Space.Compact>
                    </div>
                  </div>
                ),
              },
              {
                key: 'im',
                label: (
                  <Badge count={totalUnread} size="small" offset={[8, -2]}>
                    <span><TeamOutlined /> 内网通讯</span>
                  </Badge>
                ),
                children: (
                  <div style={{ height: '100%', overflowY: 'auto', padding: '8px 0' }}>
                    {selectedContact ? (
                      /* 联系人详情 */
                      <div style={{ padding: '0 14px' }}>
                        <Button type="link" size="small" onClick={() => setSelectedContact(null)} style={{ padding: 0, marginBottom: 10 }}>
                          ← 返回联系人列表
                        </Button>
                        <div style={{ textAlign: 'center', padding: '12px 0' }}>
                          <Avatar size={56} style={{ background: selectedContact.color }} icon={selectedContact.icon} />
                          <div style={{ marginTop: 8 }}>
                            <Text strong style={{ fontSize: 16 }}>{selectedContact.name}</Text>
                          </div>
                          <Text type="secondary">{selectedContact.role} · {selectedContact.dept}</Text>
                          <div style={{ marginTop: 8 }}>
                            <Tag color={selectedContact.online ? 'green' : 'default'}>
                              {selectedContact.online ? '在线' : '离线'}
                            </Tag>
                            <Tag color="blue">{selectedContact.tasks} 个进行中任务</Tag>
                          </div>
                        </div>
                        <div style={{ borderTop: '1px solid #f0f0f0', paddingTop: 12 }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>快捷操作</Text>
                          <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                            <Button size="small" onClick={() => { window.location.hash = ''; window.location.pathname = '/tms/distribution' }}>
                              查看任务分发
                            </Button>
                            <Button size="small" onClick={() => { window.location.pathname = '/tms/approval' }}>
                              审批中心
                            </Button>
                            <Button size="small" onClick={() => { window.location.pathname = '/quick-request' }}>
                              发起工单
                            </Button>
                          </div>
                        </div>
                      </div>
                    ) : (
                      /* 联系人列表 */
                      <List
                        dataSource={FACTORY_CONTACTS}
                        renderItem={(c) => (
                          <List.Item
                            style={{ padding: '8px 16px', cursor: 'pointer' }}
                            onClick={() => {
                              setSelectedContact(c)
                              setUnread(prev => ({ ...prev, [c.id]: 0 }))
                            }}
                          >
                            <List.Item.Meta
                              avatar={
                                <Badge dot={c.online} color="green" offset={[-4, 4]}>
                                  <Avatar style={{ background: c.color }} icon={c.icon} />
                                </Badge>
                              }
                              title={
                                <span>
                                  {c.name}
                                  <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>{c.role}</Text>
                                </span>
                              }
                              description={
                                <span style={{ fontSize: 12 }}>
                                  {c.dept} · {c.online ? '在线' : '离线'}
                                  {c.tasks > 0 && <Tag color="blue" style={{ marginLeft: 6, fontSize: 10 }}>{c.tasks} 任务</Tag>}
                                </span>
                              }
                            />
                            {unread[c.id] > 0 && <Badge count={unread[c.id]} />}
                          </List.Item>
                        )}
                      />
                    )}
                  </div>
                ),
              },
            ]}
          />
        </div>
      )}
    </>
  )
}
