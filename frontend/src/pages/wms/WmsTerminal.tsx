import React, { useState, useEffect } from 'react'
import {
  Card, Tabs, Form, Input, InputNumber, Select, Button, message, Space,
  Table, Tag, Typography, Row, Col, Result, Timeline, Divider,
} from 'antd'
import {
  ScanOutlined, ImportOutlined, ExportOutlined, SwapOutlined,
  SearchOutlined, HistoryOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'

const { Title, Text } = Typography
const FACTORY = 'F001'

const typeColors: Record<string, string> = {
  inbound: 'green', outbound: 'red', transfer: 'blue', adjust: 'orange', count_diff: 'purple',
}
const typeLabels: Record<string, string> = {
  inbound: '入库', outbound: '出库', transfer: '移库', adjust: '调整', count_diff: '盘差',
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
      <Text type="secondary">操作人：{data.operator} | {data.time?.slice(11, 19)}</Text>
    </Space>
  </Result>
)

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
            { key: 'inventory', label: <span><SearchOutlined /> 库存/流水</span>, children: <InventoryPanel /> },
          ]}
        />
      </Card>
    </div>
  )
}

export default WmsTerminal
