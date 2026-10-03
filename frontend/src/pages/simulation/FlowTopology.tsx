import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Button, Drawer, Input, InputNumber, Popconfirm, Segmented, Select, Slider, Space, Tooltip, Typography,
} from 'antd'
import {
  ApartmentOutlined, AppstoreOutlined, BankOutlined, CheckCircleOutlined, ClockCircleOutlined,
  DeleteOutlined, DeploymentUnitOutlined, FlagOutlined, HolderOutlined, InboxOutlined,
  LeftOutlined, PlusOutlined, RightOutlined, AimOutlined, TeamOutlined, ToolOutlined, WarningOutlined,
  ZoomInOutlined, ZoomOutOutlined,
} from '@ant-design/icons'
import {
  FactoryKPIs, FactorySimConfig, FactorySimResult, ProductionStrategy, SectionConfig, SectionSummary,
  WorkshopConfig,
} from '../../services/factorySim'

/* ====================================================================
 * 产线组态编辑器（拓扑画布）
 * - 工艺路线驱动的 DAG 分层自动布局（longest-path 分层 + 同层垂直堆叠）
 * - 无限画布：背景拖拽平移 / 滚轮缩放 / 适应画布 / Mini-map 视口导航
 * - 流量边：虚线流动速度随实际工时，颜色随目标工段负荷过载渐变
 * - 工段卡片 HTML5 拖拽跨车间移动，点击节点 → 右侧属性抽屉改参
 * ==================================================================== */

const { Text } = Typography

/* ---------- 布局常量 ---------- */
const WS_W = 252
const WS_HEAD = 38
const WS_PAD = 10
const CARD_H = 100
const CARD_GAP = 8
const END_W = 132
const END_H = 100
const COL_GAP = 150
const ROW_GAP = 28
const ORIGIN_X = 56
const ORIGIN_Y = 64

/* ---------- 视口常量 ---------- */
const ZOOM_MIN = 0.35
const ZOOM_MAX = 2.5
const MM_W = 196
const MM_H = 126

type Pos = { x: number; y: number }
type Sel = { type: 'workshop' | 'section'; id: string } | null
type DropHint = { wsId: string; beforeSid: string | null } | null
type Viewport = { tx: number; ty: number; zoom: number }
type BBox = { x0: number; y0: number; x1: number; y1: number }

const wsBodyH = (n: number) => (n === 0 ? 48 : n * (CARD_H + CARD_GAP) - CARD_GAP)
const wsTotalH = (n: number) => WS_HEAD + WS_PAD * 2 + wsBodyH(n)

/** 负荷率 → 热力色 */
const heat = (rate: number): string => {
  const t = Math.min(Math.max(rate, 0), 1.3) / 1.3
  return `hsl(${120 - t * 120}, 72%, ${54 - t * 8}%)`
}
const pct = (v: number) => `${Math.round(v * 100)}%`

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

interface Props {
  config: FactorySimConfig
  result: FactorySimResult | null
  scenarioId: string
  /** 后台 WHAT-IF 推演进行中 */
  computing?: boolean
  /** 场景初始 KPI，用于显示改参数后的增量 */
  baseline?: FactoryKPIs | null
  onPatchSection: (sid: string, p: Partial<SectionConfig>) => void
  onPatchWorkshop: (wid: string, p: Partial<WorkshopConfig>) => void
  onAddWorkshop: () => void
  onAddSection: (workshopId: string) => void
  onRemoveWorkshop: (wid: string) => void
  onRemoveSection: (sid: string) => void
  onMoveSection: (sid: string, targetWid: string, beforeSid: string | null) => void
  onReorderSections: (order: Record<string, string[]>) => void
}

/**
 * WHAT-IF 参照指标。引擎产能取 min(人力, 机台)，且需求超出产能的部分不计入负载，
 * 所以负荷率对增减人手几乎不动——真正随参数移动的是交付与积压指标。
 */
const KPI_METRICS: { key: keyof FactoryKPIs; label: string; unit: string; goodUp: boolean }[] = [
  { key: 'on_time_rate', label: '准时率', unit: 'pct', goodUp: true },
  { key: 'delayed_orders', label: '延期', unit: '单', goodUp: false },
  { key: 'total_unmet_hours', label: '缺口', unit: 'h', goodUp: false },
  { key: 'wip_peak', label: 'WIP 峰', unit: '件', goodUp: false },
  { key: 'bottleneck_sections', label: '瓶颈', unit: '个', goodUp: false },
]

const kpiText = (key: keyof FactoryKPIs, v: number) =>
  key === 'on_time_rate' ? `${Math.round(v * 100)}%` : `${Math.round(v)}`

/** 产能钳位来源 → 短标 / 可行动建议（决定"加人"这个动作有没有意义） */
const BIND_SHORT: Record<string, string> = { labor: '钳:人', machine: '钳:机', both: '钳:人机' }
const BIND_ADVICE: Record<string, string> = {
  labor: '人力钳位：加人或加班次可直接增产',
  machine: '机台钳位：加人不会增产，需加机台或外协',
  both: '人机同时钳位：需按同一比例加人与加机台',
}

/* ====================================================================
 * 工艺分层：把 routings 当 DAG，节点=工段，边=相邻工序
 * ==================================================================== */
/** 工段工艺层级（0=首工序）；迭代松弛，返工环最多推进 MAX_PASS 层 */
const buildSectionRanks = (cfg: FactorySimConfig): Map<string, number> => {
  const MAX_PASS = 24
  const rank = new Map<string, number>()
  const preds = new Map<string, string[]>()
  cfg.sections.forEach((s) => { rank.set(s.section_id, 0); preds.set(s.section_id, []) })

  cfg.routings.forEach((r) => {
    const seq = [...r.operations]
      .sort((a, b) => a.op_no - b.op_no)
      .map((o) => o.section_id)
      .filter((sid) => rank.has(sid))
    for (let i = 1; i < seq.length; i++) {
      if (seq[i] === seq[i - 1]) continue
      const p = preds.get(seq[i])!
      if (!p.includes(seq[i - 1])) p.push(seq[i - 1])
    }
  })

  for (let pass = 0; pass < MAX_PASS; pass++) {
    let moved = false
    rank.forEach((cur, sid) => {
      (preds.get(sid) || []).forEach((pid) => {
        const want = (rank.get(pid) ?? 0) + 1
        if (want > cur && want <= MAX_PASS) { rank.set(sid, want); moved = true }
      })
    })
    if (!moved) break
  }
  return rank
}

/** 车间 → 分层列，列内垂直堆叠；返回节点坐标与车间内工段顺序 */
const autoLayout = (cfg: FactorySimConfig): { positions: Record<string, Pos>; order: Record<string, string[]> } => {
  const ranks = buildSectionRanks(cfg)
  const sectionsOf = (wid: string) => cfg.sections.filter((s) => s.workshop_id === wid)

  const order: Record<string, string[]> = {}
  cfg.workshops.forEach((w) => {
    order[w.workshop_id] = [...sectionsOf(w.workshop_id)]
      .sort((a, b) => (ranks.get(a.section_id)! - ranks.get(b.section_id)!)
        || a.name.localeCompare(b.name))
      .map((s) => s.section_id)
  })

  const heightOf = (wid: string) => wsTotalH(sectionsOf(wid).length)
  const meanRank = (w: WorkshopConfig) => {
    const rs = sectionsOf(w.workshop_id).map((s) => ranks.get(s.section_id) ?? 0)
    return rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : 0
  }

  // 工艺流向：按车间平均层级排序，层级相近（<1 层）的并到同一列
  const sorted = cfg.workshops
    .map((w, i) => ({ w, r: meanRank(w), i }))
    .sort((a, b) => a.r - b.r || a.i - b.i)
  const cols: { r: number; items: WorkshopConfig[]; h: number }[] = []
  sorted.forEach(({ w, r }) => {
    const last = cols[cols.length - 1]
    if (last && r - last.r < 1) { last.items.push(w); last.h += heightOf(w.workshop_id) + ROW_GAP }
    else cols.push({ items: [w], r, h: heightOf(w.workshop_id) })
  })

  const colH = cols.map((c) => c.h - ROW_GAP)
  const midY = ORIGIN_Y + Math.max(160, ...colH) / 2

  const positions: Record<string, Pos> = {}
  cols.forEach((c, ci) => {
    let y = midY - c.h / 2
    c.items.forEach((w) => {
      positions[w.workshop_id] = { x: ORIGIN_X + END_W + COL_GAP + ci * (WS_W + COL_GAP), y }
      y += heightOf(w.workshop_id) + ROW_GAP
    })
  })

  const lastX = ORIGIN_X + END_W + COL_GAP + Math.max(0, cols.length - 1) * (WS_W + COL_GAP)
  positions['POOL'] = { x: ORIGIN_X, y: midY - END_H / 2 }
  positions['OUT'] = { x: lastX + WS_W + COL_GAP, y: midY - END_H / 2 }
  return { positions, order }
}

/** 所有节点（含尺寸）的包围盒 */
const bboxOf = (cfg: FactorySimConfig, pos: Record<string, Pos>): BBox => {
  const pts: { id: string; w: number; h: number }[] = [
    ...cfg.workshops.map((w) => ({
      id: w.workshop_id, w: WS_W, h: wsTotalH(cfg.sections.filter((s) => s.workshop_id === w.workshop_id).length),
    })),
    { id: 'POOL', w: END_W, h: END_H },
    { id: 'OUT', w: END_W, h: END_H },
  ]
  let x0 = 0, y0 = 0, x1 = 1200, y1 = 600
  pts.forEach(({ id, w, h }) => {
    const p = pos[id]
    if (!p) return
    x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y)
    x1 = Math.max(x1, p.x + w); y1 = Math.max(y1, p.y + h)
  })
  return { x0, y0, x1, y1 }
}

/* ==================================================================== */

const FlowTopology: React.FC<Props> = ({
  config, result, scenarioId, computing, baseline,
  onPatchSection, onPatchWorkshop, onAddWorkshop, onAddSection,
  onRemoveWorkshop, onRemoveSection, onMoveSection, onReorderSections,
}) => {
  const live = !!result

  /* ---------- 布局 / 视口状态 ---------- */
  const [positions, setPositions] = useState<Record<string, Pos>>({})
  const [vp, setVp] = useState<Viewport>({ tx: 0, ty: 0, zoom: 1 })
  const [sel, setSel] = useState<Sel>(null)
  const [dragSec, setDragSec] = useState<string | null>(null)
  const [dropHint, setDropHint] = useState<DropHint>(null)
  const [panning, setPanning] = useState(false)
  const [showMM, setShowMM] = useState(true)

  const dragRef = useRef<{ id: string; sx: number; sy: number; ox: number; oy: number } | null>(null)
  const panRef = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null)
  const mmRef = useRef<{ sx: number; sy: number } | null>(null)
  const viewportEl = useRef<HTMLDivElement | null>(null)
  const zoomRef = useRef(1)
  const [stage, setStage] = useState({ w: 1180, h: 540 })

  zoomRef.current = vp.zoom

  /* ---------- 场景切换：localStorage 合并分层布局（新增车间补默认位，旧键丢弃） ---------- */
  useEffect(() => {
    const key = `topo-layout-v2-${scenarioId}`
    let saved: Record<string, Pos> = {}
    try { saved = JSON.parse(localStorage.getItem(key) || '{}') } catch { /* ignore */ }
    const base = autoLayout(config).positions
    const merged: Record<string, Pos> = {}
    Object.keys(base).forEach((k) => { merged[k] = saved[k] || base[k] })
    setPositions(merged)
    setVp({ tx: 0, ty: 0, zoom: 1 })
    setSel(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId, config.workshops.length])

  /* ---------- 布局变化 → 持久化 ---------- */
  useEffect(() => {
    if (!scenarioId || !Object.keys(positions).length) return
    try { localStorage.setItem(`topo-layout-v2-${scenarioId}`, JSON.stringify(positions)) } catch { /* ignore */ }
  }, [positions, scenarioId])

  /* ---------- 舞台尺寸跟踪（适应画布 / mini-map 视口框） ---------- */
  useEffect(() => {
    const el = viewportEl.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => setStage({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    setStage({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  /* ---------- 派生数据 ---------- */
  const sectionsOf = useCallback(
    (wid: string) => config.sections.filter((s) => s.workshop_id === wid),
    [config.sections],
  )

  /** 工艺层级（车间内工段排序参考） */
  const ranks = useMemo(() => buildSectionRanks(config), [config])

  /** 工艺路线引用次数（工段卡片角标） */
  const routeCount = useMemo(() => {
    const m = new Map<string, number>()
    config.routings.forEach((r) => r.operations.forEach((op) => m.set(op.section_id, (m.get(op.section_id) || 0) + 1)))
    return m
  }, [config.routings])

  /** 流转边：仿真后 = 实际工时；仿真前 = 工艺路线条数 */
  const edges = useMemo(() => {
    const m = new Map<string, number>()
    const add = (from: string, to: string, w: number) => {
      const k = `${from}>${to}`
      m.set(k, (m.get(k) || 0) + w)
    }
    if (result) {
      result.orders.forEach((o) => {
        const ops = [...o.ops].sort((a, b) => a.op_no - b.op_no)
        if (!ops.length) return
        add('POOL', ops[0].section_id, ops[0].work_hours)
        add(ops[ops.length - 1].section_id, 'OUT', ops[ops.length - 1].work_hours)
        for (let i = 1; i < ops.length; i++) {
          if (ops[i].section_id !== ops[i - 1].section_id) add(ops[i - 1].section_id, ops[i].section_id, ops[i].work_hours)
        }
      })
    } else {
      config.routings.forEach((r) => {
        const ops = [...r.operations].sort((a, b) => a.op_no - b.op_no)
        if (!ops.length) return
        add('POOL', ops[0].section_id, 1)
        add(ops[ops.length - 1].section_id, 'OUT', 1)
        for (let i = 1; i < ops.length; i++) {
          if (ops[i].section_id !== ops[i - 1].section_id) add(ops[i - 1].section_id, ops[i].section_id, 1)
        }
      })
    }
    return m
  }, [config.routings, result])
  const maxFlow = Math.max(1, ...edges.values())

  const stats = useMemo(() => {
    const m = new Map<string, SectionSummary>()
    result?.sections.forEach((s) => m.set(s.section_id, s))
    return m
  }, [result])

  /* ---------- 画布内容包围盒 → 世界尺寸（含平移余量，保证连不裁边） ---------- */
  const bbox = useMemo(() => bboxOf(config, positions), [config, positions])
  const world = useMemo(() => ({
    w: Math.max(1400, bbox.x1 + 400),
    h: Math.max(760, bbox.y1 + 400),
  }), [bbox])

  /** 节点锚点（连线出入口） */
  const anchor = useCallback((id: string, side: 'l' | 'r'): Pos => {
    if (id === 'POOL' || id === 'OUT') {
      const p = positions[id] || { x: 0, y: 0 }
      return { x: side === 'r' ? p.x + END_W : p.x, y: p.y + END_H / 2 }
    }
    const sec = config.sections.find((s) => s.section_id === id)
    if (!sec) return { x: 0, y: 0 }
    const wp = positions[sec.workshop_id] || { x: 0, y: 0 }
    const idx = Math.max(0, sectionsOf(sec.workshop_id).findIndex((s) => s.section_id === id))
    return {
      x: side === 'r' ? wp.x + WS_W : wp.x,
      y: wp.y + WS_HEAD + WS_PAD + idx * (CARD_H + CARD_GAP) + CARD_H / 2,
    }
  }, [positions, config.sections, sectionsOf])

  /* ---------- 视口操作 ---------- */
  const stageWH = () => {
    const el = viewportEl.current
    return { w: el?.clientWidth || 1180, h: el?.clientHeight || 540 }
  }

  const zoomAt = useCallback((factor: number, cx?: number, cy?: number) => {
    setVp((v) => {
      const nz = clamp(Number((v.zoom * factor).toFixed(3)), ZOOM_MIN, ZOOM_MAX)
      const k = nz / v.zoom
      const px = cx ?? stageWH().w / 2
      const py = cy ?? stageWH().h / 2
      return { zoom: nz, tx: px - (px - v.tx) * k, ty: py - (py - v.ty) * k }
    })
  }, [])

  /** 把内容包围盒居中缩放到位 */
  const fitTo = useCallback((pos: Record<string, Pos>) => {
    const b = bboxOf(config, pos)
    const { w: sw, h: sh } = stageWH()
    const bw = b.x1 - b.x0, bh = b.y1 - b.y0
    if (bw <= 0 || bh <= 0) return
    const z = clamp(Math.min((sw - 48) / bw, (sh - 48) / bh), ZOOM_MIN, 1.2)
    setVp({ zoom: z, tx: (sw - bw * z) / 2 - b.x0 * z, ty: (sh - bh * z) / 2 - b.y0 * z })
  }, [config])

  const fitView = useCallback(() => fitTo(positions), [fitTo, positions])

  /* 进入场景 / 切场景：布局完成后把内容整体缩放到视野内 */
  const fittedRef = useRef('')
  useEffect(() => {
    if (!scenarioId || !Object.keys(positions).length || fittedRef.current === scenarioId) return
    fittedRef.current = scenarioId
    fitTo(positions)
  }, [scenarioId, positions, fitTo])

  /* 滚轮缩放（需要非 passive 监听才能拦截页面滚动） */
  useEffect(() => {
    const el = viewportEl.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - rect.left, e.clientY - rect.top)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomAt])

  /* ---------- 指针拖拽：节点移动（车间 / 端点） ---------- */
  const startDrag = useCallback((e: React.PointerEvent, id: string) => {
    if ((e.target as HTMLElement).closest('button, input, select, a')) return
    const p = positions[id]
    if (!p) return
    dragRef.current = { id, sx: e.clientX, sy: e.clientY, ox: p.x, oy: p.y }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }, [positions])

  const moveDrag = useCallback((e: React.PointerEvent) => {
    const d = dragRef.current
    if (!d) return
    const z = zoomRef.current || 1
    setPositions((prev) => ({
      ...prev,
      [d.id]: { x: d.ox + (e.clientX - d.sx) / z, y: d.oy + (e.clientY - d.sy) / z },
    }))
  }, [])

  const endDrag = useCallback(() => { dragRef.current = null }, [])

  /* ---------- 指针拖拽：背景平移（无限画布，挂视口保证留白区也可拖） ---------- */
  const startPan = useCallback((e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('.topo-ws, .topo-end, .topo-mm, .topo-stage-tools')) return
    panRef.current = { sx: e.clientX, sy: e.clientY, ox: vp.tx, oy: vp.ty }
    setPanning(true)
    setSel(null)
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }, [vp])

  const movePan = useCallback((e: React.PointerEvent) => {
    const p = panRef.current
    if (!p) return
    setVp((v) => ({ ...v, tx: p.ox + (e.clientX - p.sx), ty: p.oy + (e.clientY - p.sy) }))
  }, [])

  const endPan = useCallback(() => { panRef.current = null; setPanning(false) }, [])

  /* ---------- Mini-map：世界 ↔ 小地图换算 ---------- */
  const mm = useMemo(() => {
    const bw = bbox.x1 - bbox.x0, bh = bbox.y1 - bbox.y0
    const s = Math.min((MM_W - 12) / bw, (MM_H - 12) / bh)
    const ox = (MM_W - bw * s) / 2 - bbox.x0 * s
    const oy = (MM_H - bh * s) / 2 - bbox.y0 * s
    return { s, ox, oy }
  }, [bbox])

  /** mini-map 当前可视窗口 */
  const mmView = useMemo(() => ({
    x: mm.ox + (-vp.tx / vp.zoom) * mm.s,
    y: mm.oy + (-vp.ty / vp.zoom) * mm.s,
    w: (stage.w / vp.zoom) * mm.s,
    h: (stage.h / vp.zoom) * mm.s,
  }), [mm, vp, stage])

  const mmJump = useCallback((e: React.PointerEvent) => {
    const el = e.currentTarget as HTMLElement
    const rect = el.getBoundingClientRect()
    const wx = (e.clientX - rect.left - mm.ox) / mm.s
    const wy = (e.clientY - rect.top - mm.oy) / mm.s
    setVp((v) => ({ ...v, tx: stage.w / 2 - wx * v.zoom, ty: stage.h / 2 - wy * v.zoom }))
  }, [mm, stage])

  const onMmDown = (e: React.PointerEvent) => {
    mmRef.current = { sx: e.clientX, sy: e.clientY }
    mmJump(e)
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }
  const onMmMove = (e: React.PointerEvent) => { if (mmRef.current) mmJump(e) }
  const onMmUp = () => { mmRef.current = null }

  /* ---------- 自动布局（分层 + 车间内工艺排序 + 适应画布） ---------- */
  const applyAutoLayout = useCallback(() => {
    const { positions: p, order } = autoLayout(config)
    setPositions(p)
    onReorderSections(order)
    fitTo(p)
  }, [config, onReorderSections, fitTo])

  /* ---------- 工段拖放（HTML5 DnD） ---------- */
  const onSecDragStart = (e: React.DragEvent, sid: string) => {
    setDragSec(sid)
    e.dataTransfer.setData('text/plain', sid)
    e.dataTransfer.effectAllowed = 'move'
  }
  const clearDrag = () => { setDragSec(null); setDropHint(null) }
  const onSecDrop = (e: React.DragEvent, wsId: string, beforeSid: string | null) => {
    e.preventDefault()
    e.stopPropagation()
    const sid = e.dataTransfer.getData('text/plain') || dragSec
    if (sid && sid !== beforeSid) onMoveSection(sid, wsId, beforeSid)
    clearDrag()
  }

  /* ---------- 选中对象 ---------- */
  const selSection = sel?.type === 'section' ? config.sections.find((s) => s.section_id === sel.id) : undefined
  const selWorkshop = sel?.type === 'workshop' ? config.workshops.find((w) => w.workshop_id === sel.id) : undefined

  const totalQty = config.orders.reduce((s, o) => s + o.quantity, 0)

  /** 边的视觉编码：颜色/流速随目标工段的需求压力率，缺口工时如实标注 */
  const edgeVisual = (to: string, w: number) => {
    const t = Math.min(1, w / maxFlow)
    const st = stats.get(to)
    const ot = st?.overtime_used_hours ?? 0
    const unmet = st?.unmet_hours ?? 0
    // 负荷率受加班上限钳位（最高只有 1.2），压力率才是真实超载倍数，故以两者较大值判堵
    const sev = to === 'POOL' || to === 'OUT'
      ? 0
      : Math.max(st?.pressure_rate ?? 0, st?.peak_load_rate ?? 0)
    if (!live) {
      return { stroke: 'rgba(120,155,185,0.42)', width: 1.5 + t * 2, dur: 1.6, marker: 'idle', ot, unmet, sev }
    }
    if (sev >= 1) {
      return {
        stroke: heat(Math.min(sev, 1.3)),
        width: 2.4 + t * 2.5,
        dur: 3.2 + Math.min(0.8, (sev - 1) * 1.2),
        marker: sev >= 1.15 ? 'danger' : 'warn',
        ot, unmet, sev,
      }
    }
    return { stroke: `rgba(54,207,201,${0.34 + t * 0.55})`, width: 1.5 + t * 2.5, dur: 2.4 - t * 1.7, marker: 'ok', ot, unmet, sev }
  }

  /* ================================================================== */

  return (
    <div className="sim-console" style={{ padding: '12px 16px 14px', marginBottom: 12 }}>
      <div style={{ position: 'relative', zIndex: 1 }}>
        {/* ── 工具条 ── */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Space size={10} align="baseline" wrap>
            <DeploymentUnitOutlined style={{ color: '#36cfc9', fontSize: 17 }} />
            <span style={{ color: '#fff', fontWeight: 800, fontSize: 15, letterSpacing: 2 }}>产线组态编辑器</span>
            <span style={{ color: 'rgba(255,255,255,0.38)', fontSize: 10, letterSpacing: 2 }}>TOPOLOGY EDITOR</span>
            <span style={{ color: 'rgba(255,255,255,0.55)', fontSize: 11 }}>
              拖空白平移 · 滚轮缩放 · 拖车间标题移位 · 拖工段卡片跨车间 · 改参数自动推演
            </span>
          </Space>
          <Space size={8} wrap>
            {computing ? (
              <span style={{ color: '#ffd666', fontSize: 11 }}><ClockCircleOutlined /> 推演中…</span>
            ) : live ? (
              <span style={{ color: '#95de64', fontSize: 11 }}><CheckCircleOutlined /> 已点亮仿真结果</span>
            ) : (
              <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: 11 }}>静态拓扑 · 运行仿真后点亮</span>
            )}
            <Tooltip title="缩小 (-)">
              <Button size="small" icon={<ZoomOutOutlined />} style={darkBtn} onClick={() => zoomAt(1 / 1.15)} />
            </Tooltip>
            <span style={{ color: 'rgba(255,255,255,0.65)', fontSize: 11, width: 40, textAlign: 'center' }}>{Math.round(vp.zoom * 100)}%</span>
            <Tooltip title="放大 (+)">
              <Button size="small" icon={<ZoomInOutlined />} style={darkBtn} onClick={() => zoomAt(1.15)} />
            </Tooltip>
            <Tooltip title="适应画布">
              <Button size="small" icon={<AimOutlined />} style={darkBtn} onClick={fitView} />
            </Tooltip>
            <Tooltip title="按工艺路线层级重排车间与工段">
              <Button size="small" icon={<AppstoreOutlined />} style={darkBtn} onClick={applyAutoLayout}>
                自动布局
              </Button>
            </Tooltip>
            <Button size="small" type="primary" ghost icon={<PlusOutlined />} onClick={onAddWorkshop}>
              新增车间
            </Button>
          </Space>
        </div>

        {/* ── WHAT-IF 增量对比（相对场景初始解算） ── */}
        {live && baseline && result && (
          <div className={`topo-whatif${computing ? ' dim' : ''}`}>
            <span className="topo-whatif-label">WHAT-IF</span>
            {KPI_METRICS.map((m) => {
              const cur = Number(result.kpis[m.key])
              const base = Number(baseline[m.key])
              const diff = cur - base
              const moved = Math.abs(diff) > 1e-9
              const good = m.goodUp ? diff > 0 : diff < 0
              const raw = m.key === 'on_time_rate' ? Math.round(diff * 100) : Math.round(diff)
              const delta = raw === 0 ? '±0'
                : `${raw > 0 ? '+' : '−'}${Math.abs(raw)}${m.key === 'on_time_rate' ? 'pp' : ''}`
              return (
                <span key={m.key} className="topo-whatif-item"
                  title={`${m.label}：场景初始 ${kpiText(m.key, base)}${m.unit === 'pct' ? '' : ' ' + m.unit}`}>
                  <em>{m.label}</em>
                  <b>{kpiText(m.key, base)}{m.unit === 'pct' ? '' : ' ' + m.unit}</b>
                  <i>→</i>
                  <strong>{kpiText(m.key, cur)}{m.unit === 'pct' ? '' : ' ' + m.unit}</strong>
                  <span className="topo-whatif-delta"
                    style={{ color: !moved ? 'rgba(255,255,255,0.32)' : good ? '#95de64' : '#ff7875' }}>
                    {delta}
                  </span>
                </span>
              )
            })}
            <span className="topo-whatif-hint">
              压力 = 需求/产能（不设上限）；标注 钳:机 的工段加人不会增产，只有加机台/外协能压掉缺口
            </span>
          </div>
        )}

        {/* ── 无限画布视口 ── */}
        <div
          ref={viewportEl}
          className={`topo-viewport${panning ? ' panning' : ''}`}
          style={{ height: 540, marginTop: 10 }}
          onPointerDown={startPan} onPointerMove={movePan} onPointerUp={endPan} onPointerCancel={endPan}
        >
          <div
            className="topo-bg"
            style={{
              width: world.w, height: world.h,
              transform: `translate(${vp.tx}px, ${vp.ty}px) scale(${vp.zoom})`,
              transformOrigin: '0 0',
            }}
          >
            {/* SVG 连线层 */}
            <svg width={world.w} height={world.h} style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
              <defs>
                {([
                  ['idle', 'rgba(120,155,185,0.6)'],
                  ['ok', 'rgba(54,207,201,0.85)'],
                  ['warn', 'hsl(30, 82%, 52%)'],
                  ['danger', 'hsl(0, 82%, 55%)'],
                ] as const).map(([k, c]) => (
                  <marker key={k} id={`topo-arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5"
                    markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" fill={c} />
                  </marker>
                ))}
              </defs>
              {Array.from(edges.entries()).map(([key, w]) => {
                const [from, to] = key.split('>')
                const a = anchor(from, 'r')
                const b = anchor(to, 'l')
                const v = edgeVisual(to, w)
                const back = (b.x - a.x) < 60
                const dx = back ? 70 : Math.max(46, Math.abs(b.x - a.x) / 3)
                const lift = back ? -26 : 0
                const d = `M ${a.x} ${a.y} C ${a.x + dx} ${a.y + lift}, ${b.x - dx} ${b.y + lift}, ${b.x} ${b.y}`
                return (
                  <g key={key}>
                    <path d={d} fill="none" stroke={v.stroke} strokeWidth={v.width}
                      strokeDasharray="7 7" className="topo-edge"
                      style={{ animationDuration: `${v.dur}s` }}
                      markerEnd={`url(#topo-arrow-${v.marker})`} />
                    <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 7 + lift} textAnchor="middle" fontSize={9}
                      fill={live ? (v.marker === 'ok' || v.marker === 'idle' ? 'rgba(150,222,230,0.9)' : v.stroke) : 'rgba(255,255,255,0.42)'}
                      style={{ paintOrder: 'stroke', stroke: 'rgba(8,20,35,0.9)', strokeWidth: 3 }}>
                      {live
                        ? `${Math.round(w)}h${v.unmet > 0
                          ? ` ⚠缺${Math.round(v.unmet)}h`
                          : v.ot > 0 ? ` ⚠+${Math.round(v.ot)}h` : ''}`
                        : `${w} 条工艺`}
                    </text>
                  </g>
                )
              })}
            </svg>

            {/* 订单池 */}
            {positions['POOL'] && (
              <div className="topo-end" style={{ left: positions['POOL'].x, top: positions['POOL'].y }}
                onPointerDown={(e) => startDrag(e, 'POOL')} onPointerMove={moveDrag} onPointerUp={endDrag}>
                <div className="flow-node flow-node-end flow-node-pool" style={{ width: '100%', height: '100%' }}>
                  <div className="flow-node-head"><span className="flow-node-name" style={{ fontSize: 13 }}><InboxOutlined /> 订单池</span></div>
                  <div className="flow-node-en">ORDER POOL</div>
                  <div className="flow-end-lines">
                    <div className="flow-end-line"><span>订单</span><b>{config.orders.length} 张</b></div>
                    <div className="flow-end-line"><span>总量</span><b>{totalQty.toLocaleString()} 件</b></div>
                  </div>
                </div>
              </div>
            )}

            {/* 成品交付 */}
            {positions['OUT'] && (
              <div className="topo-end" style={{ left: positions['OUT'].x, top: positions['OUT'].y }}
                onPointerDown={(e) => startDrag(e, 'OUT')} onPointerMove={moveDrag} onPointerUp={endDrag}>
                <div className="flow-node flow-node-end flow-node-out" style={{ width: '100%', height: '100%' }}>
                  <div className="flow-node-head"><span className="flow-node-name" style={{ fontSize: 13 }}><FlagOutlined /> 成品交付</span></div>
                  <div className="flow-node-en">DELIVERY</div>
                  <div className="flow-end-lines">
                    {result ? (
                      <>
                        <div className="flow-end-line"><span>准时</span><b style={{ color: '#95de64' }}>{result.order_count - result.kpis.delayed_orders} 单</b></div>
                        <div className="flow-end-line">
                          <span>延期</span>
                          <b style={{ color: result.kpis.delayed_orders > 0 ? '#ff7875' : '#95de64' }}>{result.kpis.delayed_orders} 单</b>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="flow-end-line"><span>准时</span><b>—</b></div>
                        <div className="flow-end-line"><span>延期</span><b>—</b></div>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* 车间容器 */}
            {config.workshops.map((ws) => {
              const p = positions[ws.workshop_id]
              if (!p) return null
              const secs = sectionsOf(ws.workshop_id)
              const isOver = dropHint?.wsId === ws.workshop_id
              return (
                <div
                  key={ws.workshop_id}
                  className={`topo-ws${isOver ? ' drag-over' : ''}`}
                  style={{ left: p.x, top: p.y }}
                  onDragOver={(e) => { if (dragSec) { e.preventDefault(); setDropHint((h) => (h?.wsId === ws.workshop_id && h.beforeSid === null ? h : { wsId: ws.workshop_id, beforeSid: null })) } }}
                  onDrop={(e) => onSecDrop(e, ws.workshop_id, null)}
                >
                  {/* 车间头（拖拽手柄） */}
                  <div className="topo-ws-head"
                    onPointerDown={(e) => startDrag(e, ws.workshop_id)} onPointerMove={moveDrag} onPointerUp={endDrag}
                    onClick={() => setSel({ type: 'workshop', id: ws.workshop_id })}>
                    <HolderOutlined style={{ color: 'rgba(255,255,255,0.35)', fontSize: 12 }} />
                    <BankOutlined style={{ color: '#36cfc9', fontSize: 13 }} />
                    <span style={{ color: '#fff', fontWeight: 800, fontSize: 13, letterSpacing: 1, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {ws.name}
                    </span>
                    <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: 9, fontFamily: "'SF Mono', Menlo, monospace" }}>
                      {ws.working_days_per_week === 5 ? '双休' : ws.working_days_per_week === 6 ? '单休' : '全周'}
                    </span>
                    <Tooltip title="新增工段">
                      <Button type="text" size="small" icon={<PlusOutlined />}
                        style={{ color: '#36cfc9', width: 22, height: 22, minWidth: 22 }}
                        onClick={(e) => { e.stopPropagation(); onAddSection(ws.workshop_id) }} />
                    </Tooltip>
                    <Popconfirm title={`删除车间「${ws.name}」？`} description={`将同时删除其 ${secs.length} 个工段`}
                      okText="删除" cancelText="取消" okButtonProps={{ danger: true }}
                      onConfirm={() => onRemoveWorkshop(ws.workshop_id)}>
                      <Button type="text" size="small" danger icon={<DeleteOutlined />}
                        style={{ width: 22, height: 22, minWidth: 22 }} onClick={(e) => e.stopPropagation()} />
                    </Popconfirm>
                  </div>

                  {/* 工段卡片列表 */}
                  <div style={{ padding: WS_PAD, display: 'flex', flexDirection: 'column', gap: CARD_GAP }}>
                    {secs.length === 0 && (
                      <div style={{
                        height: 48, border: '1px dashed rgba(255,255,255,0.25)', borderRadius: 6,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: 'rgba(255,255,255,0.4)', fontSize: 11,
                      }}>
                        拖入工段，或点击 + 新增
                      </div>
                    )}
                    {secs.map((s) => {
                      const st = stats.get(s.section_id)
                      const bn = st?.is_bottleneck ?? false
                      const rc = routeCount.get(s.section_id) || 0
                      const selected = sel?.type === 'section' && sel.id === s.section_id
                      const isBefore = dropHint?.beforeSid === s.section_id
                      return (
                        <div
                          key={s.section_id}
                          className={`topo-sec${selected ? ' selected' : ''}${dragSec === s.section_id ? ' dragging' : ''}${isBefore ? ' drop-before' : ''}${bn ? ' flow-node-bn' : ''}`}
                          draggable
                          onDragStart={(e) => onSecDragStart(e, s.section_id)}
                          onDragEnd={clearDrag}
                          onDragOver={(e) => {
                            if (dragSec && dragSec !== s.section_id) {
                              e.preventDefault(); e.stopPropagation()
                              setDropHint({ wsId: ws.workshop_id, beforeSid: s.section_id })
                            }
                          }}
                          onDrop={(e) => onSecDrop(e, ws.workshop_id, s.section_id)}
                          onClick={() => setSel({ type: 'section', id: s.section_id })}
                        >
                          {bn && <span className="flow-bn-badge"><WarningOutlined /> 瓶颈</span>}
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: 5 }}>
                            <span style={{ color: '#fff', fontWeight: 800, fontSize: 12.5, letterSpacing: 0.5, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {s.name}
                            </span>
                            <span style={{ color: 'rgba(255,255,255,0.32)', fontSize: 8.5, fontFamily: "'SF Mono', Menlo, monospace" }}>
                              {rc > 0 ? `L${ranks.get(s.section_id) ?? 0} · ` : ''}{s.section_id}
                            </span>
                          </div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 4 }}>
                            <span className={s.strategy === 'mts' ? 'flow-tag flow-tag-mts' : 'flow-tag flow-tag-mto'}>
                              {s.strategy.toUpperCase()}
                            </span>
                            {rc > 0 && (
                              <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: 9 }}>
                                <ApartmentOutlined style={{ marginRight: 2 }} />{rc} 道工序
                              </span>
                            )}
                            <span style={{ marginLeft: 'auto', color: 'rgba(255,255,255,0.55)', fontSize: 9.5, whiteSpace: 'nowrap' }}>
                              <TeamOutlined style={{ marginRight: 2, color: 'rgba(255,255,255,0.4)' }} />{s.workers}
                              <ToolOutlined style={{ margin: '0 2px 0 6px', color: 'rgba(255,255,255,0.4)' }} />{s.machines}
                              <ClockCircleOutlined style={{ margin: '0 2px 0 6px', color: 'rgba(255,255,255,0.4)' }} />{s.shifts_per_day}×{s.hours_per_shift}h
                            </span>
                          </div>
                          {st ? (
                            <>
                              <div className="flow-bar" style={{ margin: '7px 0 4px' }}>
                                <i style={{ width: `${Math.min(100, (st.pressure_rate / 1.5) * 100)}%`, background: heat(Math.max(st.pressure_rate, st.peak_load_rate)) }} />
                              </div>
                              <div className="flow-node-stats"
                                title={`需求 ${st.demand_hours.toFixed(0)}h / 基准产能 ${st.total_capacity_hours.toFixed(0)}h · `
                                  + `期内排不下 ${st.unmet_hours.toFixed(0)}h · 已用加班 ${st.overtime_used_hours.toFixed(0)}h\n`
                                  + (BIND_ADVICE[st.binding_resource] || '钳位来源未知')}>
                                <span style={{ color: heat(Math.max(st.pressure_rate, st.peak_load_rate)), fontWeight: 800, fontSize: 11 }}>
                                  {pct(st.pressure_rate)}
                                </span>
                                {st.unmet_hours > 0.5 && <span style={{ color: '#ff7875' }}>缺{st.unmet_hours.toFixed(0)}h</span>}
                                {st.overtime_used_hours > 0 && <span style={{ color: '#b37feb' }}>+{st.overtime_used_hours.toFixed(0)}h</span>}
                                <span style={{ color: 'rgba(255,255,255,0.42)' }}>{BIND_SHORT[st.binding_resource] || ''}</span>
                              </div>
                            </>
                          ) : (
                            <div className="flow-node-idle" style={{ marginTop: 7 }}>待仿真点亮</div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>

          {/* ── Mini-map 视口导航 ── */}
          {showMM && (
            <div className="topo-mm" onPointerDown={onMmDown} onPointerMove={onMmMove} onPointerUp={onMmUp}>
              {config.workshops.map((w) => {
                const p = positions[w.workshop_id]
                if (!p) return null
                return (
                  <i key={w.workshop_id} className="topo-mm-node"
                    style={{
                      left: mm.ox + p.x * mm.s, top: mm.oy + p.y * mm.s,
                      width: Math.max(3, WS_W * mm.s), height: Math.max(2, wsTotalH(sectionsOf(w.workshop_id).length) * mm.s),
                      background: 'rgba(54,207,201,0.32)', borderColor: 'rgba(54,207,201,0.75)',
                    }} />
                )
              })}
              {(['POOL', 'OUT'] as const).map((k) => {
                const p = positions[k]
                if (!p) return null
                return (
                  <i key={k} className="topo-mm-node"
                    style={{
                      left: mm.ox + p.x * mm.s, top: mm.oy + p.y * mm.s,
                      width: Math.max(3, END_W * mm.s), height: Math.max(2, END_H * mm.s),
                      background: k === 'POOL' ? 'rgba(24,144,255,0.35)' : 'rgba(82,196,26,0.35)',
                      borderColor: k === 'POOL' ? 'rgba(24,144,255,0.8)' : 'rgba(82,196,26,0.8)',
                    }} />
                )
              })}
              <div className="topo-mm-view" style={{
                left: mmView.x, top: mmView.y, width: mmView.w, height: mmView.h,
              }} />
            </div>
          )}

          {/* 视口控制条 */}
          <div className="topo-stage-tools">
            <Button size="small" shape="circle" icon={<LeftOutlined />} style={darkBtn} onClick={() => setVp((v) => ({ ...v, tx: v.tx + 160 }))} />
            <Button size="small" shape="circle" icon={<RightOutlined />} style={darkBtn} onClick={() => setVp((v) => ({ ...v, tx: v.tx - 160 }))} />
            <Button size="small" onClick={() => setShowMM((s) => !s)}
              style={{ ...darkBtn, fontSize: 11, height: 24 }}>{showMM ? '隐藏导航' : '显示导航'}</Button>
          </div>
        </div>

        {/* ── 底部图例 ── */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8, flexWrap: 'wrap', gap: 6 }}>
          <Space size={12} style={{ fontSize: 11 }} wrap>
            <span className="flow-tag flow-tag-mts">MTS 备料</span>
            <span className="flow-tag flow-tag-mto">MTO 订单</span>
            <span style={{ color: 'rgba(255,255,255,0.6)' }}><span className="flow-bn-dot" />瓶颈工段</span>
            <span style={{ color: 'rgba(255,255,255,0.6)' }}>
              <svg width="34" height="8" style={{ verticalAlign: 'middle', marginRight: 4 }}>
                <line x1="0" y1="4" x2="34" y2="4" stroke="rgba(54,207,201,0.7)" strokeWidth="2" strokeDasharray="5 4" />
              </svg>
              流速快（负荷正常）
            </span>
            <span style={{ color: 'rgba(255,255,255,0.6)' }}>
              <svg width="34" height="8" style={{ verticalAlign: 'middle', marginRight: 4 }}>
                <line x1="0" y1="4" x2="34" y2="4" stroke="hsl(0, 82%, 55%)" strokeWidth="3" strokeDasharray="5 4" />
              </svg>
              变慢渐红（需求压力 ≥100%，标注缺工时/加班时数）
            </span>
            <span style={{ color: 'rgba(255,255,255,0.6)' }}>
              钳:人 = 加人有效 · 钳:机 = 加人无效（需加机台/外协）
            </span>
          </Space>
          <span style={{ color: 'rgba(255,255,255,0.38)', fontSize: 10 }}>
            {config.workshops.length} 车间 · {config.sections.length} 工段 · {config.routings.length} 条工艺路线 · 卡片 L0/L1… 为工艺层级 · 布局自动保存
          </span>
        </div>
      </div>

      {/* ── 属性抽屉 ── */}
      <Drawer
        title={
          selSection ? (
            <Space size={6}><ToolOutlined />工段属性<Text code style={{ fontSize: 11 }}>{selSection.section_id}</Text></Space>
          ) : selWorkshop ? (
            <Space size={6}><BankOutlined />车间属性<Text code style={{ fontSize: 11 }}>{selWorkshop.workshop_id}</Text></Space>
          ) : '属性'
        }
        width={340}
        open={!!sel}
        onClose={() => setSel(null)}
        mask={false}
        styles={{ body: { paddingTop: 12 } }}
      >
        {selSection && (
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <div>
              <div style={labelSt}>工段名称</div>
              <Input size="small" value={selSection.name} onChange={(e) => onPatchSection(selSection.section_id, { name: e.target.value })} />
            </div>
            <div>
              <div style={labelSt}>生产策略</div>
              <Segmented size="small" block value={selSection.strategy}
                onChange={(v) => onPatchSection(selSection.section_id, { strategy: v as ProductionStrategy })}
                options={[{ label: 'MTS 备料', value: 'mts' }, { label: 'MTO 订单', value: 'mto' }]} />
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <div style={{ flex: 1 }}>
                <div style={labelSt}>人数</div>
                <InputNumber size="small" min={1} max={500} value={selSection.workers} style={{ width: '100%' }}
                  onChange={(v) => onPatchSection(selSection.section_id, { workers: v || 1 })} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={labelSt}>设备台数</div>
                <InputNumber size="small" min={0} max={200} value={selSection.machines} style={{ width: '100%' }}
                  onChange={(v) => onPatchSection(selSection.section_id, { machines: v || 0 })} />
              </div>
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <div style={{ flex: 1 }}>
                <div style={labelSt}>班次 / 日</div>
                <Select size="small" value={selSection.shifts_per_day} style={{ width: '100%' }}
                  onChange={(v) => onPatchSection(selSection.section_id, { shifts_per_day: v })}
                  options={[1, 2, 3].map((x) => ({ label: `${x} 班`, value: x }))} />
              </div>
              <div style={{ flex: 1 }}>
                <div style={labelSt}>时 / 班</div>
                <Select size="small" value={selSection.hours_per_shift} style={{ width: '100%' }}
                  onChange={(v) => onPatchSection(selSection.section_id, { hours_per_shift: v })}
                  options={[6, 8, 10, 12].map((h) => ({ label: `${h} 小时`, value: h }))} />
              </div>
            </div>
            <div>
              <div style={labelSt}>综合效率 {pct(selSection.efficiency)}</div>
              <Slider min={0.3} max={1} step={0.05} value={selSection.efficiency}
                onChange={(v) => onPatchSection(selSection.section_id, { efficiency: v })} />
            </div>
            <div>
              <div style={labelSt}>加班上限 {pct(selSection.max_overtime_pct)}</div>
              <Slider min={0} max={1} step={0.1} value={selSection.max_overtime_pct}
                onChange={(v) => onPatchSection(selSection.section_id, { max_overtime_pct: v })} />
            </div>
            <div>
              <div style={labelSt}>良品率 {pct(selSection.yield_rate)}</div>
              <Slider min={0.8} max={1} step={0.005} value={selSection.yield_rate}
                onChange={(v) => onPatchSection(selSection.section_id, { yield_rate: v })} />
            </div>
            <div>
              <div style={labelSt}>工种</div>
              <Input size="small" value={selSection.role_name} onChange={(e) => onPatchSection(selSection.section_id, { role_name: e.target.value })} />
            </div>
            <div style={{ borderTop: '1px dashed #f0f0f0', paddingTop: 12 }}>
              <Popconfirm title={`删除工段「${selSection.name}」？`} okText="删除" cancelText="取消" okButtonProps={{ danger: true }}
                onConfirm={() => { onRemoveSection(selSection.section_id); setSel(null) }}>
                <Button danger icon={<DeleteOutlined />} block>删除该工段</Button>
              </Popconfirm>
              {(routeCount.get(selSection.section_id) || 0) > 0 && (
                <div style={{ fontSize: 11, color: '#faad14', marginTop: 6 }}>
                  <WarningOutlined /> 该工段被 {routeCount.get(selSection.section_id)} 道工艺工序引用，删除前需先调整工艺路线
                </div>
              )}
            </div>
          </Space>
        )}
        {selWorkshop && (
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <div>
              <div style={labelSt}>车间名称</div>
              <Input size="small" value={selWorkshop.name} onChange={(e) => onPatchWorkshop(selWorkshop.workshop_id, { name: e.target.value })} />
            </div>
            <div>
              <div style={labelSt}>班制</div>
              <Segmented size="small" block value={selWorkshop.working_days_per_week}
                onChange={(v) => onPatchWorkshop(selWorkshop.workshop_id, { working_days_per_week: Number(v) })}
                options={[{ label: '双休', value: 5 }, { label: '单休', value: 6 }, { label: '全周', value: 7 }]} />
            </div>
            <div>
              <div style={labelSt}>描述</div>
              <Input.TextArea size="small" rows={2} value={selWorkshop.description}
                onChange={(e) => onPatchWorkshop(selWorkshop.workshop_id, { description: e.target.value })} />
            </div>
            <div style={{ background: '#fafafa', borderRadius: 6, padding: '8px 10px', fontSize: 12, color: '#595959' }}>
              下辖 {sectionsOf(selWorkshop.workshop_id).length} 个工段：
              {sectionsOf(selWorkshop.workshop_id).map((s) => s.name).join('、') || '（空）'}
            </div>
            <div style={{ borderTop: '1px dashed #f0f0f0', paddingTop: 12 }}>
              <Popconfirm title={`删除车间「${selWorkshop.name}」？`}
                description={`将同时删除其 ${sectionsOf(selWorkshop.workshop_id).length} 个工段`}
                okText="删除" cancelText="取消" okButtonProps={{ danger: true }}
                onConfirm={() => { onRemoveWorkshop(selWorkshop.workshop_id); setSel(null) }}>
                <Button danger icon={<DeleteOutlined />} block>删除该车间</Button>
              </Popconfirm>
            </div>
          </Space>
        )}
      </Drawer>
    </div>
  )
}

/* ---------- 杂项样式 ---------- */
const darkBtn: React.CSSProperties = {
  background: 'rgba(255,255,255,0.06)',
  borderColor: 'rgba(255,255,255,0.22)',
  color: 'rgba(255,255,255,0.85)',
}
const labelSt: React.CSSProperties = { fontSize: 11, color: '#8c8c8c', marginBottom: 4 }

export default FlowTopology
