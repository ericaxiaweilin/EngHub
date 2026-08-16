/**
 * RCC 资源调度指挥中心 V3 — 完整视图体系（找回全部丢失页面）
 * 视图：气泡面板/指挥总览/AI调度/资源负荷/资源调度板/决策中心/瓶颈分析/任务队列/图连接矩阵/逻辑链/调度日志
 * 布局：左 rail（视图导航+资源维度+智能体）| 中 main | 右 rail 固定（管理者 Action Center）
 */
import { useEffect, useMemo, useState } from 'react'
import { Tag, Button, Space, Progress, Tooltip, Input, Badge, Select, message, InputNumber } from 'antd'
import {
  ThunderboltOutlined, FundOutlined, CarryOutOutlined, FileTextOutlined,
  ReloadOutlined, SearchOutlined, CheckOutlined, CloseOutlined,
  RobotOutlined, ApartmentOutlined, TeamOutlined,
  ControlOutlined, FireOutlined, DashboardOutlined, AppstoreOutlined, ClockCircleOutlined,
} from '@ant-design/icons'
import axios from 'axios'
import { RccContext } from './rcc_theme'
import { useSearchParams } from 'react-router-dom'
import RCCOverview from './RCCOverview'
import ResourceIndexCard from './ResourceIndexCard'
import RCCResourceBoard from './RCCResourceBoard'
import RCCDecisionHub from './RCCDecisionHub'
import RCCAnalysis from './RCCAnalysis'
import LogicChainEditor from './LogicChainEditor'
import NeuralGraph from './RCCNeuralGraph'
import RCCApprovalCenter from './RCCApprovalCenter'

const API = '/api/v1'
const C = {
  bg: '#F4F6F9', surface: '#FFF', border: '#E3E7EE', borderStrong: '#D2D8E2',
  text: '#172033', text2: '#596579', text3: '#93A0B4',
  brand: '#315DAA', brand2: '#214689', brandSoft: '#EAF0FC',
  cyan: '#087F8C', cyanSoft: '#E4F4F4', purple: '#7C4CB2', purpleSoft: '#F1EAF8',
  danger: '#D64545', dangerSoft: '#FBEAEA', warn: '#B36A12', warnSoft: '#FBF0DA',
  success: '#157C4F', successSoft: '#E5F6EE',
}
// 旧子组件兼容（从独立 theme 文件导入，打破循环依赖）
export { COLORS, useRcc, RccContext } from './rcc_theme'

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
const TASK_STATUS: Record<string, { label: string; color: string; soft: string }> = {
  open: { label: '跟进中', color: C.brand, soft: C.brandSoft },
  blocked: { label: '受阻', color: C.danger, soft: C.dangerSoft },
  done: { label: '已完成', color: C.success, soft: C.successSoft },
}

export default function RCCCommandCenter() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'bubbles')
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
  // baseline 是聚合对象（people: active_workers/skills/alert_count；equipment: total/statuses/oee）
  const peopleList = Array.isArray(people) ? people : (people.items || [])
  const equipList = Array.isArray(equipment) ? equipment : (equipment.items || [])
  const peopleCount = typeof people === 'object' && !Array.isArray(people) ? (people.active_workers || 0) : peopleList.length
  const equipTotal = typeof equipment === 'object' && !Array.isArray(equipment) ? (equipment.total || 0) : equipList.length
  const equipStatuses = (equipment && typeof equipment === 'object' && !Array.isArray(equipment) && equipment.statuses) || {}
  const equipFaultCount = equipStatuses.broken || equipStatuses.fault || 0
  const equipMaintenanceCount = equipStatuses.maintenance || 0

  // 视图导航（找回全部页面）
  const views = [
    { key: 'overview', label: '指挥总览', icon: <DashboardOutlined /> },
    { key: 'ai', label: 'AI 调度', icon: <ThunderboltOutlined />, badge: pending.length },
    { key: 'approvals', label: '审批中心', icon: <CheckOutlined />, badge: pending.length },
    { key: 'capacity', label: '资源负荷', icon: <FundOutlined /> },
    { key: 'resources', label: '资源调度板', icon: <AppstoreOutlined /> },
    { key: 'decisions', label: '决策中心', icon: <ControlOutlined /> },
    { key: 'analysis', label: '瓶颈分析', icon: <FireOutlined /> },
    { key: 'dispatch', label: '任务队列', icon: <CarryOutOutlined />, badge: blockedTasks.length },
    { key: 'neural', label: '图连接矩阵', icon: <ApartmentOutlined /> },
    { key: 'logic', label: '逻辑链编排', icon: <ControlOutlined /> },
    { key: 'logs', label: '调度日志', icon: <FileTextOutlined /> },
  ]

  return (
    <div style={{ minHeight: '100vh', background: C.bg, color: C.text, fontFamily: '-apple-system,"PingFang SC","Microsoft YaHei",sans-serif' }}>
      {/* 顶栏 */}
      <header style={{ height: 54, background: C.surface, borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', gap: 14, padding: '0 18px', position: 'sticky', top: 0, zIndex: 30 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{ width: 32, height: 32, borderRadius: 8, background: 'linear-gradient(135deg,#315DAA,#087F8C)', color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 900, fontSize: 12 }}>RCC</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 14 }}>资源调度指挥中心</div>
            <div style={{ fontSize: 9.5, color: C.text3, letterSpacing: .6, fontFamily: 'monospace' }}>RESOURCE COMMAND & DISPATCH</div>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 3, marginLeft: 8, flex: 1, overflowX: 'auto' }}>
          {views.slice(0, 6).map(v => (
            <button key={v.key} onClick={() => { setActiveTab(v.key); setSearchParams({ tab: v.key }) }}
              style={{ whiteSpace: 'nowrap', border: '1px solid transparent', padding: '6px 10px', borderRadius: 7, background: activeTab === v.key ? C.brandSoft : 'transparent', color: activeTab === v.key ? C.brand2 : C.text2, fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
              {v.icon} {v.label}
              {v.badge !== undefined && v.badge > 0 && <span style={{ fontSize: 9.5, fontFamily: 'monospace', padding: '0 5px', borderRadius: 8, background: 'rgba(255,255,255,.7)', marginLeft: 3 }}>{v.badge}</span>}
            </button>
          ))}
        </div>
        <Select value={factoryId} onChange={setFactoryId} style={{ width: 130 }} options={[{ value: 'FAC_MECH_001', label: '机械厂' }, { value: 'FAC_ELEC_DEMO_2026', label: '电子厂' }]} />
        <Button icon={<ReloadOutlined spin={loading} />} onClick={loadAll} style={{ borderColor: C.borderStrong, color: C.text2 }}>刷新</Button>
      </header>

      {/* 视图切换条（7-11） */}
      <div style={{ display: 'flex', gap: 3, padding: '6px 18px', background: C.surface, borderBottom: `1px solid ${C.border}`, overflowX: 'auto' }}>
        {views.slice(6).map(v => (
          <button key={v.key} onClick={() => { setActiveTab(v.key); setSearchParams({ tab: v.key }) }}
            style={{ whiteSpace: 'nowrap', border: '1px solid transparent', padding: '5px 10px', borderRadius: 7, background: activeTab === v.key ? C.brandSoft : 'transparent', color: activeTab === v.key ? C.brand2 : C.text2, fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            {v.icon} {v.label}
            {v.badge !== undefined && v.badge > 0 && <span style={{ fontSize: 9.5, fontFamily: 'monospace', padding: '0 5px', borderRadius: 8, background: 'rgba(255,255,255,.7)', marginLeft: 3 }}>{v.badge}</span>}
          </button>
        ))}
      </div>

      {/* 两栏 shell：rail 240 | main（审批中心等全部视图在主栏） */}
      <div style={{ display: 'grid', gridTemplateColumns: '240px minmax(0,1fr)', minHeight: 'calc(100vh - 106px)' }}>

        {/* 左 rail：资源维度 + 智能体 */}
        <aside style={{ background: C.surface, borderRight: `1px solid ${C.border}`, padding: '14px 12px', overflow: 'auto', maxHeight: 'calc(100vh - 106px)' }}>
          <div style={{ fontSize: 10.5, fontWeight: 800, color: C.text3, letterSpacing: .7, textTransform: 'uppercase', margin: '4px 9px 8px' }}>资源维度</div>
          <button onClick={() => setScope('all')} style={{ width: '100%', textAlign: 'left', border: scope === 'all' ? `1px solid ${C.brandSoft}` : '1px solid transparent', background: scope === 'all' ? C.brandSoft : 'transparent', borderRadius: 10, padding: '10px 11px', display: 'flex', alignItems: 'center', fontSize: 13, fontWeight: 700, color: scope === 'all' ? C.brand2 : C.text2, marginBottom: 8, cursor: 'pointer' }}>
            全局资源态势 <span style={{ marginLeft: 'auto', fontSize: 11, fontFamily: 'monospace', color: C.text3 }}>LIVE</span>
          </button>
          {[
            { id: 'line', name: '线体 / 车间', icon: '⌁', accent: C.brand, soft: C.brandSoft, state: `${equipFaultCount + equipMaintenanceCount} 异常`, meta: `${equipTotal} 台设备` },
            { id: 'material', name: '物料 / 齐套', icon: '◇', accent: C.danger, soft: C.dangerSoft, state: `${blockedTasks.filter((t: any) => (t.block_category || '') === 'material').length} 缺料`, meta: `${blockedTasks.length} 受阻` },
            { id: 'people', name: '人员 / 技能', icon: '◎', accent: C.purple, soft: C.purpleSoft, state: `${peopleCount} 人`, meta: `出勤 ${people.attendance_rate_pct || '-'}%` },
            { id: 'equipment', name: '设备 / 模具', icon: '▣', accent: C.cyan, soft: C.cyanSoft, state: `${equipFaultCount} 故障`, meta: `${equipMaintenanceCount} 维护` },
            { id: 'order', name: '工单 / 依赖链', icon: '↳', accent: C.warn, soft: C.warnSoft, state: `${openTasks.length} 跟进`, meta: '生命周期' },
          ].map(r => (
            <button key={r.id} onClick={() => setScope(r.id)} style={{ width: '100%', textAlign: 'left', border: scope === r.id ? `1px solid ${r.accent}` : `1px solid ${C.border}`, background: C.surface, borderRadius: 10, padding: '11px', margin: '7px 0', cursor: 'pointer' }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <div style={{ width: 27, height: 27, borderRadius: 7, background: r.soft, color: r.accent, display: 'grid', placeItems: 'center', fontSize: 13, flex: '0 0 auto' }}>{r.icon}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.8, fontWeight: 700 }}>{r.name}</div>
                  <div style={{ fontSize: 10.8, color: C.text3, marginTop: 2 }}>{r.meta}</div>
                </div>
                <span style={{ fontSize: 10, fontWeight: 800, padding: '2px 6px', borderRadius: 5, background: r.soft, color: r.accent, whiteSpace: 'nowrap' }}>{r.state}</span>
              </div>
            </button>
          ))}
          <div style={{ marginTop: 18 }}>
            <div style={{ fontSize: 10.5, fontWeight: 800, color: C.text3, letterSpacing: .7, textTransform: 'uppercase', margin: '4px 9px 8px' }}>智能体协同</div>
            {['夜巡 Agent', '采购 Agent', 'PMC 计划', '设备 Agent', '品质 Agent'].map((a, i) => (
              <div key={a} style={{ display: 'flex', alignItems: 'center', padding: '7px 9px', borderRadius: 8, gap: 7 }}>
                <i style={{ width: 8, height: 8, borderRadius: '50%', background: i === 1 ? C.warn : C.success, boxShadow: `0 0 0 3px ${i === 1 ? C.warnSoft : C.successSoft}` }} />
                <span style={{ fontSize: 11.8, fontWeight: 650 }}>{a}</span>
                <span style={{ marginLeft: 'auto', fontSize: 10.5, color: C.text3 }}>{['物料监控', '补货跟催', '排产盯办', '维修调度', '品质追溯'][i]}</span>
              </div>
            ))}
          </div>
        </aside>

        {/* 中 main */}
        <main style={{ padding: '14px 16px 30px', minWidth: 0, overflow: 'auto', maxHeight: 'calc(100vh - 106px)' }}>
          <RccContext.Provider value={{ baseline, decisions: { full: tasks, pending, approved: tasks.filter((t: any) => t.status === 'approved') }, factoryId, loading, lastSync: new Date().toISOString(), refresh: loadAll }}>
          {/* 调度闭环统计条（主栏顶部，替代右栏） */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
            {[
              ['AI 提议', tasks.length, C.brand, C.brandSoft],
              ['已审批', tasks.filter((t: any) => t.status === 'approved').length, C.success, C.successSoft],
              ['人工驳回', tasks.filter((t: any) => t.status === 'rejected').length, C.danger, C.dangerSoft],
              ['待审批', pending.length, C.warn, C.warnSoft],
            ].map(([k, v, color, soft]) => (
              <button key={k as string} onClick={() => { if (k === '待审批') { setActiveTab('approvals'); setSearchParams({ tab: 'approvals' }) } }}
                style={{ border: `1px solid ${C.border}`, borderRadius: 10, background: C.surface, padding: '8px 14px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, textAlign: 'left' }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: color as string }} />
                <span style={{ fontSize: 11, color: C.text3, fontWeight: 700 }}>{k}</span>
                <b style={{ fontSize: 15, fontFamily: 'monospace', color: color as string }}>{v}</b>
              </button>
            ))}
          </div>
          {activeTab === 'overview' && (
            <>
              <ResourceIndexCard />
              <RCCOverview />
            </>
          )}
          {activeTab === 'resources' && <RCCResourceBoard />}
          {activeTab === 'decisions' && <RCCDecisionHub />}
          {activeTab === 'analysis' && <RCCAnalysis />}
          {activeTab === 'logic' && <LogicChainView />}
          {activeTab === 'neural' && <NeuralGraph tasks={tasks} inbox={inbox} baseline={baseline} factoryId={factoryId} />}
          {activeTab === 'approvals' && <RCCApprovalCenter onApproved={loadAll} />}
          {activeTab === 'logs' && <LogStream />}

          {/* AI 调度（设计稿排版：hero + 流水线 + 方案卡网格） */}
          {activeTab === 'ai' && (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <div style={{ background: 'linear-gradient(135deg,#F8FAFF,#F5FBFB)', border: '1px solid #DDE7F3', borderRadius: 14, padding: '14px 15px' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                  <div style={{ width: 36, height: 36, borderRadius: 10, background: 'linear-gradient(135deg,#315DAA,#087F8C)', color: '#fff', display: 'grid', placeItems: 'center', fontWeight: 900 }}><RobotOutlined /></div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 850 }}>RCC 智能调度引擎</div>
                    <div style={{ fontSize: 10.8, color: C.text3, marginTop: 3 }}>智能体受阻自动提交调度申请 → 审批通过回写解除阻塞 → scanner 自动继续</div>
                  </div>
                  <Space>
                    <span style={{ fontWeight: 750, fontSize: 10, fontFamily: 'monospace', padding: '4px 8px', borderRadius: 12, background: C.warnSoft, color: C.warn }}>{pending.length} 待审批</span>
                    <span style={{ fontWeight: 750, fontSize: 10, fontFamily: 'monospace', padding: '4px 8px', borderRadius: 12, background: C.successSoft, color: C.success }}>{tasks.filter((t: any) => t.status === 'approved').length} 已批准</span>
                  </Space>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,1fr)', gap: 7, marginTop: 13 }}>
                  {['受阻提交', 'RCC 受理', '智能匹配', '人工审批', '回写续跑'].map((s, i) => (
                    <div key={s} style={{ border: `1px solid ${i <= 1 ? '#AFC4EA' : C.border}`, background: i <= 1 ? C.brandSoft : '#fff', borderRadius: 9, padding: '8px 9px', minHeight: 44 }}>
                      <b style={{ display: 'block', fontSize: 10.5, color: i <= 1 ? C.brand2 : C.text }}>{i + 1}. {s}</b>
                      <span style={{ display: 'block', fontSize: 9.5, color: C.text3, marginTop: 3 }}>{['智能体 blocked 自动提交', '任务进入审批队列', '按类型/资源匹配', '批准 / 拒绝', '状态机自动接管'][i]}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,minmax(0,1fr))', gap: 10 }}>
                {pending.length === 0 && <div style={{ gridColumn: '1/-1', padding: 40, textAlign: 'center', color: C.text3, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14 }}>暂无待审批调度申请</div>}
                {pending.slice(0, 6).map((t: any) => {
                  const tm = TYPE_META[t.task_type] || { label: t.task_type, color: C.brand, soft: C.brandSoft }
                  return (
                    <div key={t.id} style={{ border: t.task_type === 'approval' ? '1px solid #F0B7B7' : `1px solid ${C.border}`, borderRadius: 11, background: '#fff', padding: 12 }}>
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

          {/* 资源负荷 */}
          {activeTab === 'capacity' && (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden' }}>
                <div style={{ display: 'flex', alignItems: 'center', padding: '13px 15px', borderBottom: `1px solid ${C.border}` }}>
                  <b style={{ fontSize: 13 }}>设备负荷与 OEE</b><span style={{ fontSize: 10.5, color: C.text3, marginLeft: 8 }}>Equipment Utilization</span>
                  <span style={{ marginLeft: 'auto', fontSize: 10, fontFamily: 'monospace', color: C.cyan, background: C.cyanSoft, padding: '3px 7px', borderRadius: 10 }}>LIVE</span>
                </div>
                <div style={{ padding: '4px 14px 8px' }}>
                  {equipTotal === 0 && <div style={{ padding: 30, textAlign: 'center', color: C.text3, fontSize: 12 }}>暂无设备基线数据</div>}
                  {/* 设备状态分布 */}
                  {Object.entries(equipStatuses).map(([st, cnt]: any) => {
                    const pct = equipTotal > 0 ? Math.round((cnt as number) / equipTotal * 100) : 0
                    const status = st === 'broken' || st === 'fault' ? 'danger' : st === 'maintenance' ? 'warn' : 'ok'
                    const label = { running: '运行中', broken: '故障', maintenance: '维护中', idle: '空闲' }[st] || st
                    return (
                      <div key={st} style={{ display: 'grid', gridTemplateColumns: '185px minmax(200px,1fr) 92px 100px', gap: 12, alignItems: 'center', padding: '12px 4px', borderBottom: `1px solid ${C.border}` }}>
                        <div><div style={{ fontSize: 12.5, fontWeight: 720 }}>{label}</div><div style={{ fontSize: 10.5, color: C.text3, marginTop: 3 }}>{cnt} 台</div></div>
                        <div style={{ height: 20, borderRadius: 6, background: '#EEF1F5', position: 'relative', overflow: 'hidden' }}>
                          <div style={{ height: '100%', borderRadius: 6, background: status === 'danger' ? 'linear-gradient(90deg,#B36A12,#D64545)' : status === 'ok' ? 'linear-gradient(90deg,#157C4F,#38A873)' : 'linear-gradient(90deg,#315DAA,#4F7CC7)', width: `${Math.min(pct, 100)}%`, position: 'relative' }}>
                            <span style={{ fontWeight: 700, fontSize: 12, fontFamily: 'monospace', color: '#fff', position: 'absolute', left: 8, top: 2 }}>{pct}%</span>
                          </div>
                        </div>
                        <span style={{ fontSize: 10.5, fontWeight: 800, padding: '3px 7px', borderRadius: 10, textAlign: 'center', background: status === 'danger' ? C.dangerSoft : status === 'warn' ? C.warnSoft : C.successSoft, color: status === 'danger' ? C.danger : status === 'warn' ? C.warn : C.success }}>{status === 'danger' ? '异常' : status === 'warn' ? '维护' : '正常'}</span>
                        <div style={{ textAlign: 'right', fontSize: 10.5, color: C.text3 }}><b style={{ display: 'block', color: C.text2, fontFamily: 'monospace', fontSize: 11.5 }}>{cnt}</b>台</div>
                      </div>
                    )
                  })}
                  {/* OEE 概览 */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, padding: '12px 4px' }}>
                    {[['OEE 实际', equipment.oee_actual_pct], ['OEE 目标', equipment.oee_target_pct], ['PM 逾期', equipment.pm_overdue_count], ['设备总数', equipTotal]].map(([k, v]: any) => (
                      <div key={k} style={{ border: `1px solid ${C.border}`, borderRadius: 9, padding: 9, background: C.surface }}>
                        <div style={{ fontSize: 9.5, color: C.text3 }}>{k}</div>
                        <div style={{ fontSize: 15, fontFamily: 'monospace', fontWeight: 800, color: typeof v === 'number' && v > 0 && k.includes('逾期') ? C.danger : C.text }}>{v}{typeof v === 'number' && k.includes('OEE') ? '%' : ''}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden' }}>
                <div style={{ display: 'flex', alignItems: 'center', padding: '13px 15px', borderBottom: `1px solid ${C.border}` }}><b style={{ fontSize: 13 }}>人员负荷</b><span style={{ fontSize: 10.5, color: C.text3, marginLeft: 8 }}>People & Skills</span></div>
                <div style={{ padding: '4px 14px 8px' }}>
                  {peopleCount === 0 && <div style={{ padding: 30, textAlign: 'center', color: C.text3, fontSize: 12 }}>暂无人员基线数据</div>}
                  {/* 人员总览 + 技能分布 */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 8, padding: '12px 4px' }}>
                    {[['在岗人数', peopleCount], ['出勤率', `${people.attendance_rate_pct || 0}%`], ['缺勤预警', people.alert_count || 0], ['技能等级', Object.keys(people.skills || {}).length]].map(([k, v]: any) => (
                      <div key={k} style={{ border: `1px solid ${C.border}`, borderRadius: 9, padding: 9, background: C.surface }}>
                        <div style={{ fontSize: 9.5, color: C.text3 }}>{k}</div>
                        <div style={{ fontSize: 15, fontFamily: 'monospace', fontWeight: 800, color: String(v).includes('%') ? C.success : C.text }}>{v}</div>
                      </div>
                    ))}
                  </div>
                  {/* 技能等级分布 */}
                  {Object.entries(people.skills || {}).map(([lv, cnt]: any) => {
                    const max = Math.max(...Object.values(people.skills || {}).map(Number), 1)
                    const pct = Math.round((cnt as number) / max * 100)
                    return (
                      <div key={lv} style={{ display: 'grid', gridTemplateColumns: '185px minmax(200px,1fr) 92px', gap: 12, alignItems: 'center', padding: '12px 4px', borderBottom: `1px solid ${C.border}` }}>
                        <div><div style={{ fontSize: 12.5, fontWeight: 720 }}>技能等级 {lv}</div><div style={{ fontSize: 10.5, color: C.text3, marginTop: 3 }}>{cnt} 人</div></div>
                        <div style={{ height: 20, borderRadius: 6, background: '#EEF1F5', position: 'relative', overflow: 'hidden' }}>
                          <div style={{ height: '100%', borderRadius: 6, background: 'linear-gradient(90deg,#315DAA,#4F7CC7)', width: `${pct}%` }}><span style={{ fontWeight: 700, fontSize: 12, fontFamily: 'monospace', color: '#fff', position: 'absolute', left: 8, top: 2 }}>{pct}%</span></div>
                        </div>
                        <span style={{ fontSize: 10.5, color: C.text3 }}>{lv === 'L5' ? '专家' : lv === 'L4' ? '高级' : lv === 'L3' ? '中级' : '初级'}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </Space>
          )}

          {/* 任务队列 */}
          {activeTab === 'dispatch' && (
            <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden' }}>
              <div style={{ display: 'flex', alignItems: 'center', padding: '13px 15px', borderBottom: `1px solid ${C.border}` }}>
                <b style={{ fontSize: 13 }}>全厂任务队列</b><span style={{ fontSize: 10.5, color: C.text3, marginLeft: 8 }}>所有人员 / 智能体的任务 · 含归属人</span>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 11, fontSize: 10.5, color: C.text3 }}>
                  <span><i style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: C.brand, marginRight: 4 }} />跟进中 {openTasks.length}</span>
                  <span><i style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: C.danger, marginRight: 4 }} />受阻 {blockedTasks.length}</span>
                </div>
                <Input prefix={<SearchOutlined style={{ color: C.text3 }} />} placeholder="搜索任务/归属人/智能体" value={query} onChange={e => setQuery(e.target.value)} style={{ width: 200, height: 30, marginLeft: 12, borderColor: C.borderStrong }} />
              </div>
              <div style={{ overflow: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 1100 }}>
                  <thead><tr style={{ background: C.surface, borderBottom: `1px solid ${C.border}` }}>
                    {['任务', '归属人', '智能体', '状态', '进度', '卡点', '最近结论'].map(h => <th key={h} style={{ padding: '10px 11px', fontSize: 10.5, color: C.text3, textAlign: 'left' }}>{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {filteredTasks.length === 0 && <tr><td colSpan={7} style={{ padding: 40, textAlign: 'center', color: C.text3, fontSize: 12 }}>暂无任务</td></tr>}
                    {filteredTasks.slice(0, 30).map((t: any) => {
                      const st = TASK_STATUS[t.status] || { label: t.status, color: C.text3, soft: '#F0F2F6' }
                      return (
                        <tr key={t.id} style={{ borderBottom: `1px solid ${C.border}`, opacity: t.status === 'done' ? .64 : 1 }}>
                          <td style={{ padding: 11, fontSize: 11.8 }}><div style={{ fontWeight: 700, color: C.text, maxWidth: 240 }}>{t.title}</div><span style={{ display: 'block', fontSize: 10, fontFamily: 'monospace', color: C.text3, marginTop: 3 }}>{t.item_type || 'followup'}</span></td>
                          <td style={{ padding: 11 }}><div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                            <div style={{ width: 25, height: 25, borderRadius: '50%', background: C.brandSoft, color: C.brand2, display: 'grid', placeItems: 'center', fontSize: 9.5, fontWeight: 850 }}>{(t.created_by || '?')[0].toUpperCase()}</div>
                            <div><div style={{ fontSize: 11, fontWeight: 750 }}>{t.created_by}</div><div style={{ fontSize: 9.5, color: C.text3 }}>{t.assigned_to ? `→ ${t.assigned_to}` : '未指派'}</div></div>
                          </div></td>
                          <td style={{ padding: 11 }}><span style={{ borderRadius: 7, padding: '3px 7px', fontSize: 10.5, fontWeight: 750, background: C.cyanSoft, color: C.cyan, whiteSpace: 'nowrap' }}>{t.agent_name || '通用'}</span></td>
                          <td style={{ padding: 11 }}><span style={{ borderRadius: 7, padding: '3px 7px', fontSize: 10.5, fontWeight: 750, background: st.soft, color: st.color, whiteSpace: 'nowrap' }}>{st.label}</span></td>
                          <td style={{ padding: 11, minWidth: 90 }}><div style={{ height: 6, background: '#EEF1F5', borderRadius: 6, overflow: 'hidden', width: 80 }}><div style={{ height: '100%', borderRadius: 6, background: t.status === 'blocked' ? C.warn : t.status === 'done' ? C.success : C.brand, width: `${Math.min(t.progress_pct || 0, 100)}%` }} /></div><span style={{ fontSize: 10, fontFamily: 'monospace', color: C.text3, marginTop: 3, display: 'block' }}>{t.progress_pct || 0}%</span></td>
                          <td style={{ padding: 11 }}>{t.blocked_by ? <span style={{ borderRadius: 7, padding: '3px 7px', fontSize: 10.5, fontWeight: 750, background: C.warnSoft, color: C.warn, whiteSpace: 'nowrap' }}>⛔ {t.blocked_by}{t.block_category ? ` / ${t.block_category}` : ''}</span> : <span style={{ color: C.text3, fontSize: 10.5 }}>—</span>}</td>
                          <td style={{ padding: 11, maxWidth: 260 }}><div style={{ fontSize: 10.5, color: C.text2, lineHeight: 1.45, maxHeight: 40, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>{t.last_follow_note || t.ai_summary || '尚未跟进'}</div></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          </RccContext.Provider>
        </main>


      </div>
    </div>
  )
}

/** 逻辑链视图（提供默认 props） */
function LogicChainView() {
  const [chains, setChains] = useState<any[]>([])
  useEffect(() => {
    axios.get(`${API}/rcc/logic-chains`).then(r => setChains(r.data?.items || r.data?.chains || [])).catch(() => {})
  }, [])
  const [editing, setEditing] = useState<any>(null)
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {chains.length === 0 && (
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, padding: 40, textAlign: 'center', color: C.text3, fontSize: 12 }}>
          暂无逻辑链数据 —— 创建或选择一条逻辑链进行编排
        </div>
      )}
      {chains.slice(0, 6).map((c: any) => (
        <div key={c.id} style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 12, padding: 12, display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ fontSize: 12.5, fontWeight: 750, flex: 1 }}>{c.name || c.trigger || c.id}</div>
          <Tag color="blue">{c.status || 'active'}</Tag>
          <Button size="small" onClick={() => setEditing(c)}>打开编排</Button>
        </div>
      ))}
      {editing && <LogicChainEditor chain={editing} onClose={() => setEditing(null)} onSaved={() => setEditing(null)} />}
    </Space>
  )
}

/** 调度日志流 */
function LogStream() {
  const [logs, setLogs] = useState<any[]>([])
  useEffect(() => {
    axios.get(`${API}/rcc/tasks`, { params: { page_size: 20 } }).then(r => {
      const items = r.data?.items || []
      setLogs(items.map((t: any) => ({ time: (t.created_at || '').slice(11, 19), agent: t.requested_by || '系统', msg: `${t.title}（${t.task_type}）`, result: t.status })))
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
          <span style={{ textAlign: 'right' }}><span style={{ fontSize: 10, fontWeight: 800, padding: '2px 6px', borderRadius: 8, background: l.result === 'approved' ? C.successSoft : l.result === 'pending' ? C.warnSoft : C.cyanSoft, color: l.result === 'approved' ? C.success : l.result === 'pending' ? C.warn : C.cyan }}>{l.result}</span></span>
        </div>
      ))}
    </div>
  )
}
