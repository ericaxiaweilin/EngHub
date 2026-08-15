/**
 * RCC 图连接矩阵（Neural Graph）
 * 组织 → 人员/任务/物料/设备 拓扑图（@antv/x6），参考 luaguage PlmSystemFlowCanvas 图结构思路
 * 节点：组织（蓝）/ 人员（紫）/ 任务（橙）/ 物料设备（青）
 * 边：任务→归属人（member）/ 任务→卡点资源（resource）/ 已批准（绿）/ 已拒绝（红虚）
 */
import { useEffect, useRef, useState } from 'react'
import { Graph } from '@antv/x6'
import { Tag, Space, Select } from 'antd'
import { RobotOutlined, UserOutlined, CarryOutOutlined } from '@ant-design/icons'

const C = {
  bg: '#F4F6F9', surface: '#FFF', border: '#E3E7EE', text: '#172033', text2: '#596579', text3: '#93A0B4',
  brand: '#315DAA', brand2: '#214689', brandSoft: '#EAF0FC',
  cyan: '#087F8C', cyanSoft: '#E4F4F4', purple: '#7C4CB2', purpleSoft: '#F1EAF8',
  danger: '#D64545', dangerSoft: '#FBEAEA', warn: '#B36A12', warnSoft: '#FBF0DA',
  success: '#157C4F', successSoft: '#E5F6EE',
}

interface Props {
  tasks: any[]
  inbox: any
  baseline: any
}

export default function RCCNeuralGraph({ tasks, inbox, baseline }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [graph, setGraph] = useState<Graph | null>(null)
  const [selected, setSelected] = useState<string>('')
  const [viewMode, setViewMode] = useState<'graph' | 'matrix'>('graph')

  // 构建图数据
  useEffect(() => {
    if (!wrapRef.current) return
    const g = new Graph({
      container: wrapRef.current,
      autoResize: true,
      background: { color: '#FBFCFE' },
      grid: false,
      panning: true,
      mousewheel: { enabled: true, modifiers: ['ctrl', 'meta'] },
      connecting: { connector: 'smooth' },
    })
    g.on('node:click', ({ node }) => {
      setSelected(node.id)
      const n = g.getCellById(node.id)
      g.getEdges().forEach(e => e.setAttrs({ line: { stroke: '#DCE2EA', strokeWidth: 1.4 } }))
      g.getEdges()
        .filter(e => e.getSourceCellId() === node.id || e.getTargetCellId() === node.id)
        .forEach(e => e.setAttrs({ line: { stroke: C.success, strokeWidth: 3 } }))
    })
    setGraph(g)
    return () => { g.dispose() }
  }, [])

  // 数据变化 → 渲染
  useEffect(() => {
    if (!graph) return
    graph.clearCells()
    const allTasks = inbox.tasks || []
    const pendTasks = tasks.filter((t: any) => t.status === 'pending')
    // 取前 8 个任务（受阻优先）
    const shown = [...allTasks.filter((t: any) => t.status === 'blocked').slice(0, 6),
                   ...allTasks.filter((t: any) => t.status === 'open').slice(0, 4),
                   ...pendTasks.slice(0, 3)]
    const nodes: any[] = []
    const edges: any[] = []

    const nodeW = 148
    const colX = [40, 260, 480, 700, 920]
    const colY = [60, 220, 380, 540]

    // 组织节点（中央）
    nodes.push({
      id: 'org', x: 430, y: 40, width: 180, height: 44,
      shape: 'rect', attrs: {
        body: { fill: C.brandSoft, stroke: C.brand, rx: 10, strokeWidth: 1.2 },
        label: { text: 'RCC 资源调度中心', fill: C.brand2, fontSize: 12, fontWeight: 700 },
      },
    })

    // 智能体节点
    const agents = Array.from(new Set(allTasks.map((t: any) => t.agent_name || '通用'))).slice(0, 4)
    agents.forEach((a, i) => {
      nodes.push({
        id: `agent-${a}`, x: 40, y: 180 + i * 90, width: nodeW, height: 36,
        shape: 'rect', attrs: {
          body: { fill: C.cyanSoft, stroke: C.cyan, rx: 8 },
          label: { text: `🤖 ${a}`, fill: C.cyan, fontSize: 10.5, fontWeight: 650 },
        },
      })
      edges.push({
        id: `e-org-${a}`, source: 'org', target: `agent-${a}`,
        attrs: { line: { stroke: '#CBD4E1', strokeWidth: 1.2, strokeDasharray: '4 3' } },
      })
    })

    // 任务节点 + 归属人节点
    const rows = shown.slice(0, 10)
    rows.forEach((t, i) => {
      const col = i % 4
      const row = Math.floor(i / 4)
      const x = colX[col]
      const y = colY[row] + 60
      const st = t.status === 'blocked' ? C.danger : t.status === 'done' ? C.success : C.warn
      const stSoft = t.status === 'blocked' ? C.dangerSoft : t.status === 'done' ? C.successSoft : C.warnSoft
      nodes.push({
        id: `task-${t.id}`, x, y, width: nodeW, height: 52,
        shape: 'rect', attrs: {
          body: { fill: stSoft, stroke: st, rx: 10, strokeWidth: 1.4 },
          label: { text: `⛔ ${(t.title || '').slice(0, 16)}…\n${st === C.danger ? '受阻' : st === C.success ? '完成' : '跟进中'} ${t.progress_pct || 0}%`, fill: C.text, fontSize: 10, textWrap: { wrap: true, width: nodeW - 16 } },
        },
      })
      // 归属人
      const owner = t.created_by || '系统'
      const oid = `owner-${owner}-${i}`
      if (!nodes.find((n: any) => n.id === oid)) {
        nodes.push({
          id: oid, x: 40, y: 120 + i * 46, width: 120, height: 32,
          shape: 'rect', attrs: {
            body: { fill: C.purpleSoft, stroke: C.purple, rx: 8 },
            label: { text: `👤 ${owner}`, fill: C.purple, fontSize: 10, fontWeight: 650 },
          },
        })
      }
      edges.push({
        id: `e-${t.id}-owner`, source: oid, target: `task-${t.id}`,
        attrs: { line: { stroke: C.purple, strokeWidth: 1.4 } },
      })
      // 智能体
      const agent = t.agent_name || '通用'
      if (agents.includes(agent)) {
        edges.push({
          id: `e-${t.id}-agent`, source: `agent-${agent}`, target: `task-${t.id}`,
          attrs: { line: { stroke: C.cyan, strokeWidth: 1.4, strokeDasharray: '4 3' } },
        })
      }
      // RCC 审批状态
      if (t.rcc_status) {
        const rccSt = t.rcc_status
        nodes.push({
          id: `rcc-${t.id}`, x: x + nodeW + 20, y: y + 12, width: 110, height: 30,
          shape: 'rect', attrs: {
            body: { fill: rccSt === 'approved' ? C.successSoft : rccSt === 'pending' ? C.warnSoft : C.brandSoft, stroke: rccSt === 'approved' ? C.success : rccSt === 'pending' ? C.warn : C.brand, rx: 8 },
            label: { text: `RCC ${rccSt === 'approved' ? '✅已批准' : rccSt === 'pending' ? '⏳待审批' : '执行中'}`, fill: rccSt === 'approved' ? C.success : rccSt === 'pending' ? C.warn : C.brand2, fontSize: 10, fontWeight: 700 },
          },
        })
        edges.push({
          id: `e-${t.id}-rcc`, source: `task-${t.id}`, target: `rcc-${t.id}`,
          attrs: { line: { stroke: rccSt === 'approved' ? C.success : rccSt === 'pending' ? C.warn : C.brand, strokeWidth: rccSt === 'approved' ? 3 : 1.4 } },
        })
      }
    })

    graph.fromJSON({ nodes, edges })
    // 默认选中 org
    graph.centerContent()
  }, [graph, tasks, inbox])

  // 关系矩阵视图
  const allTasks = inbox.tasks || []
  const matrixRows = allTasks.slice(0, 8)

  return (
    <Space direction="vertical" size={10} style={{ width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <b style={{ fontSize: 13 }}>Resource Neural Topology · AI 调度验证</b>
        <span style={{ fontSize: 10.5, color: C.text3 }}>组织 / 人员 / 任务 / RCC 审批状态统一对齐</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
          <button onClick={() => setViewMode('graph')} style={{ border: viewMode === 'graph' ? `1px solid ${C.brand}` : `1px solid ${C.border}`, background: viewMode === 'graph' ? C.brandSoft : C.surface, color: viewMode === 'graph' ? C.brand2 : C.text3, padding: '6px 9px', borderRadius: 7, fontSize: 10.5, fontWeight: 750, cursor: 'pointer' }}>图连接</button>
          <button onClick={() => setViewMode('matrix')} style={{ border: viewMode === 'matrix' ? `1px solid ${C.brand}` : `1px solid ${C.border}`, background: viewMode === 'matrix' ? C.brandSoft : C.surface, color: viewMode === 'matrix' ? C.brand2 : C.text3, padding: '6px 9px', borderRadius: 7, fontSize: 10.5, fontWeight: 750, cursor: 'pointer' }}>关系矩阵</button>
        </div>
      </div>

      {viewMode === 'graph' ? (
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', padding: '10px 13px', borderBottom: `1px solid ${C.border}` }}>
            <b style={{ fontSize: 12.5 }}>资源连接拓扑</b>
            <span style={{ fontSize: 10.5, color: C.text3, marginLeft: 7 }}>点击节点查看关联 · 绿色粗线=选中连接</span>
            <span style={{ marginLeft: 'auto', fontSize: 10, fontFamily: 'monospace', padding: '3px 7px', borderRadius: 10, background: C.cyanSoft, color: C.cyan }}>GRAPH SNAPSHOT</span>
          </div>
          <div ref={wrapRef} style={{ height: 560, width: '100%' }} />
          <div style={{ display: 'flex', gap: 11, flexWrap: 'wrap', padding: '8px 12px', borderTop: `1px solid ${C.border}`, fontSize: 9.8, color: C.text3 }}>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.brandSoft, marginRight: 4 }} />组织</span>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.purpleSoft, marginRight: 4 }} />人员</span>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.warnSoft, marginRight: 4 }} />任务</span>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.cyanSoft, marginRight: 4 }} />智能体</span>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.successSoft, marginRight: 4 }} />RCC 已批准</span>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.warnSoft, marginRight: 4 }} />RCC 待审批</span>
            {selected && <Tag color="blue" closable onClose={() => setSelected('')}>已选：{selected.slice(0, 20)}</Tag>}
          </div>
        </div>
      ) : (
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, padding: 12, overflow: 'auto' }}>
          <table style={{ borderCollapse: 'separate', borderSpacing: 3, minWidth: 900 }}>
            <thead>
              <tr>
                <th style={{ position: 'sticky', left: 0, background: C.surface, padding: 6, fontSize: 9.5, textAlign: 'left', minWidth: 185, color: C.text3 }}>任务 \ 资源</th>
                {['归属人', '智能体', '状态', 'RCC 审批', '卡点'].map(h => (
                  <th key={h} style={{ padding: 6, fontSize: 9.5, textAlign: 'center', color: C.text3 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrixRows.map((t: any) => (
                <tr key={t.id}>
                  <td style={{ position: 'sticky', left: 0, background: C.surface, padding: 6, fontSize: 10.5, fontWeight: 750, color: C.text, minWidth: 185 }}>
                    <div style={{ maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.title}</div>
                    <div style={{ fontSize: 9, color: C.text3, fontWeight: 500, fontFamily: 'monospace' }}>{t.item_type}</div>
                  </td>
                  <td style={{ height: 38, minWidth: 90, border: `1px solid ${C.border}`, borderRadius: 7, background: C.purpleSoft, padding: 3, textAlign: 'center', fontSize: 10, color: C.purple, fontWeight: 750 }}>{t.created_by}</td>
                  <td style={{ height: 38, minWidth: 90, border: `1px solid ${C.border}`, borderRadius: 7, background: C.cyanSoft, padding: 3, textAlign: 'center', fontSize: 10, color: C.cyan, fontWeight: 750 }}>{t.agent_name || '通用'}</td>
                  <td style={{ height: 38, minWidth: 70, border: `1px solid ${C.border}`, borderRadius: 7, background: t.status === 'blocked' ? C.dangerSoft : t.status === 'done' ? C.successSoft : C.brandSoft, padding: 3, textAlign: 'center', fontSize: 10, color: t.status === 'blocked' ? C.danger : t.status === 'done' ? C.success : C.brand2, fontWeight: 850 }}>
                    {t.status === 'blocked' ? '⛔ 受阻' : t.status === 'done' ? '✓ 完成' : '跟进中'}
                  </td>
                  <td style={{ height: 38, minWidth: 90, border: `1px solid ${C.border}`, borderRadius: 7, background: t.rcc_status === 'approved' ? C.successSoft : t.rcc_status === 'pending' ? C.warnSoft : '#FAFBFC', padding: 3, textAlign: 'center', fontSize: 10, color: t.rcc_status === 'approved' ? C.success : t.rcc_status === 'pending' ? C.warn : '#C5CCD7', fontWeight: 750 }}>
                    {t.rcc_status === 'approved' ? '✅ 已批准' : t.rcc_status === 'pending' ? '⏳ 待审批' : t.rcc_status || '—'}
                  </td>
                  <td style={{ height: 38, minWidth: 110, border: `1px solid ${C.border}`, borderRadius: 7, background: t.blocked_by ? C.warnSoft : '#FAFBFC', padding: 3, textAlign: 'center', fontSize: 10, color: t.blocked_by ? C.warn : '#C5CCD7', fontWeight: 750 }}>
                    {t.blocked_by ? `⛔ ${t.blocked_by}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Space>
  )
}
