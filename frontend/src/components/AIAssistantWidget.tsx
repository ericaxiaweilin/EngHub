/**
 * AI 助手浮窗 + 内网 IM 联系人
 * 可拖拽移动、最小化/最大化，参考 luaguage ChatbotWidget 交互模式
 */
import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Tabs, Input, Button, List, Avatar, Badge, Tag, Typography, Space, Spin, Tooltip, Modal, Form, Radio, message } from 'antd'
import {
  RobotOutlined, TeamOutlined, SendOutlined, MinusOutlined,
  ExpandOutlined, CompressOutlined, CloseOutlined,
  ToolOutlined, SafetyCertificateOutlined, DesktopOutlined, ApiOutlined,
  ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined,
  AlertOutlined, ExperimentOutlined, PhoneOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { tmsApi } from '../services/tms'
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

// ---------- 工具执行记录（AI 已执行的操作） ----------
interface ToolAction {
  tool: string
  label: string
  arguments: Record<string, any>
  result: Record<string, any>
  is_write: boolean
  success: boolean
}

// ---------- 聊天消息 ----------
interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  time: string
  degraded?: boolean
  actions?: ToolAction[]
}

// ---------- 快捷指令 ----------
const QUICK_COMMANDS = [
  '今天生产情况怎么样？',
  '查询在制工单',
  '查询库存水平',
  '最近有哪些不良品？',
  '设备运行状态如何？',
]

// ---------- IM 聊天消息 ----------
interface IMMsg {
  id: string
  from: 'me' | 'them' | 'system'
  content: string
  time: string
  isCall?: boolean  // 工单呼叫卡片
  callMeta?: { call_type: string; station: string; priority: string; task_code?: string }
}

// 工单呼叫类型（与 QuickRequest 页一致，落到 TMS call_request）
const IM_CALL_TYPES = [
  { value: 'equipment_fault', label: '设备故障', icon: <ToolOutlined />, color: '#f5222d' },
  { value: 'material_call', label: '物料呼叫', icon: <AlertOutlined />, color: '#fa8c16' },
  { value: 'quality_call', label: '品质呼叫', icon: <ExperimentOutlined />, color: '#722ed1' },
  { value: 'support_call', label: '支援呼叫', icon: <PhoneOutlined />, color: '#1890ff' },
]

const now = () => new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

export default function AIAssistantWidget() {
  const [open, setOpen] = useState(false)
  const [maximized, setMaximized] = useState(false)
  const [tab, setTab] = useState('ai')
  // 拖拽 & 拉伸（参考 luaguage ChatbotWidget - Pointer Events 方案）
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const dragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number } | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  // 拉伸状态（Pointer Capture 方案，不用 React state 避免重渲染）
  const resizeStateRef = useRef<{
    edge: 'left' | 'right' | 'top' | 'bottom'
    startX: number
    startY: number
    startWidth: number
    startHeight: number
    rafId?: number
  } | null>(null)
  const [isResizing, setIsResizing] = useState(false)
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
  // IM 聊天
  const [imMessages, setImMessages] = useState<Record<string, IMMsg[]>>({})
  const [imInput, setImInput] = useState('')
  const [imSending, setImSending] = useState(false)
  const imListRef = useRef<HTMLDivElement>(null)
  // 工单呼叫弹窗
  const [callModalOpen, setCallModalOpen] = useState(false)
  const [callType, setCallType] = useState('equipment_fault')
  const [callForm] = Form.useForm()
  const [callSubmitting, setCallSubmitting] = useState(false)

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

  // ---------- 拉伸逻辑（luaguage Pointer Events 方案） ----------
  const handleResizeStart = useCallback((
    event: React.PointerEvent<HTMLDivElement>,
    edge: 'left' | 'right' | 'top' | 'bottom',
  ) => {
    if (maximized) return
    const node = panelRef.current
    if (!node) return
    event.preventDefault()
    // 关键：setPointerCapture 保证鼠标移出窗口也能收到事件
    ;(event.currentTarget as HTMLDivElement).setPointerCapture(event.pointerId)
    resizeStateRef.current = {
      edge,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: node.offsetWidth,
      startHeight: node.offsetHeight,
    }
    setIsResizing(true)
  }, [maximized])

  const handleResizeMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const state = resizeStateRef.current
    const node = panelRef.current
    if (!state || !node) return
    if (state.rafId != null) cancelAnimationFrame(state.rafId)
    const cx = event.clientX
    const cy = event.clientY
    state.rafId = requestAnimationFrame(() => {
      const margin = 8
      const minWidth = 320
      const minHeight = 400
      const maxWidth = Math.max(minWidth, window.innerWidth - margin * 2)
      const maxHeight = Math.max(minHeight, window.innerHeight - margin * 2)
      const widthDelta = state.edge === 'left'
        ? state.startX - cx
        : state.edge === 'right'
          ? cx - state.startX
          : 0
      const heightDelta = state.edge === 'top'
        ? state.startY - cy
        : state.edge === 'bottom'
          ? cy - state.startY
          : 0
      const nextWidth = Math.min(maxWidth, Math.max(minWidth, state.startWidth + widthDelta))
      const nextHeight = Math.min(maxHeight, Math.max(minHeight, state.startHeight + heightDelta))
      // 直接操作 DOM，不用 React state，避免重渲染卡顿
      node.style.width = `${nextWidth}px`
      node.style.height = `${nextHeight}px`
    })
  }, [])

  const handleResizeEnd = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const state = resizeStateRef.current
    if (state?.rafId != null) cancelAnimationFrame(state.rafId)
    resizeStateRef.current = null
    setIsResizing(false)
    ;(event.currentTarget as HTMLDivElement).releasePointerCapture(event.pointerId)
  }, [])

  // ---------- 发送消息 ----------
  const sendMessage = async (preset?: string) => {
    const text = (preset ?? input).trim()
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
        actions: res.actions || [],
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

  // ---------- IM 自动滚动 ----------
  useEffect(() => {
    if (imListRef.current) imListRef.current.scrollTop = imListRef.current.scrollHeight
  }, [imMessages, selectedContact])

  // ---------- IM 发送消息 ----------
  const sendImMessage = () => {
    const text = imInput.trim()
    if (!text || !selectedContact || imSending) return
    setImInput('')
    const cid = selectedContact.id
    const myMsg: IMMsg = { id: `m${Date.now()}`, from: 'me', content: text, time: now() }
    setImMessages(prev => ({ ...prev, [cid]: [...(prev[cid] || []), myMsg] }))
    setImSending(true)
    // 内网环境：模拟对方回复（实际可对接 WebSocket）
    const contact = selectedContact
    setTimeout(() => {
      setImMessages(prev => ({
        ...prev,
        [cid]: [...(prev[cid] || []), {
          id: `r${Date.now()}`,
          from: 'them',
          content: contact.online
            ? `收到，我是${contact.name}，看到后会尽快处理。如需紧急处理可点下方“工单呼叫”。`
            : '（对方离线，消息已送达，上线后可见）',
          time: now(),
        }],
      }))
      setImSending(false)
    }, 900)
  }

  // ---------- 打开工单呼叫弹窗 ----------
  const openCallModal = (type: string) => {
    setCallType(type)
    callForm.resetFields()
    callForm.setFieldsValue({ priority: 'high' })
    setCallModalOpen(true)
  }

  // ---------- 提交工单呼叫 → 直接创建 TMS 任务（不跳转页面） ----------
  const submitCall = async () => {
    if (!selectedContact) return
    try {
      const values = await callForm.validateFields()
      setCallSubmitting(true)
      const ct = IM_CALL_TYPES.find(c => c.value === callType)
      const res: any = await tmsApi.createTask({
        title: `${ct?.label}呼叫 - ${values.station}`,
        task_type: 'call_request',
        description: values.description,
        priority: values.priority,
        required_skills: [],
        metadata: {
          call_type: callType,
          station: values.station,
          requested_by: user?.username,
          target_contact: selectedContact.name,
          via: 'im_chat',
        } as any,
      })
      const taskCode = res?.task_code || res?.data?.task_code || ''
      const cid = selectedContact.id
      setImMessages(prev => ({
        ...prev,
        [cid]: [...(prev[cid] || []), {
          id: `c${Date.now()}`,
          from: 'system',
          isCall: true,
          content: `${ct?.label}呼叫已发送给 ${selectedContact.name}`,
          time: now(),
          callMeta: { call_type: callType, station: values.station, priority: values.priority, task_code: taskCode },
        }],
      }))
      message.success('工单呼叫已发送，等待响应')
      setCallModalOpen(false)
    } catch (e: any) {
      if (e?.errorFields) return
      message.error('呼叫发送失败: ' + (e?.response?.data?.detail || e?.message || ''))
    } finally {
      setCallSubmitting(false)
    }
  }

  // ---------- 面板样式（初始尺寸，拉伸通过直接操作 DOM） ----------
  const panelStyle: React.CSSProperties = maximized
    ? { position: 'fixed', inset: 0, width: '100vw', height: '100vh', borderRadius: 0, zIndex: 1000 }
    : {
        position: 'fixed',
        width: 400,
        height: 560,
        minWidth: 320,
        minHeight: 400,
        maxWidth: '92vw',
        maxHeight: '92vh',
        borderRadius: 12,
        zIndex: 1000,
        // 拉伸时禁止文本选中
        userSelect: isResizing ? 'none' : undefined,
        ...(pos
          ? { left: pos.x, top: pos.y }
          : { right: 24, bottom: 24 }),
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

          {/* Tab 导航栏（仅切换，不承载内容） */}
          <Tabs
            activeKey={tab}
            onChange={setTab}
            size="small"
            centered
            style={{ flexShrink: 0, margin: 0, padding: '0 12px' }}
            items={[
              { key: 'ai', label: <span><RobotOutlined /> AI 助手</span> },
              {
                key: 'im',
                label: (
                  <Badge count={totalUnread} size="small" offset={[8, -2]}>
                    <span><TeamOutlined /> 内网通讯</span>
                  </Badge>
                ),
              },
            ]}
          />

          {/* 内容区（直接 flex 布局，不经过 Tabs content-holder） */}
          <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            {tab === 'ai' && (
              <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
                {/* 消息列表 */}
                <div ref={listRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px 14px' }}>
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
                            {/* AI 已执行的操作 */}
                            {m.role === 'assistant' && m.actions && m.actions.length > 0 && (
                              <div style={{ marginTop: 8, borderTop: '1px dashed #d9d9d9', paddingTop: 6 }}>
                                <Text type="secondary" style={{ fontSize: 11 }}>
                                  <ThunderboltOutlined /> 已执行 {m.actions.length} 个操作
                                </Text>
                                {m.actions.map((a, idx) => (
                                  <div key={idx} style={{
                                    marginTop: 4,
                                    background: a.is_write ? '#f6ffed' : '#f0f5ff',
                                    border: `1px solid ${a.is_write ? '#b7eb8f' : '#adc6ff'}`,
                                    borderRadius: 6,
                                    padding: '4px 8px',
                                    fontSize: 11,
                                  }}>
                                    <Space size={4}>
                                      {a.success
                                        ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                                        : <CloseCircleOutlined style={{ color: '#f5222d' }} />}
                                      <Text strong style={{ fontSize: 11 }}>{a.label}</Text>
                                      <Tag color={a.is_write ? 'green' : 'blue'} style={{ fontSize: 10, lineHeight: '16px', margin: 0 }}>
                                        {a.is_write ? '写操作' : '查询'}
                                      </Tag>
                                    </Space>
                                    {a.result && a.result.error && (
                                      <div style={{ color: '#f5222d', marginTop: 2 }}>{a.result.error}</div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}
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
                    {/* 快捷指令 */}
                    <div style={{ padding: '6px 12px 0', flexShrink: 0, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {QUICK_COMMANDS.map(cmd => (
                        <Tag
                          key={cmd}
                          color="processing"
                          style={{ cursor: loading ? 'not-allowed' : 'pointer', fontSize: 11, borderRadius: 12, padding: '1px 8px' }}
                          onClick={() => !loading && sendMessage(cmd)}
                        >
                          {cmd}
                        </Tag>
                      ))}
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
                          onClick={() => sendMessage()}
                          loading={loading}
                          style={{ borderRadius: '0 8px 8px 0', height: 'auto' }}
                        />
                      </Space.Compact>
                    </div>
              </div>
            )}
            {tab === 'im' && (
                  <div style={{ flex: 1, minHeight: 0, overflowY: selectedContact ? 'hidden' : 'auto', padding: selectedContact ? 0 : '8px 0' }}>
                    {selectedContact ? (
                      /* 联系人聊天 */
                      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                        {/* 头部 */}
                        <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                          <Button type="text" size="small" onClick={() => setSelectedContact(null)}>←</Button>
                          <Avatar size={32} style={{ background: selectedContact.color }} icon={selectedContact.icon} />
                          <div style={{ flex: 1, lineHeight: 1.3 }}>
                            <div>
                              <Text strong>{selectedContact.name}</Text>
                              <Text type="secondary" style={{ fontSize: 11, marginLeft: 6 }}>{selectedContact.role}</Text>
                            </div>
                            <Badge status={selectedContact.online ? 'success' : 'default'}
                              text={<Text type="secondary" style={{ fontSize: 11 }}>{selectedContact.online ? '在线' : '离线'} · {selectedContact.tasks} 个任务</Text>} />
                          </div>
                        </div>
                        {/* 消息区 */}
                        <div ref={imListRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '10px 12px', background: '#fafafa' }}>
                          {(imMessages[selectedContact.id] || []).length === 0 && (
                            <div style={{ textAlign: 'center', color: '#999', fontSize: 12, marginTop: 24 }}>
                              暂无消息，可直接发送或发起工单呼叫
                            </div>
                          )}
                          {(imMessages[selectedContact.id] || []).map(m => (
                            <div key={m.id} style={{ marginBottom: 10 }}>
                              {m.isCall ? (
                                /* 工单呼叫卡片 */
                                <div style={{ maxWidth: '88%', margin: '0 auto', background: '#fff7e6', border: '1px solid #ffd591', borderRadius: 8, padding: '8px 10px', fontSize: 12 }}>
                                  <Space size={4}>
                                    <PhoneOutlined style={{ color: '#fa8c16' }} />
                                    <Text strong style={{ fontSize: 12 }}>{m.content}</Text>
                                  </Space>
                                  <div style={{ marginTop: 4, color: '#666', fontSize: 11 }}>
                                    工位：{m.callMeta?.station} · 优先级：{m.callMeta?.priority}
                                    {m.callMeta?.task_code && <span> · 任务号：{m.callMeta.task_code}</span>}
                                  </div>
                                  <div style={{ fontSize: 10, color: '#999', marginTop: 2, textAlign: 'right' }}>{m.time}</div>
                                </div>
                              ) : (
                                <div style={{ display: 'flex', justifyContent: m.from === 'me' ? 'flex-end' : 'flex-start' }}>
                                  {m.from === 'them' && (
                                    <Avatar size={26} style={{ background: selectedContact.color, marginRight: 6, flexShrink: 0 }} icon={selectedContact.icon} />
                                  )}
                                  <div style={{
                                    maxWidth: '72%', padding: '7px 10px', borderRadius: 10,
                                    background: m.from === 'me' ? '#1677ff' : '#fff',
                                    color: m.from === 'me' ? '#fff' : '#333',
                                    fontSize: 12, lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                                    border: m.from === 'them' ? '1px solid #eee' : 'none',
                                  }}>
                                    {m.content}
                                    <div style={{ fontSize: 10, color: m.from === 'me' ? 'rgba(255,255,255,0.7)' : '#999', marginTop: 3, textAlign: 'right' }}>{m.time}</div>
                                  </div>
                                </div>
                              )}
                            </div>
                          ))}
                          {imSending && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <Avatar size={26} style={{ background: selectedContact.color }} icon={selectedContact.icon} />
                              <Spin size="small" />
                            </div>
                          )}
                        </div>
                        {/* 工单呼叫快捷按钮 */}
                        <div style={{ padding: '6px 12px', borderTop: '1px solid #f0f0f0', flexShrink: 0 }}>
                          <Text type="secondary" style={{ fontSize: 11 }}>工单呼叫（直达 {selectedContact.name}，无需跳转）</Text>
                          <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                            {IM_CALL_TYPES.map(ct => (
                              <Button key={ct.value} size="small" onClick={() => openCallModal(ct.value)}
                                style={{ flex: 1, color: ct.color, borderColor: ct.color, fontSize: 11, padding: '0 2px' }}>
                                {ct.icon} {ct.label}
                              </Button>
                            ))}
                          </div>
                        </div>
                        {/* 输入区 */}
                        <div style={{ padding: '8px 12px', borderTop: '1px solid #f0f0f0', flexShrink: 0 }}>
                          <Space.Compact style={{ width: '100%' }}>
                            <Input
                              value={imInput}
                              onChange={e => setImInput(e.target.value)}
                              onPressEnter={sendImMessage}
                              placeholder={`发消息给 ${selectedContact.name}...`}
                            />
                            <Button type="primary" icon={<SendOutlined />} onClick={sendImMessage} />
                          </Space.Compact>
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
            )}
          </div>

          {/* 拉伸手柄（四方向，参考 luaguage Pointer Events 方案） */}
          {!maximized && (
            <>
              {/* 顶部手柄 */}
              <div
                onPointerDown={(e) => handleResizeStart(e, 'top')}
                onPointerMove={handleResizeMove}
                onPointerUp={handleResizeEnd}
                onPointerCancel={handleResizeEnd}
                title="顶部拖拽调整高度"
                style={{
                  position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)',
                  width: '28%', maxWidth: 120, height: 10, cursor: 'ns-resize',
                  touchAction: 'none', userSelect: 'none', zIndex: 70,
                }}
              >
                <div style={{ width: 40, height: 3, margin: '4px auto 0', borderRadius: 999, background: 'rgba(0,0,0,0.15)' }} />
              </div>
              {/* 底部手柄 */}
              <div
                onPointerDown={(e) => handleResizeStart(e, 'bottom')}
                onPointerMove={handleResizeMove}
                onPointerUp={handleResizeEnd}
                onPointerCancel={handleResizeEnd}
                title="底部拖拽调整高度"
                style={{
                  position: 'absolute', bottom: 0, left: '50%', transform: 'translateX(-50%)',
                  width: '28%', maxWidth: 120, height: 10, cursor: 'ns-resize',
                  touchAction: 'none', userSelect: 'none', zIndex: 70,
                }}
              >
                <div style={{ width: 40, height: 3, margin: '4px auto 0', borderRadius: 999, background: 'rgba(0,0,0,0.15)' }} />
              </div>
              {/* 左下角手柄 */}
              <div
                onPointerDown={(e) => handleResizeStart(e, 'left')}
                onPointerMove={handleResizeMove}
                onPointerUp={handleResizeEnd}
                onPointerCancel={handleResizeEnd}
                title="左下角拖拽缩放"
                style={{
                  position: 'absolute', left: 6, bottom: 6, width: 16, height: 16,
                  cursor: 'nesw-resize', touchAction: 'none', userSelect: 'none', zIndex: 70,
                  display: 'flex', alignItems: 'flex-end', justifyContent: 'flex-start',
                  borderBottomLeftRadius: 10,
                }}
              >
                <div style={{ width: 10, height: 10, borderLeft: '2px solid rgba(0,0,0,0.25)', borderBottom: '2px solid rgba(0,0,0,0.25)', borderBottomLeftRadius: 8 }} />
              </div>
              {/* 右下角手柄 */}
              <div
                onPointerDown={(e) => handleResizeStart(e, 'right')}
                onPointerMove={handleResizeMove}
                onPointerUp={handleResizeEnd}
                onPointerCancel={handleResizeEnd}
                title="右下角拖拽缩放"
                style={{
                  position: 'absolute', right: 6, bottom: 6, width: 16, height: 16,
                  cursor: 'nwse-resize', touchAction: 'none', userSelect: 'none', zIndex: 70,
                  display: 'flex', alignItems: 'flex-end', justifyContent: 'flex-end',
                  borderBottomRightRadius: 10,
                }}
              >
                <div style={{ width: 10, height: 10, borderRight: '2px solid rgba(0,0,0,0.25)', borderBottom: '2px solid rgba(0,0,0,0.25)', borderBottomRightRadius: 8 }} />
              </div>
            </>
          )}
        </div>
      )}

      {/* 工单呼叫弹窗（模板直达，无需跳转页面） */}
      <Modal
        title={
          <Space>
            <PhoneOutlined style={{ color: IM_CALL_TYPES.find(c => c.value === callType)?.color }} />
            <span>{IM_CALL_TYPES.find(c => c.value === callType)?.label}呼叫</span>
          </Space>
        }
        open={callModalOpen}
        onCancel={() => setCallModalOpen(false)}
        onOk={submitCall}
        confirmLoading={callSubmitting}
        okText="发送呼叫"
        cancelText="取消"
        width={400}
        destroyOnClose
      >
        {selectedContact && (
          <div style={{ marginBottom: 12, padding: '8px 10px', background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 6, fontSize: 12 }}>
            <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 6 }} />
            呼叫将直达 <Text strong>{selectedContact.name}</Text>（{selectedContact.role}），并同步创建 TMS 任务
          </div>
        )}
        <Form form={callForm} layout="vertical">
          <Form.Item name="station" label="工位 / 位置" rules={[{ required: true, message: '请输入工位' }]}>
            <Input placeholder="如: ST-ASM-01 / A栋2层" />
          </Form.Item>
          <Form.Item name="priority" label="紧急程度" rules={[{ required: true }]}>
            <Radio.Group>
              <Radio.Button value="low">低</Radio.Button>
              <Radio.Button value="medium">中</Radio.Button>
              <Radio.Button value="high">高</Radio.Button>
              <Radio.Button value="urgent">紧急</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item name="description" label="问题描述" rules={[{ required: true, message: '请描述问题' }]}>
            <Input.TextArea rows={3} placeholder="简要描述现场情况..." />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}
