import React, { useState, useEffect, useCallback } from 'react'
import { getActiveFactoryId } from '../../utils/factory'
import {
  Card, Tabs, Form, Input, InputNumber, Select, Button, message, Space,
  Table, Tag, Typography, Row, Col, Result, Timeline, Divider, Statistic,
  Modal, Switch, DatePicker, Alert, Popconfirm, Checkbox,
} from 'antd'
import {
  ScanOutlined, ImportOutlined, ExportOutlined, SwapOutlined,
  SearchOutlined, HistoryOutlined, LockOutlined, UnlockOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'

const { Title, Text } = Typography
const FACTORY = getActiveFactoryId()

const typeColors: Record<string, string> = {
  inbound: 'green', outbound: 'red', transfer: 'blue', adjust: 'orange', count_diff: 'purple',
}
const typeLabels: Record<string, string> = {
  inbound: '入库', outbound: '出库', transfer: '移库', adjust: '调整', count_diff: '盘差',
}
// 词表要跟写入侧一致：冻结写的是 status='locked'，读侧别再造一个 frozen
const stockStatusMeta: Record<string, { color: string; text: string }> = {
  available: { color: 'success', text: '可用' },
  active: { color: 'success', text: '可用' },
  locked: { color: 'error', text: '质量冻结' },
  shortage: { color: 'warning', text: '缺货' },
  held: { color: 'warning', text: '待检' },
}

const StockStatusTag: React.FC<{ status?: string; reason?: string }> = ({ status, reason }) => {
  const m = stockStatusMeta[(status || '').toLowerCase()]
  if (!m) return <Tag>{status || '未标'}</Tag>
  return <Tag color={m.color}>{reason ? `${m.text}·${reason}` : m.text}</Tag>
}

/** 操作结果动画 */
const OperationResult: React.FC<{ data: any; onClose: () => void }> = ({ data, onClose }) => (
  <Result
    status="success"
    title={`${typeLabels[data.type] || data.type}成功`}
    subTitle={`${data.material_code || data.material_id} × ${data.quantity} ${data.unit || 'pcs'}`}
    extra={[
      <Button key="again" type="primary" onClick={onClose}>继续操作</Button>,
    ]}
  >
    <Space direction="vertical" size="small">
      <Text>操作后库存：<Text strong>{data.after_qty}</Text></Text>
      {/* 每一笔记账都要有单据号：没有它，事后说不清这批是谁收的、从哪张单扣的 */}
      <Text type="secondary">单据号：{data.outbound_code || data.document_no || '未记单据'}</Text>
      <Text type="secondary">流水类型：{data.transaction_type || '—'}</Text>
      <Text type="secondary">操作人：{data.operator} | {data.time?.slice(11, 19)}</Text>
    </Space>
  </Result>
)

const INBOUND_TYPES = [
  { value: 'purchase', label: '采购到货' },
  { value: 'production', label: '完工入库' },
  { value: 'return', label: '生产退料' },
  { value: 'adjustment', label: '数量调整' },
]
const OUTBOUND_TYPES = [
  { value: 'sales', label: '发货' },
  { value: 'production', label: '领料（要挂工单）' },
  { value: 'scrap', label: '报废' },
  { value: 'adjustment', label: '数量调整' },
]

/** 冻结/放行：把"锁住哪几行、凭什么锁、谁放的"变成界面动作
 *
 * 后端的账是两笔：inventory_freezes 一条记录 + inventory.status='locked' 一行锁。
 * 这里必须把 sync_check 的结论直接显示出来 —— 对不上就说明有人绕过接口改了 status，
 * 那等于回到"标了待检照样领得走"的装饰品状态。
 */
const FreezePanel: React.FC = () => {
  const [status, setStatus] = useState<any | null>(null)
  const [rows, setRows] = useState<any[]>([])
  const [keyword, setKeyword] = useState('')
  const [picked, setPicked] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [freezeModal, setFreezeModal] = useState(false)
  const [releaseTarget, setReleaseTarget] = useState<any | null>(null)
  const [applyDirectly, setApplyDirectly] = useState(false)
  const [form] = Form.useForm()
  const [releaseForm] = Form.useForm()

  const loadStatus = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/wms/freeze-status', { params: { factory_id: FACTORY } })
      setStatus(res)
    } catch { setStatus(null) } finally { setLoading(false) }
  }, [])

  const search = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/wms/search', {
        params: { factory_id: FACTORY, keyword: keyword || undefined },
      })
      setRows(res?.items || [])
    } catch { setRows([]) } finally { setLoading(false) }
  }, [keyword])

  useEffect(() => { loadStatus(); search() }, [])

  const submitFreeze = async () => {
    const vals = await form.validateFields()
    const until = vals.freeze_until ? vals.freeze_until.toISOString() : null
    try {
      const res: any = await api.post('/api/v1/wms/freeze', {
        factory_id: FACTORY,
        inventory_ids: picked,
        reason_code: vals.reason_code,
        reason_text: vals.reason_text || '',
        freeze_until: until,
        auto_unfreeze: !!vals.auto_unfreeze,
        apply: applyDirectly,
      })
      if (res.error) { message.error(res.error); return }
      message.success(applyDirectly
        ? `已冻结 ${res.frozen} 行（本来就冻着 ${res.already_frozen} 行）`
        : `预演：将冻结 ${res.frozen || res.targets?.length || 0} 行，未写入台账`)
      setFreezeModal(false); form.resetFields(); setPicked([])
      setApplyDirectly(false); loadStatus(); search()
    } catch (e: any) { message.error(e?.response?.data?.detail || '冻结失败') }
  }

  const submitRelease = async () => {
    const vals = await releaseForm.validateFields()
    try {
      const res: any = await api.post('/api/v1/wms/freeze/release', {
        factory_id: FACTORY,
        inventory_id: releaseTarget?.inventory_id,
        note: vals.note || '',
        apply: true,
      })
      if (res.error) { message.error(res.error); return }
      message.success(`放行 ${res.released} 条，放回原状态 ${res.restored} 行`
        + (res.status_left_as_is ? `，${res.status_left_as_is} 行没记原状态所以没动` : ''))
      setReleaseTarget(null); releaseForm.resetFields(); loadStatus(); search()
    } catch (e: any) { message.error(e?.response?.data?.detail || '放行失败') }
  }

  const ledger = status?.ledger
  const byStatus: Record<string, number> = {}
  ;(status?.by_status || []).forEach((r: any) => { byStatus[r.s] = r.n })

  return (
    <div>
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Statistic title="活动冻结记录" value={byStatus.active || 0} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="台账上锁的行" value={ledger?.locked_rows ?? 0}
          valueStyle={{ color: (ledger?.locked_rows ?? 0) > 0 ? '#f5222d' : undefined }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="当前挡住多少件" value={status?.blocking_qty ?? 0}
          suffix={`/ ${status?.currently_blocking ?? 0} 行`} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="人放行的" value={byStatus.released || 0}
          suffix={<span style={{ fontSize: 12 }}>到期放 {byStatus.expired || 0}</span>} /></Card></Col>
      </Row>

      {ledger && (
        <Alert
          style={{ marginBottom: 12 }}
          type={ledger.in_sync ? 'success' : 'error'}
          showIcon
          message={ledger.in_sync ? '两笔账对得上' : '两笔账对不上'}
          description={ledger.note}
        />
      )}

      <Card size="small" title="当前被冻住、领不走的库存行" style={{ marginBottom: 12 }}
        extra={<Button size="small" icon={<SearchOutlined />} onClick={loadStatus}>刷新</Button>}>
        <Table
          rowKey="inventory_id" size="small" loading={loading}
          dataSource={status?.held || []}
          pagination={{ pageSize: 8, showTotal: (t) => `共 ${t} 行（只列前 20）` }}
          locale={{ emptyText: '没有行被冻着 —— 领料/出库现在畅通' }}
          columns={[
            { title: '物料ID', dataIndex: 'material_id', width: 150 },
            { title: '库存行', dataIndex: 'inventory_id', width: 200,
              render: (v: string) => <Text copyable={{ text: v }} style={{ fontSize: 12 }}>{v.slice(0, 18)}…</Text> },
            { title: '可用件数', dataIndex: 'available_qty', width: 100, align: 'right',
              render: (v: number) => <Text strong style={{ color: '#f5222d' }}>{v}</Text> },
            { title: '原因码', dataIndex: 'reason_code', width: 120, render: (v: string) => <Tag color="error">{v || '未填'}</Tag> },
            { title: '谁冻的', dataIndex: 'frozen_by', width: 110 },
            { title: '操作', width: 90, render: (_: any, r: any) => (
              <Button size="small" icon={<UnlockOutlined />} onClick={() => setReleaseTarget(r)}>放行</Button>
            ) },
          ]}
        />
      </Card>

      <Card size="small" title="要冻结哪几行：搜出来勾，不用手抄 id"
        extra={
          <Space>
            <Input size="small" placeholder="料号/名称/批次" value={keyword}
              onChange={(e) => setKeyword(e.target.value)} onPressEnter={search} style={{ width: 180 }} />
            <Button size="small" onClick={search}>搜索</Button>
            <Button size="small" type="primary" danger icon={<LockOutlined />}
              disabled={!picked.length} onClick={() => setFreezeModal(true)}>
              冻结所选（{picked.length}）
            </Button>
          </Space>
        }>
        <Table
          rowKey="id" size="small" loading={loading}
          dataSource={rows}
          rowSelection={{
            selectedRowKeys: picked,
            onChange: (keys) => setPicked(keys as string[]),
            getCheckboxProps: (r: any) => ({ disabled: (r.status || '').toLowerCase() === 'locked' }),
          }}
          pagination={{ pageSize: 8, showTotal: (t) => `共 ${t} 行（最多 100）` }}
          columns={[
            { title: '料号', dataIndex: 'material_code', width: 140 },
            { title: '名称', dataIndex: 'material_name', ellipsis: true, width: 180 },
            { title: '批次', dataIndex: 'batch_code', width: 120 },
            { title: '可用', dataIndex: 'available_qty', width: 80, align: 'right' },
            { title: '状态', width: 150,
              render: (_: any, r: any) => <StockStatusTag status={r.status} reason={r.lock_reason} /> },
          ]}
        />
      </Card>

      <Modal
        title={`冻结 ${picked.length} 行库存`}
        open={freezeModal}
        onOk={submitFreeze}
        onCancel={() => setFreezeModal(false)}
        okText={applyDirectly ? '确认写入台账' : '只预演，不写'}
      >
        <Alert
          style={{ marginBottom: 12 }}
          type="warning"
          showIcon
          message="冻结后这些行的领料/出库/移库当场走不通"
          description={
            <Space direction="vertical">
              <span>默认只预演（apply=false，一行都不写）。要真锁住，把下面的开关打开。</span>
              <Checkbox checked={applyDirectly} onChange={(e) => setApplyDirectly(e.target.checked)}>
                直接写入台账（apply=true）
              </Checkbox>
            </Space>
          }
        />
        <Form form={form} layout="vertical">
          <Form.Item name="reason_code" label="原因码（必填，事后要靠它知道凭什么锁）"
            rules={[{ required: true, message: '冻结必须有原因码' }]}>
            <Select placeholder="选一个"
              options={['来料待检', '不合格', '事故封存', '供应商争议', '客户投诉批次'].map(v => ({ value: v, label: v }))} />
          </Form.Item>
          <Form.Item name="reason_text" label="说明"><Input.TextArea rows={2} placeholder="哪张检验单、什么问题" /></Form.Item>
          <Form.Item name="freeze_until" label="解冻期限（不填=不自动到期）"><DatePicker showTime style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="auto_unfreeze" label="到期由系统自动放行" valuePropName="checked">
            <Switch checkedChildren="到期自动放" unCheckedChildren="只人放行" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`放行：${releaseTarget?.material_id || ''}`}
        open={!!releaseTarget}
        onOk={submitRelease}
        onCancel={() => setReleaseTarget(null)}
        okText="放行并记账"
      >
        <Alert
          style={{ marginBottom: 12 }}
          type="info"
          showIcon
          message="人放行写 released，到期系统放写 expired —— 两本账分开，事后才分得清是谁批的"
        />
        <Form form={releaseForm} layout="vertical">
          <Form.Item name="note" label="放行依据（检验结论/复判单号）" rules={[{ required: true, message: '放行要落名依据' }]}>
            <Input.TextArea rows={2} placeholder="例：IQC-2026-1012 复检合格" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

/** 入库面板 */
const InboundPanel: React.FC = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setLoading(true)
      const res: any = await api.post('/api/v1/wms/inbound', { ...values, factory_id: FACTORY })
      setResult(res)
      form.resetFields()
      message.success('入库成功')
    } catch (e: any) {
      if (e?.response) message.error(e.response.data?.detail || '入库失败')
    } finally { setLoading(false) }
  }

  if (result) return <OperationResult data={result} onClose={() => setResult(null)} />

  return (
    <Form form={form} layout="vertical" style={{ maxWidth: 400 }}>
      <Form.Item name="material_code" label="物料编码" rules={[{ required: true }]}>
        <Input prefix={<ScanOutlined />} placeholder="扫码或输入物料编码" size="large" />
      </Form.Item>
      <Form.Item name="material_id" label="物料ID" rules={[{ required: true }]}>
        <Input placeholder="物料ID（如 MAT-001）" />
      </Form.Item>
      <Form.Item name="material_name" label="物料名称">
        <Input placeholder="物料名称（可选）" />
      </Form.Item>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="quantity" label="数量" rules={[{ required: true }]}>
            <InputNumber min={1} style={{ width: '100%' }} size="large" placeholder="0" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="unit" label="单位" initialValue="pcs">
            <Select options={[{ value: 'pcs' }, { value: 'kg' }, { value: 'm' }, { value: 'set' }]} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="warehouse_id" label="目标仓库" rules={[{ required: true }]}>
        <Input placeholder="仓库ID（如 WH-001）" />
      </Form.Item>
      <Form.Item name="batch_code" label="批次号">
        <Input placeholder="批次号（可选）" />
      </Form.Item>
      <Form.Item name="inbound_type" label="入库类型（决定这笔记在流水的哪一格）" initialValue="purchase">
        <Select options={INBOUND_TYPES} />
      </Form.Item>
      <Button type="primary" icon={<ImportOutlined />} size="large" block loading={loading} onClick={handleSubmit}>
        确认入库
      </Button>
    </Form>
  )
}

/** 出库面板 */
const OutboundPanel: React.FC = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setLoading(true)
      const res: any = await api.post('/api/v1/wms/outbound', { ...values, factory_id: FACTORY })
      setResult(res)
      form.resetFields()
      message.success('出库成功')
    } catch (e: any) {
      if (e?.response) message.error(e.response.data?.detail || '出库失败')
    } finally { setLoading(false) }
  }

  if (result) return <OperationResult data={result} onClose={() => setResult(null)} />

  return (
    <Form form={form} layout="vertical" style={{ maxWidth: 400 }}>
      <Form.Item name="material_id" label="物料ID" rules={[{ required: true }]}>
        <Input prefix={<ScanOutlined />} placeholder="扫码或输入物料ID" size="large" />
      </Form.Item>
      <Form.Item name="quantity" label="出库数量" rules={[{ required: true }]}>
        <InputNumber min={1} style={{ width: '100%' }} size="large" placeholder="0" />
      </Form.Item>
      <Form.Item name="warehouse_id" label="源仓库">
        <Input placeholder="仓库ID（可选，默认自动匹配）" />
      </Form.Item>
      <Form.Item name="outbound_type" label="出库用途" initialValue="sales">
        <Select options={OUTBOUND_TYPES} />
      </Form.Item>
      {Form.useWatch('outbound_type', form) === 'production' && (
        <Form.Item name="work_order_id" label="工单ID"
          rules={[{ required: true, message: '领料必须挂工单，否则这笔消耗归不到工单' }]}>
          <Input placeholder="WO-…（生产领料必填）" />
        </Form.Item>
      )}
      <Form.Item name="remark" label="备注">
        <Input placeholder="领料单号/用途（可选）" />
      </Form.Item>
      <Button type="primary" danger icon={<ExportOutlined />} size="large" block loading={loading} onClick={handleSubmit}>
        确认出库
      </Button>
    </Form>
  )
}

/** 移库面板 */
const TransferPanel: React.FC = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setLoading(true)
      const res: any = await api.post('/api/v1/wms/transfer', { ...values, factory_id: FACTORY })
      setResult(res)
      form.resetFields()
      message.success('移库成功')
    } catch (e: any) {
      if (e?.response) message.error(e.response.data?.detail || '移库失败')
    } finally { setLoading(false) }
  }

  if (result) return <OperationResult data={result} onClose={() => setResult(null)} />

  return (
    <Form form={form} layout="vertical" style={{ maxWidth: 400 }}>
      <Form.Item name="material_id" label="物料ID" rules={[{ required: true }]}>
        <Input prefix={<ScanOutlined />} placeholder="扫码或输入物料ID" size="large" />
      </Form.Item>
      <Form.Item name="quantity" label="移库数量" rules={[{ required: true }]}>
        <InputNumber min={1} style={{ width: '100%' }} size="large" placeholder="0" />
      </Form.Item>
      <Row gutter={16}>
        <Col span={12}>
          <Form.Item name="from_warehouse_id" label="源仓库" rules={[{ required: true }]}>
            <Input placeholder="WH-001" />
          </Form.Item>
        </Col>
        <Col span={12}>
          <Form.Item name="to_warehouse_id" label="目标仓库" rules={[{ required: true }]}>
            <Input placeholder="WH-002" />
          </Form.Item>
        </Col>
      </Row>
      <Button type="primary" icon={<SwapOutlined />} size="large" block loading={loading} onClick={handleSubmit}>
        确认移库
      </Button>
    </Form>
  )
}

/** 库存查询 + 操作流水 */
const InventoryPanel: React.FC = () => {
  const [keyword, setKeyword] = useState('')
  const [items, setItems] = useState<any[]>([])
  const [txns, setTxns] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  const search = async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/wms/search', { params: { factory_id: FACTORY, keyword: keyword || undefined } })
      setItems(res?.items || [])
    } catch { /* ignore */ } finally { setLoading(false) }
  }

  const loadTxns = async () => {
    try {
      const res: any = await api.get('/api/v1/wms/recent-operations', { params: { factory_id: FACTORY, limit: 30 } })
      setTxns(res?.items || [])
    } catch { /* ignore */ }
  }

  useEffect(() => { search(); loadTxns() }, [])

  const invColumns: ColumnsType<any> = [
    { title: '物料编码', dataIndex: 'material_code', key: 'code', width: 120 },
    { title: '名称', dataIndex: 'material_name', key: 'name', width: 120, render: (v) => v || '—' },
    { title: '库存', dataIndex: 'total_qty', key: 'qty', width: 80, align: 'right' },
    { title: '可用', dataIndex: 'available_qty', key: 'avail', width: 80, align: 'right' },
    { title: '仓库', dataIndex: 'warehouse_id', key: 'wh', width: 90 },
    { title: '状态', dataIndex: 'status', key: 'status', width: 140,
      render: (v: string, r: any) => <StockStatusTag status={v} reason={r.lock_reason} /> },
    { title: '最后动销', dataIndex: 'last_movement_at', key: 'last', width: 100,
      render: (v) => v ? v.slice(5, 16).replace('T', ' ') : <Text type="secondary">无</Text> },
  ]

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Input
          prefix={<SearchOutlined />}
          placeholder="搜索物料编码/名称"
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          onPressEnter={search}
          style={{ width: 250 }}
        />
        <Button onClick={search} loading={loading}>查询</Button>
      </Space>

      <Table columns={invColumns} dataSource={items} rowKey="id" size="small"
        pagination={{ pageSize: 10 }} loading={loading} style={{ marginBottom: 24 }} />

      <Divider><HistoryOutlined /> 最近操作</Divider>
      <Timeline
        items={txns.slice(0, 15).map(t => ({
          color: t.type === 'inbound' ? 'green' : t.type === 'outbound' ? 'red' : 'blue',
          children: (
            <Space>
              <Tag color={typeColors[t.type]}>{typeLabels[t.type] || t.type}</Tag>
              <Text>{t.material_id}</Text>
              <Text strong>{t.quantity > 0 ? `+${t.quantity}` : t.quantity}</Text>
              <Text type="secondary">{t.operator} | {t.time?.slice(11, 19)}</Text>
            </Space>
          ),
        }))}
      />
    </div>
  )
}

const WmsTerminal: React.FC = () => {
  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }}>
        <ScanOutlined style={{ fontSize: 22, color: '#1890ff' }} />
        <Title level={4} style={{ margin: 0 }}>仓管操作终端</Title>
        <Tag color="blue">扫码作业</Tag>
      </Space>

      <Card>
        <Tabs
          defaultActiveKey="inbound"
          items={[
            { key: 'inbound', label: <span><ImportOutlined /> 入库</span>, children: <InboundPanel /> },
            { key: 'outbound', label: <span><ExportOutlined /> 出库</span>, children: <OutboundPanel /> },
            { key: 'transfer', label: <span><SwapOutlined /> 移库</span>, children: <TransferPanel /> },
            { key: 'freeze', label: <span><LockOutlined /> 冻结/放行</span>, children: <FreezePanel /> },
            { key: 'inventory', label: <span><SearchOutlined /> 库存/流水</span>, children: <InventoryPanel /> },
          ]}
        />
      </Card>
    </div>
  )
}

export default WmsTerminal
