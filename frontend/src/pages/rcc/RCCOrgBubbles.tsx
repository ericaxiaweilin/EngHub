/**
 * RCC 任务智慧中心 - 组织层级气泡图
 *
 * 气泡是一个组织角色，层级由 RCC 逻辑链决定。
 * 点击气泡进入下一层，当前画布只展示这一层的子气泡。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Alert, Button, Empty, Space, Spin, Tag, Tooltip } from 'antd'
import {
  ApiOutlined,
  ArrowLeftOutlined,
  HomeOutlined,
  ReloadOutlined,
  TeamOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import axios from 'axios'
import { COLORS } from './RCCCommandCenter'

const API_BASE = '/api/v1/rcc'
const ROOT_ID = '__rcc_root__'

interface BubbleNode {
  id: string
  name: string
  parent_id?: string | null
  level: number
  scope: string
  health: 'normal' | 'warning' | 'danger'
  load: number
  violations: string[]
  key_outputs: Record<string, number>
  param_count: number
  capability_count: number
  children: BubbleNode[]
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

interface RCCOrgBubblesProps {
  factoryId?: string
}

const HEALTH_COLOR: Record<string, { fill: string; glow: string; stroke: string; text: string }> = {
  normal: { fill: '#0d3b3b', glow: '#00d4aa', stroke: '#00d4aa', text: '#5eead4' },
  warning: { fill: '#3b3008', glow: '#fbbf24', stroke: '#fbbf24', text: '#fcd34d' },
  danger: { fill: '#3b1010', glow: '#f87171', stroke: '#f87171', text: '#fca5a5' },
}

const LEVEL_LABEL: Record<number, string> = {
  1: '现场',
  2: '主管',
  3: '经理',
  4: '总监',
  5: '高层',
}

function healthLabel(health: BubbleNode['health']) {
  return health === 'normal' ? '正常' : health === 'warning' ? '预警' : '瓶颈'
}

function buildHierarchy(nodes: BubbleNode[], edges: BubbleEdge[]): BubbleNode[] {
  if (nodes.length === 0) return []

  const byId = new Map(nodes.map(node => [node.id, node]))
  const firstLevel = Math.min(...nodes.map(node => node.level))
  // 有 parent_id 的节点归属到父节点下（如 SMT线长 → hr_sup 人力）
  const withParent = new Set(nodes.filter(n => n.parent_id && byId.has(n.parent_id)).map(n => n.id))
  // 顶层 = 无 parent 的节点（level 1 线长归 hr_sup 后，hr_sup/质量/设备/仓储/生产经理都是顶层）
  const roots = nodes.filter(n => !withParent.has(n.id))
  const rootIds = new Set(roots.map(n => n.id))

  const buildNode = (node: BubbleNode, visited: Set<string>): BubbleNode => {
    if (visited.has(node.id)) return { ...node, children: [] }  // 防环
    const nextVisited = new Set(visited).add(node.id)
    // 1) 优先按 parent_id 挂子节点（组织归属）
    const directChildren = nodes.filter(c => c.parent_id === node.id)
    // 2) 其次按 level 层级连（信号传导链，排除已归属其他父的 AND 顶层节点——避免重复挂载）
    const nextLevel = node.level + 1
    const linkedIds = new Set<string>()
    edges.forEach(edge => {
      const candidateId = edge.source === node.id ? edge.target : edge.target === node.id ? edge.source : null
      if (candidateId && byId.get(candidateId)?.level === nextLevel
          && !withParent.has(candidateId) && !rootIds.has(candidateId)) linkedIds.add(candidateId)
    })
    const childIds = directChildren.length > 0
      ? [...directChildren.map(c => c.id), ...linkedIds]
      : linkedIds.size > 0
        ? [...linkedIds]
        : nodes.filter(candidate => candidate.level === nextLevel && !withParent.has(candidate.id) && !rootIds.has(candidate.id)).map(candidate => candidate.id)

    return {
      ...node,
      children: [...new Set(childIds)]
        .map(childId => byId.get(childId))
        .filter((child): child is BubbleNode => Boolean(child))
        .map(child => buildNode(child, nextVisited)),
    }
  }

  return roots.map(node => buildNode(node, new Set()))
}

function Bubble({ node, size, onClick }: { node: BubbleNode; size: number; onClick: () => void }) {
  const hc = HEALTH_COLOR[node.health] || HEALTH_COLOR.normal
  const hasChildren = node.children.length > 0

  const activate = () => {
    if (hasChildren) onClick()
  }

  return (
    <div
      role="button"
      tabIndex={hasChildren ? 0 : -1}
      aria-label={hasChildren ? `进入${node.name}下一层` : node.name}
      onClick={activate}
      onKeyDown={event => {
        if ((event.key === 'Enter' || event.key === ' ') && hasChildren) {
          event.preventDefault()
          onClick()
        }
      }}
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        background: `radial-gradient(circle at 35% 30%, ${hc.stroke}28, ${hc.fill})`,
        border: `2px solid ${hc.stroke}`,
        boxShadow: `0 0 24px ${hc.glow}44`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 3,
        cursor: hasChildren ? 'pointer' : 'default',
        transition: 'transform 180ms ease, box-shadow 180ms ease',
        position: 'relative',
        userSelect: 'none',
        outline: 'none',
      }}
      onMouseEnter={event => {
        if (hasChildren) {
          event.currentTarget.style.transform = 'scale(1.08)'
          event.currentTarget.style.boxShadow = `0 0 34px ${hc.glow}88`
        }
      }}
      onMouseLeave={event => {
        event.currentTarget.style.transform = 'scale(1)'
        event.currentTarget.style.boxShadow = `0 0 24px ${hc.glow}44`
      }}
    >
      {node.health === 'danger' && (
        <div style={{
          position: 'absolute', inset: -7, borderRadius: '50%',
          border: `1px dashed ${hc.stroke}`, opacity: 0.65,
          animation: 'rccBubblePulse 1.6s infinite',
        }} />
      )}
      <TeamOutlined style={{ color: hc.text, fontSize: Math.max(16, size * 0.12) }} />
      <span style={{
        color: COLORS.text, fontSize: Math.max(11, size * 0.075), fontWeight: 700,
        maxWidth: size * 0.76, overflow: 'hidden', textOverflow: 'ellipsis',
        whiteSpace: 'nowrap', textAlign: 'center',
      }}>
        {node.name}
      </span>
      <span style={{ color: hc.text, fontSize: Math.max(15, size * 0.105), fontWeight: 800 }}>
        {Math.round(node.load * 100)}%
      </span>
      <span style={{ color: COLORS.textDim, fontSize: Math.max(9, size * 0.06) }}>
        {LEVEL_LABEL[node.level] || `L${node.level}`} · {healthLabel(node.health)}
      </span>
      {hasChildren && (
        <span style={{
          position: 'absolute', bottom: size * 0.1,
          color: COLORS.textMuted, fontSize: 9,
        }}>
          {node.children.length} 个下级 · 点击进入 ›
        </span>
      )}
      {node.violations.length > 0 && (
        <span style={{
          position: 'absolute', top: size * 0.07, right: size * 0.07,
          minWidth: 18, height: 18, padding: '0 5px', borderRadius: 10,
          background: COLORS.danger, color: '#fff', fontSize: 10,
          fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          {node.violations.length}
        </span>
      )}
    </div>
  )
}

export default function RCCOrgBubbles({ factoryId = 'FAC_ELEC_DEMO_2026' }: RCCOrgBubblesProps) {
  const [tree, setTree] = useState<BubbleNode[]>([])
  const [edges, setEdges] = useState<BubbleEdge[]>([])
  const [meta, setMeta] = useState<{ total_nodes: number; total_edges: number } | null>(null)
  const [path, setPath] = useState<BubbleNode[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await axios.get(`${API_BASE}/org-bubbles`, { params: { factory_id: factoryId } })
      const data = response.data
      const rawNodes: BubbleNode[] = (data.nodes || []).map((node: Omit<BubbleNode, 'children'>) => ({
        ...node,
        children: [],
      }))

      if (!data.success || rawNodes.length === 0) {
        setTree([])
        setEdges([])
        setMeta(null)
        setError('RCC气泡数据返回为空')
      } else {
        const nextEdges = data.edges || []
        setTree(buildHierarchy(rawNodes, nextEdges))
        setEdges(nextEdges)
        setMeta(data.meta || null)
        setPath([])
      }
    } catch (requestError: any) {
      setTree([])
      setEdges([])
      setMeta(null)
      setError(requestError?.response?.data?.detail || requestError?.message || 'RCC气泡数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [factoryId])

  useEffect(() => { fetchData() }, [fetchData])

  // 当前层：drill 路径最后节点 或 顶层（tree 数组，无 L0 虚拟根）
  const currentNode = path[path.length - 1] || null
  const children = currentNode ? (currentNode.children || []) : tree
  const childIds = useMemo(() => new Set(children.map(child => child.id)), [children])
  const currentEdges = useMemo(() => {
    if (!currentNode) return []  // 顶层：直接展示全部节点，无单一中心协同链
    return edges.filter(edge => {
      const connected = edge.source === currentNode.id || edge.target === currentNode.id
      const childId = edge.source === currentNode.id ? edge.target : edge.source
      return connected && childIds.has(childId)
    })
  }, [children, childIds, currentNode, edges])

  const getBubbleSize = (node: BubbleNode) => {
    const maxLoad = Math.max(...children.map(child => child.load), 0.01)
    const ratio = node.load / maxLoad
    const base = path.length === 0 ? 206 : path.length === 1 ? 176 : 148
    return Math.round(Math.max(112, base * (0.72 + ratio * 0.28)))
  }

  const drillInto = (node: BubbleNode) => {
    if (node.children.length > 0) setPath(currentPath => [...currentPath, node])
  }

  const goBack = () => setPath(currentPath => currentPath.slice(0, -1))
  const goToLevel = (index: number) => setPath(index < 0 ? [] : currentPath => currentPath.slice(0, index + 1))

  return (
    <div style={{ position: 'relative' }}>
      <style>{`
        @keyframes rccBubblePulse {
          0%, 100% { opacity: .65; transform: scale(1); }
          50% { opacity: .2; transform: scale(1.07); }
        }
        @keyframes rccBubbleIn {
          from { opacity: 0; transform: scale(.72); }
          to { opacity: 1; transform: scale(1); }
        }
      `}</style>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
        <TeamOutlined style={{ color: COLORS.accent, fontSize: 18 }} />
        <span style={{ color: COLORS.text, fontWeight: 700, fontSize: 15 }}>任务智慧中心 · 组织层级气泡图</span>
        {meta && (
          <Tag style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, color: COLORS.textDim }}>
            {meta.total_nodes} 个组织 · {meta.total_edges} 条协同链
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

      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        marginBottom: 14, padding: '10px 12px',
        background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, borderRadius: 10,
      }}>
        <Button
          size="small"
          icon={<ArrowLeftOutlined />}
          onClick={goBack}
          disabled={path.length === 0}
          style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, color: COLORS.text }}
        >
          上一层
        </Button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, flex: 1, flexWrap: 'wrap' }}>
          <span
            onClick={() => goToLevel(-1)}
            style={{ color: path.length === 0 ? COLORS.accent : COLORS.textDim, cursor: 'pointer', fontSize: 13, fontWeight: 600 }}
          >
            <HomeOutlined style={{ marginRight: 4 }} />RCC组织
          </span>
          {path.map((node, index) => (
            <span key={node.id} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ color: COLORS.textMuted, fontSize: 11 }}>›</span>
              <span
                onClick={() => goToLevel(index)}
                style={{
                  color: index === path.length - 1 ? (HEALTH_COLOR[node.health]?.text || COLORS.text) : COLORS.textDim,
                  cursor: 'pointer', fontSize: 13, fontWeight: index === path.length - 1 ? 700 : 400,
                }}
              >
                {node.name}
              </span>
            </span>
          ))}
        </div>
        <Tooltip title="重新加载层级气泡">
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={fetchData}
            style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, color: COLORS.textDim }}
          />
        </Tooltip>
      </div>

      {currentNode && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 14,
          padding: '10px 16px', background: COLORS.bgCard,
          border: `1px solid ${COLORS.border}`, borderRadius: 10,
        }}>
          <div style={{ width: 12, height: 12, borderRadius: '50%', background: HEALTH_COLOR[currentNode.health].stroke, boxShadow: `0 0 10px ${HEALTH_COLOR[currentNode.health].glow}` }} />
          <span style={{ color: COLORS.text, fontWeight: 700 }}>{currentNode.name}</span>
          <Tag style={{ background: COLORS.bg, border: `1px solid ${HEALTH_COLOR[currentNode.health].stroke}66`, color: HEALTH_COLOR[currentNode.health].text }}>
            {LEVEL_LABEL[currentNode.level] || `L${currentNode.level}`}
          </Tag>
          <span style={{ color: COLORS.textDim, fontSize: 12 }}>{children.length} 个下级节点</span>
          {currentEdges.length > 0 && (
            <span style={{ color: COLORS.textMuted, fontSize: 12 }}>
              <ThunderboltOutlined style={{ color: COLORS.warning, marginRight: 4 }} />{currentEdges.length} 条直接协同链
            </span>
          )}
          <span style={{ color: COLORS.textMuted, fontSize: 12, marginLeft: 'auto' }}>
            <ApiOutlined style={{ marginRight: 4, color: COLORS.accentBlue }} />{currentNode.scope}
          </span>
        </div>
      )}

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
          minHeight: 430, overflow: 'hidden', position: 'relative',
        }}>
          {!tree && !loading ? (
            <div style={{ height: 380, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Empty description={<span style={{ color: COLORS.textDim }}>当前工厂暂无RCC气泡节点</span>} />
            </div>
          ) : children.length === 0 && !loading ? (
            <div style={{ height: 380, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: COLORS.textMuted }}>
              <div style={{ fontSize: 34, marginBottom: 12 }}>⌁</div>
              <div style={{ color: COLORS.text, fontWeight: 700 }}>已到达最底层</div>
              <div style={{ marginTop: 6, fontSize: 12 }}>点击“上一层”返回继续查看其他组织节点</div>
            </div>
          ) : (
            <div style={{
              display: 'flex', flexWrap: 'wrap', gap: 28,
              justifyContent: 'center', alignItems: 'center',
              padding: '46px 24px', minHeight: 430,
            }}>
              {children.map((child, index) => (
                <div key={child.id} style={{ animation: `rccBubbleIn 320ms cubic-bezier(.34,1.56,.64,1) ${index * 55}ms both` }}>
                  <Bubble node={child} size={getBubbleSize(child)} onClick={() => drillInto(child)} />
                </div>
              ))}
            </div>
          )}
        </div>
      </Spin>

      <div style={{
        display: 'flex', justifyContent: 'center', gap: 24, marginTop: 14,
        padding: '12px 0', borderTop: `1px solid ${COLORS.border}`,
      }}>
        <Space size={5}><div style={{ width: 10, height: 10, borderRadius: '50%', background: '#00d4aa' }} /><span style={{ color: COLORS.textMuted, fontSize: 11 }}>正常</span></Space>
        <Space size={5}><div style={{ width: 10, height: 10, borderRadius: '50%', background: '#fbbf24' }} /><span style={{ color: COLORS.textMuted, fontSize: 11 }}>预警</span></Space>
        <Space size={5}><div style={{ width: 10, height: 10, borderRadius: '50%', background: '#f87171' }} /><span style={{ color: COLORS.textMuted, fontSize: 11 }}>瓶颈</span></Space>
        <span style={{ color: COLORS.textMuted, fontSize: 11 }}>气泡大小 = 当前负荷 · 点击进入下一层</span>
      </div>
    </div>
  )
}
