/**
 * RCC 神经连接矩阵 V2 — 高细节度拓扑
 * 节点：组织(RCC中心) / 智能体 / 人员(头像+技能+状态) / 设备(编码+OEE+状态) / 任务(标题+进度+卡点+RCC审批)
 * 边：关系标签（创建/指派/负责/审批/受影响）
 * 视图：图连接（分层拓扑）+ 关系矩阵（任务×资源 细节表）
 */
import { useEffect, useRef, useState } from 'react'
import { Graph } from '@antv/x6'
import { Tag, Space } from 'antd'
import { RobotOutlined } from '@ant-design/icons'

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
  factoryId?: string
}

// 节点组件（HTML 渲染，高细节）
const nodeHtml = (data: any) => {
  const { kind, title, sub, tags, color, soft, progress } = data
  const tagHtml = (tags || []).map((t: string) =>
    `<span style="display:inline-block;background:${C.cyanSoft};color:${C.cyan};border-radius:5px;padding:1px 5px;font-size:9px;font-weight:700;margin-right:3px;margin-top:2px">${t}</span>`).join('')
  const bar = progress !== undefined
    ? `<div style="height:4px;background:#EDF0F4;border-radius:3px;margin-top:5px;overflow:hidden"><div style="height:100%;background:${progress >= 90 ? C.danger : progress >= 60 ? C.warn : color};width:${Math.min(progress, 100)}%"></div></div>`
    : ''
  return `<div style="padding:8px 10px;font-size:11px;line-height:1.35;min-width:120px">
    <div style="font-weight:800;color:${C.text};font-size:11.5px">${title}</div>
    <div style="color:${C.text3};font-size:9.5px;margin-top:1px">${sub || ''}</div>
    <div style="margin-top:2px">${tagHtml}</div>${bar}</div>`
}

export default function RCCNeuralGraph({ tasks, inbox, baseline, factoryId }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [graph, setGraph] = useState<Graph | null>(null)
  const [selected, setSelected] = useState<string>('')
  const [viewMode, setViewMode] = useState<'graph' | 'matrix'>('graph')
  const [nodeInfo, setNodeInfo] = useState<any>(null)

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
      interacting: { nodeMovable: true },
    })
    g.on('node:click', ({ node }) => {
      setSelected(node.id)
      setNodeInfo(node.getData() || null)
      g.getEdges().forEach(e => e.setAttrs({ line: { stroke: '#DCE2EA', strokeWidth: 1.2 } }))
      g.getEdges().filter(e => e.getSourceCellId() === node.id || e.getTargetCellId() === node.id)
        .forEach(e => e.setAttrs({ line: { stroke: C.success, strokeWidth: 3 } }))
    })
    g.on('blank:click', () => { setSelected(''); setNodeInfo(null); g.getEdges().forEach(e => e.setAttrs({ line: { stroke: '#DCE2EA', strokeWidth: 1.2 } })) })
    setGraph(g)
    return () => { g.dispose() }
  }, [])

  useEffect(() => {
    if (!graph) return
    graph.clearCells()
    const allTasks = inbox.tasks || []
    const pendTasks = tasks.filter((t: any) => t.status === 'pending')
    const shown = [...allTasks.filter((t: any) => t.status === 'blocked').slice(0, 6),
                   ...allTasks.filter((t: any) => t.status === 'open').slice(0, 4),
                   ...pendTasks.slice(0, 3)]
    const nodes: any[] = []
    const edges: any[] = []

    const people = baseline.people || {}
    const equipment = baseline.equipment || {}
    const peopleList = Array.isArray(people) ? people : (people.items || [])
    const equipList = Array.isArray(equipment) ? equipment : (equipment.items || [])

    // 中央组织节点
    nodes.push({
      id: 'org', x: 400, y: 30, width: 210, height: 52,
      shape: 'html', data: {
        kind: 'org', title: '🏢 RCC 资源调度中心', sub: factoryId || 'FAC_MECH_001', color: C.brand,
        tags: [`${allTasks.length} 任务`, `${tasks.filter((t: any) => t.status === 'pending').length} 待审批`],
      },
    })

    // 智能体层
    const agents = Array.from(new Set(allTasks.map((t: any) => t.agent_name || '通用'))).slice(0, 5)
    agents.forEach((a, i) => {
      const agentTasks = allTasks.filter((t: any) => t.agent_name === a)
      nodes.push({
        id: `agent-${a}`, x: 30, y: 150 + i * 95, width: 160, height: 44,
        shape: 'html', data: {
          kind: 'agent', title: `🤖 ${a}`, sub: `${agentTasks.length} 任务 · ${agentTasks.filter((t: any) => t.status === 'blocked').length} 受阻`,
          color: C.cyan, tags: [agentTasks.some((t: any) => t.status === 'blocked') ? '⛔ 受阻' : '运行中'],
        },
      })
      edges.push({ id: `e-org-${a}`, source: 'org', target: `agent-${a}`, attrs: { line: { stroke: '#CBD4E1', strokeWidth: 1.2, strokeDasharray: '4 3' } }, data: { label: '隶属' } })
    })

    // 任务层（每个任务节点：标题+进度+卡点+归属+智能体+RCC状态）
    const rows = shown.slice(0, 10)
    const colX = [290, 500, 710, 920]
    const colY = [140, 300, 460]
    rows.forEach((t, i) => {
      const col = i % 4
      const row = Math.floor(i / 4)
      const x = colX[col]
      const y = colY[row]
      const stColor = t.status === 'blocked' ? C.danger : t.status === 'done' ? C.success : C.warn
      const tags = [
        t.status === 'blocked' ? `⛔ ${t.blocked_by || '受阻'}` : t.status === 'done' ? '✅ 完成' : '跟进中',
        t.rcc_status === 'pending' ? '⏳ RCC待审' : t.rcc_status === 'approved' ? '✅ RCC已批' : '',
      ].filter(Boolean)
      nodes.push({
        id: `task-${t.id}`, x, y, width: 190, height: 64,
        shape: 'html', data: {
          kind: 'task', title: `📋 ${(t.title || '').slice(0, 18)}${(t.title || '').length > 18 ? '…' : ''}`,
          sub: `${t.item_type || 'followup'} · ${t.progress_pct || 0}%`, color: stColor,
          tags, progress: t.progress_pct || 0,
        },
      })
      // 归属人节点（详细）
      const owner = t.created_by || '系统'
      const oid = `owner-${owner}`
      if (!nodes.find((n: any) => n.id === oid)) {
        const person = peopleList.find((p: any) => p.name === owner || p.username === owner || p.employee_code === owner)
        nodes.push({
          id: oid, x: 30, y: 660 + Object.keys(nodes).length % 4 * 50, width: 150, height: 48,
          shape: 'html', data: {
            kind: 'person', title: `👤 ${owner}`,
            sub: person ? `${person.position || '员工'} · ${person.department || ''}` : '任务创建者',
            color: C.purple, tags: [person?.skill_level ? `Lv${person.skill_level}` : '', person?.status === 'leave' ? '请假' : ''].filter(Boolean),
          },
        })
      }
      edges.push({ id: `e-${t.id}-owner`, source: oid, target: `task-${t.id}`, data: { label: '创建' }, attrs: { line: { stroke: C.purple, strokeWidth: 1.4 } } })
      // 指派
      if (t.assigned_to) {
        const aid = `owner-${t.assigned_to}`
        if (!nodes.find((n: any) => n.id === aid)) {
          nodes.push({
            id: aid, x: 30, y: 700 + Object.keys(nodes).length % 4 * 50, width: 150, height: 44,
            shape: 'html', data: { kind: 'person', title: `👤 ${t.assigned_to}`, sub: '任务指派对象', color: C.purple, tags: ['指派'] },
          })
        }
        edges.push({ id: `e-${t.id}-assigned`, source: `task-${t.id}`, target: aid, data: { label: '指派' }, attrs: { line: { stroke: C.purple, strokeWidth: 1.2, strokeDasharray: '3 2' } } })
      }
      // 智能体边
      const agent = t.agent_name || '通用'
      if (agents.includes(agent)) {
        edges.push({ id: `e-${t.id}-agent`, source: `agent-${agent}`, target: `task-${t.id}`, data: { label: '负责' }, attrs: { line: { stroke: C.cyan, strokeWidth: 1.4, strokeDasharray: '4 3' } } })
      }
      // RCC 审批节点
      if (t.rcc_status) {
        const rccColor = t.rcc_status === 'approved' ? C.success : t.rcc_status === 'pending' ? C.warn : C.brand
        nodes.push({
          id: `rcc-${t.id}`, x: x + 200, y: y + 10, width: 130, height: 40,
          shape: 'html', data: {
            kind: 'rcc', title: t.rcc_status === 'approved' ? '✅ RCC 已批准' : t.rcc_status === 'pending' ? '⏳ RCC 待审批' : 'RCC 执行中',
            sub: '资源调度', color: rccColor, tags: [],
          },
        })
        edges.push({ id: `e-${t.id}-rcc`, source: `task-${t.id}`, target: `rcc-${t.id}`, data: { label: '升级' }, attrs: { line: { stroke: rccColor, strokeWidth: t.rcc_status === 'approved' ? 3 : 1.6 } } })
      }
    })

    // 设备节点（每个设备：编码+名称+OEE+状态）
    equipList.slice(0, 4).forEach((e: any, i: number) => {
      const fault = e.status === 'fault' || e.status === 'broken' || e.status === 'maintenance'
      nodes.push({
        id: `eq-${e.equipment_code || e.id || i}`, x: 30, y: 500 + i * 70, width: 165, height: 48,
        shape: 'html', data: {
          kind: 'equipment', title: `🔧 ${e.equipment_name || e.name}`,
          sub: `${e.equipment_code || e.id} · ${e.status || 'running'}`,
          color: fault ? C.danger : C.cyan,
          tags: [`OEE ${Math.round((e.utilization || 0) * 100)}%`, fault ? '⚠ 故障' : '正常'].filter(Boolean),
        },
      })
      edges.push({
        id: `e-org-eq-${i}`, source: 'org', target: `eq-${e.equipment_code || e.id || i}`,
        data: { label: '产能' }, attrs: { line: { stroke: fault ? C.danger : C.cyan, strokeWidth: fault ? 2 : 1.2 } },
      })
    })

    graph.fromJSON({ nodes, edges })
    graph.centerContent()
  }, [graph, tasks, inbox, baseline])

  // 关系矩阵（细节表）
  const allTasks = inbox.tasks || []
  const matrixRows = allTasks.slice(0, 8)

  return (
    <Space direction="vertical" size={10} style={{ width: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <b style={{ fontSize: 13 }}>Resource Neural Topology · 神经连接矩阵</b>
        <span style={{ fontSize: 10.5, color: C.text3 }}>组织 / 智能体 / 人员 / 设备 / 任务 / RCC 审批 全要素连接</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 5 }}>
          <button onClick={() => setViewMode('graph')} style={{ border: viewMode === 'graph' ? `1px solid ${C.brand}` : `1px solid ${C.border}`, background: viewMode === 'graph' ? C.brandSoft : C.surface, color: viewMode === 'graph' ? C.brand2 : C.text3, padding: '6px 9px', borderRadius: 7, fontSize: 10.5, fontWeight: 750, cursor: 'pointer' }}>图连接</button>
          <button onClick={() => setViewMode('matrix')} style={{ border: viewMode === 'matrix' ? `1px solid ${C.brand}` : `1px solid ${C.border}`, background: viewMode === 'matrix' ? C.brandSoft : C.surface, color: viewMode === 'matrix' ? C.brand2 : C.text3, padding: '6px 9px', borderRadius: 7, fontSize: 10.5, fontWeight: 750, cursor: 'pointer' }}>关系矩阵</button>
        </div>
      </div>

      {viewMode === 'graph' ? (
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, overflow: 'hidden' }}>
          <div style={{ display: 'flex', alignItems: 'center', padding: '10px 13px', borderBottom: `1px solid ${C.border}` }}>
            <b style={{ fontSize: 12.5 }}>全要素连接拓扑</b>
            <span style={{ fontSize: 10.5, color: C.text3, marginLeft: 7 }}>点击节点查看详情 · 绿色粗线=选中连接</span>
            <span style={{ marginLeft: 'auto', fontSize: 10, fontFamily: 'monospace', padding: '3px 7px', borderRadius: 10, background: C.cyanSoft, color: C.cyan }}>GRAPH LIVE</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 260px' }}>
            <div ref={wrapRef} style={{ height: 640, width: '100%' }} />
            {/* 节点详情面板 */}
            <div style={{ borderLeft: `1px solid ${C.border}`, padding: 12, overflow: 'auto', height: 640 }}>
              {!nodeInfo ? (
                <div style={{ color: C.text3, fontSize: 11, lineHeight: 1.8, padding: 8 }}>
                  <b style={{ color: C.text2, display: 'block', marginBottom: 8 }}>节点详情</b>
                  点击任意节点查看：<br />
                  · 人员：技能等级 / 岗位 / 请假状态<br />
                  · 设备：编码 / OEE / 故障状态<br />
                  · 任务：进度 / 卡点归属 / RCC 审批<br />
                  · 边：创建 / 指派 / 负责 / 升级关系
                </div>
              ) : (
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 800, marginBottom: 4 }}>{nodeInfo.title}</div>
                  <div style={{ fontSize: 10.5, color: C.text3, marginBottom: 10 }}>{nodeInfo.sub}</div>
                  {(nodeInfo.tags || []).map((t: string, i: number) => (
                    <Tag key={i} color="blue" style={{ marginBottom: 4 }}>{t}</Tag>
                  ))}
                  <div style={{ marginTop: 12, padding: 9, borderRadius: 8, background: C.brandSoft, fontSize: 10.5, color: C.brand2, lineHeight: 1.6 }}>
                    <b>类型：</b>{nodeInfo.kind}<br />
                    <b>连接关系：</b>点击节点高亮关联边（绿色粗线）
                  </div>
                </div>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 11, flexWrap: 'wrap', padding: '8px 12px', borderTop: `1px solid ${C.border}`, fontSize: 9.8, color: C.text3 }}>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.brandSoft, marginRight: 4 }} />组织</span>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.cyanSoft, marginRight: 4 }} />智能体</span>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.purpleSoft, marginRight: 4 }} />人员</span>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: '#E4F4F4', marginRight: 4 }} />设备</span>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.warnSoft, marginRight: 4 }} />任务</span>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.successSoft, marginRight: 4 }} />RCC 已批</span>
            <span><i style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 3, background: C.warnSoft, marginRight: 4 }} />RCC 待审</span>
          </div>
        </div>
      ) : (
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 14, padding: 12, overflow: 'auto' }}>
          <table style={{ borderCollapse: 'separate', borderSpacing: 3, minWidth: 1050 }}>
            <thead>
              <tr>
                <th style={{ position: 'sticky', left: 0, background: C.surface, padding: 6, fontSize: 9.5, textAlign: 'left', minWidth: 200, color: C.text3 }}>任务 \ 资源</th>
                {['归属人', '指派给', '智能体', '状态', 'RCC 审批', '卡点'].map(h => <th key={h} style={{ padding: 6, fontSize: 9.5, textAlign: 'center', color: C.text3 }}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {matrixRows.map((t: any) => (
                <tr key={t.id}>
                  <td style={{ position: 'sticky', left: 0, background: C.surface, padding: 6, fontSize: 10.5, fontWeight: 750, color: C.text, minWidth: 200 }}>
                    <div style={{ maxWidth: 185, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.title}</div>
                    <div style={{ fontSize: 9, color: C.text3, fontWeight: 500, fontFamily: 'monospace' }}>{t.item_type} · {t.progress_pct || 0}%</div>
                  </td>
                  <td style={{ height: 38, minWidth: 90, border: `1px solid ${C.border}`, borderRadius: 7, background: C.purpleSoft, padding: 3, textAlign: 'center', fontSize: 10, color: C.purple, fontWeight: 750 }}>👤 {t.created_by}</td>
                  <td style={{ height: 38, minWidth: 90, border: `1px solid ${C.border}`, borderRadius: 7, background: C.purpleSoft, padding: 3, textAlign: 'center', fontSize: 10, color: C.purple, fontWeight: 750 }}>{t.assigned_to ? `→ ${t.assigned_to}` : '—'}</td>
                  <td style={{ height: 38, minWidth: 90, border: `1px solid ${C.border}`, borderRadius: 7, background: C.cyanSoft, padding: 3, textAlign: 'center', fontSize: 10, color: C.cyan, fontWeight: 750 }}>🤖 {t.agent_name || '通用'}</td>
                  <td style={{ height: 38, minWidth: 70, border: `1px solid ${C.border}`, borderRadius: 7, background: t.status === 'blocked' ? C.dangerSoft : t.status === 'done' ? C.successSoft : C.brandSoft, padding: 3, textAlign: 'center', fontSize: 10, color: t.status === 'blocked' ? C.danger : t.status === 'done' ? C.success : C.brand2, fontWeight: 850 }}>{t.status === 'blocked' ? '⛔ 受阻' : t.status === 'done' ? '✓ 完成' : '跟进中'}</td>
                  <td style={{ height: 38, minWidth: 90, border: `1px solid ${C.border}`, borderRadius: 7, background: t.rcc_status === 'approved' ? C.successSoft : t.rcc_status === 'pending' ? C.warnSoft : '#FAFBFC', padding: 3, textAlign: 'center', fontSize: 10, color: t.rcc_status === 'approved' ? C.success : t.rcc_status === 'pending' ? C.warn : '#C5CCD7', fontWeight: 750 }}>{t.rcc_status === 'approved' ? '✅ 已批准' : t.rcc_status === 'pending' ? '⏳ 待审批' : t.rcc_status || '—'}</td>
                  <td style={{ height: 38, minWidth: 110, border: `1px solid ${C.border}`, borderRadius: 7, background: t.blocked_by ? C.warnSoft : '#FAFBFC', padding: 3, textAlign: 'center', fontSize: 10, color: t.blocked_by ? C.warn : '#C5CCD7', fontWeight: 750 }}>{t.blocked_by ? `⛔ ${t.blocked_by}${t.block_category ? `(${t.block_category})` : ''}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Space>
  )
}
