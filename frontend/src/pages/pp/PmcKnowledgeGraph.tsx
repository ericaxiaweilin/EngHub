import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button, Card, Empty, Space, Tag, Typography } from 'antd'
import { CloseOutlined, ThunderboltOutlined } from '@ant-design/icons'

const { Text, Title } = Typography

export const NEURAL_COLORS = {
  bg: '#0f1923',
  bgCard: 'rgba(26, 39, 51, 0.92)',
  border: '#2a3f50',
  accent: '#00d4aa',
  accentBlue: '#4facfe',
  accentPurple: '#a78bfa',
  warning: '#fbbf24',
  danger: '#f87171',
  text: '#e2e8f0',
  textDim: '#94a3b8',
}

interface GraphQuestion {
  id: string
  question_code: string
  skill: string
  difficulty: number
  prompt: string
  reference_terms?: string[]
}

interface PackData {
  position?: {
    title?: string
    duties?: string
    escalation?: string
    related_tools?: string
    daily_flow?: Array<{ step: number; task: string; detail: string }>
  }
  quiz?: { questions?: GraphQuestion[] }
  factory_id?: string | null
}

interface WebNode {
  id: string
  label: string
  type: 'root' | 'skill' | 'term'
  radius: number
  color: string
  angle: number
  ring: number
  skill?: string
  qcount?: number
  maxDiff?: number
}

interface WebEdge {
  source: string
  target: string
  color: string
}

const skillColor = (i: number): string => {
  const palette = ['#00d4aa', '#4facfe', '#a78bfa', '#fbbf24', '#34d399', '#f472b6']
  return palette[i % palette.length]
}

interface PmcKnowledgeGraphProps {
  pack: PackData
  onSelectSkill: (skill: string | null) => void
  selectedSkill: string | null
}

const PmcKnowledgeGraph: React.FC<PmcKnowledgeGraphProps> = ({ pack, onSelectSkill, selectedSkill }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const hoveredRef = useRef<string | null>(null)

  const { nodes, edges, skillList } = useMemo(() => {
    const questions: GraphQuestion[] = pack?.quiz?.questions || []
    const rootTitle = pack?.position?.title || 'PMC 计划员'
    const bySkill = new Map<string, GraphQuestion[]>()
    questions.forEach((q) => {
      const list = bySkill.get(q.skill) || []
      list.push(q)
      bySkill.set(q.skill, list)
    })
    const skills = Array.from(bySkill.keys())
    const nodes: WebNode[] = [
      { id: '__root__', label: rootTitle, type: 'root', radius: 16, color: NEURAL_COLORS.accent, angle: 0, ring: 0 },
    ]
    const edges: WebEdge[] = []
    skills.forEach((skill, i) => {
      const qs = bySkill.get(skill) || []
      const maxDiff = Math.max(...qs.map((q) => q.difficulty || 1))
      const angle = (i / skills.length) * Math.PI * 2
      nodes.push({
        id: `skill:${skill}`,
        label: skill,
        type: 'skill',
        radius: maxDiff >= 3 ? 11 : maxDiff === 2 ? 9 : 7,
        color: skillColor(i),
        angle,
        ring: 1,
        qcount: qs.length,
        maxDiff,
      })
      edges.push({ source: '__root__', target: `skill:${skill}`, color: skillColor(i) })
      qs.forEach((q, k) => {
        ;(q.reference_terms || []).forEach((term, m) => {
          const tId = `term:${skill}:${term}`
          nodes.push({
            id: tId,
            label: term,
            type: 'term',
            radius: 3,
            color: NEURAL_COLORS.textDim,
            angle: angle + (k * 0.35 + m * 0.12) * (k % 2 === 0 ? 1 : -1),
            ring: 2,
            skill,
          })
          edges.push({ source: `skill:${skill}`, target: tId, color: skillColor(i) })
        })
      })
    })
    return { nodes, edges, skillList: skills }
  }, [pack])

  useEffect(() => {
    hoveredRef.current = hovered
  }, [hovered])

  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let width = 0
    let height = 0
    let raf = 0
    let t = 0
    const dpr = Math.min(window.devicePixelRatio || 1, 2)

    const resize = () => {
      const rect = wrap.getBoundingClientRect()
      width = rect.width
      height = rect.height
      canvas.width = width * dpr
      canvas.height = height * dpr
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(wrap)

    const pos = (angle: number, ring: number): { x: number; y: number } => {
      const cx = width / 2
      const cy = height / 2
      const r1 = Math.min(width, height) * 0.36
      const r2 = r1 * 0.58
      const r = ring === 0 ? 0 : ring === 1 ? r1 : r2
      const a = angle + Math.sin(t * 0.0004) * 0.02
      return { x: cx + Math.cos(a) * r, y: cy + Math.sin(a) * r }
    }

    const nodePos = (n: WebNode): { x: number; y: number } => pos(n.angle, n.ring)

    const draw = () => {
      t += 1
      ctx.clearRect(0, 0, width, height)
      const cx = width / 2
      const cy = height / 2
      const r1 = Math.min(width, height) * 0.36
      const r2 = r1 * 0.58
      const hover = hoveredRef.current

      ctx.save()
      ctx.beginPath()
      ctx.arc(cx, cy, r2, 0, Math.PI * 2)
      ctx.strokeStyle = 'rgba(42, 63, 80, 0.5)'
      ctx.lineWidth = 1
      ctx.stroke()
      ctx.beginPath()
      ctx.arc(cx, cy, r1, 0, Math.PI * 2)
      ctx.strokeStyle = 'rgba(42, 63, 80, 0.65)'
      ctx.lineWidth = 1.2
      ctx.stroke()
      ctx.restore()

      edges.forEach((edge) => {
        const s = nodes.find((n) => n.id === edge.source)
        const e = nodes.find((n) => n.id === edge.target)
        if (!s || !e) return
        const ps = nodePos(s)
        const pe = nodePos(e)
        const active = hover === s.id || hover === e.id
        const selected = selectedSkill && (s.id === `skill:${selectedSkill}` || e.id === `skill:${selectedSkill}`)
        ctx.beginPath()
        ctx.moveTo(ps.x, ps.y)
        ctx.lineTo(pe.x, pe.y)
        ctx.strokeStyle = active
          ? edge.color
          : selected
            ? edge.color + 'aa'
            : edge.color + '2e'
        ctx.lineWidth = active ? 2 : 1
        ctx.stroke()
      })

      nodes.forEach((n) => {
        const p = nodePos(n)
        const active = hover === n.id
        const selected = selectedSkill && (n.id === `skill:${selectedSkill}` || n.skill === selectedSkill)
        if (n.type === 'root') {
          ctx.beginPath()
          ctx.arc(p.x, p.y, 22, 0, Math.PI * 2)
          const grad = ctx.createRadialGradient(p.x, p.y, 2, p.x, p.y, 22)
          grad.addColorStop(0, 'rgba(0, 212, 170, 0.35)')
          grad.addColorStop(1, 'rgba(0, 212, 170, 0)')
          ctx.fillStyle = grad
          ctx.fill()
        }
        ctx.beginPath()
        ctx.arc(p.x, p.y, n.radius, 0, Math.PI * 2)
        ctx.fillStyle = active ? '#ffffff' : n.color
        ctx.fill()
        if (active || selected || n.type === 'skill') {
          ctx.beginPath()
          ctx.arc(p.x, p.y, n.radius + 4, 0, Math.PI * 2)
          ctx.strokeStyle = (active ? '#ffffff' : n.color) + '55'
          ctx.lineWidth = 1.5
          ctx.stroke()
        }
        if (n.type === 'skill') {
          ctx.font = '11px system-ui, sans-serif'
          ctx.fillStyle = active || selected ? n.color : 'rgba(148, 163, 184, 0.9)'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'top'
          ctx.fillText(n.label, p.x, p.y + n.radius + 6)
        }
      })

      ;(nodes.filter((n) => n.type === 'skill') as WebNode[]).forEach((skill) => {
        const ps = nodePos(skill)
        const prog = (t * 0.0012 + skill.angle * 3) % 1
        const pr = r2 + (r1 - r2) * prog
        const a = skill.angle + Math.sin(t * 0.0004) * 0.02
        const px = cx + Math.cos(a) * pr
        const py = cy + Math.sin(a) * pr
        ctx.beginPath()
        ctx.arc(px, py, 2, 0, Math.PI * 2)
        ctx.fillStyle = skill.color + 'cc'
        ctx.fill()
        ctx.beginPath()
        ctx.moveTo(ps.x, ps.y)
        ctx.lineTo(px, py)
        ctx.strokeStyle = skill.color + '18'
        ctx.lineWidth = 0.8
        ctx.stroke()
        const back = (t * 0.0008 + skill.angle * 5) % 1
        const br = r2 + (r1 - r2) * back
        const bx = cx + Math.cos(a) * br
        const by = cy + Math.sin(a) * br
        ctx.beginPath()
        ctx.arc(bx, by, 1.4, 0, Math.PI * 2)
        ctx.fillStyle = '#ffffff40'
        ctx.fill()
      })

      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)

    const hitTest = (clientX: number, clientY: number): string | null => {
      const rect = canvas.getBoundingClientRect()
      const mx = clientX - rect.left
      const my = clientY - rect.top
      let best: { id: string; d: number } | null = null
      nodes.forEach((n) => {
        const p = nodePos(n)
        const dist = Math.hypot(p.x - mx, p.y - my)
        const rr = n.type === 'root' ? 22 : n.radius + (n.type === 'skill' ? 8 : 6)
        if (dist < rr && (!best || dist < best.d)) best = { id: n.id, d: dist }
      })
      return best?.id ?? null
    }

    const onMove = (ev: MouseEvent) => {
      const id = hitTest(ev.clientX, ev.clientY)
      setHovered((prev) => (prev === id ? prev : id))
    }
    const onClick = (ev: MouseEvent) => {
      const id = hitTest(ev.clientX, ev.clientY)
      if (!id) return
      const n = nodes.find((x) => x.id === id)
      if (!n) return
      if (n.type === 'root') onSelectSkill(null)
      else if (n.type === 'skill') onSelectSkill(n.label)
      else if (n.skill) onSelectSkill(n.skill)
    }
    canvas.addEventListener('mousemove', onMove)
    canvas.addEventListener('click', onClick)

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      canvas.removeEventListener('mousemove', onMove)
      canvas.removeEventListener('click', onClick)
    }
  }, [nodes, edges, onSelectSkill, selectedSkill])

  return (
    <div
      ref={wrapRef}
      style={{
        position: 'relative',
        width: '100%',
        height: 460,
        borderRadius: 12,
        border: `1px solid ${NEURAL_COLORS.border}`,
        background: `radial-gradient(circle at 50% 50%, #16222e 0%, ${NEURAL_COLORS.bg} 70%)`,
        overflow: 'hidden',
      }}
    >
      <canvas ref={canvasRef} style={{ display: 'block', width: '100%', height: '100%', cursor: 'pointer' }} />
      <div style={{ position: 'absolute', top: 12, left: 14, pointerEvents: 'none' }}>
        <Space size={4}>
          <Tag color="cyan" style={{ background: NEURAL_COLORS.bgCard, border: `1px solid ${NEURAL_COLORS.border}` }}>
            知识图谱 · 神经蛛网
          </Tag>
          <Tag color="default" style={{ background: NEURAL_COLORS.bgCard, border: `1px solid ${NEURAL_COLORS.border}`, color: NEURAL_COLORS.textDim }}>
            {skillList.length} 技能 · {nodes.length - skillList.length - 1} 术语
          </Tag>
        </Space>
      </div>
      <div style={{ position: 'absolute', bottom: 12, left: 14, right: 14, pointerEvents: 'none' }}>
        <Space wrap>
          {skillList.slice(0, 12).map((skill) => {
            const n = nodes.find((x) => x.id === `skill:${skill}`)
            const active = hovered === `skill:${skill}` || selectedSkill === skill
            return (
              <Tag
                key={skill}
                style={{
                  background: active ? n?.color + '22' : 'transparent',
                  border: `1px solid ${active ? n?.color : NEURAL_COLORS.border}`,
                  color: active ? n?.color : NEURAL_COLORS.textDim,
                  cursor: 'pointer',
                  pointerEvents: 'auto',
                }}
                onClick={() => onSelectSkill(selectedSkill === skill ? null : skill)}
              >
                {skill}
              </Tag>
            )
          })}
          {skillList.length > 12 && (
            <Text style={{ color: NEURAL_COLORS.textMuted || NEURAL_COLORS.textDim, fontSize: 12 }}>
              +{skillList.length - 12} 更多
            </Text>
          )}
        </Space>
      </div>
      {hovered && (() => {
        const n = nodes.find((x) => x.id === hovered)
        if (!n) return null
        return (
          <div
            style={{
              position: 'absolute',
              top: 12,
              right: 14,
              maxWidth: 260,
              padding: '8px 12px',
              borderRadius: 8,
              background: NEURAL_COLORS.bgCard,
              border: `1px solid ${n.color}66`,
              boxShadow: `0 0 20px ${n.color}22`,
              pointerEvents: 'none',
            }}
          >
            <Text style={{ color: n.color, fontWeight: 600, fontSize: 12 }}>{n.label}</Text>
            <div>
              <Text style={{ color: NEURAL_COLORS.textDim, fontSize: 11 }}>
                {n.type === 'root' ? '岗位知识中心' : n.type === 'skill' ? `技能 · ${n.qcount} 题` : '知识术语'}
              </Text>
            </div>
          </div>
        )
      })()}
    </div>
  )
}

const SkillPanel: React.FC<{ pack: PackData; skill: string; onClose: () => void }> = ({ pack, skill, onClose }) => {
  const questions = (pack?.quiz?.questions || []).filter((q) => q.skill === skill)
  return (
    <Card
      size="small"
      style={{ background: NEURAL_COLORS.bgCard, border: `1px solid ${NEURAL_COLORS.border}` }}
      title={
        <Space>
          <ThunderboltOutlined style={{ color: NEURAL_COLORS.accent }} />
          <Text style={{ color: NEURAL_COLORS.text }}>{skill}</Text>
        </Space>
      }
      extra={<Button size="small" type="text" icon={<CloseOutlined />} onClick={onClose} style={{ color: NEURAL_COLORS.textDim }} />}
    >
      {!questions.length ? (
        <Empty description="暂无题目" />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={10}>
          {questions.map((q) => (
            <div key={q.id} style={{ padding: '8px 10px', borderRadius: 8, border: `1px solid ${NEURAL_COLORS.border}` }}>
              <Space align="start" style={{ width: '100%' }}>
                <Tag color={q.difficulty >= 3 ? 'red' : q.difficulty === 2 ? 'gold' : 'blue'}>{q.difficulty}</Tag>
                <Text style={{ color: NEURAL_COLORS.text, fontSize: 13 }}>{q.prompt}</Text>
              </Space>
              {(q.reference_terms || []).length > 0 && (
                <div style={{ marginTop: 6, paddingLeft: 4 }}>
                  <Text style={{ color: NEURAL_COLORS.textDim, fontSize: 12 }}>术语：{(q.reference_terms || []).join('、')}</Text>
                </div>
              )}
            </div>
          ))}
        </Space>
      )}
    </Card>
  )
}

export { SkillPanel, skillColor }
export default PmcKnowledgeGraph