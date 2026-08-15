/**
 * RCC 资源调度指挥中心 · V2（设计稿形态）
 * 浅色三栏：资源维度 rail | 主内容 5 Tab | 管理者 Action Center
 * 数据接真实 API：rcc/tasks + rcc/data + task-center/inbox
 */
import { useEffect, useMemo, useState, createContext, useContext } from 'react'
import { Tag, Button, Space, Progress, Tooltip, Input, Badge, Select, message } from 'antd'
import {
  ThunderboltOutlined, FundOutlined, CarryOutOutlined, ExperimentOutlined,
  FileTextOutlined, ReloadOutlined, SearchOutlined, CheckOutlined, CloseOutlined,
  AppstoreOutlined, TeamOutlined, SafetyOutlined, InboxOutlined, ToolOutlined,
  RobotOutlined, UserOutlined, ClusterOutlined, ArrowRightOutlined, ApartmentOutlined,
} from '@ant-design/icons'
import axios from 'axios'
import { useSearchParams } from 'react-router-dom'
import NeuralGraph from './RCCNeuralGraph'

const API = '/api/v1'
const C = {
  bg: '#F4F6F9', surface: '#FFF', border: '#E3E7EE', borderStrong: '#D2D8E2',
  text: '#172033', text2: '#596579', text3: '#93A0B4',
  brand: '#315DAA', brand2: '#214689', brandSoft: '#EAF0FC',
  cyan: '#087F8C', cyanSoft: '#E4F4F4', purple: '#7C4CB2', purpleSoft: '#F1EAF8',
  danger: '#D64545', dangerSoft: '#FBEAEA', warn: '#B36A12', warnSoft: '#FBF0DA',
  success: '#157C4F', successSoft: '#E5F6EE',
}

const TYPE_META: Record<string, { label: string; color: string; soft: string }> = {
  resource_allocation: { label: '资源分配', color: C.brand, soft: C.brandSoft },
  supplier_followup: { label: '供应商跟催', color: C.cyan, soft: C.cyanSoft },
  equipment_maintenance: { label: '设备维修', color: C.purple, soft: C.purpleSoft },
  approval: { label: '待审批', color: C.warn, soft: C.warnSoft },
  manpower: { label: '人力调度', color: C.success, soft: C.successSoft },
  data_fix: { label: '数据修复', color: C.text3, soft: '#F0F2F6' },
  dispatch: { label: '派工', color: C.brand, soft: C.brandSoft },
  scheduling: { label: '排程', color: C.cyan, soft: C.cyanSoft },
}
const STATUS_META: Record<string, { label: string; color: string }> = {
  pending: { label: '待审批', color: C.warn }, approved: { label: '已批准', color: C.success },
  rejected: { label: '已拒绝', color: C.danger }, executing: { label: '执行中', color: C.cyan },
  completed: { label: '已完成', color: C.success }, failed: { label: '失败', color: C.danger },
  escalated: { label: '已升级', color: C.purple },
}
const TASK_STATUS: Record<string, { label: string; color: string; soft: string }> = {
  open: { label: '跟进中', color: C.brand, soft: C.brandSoft },
  blocked: { label: '受阻', color: C.danger, soft: C.dangerSoft },
  done: { label: '已完成', color: C.success, soft: C.successSoft },
}

// ===== 旧子组件兼容导出（RCCAnalysis/DecisionHub/OrgBubble 等仍引用）=====
export const COLORS = {
  bg: '#0f1923', bgCard: '#1a2733', bgHover: '#243442', border: '#2a3f50',
  accent: '#00d4aa', accentBlue: '#4facfe', accentPurple: '#a78bfa',
  warning: '#fbbf24', danger: '#f87171', success: '#34d399',
  text: '#e2e8f0', textDim: '#94a3b8', textMuted: '#64748b',
}
const _RccCtx = createContext<any>({ baseline: {}, decisions: {}, factoryId: 'FAC_MECH_001', loading: false, lastSync: null, refresh: () => {} })
export const useRcc = () => useContext(_RccCtx)
export const RccContext = _RccCtx

export default function RCCCommandCenter() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'ai')
  const [factoryId, setFactoryId] = useState(localStorage.getItem('active_factory_id') || 'FAC_MECH_001')
  const [tasks, setTasks] = useState<any[]>([])
  const [baseline, setBaseline] = useState<any>({})
  const [inbox, setInbox] = useState<any>({ tasks: [], plans: [] })
  const [loading, setLoading] = useState(false)
  const [query, setQuery] = useState('')
  const [scope, setScope] = useState('all')

  const loadAll = async () => {
    setLoading(true)
    try {
      const [t, d, ib] = await Promise.allSettled([
        axios.get(`${API}/rcc/tasks`, { params: { page_size: 100 } }),
        axios.get(`${API}/rcc/data`, { params: { factory_id: factoryId, mode: 'single' } }),
        axios.get(`${API}/task-center/inbox`, { params: {}, headers: { 'X-Factory-Id': factoryId } }),
      ])
      if (t.status === 'fulfilled') setTasks(t.value.data?.items || [])
      if (d.status === 'fulfilled') setBaseline(d.value.data?.baseline || {})
      if (ib.status === 'fulfilled') setInbox(ib.value.data || {})
    } finally { setLoading(false) }
  }
  useEffect(() => { loadAll() }, [factoryId])

  const approve = async (id: string) => {
    try {
      await axios.post(`${API}/rcc/tasks/${id}/approve`, null, { params: { approver_id: 'rcc_controller', comment: '调度批准' } })
      message.success('已批准，关联任务自动解除阻塞')
      loadAll()
    } catch (e: any) { message.error(String(e.response?.data?.detail || e.message).slice(0, 60)) }
  }
  const reject = async (id: string) => {
    const reason = prompt('拒绝原因：') || '未说明'
    try {
      await axios.post(`${API}/rcc/tasks/${id}/reject`, null, { params: { approver_id: 'rcc_controller', reason } })
      message.success('已拒绝')
      loadAll()
    } catch (e: any) { message.error(String(e.response?.data?.detail || e.message).slice(0, 60)) }
  }

  const pending = tasks.filter(t => t.status === 'pending')
  const allTasks = inbox.tasks || []
  const blockedTasks = allTasks.filter((t: any) => t.status === 'blocked')
  const openTasks = allTasks.filter((t: any) => t.status === 'open')

  const filteredTasks = useMemo(() => allTasks.filter((t: any) => {
    const q = query.toLowerCase()
    return !q || `${t.title} ${t.created_by} ${t.assigned_to || ''} ${t.agent_name || ''}`.toLowerCase().includes(q)
  }), [allTasks, query])

  const people = baseline.people || {}
  const equipment = baseline.equipment || {}
  const peopleList = Array.isArray(people) ? people : (people.items || [])
  const equipList = Array.isArray(equipment) ? equipment : (equipment.items || [])

  const tabs = [
    { key: 'ai', label: 'AI 调度', icon: <ThunderboltOutlined />, badge: pending.length },
    { key: 'capacity', label: '资源负荷', icon: <FundOutlined /> },
    { key: 'dispatch', label: '任务队列', icon: <CarryOutOutlined />, badge: blockedTasks.length },
    { key: 'neural', label: '图连接矩阵', icon: <ApartmentOutlined /> },
    { key: 'logs', label: '调度日志', icon: <FileTextOutlined /> },
  ]

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text, fontFamily: '-apple-system,"PingFang SC","Microsoft YaHei",sans-serif' }}>
      {/* 顶栏 */}
      <header style={{ height: 56, background: C.surface, borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', gap: 16, padding: '0 20px', position: 'sticky', top: 0, zIndex: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 34, height: 34, borderRadius: 9, background: 'linear-gradient(135deg,#315DAA,#087F8C)', color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 900, fontSize: 13 }}>RCC</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 15, letterSpacing: .2 }}>资源调度指挥中心</div>
            <div style={{ fontSize: 10, color: C.text3, letterSpacing: .7, fontFamily: 'monospace' }}>RESOURCE COMMAND & DISPATCH</div>
          </div>
        </div>
        <Space size={8} style={{ marginLeft: 'auto' }}>
          <Select value={factoryId} onChange={setFactoryId} style={{ width: 150 }} options={[{ value: 'FAC_MECH_001', label: '机械厂' }, { value: 'FAC_ELEC_DEMO_2026', label: '电子厂' }]} />
          <Button icon={<ReloadOutlined spin={loading} />} onClick={loadAll} style={{ borderColor: C.borderStrong, color: C.text2 }}>刷新</Button>
        </Space>
      </header>

      {/* 三栏 shell */}
      <div style={{ display: 'grid', gridTemplateColumns: '240px minmax(0,1fr) 320px', minHeight: 'calc(100vh - 56px)' }}>

        {/* 左 rail：资源维度 */}
        <aside style={{ background: C.surface, borderRight: `1px solid ${C.border}`, padding: "14px 12px", overflow: 'auto' }}>
          <div style={{ fontSize: 10.5, fontWeight: 800, color: C.text3, letterSpacing: .7, textTransform: 'uppercase', margin: '4px 9px 8px' }}>资源维度</div>
          <button onClick={() => setScope('all')} style={{ width: '100%', textAlign: 'left', border: scope === 'all' ? `1px solid ${C.brandSoft}` : '1px solid transparent', background: scope === 'all' ? C.brandSoft : 'transparent', borderRadius: 10, padding: '10px 11px', display: 'flex', alignItems: 'center', fontSize: 13, fontWeight: 700, color: scope === 'all' ? C.brand2 : C.text2, marginBottom: 8, cursor: 'pointer' }}>
            全局资源态势 <span style={{ marginLeft: 'auto', fontSize: 11, fontFamily: 'monospace', color: C.text3 }}>LIVE</span>
          </button>
          {[
            { id: 'line', name: '线体 / 车间', sub: 'Production Lines', icon: '⌁', accent: C.brand, soft: C.brandSoft, state: `${equipList.filter((e: any) => e.utilization > 0.9).length || 0} 超载`, meta: `${equipList.length || 0} 节点` },
            { id: 'material', name: '物料 / 齐套', sub: 'Material Readiness', icon: '◇', accent: C.danger, soft: C.dangerSoft, state: `${blockedTasks.filter((t: any) => (t.block_category || '') === 'material').length} 缺料`, meta: `${blockedTasks.length} 受阻任务` },
            { id: 'people', name: '人员 / 技能', sub: 'People & Skills', icon: '◎', accent: C.purple, soft: C.purpleSoft, state: `${peopleList.length || 0} 人`, meta: '技能矩阵' },
            { id: 'equipment', name: '设备 / 模具', sub: 'Equipment & Tooling', icon: '▣', accent: C.cyan, soft: C.cyanSoft, state: `${equipList.filter((e: any) => e.status === 'fault').length || 0} 故障`, meta: `OEE 监控` },
            { id: 'order', name: '工单 / 依赖链', sub: 'Orders & Dependencies', icon: '↳', accent: C.warn, soft: C.warnSoft, state: `${openTasks.length} 跟进`, meta: '工单生命周期' },
          ].map(r => (
            <button key={r.id} onClick={() => setScope(r.id)} style={{ width: '100%', textAlign: 'left', border: scope === r.id ? `1px solid ${r.accent}` : `1px solid ${C.border}`, background: C.surface, borderRadius: 10, padding: '11px', margin: '7px 0', cursor: 'pointer', position: 'relative', transition: '.15s' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <div style={{ width: 27, height: 27, borderRadius: 7, background: r.soft, color: r.accent, display: 'grid', placeItems: 'center', fontSize: 13, flex: '0 0 auto' }}>{r.icon}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.8, fontWeight: 700 }}>{r.name}</div>
                  <div style={{ fontSize: 10.8, color: C.text3, marginTop: 2 }}>{r.sub}</div>
                </div>
                <span style={{ fontSize: 10, fontWeight: 800, padding: '2px 6px', borderRadius: 5, background: r.soft, color: r.accent, whiteSpace: 'nowrap' }}>{r.state}</span>
              </div>
              <div style={{ height: 5, background: '#EDF0F4', borderRadius: 4, marginTop: 10, overflow: 'hidden' }}>
                <div style={{ height: '100%', borderRadius: 4, background: r.accent, width: `${scope === r.id ? 80 : 40}%` }} />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 10.8, color: C.text3 }}><span>{r.meta}</span></div>
            </button>
          ))}
          <div style={{ marginTop: 18 }}>
            <div style={{ fontSize: 10.5, fontWeight: 800, color: C.text3, letterSpacing: .7, textTransform: 'uppercase', margin: '4px 9px 8px' }}>智能体协同状态</div>
            {['夜巡 Agent', '采购 Agent', 'PMC 计划 Agent', '设备 Agent'].map((a, i) => (
              <div key={a} style={{ display: 'flex', alignItems: 'center', padding: '7px 9px', borderRadius: 8, gap: 7 }}>
                <i style={{ width: 8, height: 8, borderRadius: '50%', background: i === 1 ? C.warn : C.success, boxShadow: `0 0 0 3px ${i === 1 ? C.warnSoft : C.successSoft}` }} />
                <span style={{ fontSize: 11.8, fontWeight: 650 }}>{a}</span>
                <span style={{ marginLeft: 'auto', fontSize: 10.5, color: C.text3 }}>{['物料监控', '补货跟催', '排产盯办', '维修调度'][i]}</span>
              </div>
            ))}
          </div>
        </aside>

        {/* 中 main：5 Tab */}
        <main style={{ padding: '14px 16px 30px', minWidth: 0, overflow: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
            <div style={{ display: 'flex', gap: 4, flex: 1, overflowX: 'auto' }}>
              {tabs.map(t => (
                <button key={t.key} onClick={() => { setActiveTab(t.key); setSearchParams({ tab: t.key }) }}
                  style={{ whiteSpace: 'nowrap', border: '1px solid transparent', padding: '7px 11px', borderRadius: 8, color: activeTab === t.key ? C.brand2 : C.text2, fontSize: 12.5, fontWeight: 700, cursor: 'pointer', background: activeTab === t.key ? C.brandSoft : 'transparent' }}>
                  {t.icon} {t.label}
                  {t.badge !== undefined && t.badge > 0 && <span style={{ fontSize: 10, fontFamily: 'monospace', padding: '1px 5px', borderRadius: 8, background: 'rgba(255,255,255,.7)', marginLeft: 4 }}>{t.badge}</span>}
                </button>
              ))}
            </div>
            {activeTab === 'dispatch' && (
              <Input prefix={<SearchOutlined style={{ color: C.text3 }} />} placeholder="搜索任务 / 归属人 / 智能体" value={query} onChange={e => setQuery(e.target.value)} style={{ width: 210, height: 34, borderColor: C.borderStrong, background: C.surface }} />
            )}
          </div>

          {/* Tab: AI 调度 */}
          {activeTab === 'ai' && (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <div style={{ background: 'linear-gradient(135deg,#F8FAFF,#F5FBFB)', border: '1px solid #DDE7F3', borderRadius: 14, padding: '14px 15px' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                  <div style={{ width: 36, height: 36, borderRadius: 10, background: 'linear-gradient(135deg,#315DAA,#087F8C)', color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 900 }}><RobotOutlined /></div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 850 }}>RCC 智能调度引擎</div>
                    <div style={{ fontSize: 10.8, color: C.text3, marginTop: 3 }}>智能体受阻自动提交调度申请 → 审批通过回写解除阻塞 → scanner 自动继续。人机协同全程可视。</div>
                  </div>
                  <Space>
                    <span style={{ fontWeight: 750, fontSize: 10, fontFamily: 'monospace', padding: '4px 8px', borderRadius: 12, background: C.successSoft, color: C.success }}>{pending.length} 待审批</span>
                    <span style={{ fontWeight: 750, fontSize: 10, fontFamily: 'monospace', padding: '4px 8px', borderRadius: 12, background: C.cyanSoft, color: C.cyan }}>{tasks.filter((t: any) => t.status === 'approved').length} 已批准</span>
                  </Space>
                </div>
                {/* 调度流水线 */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 7, marginTop: 13 }}>
                  {['受阻提交', 'RCC 受理', '智能匹配', '人工审批', '回写续跑'].map((s, i) => (
                    <div key={s} style={{ position: 'relative', border: `1px solid ${i <= 1 ? '#AFC4EA' : C.border}`, background: i <= 1 ? C.brandSoft : '#fff', borderRadius: 9, padding: '8px 9px', minHeight: 44 }}>
                      <b style={{ display: 'block', fontSize: 10.5, color: i <= 1 ? C.brand2 : C.text }}>{i + 1}. {s}</b>
                      <span style={{ display: 'block', fontSize: 9.5, color: C.text3, marginTop: 3 }}>
                        {['智能体 blocked 自动提交', '任务进入审批队列', '按类型/资源匹配', '批准 / 拒绝', '状态机自动接管'][i]}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
              {/* 调度方案卡 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,minmax(0,1fr))', gap: 10 }}>
                {pending.length === 0 && (
                  <div style={{ gridColumn: '1/-1', padding: 40, textAlign: 'center', color: C.text3, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14 }}>暂无待审批调度申请 —— 智能体受阻时会自动提交</div>
                )}
                {pending.slice(0, 6).map((t: any) => {
                  const tm = TYPE_META[t.task_type] || { label: t.task_type, color: C.brand, soft: C.brandSoft }
                  return (
                    <div key={t.id} style={{ border: t.task_type === 'approval' ? '1px solid #F0B7B7' : `1px solid ${C.border}`, borderRadius: 11, background: '#fff', padding: 12, position: 'relative' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                        <span style={{ fontSize: 9.5, fontWeight: 850, fontFamily: 'monospace', padding: '2px 6px', borderRadius: 5, background: tm.soft, color: tm.color }}>{tm.label}</span>
                        <span style={{ fontSize: 9.5, fontFamily: 'monospace', color: C.text3, marginLeft: 'auto' }}>{t.task_code}</span>
                      </div>
                      <div style={{ fontSize: 12.5, fontWeight: 800, marginTop: 8 }}>{t.title}</div>
                      <div style={{ fontSize: 10.5, color: C.text3, lineHeight: 1.45, marginTop: 3 }}>{t.expected_impact_summary || '资源调度申请'}</div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 9, fontSize: 10, color: C.text3 }}>
                        <span><RobotOutlined /> {t.requested_by}</span>
                        <b style={{ color: C.success, fontWeight: 800, fontSize: 10, fontFamily: 'monospace' }}>审批后自动续跑</b>
                      </div>
                      <div style={{ display: 'flex', gap: 6, marginTop: 9 }}>
                        <button onClick={() => approve(t.id)} style={{ flex: 1, height: 28, borderRadius: 7, border: 'none', background: C.brand, color: '#fff', fontSize: 10, fontWeight: 800, cursor: 'pointer' }}><CheckOutlined /> 批准调度</button>
                        <button onClick={() => reject(t.id)} style={{ flex: 1, height: 28, borderRadius: 7, border: `1px solid ${C.border}`, background: '#fff', color: C.text2, fontSize: 10, fontWeight: 800, cursor: 'pointer' }}><CloseOutlined /> 驳回</button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </Space>
          )}

          {/* Tab: 资源负荷 */}
          {activeTab === 'capacity' && (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden' }}>
                <div style={{ display: 'flex', alignItems: 'center', padding: '13px 15px', borderBottom: `1px solid ${C.border}` }}>
                  <b style={{ fontSize: 13 }}>设备负荷与 OEE</b>
                  <span style={{ fontSize: 10.5, color: C.text3, marginLeft: 8 }}>Equipment Utilization</span>
                  <span style={{ marginLeft: 'auto', fontSize: 10, fontFamily: 'monospace', color: C.cyan, background: C.cyanSoft, padding: '3px 7px', borderRadius: 10 }}>LIVE</span>
                </div>
                <div style={{ padding: '4px 14px 8px' }}>
                  {equipList.length === 0 && <div style={{ padding: 30, textAlign: 'center', color: C.text3, fontSize: 12 }}>暂无设备基线数据</div>}
                  {equipList.slice(0, 8).map((e: any) => {
                    const pct = Math.round((e.utilization || 0) * 100)
                    const status = pct > 90 ? 'danger' : pct < 60 ? 'ok' : 'warn'
                    return (
                      <div key={e.equipment_code || e.id || e.name} style={{ display: 'grid', gridTemplateColumns: '185px minmax(200px,1fr) 92px 100px', gap: 12, alignItems: 'center', padding: '12px 4px', borderBottom: `1px solid ${C.border}` }}>
                        <div>
                          <div style={{ fontSize: 12.5, fontWeight: 720 }}>{e.equipment_name || e.name}</div>
                          <div style={{ fontSize: 10.5, color: C.text3, marginTop: 3 }}>{e.equipment_code || e.id} · {e.status || '运行中'}</div>
                        </div>
                        <div style={{ height: 20, borderRadius: 6, background: '#EEF1F5', position: 'relative', overflow: 'hidden' }}>
                          <div style={{ height: '100%', borderRadius: 6, background: status === 'danger' ? `linear-gradient(90deg,#B36A12,#D64545)` : status === 'ok' ? `linear-gradient(90deg,#157C4F,#38A873)` : `linear-gradient(90deg,#315DAA,#4F7CC7)`, width: `${Math.min(pct, 100)}%`, position: 'relative' }}>
                            <span style={{ fontWeight: 700, fontSize: 12, fontFamily: 'monospace', color: '#fff', position: 'absolute', left: 8, top: 2, whiteSpace: 'nowrap' }}>{pct}%</span>
                          </div>
                        </div>
                        <span style={{ fontSize: 10.5, fontWeight: 800, padding: '3px 7px', borderRadius: 10, textAlign: 'center', background: status === 'danger' ? C.dangerSoft : status === 'warn' ? C.warnSoft : C.successSoft, color: status === 'danger' ? C.danger : status === 'warn' ? C.warn : C.success }}>
                          {status === 'danger' ? '超载' : status === 'warn' ? '高负荷' : '正常'}
                        </span>
                        <div style={{ textAlign: 'right', fontSize: 10.5, color: C.text3 }}><b style={{ display: 'block', color: C.text2, fontFamily: 'monospace', fontSize: 11.5, fontWeight: 700 }}>{e.capacity_hours || e.available_hours || '-'}h</b>可用产能</div>
                      </div>
                    )
                  })}
                </div>
              </div>
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden' }}>
                <div style={{ display: 'flex', alignItems: 'center', padding: '13px 15px', borderBottom: `1px solid ${C.border}` }}>
                  <b style={{ fontSize: 13 }}>人员负荷</b><span style={{ fontSize: 10.5, color: C.text3, marginLeft: 8 }}>People & Skills</span>
                </div>
                <div style={{ padding: '4px 14px 8px' }}>
                  {peopleList.length === 0 && <div style={{ padding: 30, textAlign: 'center', color: C.text3, fontSize: 12 }}>暂无人员基线数据</div>}
                  {peopleList.slice(0, 8).map((p: any) => {
                    const load = Math.round((p.load || 0) * 100)
                    return (
                      <div key={p.employee_code || p.id || p.name} style={{ display: 'grid', gridTemplateColumns: '185px minmax(200px,1fr) 92px', gap: 12, alignItems: 'center', padding: '12px 4px', borderBottom: `1px solid ${C.border}` }}>
                        <div>
                          <div style={{ fontSize: 12.5, fontWeight: 720 }}>{p.name}</div>
                          <div style={{ fontSize: 10.5, color: C.text3, marginTop: 3 }}>{p.position || p.role}</div>
                        </div>
                        <div style={{ height: 20, borderRadius: 6, background: '#EEF1F5', position: 'relative', overflow: 'hidden' }}>
                          <div style={{ height: '100%', borderRadius: 6, background: load > 90 ? 'linear-gradient(90deg,#B36A12,#D64545)' : 'linear-gradient(90deg,#315DAA,#4F7CC7)', width: `${Math.min(load, 100)}%` }}>
                            <span style={{ fontWeight: 700, fontSize: 12, fontFamily: 'monospace', color: '#fff', position: 'absolute', left: 8, top: 2 }}>{load}%</span>
                          </div>
                        </div>
                        <span style={{ fontSize: 10.5, color: C.text3 }}>{p.skill || p.department || '-'}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </Space>
          )}

          {/* Tab: 任务队列 */}
          {activeTab === 'dispatch' && (
            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden' }}>
              <div style={{ display: 'flex', alignItems: 'center', padding: '13px 15px', borderBottom: `1px solid ${C.border}` }}>
                <b style={{ fontSize: 13 }}>全厂任务队列</b>
                <span style={{ fontSize: 10.5, color: C.text3, marginLeft: 8 }}>所有人员 / 智能体的任务 · 含归属人</span>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 11, fontSize: 10.5, color: C.text3, alignItems: 'center' }}>
                  <span><i style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: C.brand, marginRight: 4 }} />跟进中 {openTasks.length}</span>
                  <span><i style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: C.danger, marginRight: 4 }} />受阻 {blockedTasks.length}</span>
                </div>
              </div>
              <div style={{ overflow: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 1100 }}>
                  <thead>
                    <tr style={{ background: C.surface, borderBottom: `1px solid ${C.border}` }}>
                      {['任务', '归属人', '智能体', '状态', '进度', '卡点', '最近结论'].map(h => (
                        <th key={h} style={{ padding: '10px 11px', fontSize: 10.5, color: C.text3, textAlign: 'left', letterSpacing: .25, whiteSpace: 'nowrap' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredTasks.length === 0 && <tr><td colSpan={7} style={{ padding: 40, textAlign: 'center', color: C.text3, fontSize: 12 }}>暂无任务</td></tr>}
                    {filteredTasks.slice(0, 30).map((t: any) => {
                      const st = TASK_STATUS[t.status] || { label: t.status, color: C.text3, soft: '#F0F2F6' }
                      return (
                        <tr key={t.id} style={{ borderBottom: `1px solid ${C.border}`, opacity: t.status === 'done' ? .64 : 1 }}>
                          <td style={{ padding: 11, fontSize: 11.8 }}>
                            <div style={{ fontWeight: 700, color: C.text, lineHeight: 1.4, maxWidth: 240 }}>{t.title}</div>
                            <span style={{ display: 'block', fontSize: 10, fontFamily: 'monospace', color: C.text3, marginTop: 3 }}>{t.item_type || 'followup'}</span>
                          </td>
                          <td style={{ padding: 11 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                              <div style={{ width: 25, height: 25, borderRadius: '50%', background: C.brandSoft, color: C.brand2, display: 'grid', placeItems: 'center', fontSize: 9.5, fontWeight: 850 }}>{(t.created_by || '?')[0].toUpperCase()}</div>
                              <div>
                                <div style={{ fontSize: 11, fontWeight: 750 }}>{t.created_by}</div>
                                <div style={{ fontSize: 9.5, color: C.text3 }}>{t.assigned_to ? `→ ${t.assigned_to}` : '未指派'}</div>
                              </div>
                            </div>
                          </td>
                          <td style={{ padding: 11 }}><span style={{ display: 'inline-flex', borderRadius: 7, padding: '3px 7px', fontSize: 10.5, fontWeight: 750, background: C.cyanSoft, color: C.cyan, whiteSpace: 'nowrap' }}>{t.agent_name || '通用'}</span></td>
                          <td style={{ padding: 11 }}><span style={{ display: 'inline-flex', borderRadius: 7, padding: '3px 7px', fontSize: 10.5, fontWeight: 750, background: st.soft, color: st.color, whiteSpace: 'nowrap' }}>{st.label}</span></td>
                          <td style={{ padding: 11, minWidth: 90 }}>
                            <div style={{ height: 6, background: '#EEF1F5', borderRadius: 6, overflow: 'hidden', width: 80 }}>
                              <div style={{ height: '100%', borderRadius: 6, background: t.status === 'blocked' ? C.warn : t.status === 'done' ? C.success : C.brand, width: `${Math.min(t.progress_pct || 0, 100)}%` }} />
                            </div>
                            <span style={{ fontSize: 10, fontFamily: 'monospace', color: C.text3, marginTop: 3, display: 'block' }}>{t.progress_pct || 0}%</span>
                          </td>
                          <td style={{ padding: 11 }}>
                            {t.blocked_by ? (
                              <span style={{ display: 'inline-flex', borderRadius: 7, padding: '3px 7px', fontSize: 10.5, fontWeight: 750, background: C.warnSoft, color: C.warn, whiteSpace: 'nowrap' }}>⛔ {t.blocked_by}{t.block_category ? ` / ${t.block_category}` : ''}</span>
                            ) : <span style={{ color: C.text3, fontSize: 10.5 }}>—</span>}
                          </td>
                          <td style={{ padding: 11, maxWidth: 260 }}>
                            <div style={{ fontSize: 10.5, color: C.text2, lineHeight: 1.45, maxHeight: 40, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>{t.last_follow_note || t.ai_summary || '尚未跟进'}</div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Tab: 图连接矩阵 */}
          {activeTab === 'neural' && <NeuralGraph tasks={tasks} inbox={inbox} baseline={baseline} />}

          {/* Tab: 调度日志 */}
          {activeTab === 'logs' && <LogStream />}
        </main>

        {/* 右 rail：管理者 Action Center */}
        <aside style={{ background: C.surface, borderLeft: `1px solid ${C.border}`, padding: '15px 13px 28px', overflow: 'auto' }}>
          <div style={{ position: 'sticky', top: 70 }}>
            <div style={{ fontSize: 10.5, fontWeight: 800, color: C.text3, letterSpacing: .7, textTransform: 'uppercase', margin: '4px 9px 8px' }}>管理者 Action Center</div>
            {pending.length === 0 && <div style={{ border: `1px solid ${C.border}`, borderRadius: 12, padding: 14, color: C.text3, fontSize: 11, textAlign: 'center' }}>审批队列已清空 ✓</div>}
            {pending.slice(0, 5).map((t: any) => {
              const tm = TYPE_META[t.task_type] || { label: t.task_type, color: C.brand, soft: C.brandSoft }
              return (
                <div key={t.id} style={{ border: t.task_type === 'approval' ? '1px solid #F0B7B7' : `1px solid ${C.border}`, borderRadius: 12, padding: 12, marginBottom: 10, background: C.surface }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                    <div style={{ width: 29, height: 29, borderRadius: 8, background: tm.soft, color: tm.color, display: 'grid', placeItems: 'center', flex: '0 0 auto', fontSize: 13 }}><CarryOutOutlined /></div>
                    <div>
                      <div style={{ fontSize: 12.5, fontWeight: 780, lineHeight: 1.35 }}>{t.title?.slice(0, 32)}{t.title?.length > 32 ? '…' : ''}</div>
                      <div style={{ marginTop: 3, fontSize: 10, color: C.text3, fontFamily: 'monospace' }}>{t.task_code} · {tm.label}</div>
                    </div>
                  </div>
                  <div style={{ fontSize: 11, color: C.text2, lineHeight: 1.5, margin: '9px 0' }}>{t.expected_impact_summary || t.description || '—'}</div>
                  <div style={{ borderLeft: `2px solid ${C.cyan}`, padding: '7px 8px', background: C.cyanSoft, color: '#24656C', fontSize: 10.5, lineHeight: 1.45, borderRadius: '0 7px 7px 0' }}>
                    <RobotOutlined /> {t.requested_by || '智能体'} 提交 · 审批后自动回写解除阻塞
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 9 }}>
                    <button onClick={() => approve(t.id)} style={{ flex: 1, height: 29, borderRadius: 7, border: 'none', background: C.brand, color: '#fff', fontSize: 10.5, fontWeight: 800, cursor: 'pointer' }}><CheckOutlined /> 批准</button>
                    <button onClick={() => reject(t.id)} style={{ flex: 1, height: 29, borderRadius: 7, border: `1px solid ${C.border}`, background: C.surface, color: C.text2, fontSize: 10.5, fontWeight: 800, cursor: 'pointer' }}><CloseOutlined /> 驳回</button>
                  </div>
                </div>
              )
            })}
            <div style={{ marginTop: 16, borderTop: `1px solid ${C.border}`, paddingTop: 13 }}>
              <div style={{ fontSize: 10.5, fontWeight: 800, color: C.text3, letterSpacing: .7, textTransform: 'uppercase', margin: '0 0 8px' }}>今日调度闭环</div>
              {[
                ['AI 提议', tasks.length], ['已审批', tasks.filter((t: any) => t.status === 'approved').length],
                ['人工驳回', tasks.filter((t: any) => t.status === 'rejected').length], ['待审批', pending.length],
              ].map(([k, v]) => (
                <div key={k as string} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 8px', fontSize: 11, color: C.text2 }}>
                  <span>{k}</span><b style={{ fontWeight: 700, fontSize: 11, fontFamily: 'monospace', color: C.text }}>{v}</b>
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </div>
  )
}

/** 调度日志流 */
function LogStream() {
  const [logs, setLogs] = useState<any[]>([])
  useEffect(() => {
    axios.get(`${API}/task-center/tasks?limit=5`).catch(() => {})
    // 用 inbox 任务的日志（简化：显示任务变更流）
    axios.get(`${API}/rcc/tasks`, { params: { page_size: 20 } }).then(r => {
      const items = r.data?.items || []
      setLogs(items.map((t: any) => ({
        time: (t.created_at || '').slice(11, 19), agent: t.requested_by || '系统',
        msg: `${t.title}（${t.task_type}）`, result: t.status,
      })))
    }).catch(() => {})
  }, [])
  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, padding: '4px 14px 10px' }}>
      {logs.length === 0 && <div style={{ padding: 40, textAlign: 'center', color: C.text3, fontSize: 12 }}>暂无调度日志</div>}
      {logs.slice(0, 30).map((l: any, i: number) => (
        <div key={i} style={{ display: 'grid', gridTemplateColumns: '72px 110px 1fr 90px', gap: 10, padding: '9px 2px', borderBottom: `1px solid ${C.border}`, fontSize: 11, alignItems: 'center' }}>
          <span style={{ fontFamily: 'monospace', fontSize: 10, color: C.text3 }}>{l.time}</span>
          <span style={{ fontWeight: 750, color: C.cyan }}>{l.agent}</span>
          <span style={{ color: C.text2 }}>{l.msg}</span>
          <span style={{ textAlign: 'right' }}><span style={{ fontSize: 10, fontWeight: 800, padding: '2px 6px', borderRadius: 8, background: l.result === 'approved' ? C.successSoft : l.result === 'pending' ? C.warnSoft : C.cyanSoft, color: l.result === 'approved' ? C.success : l.result === 'pending' ? C.warn : C.cyan }}>
            {STATUS_META[l.result]?.label || l.result}
          </span></span>
        </div>
      ))}
    </div>
  )
}
