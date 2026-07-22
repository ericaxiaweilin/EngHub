import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, InputNumber,
  Select, DatePicker, message, Descriptions, Empty, Row, Col, Statistic,
  Tooltip, Badge, Progress, Alert,
} from 'antd'
import {
  PlusOutlined, CalculatorOutlined, CheckCircleOutlined,
  SendOutlined, WarningOutlined, ReloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import { listPlans, createPlan, confirmPlan, releasePlan, calculateMrp, checkCapacityConflict } from '../../services/modules'
import DrillDownDrawer from '../../components/trace/DrillDownDrawer'
import RecordDetailDrawer, { DetailField } from '../../components/trace/RecordDetailDrawer'

const statusMap: Record<string, { color: string; text: string; next?: string }> = {
  draft: { color: 'default', text: '草稿', next: 'confirmed' },
  confirmed: { color: 'processing', text: '已确认', next: 'released' },
  released: { color: 'success', text: '已下达' },
}

const customerLevelMap: Record<string, { color: string; text: string }> = {
  a: { color: 'gold', text: 'A 级 (战略)' },
  b: { color: 'blue', text: 'B 级 (重要)' },
  c: { color: 'default', text: 'C 级 (普通)' },
}

interface DrillConfig {
  title: string
  headline?: React.ReactNode
  formula?: string
  columns: ColumnsType<any>
  records: any[]
  onRowClick?: (r: any) => void
}

const PlanList: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [mrp, setMrp] = useState<any | null>(null)
  const [conflictMap, setConflictMap] = useState<Record<string, any>>({})
  const [form] = Form.useForm()

  // 追溯交互状态：统计下钻抽屉 / 计划详情
  const [drill, setDrill] = useState<DrillConfig | null>(null)
  const [detail, setDetail] = useState<any | null>(null)

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await listPlans(factory)
      setData(res.items || [])
    } catch {
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [factory])

  const submit = async () => {
    const v = await form.validateFields()
    await createPlan({
      factory_id: factory,
      product_id: v.product_id,
      quantity: v.quantity,
      required_date: v.required_date.format('YYYY-MM-DD'),
      customer_level: v.customer_level,
      priority: v.priority,
      sales_order_id: v.sales_order_id || undefined,
    })
    message.success('计划已创建')
    setOpen(false)
    form.resetFields()
    fetchData()
  }

  const doMrp = async (planId: string) => {
    try {
      const res = await calculateMrp(planId)
      setMrp(res)
      message.success('MRP 计算完成')
    } catch {
      message.error('MRP 计算失败')
    }
  }

  const doConflictCheck = async (planId: string) => {
    try {
      const res = await checkCapacityConflict(planId)
      setConflictMap(prev => ({ ...prev, [planId]: res }))
      if (res.has_conflict) {
        message.warning(`发现 ${res.conflicts?.length || 0} 个产能冲突`)
      } else {
        message.success('无产能冲突')
      }
    } catch {
      message.error('检查失败')
    }
  }

  const handleStatusAction = async (record: any, action: 'confirm' | 'release') => {
    try {
      if (action === 'confirm') {
        await confirmPlan(record.id)
        message.success('计划已确认')
      } else {
        await releasePlan(record.id)
        message.success('计划已下达')
      }
      fetchData()
    } catch {
      message.error('操作失败')
    }
  }

  const columns = [
    {
      title: '计划编号', dataIndex: 'plan_code', key: 'plan_code', width: 160,
      render: (v: string) => <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{v || '-'}</span>,
    },
    {
      title: '产品', dataIndex: 'product_id', key: 'product_id', width: 120,
      render: (v: string) => <Tag>{v || '-'}</Tag>,
    },
    {
      title: '数量', dataIndex: 'quantity', key: 'quantity', width: 90, align: 'right' as const,
      render: (v: number) => <span style={{ fontWeight: 600 }}>{v?.toLocaleString() ?? '-'}</span>,
    },
    {
      title: '需求日期', dataIndex: 'required_date', key: 'required_date', width: 120,
      render: (v: string) => {
        if (!v) return '-'
        const isOverdue = dayjs(v).isBefore(dayjs(), 'day')
        return <span style={{ color: isOverdue ? '#f5222d' : undefined, fontWeight: isOverdue ? 600 : undefined }}>{v}</span>
      },
    },
    {
      title: '客户等级', dataIndex: 'customer_level', key: 'customer_level', width: 110,
      render: (v: string) => {
        const m = customerLevelMap[v] || { color: 'default', text: v || '-' }
        return <Tag color={m.color}>{m.text}</Tag>
      },
    },
    {
      title: '优先级', dataIndex: 'priority', key: 'priority', width: 100,
      render: (v: number) => (
        <Space size={4}>
          <Progress
            percent={v || 0}
            size="small"
            style={{ width: 50 }}
            strokeColor={v >= 80 ? '#f5222d' : v >= 50 ? '#faad14' : '#52c41a'}
            showInfo={false}
          />
          <span style={{ fontSize: 12 }}>{v ?? '-'}</span>
        </Space>
      ),
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => {
        const m = statusMap[s] || { color: 'default', text: s }
        return <Tag color={m.color}>{m.text}</Tag>
      },
    },
    {
      title: '产能冲突', key: 'conflict', width: 80, align: 'center' as const,
      render: (_: any, r: any) => {
        const c = conflictMap[r.id]
        if (!c) return <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); doConflictCheck(r.id) }}>检查</Button>
        return c.has_conflict
          ? <Tooltip title={c.conflicts?.map((x: any) => x.message || JSON.stringify(x)).join('\n')}>
              <Badge count={c.conflicts?.length || 1} color="#f5222d" />
            </Tooltip>
          : <Tag color="success" style={{ fontSize: 11 }}>无</Tag>
      },
    },
    {
      title: '操作', key: 'action', width: 200, fixed: 'right' as const,
      render: (_: any, r: any) => (
        <Space size={4}>
          {r.status === 'draft' && (
            <Button type="link" size="small" icon={<CheckCircleOutlined />}
              onClick={(e) => { e.stopPropagation(); handleStatusAction(r, 'confirm') }}>确认</Button>
          )}
          {r.status === 'confirmed' && (
            <Button type="link" size="small" icon={<SendOutlined />}
              onClick={(e) => { e.stopPropagation(); handleStatusAction(r, 'release') }}>下达</Button>
          )}
          <Button type="link" size="small" icon={<CalculatorOutlined />}
            onClick={(e) => { e.stopPropagation(); doMrp(r.id) }}>MRP</Button>
        </Space>
      ),
    },
  ]

  const draftCount = data.filter(d => d.status === 'draft').length
  const confirmedCount = data.filter(d => d.status === 'confirmed').length
  const releasedCount = data.filter(d => d.status === 'released').length

  // ===== 追溯：计划详情字段（全字段）=====
  const detailFields: DetailField[] = [
    { label: '计划编号', key: 'plan_code', render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v || '-'}</span> },
    { label: '产品', key: 'product_id', render: (v: string) => v || '-' },
    { label: '数量', key: 'quantity', render: (v: number) => <span style={{ fontWeight: 600 }}>{v?.toLocaleString() ?? '-'}</span> },
    { label: '需求日期', key: 'required_date', render: (v: string) => v || '-' },
    { label: '客户等级', key: 'customer_level', render: (v: string) => { const m = customerLevelMap[v] || { color: 'default', text: v || '-' }; return <Tag color={m.color}>{m.text}</Tag> } },
    { label: '优先级', key: 'priority', render: (v: number) => v ?? '-' },
    { label: '状态', key: 'status', render: (s: string) => { const m = statusMap[s] || { color: 'default', text: s }; return <Tag color={m.color}>{m.text}</Tag> } },
    { label: '关联销售订单', key: 'sales_order_id', render: (v: string) => v || '-' },
    { label: '创建时间', key: 'created_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-') },
  ]

  // ===== 追溯：计划下钻共用列 =====
  const drillColumns: ColumnsType<any> = [
    { title: '计划编号', dataIndex: 'plan_code', key: 'code', width: 160, render: (v: string) => <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{v || '-'}</span> },
    { title: '产品', dataIndex: 'product_id', key: 'prod', width: 120, render: (v: string) => <Tag>{v || '-'}</Tag> },
    { title: '数量', dataIndex: 'quantity', key: 'qty', width: 90, align: 'right' as const, render: (v: number) => v?.toLocaleString() ?? '-' },
    { title: '需求日期', dataIndex: 'required_date', key: 'date', width: 110 },
    { title: '客户等级', dataIndex: 'customer_level', key: 'level', width: 110, render: (v: string) => { const m = customerLevelMap[v] || { color: 'default', text: v || '-' }; return <Tag color={m.color}>{m.text}</Tag> } },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (s: string) => { const m = statusMap[s] || { color: 'default', text: s }; return <Tag color={m.color}>{m.text}</Tag> } },
  ]

  // ===== 追溯：顶部 4 个统计的下钻配置 =====
  const statDrills = {
    draft: (): DrillConfig => ({
      title: '草稿计划 · 追溯',
      headline: `${draftCount} 个`,
      formula: `${draftCount} 草稿 / ${data.length} 总计划`,
      columns: drillColumns,
      records: data.filter(d => d.status === 'draft'),
      onRowClick: (r) => setDetail(r),
    }),
    confirmed: (): DrillConfig => ({
      title: '已确认计划 · 追溯',
      headline: `${confirmedCount} 个`,
      formula: `${confirmedCount} 已确认 / ${data.length} 总计划`,
      columns: drillColumns,
      records: data.filter(d => d.status === 'confirmed'),
      onRowClick: (r) => setDetail(r),
    }),
    released: (): DrillConfig => ({
      title: '已下达计划 · 追溯',
      headline: `${releasedCount} 个`,
      formula: `${releasedCount} 已下达 / ${data.length} 总计划`,
      columns: drillColumns,
      records: data.filter(d => d.status === 'released'),
      onRowClick: (r) => setDetail(r),
    }),
    total: (): DrillConfig => ({
      title: '全部计划 · 追溯',
      headline: `${data.length} 个`,
      formula: `草稿 ${draftCount} + 已确认 ${confirmedCount} + 已下达 ${releasedCount} = ${data.length}`,
      columns: drillColumns,
      records: data,
      onRowClick: (r) => setDetail(r),
    }),
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>生产计划 (MPS)</h2>
        <Space>
          <Input addonBefore="工厂" value={factory} onChange={(e) => setFactory(e.target.value)} style={{ width: 160 }} />
          <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>新建计划</Button>
        </Space>
      </div>

      {/* 统计卡 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small" hoverable onClick={() => setDrill(statDrills.draft())}><Statistic title="草稿" value={draftCount} valueStyle={{ color: '#999' }} /><div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div></Card></Col>
        <Col span={6}><Card size="small" hoverable onClick={() => setDrill(statDrills.confirmed())}><Statistic title="已确认" value={confirmedCount} valueStyle={{ color: '#1890ff' }} /><div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div></Card></Col>
        <Col span={6}><Card size="small" hoverable onClick={() => setDrill(statDrills.released())}><Statistic title="已下达" value={releasedCount} valueStyle={{ color: '#52c41a' }} /><div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div></Card></Col>
        <Col span={6}><Card size="small" hoverable onClick={() => setDrill(statDrills.total())}><Statistic title="总计" value={data.length} /><div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div></Card></Col>
      </Row>

      <Card>
        <Table
          rowKey={(r) => r.id || r.plan_code}
          columns={columns}
          dataSource={data}
          loading={loading}
          scroll={{ x: 1100 }}
          onRow={(r) => ({ onClick: () => setDetail(r), style: { cursor: 'pointer' } })}
          locale={{ emptyText: <Empty description="暂无计划，点击「新建计划」创建" /> }}
          pagination={{ pageSize: 10, showTotal: t => `共 ${t} 条` }}
        />
      </Card>

      {/* MRP 结果 */}
      {mrp && (
        <Card
          title={<span><CalculatorOutlined style={{ marginRight: 8 }} />MRP 计算结果</span>}
          style={{ marginTop: 16 }}
          extra={<Button type="link" onClick={() => setMrp(null)}>关闭</Button>}
        >
          <Descriptions column={3} size="small" style={{ marginBottom: 12 }}>
            <Descriptions.Item label="MRP ID"><span style={{ fontFamily: 'monospace' }}>{mrp.id}</span></Descriptions.Item>
            <Descriptions.Item label="状态"><Tag color="success">{mrp.status}</Tag></Descriptions.Item>
            <Descriptions.Item label="物料条目">{mrp.items?.length || 0}</Descriptions.Item>
          </Descriptions>
          {mrp.items?.some((i: any) => i.net_qty > 0) && (
            <Alert type="warning" showIcon icon={<WarningOutlined />}
              message="存在净需求缺口，建议生成采购订单"
              style={{ marginBottom: 12 }}
            />
          )}
          <Table
            size="small"
            rowKey={(r: any, i) => r.material_id || String(i)}
            dataSource={mrp.items || []}
            locale={{ emptyText: '无物料需求' }}
            columns={[
              { title: '物料', dataIndex: 'material_id', render: (v: string) => <Tag>{v}</Tag> },
              { title: '需求量', dataIndex: 'required_qty', align: 'right' as const },
              { title: '在库', dataIndex: 'on_hand_qty', align: 'right' as const },
              {
                title: '净需求', dataIndex: 'net_qty', align: 'right' as const,
                render: (v: number) => (
                  <span style={{ color: v > 0 ? '#f5222d' : '#52c41a', fontWeight: 600 }}>{v}</span>
                ),
              },
              {
                title: '建议采购', dataIndex: 'suggested_order_qty', align: 'right' as const,
                render: (v: number) => v > 0 ? <Tag color="orange">{v}</Tag> : '-',
              },
            ]}
          />
        </Card>
      )}

      {/* 新建计划 */}
      <Modal title="新建生产计划" open={open} onCancel={() => setOpen(false)} onOk={submit} destroyOnClose width={520}>
        <Form form={form} layout="vertical" initialValues={{ quantity: 1000, customer_level: 'b', priority: 50, required_date: dayjs().add(14, 'day') }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="产品ID" name="product_id" rules={[{ required: true, message: '请输入产品ID' }]}>
                <Input placeholder="PROD-xxx" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="数量" name="quantity" rules={[{ required: true }]}>
                <InputNumber min={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="需求日期" name="required_date" rules={[{ required: true }]}>
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="客户等级" name="customer_level">
                <Select options={[
                  { label: 'A 级 (战略客户)', value: 'a' },
                  { label: 'B 级 (重要客户)', value: 'b' },
                  { label: 'C 级 (普通客户)', value: 'c' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="优先级 (1-100)" name="priority">
                <InputNumber min={1} max={100} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="关联销售订单 (可选)" name="sales_order_id">
                <Input placeholder="SO-xxx" />
              </Form.Item>
            </Col>
          </Row>
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

      {/* 追溯：计划详情 */}
      <RecordDetailDrawer
        open={!!detail}
        onClose={() => setDetail(null)}
        title="生产计划详情"
        record={detail}
        fields={detailFields}
      />
    </div>
  )
}

export default PlanList
