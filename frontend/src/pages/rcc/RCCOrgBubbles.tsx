/**
 * RCC 任务智慧中心 — 组织泡泡图（力导向）
 * 每个泡泡 = 一个组织节点（大小=负荷，颜色=健康度）
 * 连线 = 逻辑链信号传导（带粒子动画）
 * 点击泡泡 → 右侧 Drawer 展示详情
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { Alert, Drawer, Empty, Tag, Space, Descriptions, Spin } from 'antd'
import {
  ThunderboltOutlined, CloseCircleOutlined,
  ApiOutlined, TeamOutlined,
} from '@ant-design/icons'
import axios from 'axios'
import { COLORS } from './RCCCommandCenter'

const API_BASE = '/api/v1/rcc'

// ==================== 类型 ====================
interface BubbleNode {
  id: string
  name: string
  level: number
  scope: string
  health: 'normal' | 'warning' | 'danger'
  load: number
  violations: string[]
  key_outputs: Record<string, number>
  param_count: number
  capability_count: number
  // 力导向坐标
  x: number
  y: number
  vx: number
  vy: number
}

interface BubbleEdge {
  source: string
  target: string
  signal: string
  target_signal: string
  label: string
  chain_name: string
  value: number | null
  latency_h: number
}

// ==================== 健康度配色 ====================
const HEALTH_COLOR: Record<string, { fill: string; glow: string; stroke: string }> = {
  normal: { fill: '#0d3b3b', glow: '#00d4aa', stroke: '#00d4aa' },
  warning: { fill: '#3b3008', glow: '#fbbf24', stroke: '#fbbf24' },
  danger: { fill: '#3b1010', glow: '#f87171', stroke: '#f87171' },
}

const LEVEL_LABEL: Record<number, string> = {
  1: '现场', 2: '主管', 3: '经理', 4: '总监', 5: '高层',
}

// ==================== 力模拟 ====================
function initPositions(nodes: BubbleNode[], w: number, h: number) {
  const cx = w / 2, cy = h / 2
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length
    const r = Math.min(w, h) * 0.28
    n.x = cx + r * Math.cos(angle) + (Math.random() - 0.5) * 30
    n.y = cy + r * Math.sin(angle) + (Math.random() - 0.5) * 30
    n.vx = 0
    n.vy = 0
  })
}

function simulate(nodes: BubbleNode[], edges: BubbleEdge[], w: number, h: number, alpha: number) {
  const cx = w / 2, cy = h / 2
  // 向心力
  nodes.forEach(n => {
    n.vx += (cx - n.x) * 0.002 * alpha
    n.vy += (cy - n.y) * 0.002 * alpha
  })
  // 斥力（节点间）
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const dx = nodes[j].x - nodes[i].x
      const dy = nodes[j].y - nodes[i].y
      const dist = Math.max(30, Math.sqrt(dx * dx + dy * dy))
      const force = (180 * alpha) / (dist * dist)
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force
      nodes[i].vx -= fx
      nodes[i].vy -= fy
      nodes[j].vx += fx
      nodes[j].vy += fy
    }
  }
  // 弹簧力（边）
  const nodeMap = Object.fromEntries(nodes.map(n => [n.id, n]))
  edges.forEach(e => {
    const s = nodeMap[e.source], t = nodeMap[e.target]
    if (!s || !t) return
    const dx = t.x - s.x, dy = t.y - s.y
    const dist = Math.max(30, Math.sqrt(dx * dx + dy * dy))
    const target_dist = 160
    const force = (dist - target_dist) * 0.005 * alpha
    const fx = (dx / dist) * force
    const fy = (dy / dist) * force
    s.vx += fx; s.vy += fy
    t.vx -= fx; t.vy -= fy
  })
  // 积分
  nodes.forEach(n => {
    n.vx *= 0.85
    n.vy *= 0.85
    n.x += n.vx
    n.y += n.vy
    // 边界
    const r = 30 + n.load * 30
    n.x = Math.max(r + 10, Math.min(w - r - 10, n.x))
    n.y = Math.max(r + 10, Math.min(h - r - 10, n.y))
  })
}

// ==================== 主组件 ====================
interface RCCOrgBubblesProps {
  factoryId?: string
}

export default function RCCOrgBubbles({ factoryId = 'FAC_ELEC_DEMO_2026' }: RCCOrgBubblesProps) {
  const [nodes, setNodes] = useState<BubbleNode[]>([])
  const [edges, setEdges] = useState<BubbleEdge[]>([])
  const [meta, setMeta] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<BubbleNode | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const svgRef = useRef<SVGSVGElement>(null)
  const animRef = useRef<number>(0)
  const alphaRef = useRef(1)
  const nodesRef = useRef<BubbleNode[]>([])
  const [tick, setTick] = useState(0)

  const W = 800, H = 520

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await axios.get(`${API_BASE}/org-bubbles`, { params: { factory_id: factoryId } })
      const data = res.data
      if (data.success) {
        const ns: BubbleNode[] = (data.nodes || []).map((n: any) => ({
          ...n, x: 0, y: 0, vx: 0, vy: 0,
        }))
        initPositions(ns, W, H)
        nodesRef.current = ns
        setNodes(ns)
        setEdges(data.edges || [])
        setMeta(data.meta)
        alphaRef.current = 1
      } else {
        setNodes([])
        setEdges([])
        setError('RCC气泡数据返回为空')
      }
    } catch (e: any) {
      setNodes([])
      setEdges([])
      setError(e?.response?.data?.detail || e?.message || 'RCC气泡数据加载失败')
    }
    setLoading(false)
  }, [factoryId])

  useEffect(() => { fetchData() }, [fetchData])

  // 力模拟动画循环
  useEffect(() => {
    if (nodes.length === 0) return
    let running = true
    const loop = () => {
      if (!running) return
      if (alphaRef.current > 0.01) {
        simulate(nodesRef.current, edges, W, H, alphaRef.current)
        alphaRef.current *= 0.98
        setTick(t => t + 1)
      }
      animRef.current = requestAnimationFrame(loop)
    }
    animRef.current = requestAnimationFrame(loop)
    return () => { running = false; cancelAnimationFrame(animRef.current) }
  }, [nodes.length, edges])

  const handleBubbleClick = (node: BubbleNode) => {
    setSelected(node)
    setDrawerOpen(true)
  }

  const nodeMap = Object.fromEntries(nodesRef.current.map(n => [n.id, n]))

  return (
    <div style={{ position: 'relative' }}>
      {/* 标题栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <TeamOutlined style={{ color: COLORS.accent, fontSize: 18 }} />
        <span style={{ color: COLORS.text, fontWeight: 700, fontSize: 15 }}>任务智慧中心 · 组织协同泡泡图</span>
        {meta && (
          <Tag style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, color: COLORS.textDim }}>
            {meta.total_nodes} 组织 · {meta.total_edges} 协同链
          </Tag>
        )}
        <div style={{ marginLeft: 'auto' }}>
          <Space size={12}>
            <Space size={4}><div style={{ width: 10, height: 10, borderRadius: '50%', background: COLORS.success }} /><span style={{ color: COLORS.textMuted, fontSize: 11 }}>正常</span></Space>
            <Space size={4}><div style={{ width: 10, height: 10, borderRadius: '50%', background: COLORS.warning }} /><span style={{ color: COLORS.textMuted, fontSize: 11 }}>预警</span></Space>
            <Space size={4}><div style={{ width: 10, height: 10, borderRadius: '50%', background: COLORS.danger }} /><span style={{ color: COLORS.textMuted, fontSize: 11 }}>瓶颈</span></Space>
          </Space>
        </div>
      </div>

      {/* 泡泡图画布 */}
      <Spin spinning={loading}>
        {error && (
          <Alert
            type="warning"
            showIcon
            message={error}
            style={{ marginBottom: 12, background: COLORS.bgCard, borderColor: COLORS.border, color: COLORS.text }}
          />
        )}
        <div style={{
          background: COLORS.bg, borderRadius: 16, border: `1px solid ${COLORS.border}`,
          overflow: 'hidden', position: 'relative',
        }}>
          {nodesRef.current.length === 0 && !loading ? (
            <div style={{ height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Empty description={<span style={{ color: COLORS.textDim }}>当前工厂暂无RCC气泡节点</span>} />
            </div>
          ) : (
          <svg ref={svgRef} width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
            {/* 背景网格 */}
            <defs>
              <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                <path d="M 40 0 L 0 0 0 40" fill="none" stroke={COLORS.border} strokeWidth="0.3" opacity="0.4" />
              </pattern>
              {/* 发光滤镜 */}
              <filter id="glow-normal"><feDropShadow dx="0" dy="0" stdDeviation="6" floodColor="#00d4aa" floodOpacity="0.5" /></filter>
              <filter id="glow-warning"><feDropShadow dx="0" dy="0" stdDeviation="6" floodColor="#fbbf24" floodOpacity="0.5" /></filter>
              <filter id="glow-danger"><feDropShadow dx="0" dy="0" stdDeviation="8" floodColor="#f87171" floodOpacity="0.6" /></filter>
            </defs>
            <rect width={W} height={H} fill="url(#grid)" />

            {/* 连线 */}
            {edges.map((e, i) => {
              const s = nodeMap[e.source], t = nodeMap[e.target]
              if (!s || !t) return null
              const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2
              return (
                <g key={`edge-${i}`}>
                  <line x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                    stroke={COLORS.border} strokeWidth={1.5} strokeDasharray="4 3" opacity={0.6} />
                  {/* 信号标签 */}
                  <rect x={mx - 24} y={my - 9} width={48} height={18} rx={9}
                    fill={COLORS.bgCard} stroke={COLORS.border} strokeWidth={0.5} />
                  <text x={mx} y={my + 4} textAnchor="middle" fontSize={9} fill={COLORS.textDim}>
                    {e.signal.slice(0, 4)}
                  </text>
                  {/* 粒子动画 */}
                  <circle r={2.5} fill={COLORS.accent} opacity={0.8}>
                    <animateMotion dur={`${2 + i * 0.3}s`} repeatCount="indefinite"
                      path={`M${s.x},${s.y} L${t.x},${t.y}`} />
                  </circle>
                </g>
              )
            })}

            {/* 泡泡节点 */}
            {nodesRef.current.map(n => {
              const r = 30 + n.load * 30
              const hc = HEALTH_COLOR[n.health] || HEALTH_COLOR.normal
              return (
                <g key={n.id} onClick={() => handleBubbleClick(n)} style={{ cursor: 'pointer' }}>
                  {/* 外发光圈 */}
                  <circle cx={n.x} cy={n.y} r={r + 6} fill="none"
                    stroke={hc.glow} strokeWidth={1} opacity={0.3}
                    strokeDasharray={n.health === 'danger' ? '3 3' : undefined}>
                    {n.health === 'danger' && (
                      <animate attributeName="opacity" values="0.3;0.7;0.3" dur="1.5s" repeatCount="indefinite" />
                    )}
                  </circle>
                  {/* 主泡泡 */}
                  <circle cx={n.x} cy={n.y} r={r}
                    fill={hc.fill} stroke={hc.stroke} strokeWidth={2}
                    filter={`url(#glow-${n.health})`} />
                  {/* 层级环 */}
                  <circle cx={n.x} cy={n.y} r={r - 5} fill="none"
                    stroke={hc.stroke} strokeWidth={0.5} opacity={0.3} />
                  {/* 名称 */}
                  <text x={n.x} y={n.y - 4} textAnchor="middle" fontSize={12}
                    fontWeight={700} fill={COLORS.text}>
                    {n.name}
                  </text>
                  {/* 层级 + 负荷 */}
                  <text x={n.x} y={n.y + 12} textAnchor="middle" fontSize={9} fill={COLORS.textDim}>
                    {LEVEL_LABEL[n.level] || `L${n.level}`} · 负荷 {Math.round(n.load * 100)}%
                  </text>
                  {/* 告警角标 */}
                  {n.violations.length > 0 && (
                    <g>
                      <circle cx={n.x + r * 0.7} cy={n.y - r * 0.7} r={8} fill={COLORS.danger} />
                      <text x={n.x + r * 0.7} y={n.y - r * 0.7 + 3.5} textAnchor="middle"
                        fontSize={9} fill="#fff" fontWeight={700}>
                        {n.violations.length}
                      </text>
                    </g>
                  )}
                </g>
              )
            })}
          </svg>
          )}
        </div>
      </Spin>

      {/* 详情 Drawer */}
      <Drawer
        title={
          <Space>
            <span style={{ color: COLORS.text }}>{selected?.name}</span>
            {selected && (
              <Tag color={selected.health === 'normal' ? 'green' : selected.health === 'warning' ? 'orange' : 'red'}>
                {selected.health === 'normal' ? '正常' : selected.health === 'warning' ? '预警' : '瓶颈'}
              </Tag>
            )}
          </Space>
        }
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={400}
        styles={{ body: { background: COLORS.bgCard }, header: { background: COLORS.bgCard, borderBottom: `1px solid ${COLORS.border}` } }}
      >
        {selected && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Descriptions column={1} size="small" labelStyle={{ color: COLORS.textDim }} contentStyle={{ color: COLORS.text }}>
              <Descriptions.Item label="层级">{LEVEL_LABEL[selected.level]} (L{selected.level})</Descriptions.Item>
              <Descriptions.Item label="职责范围">{selected.scope}</Descriptions.Item>
              <Descriptions.Item label="可调参数">{selected.param_count} 个</Descriptions.Item>
              <Descriptions.Item label="能力项">{selected.capability_count} 个</Descriptions.Item>
              <Descriptions.Item label="负荷">{Math.round(selected.load * 100)}%</Descriptions.Item>
            </Descriptions>

            {/* 关键输出信号 */}
            <div>
              <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 13, marginBottom: 8 }}>
                <ApiOutlined style={{ marginRight: 6, color: COLORS.accentBlue }} />关键输出信号
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {Object.entries(selected.key_outputs).map(([k, v]) => (
                  <Tag key={k} style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, color: COLORS.textDim }}>
                    {k}: <span style={{ color: COLORS.accent, fontWeight: 600 }}>{v}</span>
                  </Tag>
                ))}
              </div>
            </div>

            {/* 违反项 */}
            {selected.violations.length > 0 && (
              <div>
                <div style={{ color: COLORS.danger, fontWeight: 600, fontSize: 13, marginBottom: 8 }}>
                  <CloseCircleOutlined style={{ marginRight: 6 }} />约束违反 ({selected.violations.length})
                </div>
                {selected.violations.map((v, i) => (
                  <div key={i} style={{
                    padding: '8px 12px', borderRadius: 6, marginBottom: 6,
                    background: '#3b1010', border: '1px solid #f8717133', color: COLORS.danger, fontSize: 12,
                  }}>
                    {v}
                  </div>
                ))}
              </div>
            )}

            {/* 关联边 */}
            <div>
              <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 13, marginBottom: 8 }}>
                <ThunderboltOutlined style={{ marginRight: 6, color: COLORS.warning }} />协同连接
              </div>
              {edges.filter(e => e.source === selected.id || e.target === selected.id).map((e, i) => (
                <div key={i} style={{
                  padding: '6px 10px', borderRadius: 6, marginBottom: 4,
                  background: COLORS.bg, border: `1px solid ${COLORS.border}`, fontSize: 11, color: COLORS.textDim,
                }}>
                  {e.source === selected.id ? '→ ' + e.target : '← ' + e.source}
                  <span style={{ marginLeft: 8, color: COLORS.accentBlue }}>{e.label}</span>
                  {e.value !== null && <span style={{ marginLeft: 6, color: COLORS.accent }}>= {e.value}</span>}
                </div>
              ))}
            </div>
          </Space>
        )}
      </Drawer>
    </div>
  )
}
