/**
 * AI 助手浮窗 + 内网 IM 联系人
 * 可拖拽移动、最小化/最大化，参考 luaguage ChatbotWidget 交互模式
 */
import React, { useState, useRef, useEffect, useCallback, lazy, Suspense } from 'react'
import { Tabs, Input, Button, List, Avatar, Badge, Tag, Typography, Space, Spin, Tooltip, Popover, Modal, Form, Radio, message, Table, Select, Empty, Popconfirm } from 'antd'
import {
  RobotOutlined, TeamOutlined, SendOutlined, MinusOutlined,
  ExpandOutlined, CompressOutlined, CloseOutlined,
  ToolOutlined, SafetyCertificateOutlined, DesktopOutlined, ApiOutlined,
  ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined,
  AlertOutlined, ExperimentOutlined, PhoneOutlined,
  PaperClipOutlined, FileOutlined, DownloadOutlined, TableOutlined,
  CopyOutlined, ShareAltOutlined, CommentOutlined, InboxOutlined,
  ArrowLeftOutlined, CheckOutlined, ReloadOutlined,
  PlusOutlined, DeleteOutlined, EditOutlined, UnorderedListOutlined,
  CarryOutOutlined, InfoCircleOutlined, CrownOutlined,
} from '@ant-design/icons'

// 任务中心（嵌入 chatbot 浮窗第三个 tab）
import TaskCenter from '../pages/collab/TaskCenter'

// Univer 电子表格（懒加载：仅在用户点击"在电子表格中打开"时才下载分包）
const SpreadsheetEditor = lazy(() => import('./SpreadsheetEditor'))
import api from '../services/api'
import { tmsApi } from '../services/tms'
import { getStoredUser, logout } from '../services/auth'

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
  is_sim?: boolean
  success: boolean
}

// ---------- 附件（随消息上传的图片/文件） ----------
interface MsgAttachment {
  file_id: string
  filename: string
  content_type?: string
  is_image?: boolean
  size?: number
}

// ---------- 结构化表格数据（后端 table 事件推送） ----------
interface TableData {
  title: string
  columns: { key: string; label: string }[]
  rows: Record<string, any>[]
}

// ---------- 聊天消息 ----------
interface ChatMsg {
  id: string
  role: 'user' | 'assistant'
  content: string
  time: string
  quote?: {
    id: string
    role: 'user' | 'assistant'
    content: string
  }
  degraded?: boolean
  actions?: ToolAction[]
  attachments?: MsgAttachment[]
  tables?: TableData[]
}

// ---------- 快捷指令（后端不可用时的本地兜底） ----------
const FALLBACK_QUICK_COMMANDS = [
  '今天生产情况怎么样？',
  '查询在制工单',
  '查询库存水平',
  '最近有哪些不良品？',
  '设备运行状态如何？',
  '跑一次高温加班合规仿真',
  '最近的仿真审计记录',
]

// ---------- 智能体调度 ----------
interface ChatAgent {
  key: string
  name: string
  description: string
  capabilities?: string[]
  inputs?: string[]
  outputs?: string[]
  boundaries?: string[]
}

// ---------- 快速命令（后端 CRUD，新增后自动归类智能体） ----------
interface QuickCommand {
  id: string
  command_text: string
  agent_key?: string | null
  agent_name?: string | null
  is_preset: boolean
}

// ---------- IM 聊天消息 ----------
interface IMMsg {
  id: string
  from: 'me' | 'them' | 'system'
  content: string
  time: string
  isCall?: boolean  // 工单呼叫卡片
  callMeta?: { call_type: string; station: string; priority: string; task_code?: string }
}

interface IMGroup {
  id: string
  factory_id: string
  name: string
  description?: string
  group_type?: string
  org_node_id?: string
  owner_id?: string
  avatar_color?: string
  message_count?: number
  last_message_at?: string
}

interface IMGroupMsg {
  id: string
  group_id: string
  sender_id: string
  sender_name: string
  msg_type: string
  content: string
  created_at?: string
}

interface InfoItem {
  id: string
  source: 'im' | 'system' | 'ai'
  title: string
  content: string
  time: string
  unread: boolean
  sender?: string
  backendId?: string
}

// 工单呼叫类型（与 QuickRequest 页一致，落到 TMS call_request）
const IM_CALL_TYPES = [
  { value: 'equipment_fault', label: '设备故障', icon: <ToolOutlined />, color: '#f5222d' },
  { value: 'material_call', label: '物料呼叫', icon: <AlertOutlined />, color: '#fa8c16' },
  { value: 'quality_call', label: '品质呼叫', icon: <ExperimentOutlined />, color: '#722ed1' },
  { value: 'support_call', label: '支援呼叫', icon: <PhoneOutlined />, color: '#1890ff' },
]

const now = () => new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
const createId = (prefix: string) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
const quotePreview = (content: string) => content.replace(/\s+/g, ' ').trim().slice(0, 120)

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
    { id: createId('welcome'), role: 'assistant', content: '你好！我是 EngHub MES 智能助手，可以回答生产工单、报工、检验、不良品、库存、计划等问题。', time: now() },
  ])
  const [input, setInput] = useState('')
  const [replyingTo, setReplyingTo] = useState<ChatMsg | null>(null)
  const [shareMessage, setShareMessage] = useState<ChatMsg | null>(null)
  const [shareTarget, setShareTarget] = useState('info')
  const [loading, setLoading] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  // 待发送附件（先调 /files/upload 拿 file_id，再随消息提交）
  const [pendingAttachments, setPendingAttachments] = useState<MsgAttachment[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // 可用工作流清单（从 /chat/tools 拉取，供快捷指令区展示）
  const [workflows, setWorkflows] = useState<{ name: string; label: string; needs_params: boolean }[]>([])
  // 智能体调度：可选 agent 列表 + 当前选中（auto = 由模型自动调度）
  const [agents, setAgents] = useState<ChatAgent[]>([])
  const [selectedAgent, setSelectedAgent] = useState<string>('auto')
  // 快速命令（后端 CRUD）
  const [quickCommands, setQuickCommands] = useState<QuickCommand[]>([])
  const [cmdModalOpen, setCmdModalOpen] = useState(false)
  const [newCmdText, setNewCmdText] = useState('')
  const [newCmdAgent, setNewCmdAgent] = useState<string>('auto')
  const [cmdSaving, setCmdSaving] = useState(false)
  const [editingCmdId, setEditingCmdId] = useState<string | null>(null)
  const [editCmdText, setEditCmdText] = useState('')
  const [editCmdAgent, setEditCmdAgent] = useState<string>('auto')
  // IM 未读
  const [unread, setUnread] = useState<Record<string, number>>({ c2: 1, c3: 2 })
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null)
  const [selectedGroup, setSelectedGroup] = useState<IMGroup | null>(null)
  const [infoOpen, setInfoOpen] = useState(false)
  const [infoItems, setInfoItems] = useState<InfoItem[]>([])
  const [infoLoading, setInfoLoading] = useState(false)
  const [groups, setGroups] = useState<IMGroup[]>([])
  const [groupsLoading, setGroupsLoading] = useState(false)
  const [groupModalOpen, setGroupModalOpen] = useState(false)
  const [groupForm] = Form.useForm()
  // IM 聊天
  const [imMessages, setImMessages] = useState<Record<string, IMMsg[]>>({})
  const [imInput, setImInput] = useState('')
  const [imSending, setImSending] = useState(false)
  const [groupMessages, setGroupMessages] = useState<Record<string, IMGroupMsg[]>>({})
  const [groupInput, setGroupInput] = useState('')
  const [groupSending, setGroupSending] = useState(false)
  const imListRef = useRef<HTMLDivElement>(null)
  // 工单呼叫弹窗
  const [callModalOpen, setCallModalOpen] = useState(false)
  const [callType, setCallType] = useState('equipment_fault')
  const [callForm] = Form.useForm()
  const [callSubmitting, setCallSubmitting] = useState(false)
  // 电子表格弹窗（chatbot 查询结果 → Univer 在线表格）
  const [sheetTable, setSheetTable] = useState<TableData | null>(null)

  const user = getStoredUser()
  const activeFactoryId = () => localStorage.getItem('active_factory_id') || user?.factory_id || 'FAC_ELEC_DEMO_2026'
  const [commanderOn, setCommanderOn] = useState(false)
  const [commanderBusy, setCommanderBusy] = useState(false)

  const refreshCommanderStatus = useCallback(async () => {
    try {
      const res: any = await api.get('/api/v1/commander/my-status')
      setCommanderOn(!!res?.enabled)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { refreshCommanderStatus() }, [refreshCommanderStatus])

  const toggleCommander = useCallback(async () => {
    setCommanderBusy(true)
    try {
      const res: any = await api.post('/api/v1/commander/toggle', {
        enabled: !commanderOn,
        factory_id: activeFactoryId(),
      })
      setCommanderOn(!!res?.enabled)
      message.success(res?.message || (res?.enabled ? '指挥官已开启' : '指挥官已关闭'))
      if (res?.enabled) {
        const sensingId = `cmd-sensing-${Date.now()}`
        setMessages((prev) => [...prev, {
          id: sensingId,
          role: 'assistant',
          content: '🎖️ 工厂指挥官已开启！\n\n📡 正在执行首轮态势感知…\n• 读取您的任务表与在制工单\n• 扫描产能负荷与工位利用率\n• 检查设备状态、物料库存、交期与质量态势',
          time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
        }])
        try {
          const cycle: any = await api.post('/api/v1/commander/cycle', {
            factory_id: activeFactoryId(),
            auto_execute: true,
          })
          const st = cycle?.state || {}
          const orders = st.orders || {}
          const capacity = st.capacity || {}
          const equipment = st.equipment || {}
          const material = st.material || {}
          const delivery = st.delivery || {}
          const quality = st.quality || {}
          const modeMap: Record<string, string> = {
            surplus: '🟢 订单充足（挑单/延交低优）',
            normal: '🔵 产销平衡（维持节奏）',
            deficit: '🟡 订单欠缺（主动接单补产）',
          }
          const lines = [
            '✅ 首轮态势感知完成，已接管您的工作范围：',
            '',
            '📋 任务表读取',
            `   在制工单 ${orders.active ?? '-'} 单（待排 ${orders.pending ?? '-'} / 执行中 ${orders.in_progress ?? '-'}），逾期 ${orders.overdue ?? 0} 单，7天内到期 ${orders.due_7d ?? 0} 单`,
            '🏭 产能负荷',
            `   工位利用 ${capacity.utilization ?? '-'}（繁忙 ${capacity.stations ?? '-'}），负荷率 ${orders.load_ratio != null ? Math.round(orders.load_ratio * 100) + '%' : '-'}`,
            '🔧 设备状态',
            `   运行 ${equipment.running ?? '-'} / 维修 ${equipment.maintenance ?? '-'} / 故障 ${equipment.broken ?? '-'}（共 ${equipment.total ?? '-'} 台）`,
            '📦 物料 & 🚚 交期 & ✅ 质量',
            `   缺料 ${material.low_stock ?? 0} 项｜交期达成 ${delivery.on_time_rate ?? '-'}｜不良率 ${quality.defect_rate ?? '-'}`,
            '',
            `🎯 订单模式判定：${modeMap[cycle?.order_mode] || cycle?.order_mode}`,
          ]
          const decisions = cycle?.decisions || []
          if (decisions.length) {
            lines.push('', `📌 本轮自主决策（${decisions.length} 项）：`)
            decisions.forEach((d: any, i: number) => {
              lines.push(`   ${d.executed ? '✅' : '📋'} ${i + 1}. [${d.priority}] ${d.reason}`)
              if (d.result?.message) lines.push(`      → ${d.result.message}`)
            })
          }
          const alerts = cycle?.alerts || []
          if (alerts.length) {
            lines.push('', '⚠️ 预警：')
            alerts.forEach((a: string) => lines.push(`   • ${a}`))
          }
          const nextActions = cycle?.next_actions || []
          if (nextActions.length) {
            lines.push('', '🔜 下一步：')
            nextActions.forEach((a: string) => lines.push(`   • ${a}`))
          }
          lines.push('', `⏱️ 感知+决策耗时 ${Math.round(cycle?.duration_ms ?? 0)}ms｜后续将定期自动巡检，重大决策会先请示您。`)
          setMessages((prev) => prev.map((m) => m.id === sensingId ? { ...m, content: lines.join('\n') } : m))
        } catch {
          setMessages((prev) => prev.map((m) => m.id === sensingId ? { ...m, content: '🎖️ 指挥官已开启，但首轮感知循环调用失败，稍后会自动重试。' } : m))
        }
      }
    } catch {
      message.error('指挥官开关操作失败')
    } finally {
      setCommanderBusy(false)
    }
  }, [commanderOn])

  const infoStorageKey = `enghub-info:${user?.username || 'anonymous'}:${localStorage.getItem('active_factory_id') || 'default'}`

  const addInfoItem = useCallback((item: InfoItem) => {
    setInfoItems(prev => [item, ...prev.filter(existing => existing.id !== item.id)].slice(0, 100))
  }, [])

  const fetchSystemInfo = useCallback(async () => {
    const factoryId = localStorage.getItem('active_factory_id')
    if (!factoryId) return
    setInfoLoading(true)
    try {
      const res: any = await api.get('/api/v1/notifications', {
        params: { factory_id: factoryId, limit: 50 },
      })
      const rows = Array.isArray(res) ? res : (res.items || res.notifications || [])
      const systemItems: InfoItem[] = rows.map((item: any) => ({
        id: `system-${item.id}`,
        backendId: item.id,
        source: item.source_type === 'ai' ? 'ai' : 'system',
        title: item.title || '系统信息',
        content: item.content || '',
        time: item.created_at
          ? new Date(item.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
          : now(),
        unread: !item.is_read,
        sender: item.source_type === 'ai' ? 'AI 助手' : '系统',
      }))
      setInfoItems(prev => {
        const localItems = prev.filter(item => !item.backendId)
        return [...systemItems, ...localItems].slice(0, 100)
      })
    } catch {
      // 信息模块仍可使用本地 IM 和 AI 分享记录。
    } finally {
      setInfoLoading(false)
    }
  }, [])

  const fetchGroups = useCallback(async () => {
    const factoryId = activeFactoryId()
    setGroupsLoading(true)
    try {
      const res: any = await api.get('/api/v1/collaboration/im/groups', {
        params: { factory_id: factoryId },
      })
      setGroups(res.groups || [])
    } catch {
      setGroups([])
    } finally {
      setGroupsLoading(false)
    }
  }, [user?.factory_id])

  const fetchGroupMessages = useCallback(async (groupId: string) => {
    try {
      const res: any = await api.get(`/api/v1/collaboration/im/groups/${groupId}/messages`)
      setGroupMessages(prev => ({ ...prev, [groupId]: res.messages || [] }))
    } catch {
      setGroupMessages(prev => ({ ...prev, [groupId]: prev[groupId] || [] }))
    }
  }, [])

  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(infoStorageKey) || '[]')
      if (Array.isArray(stored)) setInfoItems(stored)
    } catch {
      localStorage.removeItem(infoStorageKey)
    }
    fetchSystemInfo()
    const timer = window.setInterval(fetchSystemInfo, 30000)
    return () => window.clearInterval(timer)
  }, [fetchSystemInfo, infoStorageKey])

  useEffect(() => {
    const localItems = infoItems.filter(item => !item.backendId)
    localStorage.setItem(infoStorageKey, JSON.stringify(localItems))
  }, [infoItems, infoStorageKey])

  useEffect(() => {
    if (open || tab === 'im') fetchGroups()
  }, [open, tab, fetchGroups])

  // 自动滚动到底部
  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [messages, loading])

  // 拉取可用工作流（仅展示无需参数的确定性流程，点击即触发）
  useEffect(() => {
    api.get('/api/v1/chat/tools')
      .then((res: any) => setWorkflows((res.workflows || []).filter((w: any) => !w.needs_params)))
      .catch(() => { /* 网关/后端未就绪时不展示工作流快捷指令 */ })
  }, [])

  // 拉取可调度智能体 + 快速命令
  const fetchQuickCommands = useCallback(async () => {
    try {
      const res: any = await api.get('/api/v1/chat/quick-commands')
      setQuickCommands(res.commands || [])
    } catch {
      // 后端不可用时降级为本地预设命令
      setQuickCommands(FALLBACK_QUICK_COMMANDS.map((c, i) => ({ id: `local-${i}`, command_text: c, is_preset: true })))
    }
  }, [])
  useEffect(() => {
    api.get('/api/v1/chat/agents')
      .then((res: any) => setAgents(res.agents || []))
      .catch(() => { /* 智能体列表不可用时隐藏选择器 */ })
    fetchQuickCommands()
  }, [fetchQuickCommands])

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

  // ---------- 发送消息（SSE 流式输出） ----------
  // agentKeyOverride：快速命令自带的归类智能体，优先于顶部选择器
  const sendMessage = async (preset?: string, agentKeyOverride?: string) => {
    const text = (preset ?? input).trim()
    if (loading) return
    if (!text && pendingAttachments.length === 0) return
    const atts = [...pendingAttachments]
    const quote = replyingTo
      ? { id: replyingTo.id, role: replyingTo.role, content: quotePreview(replyingTo.content) }
      : undefined
    setInput('')
    setReplyingTo(null)
    setPendingAttachments([])
    const userMsg: ChatMsg = { id: createId('user'), role: 'user', content: text, time: now(), attachments: atts, quote }
    const history = [...messages, userMsg]
    setMessages(history)
    setLoading(true)

    // 占位 assistant 消息，流式填充内容
    const streamMsg: ChatMsg = { id: createId('assistant'), role: 'assistant', content: '', time: now(), actions: [] }
    setMessages(prev => [...prev, streamMsg])

    try {
      const payload: any = {
        messages: history.slice(-10).map(m => ({
          role: m.role,
          content: m.quote
            ? `引用${m.quote.role === 'assistant' ? 'AI 助手' : '用户'}消息：${m.quote.content}\n\n${m.content}`
            : m.content,
        })),
      }
      if (atts.length > 0) {
        payload.attachments = atts.map(a => ({
          file_id: a.file_id,
          kind: a.is_image ? 'image' : 'file',
        }))
      }
      // 智能体调度：快速命令归类 > 选择器指定；auto 不传，由模型自动调度
      const dispatchAgent = agentKeyOverride || (selectedAgent !== 'auto' ? selectedAgent : undefined)
      if (dispatchAgent) payload.agent_key = dispatchAgent
      const token = localStorage.getItem('token')
      const factoryId = localStorage.getItem('active_factory_id')
      const resp = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(factoryId ? { 'X-Factory-Id': factoryId } : {}),
        },
        body: JSON.stringify(payload),
      })
      if (resp.status === 401) {
        logout()
        sessionStorage.setItem('session_expired', '1')
        window.location.href = '/login'
        return
      }
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let accContent = ''
      let accActions: ToolAction[] = []
      let accTables: TableData[] = []
      let degraded = false

      const applyUpdate = () => {
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            id: streamMsg.id,
            role: 'assistant',
            content: accContent,
            time: streamMsg.time,
            degraded,
            actions: accActions.length > 0 ? [...accActions] : [],
            tables: accTables.length > 0 ? [...accTables] : [],
          }
          return updated
        })
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        // 按 SSE 帧分割（以 \n\n 分隔）
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''
        for (const frame of frames) {
          if (!frame.trim()) continue
          let eventType = 'message'
          let dataStr = ''
          for (const line of frame.split('\n')) {
            if (line.startsWith('event: ')) eventType = line.slice(7)
            else if (line.startsWith('data: ')) dataStr += line.slice(6)
          }
          if (!dataStr) continue
          try {
            const data = JSON.parse(dataStr)
            if (eventType === 'delta') {
              accContent += data.content || ''
              applyUpdate()
            } else if (eventType === 'action') {
              accActions = [...accActions, data]
              applyUpdate()
            } else if (eventType === 'table') {
              accTables = [...accTables, data as TableData]
              applyUpdate()
            } else if (eventType === 'done') {
              degraded = !!data.degraded
              applyUpdate()
            } else if (eventType === 'error') {
              accContent += data.message || '服务异常'
              degraded = true
              applyUpdate()
            }
          } catch { /* 忽略解析失败的帧 */ }
        }
      }
      // 流结束但无内容
      if (!accContent) {
        accContent = '抱歉，暂时无法回答。'
        applyUpdate()
      }
    } catch {
      setMessages(prev => {
        const updated = [...prev]
        updated[updated.length - 1] = {
          id: streamMsg.id,
          role: 'assistant',
          content: '网络异常，请稍后重试。',
          time: streamMsg.time,
          degraded: true,
        }
        return updated
      })
    } finally {
      setLoading(false)
    }
  }

  // ---------- 快速命令 CRUD ----------
  const addQuickCommand = async () => {
    const text = newCmdText.trim()
    if (!text) return
    setCmdSaving(true)
    try {
      const res: any = await api.post('/api/v1/chat/quick-commands', {
        command_text: text,
        agent_key: newCmdAgent !== 'auto' ? newCmdAgent : undefined,
      })
      message.success(res.agent_name ? `已添加，自动归类到「${res.agent_name}」` : '已添加（通用命令，交由智能体自动处理）')
      setNewCmdText('')
      setNewCmdAgent('auto')
      fetchQuickCommands()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '添加失败')
    } finally {
      setCmdSaving(false)
    }
  }

  const startEditCommand = (cmd: QuickCommand) => {
    setEditingCmdId(cmd.id)
    setEditCmdText(cmd.command_text)
    setEditCmdAgent(cmd.agent_key || 'auto')
  }

  const saveQuickCommand = async () => {
    if (!editingCmdId) return
    const text = editCmdText.trim()
    if (!text) return
    setCmdSaving(true)
    try {
      const res: any = await api.put(`/api/v1/chat/quick-commands/${editingCmdId}`, {
        command_text: text,
        agent_key: editCmdAgent !== 'auto' ? editCmdAgent : undefined,
      })
      message.success(res.agent_name ? `已更新，归类到「${res.agent_name}」` : '已更新')
      setEditingCmdId(null)
      fetchQuickCommands()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '更新失败')
    } finally {
      setCmdSaving(false)
    }
  }

  const removeQuickCommand = async (id: string) => {
    try {
      await api.delete(`/api/v1/chat/quick-commands/${id}`)
      message.success('已删除')
      fetchQuickCommands()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '删除失败')
    }
  }

  // 在弹窗内直接点击快捷命令：以其归类智能体身份发送，并关闭弹窗
  const sendQuickCommand = (cmd: QuickCommand) => {
    if (loading) return
    setCmdModalOpen(false)
    setEditingCmdId(null)
    sendMessage(cmd.command_text, cmd.agent_key || undefined)
  }

  const copyChatMessage = async (chatMessage: ChatMsg) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(chatMessage.content)
      } else {
        const textarea = document.createElement('textarea')
        textarea.value = chatMessage.content
        textarea.style.position = 'fixed'
        textarea.style.opacity = '0'
        document.body.appendChild(textarea)
        textarea.select()
        document.execCommand('copy')
        textarea.remove()
      }
      message.success('消息已复制')
    } catch {
      message.error('复制失败，请检查浏览器权限')
    }
  }

  const shareChatMessage = async () => {
    if (!shareMessage) return
    const content = shareMessage.content.trim()
    if (!content) return
    if (shareTarget === 'info') {
      addInfoItem({
        id: createId('ai'),
        source: 'ai',
        title: 'AI 助手分享',
        content,
        time: now(),
        unread: true,
        sender: user?.full_name || user?.username || '我',
      })
      message.success('已分享到内网信息')
    } else if (shareTarget.startsWith('group:')) {
      const groupId = shareTarget.replace('group:', '')
      const group = groups.find(item => item.id === groupId)
      if (!group) return
      try {
        const res: any = await api.post(`/api/v1/collaboration/im/groups/${groupId}/messages`, {
          content: `[AI 助手分享]\n${content}`,
        })
        setGroupMessages(prev => ({
          ...prev,
          [groupId]: [...(prev[groupId] || []), {
            id: res.id || createId('group-share'),
            group_id: groupId,
            sender_id: user?.username || 'me',
            sender_name: user?.full_name || user?.username || '我',
            msg_type: 'text',
            content: `[AI 助手分享]\n${content}`,
            created_at: new Date().toISOString(),
          }],
        }))
        message.success(`已分享到${group.name}`)
      } catch {
        message.error('分享到群失败')
        return
      }
    } else {
      const contact = FACTORY_CONTACTS.find(item => item.id === shareTarget)
      if (!contact) return
      const shared: IMMsg = {
        id: createId('share'),
        from: 'me',
        content: `[AI 助手分享]\n${content}`,
        time: now(),
      }
      setImMessages(prev => ({
        ...prev,
        [contact.id]: [...(prev[contact.id] || []), shared],
      }))
      message.success(`已分享给${contact.name}`)
    }
    setShareMessage(null)
    setShareTarget('info')
  }

  // ---------- 选择并上传附件 → 拿 file_id 暂存，随下一条消息提交 ----------
  const onPickFiles = () => {
    if (!loading && !uploading) fileInputRef.current?.click()
  }

  const onFilesSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    e.target.value = ''  // 重置，允许重复选择同名文件
    if (files.length === 0) return
    setUploading(true)
    try {
      for (const f of files) {
        const fd = new FormData()
        fd.append('file', f)
        const res: any = await api.post('/api/v1/files/upload', fd, {
          headers: { 'Content-Type': undefined },  // 移除默认 application/json，让浏览器自动设置 multipart/form-data + boundary
        })
        setPendingAttachments(prev => [...prev, {
          file_id: res.id,
          filename: res.filename,
          content_type: res.content_type,
          is_image: res.is_image,
          size: res.size,
        }])
      }
    } catch {
      message.error('附件上传失败')
    } finally {
      setUploading(false)
    }
  }

  // ---------- 下载系统文件（带鉴权 token，导出报告/附件通用） ----------
  const downloadSystemFile = async (fileId: string, filename?: string) => {
    try {
      const token = localStorage.getItem('token')
      const resp = await fetch(`/api/v1/files/${fileId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename || fileId
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch {
      message.error('下载失败（可能无权访问或文件不存在）')
    }
  }

  // ---------- IM 自动滚动 ----------
  useEffect(() => {
    if (imListRef.current) imListRef.current.scrollTop = imListRef.current.scrollHeight
  }, [imMessages, selectedContact, groupMessages, selectedGroup])

  useEffect(() => {
    if (selectedGroup) fetchGroupMessages(selectedGroup.id)
  }, [selectedGroup, fetchGroupMessages])

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
      const replyContent = contact.online
        ? `收到，我是${contact.name}，看到后会尽快处理。如需紧急处理可点下方“工单呼叫”。`
        : '（对方离线，消息已送达，上线后可见）'
      setImMessages(prev => ({
        ...prev,
        [cid]: [...(prev[cid] || []), {
          id: createId('reply'),
          from: 'them',
          content: replyContent,
          time: now(),
        }],
      }))
      addInfoItem({
        id: createId('im'),
        source: 'im',
        title: `${contact.name} 发来消息`,
        content: replyContent,
        time: now(),
        unread: true,
        sender: contact.name,
      })
      setImSending(false)
    }, 900)
  }

  const sendGroupMessage = async () => {
    const text = groupInput.trim()
    if (!text || !selectedGroup || groupSending) return
    const groupId = selectedGroup.id
    setGroupInput('')
    setGroupSending(true)
    try {
      const res: any = await api.post(`/api/v1/collaboration/im/groups/${groupId}/messages`, {
        content: text,
      })
      setGroupMessages(prev => ({
        ...prev,
        [groupId]: [...(prev[groupId] || []), {
          id: res.id || createId('group-msg'),
          group_id: groupId,
          sender_id: user?.username || 'me',
          sender_name: user?.full_name || user?.username || '我',
          msg_type: 'text',
          content: text,
          created_at: new Date().toISOString(),
        }],
      }))
      fetchGroups()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '群消息发送失败')
    } finally {
      setGroupSending(false)
    }
  }

  const createGroup = async () => {
    try {
      const values = await groupForm.validateFields()
      const res: any = await api.post('/api/v1/collaboration/im/groups', {
        factory_id: activeFactoryId(),
        name: values.name,
        description: values.description,
        group_type: values.group_type || 'custom',
      })
      message.success('群已创建')
      setGroupModalOpen(false)
      groupForm.resetFields()
      await fetchGroups()
      if (res?.id) {
        setSelectedContact(null)
        setInfoOpen(false)
        setSelectedGroup({
          id: res.id,
          factory_id: res.factory_id || activeFactoryId(),
          name: res.name || values.name,
          description: values.description,
          group_type: values.group_type || 'custom',
          avatar_color: '#1677ff',
        })
      }
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '创建群失败')
    }
  }

  const markInfoRead = async (item: InfoItem) => {
    setInfoItems(prev => prev.map(existing => existing.id === item.id ? { ...existing, unread: false } : existing))
    if (item.backendId) {
      try {
        await api.put(`/api/v1/notifications/${item.backendId}/read`)
      } catch {
        setInfoItems(prev => prev.map(existing => existing.id === item.id ? { ...existing, unread: true } : existing))
      }
    }
  }

  const markAllInfoRead = async () => {
    setInfoItems(prev => prev.map(item => ({ ...item, unread: false })))
    const factoryId = localStorage.getItem('active_factory_id')
    if (factoryId) {
      try {
        await api.put('/api/v1/notifications/read-all', null, { params: { factory_id: factoryId } })
      } catch {
        fetchSystemInfo()
      }
    }
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
      addInfoItem({
        id: createId('system'),
        source: 'system',
        title: `${ct?.label || '工单'}呼叫已创建`,
        content: `${values.station} · ${selectedContact.name}${taskCode ? ` · ${taskCode}` : ''}`,
        time: now(),
        unread: true,
        sender: '系统',
      })
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

  const infoUnread = infoItems.filter(item => item.unread).length
  const totalUnread = Object.values(unread).reduce((a, b) => a + b, 0) + infoUnread

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
            <Space size={6}>
              <Tooltip title={commanderOn ? '指挥官已开启：AI正在主动接管您的工作（点击关闭）' : '开启工厂指挥官：AI主动接管生产调度（点击开启）'}>
                <Button
                  size="small"
                  loading={commanderBusy}
                  onClick={toggleCommander}
                  style={{
                    borderRadius: 14,
                    fontWeight: 700,
                    fontSize: 11,
                    border: commanderOn ? 'none' : '1px solid rgba(255,255,255,0.6)',
                    background: commanderOn ? 'linear-gradient(135deg, #52c41a, #73d13d)' : 'transparent',
                    color: '#fff',
                    boxShadow: commanderOn ? '0 0 8px rgba(82,196,26,0.6)' : 'none',
                  }}
                >
                  <CrownOutlined style={{ marginRight: 3 }} />
                  {commanderOn ? '指挥官·接管中' : '指挥官'}
                </Button>
              </Tooltip>
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
              { key: 'tasks', label: <span><CarryOutOutlined /> 任务中心</span> },
            ]}
          />

          {/* 内容区（直接 flex 布局，不经过 Tabs content-holder） */}
          <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            {tab === 'ai' && (
              <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
                {/* 消息列表 */}
                <div ref={listRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px 14px' }}>
                      {messages.map((m) => (
                        <div key={m.id} style={{
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
                            {m.quote && (
                              <div style={{
                                marginBottom: 6, padding: '5px 7px', borderLeft: '3px solid currentColor',
                                background: m.role === 'user' ? 'rgba(255,255,255,0.14)' : '#fff',
                                borderRadius: 4, opacity: 0.82, fontSize: 11,
                              }}>
                                <div style={{ fontWeight: 600, marginBottom: 2 }}>
                                  {m.quote.role === 'assistant' ? 'AI 助手' : '用户'}
                                </div>
                                <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {m.quote.content}
                                </div>
                              </div>
                            )}
                            {/* 消息附件（用户上传的图片/文件） */}
                            {m.attachments && m.attachments.length > 0 && (
                              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
                                {m.attachments.map((att, ai) => (
                                  att.is_image ? (
                                    <img
                                      key={ai}
                                      src={`/api/v1/files/${att.file_id}`}
                                      alt={att.filename}
                                      style={{ maxWidth: 120, maxHeight: 120, borderRadius: 6, objectFit: 'cover', border: '1px solid rgba(0,0,0,0.08)' }}
                                    />
                                  ) : (
                                    <div key={ai} style={{
                                      display: 'flex', alignItems: 'center', gap: 4,
                                      background: m.role === 'user' ? 'rgba(255,255,255,0.18)' : '#fafafa',
                                      border: '1px solid rgba(0,0,0,0.08)', borderRadius: 6, padding: '4px 8px', fontSize: 11,
                                    }}>
                                      <FileOutlined /> {att.filename}
                                    </div>
                                  )
                                ))}
                              </div>
                            )}
                            {m.content || (
                              // 流式输出中：内容尚未到达时显示打字动画
                              <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center' }}>
                                <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#999', animation: 'typingBlink 1.2s infinite' }} />
                                <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#999', animation: 'typingBlink 1.2s 0.2s infinite' }} />
                                <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#999', animation: 'typingBlink 1.2s 0.4s infinite' }} />
                              </span>
                            )}
                            {/* AI 已执行的操作 */}
                            {m.role === 'assistant' && m.actions && m.actions.length > 0 && (
                              <div style={{ marginTop: 8, borderTop: '1px dashed #d9d9d9', paddingTop: 6 }}>
                                <Text type="secondary" style={{ fontSize: 11 }}>
                                  <ThunderboltOutlined /> 已执行 {m.actions.length} 个操作
                                </Text>
                                {m.actions.map((a, idx) => {
                                  // 工作流 → 流程卡片（步骤序号 + 每步工具/结果/成功状态），区别于单工具卡片
                                  if (a.tool === 'run_workflow' && a.result && Array.isArray(a.result.steps)) {
                                    const wf = a.result
                                    return (
                                      <div key={idx} style={{
                                        marginTop: 4,
                                        background: '#fff7e6',
                                        border: '1px solid #ffd591',
                                        borderRadius: 6,
                                        padding: '6px 8px',
                                        fontSize: 11,
                                      }}>
                                        <Space size={4}>
                                          {wf.success
                                            ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                                            : <CloseCircleOutlined style={{ color: '#f5222d' }} />}
                                          <Text strong style={{ fontSize: 11 }}>{wf.label || a.label}</Text>
                                          <Tag color="orange" style={{ fontSize: 10, lineHeight: '16px', margin: 0 }}>
                                            工作流 {wf.completed_steps}/{wf.total_steps}
                                          </Tag>
                                        </Space>
                                        <div style={{ marginTop: 4 }}>
                                          {wf.steps.map((s: any, si: number) => (
                                            <div key={si} style={{ display: 'flex', alignItems: 'flex-start', gap: 4, marginTop: 2 }}>
                                              <Text type="secondary" style={{ fontSize: 10, flexShrink: 0, lineHeight: '18px' }}>{si + 1}.</Text>
                                              {s.success
                                                ? <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 11, marginTop: 3 }} />
                                                : <CloseCircleOutlined style={{ color: '#f5222d', fontSize: 11, marginTop: 3 }} />}
                                              <Text style={{ fontSize: 11, lineHeight: '18px' }}>{s.label}</Text>
                                              {s.result && s.result.error && (
                                                <Text type="danger" style={{ fontSize: 10, lineHeight: '18px' }}>：{s.result.error}</Text>
                                              )}
                                            </div>
                                          ))}
                                        </div>
                                      </div>
                                    )
                                  }
                                  // 色标：仿真=紫 / 写操作=绿 / 查询=蓝
                                  const tone = a.is_sim
                                    ? { bg: '#f9f0ff', bd: '#d3adf7', tag: 'purple' as const, text: '仿真' }
                                    : a.is_write
                                      ? { bg: '#f6ffed', bd: '#b7eb8f', tag: 'green' as const, text: '写操作' }
                                      : { bg: '#f0f5ff', bd: '#adc6ff', tag: 'blue' as const, text: '查询' }
                                  return (
                                  <div key={idx} style={{
                                    marginTop: 4,
                                    background: tone.bg,
                                    border: `1px solid ${tone.bd}`,
                                    borderRadius: 6,
                                    padding: '4px 8px',
                                    fontSize: 11,
                                  }}>
                                    <Space size={4}>
                                      {a.success
                                        ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                                        : <CloseCircleOutlined style={{ color: '#f5222d' }} />}
                                      <Text strong style={{ fontSize: 11 }}>{a.label}</Text>
                                      <Tag color={tone.tag} style={{ fontSize: 10, lineHeight: '16px', margin: 0 }}>
                                        {tone.text}
                                      </Tag>
                                    </Space>
                                    {a.result && a.result.error && (
                                      <div style={{ color: '#f5222d', marginTop: 2 }}>{a.result.error}</div>
                                    )}
                                  </div>
                                  )
                                })}
                              </div>
                            )}
                            {m.degraded && m.role === 'assistant' && (
                              <div style={{ marginTop: 4 }}>
                                <Tag color="orange" style={{ fontSize: 10 }}>离线降级模式</Tag>
                              </div>
                            )}
                            {/* AI 生成的文件（导出报告等）→ 可下载卡片 */}
                            {m.role === 'assistant' && m.actions && m.actions.some(a => a.result && a.result.file_id) && (
                              <div style={{ marginTop: 6 }}>
                                {m.actions.filter(a => a.result && a.result.file_id).map((a, fi) => (
                                  <div key={fi}
                                    onClick={() => downloadSystemFile(a.result.file_id, a.result.filename)}
                                    style={{
                                      display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                                      background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 6,
                                      padding: '6px 10px', marginTop: 4,
                                    }}>
                                    <FileOutlined style={{ color: '#52c41a', fontSize: 16 }} />
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                      <div style={{ fontSize: 12, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {a.result.filename || '导出文件'}
                                      </div>
                                      <div style={{ fontSize: 10, color: '#999' }}>
                                        {(a.result.content_type || '')}{a.result.size ? ` · ${a.result.size} 字节` : ''}
                                      </div>
                                    </div>
                                    <DownloadOutlined style={{ color: '#52c41a' }} />
                                  </div>
                                ))}
                              </div>
                            )}
                            {/* 结构化表格（chatbot 查询结果 → 可交互表格 + Univer 电子表格） */}
                            {m.role === 'assistant' && m.tables && m.tables.length > 0 && (
                              <div style={{ marginTop: 8 }}>
                                {m.tables.map((tbl, ti) => (
                                  <div key={ti} style={{
                                    background: '#fff', border: '1px solid #e6f4ff',
                                    borderRadius: 8, overflow: 'hidden', marginTop: ti > 0 ? 8 : 0,
                                    boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
                                  }}>
                                    <div style={{
                                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                      padding: '6px 10px', background: '#f0f7ff', borderBottom: '1px solid #e6f4ff',
                                    }}>
                                      <Space size={4}>
                                        <TableOutlined style={{ color: '#1677ff' }} />
                                        <Text strong style={{ fontSize: 11 }}>{tbl.title}</Text>
                                        <Tag color="blue" style={{ fontSize: 10, lineHeight: '16px', margin: 0 }}>{tbl.rows.length} 行</Tag>
                                      </Space>
                                      <Button
                                        type="link" size="small"
                                        icon={<TableOutlined />}
                                        style={{ fontSize: 11, padding: 0, height: 'auto' }}
                                        onClick={() => setSheetTable(tbl)}
                                      >
                                        在电子表格中打开
                                      </Button>
                                    </div>
                                    <Table
                                      size="small"
                                      dataSource={tbl.rows.map((r, ri) => ({ ...r, _rowKey: ri }))}
                                      rowKey="_rowKey"
                                      columns={tbl.columns.map(c => ({
                                        title: c.label,
                                        dataIndex: c.key,
                                        key: c.key,
                                        ellipsis: true,
                                        render: (v: any) => v === null || v === undefined ? '-' : String(v),
                                      }))}
                                      pagination={tbl.rows.length > 5 ? { pageSize: 5, size: 'small', showTotal: undefined } : false}
                                      scroll={{ x: 'max-content' }}
                                      style={{ fontSize: 11 }}
                                    />
                                  </div>
                                ))}
                              </div>
                            )}
                            {!!m.content && (
                              <div style={{
                                display: 'flex', justifyContent: 'flex-end', gap: 2,
                                marginTop: 5, paddingTop: 4,
                                borderTop: `1px solid ${m.role === 'user' ? 'rgba(255,255,255,0.2)' : '#e8e8e8'}`,
                              }}>
                                <Tooltip title="引用回复">
                                  <Button
                                    type="text" size="small" icon={<CommentOutlined />}
                                    aria-label="引用回复"
                                    onClick={() => setReplyingTo(m)}
                                    style={{ color: m.role === 'user' ? '#fff' : '#666', width: 24, height: 22, padding: 0 }}
                                  />
                                </Tooltip>
                                <Tooltip title="复制">
                                  <Button
                                    type="text" size="small" icon={<CopyOutlined />}
                                    aria-label="复制消息"
                                    onClick={() => copyChatMessage(m)}
                                    style={{ color: m.role === 'user' ? '#fff' : '#666', width: 24, height: 22, padding: 0 }}
                                  />
                                </Tooltip>
                                <Tooltip title="分享">
                                  <Button
                                    type="text" size="small" icon={<ShareAltOutlined />}
                                    aria-label="分享消息"
                                    onClick={() => setShareMessage(m)}
                                    style={{ color: m.role === 'user' ? '#fff' : '#666', width: 24, height: 22, padding: 0 }}
                                  />
                                </Tooltip>
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
                    {/* 智能体调度选择器 */}
                    {agents.length > 0 && (
                      <div style={{ padding: '6px 12px 0', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                        <RobotOutlined style={{ color: '#1677ff', fontSize: 12, flexShrink: 0 }} />
                        <Select
                          size="small"
                          value={selectedAgent}
                          onChange={setSelectedAgent}
                          style={{ width: 170, flexShrink: 0 }}
                          options={[
                            { value: 'auto', label: '智能体（模型自选）' },
                            ...agents.map(a => ({ value: a.key, label: a.name })),
                          ]}
                        />
                        {selectedAgent !== 'auto' && (
                          <>
                            <Text type="secondary" style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {agents.find(a => a.key === selectedAgent)?.description}
                            </Text>
                            <Popover
                              placement="topLeft"
                              title={`${agents.find(a => a.key === selectedAgent)?.name || '智能体'}职责说明`}
                              content={(() => {
                                const agent = agents.find(a => a.key === selectedAgent)
                                if (!agent) return null
                                return (
                                  <div style={{ width: 300, fontSize: 12 }}>
                                    <div style={{ marginBottom: 6 }}><Text strong>能做什么：</Text>{(agent.capabilities || []).join('、') || agent.description}</div>
                                    <div style={{ marginBottom: 6 }}><Text strong>输入：</Text>{(agent.inputs || []).join('、') || '按当前会话上下文'}</div>
                                    <div style={{ marginBottom: 6 }}><Text strong>输出：</Text>{(agent.outputs || []).join('、') || '结构化处理结果'}</div>
                                    <div><Text strong>边界：</Text>{(agent.boundaries || []).join('；') || '超出职责时升级人工'}</div>
                                  </div>
                                )
                              })()}
                            >
                              <Button type="text" size="small" icon={<InfoCircleOutlined />} aria-label="查看智能体职责" />
                            </Popover>
                          </>
                        )}
                      </div>
                    )}
                    {/* 快捷指令区：仅保留工作流触发 + 快捷命令入口，快捷命令本体收进弹窗 */}
                    <div style={{ padding: '6px 12px 0', flexShrink: 0, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {/* 可用工作流（橙色区分，点击即触发确定性流程） */}
                      {workflows.map(wf => (
                        <Tag
                          key={wf.name}
                          color="orange"
                          style={{ cursor: loading ? 'not-allowed' : 'pointer', fontSize: 11, borderRadius: 12, padding: '1px 8px', margin: 0 }}
                          onClick={() => !loading && sendMessage(wf.label)}
                        >
                          <ThunderboltOutlined /> {wf.label}
                        </Tag>
                      ))}
                      {/* 快捷命令入口：点击打开弹窗，在弹窗内直接发送给智能体 */}
                      <Tag
                        icon={<UnorderedListOutlined />}
                        color="processing"
                        style={{ cursor: 'pointer', fontSize: 11, borderRadius: 12, padding: '1px 8px', margin: 0 }}
                        onClick={() => setCmdModalOpen(true)}
                      >
                        快捷命令
                      </Tag>
                    </div>
                    {/* 快捷命令弹窗：点击命令即直接发送；新增后立即自动归类到对应智能体 */}
                    <Modal
                      title="快捷命令"
                      open={cmdModalOpen}
                      onCancel={() => { setCmdModalOpen(false); setEditingCmdId(null) }}
                      footer={null}
                      width={560}
                    >
                      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
                        <Input
                          placeholder="输入新命令语句，如：检查本周交期风险"
                          value={newCmdText}
                          onChange={e => setNewCmdText(e.target.value)}
                          onPressEnter={addQuickCommand}
                        />
                        <Select
                          value={newCmdAgent}
                          onChange={setNewCmdAgent}
                          style={{ width: 150 }}
                          options={[
                            { value: 'auto', label: '自动归类' },
                            ...agents.map(a => ({ value: a.key, label: a.name })),
                          ]}
                        />
                        <Button type="primary" icon={<PlusOutlined />} loading={cmdSaving} onClick={addQuickCommand}>添加</Button>
                      </Space.Compact>
                      <List
                        size="small"
                        dataSource={quickCommands}
                        style={{ maxHeight: 320, overflowY: 'auto' }}
                        renderItem={cmd => (
                          <List.Item
                            actions={cmd.is_preset ? [
                              <Tag key="preset" style={{ fontSize: 10 }}>预置</Tag>,
                            ] : editingCmdId === cmd.id ? [
                              <Button key="save" type="link" size="small" loading={cmdSaving} onClick={saveQuickCommand}>保存</Button>,
                              <Button key="cancel" type="link" size="small" onClick={() => setEditingCmdId(null)}>取消</Button>,
                            ] : [
                              <Button key="edit" type="text" size="small" icon={<EditOutlined />} aria-label="编辑命令" onClick={() => startEditCommand(cmd)} />,
                              <Popconfirm key="del" title="删除该命令？" onConfirm={() => removeQuickCommand(cmd.id)}>
                                <Button type="text" size="small" danger icon={<DeleteOutlined />} aria-label="删除命令" />
                              </Popconfirm>,
                            ]}
                          >
                            {editingCmdId === cmd.id ? (
                              <Space.Compact style={{ width: '100%' }}>
                                <Input size="small" value={editCmdText} onChange={e => setEditCmdText(e.target.value)} onPressEnter={saveQuickCommand} />
                                <Select
                                  size="small"
                                  value={editCmdAgent}
                                  onChange={setEditCmdAgent}
                                  style={{ width: 140 }}
                                  options={[
                                    { value: 'auto', label: '自动归类' },
                                    ...agents.map(a => ({ value: a.key, label: a.name })),
                                  ]}
                                />
                              </Space.Compact>
                            ) : (
                              <Space size={6}>
                                <Tooltip title={cmd.agent_name ? `点击发送，由「${cmd.agent_name}」处理` : '点击发送给智能体'}>
                                  <Text
                                    style={{ fontSize: 13, cursor: loading ? 'not-allowed' : 'pointer', color: '#1677ff' }}
                                    onClick={() => sendQuickCommand(cmd)}
                                  >{cmd.command_text}</Text>
                                </Tooltip>
                                {cmd.agent_name
                                  ? <Tag color="geekblue" style={{ fontSize: 10 }}>{cmd.agent_name}</Tag>
                                  : <Tag style={{ fontSize: 10 }}>智能体</Tag>}
                              </Space>
                            )}
                          </List.Item>
                        )}
                      />
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        点击命令即可直接发送给对应智能体；新增命令后系统会自动归类到对应智能体。
                      </Text>
                    </Modal>
                    {/* 输入区 */}
                    <div style={{ padding: '8px 12px', borderTop: '1px solid #f0f0f0', flexShrink: 0 }}>
                      {replyingTo && (
                        <div style={{
                          display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
                          padding: '6px 8px', background: '#f5f8ff', borderLeft: '3px solid #1677ff',
                        }}>
                          <CommentOutlined style={{ color: '#1677ff' }} />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <Text strong style={{ fontSize: 11 }}>
                              引用{replyingTo.role === 'assistant' ? ' AI 助手' : '用户'}消息
                            </Text>
                            <div style={{ fontSize: 11, color: '#666', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {quotePreview(replyingTo.content)}
                            </div>
                          </div>
                          <Button type="text" size="small" icon={<CloseOutlined />} aria-label="取消引用" onClick={() => setReplyingTo(null)} />
                        </div>
                      )}
                      {/* 待发送附件预览（上传后、发送前可移除） */}
                      {pendingAttachments.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
                          {pendingAttachments.map((att, i) => (
                            <div key={att.file_id} style={{
                              position: 'relative', display: 'flex', alignItems: 'center',
                              border: '1px solid #d9d9d9', borderRadius: 6, overflow: 'hidden', background: '#fafafa',
                            }}>
                              {att.is_image ? (
                                <img src={`/api/v1/files/${att.file_id}`} alt={att.filename}
                                  style={{ width: 40, height: 40, objectFit: 'cover' }} />
                              ) : (
                                <span style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 8px', fontSize: 11, maxWidth: 140 }}>
                                  <FileOutlined /> <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{att.filename}</span>
                                </span>
                              )}
                              <CloseOutlined
                                onClick={() => setPendingAttachments(prev => prev.filter((_, idx) => idx !== i))}
                                style={{
                                  position: 'absolute', top: 2, right: 2, fontSize: 10, cursor: 'pointer',
                                  color: '#fff', background: 'rgba(0,0,0,0.5)', borderRadius: '50%', padding: 2,
                                }} />
                            </div>
                          ))}
                        </div>
                      )}
                      <Space.Compact style={{ width: '100%' }}>
                        <Button
                          icon={<PaperClipOutlined />}
                          onClick={onPickFiles}
                          loading={uploading}
                          title="上传图片/文件"
                          style={{ borderRadius: '8px 0 0 8px' }}
                        />
                        <TextArea
                          value={input}
                          onChange={e => setInput(e.target.value)}
                          onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); sendMessage() } }}
                          placeholder="输入问题，Enter 发送..."
                          autoSize={{ minRows: 1, maxRows: 3 }}
                          style={{ borderRadius: 0 }}
                        />
                        <Button
                          type="primary"
                          icon={<SendOutlined />}
                          onClick={() => sendMessage()}
                          loading={loading}
                          style={{ borderRadius: '0 8px 8px 0', height: 'auto' }}
                        />
                      </Space.Compact>
                      {/* 隐藏的文件选择框（图片+文件多选） */}
                      <input
                        ref={fileInputRef}
                        type="file"
                        multiple
                        style={{ display: 'none' }}
                        onChange={onFilesSelected}
                      />
                    </div>
              </div>
            )}
            {tab === 'im' && (
                  <div style={{ flex: 1, minHeight: 0, overflowY: selectedContact || infoOpen ? 'hidden' : 'auto', padding: selectedContact || infoOpen ? 0 : '8px 0' }}>
                    {infoOpen ? (
                      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                        <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: 8 }}>
                          <Button type="text" size="small" icon={<ArrowLeftOutlined />} aria-label="返回内网列表" onClick={() => setInfoOpen(false)} />
                          <Avatar size={32} style={{ background: '#13c2c2' }} icon={<InboxOutlined />} />
                          <div style={{ flex: 1 }}>
                            <Text strong>信息</Text>
                            <div><Text type="secondary" style={{ fontSize: 11 }}>IM、系统与 AI 助手信息</Text></div>
                          </div>
                          <Tooltip title="刷新">
                            <Button type="text" size="small" icon={<ReloadOutlined />} loading={infoLoading} onClick={fetchSystemInfo} />
                          </Tooltip>
                          <Tooltip title="全部已读">
                            <Button type="text" size="small" icon={<CheckOutlined />} disabled={infoUnread === 0} onClick={markAllInfoRead} />
                          </Tooltip>
                        </div>
                        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', background: '#fafafa' }}>
                          {infoItems.length === 0 ? (
                            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无信息" style={{ marginTop: 48 }} />
                          ) : (
                            <List
                              dataSource={infoItems}
                              renderItem={(item) => {
                                const sourceTone = item.source === 'im'
                                  ? { color: 'blue', label: 'IM' }
                                  : item.source === 'ai'
                                    ? { color: 'purple', label: 'AI 助手' }
                                    : { color: 'orange', label: '系统' }
                                return (
                                  <List.Item
                                    onClick={() => item.unread && markInfoRead(item)}
                                    style={{
                                      padding: '10px 14px', cursor: item.unread ? 'pointer' : 'default',
                                      background: item.unread ? '#f0f7ff' : '#fff',
                                      borderLeft: item.unread ? '3px solid #1677ff' : '3px solid transparent',
                                    }}
                                  >
                                    <div style={{ width: '100%', minWidth: 0 }}>
                                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                        <Tag color={sourceTone.color} style={{ margin: 0, fontSize: 10 }}>{sourceTone.label}</Tag>
                                        <Text strong={item.unread} style={{ flex: 1, fontSize: 12 }} ellipsis>{item.title}</Text>
                                        {item.unread && <Badge status="processing" />}
                                      </div>
                                      <div style={{ marginTop: 5, fontSize: 12, color: '#555', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                        {item.content}
                                      </div>
                                      <div style={{ marginTop: 4, display: 'flex', justifyContent: 'space-between', color: '#999', fontSize: 10 }}>
                                        <span>{item.sender || sourceTone.label}</span>
                                        <span>{item.time}</span>
                                      </div>
                                    </div>
                                  </List.Item>
                                )
                              }}
                            />
                          )}
                        </div>
                      </div>
                    ) : selectedGroup ? (
                      /* 群聊天 */
                      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
                        <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                          <Button type="text" size="small" onClick={() => setSelectedGroup(null)}>←</Button>
                          <Avatar size={32} style={{ background: selectedGroup.avatar_color || '#1677ff' }} icon={<TeamOutlined />} />
                          <div style={{ flex: 1, lineHeight: 1.3, minWidth: 0 }}>
                            <div>
                              <Text strong>{selectedGroup.name}</Text>
                              <Tag color="blue" style={{ marginLeft: 6, fontSize: 10 }}>{selectedGroup.group_type || 'group'}</Tag>
                            </div>
                            <Text type="secondary" style={{ fontSize: 11 }} ellipsis>{selectedGroup.description || '群协同消息'}</Text>
                          </div>
                          <Tooltip title="刷新消息">
                            <Button type="text" size="small" icon={<ReloadOutlined />} onClick={() => fetchGroupMessages(selectedGroup.id)} />
                          </Tooltip>
                        </div>
                        <div ref={imListRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '10px 12px', background: '#fafafa' }}>
                          {(groupMessages[selectedGroup.id] || []).length === 0 && (
                            <div style={{ textAlign: 'center', color: '#999', fontSize: 12, marginTop: 24 }}>
                              暂无群消息
                            </div>
                          )}
                          {(groupMessages[selectedGroup.id] || []).map(m => {
                            const mine = m.sender_id === user?.username
                            const systemMsg = m.sender_id === 'system' || m.msg_type === 'system'
                            return (
                              <div key={m.id} style={{ marginBottom: 10, display: 'flex', justifyContent: mine ? 'flex-end' : 'flex-start' }}>
                                {!mine && (
                                  <Avatar size={26} style={{ background: systemMsg ? '#13c2c2' : selectedGroup.avatar_color || '#1677ff', marginRight: 6, flexShrink: 0 }} icon={systemMsg ? <InboxOutlined /> : <TeamOutlined />} />
                                )}
                                <div style={{
                                  maxWidth: '76%',
                                  padding: '7px 10px',
                                  borderRadius: 10,
                                  background: mine ? '#1677ff' : systemMsg ? '#fff7e6' : '#fff',
                                  color: mine ? '#fff' : '#333',
                                  fontSize: 12,
                                  lineHeight: 1.5,
                                  whiteSpace: 'pre-wrap',
                                  wordBreak: 'break-word',
                                  border: mine ? 'none' : systemMsg ? '1px solid #ffd591' : '1px solid #eee',
                                }}>
                                  {!mine && <div style={{ fontSize: 10, color: systemMsg ? '#fa8c16' : '#999', marginBottom: 2 }}>{m.sender_name || m.sender_id}</div>}
                                  {m.content}
                                  <div style={{ fontSize: 10, color: mine ? 'rgba(255,255,255,0.7)' : '#999', marginTop: 3, textAlign: 'right' }}>
                                    {m.created_at ? new Date(m.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : now()}
                                  </div>
                                </div>
                              </div>
                            )
                          })}
                          {groupSending && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <Avatar size={26} style={{ background: selectedGroup.avatar_color || '#1677ff' }} icon={<TeamOutlined />} />
                              <Spin size="small" />
                            </div>
                          )}
                        </div>
                        <div style={{ padding: '6px 12px', borderTop: '1px solid #f0f0f0', flexShrink: 0 }}>
                          <Text type="secondary" style={{ fontSize: 11 }}>群协同（Chatbot 任务、异常、RCC 决策可同步到群）</Text>
                        </div>
                        <div style={{ padding: '8px 12px', borderTop: '1px solid #f0f0f0', flexShrink: 0 }}>
                          <Space.Compact style={{ width: '100%' }}>
                            <Input
                              value={groupInput}
                              onChange={e => setGroupInput(e.target.value)}
                              onPressEnter={sendGroupMessage}
                              placeholder={`发到 ${selectedGroup.name}...`}
                            />
                            <Button type="primary" icon={<SendOutlined />} loading={groupSending} onClick={sendGroupMessage} />
                          </Space.Compact>
                        </div>
                      </div>
                    ) : selectedContact ? (
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
                      <>
                        <List.Item
                          style={{ padding: '10px 16px', cursor: 'pointer', borderBottom: '1px solid #f0f0f0' }}
                          onClick={() => setInfoOpen(true)}
                        >
                          <List.Item.Meta
                            avatar={<Avatar style={{ background: '#13c2c2' }} icon={<InboxOutlined />} />}
                            title={<Text strong>信息</Text>}
                            description={<Text type="secondary" style={{ fontSize: 12 }}>接收 IM、系统和 AI 助手信息</Text>}
                          />
                          {infoUnread > 0 && <Badge count={infoUnread} />}
                        </List.Item>
                        <div style={{ padding: '8px 16px 4px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>群组</Text>
                          <Button type="text" size="small" icon={<PlusOutlined />} onClick={() => setGroupModalOpen(true)}>建群</Button>
                        </div>
                        <Spin spinning={groupsLoading}>
                          <List
                            dataSource={groups}
                            locale={{ emptyText: '暂无群组' }}
                            renderItem={(g) => (
                              <List.Item
                                style={{ padding: '8px 16px', cursor: 'pointer' }}
                                onClick={() => {
                                  setSelectedGroup(g)
                                  setSelectedContact(null)
                                  setInfoOpen(false)
                                }}
                              >
                                <List.Item.Meta
                                  avatar={<Avatar style={{ background: g.avatar_color || '#1677ff' }} icon={<TeamOutlined />} />}
                                  title={
                                    <span>
                                      {g.name}
                                      <Tag color="geekblue" style={{ marginLeft: 6, fontSize: 10 }}>{g.group_type || 'group'}</Tag>
                                    </span>
                                  }
                                  description={
                                    <span style={{ fontSize: 12 }}>
                                      {g.description || '群协同'}
                                      {(g.message_count || 0) > 0 && <Tag color="blue" style={{ marginLeft: 6, fontSize: 10 }}>{g.message_count} 消息</Tag>}
                                    </span>
                                  }
                                />
                              </List.Item>
                            )}
                          />
                        </Spin>
                        <div style={{ padding: '8px 16px 4px' }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>联系人</Text>
                        </div>
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
                      </>
                    )}
                  </div>
            )}
            {tab === 'tasks' && (
              <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
                <TaskCenter />
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

      <Modal
        title={<Space><ShareAltOutlined /><span>分享消息</span></Space>}
        open={!!shareMessage}
        onCancel={() => { setShareMessage(null); setShareTarget('info') }}
        onOk={shareChatMessage}
        okText="分享"
        cancelText="取消"
        width={400}
      >
        <Text type="secondary" style={{ fontSize: 12 }}>分享到</Text>
        <Select
          value={shareTarget}
          onChange={setShareTarget}
          style={{ width: '100%', marginTop: 6 }}
          options={[
            { value: 'info', label: '内网信息' },
            ...groups.map(group => ({
              value: `group:${group.id}`,
              label: `${group.name} · 群`,
            })),
            ...FACTORY_CONTACTS.map(contact => ({
              value: contact.id,
              label: `${contact.name} · ${contact.role}`,
            })),
          ]}
        />
        <div style={{
          marginTop: 12, padding: '8px 10px', maxHeight: 160, overflowY: 'auto',
          background: '#f5f5f5', border: '1px solid #e8e8e8', borderRadius: 6,
          whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12,
        }}>
          {shareMessage?.content}
        </div>
      </Modal>

      <Modal
        title={<Space><TeamOutlined /><span>创建群</span></Space>}
        open={groupModalOpen}
        onCancel={() => setGroupModalOpen(false)}
        onOk={createGroup}
        okText="创建"
        cancelText="取消"
        width={420}
        destroyOnClose
      >
        <Form form={groupForm} layout="vertical">
          <Form.Item name="name" label="群名称" rules={[{ required: true, message: '请输入群名称' }]}>
            <Input placeholder="如：模具试产攻关群" />
          </Form.Item>
          <Form.Item name="group_type" label="群类型" initialValue="custom">
            <Select
              options={[
                { value: 'custom', label: '自定义' },
                { value: 'rcc', label: 'RCC指挥' },
                { value: 'exception', label: '异常处理' },
                { value: 'quality', label: '质量联动' },
                { value: 'ie', label: 'IE改善' },
              ]}
            />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea rows={3} placeholder="说明这个群负责的流程、异常或项目" />
          </Form.Item>
        </Form>
      </Modal>

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

      {/* 电子表格弹窗（chatbot 查询结果 → Univer 类 Excel 在线表格，支持公式/筛选/复制粘贴） */}
      <Modal
        title={
          <Space>
            <TableOutlined style={{ color: '#1677ff' }} />
            <span>{sheetTable?.title || '电子表格'}</span>
            <Tag color="blue" style={{ fontSize: 10 }}>Univer 在线表格</Tag>
          </Space>
        }
        open={!!sheetTable}
        onCancel={() => setSheetTable(null)}
        footer={
          <Button onClick={() => setSheetTable(null)}>关闭</Button>
        }
        width="85vw"
        style={{ top: 32 }}
        destroyOnClose
      >
        {sheetTable && (
          <Suspense fallback={<div style={{ textAlign: 'center', padding: 48 }}><Spin tip="加载电子表格组件..." /></div>}>
            <SpreadsheetEditor
              headers={sheetTable.columns.map(c => c.label)}
              initialData={sheetTable.rows.map(r => sheetTable.columns.map(c => r[c.key] ?? ''))}
              height={Math.min(520, Math.max(280, sheetTable.rows.length * 28 + 80))}
              sheetName={sheetTable.title}
            />
          </Suspense>
        )}
      </Modal>
    </>
  )
}
