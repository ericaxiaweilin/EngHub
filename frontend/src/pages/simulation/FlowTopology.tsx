import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Button, Drawer, Input, InputNumber, Popconfirm, Segmented, Select, Slider, Space, Tooltip, Typography,
} from 'antd'
import {
  ApartmentOutlined, AppstoreOutlined, BankOutlined, CheckCircleOutlined,
  ClockCircleOutlined, DeleteOutlined, DeploymentUnitOutlined, FlagOutlined, HolderOutlined,
  InboxOutlined, PlusOutlined, TeamOutlined, ToolOutlined, WarningOutlined, ZoomInOutlined,
  ZoomOutOutlined,
} from '@ant-design/icons'
import {
  FactorySimConfig, FactorySimResult, ProductionStrategy, SectionConfig, SectionSummary,
  WorkshopConfig,
} from '../../services/factorySim'

/* ====================================================================
 * 产线组态编辑器（配置式）
 * - 画布自由拖拽：车间容器 / 端点节点（订单池·成品交付）鼠标拖动
 * - 工段卡片：HTML5 拖拽跨车间移动 / 排序，落点高亮 + 插入指示线
 * - 点击节点 → 右侧属性抽屉直接改参（人数/班次/效率…）
 * - 连线由工艺路线自动推导，仿真后按实际工时点亮
 * - 布局按场景持久化到 localStorage
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

type Pos = { x: number; y: number }
type Sel = { type: 'workshop' | 'section'; id: string } | null
type DropHint = { wsId: string; beforeSid: string | null } | null

const wsBodyH = (n: number) => (n === 0 ? 48 : n * (CARD_H + CARD_GAP) - CARD_GAP)
const wsTotalH = (n: number) => WS_HEAD + WS_PAD * 2 + wsBodyH(n)

/** 负荷率 → 热力色 */
const heat = (rate: number): string => {
  const t = Math.min(Math.max(rate, 0), 1.3) / 1.3
  return `hsl(${120 - t * 120}, 72%, ${54 - t * 8}%)`
}
const pct = (v: number) => `${Math.round(v * 100)}%`

interface Props {
  config: FactorySimConfig
  result: FactorySimResult | null
  scenarioId: string
  onPatchSection: (sid: string, p: Partial<SectionConfig>) => void
  onPatchWorkshop: (wid: string, p: Partial<WorkshopConfig>) => void
  onAddWorkshop: () => void
  onAddSection: (workshopId: string) => void
  onRemoveWorkshop: (wid: string) => void
  onRemoveSection: (sid: string) => void
  onMoveSection: (sid: string, targetWid: string, beforeSid: string | null) => void
}

/* ---------- 自动布局：订单池 → 车间网格 → 成品交付 ---------- */
const autoLayout = (cfg: FactorySimConfig): Record<string, Pos> => {
  const pos: Record<string, Pos> = {}
  const n = cfg.workshops.length
  const perRow = Math.max(1, Math.min(n, 3))
  const heights = cfg.workshops.map((w) =>
    wsTotalH(cfg.sections.filter((s) => s.workshop_id === w.workshop_id).length))
  const maxH = Math.max(140, ...heights)
  cfg.workshops.forEach((w, i) => {
    const col = i % perRow
    const row = Math.floor(i / perRow)
    pos[w.workshop_id] = { x: 250 + col * (WS_W + 170), y: 70 + row * (maxH + 100) }
  })
  const rows = Math.ceil(n / perRow)
  const midY = 70 + ((rows - 1) * (maxH + 100)) / 2 + maxH / 2 - END_H / 2
  pos['POOL'] = { x: 46, y: Math.max(70, midY) }
  pos['OUT'] = { x: 250 + (perRow - 1) * (WS_W + 170) + WS_W + 170, y: Math.max(70, midY) }
  return pos
}

/* ==================================================================== */

const FlowTopology: React.FC<Props> = ({
  config, result, scenarioId,
  onPatchSection, onPatchWorkshop, onAddWorkshop, onAddSection,
  onRemoveWorkshop, onRemoveSection, onMoveSection,
}) => {
  const live = !!result

  /* ---------- 布局状态 ---------- */
  const [positions, setPositions] = useState<Record<string, Pos>>({})
  const [zoom, setZoom] = useState(1)
  const [sel, setSel] = useState<Sel>(null)
  const [dragSec, setDragSec] = useState<string | null>(null)
  const [dropHint, setDropHint] = useState<DropHint>(null)
  const dragRef = useRef<{ id: string; sx: number; sy: number; ox: number; oy: number } | null>(null)

  /* 初始化 / 场景切换：localStorage 合并自动布局（新增车间补默认位，旧键丢弃） */
  useEffect(() => {
    const key = `topo-layout-${scenarioId}`
    let saved: Record<string, Pos> = {}
    try { saved = JSON.parse(localStorage.getItem(key) || '{}') } catch { /* ignore */ }
    const base = autoLayout(config)
    const merged: Record<string, Pos> = {}
    Object.keys(base).forEach((k) => { merged[k] = saved[k] || base[k] })
    setPositions(merged)
    setSel(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scenarioId, config.workshops.length])

  /* 布局变化 → 持久化 */
  useEffect(() => {
    if (!scenarioId || !Object.keys(positions).length) return
    try { localStorage.setItem(`topo-layout-${scenarioId}`, JSON.stringify(positions)) } catch { /* ignore */ }
  }, [positions, scenarioId])

  /* ---------- 指针拖拽（车间 / 端点） ---------- */
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
    const dx = (e.clientX - d.sx) / zoom
    const dy = (e.clientY - d.sy) / zoom
    setPositions((prev) => ({ ...prev, [d.id]: { x: Math.max(0, d.ox + dx), y: Math.max(0, d.oy + dy) } }))
  }, [zoom])

  const endDrag = useCallback(() => { dragRef.current = null }, [])

  /* ---------- 派生数据 ---------- */
  const sectionsOf = useCallback(
    (wid: string) => config.sections.filter((s) => s.workshop_id === wid),
    [config.sections],
  )

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

  /** 画布尺寸（包围盒 + 边距） */
  const canvasSize = useMemo(() => {
    let maxX = 1280
    let maxY = 620
    config.workshops.forEach((w) => {
      const p = positions[w.workshop_id]
      if (!p) return
      maxX = Math.max(maxX, p.x + WS_W + 90)
      maxY = Math.max(maxY, p.y + wsTotalH(sectionsOf(w.workshop_id).length) + 90)
    })
    ;['POOL', 'OUT'].forEach((k) => {
      const p = positions[k]
      if (p) { maxX = Math.max(maxX, p.x + END_W + 90); maxY = Math.max(maxY, p.y + END_H + 90) }
    })
    return { w: maxX, h: maxY }
  }, [positions, config.workshops, sectionsOf])

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
              拖拽车间标题移动位置 · 拖拽工段卡片跨车间移动 · 点击节点编辑参数
            </span>
          </Space>
          <Space size={8} wrap>
            {live ? (
              <span style={{ color: '#95de64', fontSize: 11 }}><CheckCircleOutlined /> 已点亮仿真结果</span>
            ) : (
              <span style={{ color: 'rgba(255,255,255,0.45)', fontSize: 11 }}>静态拓扑 · 运行仿真后点亮</span>
            )}
            <Button size="small" icon={<ZoomOutOutlined />} style={darkBtn}
              onClick={() => setZoom((z) => Math.max(0.6, Number((z - 0.15).toFixed(2))))} />
            <span style={{ color: 'rgba(255,255,255,0.65)', fontSize: 11, width: 36, textAlign: 'center' }}>{Math.round(zoom * 100)}%</span>
            <Button size="small" icon={<ZoomInOutlined />} style={darkBtn}
              onClick={() => setZoom((z) => Math.min(1.5, Number((z + 0.15).toFixed(2))))} />
            <Button size="small" icon={<AppstoreOutlined />} style={darkBtn}
              onClick={() => setPositions(autoLayout(config))}>
              自动布局
            </Button>
            <Button size="small" type="primary" ghost icon={<PlusOutlined />} onClick={onAddWorkshop}>
              新增车间
            </Button>
          </Space>
        </div>

        {/* ── 画布 ── */}
        <div style={{ overflow: 'auto', marginTop: 10, borderRadius: 6, border: '1px solid rgba(94,140,180,0.28)', height: 540 }}>
          <div style={{ width: canvasSize.w * zoom, height: canvasSize.h * zoom, position: 'relative' }}>
            <div
              className="topo-canvas"
              style={{ width: canvasSize.w, height: canvasSize.h, transform: `scale(${zoom})`, transformOrigin: '0 0' }}
            >
              {/* SVG 连线层 */}
              <svg width={canvasSize.w} height={canvasSize.h} style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
                <defs>
                  <marker id="topo-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M 0 0 L 10 5 L 0 10 z" fill={live ? 'rgba(54,207,201,0.85)' : 'rgba(120,155,185,0.6)'} />
                  </marker>
                </defs>
                {Array.from(edges.entries()).map(([key, w]) => {
                  const [from, to] = key.split('>')
                  const a = anchor(from, 'r')
                  const b = anchor(to, 'l')
                  const t = Math.min(1, w / maxFlow)
                  const dx = Math.max(46, Math.abs(b.x - a.x) / 3)
                  const d = `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`
                  const color = live ? `rgba(54,207,201,${0.3 + t * 0.6})` : 'rgba(120,155,185,0.42)'
                  return (
                    <g key={key}>
                      <path d={d} fill="none" stroke={color} strokeWidth={1.5 + t * 2.5}
                        strokeDasharray="7 7" className="topo-edge" markerEnd="url(#topo-arrow)" />
                      <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 7} textAnchor="middle" fontSize={9}
                        fill={live ? 'rgba(150,222,230,0.9)' : 'rgba(255,255,255,0.42)'}
                        style={{ paintOrder: 'stroke', stroke: 'rgba(8,20,35,0.9)', strokeWidth: 3 }}>
                        {live ? `${Math.round(w)}h` : `${w} 条工艺`}
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
                              <span style={{ color: 'rgba(255,255,255,0.32)', fontSize: 8.5, fontFamily: "'SF Mono', Menlo, monospace" }}>{s.section_id}</span>
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
                                  <i style={{ width: `${Math.min(100, (st.avg_load_rate / 1.3) * 100)}%`, background: heat(st.avg_load_rate) }} />
                                </div>
                                <div className="flow-node-stats">
                                  <span style={{ color: heat(st.avg_load_rate), fontWeight: 800, fontSize: 11 }}>{pct(st.avg_load_rate)}</span>
                                  <span>峰 {pct(st.peak_load_rate)}</span>
                                  {st.overtime_used_hours > 0 && <span style={{ color: '#b37feb' }}>+{st.overtime_used_hours.toFixed(0)}h</span>}
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
              工艺流转（{live ? '实际工时' : '路线条数'}）
            </span>
          </Space>
          <span style={{ color: 'rgba(255,255,255,0.38)', fontSize: 10 }}>
            {config.workshops.length} 车间 · {config.sections.length} 工段 · {config.routings.length} 条工艺路线 · 布局自动保存
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
