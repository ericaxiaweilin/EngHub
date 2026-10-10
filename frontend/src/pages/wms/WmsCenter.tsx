import React, { useEffect, useState, useCallback } from 'react'
import { getActiveFactoryId } from '../../utils/factory'
import {
  Card, Tabs, Table, Button, Tag, Space, Row, Col, Statistic, Modal, Form,
  Input, InputNumber, Select, message, Empty, Spin, Timeline, Drawer, Progress,
  Popconfirm, Alert, Tooltip,
} from 'antd'
import {
  AuditOutlined, SearchOutlined, PlusOutlined, WarningOutlined, DashboardOutlined,
  EditOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const FACTORY = getActiveFactoryId()

// ============== 盘点录入（把实测数敲进明细） ==============
// 为什么要有这一层：POST /inventory/count/{id}/items 只认 item_id，而在这次补 GET 明细之前
// 全仓没有任何地方能列出 item_id —— 于是"已录实测 0/200"从来不是现场没盘，是人看不到该录哪几行。
const CountEntryDrawer: React.FC<{
  order: any | null
  onClose: () => void
  onChanged: () => void
}> = ({ order, onClose, onChanged }) => {
  const [items, setItems] = useState<any[]>([])
  const [meta, setMeta] = useState<any | null>(null)
  const [draft, setDraft] = useState<Record<string, number | null>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState<string | null>(null)
  const [approving, setApproving] = useState(false)

  const load = useCallback(async () => {
    if (!order?.id) return
    setLoading(true)
    try {
      const res: any = await api.get(`/api/v1/inventory/count/${order.id}/items`)
      setItems(res.items || [])
      setMeta(res)
      setDraft({})
    } catch {
      setItems([]); setMeta(null)
    } finally { setLoading(false) }
  }, [order?.id])

  useEffect(() => { load() }, [load])

  const save = async (row: any) => {
    const value = draft[row.item_id]
    if (value === undefined || value === null) { message.warning('先填这一行的实测数'); return }
    setSaving(row.item_id)
    try {
      const res: any = await api.post(`/api/v1/inventory/count/${order.id}/items`, {
        item_id: row.item_id, counted_qty: value,
      })
      const diff = Number(res.diff_qty ?? 0)
      message.success(diff === 0 ? '已录入：与系统数一致' : `已录入：差异 ${diff > 0 ? '+' : ''}${diff}`)
      await load(); onChanged()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '录入失败')
    } finally { setSaving(null) }
  }

  const approve = async () => {
    setApproving(true)
    try {
      const res: any = await api.post(`/api/v1/inventory/count/${order.id}/approve`, {})
      message.success(res.message || '盘点已审批')
      await load(); onChanged()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '审批失败')
    } finally { setApproving(false) }
  }

  const pending = meta?.pending ?? 0
  const columns = [
    { title: '料号', dataIndex: 'material_code', width: 130 },
    { title: '名称', dataIndex: 'material_name', width: 170, ellipsis: true,
      render: (v: string) => v ? <Tooltip title={v}>{v}</Tooltip> : <span style={{ color: '#999' }}>—</span> },
    { title: '库位', dataIndex: 'location_code', width: 120,
      render: (v: string) => v || <span style={{ color: '#999' }}>无库位</span> },
    { title: '批次', dataIndex: 'batch_code', width: 120, render: (v: string) => v || '—' },
    { title: '系统数', dataIndex: 'system_qty', width: 90, align: 'right' as const },
    { title: '实测数', width: 120, align: 'center' as const,
      render: (_: any, r: any) => (
        <InputNumber
          size="small" min={0} style={{ width: 100 }}
          defaultValue={r.counted_qty ?? undefined}
          placeholder={r.counted_qty == null ? '实盘数' : String(r.counted_qty)}
          onChange={(v) => setDraft(d => ({ ...d, [r.item_id]: v as number | null }))}
        />
      ) },
    { title: '差异', width: 80, align: 'right' as const,
      render: (_: any, r: any) => {
        const v = draft[r.item_id] ?? r.counted_qty
        if (v === undefined || v === null) return <span style={{ color: '#999' }}>未盘</span>
        const diff = Number(v) - Number(r.system_qty ?? 0)
        return <span style={{ color: diff === 0 ? '#999' : '#f5222d', fontWeight: diff === 0 ? 400 : 600 }}>
          {diff > 0 ? `+${diff}` : diff}
        </span>
      } },
    { title: '状态', width: 90,
      render: (_: any, r: any) => r.adjusted
        ? <Tag color="success">已调差</Tag>
        : (r.counted_qty != null ? <Tag color="processing">已录</Tag> : <Tag>未录</Tag>) },
    { title: '操作', width: 80,
      render: (_: any, r: any) => (
        <Button size="small" type="link" loading={saving === r.item_id}
          disabled={draft[r.item_id] === undefined || draft[r.item_id] === null}
          onClick={() => save(r)}>保存</Button>
      ) },
  ]

  return (
    <Drawer
      open
      width={1000}
      onClose={onClose}
      title={order ? `盘点录入 · ${order.count_code || order.id}` : '盘点录入'}
      extra={
        <Popconfirm
          title="提交审批并调整台账？"
          description={pending > 0
            ? `还有 ${pending} 行没录实测数 —— 审批只调已录的行，没录的不动库存`
            : '所有明细都已录入，审批后按差异自动盘盈/盘亏'}
          okText="审批"
          cancelText="先不"
          onConfirm={approve}
        >
          <Button type="primary" icon={<CheckCircleOutlined />} loading={approving} disabled={!items.length}>
            提交审批
          </Button>
        </Popconfirm>
      }
    >
      {order && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message={`厂区 ${FACTORY} · 仓库 ${order.warehouse_id || '未指定'} · 当前状态 ${order.status || '—'}`}
          description={meta ? (
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <span>
                已录 {meta.counted}/{meta.total} 行 · 待录 {meta.pending} · 有差异 {meta.with_diff} 行
                · 已调差 {items.filter(i => i.adjusted).length} 行
              </span>
              <Progress percent={Math.round((meta.counted / Math.max(1, meta.total)) * 100)} size="small" />
              <span style={{ color: '#8c8c8c', fontSize: 12 }}>{meta.note}</span>
            </Space>
          ) : '明细没读到（GET /api/v1/inventory/count/{id}/items）'}
        />
      )}
      <Table
        rowKey="item_id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 行` }}
      />
    </Drawer>
  )
}

// ============== 盘点管理 ==============
const CountPanel: React.FC = () => {
  const [counts, setCounts] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [createModal, setCreateModal] = useState(false)
  const [entry, setEntry] = useState<any | null>(null)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/inventory/count', { params: { factory_id: FACTORY } })
      setCounts(res.items || [])
    } catch { /* */ } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const handleCreate = async () => {
    const vals = await form.validateFields()
    try {
      const res: any = await api.post('/api/v1/inventory/count', { ...vals, factory_id: FACTORY })
      message.success(`盘点单已创建，${res.total_items} 项待盘`)
      setCreateModal(false); form.resetFields(); load()
    } catch (e: any) { message.error(e?.response?.data?.detail || '失败') }
  }

  const statusColor: Record<string, string> = { draft: 'default', counting: 'processing', pending_approval: 'warning', approved: 'success', rejected: 'error' }
  const statusText: Record<string, string> = { draft: '草稿', counting: '盘点中', pending_approval: '待审批', approved: '已审批', rejected: '已驳回' }

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)}>新建盘点</Button>
        <Button icon={<SearchOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Table dataSource={counts} rowKey="id" size="small" loading={loading} pagination={{ pageSize: 10 }}
        columns={[
          { title: '盘点单号', dataIndex: 'count_code', width: 180 },
          { title: '类型', dataIndex: 'count_type', width: 80, render: (v: string) => <Tag>{v}</Tag> },
          { title: '状态', dataIndex: 'status', width: 100, render: (v: string) => <Tag color={statusColor[v]}>{statusText[v] || v}</Tag> },
          { title: '总项数', dataIndex: 'total_items', width: 80 },
          { title: '差异项', dataIndex: 'diff_items', width: 80, render: (v: number) => <span style={{ color: v > 0 ? '#f5222d' : undefined }}>{v}</span> },
          { title: '差异数量', dataIndex: 'total_diff_qty', width: 90 },
          { title: '创建时间', dataIndex: 'created_at', width: 110, render: (v: string) => v?.slice(0, 10) },
          { title: '操作', width: 110,
            render: (_: any, r: any) => (
              <Button size="small" icon={<EditOutlined />} onClick={() => setEntry(r)}>录入明细</Button>
            ) },
        ]}
      />
      {entry && <CountEntryDrawer order={entry} onClose={() => setEntry(null)} onChanged={load} />}
      <Modal title="新建盘点单" open={createModal} onOk={handleCreate} onCancel={() => setCreateModal(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="warehouse_id" label="仓库ID" rules={[{ required: true }]}><Input placeholder="仓库ID" /></Form.Item>
          <Form.Item name="count_type" label="盘点类型" initialValue="periodic">
            <Select options={[{ value: 'periodic', label: '定期盘点' }, { value: 'cycle', label: '循环盘点' }, { value: 'spot', label: '抽盘' }]} />
          </Form.Item>
          <Form.Item name="remark" label="备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ============== 物料追溯 ==============
const TracePanel: React.FC = () => {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [materialId, setMaterialId] = useState('')
  const [batchCode, setBatchCode] = useState('')

  const handleTrace = async () => {
    if (!materialId) { message.warning('请输入物料ID'); return }
    setLoading(true)
    try {
      const res: any = await api.get(`/api/v1/inventory/material/${materialId}/trace`, {
        params: { factory_id: FACTORY, batch_code: batchCode || undefined }
      })
      setData(res)
    } catch { setData(null) } finally { setLoading(false) }
  }

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Input placeholder="物料ID" value={materialId} onChange={e => setMaterialId(e.target.value)} style={{ width: 180 }} />
        <Input placeholder="批次号(可选)" value={batchCode} onChange={e => setBatchCode(e.target.value)} style={{ width: 150 }} />
        <Button type="primary" icon={<SearchOutlined />} onClick={handleTrace}>追溯</Button>
      </Space>

      <Spin spinning={loading}>
        {!data ? <Empty description="输入物料ID进行正反向追溯" /> : (
          <Row gutter={12}>
            <Col span={8}>
              <Card size="small" title="入库记录" extra={<Tag color="green">{data.inbound_records?.length}</Tag>}>
                {data.inbound_records?.length ? (
                  <Timeline items={data.inbound_records.map((r: any) => ({
                    color: 'green',
                    children: <div><b>{r.code}</b> +{r.quantity} <br /><span style={{ fontSize: 11, color: '#999' }}>{r.batch_code} | {r.created_at?.slice(0, 10)}</span></div>,
                  }))} />
                ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small" title="出库记录" extra={<Tag color="orange">{data.outbound_records?.length}</Tag>}>
                {data.outbound_records?.length ? (
                  <Timeline items={data.outbound_records.map((r: any) => ({
                    color: 'orange',
                    children: <div><b>{r.code}</b> -{r.quantity} <br /><span style={{ fontSize: 11, color: '#999' }}>{r.batch_code} | {r.created_at?.slice(0, 10)}</span></div>,
                  }))} />
                ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small" title="库存流水" extra={<Tag color="blue">{data.transactions?.length}</Tag>}>
                {data.transactions?.length ? (
                  <Timeline items={data.transactions.slice(0, 10).map((t: any) => ({
                    color: t.quantity > 0 ? 'green' : 'red',
                    children: <div>{t.transaction_type} {t.quantity > 0 ? '+' : ''}{t.quantity} <br /><span style={{ fontSize: 11, color: '#999' }}>{t.remark || t.operator} | {t.created_at?.slice(5, 16)}</span></div>,
                  }))} />
                ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
              </Card>
            </Col>
          </Row>
        )}
      </Spin>
    </div>
  )
}

// ============== 库存预警 ==============
const AlertPanel: React.FC = () => {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    (async () => {
      setLoading(true)
      try {
        const res: any = await api.get('/api/v1/inventory/alerts', { params: { factory_id: FACTORY } })
        setData(res)
      } catch { /* */ } finally { setLoading(false) }
    })()
  }, [])

  if (loading) return <Spin />
  if (!data) return <Empty />

  return (
    <div>
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={8}><Card size="small"><Statistic title="预警总数" value={data.alert_count} prefix={<WarningOutlined />} valueStyle={{ color: data.alert_count > 0 ? '#f5222d' : '#52c41a' }} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="零库存" value={data.zero_stock?.length} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="低库存" value={data.low_stock?.length} /></Card></Col>
      </Row>
      <Card size="small" title="零库存物料" style={{ marginBottom: 12 }}>
        {data.zero_stock?.length ? (
          <Table dataSource={data.zero_stock} rowKey="material_id" size="small" pagination={false}
            columns={[{ title: '物料ID', dataIndex: 'material_id' }, { title: '物料编码', dataIndex: 'material_code' }, { title: '批次', dataIndex: 'batch_code' }]} />
        ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无" />}
      </Card>
      <Card size="small" title="低库存物料">
        {data.low_stock?.length ? (
          <Table dataSource={data.low_stock} rowKey="material_id" size="small" pagination={false}
            columns={[{ title: '物料ID', dataIndex: 'material_id' }, { title: '物料编码', dataIndex: 'material_code' }, { title: '可用量', dataIndex: 'available_qty', render: (v: number) => <Tag color="warning">{v}</Tag> }]} />
        ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无" />}
      </Card>
    </div>
  )
}

// ============== 能力矩阵（WMS 到底哪一格能用、哪一格缺东西） ==============
// 这一格存在的理由：后端 10-09 把"仓储功能很弱"拆成了 14 张可核对的格子，但界面上一格都看不见 ——
// 判词只能靠 curl 读，等于没交付。四种状态必须分颜色分开文字，不能笼统写成"弱"：
// live=有数据有人在用；thin=有数但填充率低到不能当结论；empty=表和接口都在、0 行（没被走过）；
// blocked_on_source=外部源没有新数（点名哪个源、停更多久），不拿过期快照出读数。
const STATE_META: Record<string, { color: string; text: string }> = {
  live: { color: 'success', text: '能用' },
  thin: { color: 'warning', text: '数不够硬' },
  empty: { color: 'default', text: '从没被走过' },
  blocked_on_source: { color: 'error', text: '缺外部新数' },
  not_computable: { color: 'processing', text: '算不出' },
  error: { color: 'error', text: '读取出错' },
}

const CapabilityPanel: React.FC = () => {
  const [data, setData] = useState<any | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/wms/capability', { params: { factory_id: FACTORY } })
      setData(res)
    } catch { /* 读不到要显式空态，不能拿上一厂的数顶着看 */ } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  if (loading) return <Spin />
  if (!data) return <Empty description="能力矩阵没读到（GET /api/v1/wms/capability）" />

  const score = data.score || {}
  return (
    <div>
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Statistic title="能用" value={score.live || 0} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="数不够硬" value={score.thin || 0} valueStyle={{ color: '#faad14' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="从没被走过" value={score.empty || 0} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="缺外部新数" value={score.blocked_on_source || 0} valueStyle={{ color: '#f5222d' }} /></Card></Col>
      </Row>
      <Table dataSource={data.capabilities || []} rowKey="capability" size="small"
        pagination={false}
        columns={[
          { title: '状态', dataIndex: 'state', width: 120, render: (v: string) => {
              const m = STATE_META[v] || { color: 'default', text: v }
              return <Tag color={m.color}>{m.text}</Tag>
            } },
          { title: '能力', dataIndex: 'capability', width: 190 },
          { title: '实测读数', dataIndex: 'reads' },
          { title: '还缺什么', dataIndex: 'missing', width: 260,
            render: (v: string) => v || <span style={{ color: '#999' }}>—</span> },
        ]}
      />
      <Card size="small" style={{ marginTop: 12 }} title="判词怎么读">
        <div style={{ whiteSpace: 'pre-wrap', color: '#555', fontSize: 12 }}>{data.rule}</div>
        <div style={{ color: '#999', fontSize: 12, marginTop: 6 }}>
          生成时间 {String(data.generated_at || '').replace('T', ' ').slice(0, 19)} · 厂区 {data.factory_id}
          （空表不等于坏了，也不等于通过）
        </div>
      </Card>
    </div>
  )
}


// ============== 主页面 ==============
const WmsCenter: React.FC = () => {
  return (
    <Tabs size="small" defaultActiveKey="count" items={[
      { key: 'count', label: <span><AuditOutlined /> 盘点管理</span>, children: <CountPanel /> },
      { key: 'trace', label: <span><SearchOutlined /> 物料追溯</span>, children: <TracePanel /> },
      { key: 'alerts', label: <span><WarningOutlined /> 库存预警</span>, children: <AlertPanel /> },
      { key: 'capability', label: <span><DashboardOutlined /> 能力矩阵</span>, children: <CapabilityPanel /> },
    ]} />
  )
}

export default WmsCenter
