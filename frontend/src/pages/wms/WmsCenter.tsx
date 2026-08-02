import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Tabs, Table, Button, Tag, Space, Row, Col, Statistic, Modal, Form,
  Input, Select, message, Empty, Spin, Timeline,
} from 'antd'
import {
  AuditOutlined, SearchOutlined, PlusOutlined, WarningOutlined, BoxPlotOutlined, ApiOutlined,
} from '@ant-design/icons'
import api from '../../services/api'
import VolumeManagement from './VolumeManagement'
import WmsEnhancementHub from './WmsEnhancementHub'

const FACTORY = 'F001'

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
          {
            title: '操作', key: 'act', width: 90,
            render: (_: any, r: any) => r.status === 'pending_approval' ? (
              <Button size="small" type="link" onClick={async () => {
                try {
                  await api.post(`/api/v1/inventory/count/${r.id}/approve`)
                  message.success('盘点差异已审批调整')
                  load()
                } catch (e: any) { message.error(e?.response?.data?.detail || '审批失败') }
              }}>审批</Button>
            ) : null,
          },
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

// ============== 主页面 ==============
const WmsCenter: React.FC = () => {
  return (
    <Tabs size="small" defaultActiveKey="count" items={[
      { key: 'count', label: <span><AuditOutlined /> 盘点管理</span>, children: <CountPanel /> },
      { key: 'trace', label: <span><SearchOutlined /> 物料追溯</span>, children: <TracePanel /> },
      { key: 'alerts', label: <span><WarningOutlined /> 库存预警</span>, children: <AlertPanel /> },
      { key: 'volume', label: <span><BoxPlotOutlined /> 体积管理</span>, children: <VolumeManagement /> },
      { key: 'enhancement', label: <span><ApiOutlined /> 增强功能</span>, children: <WmsEnhancementHub /> },
    ]} />
  )
}

export default WmsCenter
