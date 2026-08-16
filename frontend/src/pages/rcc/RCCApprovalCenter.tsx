/**
 * RCC 审批中心（独立视图，不挤在右栏）
 * 审批队列全量卡片：任务详情/类型/影响/证据/请求方/时间/审批操作
 * 按类型分组：资源分配 / 人力调度 / 设备维修 / 待审批 / 供应商跟催
 */
import { useEffect, useState } from 'react'
import { Tag, Button, Space, Select, Empty, message, Input } from 'antd'
import {
  CheckOutlined, CloseOutlined, RobotOutlined, CarryOutOutlined,
  ThunderboltOutlined, TeamOutlined, ToolOutlined, ApartmentOutlined,
  ClockCircleOutlined, UserOutlined, SearchOutlined,
} from '@ant-design/icons'
import axios from 'axios'

const API = '/api/v1'
const C = {
  bg: '#F4F6F9', surface: '#FFF', border: '#E3E7EE', borderStrong: '#D2D8E2',
  text: '#172033', text2: '#596579', text3: '#93A0B4',
  brand: '#315DAA', brand2: '#214689', brandSoft: '#EAF0FC',
  cyan: '#087F8C', cyanSoft: '#E4F4F4', purple: '#7C4CB2', purpleSoft: '#F1EAF8',
  danger: '#D64545', dangerSoft: '#FBEAEA', warn: '#B36A12', warnSoft: '#FBF0DA',
  success: '#157C4F', successSoft: '#E5F6EE',
}

const TYPE_META: Record<string, { label: string; icon: any; color: string; soft: string }> = {
  resource_allocation: { label: '资源分配', icon: <ApartmentOutlined />, color: C.brand, soft: C.brandSoft },
  supplier_followup: { label: '供应商跟催', icon: <CarryOutOutlined />, color: C.cyan, soft: C.cyanSoft },
  equipment_maintenance: { label: '设备维修', icon: <ToolOutlined />, color: C.purple, soft: C.purpleSoft },
  approval: { label: '待审批', icon: <ClockCircleOutlined />, color: C.warn, soft: C.warnSoft },
  manpower: { label: '人力调度', icon: <TeamOutlined />, color: C.success, soft: C.successSoft },
  data_fix: { label: '数据修复', icon: <RobotOutlined />, color: C.text3, soft: '#F0F2F6' },
  dispatch: { label: '派工', icon: <CarryOutOutlined />, color: C.brand, soft: C.brandSoft },
  scheduling: { label: '排程', icon: <ThunderboltOutlined />, color: C.cyan, soft: C.cyanSoft },
}

export default function RCCApprovalCenter({ onApproved }: { onApproved?: () => void }) {
  const [tasks, setTasks] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [typeFilter, setTypeFilter] = useState('')
  const [query, setQuery] = useState('')
  const [approver, setApprover] = useState('rcc_controller')

  const load = async () => {
    setLoading(true)
    try {
      const r = await axios.get(`${API}/rcc/tasks`, { params: { status: 'pending', page_size: 100 } })
      setTasks(r.data?.items || [])
    } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const approve = async (id: string) => {
    try {
      await axios.post(`${API}/rcc/tasks/${id}/approve`, null, { params: { approver_id: approver, comment: `${approver} 审批通过` } })
      message.success('已批准，关联任务自动解除阻塞')
      load(); onApproved?.()
    } catch (e: any) { message.error(String(e.response?.data?.detail || e.message).slice(0, 60)) }
  }
  const reject = async (id: string) => {
    const reason = prompt('拒绝原因：') || '未说明'
    try {
      await axios.post(`${API}/rcc/tasks/${id}/reject`, null, { params: { approver_id: approver, reason } })
      message.success('已拒绝')
      load(); onApproved?.()
    } catch (e: any) { message.error(String(e.response?.data?.detail || e.message).slice(0, 60)) }
  }

  const filtered = tasks.filter((t: any) => {
    const tm = TYPE_META[t.task_type] || { label: t.task_type }
    if (typeFilter && t.task_type !== typeFilter) return false
    const q = query.toLowerCase()
    return !q || `${t.title} ${t.task_code} ${tm.label}`.toLowerCase().includes(q)
  })
  const types = Array.from(new Set(tasks.map((t: any) => t.task_type)))

  return (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      {/* 审批中心头部 */}
      <div style={{ background: 'linear-gradient(135deg,#F8FAFF,#F5FBFB)', border: '1px solid #DDE7F3', borderRadius: 14, padding: '16px 18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 11, background: 'linear-gradient(135deg,#315DAA,#087F8C)', color: '#fff', display: 'grid', placeItems: 'center', fontSize: 16 }}><CheckOutlined /></div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 850 }}>管理者审批中心</div>
            <div style={{ fontSize: 11, color: C.text3, marginTop: 2 }}>智能体受阻自动提交的调度申请 · 审批通过 → 回写解除阻塞 → 智能体自动继续</div>
          </div>
          <Space size={8}>
            <span style={{ fontWeight: 750, fontSize: 12, fontFamily: 'monospace', padding: '5px 10px', borderRadius: 12, background: C.warnSoft, color: C.warn }}>⏳ {filtered.length} 待审批</span>
            <Input value={approver} onChange={e => setApprover(e.target.value)} style={{ width: 130, height: 32, borderColor: C.borderStrong }} placeholder="审批人" />
          </Space>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 14, flexWrap: 'wrap' }}>
          <Select allowClear placeholder="按类型筛选" style={{ width: 150 }} value={typeFilter || undefined} onChange={v => setTypeFilter(v || '')}
            options={types.map(t => ({ value: t, label: (TYPE_META[t] || { label: t }).label }))} />
          <Input prefix={<SearchOutlined style={{ color: C.text3 }} />} placeholder="搜索任务 / 编号" style={{ width: 240, height: 32, borderColor: C.borderStrong }}
            value={query} onChange={e => setQuery(e.target.value)} />
        </div>
      </div>

      {/* 审批卡片（两列网格，宽敞展示） */}
      {filtered.length === 0 && <Empty description="暂无待审批调度申请" style={{ padding: 40, background: C.surface, borderRadius: 14, border: `1px solid ${C.border}` }} />}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,minmax(0,1fr))', gap: 12 }}>
        {filtered.slice(0, 40).map((t: any) => {
          const tm = TYPE_META[t.task_type] || { label: t.task_type, icon: <RobotOutlined />, color: C.brand, soft: C.brandSoft }
          const ctx = t.request_context || {}
          const isApproval = t.task_type === 'approval'
          return (
            <div key={t.id} style={{
              border: isApproval ? '1px solid #F0B7B7' : `1px solid ${C.border}`,
              borderRadius: 12, background: C.surface, padding: 14, display: 'flex', flexDirection: 'column', gap: 10,
            }}>
              {/* 卡片头：类型 + 编号 + 状态 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 30, height: 30, borderRadius: 8, background: tm.soft, color: tm.color, display: 'grid', placeItems: 'center', fontSize: 14 }}>{tm.icon}</div>
                <Tag color="blue" style={{ margin: 0 }}>{tm.label}</Tag>
                <span style={{ fontSize: 11, fontFamily: 'monospace', color: C.text3 }}>{t.task_code}</span>
                {isApproval && <Tag color="volcano" style={{ marginLeft: 'auto' }}>⛔ 需人工审批</Tag>}
              </div>
              {/* 任务标题 */}
              <div style={{ fontSize: 13.5, fontWeight: 800, color: C.text, lineHeight: 1.45 }}>{t.title}</div>
              {/* 影响说明 */}
              {t.expected_impact_summary && (
                <div style={{ fontSize: 11.5, color: C.text2, lineHeight: 1.55, background: C.surface, padding: '8px 10px', borderRadius: 8, border: `1px solid ${C.border}` }}>
                  {t.expected_impact_summary}
                </div>
              )}
              {/* 证据 / 上下文 */}
              {t.description && (
                <div style={{ borderLeft: `2px solid ${C.cyan}`, padding: '8px 10px', background: C.cyanSoft, color: '#24656C', fontSize: 11, lineHeight: 1.5, borderRadius: '0 8px 8px 0' }}>
                  {t.description.slice(0, 220)}{t.description.length > 220 ? '…' : ''}
                </div>
              )}
              {/* 元信息 */}
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 10.5, color: C.text3 }}>
                <span><RobotOutlined /> {t.requested_by || '智能体'}</span>
                {ctx.station && <span>工位: {ctx.station}</span>}
                {ctx.leave_rate && <span>缺勤率: {ctx.leave_rate}%</span>}
                {ctx.suggested_transfer && <span>方案: {ctx.suggested_transfer} 借调 {ctx.suggested_count} 人</span>}
                {t.created_at && <span><ClockCircleOutlined /> {String(t.created_at).slice(0, 16).replace('T', ' ')}</span>}
              </div>
              {/* 审批操作 */}
              <div style={{ display: 'flex', gap: 8, marginTop: 'auto', paddingTop: 4 }}>
                <button onClick={() => approve(t.id)} style={{
                  flex: 1, height: 34, borderRadius: 8, border: 'none', background: C.brand, color: '#fff',
                  fontSize: 12, fontWeight: 800, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                }}><CheckOutlined /> 批准调度</button>
                <button onClick={() => reject(t.id)} style={{
                  flex: 1, height: 34, borderRadius: 8, border: `1px solid ${C.borderStrong}`, background: C.surface, color: C.danger,
                  fontSize: 12, fontWeight: 800, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                }}><CloseOutlined /> 驳回</button>
              </div>
            </div>
          )
        })}
      </div>
    </Space>
  )
}
