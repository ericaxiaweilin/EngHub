import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Button, Input, Modal, Popconfirm, Select, Space, Tag, Tooltip, Typography, message,
} from 'antd'
import {
  ApartmentOutlined, CompressOutlined, DeleteOutlined, DragOutlined, EditOutlined, ExpandOutlined,
  PlusOutlined, ReloadOutlined, SaveOutlined, UndoOutlined, ZoomInOutlined, ZoomOutOutlined,
} from '@ant-design/icons'
import { Graph } from '@antv/x6'
import { register } from '@antv/x6-react-shape'

const { Text } = Typography
const { TextArea } = Input

type FlowNode = Record<string, any> & {
  id: string
  kind?: string
  title?: string
  label?: string
  layout?: { x: number; y: number; width: number; height: number; lane?: string; rank?: number }
}

interface Props {
  diagram: Record<string, any>
  selectedNodeId?: string
  onSelect: (nodeId: string) => void
  onDiagramChange: (diagram: Record<string, any>) => void
}

const clone = <T,>(value: T): T => {
  if (typeof structuredClone === 'function') return structuredClone(value)
  return JSON.parse(JSON.stringify(value))
}

const toArray = (value: any): any[] => value == null || value === '' ? [] : Array.isArray(value) ? value : [value]
const readable = (item: any) => {
  if (item == null) return ''
  if (typeof item !== 'object') return String(item)
  return [item.condition || item.when, item.action || item.title, item.owner ? `责任：${item.owner}` : '']
    .filter(Boolean).join(' → ') || JSON.stringify(item)
}
const compact = (value: any, limit = 2) => {
  const rows = toArray(value).map(readable).filter(Boolean)
  return rows.length ? `${rows.slice(0, limit).join('、')}${rows.length > limit ? ` 等${rows.length}项` : ''}` : '未配置'
}
const lines = (value: any) => toArray(value).map(readable).filter(Boolean).join('\n')
const fromLines = (value: string) => value.split('\n').map(v => v.trim()).filter(Boolean)

const NODE_STYLE: Record<string, { border: string; fill: string; tag: string; tagBg: string; accent: string }> = {
  start: { border: '#86d66b', fill: '#f5ffef', tag: '#287d16', tagBg: '#dcf7ce', accent: '#52c41a' },
  end: { border: '#86d66b', fill: '#f5ffef', tag: '#287d16', tagBg: '#dcf7ce', accent: '#52c41a' },
  approval: { border: '#c5a7ef', fill: '#ffffff', tag: '#5b21b6', tagBg: '#f1e8ff', accent: '#8b5cf6' },
  decision: { border: '#9cc4ff', fill: '#ffffff', tag: '#1559b7', tagBg: '#eaf3ff', accent: '#1677ff' },
  task: { border: '#82d8d2', fill: '#ffffff', tag: '#087b78', tagBg: '#e3f8f6', accent: '#13a8a8' },
  fallback: { border: '#f6aaa8', fill: '#ffffff', tag: '#b4232d', tagBg: '#fff0ef', accent: '#ef4444' },
  exception: { border: '#f6aaa8', fill: '#ffffff', tag: '#b4232d', tagBg: '#fff0ef', accent: '#ef4444' },
}

const KIND_LABEL: Record<string, string> = {
  start: '开始', end: '结束', approval: '审批', decision: '判断', task: '执行', fallback: 'Fallback', exception: '异常',
}

const EDGE_STYLE = {
  normal: { color: '#4f86e8', pale: '#edf4ff', width: 2.35, label: '正常流转' },
  fallback: { color: '#dc6670', pale: '#fff1f2', width: 2.05, label: '异常分支' },
  recovery: { color: '#e79a35', pale: '#fff7e8', width: 1.9, label: '恢复回流' },
} as const

const WorkflowCanvasNode: React.FC<{ node?: any }> = ({ node }) => {
  const data = node?.getData() || {}
  const kind = data.kind || 'task'
  const style = NODE_STYLE[kind] || NODE_STYLE.task
  const terminal = kind === 'start' || kind === 'end'
  return (
    <div style={{
      width: '100%', height: '100%', boxSizing: 'border-box', overflow: 'hidden', userSelect: 'none', position: 'relative',
      border: `1px solid ${data.selected ? '#1677ff' : style.border}`,
      borderRadius: terminal ? 30 : 14, background: style.fill,
      boxShadow: data.selected ? '0 0 0 3px rgba(22,119,255,.15), 0 12px 30px rgba(27,78,132,.18)' : '0 8px 22px rgba(29,58,91,.09)',
      padding: terminal ? '14px 20px' : '14px 15px 12px 17px', color: '#1f2d3d', cursor: data.editable ? 'move' : 'pointer',
    }}>
      {!terminal && <div style={{ position: 'absolute', inset: '0 auto 0 0', width: 4, background: style.accent }} />}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between' }}>
        <strong style={{ minWidth: 0, fontSize: terminal ? 14 : 13, lineHeight: '20px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: terminal ? style.tag : '#20344a' }}>
          {data.title || data.label || '未命名节点'}
        </strong>
        {!terminal && <span style={{ flexShrink: 0, borderRadius: 10, padding: '1px 7px', fontSize: 9, color: style.tag, background: style.tagBg }}>{KIND_LABEL[kind] || '步骤'}</span>}
      </div>
      {!terminal && <>
        <div style={{ marginTop: 7, color: '#72849a', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          责任 · {compact(data.related_parties || data.role, 3)}
        </div>
        <div style={{ marginTop: 6, height: 32, color: '#41566d', fontSize: 10, lineHeight: '16px', overflow: 'hidden' }}>
          {data.summary || data.action || '双击补充处理说明'}
        </div>
        <div style={{ marginTop: 6, display: 'flex', gap: 5, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 9, color: '#0958d9', background: '#e6f4ff', borderRadius: 8, padding: '1px 6px' }}>输入 {toArray(data.inputs).length}</span>
          <span style={{ fontSize: 9, color: '#237804', background: '#f6ffed', borderRadius: 8, padding: '1px 6px' }}>输出 {toArray(data.outputs || data.deliverables).length}</span>
          {['fallback', 'exception'].includes(kind) && <span style={{ fontSize: 9, color: '#d46b08', background: '#fff7e6', borderRadius: 8, padding: '1px 6px' }}>回流</span>}
        </div>
      </>}
    </div>
  )
}

let registered = false
const ensureShape = () => {
  if (registered) return
  register({ shape: 'workflow-canvas-node', width: 340, height: 146, component: WorkflowCanvasNode })
  registered = true
}

const keyOf = (diagram: Record<string, any>) => diagram.workflow_key || diagram.flow_id || diagram.flow_code || diagram.title || 'workflow'
const isNormalEdge = (edge: any) => edge.type === 'normal' || edge.path === 'normal'
const isFallbackNode = (node?: FlowNode) => node?.kind === 'fallback' || node?.kind === 'exception'

type ViewportState = { x: number; y: number; width: number; height: number }

const WorkflowCanvasEditor: React.FC<Props> = ({ diagram, selectedNodeId, onSelect, onDiagramChange }) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph | null>(null)
  const diagramRef = useRef(diagram)
  const onSelectRef = useRef(onSelect)
  const onChangeRef = useRef(onDiagramChange)
  const editModeRef = useRef(false)
  const baselineRef = useRef<Record<string, any>>(clone(diagram))
  const historyRef = useRef<Record<string, any>[]>([])
  const loadedKeyRef = useRef('')
  const [canvasTool, setCanvasTool] = useState<'pan' | 'edit'>('pan')
  const editMode = canvasTool === 'edit'
  const [fullscreen, setFullscreen] = useState(false)
  const [zoomPct, setZoomPct] = useState(100)
  const [viewport, setViewport] = useState<ViewportState>({ x: 0, y: 0, width: 1180, height: 760 })
  const [canUndo, setCanUndo] = useState(false)
  const [draftLoaded, setDraftLoaded] = useState(false)
  const [editing, setEditing] = useState<FlowNode | null>(null)
  const [editForm, setEditForm] = useState<Record<string, any>>({})

  diagramRef.current = diagram
  onSelectRef.current = onSelect
  onChangeRef.current = onDiagramChange
  editModeRef.current = editMode

  const syncViewport = useCallback(() => {
    const graph = graphRef.current
    const container = containerRef.current
    if (!graph || !container) return
    const matrix = graph.matrix()
    const scaleX = Math.max(Math.abs(matrix.a || 1), .001)
    const scaleY = Math.max(Math.abs(matrix.d || 1), .001)
    setViewport({
      x: -matrix.e / scaleX,
      y: -matrix.f / scaleY,
      width: container.clientWidth / scaleX,
      height: container.clientHeight / scaleY,
    })
  }, [])

  const storageKey = useMemo(() => `enghub-workflow-canvas:${keyOf(diagram)}`, [diagram.workflow_key, diagram.flow_id, diagram.flow_code, diagram.title])

  const pushHistory = useCallback(() => {
    historyRef.current = [...historyRef.current.slice(-29), clone(diagramRef.current)]
    setCanUndo(true)
  }, [])

  const commit = useCallback((next: Record<string, any>, remember = true) => {
    if (remember) pushHistory()
    diagramRef.current = next
    onChangeRef.current(next)
  }, [pushHistory])

  const openEditor = useCallback((nodeId: string) => {
    if (!editModeRef.current || nodeId.startsWith('__lane_')) return
    const node = diagramRef.current.nodes?.find((item: FlowNode) => item.id === nodeId)
    if (!node) return
    setEditing(node)
    setEditForm({
      title: node.title || node.label || '', kind: node.kind || 'task', role: lines(node.role),
      related_parties: lines(node.related_parties), summary: node.summary || node.action || '',
      inputs: lines(node.inputs), judgement_criteria: lines(node.judgement_criteria || node.condition),
      outputs: lines(node.outputs), deliverables: lines(node.deliverables), resume_condition: node.resume_condition || '',
    })
  }, [])

  useEffect(() => {
    if (!containerRef.current) return
    ensureShape()
    const graph = new Graph({
      container: containerRef.current,
      autoResize: true,
      background: { color: '#f8fbff' },
      grid: { visible: true, type: 'dot', args: { color: '#d5e2ef', thickness: 1 } },
      panning: { enabled: true, eventTypes: ['leftMouseDown'] },
      mousewheel: { enabled: true, modifiers: ['ctrl', 'meta'], minScale: 0.32, maxScale: 1.8, factor: 1.08 },
      interacting: (cellView) => {
        if (cellView.cell.id.startsWith('__lane_')) return false
        return { nodeMovable: editModeRef.current, edgeMovable: false, edgeLabelMovable: false, arrowheadMovable: false }
      },
      connecting: { allowBlank: false, allowLoop: false, allowNode: false, allowEdge: false },
    })
    graph.on('node:click', ({ node }) => {
      if (!node.id.startsWith('__lane_')) onSelectRef.current(node.id)
    })
    graph.on('node:dblclick', ({ node }) => openEditor(node.id))
    graph.on('blank:click', () => onSelectRef.current(''))
    graph.on('node:moved', ({ node }) => {
      if (!editModeRef.current || node.id.startsWith('__lane_')) return
      const current = diagramRef.current
      const target = current.nodes?.find((item: FlowNode) => item.id === node.id)
      if (!target) return
      const pos = node.getPosition()
      const size = node.getSize()
      const next = clone(current)
      const item = next.nodes.find((n: FlowNode) => n.id === node.id)
      item.layout = { ...(item.layout || {}), x: Math.round(pos.x), y: Math.round(pos.y), width: size.width, height: size.height }
      commit(next)
    })
    graph.on('edge:mouseenter', ({ edge }) => {
      const baseWidth = Number(edge.getData()?.baseWidth || 2)
      edge.attr('line/strokeWidth', baseWidth + .85)
      edge.attr('line/strokeOpacity', 1)
    })
    graph.on('edge:mouseleave', ({ edge }) => {
      const data = edge.getData() || {}
      edge.attr('line/strokeWidth', Number(data.baseWidth || 2))
      edge.attr('line/strokeOpacity', Number(data.baseOpacity || 1))
    })
    graph.on('scale', ({ sx }) => { setZoomPct(Math.round(sx * 100)); syncViewport() })
    graph.on('translate', syncViewport)
    graph.on('resize', syncViewport)
    graphRef.current = graph
    return () => { graph.dispose(); graphRef.current = null }
  }, [commit, openEditor, syncViewport])

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    if (fullscreen) document.body.style.overflow = 'hidden'
    const timer = window.setTimeout(() => {
      graphRef.current?.resize()
      if (fullscreen) fit()
      else syncViewport()
    }, 80)
    return () => {
      window.clearTimeout(timer)
      document.body.style.overflow = previousOverflow
    }
  // `fit` intentionally reads the current graph and does not need to recreate this effect.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fullscreen, syncViewport])

  useEffect(() => {
    const workflowKey = keyOf(diagram)
    if (loadedKeyRef.current === workflowKey) return
    loadedKeyRef.current = workflowKey
    baselineRef.current = clone(diagram)
    historyRef.current = []
    setCanUndo(false)
    setDraftLoaded(false)
    try {
      const saved = JSON.parse(localStorage.getItem(`enghub-workflow-canvas:${workflowKey}`) || 'null')
      if (saved?.diagram?.nodes?.length) {
        setDraftLoaded(true)
        diagramRef.current = saved.diagram
        onChangeRef.current(saved.diagram)
      }
    } catch { /* ignore invalid local draft */ }
  }, [diagram.workflow_key, diagram.flow_id, diagram.flow_code, diagram.title])

  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return
    const canvasWidth = diagram.canvas?.width || 1180
    const canvasHeight = diagram.canvas?.height || 760
    const lanes = (diagram.canvas?.lanes?.length ? diagram.canvas.lanes : [
      { key: 'fallback-left', label: '不通过 / Fallback', x: 12, width: 366 },
      { key: 'normal', label: '正常主流程', x: 397, width: 386 },
      { key: 'fallback-right', label: '不通过 / Fallback', x: 802, width: 366 },
    ]).map((lane: any) => ({
      id: `__lane_${lane.key}`, shape: 'rect', x: lane.x, y: 78, width: lane.width, height: Math.max(260, canvasHeight - 94), zIndex: 0,
      label: lane.label,
      attrs: {
        body: { fill: lane.key === 'normal' ? '#f4f8fd' : '#fff9f8', fillOpacity: .78, stroke: lane.key === 'normal' ? '#c7ddf4' : '#f3d5d2', strokeWidth: 1, strokeDasharray: lane.key === 'normal' ? '' : '6 5', rx: 18, ry: 18, pointerEvents: 'none' },
        label: { fill: lane.key === 'normal' ? '#3973ad' : '#bc5054', fontSize: 11, fontWeight: 650, refY: 18, textVerticalAnchor: 'top', pointerEvents: 'none' },
      },
    }))
    const nodes = (diagram.nodes || []).map((node: FlowNode, index: number) => {
      const terminal = node.kind === 'start' || node.kind === 'end'
      const fallback = isFallbackNode(node)
      const layout = node.layout || {
        x: fallback ? (index % 2 ? 820 : 30) : terminal ? 485 : 420,
        y: 30 + index * 190, width: terminal ? 210 : fallback ? 330 : 350, height: terminal ? 58 : fallback ? 132 : 146,
      }
      return {
        id: node.id, shape: 'workflow-canvas-node', x: layout.x, y: layout.y,
        width: layout.width || (terminal ? 210 : fallback ? 320 : 360), height: layout.height || (terminal ? 56 : fallback ? 116 : 154), zIndex: 3,
        data: { ...node, selected: selectedNodeId === node.id, editable: editMode },
      }
    })
    const nodeLookup = new Map((diagram.nodes || []).map((node: FlowNode) => [node.id, node]))
    const edges = (diagram.edges || []).map((edge: any, index: number) => {
      const sourceNode = nodeLookup.get(edge.source) as FlowNode | undefined
      const targetNode = nodeLookup.get(edge.target) as FlowNode | undefined
      const normal = isNormalEdge(edge)
      const recovery = edge.type === 'recovery'
      const semantic = recovery ? EDGE_STYLE.recovery : normal ? EDGE_STYLE.normal : EDGE_STYLE.fallback
      const connected = !selectedNodeId || edge.source === selectedNodeId || edge.target === selectedNodeId
      let sourceAnchor = 'bottom'
      let targetAnchor = 'top'
      if (!normal) {
        const sourceX = (sourceNode?.layout?.x || 0) + (sourceNode?.layout?.width || 340) / 2
        const targetX = (targetNode?.layout?.x || 0) + (targetNode?.layout?.width || 340) / 2
        sourceAnchor = targetX < sourceX ? 'left' : 'right'
        targetAnchor = targetX < sourceX ? 'right' : 'left'
      }
      const color = semantic.color
      const baseWidth = semantic.width + (connected && selectedNodeId ? .35 : 0)
      const baseOpacity = connected ? 1 : .58
      const sourceCenterX = (sourceNode?.layout?.x || 0) + (sourceNode?.layout?.width || 340) / 2
      const targetCenterX = (targetNode?.layout?.x || 0) + (targetNode?.layout?.width || 340) / 2
      const sourceCenterY = (sourceNode?.layout?.y || 0) + (sourceNode?.layout?.height || 140) / 2
      const targetCenterY = (targetNode?.layout?.y || 0) + (targetNode?.layout?.height || 140) / 2
      // Detailed gate criteria live in the selected-node panel.  Keeping edge
      // labels semantic and short prevents labels from colliding with cards.
      const label = recovery ? '恢复重判' : normal ? '通过' : '不通过'
      return {
        id: edge.id || `edge-${index}`, zIndex: connected ? 2 : 1,
        data: { baseWidth, baseOpacity, semantic: recovery ? 'recovery' : normal ? 'normal' : 'fallback' },
        source: { cell: edge.source, anchor: { name: sourceAnchor, args: normal ? {} : { dy: recovery ? 17 : -17 } } },
        target: { cell: edge.target, anchor: { name: targetAnchor, args: normal ? {} : { dy: recovery ? 17 : -17 } } },
        router: normal ? { name: 'orth', args: { padding: 20 } } : undefined,
        vertices: normal ? undefined : [{
          x: (sourceCenterX + targetCenterX) / 2,
          y: (sourceCenterY + targetCenterY) / 2 + (recovery ? 22 : -22),
        }],
        connector: normal ? { name: 'rounded', args: { radius: 18 } } : { name: 'smooth' },
        attrs: { line: {
          stroke: color, strokeWidth: baseWidth, strokeOpacity: baseOpacity,
          strokeDasharray: recovery ? '7 6' : undefined, strokeLinecap: 'round', strokeLinejoin: 'round',
          sourceMarker: normal ? undefined : { name: 'circle', r: 2.6, fill: color, stroke: color },
          targetMarker: { name: 'classic', width: 8, height: 7, fill: color, stroke: color },
        } },
        labels: [{ attrs: {
          label: { text: label, fill: color, fontSize: 9, fontWeight: 650 },
          body: { fill: semantic.pale, fillOpacity: .98, stroke: color, strokeOpacity: .24, strokeWidth: .6, rx: 9, ry: 9, refWidth: '145%', refHeight: '165%', refX: '-22.5%', refY: '-32.5%' },
        }, position: normal ? .5 : recovery ? .68 : .34 }],
      }
    })
    graph.fromJSON({ nodes: [...lanes, ...nodes], edges })
    // 新图首次进入时给出可阅读的工作视角；“适配”按钮负责查看完整鸟瞰图。
    if (!(graph as any).__workflowFitted) {
      ;(graph as any).__workflowFitted = true
      requestAnimationFrame(() => {
        graph.zoomTo(.55)
        const focusCell = graph.getCellById(selectedNodeId || '')
        if (focusCell) graph.centerCell(focusCell)
        else graph.centerContent()
        setZoomPct(Math.round(Number(graph.zoom()) * 100))
        syncViewport()
      })
    }
  }, [diagram, selectedNodeId, editMode, syncViewport])

  const zoom = (delta: number) => {
    const graph = graphRef.current
    if (!graph) return
    graph.zoom(delta)
    setZoomPct(Math.round(Number(graph.zoom()) * 100))
    requestAnimationFrame(syncViewport)
  }

  const fit = () => {
    const graph = graphRef.current
    if (!graph) return
    graph.zoomToFit({ padding: 36, maxScale: 1 })
    graph.centerContent()
    setZoomPct(Math.round(Number(graph.zoom()) * 100))
    requestAnimationFrame(syncViewport)
  }

  const centerFromOverview = (event: React.MouseEvent<HTMLDivElement>) => {
    const graph = graphRef.current
    if (!graph) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const canvasWidth = diagram.canvas?.width || 1180
    const canvasHeight = diagram.canvas?.height || 760
    const x = ((event.clientX - bounds.left) / bounds.width) * canvasWidth
    const y = ((event.clientY - bounds.top) / bounds.height) * canvasHeight
    graph.centerPoint(x, y)
    requestAnimationFrame(syncViewport)
  }

  const undo = () => {
    const previous = historyRef.current.pop()
    if (!previous) return
    diagramRef.current = previous
    onChangeRef.current(previous)
    setCanUndo(historyRef.current.length > 0)
  }

  const saveDraft = () => {
    try {
      localStorage.setItem(storageKey, JSON.stringify({ savedAt: new Date().toISOString(), diagram: diagramRef.current }))
      setDraftLoaded(true)
      message.success('流程画布草稿已保存到本机')
    } catch {
      message.error('草稿保存失败：浏览器存储空间不足')
    }
  }

  const reset = () => {
    localStorage.removeItem(storageKey)
    historyRef.current = []
    setCanUndo(false)
    setDraftLoaded(false)
    const original = clone(baselineRef.current)
    diagramRef.current = original
    onChangeRef.current(original)
    requestAnimationFrame(fit)
    message.success('已恢复流程引擎生成的原始版本')
  }

  const saveNode = () => {
    if (!editing) return
    const next = clone(diagramRef.current)
    const node = next.nodes.find((item: FlowNode) => item.id === editing.id)
    if (!node) return
    Object.assign(node, {
      title: editForm.title.trim(), label: editForm.title.trim(), kind: editForm.kind,
      role: editForm.role.trim(), related_parties: fromLines(editForm.related_parties),
      summary: editForm.summary.trim(), action: editForm.summary.trim(), inputs: fromLines(editForm.inputs),
      judgement_criteria: fromLines(editForm.judgement_criteria), outputs: fromLines(editForm.outputs),
      deliverables: fromLines(editForm.deliverables), resume_condition: editForm.resume_condition.trim(),
    })
    commit(next)
    setEditing(null)
    message.success('节点内容已更新，记得保存草稿')
  }

  const addStep = () => {
    const current = clone(diagramRef.current)
    const selected = current.nodes.find((node: FlowNode) => node.id === selectedNodeId && !isFallbackNode(node) && node.kind !== 'end')
      || [...current.nodes].reverse().find((node: FlowNode) => !isFallbackNode(node) && node.kind !== 'end')
    if (!selected) return
    const id = `draft_step_${Date.now()}`
    const outgoingIndex = current.edges.findIndex((edge: any) => edge.source === selected.id && isNormalEdge(edge))
    const outgoing = outgoingIndex >= 0 ? current.edges[outgoingIndex] : null
    const y = (selected.layout?.y || 100) + (selected.layout?.height || 146) + 90
    const node: FlowNode = {
      id, kind: 'task', title: '新增流程步骤', summary: '双击编辑处理动作、输入输出与责任方', role: '', inputs: [], outputs: [],
      layout: { x: selected.layout?.x || 420, y, width: 350, height: 146, lane: 'normal' },
    }
    current.nodes.push(node)
    if (outgoing) {
      current.edges.splice(outgoingIndex, 1, { ...outgoing, id: `${outgoing.id || 'edge'}-before-${id}`, target: id })
      current.edges.push({ id: `${id}-next`, source: id, target: outgoing.target, type: 'normal', path: 'normal', label: '通过' })
    } else {
      current.edges.push({ id: `${selected.id}-${id}`, source: selected.id, target: id, type: 'normal', path: 'normal', label: '通过' })
    }
    commit(current)
    onSelectRef.current(id)
    setTimeout(() => openEditor(id), 0)
  }

  const addFallback = () => {
    const current = clone(diagramRef.current)
    const selected = current.nodes.find((node: FlowNode) => node.id === selectedNodeId && !isFallbackNode(node) && !['start', 'end'].includes(node.kind || ''))
    if (!selected) { message.warning('请先选择一个主流程节点'); return }
    const siblings = current.nodes.filter((node: FlowNode) => node.fallback_of === selected.id)
    const left = siblings.length % 2 === 0
    const id = `draft_fallback_${Date.now()}`
    const node: FlowNode = {
      id, kind: 'fallback', title: '新增 Fallback', fallback_of: selected.id,
      summary: '双击编辑不通过后的处理动作', judgement_criteria: ['不通过条件待配置'], related_parties: [], resume_condition: '条件恢复后返回原节点重判',
      layout: { x: left ? 30 : 820, y: (selected.layout?.y || 120) + siblings.length * 32, width: 330, height: 132, lane: left ? 'fallback-left' : 'fallback-right' },
    }
    current.nodes.push(node)
    current.edges.push(
      { id: `${selected.id}-${id}`, source: selected.id, target: id, type: 'fallback', path: 'fallback', label: '不通过' },
      { id: `${id}-${selected.id}`, source: id, target: selected.id, type: 'recovery', path: 'fallback', label: '恢复后重判' },
    )
    commit(current)
    onSelectRef.current(id)
    setTimeout(() => openEditor(id), 0)
  }

  const deleteSelected = () => {
    const current = clone(diagramRef.current)
    const selected = current.nodes.find((node: FlowNode) => node.id === selectedNodeId)
    if (!selected || ['start', 'end'].includes(selected.kind || '')) return
    const removeIds = new Set<string>([selected.id])
    if (!isFallbackNode(selected)) current.nodes.filter((node: FlowNode) => node.fallback_of === selected.id).forEach((node: FlowNode) => removeIds.add(node.id))
    const incoming = current.edges.find((edge: any) => edge.target === selected.id && isNormalEdge(edge) && !removeIds.has(edge.source))
    const outgoing = current.edges.find((edge: any) => edge.source === selected.id && isNormalEdge(edge) && !removeIds.has(edge.target))
    current.nodes = current.nodes.filter((node: FlowNode) => !removeIds.has(node.id))
    current.edges = current.edges.filter((edge: any) => !removeIds.has(edge.source) && !removeIds.has(edge.target))
    if (incoming && outgoing) current.edges.push({ ...incoming, id: `${incoming.source}-${outgoing.target}-splice`, target: outgoing.target })
    commit(current)
    onSelectRef.current('')
  }

  const selected = diagram.nodes?.find((node: FlowNode) => node.id === selectedNodeId)
  const selectedCanDelete = selected && !['start', 'end'].includes(selected.kind || '')
  const overviewWidth = diagram.canvas?.width || 1180
  const overviewHeight = diagram.canvas?.height || 760
  const overviewNodes = (diagram.nodes || []).filter((node: FlowNode) => node.layout)
  const viewportRect = {
    left: `${Math.max(0, Math.min(100, viewport.x / overviewWidth * 100))}%`,
    top: `${Math.max(0, Math.min(100, viewport.y / overviewHeight * 100))}%`,
    width: `${Math.max(7, Math.min(100, viewport.width / overviewWidth * 100))}%`,
    height: `${Math.max(7, Math.min(100, viewport.height / overviewHeight * 100))}%`,
  }

  return (
    <div style={{
      border: '1px solid #d5e2ef', borderRadius: fullscreen ? 16 : 12, overflow: 'hidden', background: '#f8fbff',
      boxShadow: fullscreen ? '0 24px 80px rgba(15,35,60,.28)' : '0 8px 26px rgba(40,75,110,.08)',
      ...(fullscreen ? { position: 'fixed' as const, inset: 12, zIndex: 2000, width: 'auto', height: 'auto' } : {}),
    }}>
      <div style={{ minHeight: 50, padding: '8px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', background: 'rgba(255,255,255,.98)', borderBottom: '1px solid #e1ebf4' }}>
        <Space size={6} wrap>
          <span style={{ display: 'grid', placeItems: 'center', width: 27, height: 27, borderRadius: 8, color: '#fff', background: 'linear-gradient(135deg,#1677ff,#56a4ff)' }}><ApartmentOutlined /></span>
          <Text strong style={{ fontSize: 12, color: '#20344a' }}>流程设计画布</Text>
          <Tag color={editMode ? 'blue' : 'cyan'} style={{ margin: 0, fontSize: 9 }}>{editMode ? '节点编辑' : '抓手模式'}</Tag>
          {draftLoaded && <Tag color="gold" style={{ margin: 0, fontSize: 9 }}>本机草稿</Tag>}
          <Text type="secondary" style={{ fontSize: 9 }}>{editMode ? '拖动节点 · 双击编辑' : '按住任意空白区域拖动整张图'} · Ctrl/⌘ + 滚轮缩放</Text>
        </Space>
        <Space size={4} wrap>
          <Button size="small" type={!editMode ? 'primary' : 'default'} icon={<DragOutlined />} onClick={() => setCanvasTool('pan')}>抓手</Button>
          <Button size="small" type={editMode ? 'primary' : 'default'} icon={<EditOutlined />} onClick={() => setCanvasTool('edit')}>编辑</Button>
          <Button size="small" icon={<ZoomOutOutlined />} onClick={() => zoom(-0.12)} />
          <span style={{ width: 36, textAlign: 'center', color: '#60758b', fontSize: 10 }}>{zoomPct}%</span>
          <Button size="small" icon={<ZoomInOutlined />} onClick={() => zoom(0.12)} />
          <Button size="small" icon={<ApartmentOutlined />} onClick={fit}>整图</Button>
          <Tooltip title={fullscreen ? '退出全屏画布' : '全屏打开画布'}>
            <Button size="small" icon={fullscreen ? <CompressOutlined /> : <ExpandOutlined />} onClick={() => setFullscreen(value => !value)}>{fullscreen ? '退出全屏' : '全屏'}</Button>
          </Tooltip>
          <Button size="small" icon={<UndoOutlined />} disabled={!canUndo} onClick={undo}>撤销</Button>
          <Button size="small" icon={<PlusOutlined />} disabled={!editMode} onClick={addStep}>步骤</Button>
          <Button size="small" icon={<PlusOutlined />} disabled={!editMode} onClick={addFallback}>Fallback</Button>
          {selectedCanDelete && <Popconfirm title="删除该节点及其关联分支？" okText="删除" cancelText="取消" okButtonProps={{ danger: true }} onConfirm={deleteSelected}>
            <Button size="small" danger icon={<DeleteOutlined />} disabled={!editMode} />
          </Popconfirm>}
          {selected && <Button size="small" icon={<EditOutlined />} disabled={!editMode} onClick={() => openEditor(selected.id)}>编辑</Button>}
          <Popconfirm title="恢复流程引擎原始版本？" description="本机草稿和当前改动会被清除" okText="恢复" cancelText="取消" onConfirm={reset}>
            <Button size="small" icon={<ReloadOutlined />}>重置</Button>
          </Popconfirm>
          <Tooltip title="保存在当前浏览器，不会覆盖流程引擎正式版本"><Button size="small" type="primary" icon={<SaveOutlined />} onClick={saveDraft}>保存草稿</Button></Tooltip>
        </Space>
      </div>
      <div style={{ height: fullscreen ? 'calc(100vh - 80px)' : 620, width: '100%', position: 'relative', overflow: 'hidden' }}>
        <div ref={containerRef} style={{ position: 'absolute', inset: 0, cursor: editMode ? 'default' : 'grab' }} />
        <div style={{
          position: 'absolute', left: 14, bottom: 14, zIndex: 10, display: 'flex', gap: 12, alignItems: 'center',
          padding: '7px 10px', border: '1px solid rgba(91,125,160,.20)', borderRadius: 10,
          background: 'rgba(255,255,255,.92)', boxShadow: '0 6px 20px rgba(30,60,90,.10)', backdropFilter: 'blur(8px)', pointerEvents: 'none',
        }}>
          {Object.entries(EDGE_STYLE).map(([key, item]) => <span key={key} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', color: '#61758b', fontSize: 9, whiteSpace: 'nowrap' }}>
            <i style={{ position: 'relative', display: 'inline-block', width: 24, height: 8 }}>
              <i style={{ position: 'absolute', left: 0, right: 2, top: 3, borderTop: `${key === 'recovery' ? '1.5px dashed' : '2px solid'} ${item.color}` }} />
              <i style={{ position: 'absolute', right: 0, top: 1, width: 0, height: 0, borderTop: '3px solid transparent', borderBottom: '3px solid transparent', borderLeft: `5px solid ${item.color}` }} />
            </i>
            {item.label}
          </span>)}
        </div>
        <div
          role="button"
          aria-label="流程导航缩略图，点击可定位"
          onClick={centerFromOverview}
          style={{
            position: 'absolute', right: 14, bottom: 14, width: fullscreen ? 210 : 170, height: fullscreen ? 138 : 110,
            border: '1px solid rgba(91,125,160,.28)', borderRadius: 12, overflow: 'hidden', cursor: 'crosshair',
            background: 'rgba(255,255,255,.94)', boxShadow: '0 8px 26px rgba(30,60,90,.16)', backdropFilter: 'blur(8px)', zIndex: 10,
          }}
        >
          <div style={{ position: 'absolute', left: 8, top: 6, zIndex: 3, color: '#6b7f94', fontSize: 8, fontWeight: 700 }}>导航 · 点击定位</div>
          {overviewNodes.map((node: FlowNode) => {
            const layout = node.layout!
            const style = NODE_STYLE[node.kind || 'task'] || NODE_STYLE.task
            return <span key={node.id} style={{
              position: 'absolute', left: `${layout.x / overviewWidth * 100}%`, top: `${layout.y / overviewHeight * 100}%`,
              width: `${Math.max(2.5, (layout.width || 320) / overviewWidth * 100)}%`, height: `${Math.max(2, (layout.height || 100) / overviewHeight * 100)}%`,
              boxSizing: 'border-box', border: `1px solid ${style.accent}`, borderRadius: 2, background: style.tagBg, opacity: .88,
            }} />
          })}
          <span style={{
            position: 'absolute', ...viewportRect, boxSizing: 'border-box', border: '2px solid #1677ff', borderRadius: 4,
            background: 'rgba(22,119,255,.08)', pointerEvents: 'none', zIndex: 4,
          }} />
        </div>
      </div>

      <Modal title={`编辑节点 · ${editing?.title || editing?.label || ''}`} open={!!editing} onCancel={() => setEditing(null)} onOk={saveNode} okText="应用到画布" cancelText="取消" width={720} destroyOnClose>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px', gap: 12 }}>
          <label><div style={{ marginBottom: 5, color: '#526579', fontSize: 11 }}>节点名称</div><Input value={editForm.title || ''} onChange={e => setEditForm(v => ({ ...v, title: e.target.value }))} /></label>
          <label><div style={{ marginBottom: 5, color: '#526579', fontSize: 11 }}>节点类型</div><Select style={{ width: '100%' }} value={editForm.kind} disabled={['start', 'end'].includes(editing?.kind || '')} options={['task', 'decision', 'approval', 'fallback'].map(value => ({ value, label: KIND_LABEL[value] }))} onChange={value => setEditForm(v => ({ ...v, kind: value }))} /></label>
        </div>
        <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <label><div style={{ marginBottom: 5, color: '#526579', fontSize: 11 }}>责任角色</div><Input value={editForm.role || ''} onChange={e => setEditForm(v => ({ ...v, role: e.target.value }))} /></label>
          <label><div style={{ marginBottom: 5, color: '#526579', fontSize: 11 }}>关联方（每行一项）</div><TextArea rows={2} value={editForm.related_parties || ''} onChange={e => setEditForm(v => ({ ...v, related_parties: e.target.value }))} /></label>
        </div>
        <label style={{ display: 'block', marginTop: 12 }}><div style={{ marginBottom: 5, color: '#526579', fontSize: 11 }}>处理动作 / 说明</div><TextArea rows={3} value={editForm.summary || ''} onChange={e => setEditForm(v => ({ ...v, summary: e.target.value }))} /></label>
        <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <label><div style={{ marginBottom: 5, color: '#0958d9', fontSize: 11 }}>输入物（每行一项）</div><TextArea rows={4} value={editForm.inputs || ''} onChange={e => setEditForm(v => ({ ...v, inputs: e.target.value }))} /></label>
          <label><div style={{ marginBottom: 5, color: '#237804', fontSize: 11 }}>输出物（每行一项）</div><TextArea rows={4} value={editForm.outputs || ''} onChange={e => setEditForm(v => ({ ...v, outputs: e.target.value }))} /></label>
          <label><div style={{ marginBottom: 5, color: '#d46b08', fontSize: 11 }}>判断 / 放行条件（每行一项）</div><TextArea rows={4} value={editForm.judgement_criteria || ''} onChange={e => setEditForm(v => ({ ...v, judgement_criteria: e.target.value }))} /></label>
          <label><div style={{ marginBottom: 5, color: '#531dab', fontSize: 11 }}>交付物 / 留痕（每行一项）</div><TextArea rows={4} value={editForm.deliverables || ''} onChange={e => setEditForm(v => ({ ...v, deliverables: e.target.value }))} /></label>
        </div>
        {editing && isFallbackNode(editing) && <label style={{ display: 'block', marginTop: 12 }}><div style={{ marginBottom: 5, color: '#d46b08', fontSize: 11 }}>回流条件</div><Input value={editForm.resume_condition || ''} onChange={e => setEditForm(v => ({ ...v, resume_condition: e.target.value }))} /></label>}
      </Modal>
    </div>
  )
}

export default WorkflowCanvasEditor
