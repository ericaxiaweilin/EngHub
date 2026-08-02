/**
 * 组织气泡下钻组件 — 内联全屏模式
 * 点击大气泡 → 整个视图"进入"该气泡 → 内部裂变为小气泡
 * 不是侧边弹出，而是沉浸式下钻
 * 层级: 工厂 → 部门/车间 → 工位 → 班次/技能
 */
import { useState, useEffect, useCallback } from 'react'
import { Spin, Empty, Tag, Space, Button, Tooltip } from 'antd'
import {
  ArrowLeftOutlined, ReloadOutlined, TeamOutlined,
  ToolOutlined, FileTextOutlined, HomeOutlined,
} from '@ant-design/icons'
import api from '../services/api'
import { COLORS } from '../pages/rcc/RCCCommandCenter'

// ==================== 类型 ====================
interface BubbleNode {
  id: string
  name: string
  level: string
  count: number
  active?: number
  health: 'normal' | 'warning' | 'danger'
  skills?: Record<string, number>
  children?: BubbleNode[]
}

interface Props {
  factoryId: string
  domain: string
  title?: string
  onBack: () => void
}

// ==================== 健康配色 ====================
const HEALTH_STYLE: Record<string, { bg: string; border: string; text: string; glow: string }> = {
  normal: { bg: 'rgba(16,185,129,0.06)', border: '#10b981', text: '#34d399', glow: '0 0 24px rgba(16,185,129,0.25)' },
  warning: { bg: 'rgba(251,191,36,0.06)', border: '#fbbf24', text: '#fbbf24', glow: '0 0 24px rgba(251,191,36,0.25)' },
  danger: { bg: 'rgba(248,113,113,0.06)', border: '#f87171', text: '#f87171', glow: '0 0 28px rgba(248,113,113,0.35)' },
}

const LEVEL_ICON: Record<string, React.ReactNode> = {
  factory: <TeamOutlined />,
  department: <TeamOutlined />,
  station: <ToolOutlined />,
  shift: <FileTextOutlined />,
  status: <FileTextOutlined />,
}

const LEVEL_LABEL: Record<string, string> = {
  factory: '工厂',
  department: '部门/车间',
  station: '工位',
  shift: '班次',
  status: '状态',
}

// ==================== 单个气泡 ====================
function Bubble({ node, size, onClick }: { node: BubbleNode; size: number; onClick?: () => void }) {
  const hs = HEALTH_STYLE[node.health] || HEALTH_STYLE.normal
  const hasChildren = node.children && node.children.length > 0
  const ratio = node.active !== undefined && node.count > 0 ? Math.round((node.active / node.count) * 100) : null

  return (
    <div
      onClick={onClick}
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        background: `radial-gradient(circle at 35% 35%, ${hs.border}18, ${hs.bg})`,
        border: `2.5px solid ${hs.border}`,
        boxShadow: hs.glow,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: hasChildren ? 'pointer' : 'default',
        transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
        position: 'relative',
        userSelect: 'none',
      }}
      onMouseEnter={(e) => {
        if (hasChildren) {
          e.currentTarget.style.transform = 'scale(1.1)'
          e.currentTarget.style.boxShadow = `0 0 40px ${hs.border}66, inset 0 0 20px ${hs.border}22`
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'scale(1)'
        e.currentTarget.style.boxShadow = hs.glow
      }}
    >
      {/* 异常脉冲环 */}
      {node.health === 'danger' && (
        <div style={{
          position: 'absolute', inset: -6, borderRadius: '50%',
          border: `2px dashed ${hs.border}`, opacity: 0.5,
          animation: 'bubblePulse 1.8s infinite',
        }} />
      )}
      {/* 图标 */}
      <span style={{ color: hs.text, fontSize: Math.max(14, size * 0.13), marginBottom: 2, opacity: 0.9 }}>
        {LEVEL_ICON[node.level]}
      </span>
      {/* 名称 */}
      <span style={{
        color: COLORS.text, fontSize: Math.max(11, size * 0.085), fontWeight: 700,
        maxWidth: size * 0.75, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        textAlign: 'center',
      }}>
        {node.name}
      </span>
      {/* 数量 */}
      <span style={{ color: hs.text, fontSize: Math.max(13, size * 0.11), fontWeight: 800, marginTop: 1 }}>
        {node.count}
      </span>
      {/* 比率 */}
      {ratio !== null && (
        <span style={{ color: COLORS.textDim, fontSize: Math.max(9, size * 0.065) }}>
          {ratio}%
        </span>
      )}
      {/* 子节点角标 */}
      {hasChildren && (
        <div style={{
          position: 'absolute', top: size * 0.06, right: size * 0.06,
          background: hs.border, color: '#000', borderRadius: 10,
          padding: '1px 7px', fontSize: 10, fontWeight: 800,
        }}>
          {node.children!.length}
        </div>
      )}
      {/* 进入提示 */}
      {hasChildren && (
        <div style={{
          position: 'absolute', bottom: size * 0.1,
          color: COLORS.textMuted, fontSize: 9, opacity: 0.7,
        }}>
          点击进入 ›
        </div>
      )}
    </div>
  )
}

// ==================== 主组件 ====================
export default function OrgBubbleDrillDown({ factoryId, domain, title, onBack }: Props) {
  const [loading, setLoading] = useState(false)
  const [tree, setTree] = useState<BubbleNode | null>(null)
  const [path, setPath] = useState<BubbleNode[]>([])

  const fetchHierarchy = useCallback(async () => {
    setLoading(true)
    setPath([])
    try {
      const res: any = await api.get('/api/v1/rcc/org-hierarchy', {
        params: { factory_id: factoryId, domain },
      })
      if (res?.success && res?.tree) {
        setTree(res.tree)
      } else {
        setTree(null)
      }
    } catch {
      setTree(null)
    }
    setLoading(false)
  }, [factoryId, domain])

  useEffect(() => { fetchHierarchy() }, [fetchHierarchy])

  const currentNode = path.length > 0 ? path[path.length - 1] : tree
  const children = currentNode?.children || []
  const hs = currentNode ? (HEALTH_STYLE[currentNode.health] || HEALTH_STYLE.normal) : HEALTH_STYLE.normal

  const drillInto = (node: BubbleNode) => {
    if (node.children && node.children.length > 0) {
      setPath([...path, node])
    }
  }

  const goToLevel = (index: number) => {
    if (index < 0) { setPath([]) }
    else { setPath(path.slice(0, index + 1)) }
  }

  // 气泡大小：按数量占比
  const getBubbleSize = (node: BubbleNode) => {
    const base = path.length === 0 ? 170 : path.length === 1 ? 140 : 110
    const maxCount = Math.max(...children.map(c => c.count), 1)
    const ratio = node.count / maxCount
    return Math.max(80, base * (0.55 + ratio * 0.45))
  }

  return (
    <div style={{
      background: COLORS.bg, borderRadius: 16, border: `1px solid ${COLORS.border}`,
      minHeight: 480, padding: 24, position: 'relative', overflow: 'hidden',
    }}>
      <style>{`
        @keyframes bubblePulse {
          0%, 100% { opacity: 0.5; transform: scale(1); }
          50% { opacity: 0.15; transform: scale(1.06); }
        }
        @keyframes bubbleIn {
          from { opacity: 0; transform: scale(0.5); }
          to { opacity: 1; transform: scale(1); }
        }
      `}</style>

      {/* 顶部导航栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
        <Button
          size="small" icon={<ArrowLeftOutlined />}
          onClick={path.length > 0 ? () => setPath(path.slice(0, -1)) : onBack}
          style={{ background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, color: COLORS.text }}
        >
          {path.length > 0 ? '上一层' : '返回总览'}
        </Button>

        {/* 面包屑 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flex: 1, flexWrap: 'wrap' }}>
          <span
            onClick={() => goToLevel(-1)}
            style={{ color: path.length === 0 ? hs.text : COLORS.textDim, cursor: 'pointer', fontSize: 13, fontWeight: 600 }}
          >
            <HomeOutlined style={{ marginRight: 4 }} />{tree?.name || factoryId}
          </span>
          {path.map((p, i) => (
            <span key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ color: COLORS.textMuted, fontSize: 11 }}>›</span>
              <span
                onClick={() => goToLevel(i)}
                style={{
                  color: i === path.length - 1 ? (HEALTH_STYLE[p.health]?.text || COLORS.text) : COLORS.textDim,
                  cursor: 'pointer', fontSize: 13, fontWeight: i === path.length - 1 ? 700 : 400,
                }}
              >
                {p.name}
              </span>
            </span>
          ))}
        </div>

        <Button
          size="small" icon={<ReloadOutlined />} loading={loading} onClick={fetchHierarchy}
          style={{ background: COLORS.bgCard, border: `1px solid ${COLORS.border}`, color: COLORS.textDim }}
        />
      </div>

      {/* 当前节点信息条 */}
      {currentNode && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 14, marginBottom: 24,
          padding: '10px 18px', borderRadius: 12,
          background: COLORS.bgCard, border: `1px solid ${COLORS.border}`,
        }}>
          <div style={{ width: 14, height: 14, borderRadius: '50%', background: hs.border, boxShadow: `0 0 10px ${hs.border}` }} />
          <span style={{ color: COLORS.text, fontWeight: 700, fontSize: 15 }}>{currentNode.name}</span>
          <Tag style={{ background: hs.bg, border: `1px solid ${hs.border}`, color: hs.text }}>
            {LEVEL_LABEL[currentNode.level] || currentNode.level}
          </Tag>
          <span style={{ color: COLORS.textDim, fontSize: 13 }}>
            {currentNode.count} 条{currentNode.active !== undefined ? ` · ${currentNode.active} 有效` : ''}
          </span>
          {/* 技能标签 */}
          {currentNode.skills && Object.keys(currentNode.skills).length > 0 && (
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
              {Object.entries(currentNode.skills).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([k, v]) => (
                <Tag key={k} style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, color: COLORS.textDim, fontSize: 10 }}>
                  {k}:{v}
                </Tag>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 气泡区域 */}
      <Spin spinning={loading}>
        {!tree ? (
          <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Empty description={<span style={{ color: COLORS.textDim }}>暂无组织层级数据</span>} />
          </div>
        ) : children.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: 60, color: COLORS.textMuted,
            background: COLORS.bgCard, borderRadius: 16, border: `1px solid ${COLORS.border}`,
          }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>🔍</div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>已到达最底层</div>
            <div style={{ fontSize: 12, marginTop: 6, color: COLORS.textDim }}>
              {currentNode?.name} · {currentNode?.count} 条记录
            </div>
          </div>
        ) : (
          <div style={{
            display: 'flex', flexWrap: 'wrap', gap: 24,
            justifyContent: 'center', alignItems: 'center',
            padding: '30px 10px', minHeight: 280,
          }}>
            {children.map((child, i) => (
              <div key={child.id} style={{ animation: `bubbleIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1) ${i * 0.06}s both` }}>
                <Bubble
                  node={child}
                  size={getBubbleSize(child)}
                  onClick={() => drillInto(child)}
                />
              </div>
            ))}
          </div>
        )}
      </Spin>

      {/* 底部图例 */}
      <div style={{
        display: 'flex', justifyContent: 'center', gap: 24, marginTop: 24,
        padding: '12px 0', borderTop: `1px solid ${COLORS.border}`,
      }}>
        <Space size={5}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#10b981' }} />
          <span style={{ color: COLORS.textMuted, fontSize: 11 }}>正常 ≥90%</span>
        </Space>
        <Space size={5}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#fbbf24' }} />
          <span style={{ color: COLORS.textMuted, fontSize: 11 }}>预警 70-90%</span>
        </Space>
        <Space size={5}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#f87171' }} />
          <span style={{ color: COLORS.textMuted, fontSize: 11 }}>异常 &lt;70%</span>
        </Space>
        <Space size={5}>
          <span style={{ color: COLORS.textMuted, fontSize: 11 }}>大小 = 数量占比 · 点击气泡进入下一层</span>
        </Space>
      </div>
    </div>
  )
}
