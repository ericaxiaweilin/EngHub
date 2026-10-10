import React, { useEffect, useState, useCallback } from 'react'
import { getActiveFactoryId } from '../../utils/factory'
import {
  Card, Tabs, Table, Button, Tag, Space, Row, Col, Statistic, Modal, Form,
  Input, Select, message, Empty, Spin, Timeline,
} from 'antd'
import {
  AuditOutlined, SearchOutlined, PlusOutlined, WarningOutlined, DashboardOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const FACTORY = getActiveFactoryId()

// ============== 盘点管理 ==============
const CountPanel: React.FC = () => {
  const [counts, setCounts] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [createModal, setCreateModal] = useState(false)
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
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)} style={{ marginBottom: 12 }}>新建盘点</Button>
      <Table dataSource={counts} rowKey="id" size="small" loading={loading} pagination={{ pageSize: 10 }}
        columns={[
          { title: '盘点单号', dataIndex: 'count_code', width: 180 },
          { title: '类型', dataIndex: 'count_type', width: 80, render: (v: string) => <Tag>{v}</Tag> },
          { title: '状态', dataIndex: 'status', width: 100, render: (v: string) => <Tag color={statusColor[v]}>{statusText[v] || v}</Tag> },
          { title: '总项数', dataIndex: 'total_items', width: 80 },
          { title: '差异项', dataIndex: 'diff_items', width: 80, render: (v: number) => <span style={{ color: v > 0 ? '#f5222d' : undefined }}>{v}</span> },
          { title: '差异数量', dataIndex: 'total_diff_qty', width: 90 },
          { title: '创建时间', dataIndex: 'created_at', width: 110, render: (v: string) => v?.slice(0, 10) },
        ]}
      />
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
