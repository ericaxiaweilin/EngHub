import React, { useEffect, useState } from 'react'
import {
<<<<<<< HEAD
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, message, Empty, Row, Col,
  Progress,
} from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
=======
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, InputNumber,
  message, Row, Col, Statistic, Popconfirm, Tooltip, Progress,
} from 'antd'
import { PlusOutlined, DeleteOutlined, FundOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'
>>>>>>> 7258e8d

interface ProcessAnalysis {
  id: string
  factory_id: string
  product_id: string
<<<<<<< HEAD
  operation_code: string
  va_ratio: number
  efficiency_score: number
  created_at: string
}

const ProcessAnalyses: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<ProcessAnalysis[]>([])
  const [loading, setLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
=======
  operation_name: string
  value_type: string
  process_time: number
  inspection_time: number
  transport_time: number
  wait_time: number
  storage_time: number
  value_ratio: number
  created_at: string
}

const VALUE_TYPE_MAP: Record<string, { color: string; text: string }> = {
  va: { color: 'green', text: '增值' },
  nva: { color: 'red', text: '非增值' },
  nnva: { color: 'orange', text: '必要非增值' },
}

const MOCK_DATA: ProcessAnalysis[] = [
  { id: 'pa-1', factory_id: 'factory-sh-01', product_id: 'PRD-001', operation_name: '下料', value_type: 'va', process_time: 45.0, inspection_time: 5.0, transport_time: 8.0, wait_time: 2.0, storage_time: 0, value_ratio: 0.75, created_at: '2026-06-01' },
  { id: 'pa-2', factory_id: 'factory-sh-01', product_id: 'PRD-001', operation_name: '车削加工', value_type: 'va', process_time: 120.0, inspection_time: 10.0, transport_time: 5.0, wait_time: 3.0, storage_time: 0, value_ratio: 0.87, created_at: '2026-06-01' },
  { id: 'pa-3', factory_id: 'factory-sh-01', product_id: 'PRD-001', operation_name: '工序间搬运', value_type: 'nva', process_time: 0, inspection_time: 0, transport_time: 30.0, wait_time: 15.0, storage_time: 0, value_ratio: 0.0, created_at: '2026-06-01' },
  { id: 'pa-4', factory_id: 'factory-sh-01', product_id: 'PRD-002', operation_name: '质量检验', value_type: 'nnva', process_time: 0, inspection_time: 60.0, transport_time: 3.0, wait_time: 12.0, storage_time: 0, value_ratio: 0.32, created_at: '2026-06-05' },
  { id: 'pa-5', factory_id: 'factory-sh-01', product_id: 'PRD-002', operation_name: '装配', value_type: 'va', process_time: 90.0, inspection_time: 8.0, transport_time: 4.0, wait_time: 5.0, storage_time: 0, value_ratio: 0.84, created_at: '2026-06-05' },
  { id: 'pa-6', factory_id: 'factory-sh-01', product_id: 'PRD-003', operation_name: '等待天车', value_type: 'nva', process_time: 0, inspection_time: 0, transport_time: 0, wait_time: 45.0, storage_time: 10.0, value_ratio: 0.0, created_at: '2026-06-10' },
]

const ProcessAnalyses: React.FC = () => {
  const [factory, setFactory] = useState('factory-sh-01')
  const [data, setData] = useState<ProcessAnalysis[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()
>>>>>>> 7258e8d

  const fetchData = async () => {
    setLoading(true)
    try {
<<<<<<< HEAD
      const res = await fetch(`http://localhost:8000/api/v1/ie/process-analyses?factory_id=${factory}&limit=500`)
      const data = await res.json()
      setData(Array.isArray(data) ? data : [])
    } catch (e) {
      console.error('Error fetching process analyses', e)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [factory, searchTerm])

  const filteredData = data.filter(item =>
    item.operation_code.toLowerCase().includes(searchTerm.toLowerCase()) ||
    item.product_id.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const columns: ColumnsType<ProcessAnalysis> = [
    {
      title: '工厂ID',
      dataIndex: 'factory_id',
      key: 'factory_id',
      width: 100,
    },
    {
      title: '产品ID',
      dataIndex: 'product_id',
      key: 'product_id',
      width: 120,
    },
    {
      title: '工序代码',
      dataIndex: 'operation_code',
      key: 'operation_code',
      width: 140,
    },
    {
      title: '增值比率(%)',
      dataIndex: 'va_ratio',
      key: 'va_ratio',
      width: 120,
      render: (val) => (
        <Space direction="vertical" align="center">
          <Progress type="circle" percent={val * 100} status={val > 0.7 ? 'success' : val > 0.4 ? 'warning' : 'danger'} />
          <Tag>{(val * 100).toFixed(1)}%</Tag>
        </Space>
      ),
    },
    {
      title: '效率评分',
      dataIndex: 'efficiency_score',
      key: 'efficiency_score',
      width: 100,
      render: (val) => <Tag color={val > 80 ? 'green' : val > 60 ? 'blue' : 'red'}>{val.toFixed(1)}</Tag>,
    },
    {
      title: '创建日期',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (val) => dayjs(val).format('YYYY-MM-DD'),
    },
  ]

  return (
    <Card title="工序价值分析">
      <Row gutter={16} align="middle" style={{ marginBottom: 16 }}>
        <Col span={3}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => message.info('Create button not implemented yet')}>
            新增分析
          </Button>
        </Col>
        <Col span={4}>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }}>
            <Select.Option value="F001">F001 厂区</Select.Option>
          </Select>
        </Col>
        <Col span={8}>
          <Input
            placeholder="搜索工序代码或产品..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            prefix={<SearchOutlined />}
          />
        </Col>
      </Row>

      {filteredData.length > 0 ? (
        <Table
          dataSource={filteredData}
          columns={columns}
          loading={loading}
          pagination={{ pageSize: 10 }}
          rowKey="id"
        />
      ) : (
        <Empty description={loading ? '加载中...' : '暂无分析数据'} style={{ margin: '40px 0' }} />
      )}
    </Card>
  )
}

export default ProcessAnalyses
=======
      const res = await api.get(API_ENDPOINTS.IE_PROCESS_ANALYSES, { params: { factory_id: factory, limit: 200 } })
      const items = res.items || res || []
      setData(items)
    } catch { setData([]) } finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [factory])

  const vaCount = data.filter(d => d.value_type === 'va').length
  const avgRatio = data.length > 0 ? (data.reduce((s, d) => s + (d.value_ratio || 0), 0) / data.length * 100).toFixed(1) : '0'

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      await api.post(API_ENDPOINTS.IE_PROCESS_ANALYSES, { ...values, factory_id: factory })
      message.success('创建成功')
      setModalOpen(false); form.resetFields(); fetchData()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '创建失败')
    }
  }

  const handleDelete = async (id: string) => {
    try { await api.delete(`${API_ENDPOINTS.IE_PROCESS_ANALYSES}/${id}`); message.success('已删除'); fetchData() }
    catch { message.error('删除失败') }
  }

  const columns: ColumnsType<ProcessAnalysis> = [
    { title: '产品', dataIndex: 'product_id', key: 'product_id', width: 100, ellipsis: true },
    { title: '工序名称', dataIndex: 'operation_name', key: 'operation_name', width: 140, ellipsis: true },
    {
      title: '价值类型', dataIndex: 'value_type', key: 'value_type', width: 100,
      filters: [{ text: '增值', value: 'va' }, { text: '非增值', value: 'nva' }, { text: '必要非增值', value: 'nnva' }],
      onFilter: (v, r) => r.value_type === v,
      render: v => { const t = VALUE_TYPE_MAP[v] || { color: 'default', text: v }; return <Tag color={t.color}>{t.text}</Tag> },
    },
    { title: '加工(s)', dataIndex: 'process_time', key: 'process_time', width: 80, render: v => (v || 0).toFixed(1) },
    { title: '检验(s)', dataIndex: 'inspection_time', key: 'inspection_time', width: 80, render: v => (v || 0).toFixed(1) },
    { title: '搬运(s)', dataIndex: 'transport_time', key: 'transport_time', width: 80, render: v => (v || 0).toFixed(1) },
    { title: '等待(s)', dataIndex: 'wait_time', key: 'wait_time', width: 80, render: v => <span style={{ color: v > 10 ? '#ff4d4f' : undefined }}>{(v || 0).toFixed(1)}</span> },
    { title: '存储(s)', dataIndex: 'storage_time', key: 'storage_time', width: 80, render: v => (v || 0).toFixed(1) },
    {
      title: '增值比', dataIndex: 'value_ratio', key: 'value_ratio', width: 120,
      sorter: (a, b) => a.value_ratio - b.value_ratio,
      render: v => {
        const pct = Math.round((v || 0) * 100)
        return <Progress percent={pct} size="small" strokeColor={pct >= 60 ? '#52c41a' : pct >= 30 ? '#faad14' : '#ff4d4f'} />
      },
    },
    {
      title: '操作', key: 'action', width: 60, fixed: 'right',
      render: (_, r) => (
        <Popconfirm title="确认删除?" onConfirm={() => handleDelete(r.id)}>
          <Button type="link" size="small" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="工序总数" value={data.length} prefix={<FundOutlined />} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="增值工序" value={vaCount} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="平均增值比" value={avgRatio} suffix="%" valueStyle={{ color: '#1890ff' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="非增值工序" value={data.filter(d => d.value_type === 'nva').length} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
      </Row>

      <Card title="工序价值分析" extra={
        <Space>
          <Select value={factory} onChange={setFactory} style={{ width: 140 }} size="small">
            <Select.Option value="factory-sh-01">上海工厂</Select.Option>
            <Select.Option value="FAC_ELEC_DEMO_2026">电子工厂</Select.Option>
            <Select.Option value="FAC_MECH_001">机械工厂</Select.Option>
          </Select>
          <Button type="primary" icon={<PlusOutlined />} size="small" onClick={() => { form.resetFields(); setModalOpen(true) }}>新增</Button>
        </Space>
      }>
        <Table dataSource={data} columns={columns} loading={loading} rowKey="id" scroll={{ x: 1100 }} size="middle"
          pagination={{ pageSize: 15, showTotal: t => `共 ${t} 条` }} />
      </Card>

      <Modal title="新增工序分析" open={modalOpen} onOk={handleCreate} onCancel={() => setModalOpen(false)} okText="保存" cancelText="取消" width={560}>
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="product_id" label="产品ID" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="operation_name" label="工序名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
          </Row>
          <Form.Item name="value_type" label="价值类型" rules={[{ required: true }]} initialValue="va">
            <Select><Select.Option value="va">增值</Select.Option><Select.Option value="nva">非增值</Select.Option><Select.Option value="nnva">必要非增值</Select.Option></Select>
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="process_time" label="加工时间(s)"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="inspection_time" label="检验时间(s)"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="transport_time" label="搬运时间(s)"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="wait_time" label="等待时间(s)"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="storage_time" label="存储时间(s)"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="value_ratio" label="增值比(0~1)"><InputNumber min={0} max={1} step={0.01} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>
    </div>
  )
}

export default ProcessAnalyses
>>>>>>> 7258e8d
