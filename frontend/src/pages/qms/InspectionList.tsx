import React, { useEffect, useState, useCallback } from 'react'
import {
  Table, Button, Select, Tag, Card, Space, Modal, Form, Input, InputNumber,
  message, Row, Col, Statistic,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { getInspections, createInspection, Inspection, getWorkOrders, WorkOrder } from '../../services/mes'
import { getStoredUser } from '../../services/auth'
import DrillDownDrawer from '../../components/trace/DrillDownDrawer'
import RecordDetailDrawer, { DetailField } from '../../components/trace/RecordDetailDrawer'
import { makeWorkOrderResolver } from '../../components/trace/resolvers'

const { Option } = Select

const TYPE_MAP: Record<string, { color: string; text: string }> = {
  iqc: { color: 'blue', text: '来料 IQC' },
  ipqc: { color: 'purple', text: '过程 IPQC' },
  fqc: { color: 'cyan', text: '成品 FQC' },
  oqc: { color: 'geekblue', text: '出货 OQC' },
}

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '待检' },
  inspecting: { color: 'processing', text: '检验中' },
  passed: { color: 'success', text: '合格' },
  failed: { color: 'error', text: '不合格' },
  conditional: { color: 'warning', text: '让步接收' },
}

interface DrillConfig {
  title: string
  headline?: React.ReactNode
  formula?: string
  columns: ColumnsType<any>
  records: any[]
  onRowClick?: (r: any) => void
}

const InspectionList: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<Inspection[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [typeFilter, setTypeFilter] = useState<string | undefined>()
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()

  const navigate = useNavigate()
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])
  // 追溯交互状态：统计下钻抽屉 / 检验单详情
  const [drill, setDrill] = useState<DrillConfig | null>(null)
  const [detail, setDetail] = useState<Inspection | null>(null)

  const user = getStoredUser()
  const factoryId = localStorage.getItem('active_factory_id') || user?.factory_id || 'F01'

  const MOCK_INSPECTIONS: any[] = [
    { id: 'insp-1', inspection_code: 'IQC-2026-001', inspection_type: 'iqc', status: 'passed', work_order_id: 'wo-1', product_id: 'PRD-001', sample_size: 50, defect_count: 1, inspector: '张工', factory_id: 'factory-sh-01', created_at: '2026-07-10' },
    { id: 'insp-2', inspection_code: 'IPQC-2026-002', inspection_type: 'ipqc', status: 'passed', work_order_id: 'wo-2', product_id: 'PRD-002', sample_size: 30, defect_count: 0, inspector: '李工', factory_id: 'factory-sh-01', created_at: '2026-07-12' },
    { id: 'insp-3', inspection_code: 'FQC-2026-003', inspection_type: 'fqc', status: 'failed', work_order_id: 'wo-3', product_id: 'PRD-003', sample_size: 100, defect_count: 8, inspector: '王工', factory_id: 'factory-sh-01', created_at: '2026-07-15' },
    { id: 'insp-4', inspection_code: 'OQC-2026-004', inspection_type: 'oqc', status: 'passed', work_order_id: 'wo-1', product_id: 'PRD-001', sample_size: 20, defect_count: 0, inspector: '赵工', factory_id: 'factory-sh-01', created_at: '2026-07-18' },
    { id: 'insp-5', inspection_code: 'IQC-2026-005', inspection_type: 'iqc', status: 'inspecting', work_order_id: 'wo-4', product_id: 'PRD-004', sample_size: 40, defect_count: 2, inspector: '张工', factory_id: 'factory-sh-01', created_at: '2026-07-20' },
  ]

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, any> = { factory_id: factoryId, page, page_size: 20 }
      if (typeFilter) params.inspection_type = typeFilter
      if (statusFilter) params.status = statusFilter
      const res = await getInspections(params)
      const items = res.items || []
      setData(items)
      setTotal(res.total ?? items.length)
    } catch (err: any) {
      setData([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [factoryId, page, typeFilter, statusFilter])

  useEffect(() => { fetchData() }, [fetchData])

  // 拉取工单用于外键可读化（检验单 work_order_id → 工单号）
  useEffect(() => {
    getWorkOrders({ factory_id: factoryId, page_size: 50 })
      .then(res => setWorkOrders(res.items || []))
      .catch(() => {})
  }, [factoryId])

  const handleCreate = async (values: any) => {
    try {
      await createInspection({ ...values, factory_id: factoryId })
      message.success('检验单创建成功')
      setCreateOpen(false)
      form.resetFields()
      fetchData()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '创建失败')
    }
  }

  const passedCount = data.filter(i => i.status === 'passed').length
  const failedCount = data.filter(i => i.status === 'failed').length
  const pendingCount = data.filter(i => i.status === 'pending' || i.status === 'inspecting').length

  // ===== 追溯：ID 可读化 =====
  const woLabel = makeWorkOrderResolver(workOrders)

  // ===== 追溯：检验单详情字段（全字段）=====
  const detailFields: DetailField[] = [
    { label: '检验单号', key: 'inspection_code', render: (v: string, r: Inspection) => v || r.id },
    { label: '检验类型', key: 'inspection_type', render: (v: string) => (TYPE_MAP[v] || { text: v }).text },
    { label: '物料/产品', key: 'material_id', render: (v: string, r: Inspection) => v || r.product_id || '-' },
    {
      label: '关联工单', key: 'work_order_id',
      render: (v: string) => v
        ? <a onClick={() => { setDetail(null); navigate(`/work-orders/${v}`) }}>{woLabel(v)}</a>
        : '-',
    },
    { label: '批次', key: 'batch_id', render: (v: string) => v || '-' },
    { label: '批量', key: 'batch_size', render: (v: number) => v ?? '-' },
    { label: '抽样数', key: 'sample_size', render: (v: number) => v ?? '-' },
    { label: 'AQL', key: 'aql_level', render: (v: string) => v || '-' },
    { label: '不良数', key: 'defect_qty', render: (v: number) => <span style={{ color: (v ?? 0) > 0 ? '#f5222d' : '#52c41a', fontWeight: 600 }}>{v ?? 0}</span> },
    {
      label: '不良率', key: 'defect_rate',
      render: (_: any, r: Inspection) => (r.defect_qty && r.batch_size) ? `${(r.defect_qty / r.batch_size * 100).toFixed(2)}%` : '-',
    },
    {
      label: '判定', key: 'status',
      render: (s: string) => { const i = STATUS_MAP[s] || { color: 'default', text: s }; return <Tag color={i.color}>{i.text}</Tag> },
    },
    { label: '检验员', key: 'inspector', render: (v: any) => (v && typeof v === 'object' ? v.name : v) || '-' },
    { label: '完成时间', key: 'completed_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-') },
    { label: '创建时间', key: 'created_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-') },
  ]

  // ===== 追溯：检验单下钻共用列 =====
  const drillColumns: ColumnsType<any> = [
    { title: '检验单号', dataIndex: 'inspection_code', key: 'code', width: 150, render: (v: string, r: any) => v || r.id },
    { title: '类型', dataIndex: 'inspection_type', key: 'type', width: 100, render: (v: string) => (TYPE_MAP[v] || { text: v }).text },
    { title: '物料/产品', key: 'mat', width: 120, render: (_: any, r: any) => r.material_id || r.product_id || '-' },
    { title: '批次', dataIndex: 'batch_id', key: 'batch', width: 100, render: (v: string) => v || '-' },
    { title: '不良数', dataIndex: 'defect_qty', key: 'defect', width: 70, render: (v: number) => <span style={{ color: (v ?? 0) > 0 ? '#f5222d' : '#52c41a' }}>{v ?? 0}</span> },
    { title: '判定', dataIndex: 'status', key: 'status', width: 90, render: (s: string) => { const i = STATUS_MAP[s] || { color: 'default', text: s }; return <Tag color={i.color}>{i.text}</Tag> } },
    { title: '检验员', dataIndex: 'inspector', key: 'insp', width: 80, render: (v: any) => (v && typeof v === 'object' ? v.name : v) || '-' },
  ]

  // ===== 追溯：顶部 3 个统计的下钻配置 =====
  const statDrills = {
    pending: (): DrillConfig => ({
      title: '待检/检验中 · 追溯',
      headline: `${pendingCount} 单`,
      formula: `${pendingCount} = 待检 ${data.filter(i => i.status === 'pending').length} + 检验中 ${data.filter(i => i.status === 'inspecting').length}`,
      columns: drillColumns,
      records: data.filter(i => i.status === 'pending' || i.status === 'inspecting'),
      onRowClick: (r) => setDetail(r),
    }),
    passed: (): DrillConfig => ({
      title: '合格 · 追溯',
      headline: `${passedCount} 单`,
      formula: `${passedCount} 合格 / ${data.length} 总检验单`,
      columns: drillColumns,
      records: data.filter(i => i.status === 'passed'),
      onRowClick: (r) => setDetail(r),
    }),
    failed: (): DrillConfig => ({
      title: '不合格 · 追溯',
      headline: `${failedCount} 单`,
      formula: `${failedCount} 不合格 / ${data.length} 总检验单`,
      columns: drillColumns,
      records: data.filter(i => i.status === 'failed'),
      onRowClick: (r) => setDetail(r),
    }),
  }

  const columns = [
    { title: '检验单号', dataIndex: 'inspection_code', key: 'code', width: 150, render: (v: string, r: Inspection) => v || r.id },
    {
      title: '类型', dataIndex: 'inspection_type', key: 'type', width: 110,
      render: (v: string) => { const t = TYPE_MAP[v] || { color: 'default', text: v }; return <Tag color={t.color}>{t.text}</Tag> },
    },
    { title: '物料/产品', key: 'material', width: 130, render: (_: any, r: Inspection) => r.material_id || r.product_id || '-' },
    { title: '批次', dataIndex: 'batch_id', key: 'batch', width: 110, render: (v: string) => v || '-' },
    { title: '批量', dataIndex: 'batch_size', key: 'batch_size', width: 80 },
    { title: '抽样数', dataIndex: 'sample_size', key: 'sample', width: 80, render: (v: number) => v ?? '-' },
    { title: 'AQL', dataIndex: 'aql_level', key: 'aql', width: 70, render: (v: string) => v || '-' },
    {
      title: '不良数', dataIndex: 'defect_qty', key: 'defect', width: 80,
      render: (v: number) => <span style={{ color: v > 0 ? '#f5222d' : '#52c41a', fontWeight: 500 }}>{v ?? 0}</span>,
    },
    {
      title: '不良率', key: 'defect_rate', width: 80,
      render: (_: any, r: Inspection) => {
        if (!r.defect_qty || !r.batch_size) return '-'
        return `${(r.defect_qty / r.batch_size * 100).toFixed(2)}%`
      },
    },
    {
      title: '判定', dataIndex: 'status', key: 'status', width: 100,
      render: (s: string) => { const info = STATUS_MAP[s] || { color: 'default', text: s }; return <Tag color={info.color}>{info.text}</Tag> },
    },
    { title: '检验员', dataIndex: 'inspector', key: 'inspector', width: 90, render: (v: string) => v || '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'time', width: 130, render: (v: string) => v ? dayjs(v).format('MM-DD HH:mm') : '-' },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>检验管理</h2>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.pending())}>
            <Statistic title="待检/检验中" value={pendingCount} valueStyle={{ color: '#1890ff' }} suffix="单" />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.passed())}>
            <Statistic title="合格" value={passedCount} valueStyle={{ color: '#52c41a' }} suffix="单" />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.failed())}>
            <Statistic title="不合格" value={failedCount} valueStyle={{ color: failedCount > 0 ? '#f5222d' : undefined }} suffix="单" />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
      </Row>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select placeholder="检验类型" style={{ width: 130 }} allowClear value={typeFilter} onChange={(v) => { setTypeFilter(v); setPage(1) }}>
            <Option value="iqc">来料检验</Option>
            <Option value="ipqc">过程检验</Option>
            <Option value="fqc">成品检验</Option>
            <Option value="oqc">出货检验</Option>
          </Select>
          <Select placeholder="状态" style={{ width: 120 }} allowClear value={statusFilter} onChange={(v) => { setStatusFilter(v); setPage(1) }}>
            <Option value="pending">待检</Option>
            <Option value="passed">合格</Option>
            <Option value="failed">不合格</Option>
          </Select>
          <Button type="primary" onClick={() => { setPage(1); fetchData() }}>查询</Button>
          <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建检验单</Button>
        </Space>
      </Card>

      <Table
        columns={columns}
        dataSource={data.map((item, i) => ({ ...item, key: item.id || i }))}
        loading={loading}
        size="middle"
        scroll={{ x: 1300 }}
        onRow={(r) => ({ onClick: () => setDetail(r), style: { cursor: 'pointer' } })}
        pagination={{
          current: page, pageSize: 20, total, showTotal: (t) => `共 ${t} 条`,
          onChange: (p) => setPage(p),
        }}
      />

      <Modal title="新建检验单" open={createOpen} onCancel={() => setCreateOpen(false)} footer={null} width={520}>
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item label="检验类型" name="inspection_type" rules={[{ required: true }]}>
            <Select placeholder="选择类型">
              <Option value="iqc">来料检验 (IQC)</Option>
              <Option value="ipqc">过程检验 (IPQC)</Option>
              <Option value="fqc">成品检验 (FQC)</Option>
              <Option value="oqc">出货检验 (OQC)</Option>
            </Select>
          </Form.Item>
          <Form.Item label="物料/产品编码" name="material_id" rules={[{ required: true }]}>
            <Input placeholder="输入物料或产品编码" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="批次号" name="batch_id">
                <Input placeholder="输入批次号" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="批量" name="batch_size" rules={[{ required: true }]}>
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="AQL标准" name="aql_level">
                <Select placeholder="选择AQL" allowClear>
                  <Option value="0.65">AQL 0.65</Option>
                  <Option value="1.0">AQL 1.0</Option>
                  <Option value="1.5">AQL 1.5</Option>
                  <Option value="2.5">AQL 2.5</Option>
                  <Option value="4.0">AQL 4.0</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="抽样数" name="sample_size">
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>创建</Button>
          </Form.Item>
        </Form>
      </Modal>

      {/* 追溯：统计数字下钻抽屉 */}
      {drill && (
        <DrillDownDrawer
          open
          onClose={() => setDrill(null)}
          title={drill.title}
          headline={drill.headline}
          formula={drill.formula}
          columns={drill.columns}
          records={drill.records}
          onRowClick={drill.onRowClick}
        />
      )}

      {/* 追溯：检验单详情 */}
      <RecordDetailDrawer
        open={!!detail}
        onClose={() => setDetail(null)}
        title="检验单详情"
        record={detail}
        fields={detailFields}
      />
    </div>
  )
}

export default InspectionList
