/**
 * 逻辑链可视化编排器（AntV X6）
 * 触发器 → 条件(AND 串联) → 动作(顺序执行) 的线性链路画布
 * - 节点用 React 组件渲染（x6-react-shape），暗色主题与 RCC 指挥中心一致
 * - 点击节点 → 右侧属性面板编辑；动作支持上移/下移调整执行顺序
 * - 保存时序列化回 conditions[] / action_sequence[]，对接 /api/v1/rcc/logic-chains
 * - 本组件按需懒加载（React.lazy），X6 不进主包
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AutoComplete, Button, Drawer, Empty, Form, Input, InputNumber, Popconfirm,
  Select, Space, Switch, Tag, Typography, message,
} from 'antd'
import {
  ArrowDownOutlined, ArrowUpOutlined, DeleteOutlined, FilterOutlined,
  PlusOutlined, SaveOutlined, ThunderboltOutlined, ZoomInOutlined, ZoomOutOutlined,
} from '@ant-design/icons'
import { Graph } from '@antv/x6'
import { register } from '@antv/x6-react-shape'
import axios from 'axios'
import { COLORS } from './RCCCommandCenter'

const { Text } = Typography
const API_BASE = '/api/v1/rcc'

/* ---------- 数据模型 ---------- */
interface CondCfg { field: string; op: string; value: string }
interface ActionCfg { type: string; [k: string]: any }

const OP_OPTIONS = [
  { value: 'eq', label: '等于 (eq)' },
  { value: 'neq', label: '不等于 (neq)' },
  { value: 'gt', label: '大于 (gt)' },
  { value: 'gte', label: '大于等于 (gte)' },
  { value: 'lt', label: '小于 (lt)' },
  { value: 'lte', label: '小于等于 (lte)' },
  { value: 'in', label: '在列表中 (in)' },
  { value: 'contains', label: '包含 (contains)' },
  { value: 'startswith', label: '前缀匹配' },
  { value: 'endswith', label: '后缀匹配' },
  { value: 'regex', label: '正则匹配' },
]

const ACTION_TYPES = [
  { value: 'update_param', label: '更新参数' },
  { value: 'create_chatbot_ticket', label: '创建工单' },
  { value: 'notify_org_unit', label: '通知组织单元' },
  { value: 'log_audit', label: '记录审计' },
  { value: 'escalate_rcc', label: '升级 RCC 审批' },
]
const actionLabel = (t: string) => ACTION_TYPES.find(a => a.value === t)?.label || t

const EVENT_SUGGESTIONS = [
  'param_threshold_breach', 'work_order_delayed', 'work_order_completed',
  'quality_alert', 'inventory_low', 'equipment_fault', 'andon_triggered',
].map(v => ({ value: v }))

/** 动作参数摘要（节点卡片上展示） */
const actionSummary = (a: ActionCfg): string => {
  switch (a.type) {
    case 'update_param': return `${a.param_code || '?'} → ${a.value ?? '?'}`
    case 'create_chatbot_ticket': return a.message || '(无消息)'
    case 'notify_org_unit': return a.target_org_unit || '(未指定)'
    case 'log_audit': return a.note || '审计日志'
    case 'escalate_rcc': return a.reason || '升级审批'
    default: return ''
  }
}

/* ---------- X6 React 节点 ---------- */
const KIND_STYLE: Record<string, { border: string; icon: React.ReactNode; label: string }> = {
  trigger: { border: COLORS.accent, icon: <ThunderboltOutlined />, label: '触发器' },
  cond: { border: COLORS.accentBlue, icon: <FilterOutlined />, label: '条件' },
  action: { border: COLORS.accentPurple, icon: <PlusOutlined />, label: '动作' },
}

const LcNode: React.FC<{ node?: any }> = ({ node }) => {
  const d = node?.getData() || {}
  const st = KIND_STYLE[d.kind] || KIND_STYLE.cond
  return (
    <div style={{
      width: '100%', height: '100%', borderRadius: 8, boxSizing: 'border-box',
      background: COLORS.bgCard, border: `1.5px solid ${d.selected ? st.border : COLORS.border}`,
      borderLeft: `4px solid ${st.border}`, padding: '8px 10px', cursor: 'pointer',
      boxShadow: d.selected ? `0 0 8px ${st.border}66` : 'none', overflow: 'hidden',
    }}>
      <div style={{ color: st.border, fontSize: 10, display: 'flex', alignItems: 'center', gap: 4 }}>
        {st.icon}<span>{st.label}{typeof d.seq === 'number' ? ` ${d.seq + 1}` : ''}</span>
      </div>
      <div style={{
        color: COLORS.text, fontSize: 12, fontWeight: 600, marginTop: 3,
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>{d.title || '(未配置)'}</div>
      <div style={{
        color: COLORS.textMuted, fontSize: 10, marginTop: 2,
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
      }}>{d.subtitle || ''}</div>
    </div>
  )
}

let shapeRegistered = false
const ensureShape = () => {
  if (shapeRegistered) return
  register({ shape: 'lc-node', width: 190, height: 64, component: LcNode })
  shapeRegistered = true
}

/* ---------- 布局常量 ---------- */
const NODE_W = 190
const NODE_H = 64
const GAP_X = 70
const START_X = 40
const START_Y = 60

interface Props {
  chain: any | null          // null = 新建
  onClose: () => void
  onSaved: () => void
}

const LogicChainEditor: React.FC<Props> = ({ chain, onClose, onSaved }) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph | null>(null)
  const [meta, setMeta] = useState({
    chain_code: chain?.chain_code || '',
    chain_name: chain?.chain_name || '',
    trigger_event: chain?.trigger_event || '',
    enabled: chain?.enabled ?? true,
    execution_order: chain?.execution_order ?? 0,
  })
  const [conds, setConds] = useState<CondCfg[]>(
    (chain?.conditions || []).map((c: any) => ({ field: c.field || '', op: c.op || 'eq', value: String(c.value ?? '') })),
  )
  const [actions, setActions] = useState<ActionCfg[]>(
    (chain?.action_sequence || []).map((a: any) => ({ ...a, type: a.type || 'log_audit' })),
  )
  const [selected, setSelected] = useState<string>('trigger')  // 'trigger' | 'cond-i' | 'action-i'
  const [saving, setSaving] = useState(false)

  /* ---------- 初始化画布 ---------- */
  useEffect(() => {
    if (!containerRef.current) return
    ensureShape()
    const graph = new Graph({
      container: containerRef.current,
      autoResize: true,
      background: { color: COLORS.bg },
      grid: { visible: true, type: 'dot', args: { color: '#22384a', thickness: 1 } },
      panning: true,
      mousewheel: { enabled: true, modifiers: ['ctrl', 'meta'] },
      interacting: { nodeMovable: true, edgeMovable: false, edgeLabelMovable: false },
      connecting: { allowBlank: false, allowLoop: false, allowNode: false, allowEdge: false },
    })
    graph.on('node:click', ({ node }) => setSelected(node.id))
    graph.on('blank:click', () => setSelected(''))
    graphRef.current = graph
    return () => { graph.dispose(); graphRef.current = null }
  }, [])

  /* ---------- 数据 → 画布（线性链路重建，保留用户拖动过的位置） ---------- */
  const posRef = useRef<Record<string, { x: number; y: number }>>({})
  useEffect(() => {
    const graph = graphRef.current
    if (!graph) return
    graph.off('node:moved')
    graph.on('node:moved', ({ node }) => { posRef.current[node.id] = node.getPosition() })

    const nodes: any[] = []
    const chainIds: string[] = []
    let x = START_X

    nodes.push({
      id: 'trigger', shape: 'lc-node', x: posRef.current['trigger']?.x ?? x, y: posRef.current['trigger']?.y ?? START_Y,
      width: NODE_W, height: NODE_H,
      data: {
        kind: 'trigger', selected: selected === 'trigger',
        title: meta.trigger_event || '(选择触发事件)', subtitle: meta.chain_name || '',
      },
    })
    chainIds.push('trigger')
    x += NODE_W + GAP_X

    conds.forEach((c, i) => {
      const id = `cond-${i}`
      nodes.push({
        id, shape: 'lc-node', x: posRef.current[id]?.x ?? x, y: posRef.current[id]?.y ?? START_Y,
        width: NODE_W, height: NODE_H,
        data: {
          kind: 'cond', seq: i, selected: selected === id,
          title: c.field ? `${c.field} ${c.op} ${c.value}` : '(未配置)', subtitle: 'AND 条件',
        },
      })
      chainIds.push(id)
      x += NODE_W + GAP_X
    })

    actions.forEach((a, i) => {
      const id = `action-${i}`
      nodes.push({
        id, shape: 'lc-node', x: posRef.current[id]?.x ?? x, y: posRef.current[id]?.y ?? START_Y,
        width: NODE_W, height: NODE_H,
        data: {
          kind: 'action', seq: i, selected: selected === id,
          title: actionLabel(a.type), subtitle: actionSummary(a),
        },
      })
      chainIds.push(id)
      x += NODE_W + GAP_X
    })

    const edges = chainIds.slice(1).map((id, i) => ({
      source: chainIds[i], target: id,
      attrs: {
        line: {
          stroke: id.startsWith('action') ? COLORS.accentPurple : COLORS.accentBlue,
          strokeWidth: 1.5, targetMarker: { name: 'block', width: 8, height: 6 },
        },
      },
      connector: { name: 'smooth' },
    }))

    graph.fromJSON({ nodes, edges })
  }, [meta, conds, actions, selected])

  /* ---------- 节点操作 ---------- */
  const addCond = () => { setConds(p => [...p, { field: '', op: 'eq', value: '' }]); setSelected(`cond-${conds.length}`) }
  const addAction = () => { setActions(p => [...p, { type: 'log_audit' }]); setSelected(`action-${actions.length}`) }

  const removeSelected = () => {
    if (selected.startsWith('cond-')) {
      const i = Number(selected.slice(5))
      setConds(p => p.filter((_, k) => k !== i))
    } else if (selected.startsWith('action-')) {
      const i = Number(selected.slice(7))
      setActions(p => p.filter((_, k) => k !== i))
    }
    delete posRef.current[selected]
    setSelected('')
  }

  const moveAction = (dir: -1 | 1) => {
    const i = Number(selected.slice(7))
    const j = i + dir
    if (j < 0 || j >= actions.length) return
    setActions(p => { const n = [...p]; [n[i], n[j]] = [n[j], n[i]]; return n })
    // 重排后清掉这两个位置的自定义坐标，避免视觉顺序与执行顺序错位
    delete posRef.current[`action-${i}`]
    delete posRef.current[`action-${j}`]
    setSelected(`action-${j}`)
  }

  const zoom = (f: number) => graphRef.current?.zoom(f)

  /* ---------- 保存 ---------- */
  const handleSave = async () => {
    if (!meta.chain_code || !meta.chain_name || !meta.trigger_event) {
      message.warning('请填写链编码、链名称和触发事件'); return
    }
    const badCond = conds.findIndex(c => !c.field)
    if (badCond >= 0) { setSelected(`cond-${badCond}`); message.warning(`条件 ${badCond + 1} 未配置字段`); return }
    setSaving(true)
    try {
      const payload = {
        ...meta,
        conditions: conds.map(c => ({ field: c.field, op: c.op, value: c.value })),
        action_sequence: actions,
      }
      if (chain?.id) await axios.put(`${API_BASE}/logic-chains/${chain.id}`, payload)
      else await axios.post(`${API_BASE}/logic-chains`, payload)
      message.success('逻辑链已保存')
      onSaved()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '保存失败')
    } finally { setSaving(false) }
  }

  /* ---------- 属性面板 ---------- */
  const panel = useMemo(() => {
    const labelStyle = { color: COLORS.textDim, fontSize: 11 }
    if (selected === 'trigger') {
      return (
        <Form layout="vertical" size="small">
          <Form.Item label={<span style={labelStyle}>链编码（唯一）</span>}>
            <Input value={meta.chain_code} disabled={!!chain?.id} maxLength={50}
              onChange={e => setMeta(m => ({ ...m, chain_code: e.target.value }))} placeholder="如 LC_WO_DELAY_ESCALATE" />
          </Form.Item>
          <Form.Item label={<span style={labelStyle}>链名称</span>}>
            <Input value={meta.chain_name} maxLength={100}
              onChange={e => setMeta(m => ({ ...m, chain_name: e.target.value }))} placeholder="如 工单延期自动升级" />
          </Form.Item>
          <Form.Item label={<span style={labelStyle}>触发事件 (event_type)</span>}>
            <AutoComplete value={meta.trigger_event} options={EVENT_SUGGESTIONS}
              onChange={v => setMeta(m => ({ ...m, trigger_event: v }))} placeholder="选择或输入事件类型" />
          </Form.Item>
          <Space size={16}>
            <Form.Item label={<span style={labelStyle}>启用</span>}>
              <Switch checked={meta.enabled} onChange={v => setMeta(m => ({ ...m, enabled: v }))} />
            </Form.Item>
            <Form.Item label={<span style={labelStyle}>执行顺序</span>}>
              <InputNumber value={meta.execution_order} min={0} max={999}
                onChange={v => setMeta(m => ({ ...m, execution_order: Number(v ?? 0) }))} />
            </Form.Item>
          </Space>
        </Form>
      )
    }
    if (selected.startsWith('cond-')) {
      const i = Number(selected.slice(5))
      const c = conds[i]
      if (!c) return null
      const patch = (p: Partial<CondCfg>) => setConds(prev => prev.map((x, k) => (k === i ? { ...x, ...p } : x)))
      return (
        <Form layout="vertical" size="small">
          <Form.Item label={<span style={labelStyle}>字段路径（支持嵌套，如 payload.load_rate）</span>}>
            <Input value={c.field} onChange={e => patch({ field: e.target.value })} placeholder="event 数据字段" />
          </Form.Item>
          <Form.Item label={<span style={labelStyle}>比较操作符</span>}>
            <Select value={c.op} options={OP_OPTIONS} onChange={v => patch({ op: v })} />
          </Form.Item>
          <Form.Item label={<span style={labelStyle}>期望值{c.op === 'in' ? '（逗号分隔多个）' : ''}</span>}>
            <Input value={c.value} onChange={e => patch({ value: e.target.value })} />
          </Form.Item>
        </Form>
      )
    }
    if (selected.startsWith('action-')) {
      const i = Number(selected.slice(7))
      const a = actions[i]
      if (!a) return null
      const patch = (p: Partial<ActionCfg>) => setActions(prev => prev.map((x, k) => (k === i ? { ...x, ...p } : x)))
      return (
        <Form layout="vertical" size="small">
          <Form.Item label={<span style={labelStyle}>动作类型</span>}>
            <Select value={a.type} options={ACTION_TYPES} onChange={v => patch({ type: v })} />
          </Form.Item>
          {a.type === 'update_param' && (<>
            <Form.Item label={<span style={labelStyle}>参数编码 (param_code)</span>}>
              <Input value={a.param_code || ''} onChange={e => patch({ param_code: e.target.value })} />
            </Form.Item>
            <Form.Item label={<span style={labelStyle}>新值</span>}>
              <Input value={a.value ?? ''} onChange={e => patch({ value: e.target.value })} />
            </Form.Item>
          </>)}
          {a.type === 'create_chatbot_ticket' && (<>
            <Form.Item label={<span style={labelStyle}>工单消息</span>}>
              <Input.TextArea rows={3} value={a.message || ''} onChange={e => patch({ message: e.target.value })} />
            </Form.Item>
            <Form.Item label={<span style={labelStyle}>工单类型</span>}>
              <Input value={a.ticket_type || 'process_change'} onChange={e => patch({ ticket_type: e.target.value })} />
            </Form.Item>
          </>)}
          {a.type === 'notify_org_unit' && (
            <Form.Item label={<span style={labelStyle}>目标组织单元</span>}>
              <Input value={a.target_org_unit || ''} onChange={e => patch({ target_org_unit: e.target.value })} />
            </Form.Item>
          )}
          {a.type === 'log_audit' && (
            <Form.Item label={<span style={labelStyle}>审计备注</span>}>
              <Input value={a.note || ''} onChange={e => patch({ note: e.target.value })} />
            </Form.Item>
          )}
          {a.type === 'escalate_rcc' && (
            <Form.Item label={<span style={labelStyle}>升级原因</span>}>
              <Input value={a.reason || ''} onChange={e => patch({ reason: e.target.value })} />
            </Form.Item>
          )}
          <Space>
            <Button size="small" icon={<ArrowUpOutlined />} disabled={i === 0} onClick={() => moveAction(-1)}>上移</Button>
            <Button size="small" icon={<ArrowDownOutlined />} disabled={i === actions.length - 1} onClick={() => moveAction(1)}>下移</Button>
          </Space>
        </Form>
      )
    }
    return <Empty description={<span style={{ color: COLORS.textMuted }}>点击画布节点编辑属性</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }, [selected, meta, conds, actions, chain])

  return (
    <Drawer
      title={
        <Space>
          <Tag color="purple" style={{ marginRight: 0 }}>X6</Tag>
          <span>{chain?.id ? `编排逻辑链：${chain.chain_name || chain.chain_code}` : '新建逻辑链'}</span>
          <Text type="secondary" style={{ fontSize: 12 }}>触发器 → 条件(AND) → 动作(顺序执行)</Text>
        </Space>
      }
      open
      onClose={onClose}
      width="86vw"
      styles={{ body: { padding: 0, background: COLORS.bg } }}
      extra={
        <Space>
          <Button icon={<ZoomOutOutlined />} onClick={() => zoom(-0.15)} />
          <Button icon={<ZoomInOutlined />} onClick={() => zoom(0.15)} />
          <Button icon={<FilterOutlined />} onClick={addCond}>加条件</Button>
          <Button icon={<PlusOutlined />} onClick={addAction}>加动作</Button>
          {selected && selected !== 'trigger' && (
            <Popconfirm title="删除该节点？" onConfirm={removeSelected}>
              <Button danger icon={<DeleteOutlined />}>删除节点</Button>
            </Popconfirm>
          )}
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>保存</Button>
        </Space>
      }
    >
      <div style={{ display: 'flex', height: '100%' }}>
        <div ref={containerRef} style={{ flex: 1, minWidth: 0 }} />
        <div style={{
          width: 320, borderLeft: `1px solid ${COLORS.border}`, padding: 16,
          background: COLORS.bgCard, overflowY: 'auto',
        }}>
          <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 13, marginBottom: 12 }}>
            节点属性
          </div>
          {panel}
        </div>
      </div>
    </Drawer>
  )
}

export default LogicChainEditor
