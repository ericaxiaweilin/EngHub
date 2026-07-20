import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, InputNumber,
  Select, DatePicker, message, Descriptions, Empty,
} from 'antd'
import { PlusOutlined, CalculatorOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { listPlans, createPlan, confirmPlan, releasePlan, calculateMrp } from '../../services/modules'

const statusMap: Record<string, { color: string; text: string }> = {
  draft: { color: 'default', text: '草稿' },
  confirmed: { color: 'processing', text: '已确认' },
  released: { color: 'success', text: '已下达' },
}

const PlanList: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [mrp, setMrp] = useState<any | null>(null)
  const [form] = Form.useForm()

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
    })
    message.success('计划已创建')
    setOpen(false)
    form.resetFields()
    fetchData()
  }

  const doMrp = async (planId: string) => {
    const res = await calculateMrp(planId)
    setMrp(res)
    message.success('MRP 计算完成')
  }

  const columns = [
    { title: '计划编号', dataIndex: 'plan_code', key: 'plan_code', render: (v: string) => v || '-' },
    { title: '产品', dataIndex: 'product_id', key: 'product_id' },
    { title: '数量', dataIndex: 'quantity', key: 'quantity' },
    { title: '需求日期', dataIndex: 'required_date', key: 'required_date' },
    { title: '优先级', dataIndex: 'priority', key: 'priority' },
    {
      title: '状态', dataIndex: 'status', key: 'status',
      render: (s: string) => { const m = statusMap[s] || { color: 'default', text: s }; return <Tag color={m.color}>{m.text}</Tag> },
    },
    {
      title: '操作', key: 'action',
      render: (_: any, r: any) => (
        <Space>
          <Button type="link" size="small" onClick={async () => { await confirmPlan(r.id); message.success('已确认'); fetchData() }}>确认</Button>
          <Button type="link" size="small" onClick={async () => { await releasePlan(r.id); message.success('已下达'); fetchData() }}>下达</Button>
          <Button type="link" size="small" icon={<CalculatorOutlined />} onClick={() => doMrp(r.id)}>MRP</Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>生产计划 (MPS)</h2>
        <Space>
          <Input addonBefore="工厂" value={factory} onChange={(e) => setFactory(e.target.value)} style={{ width: 160 }} />
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>新建计划</Button>
        </Space>
      </div>

      <Card>
        <Table
          rowKey={(r) => r.id || r.plan_code}
          columns={columns}
          dataSource={data}
          loading={loading}
          locale={{ emptyText: <Empty description="暂无计划，点击「新建计划」创建" /> }}
        />
      </Card>

      {mrp && (
        <Card title="MRP 计算结果" style={{ marginTop: 16 }} extra={<Button type="link" onClick={() => setMrp(null)}>关闭</Button>}>
          <Descriptions column={3} size="small" style={{ marginBottom: 12 }}>
            <Descriptions.Item label="MRP ID">{mrp.id}</Descriptions.Item>
            <Descriptions.Item label="状态"><Tag color="success">{mrp.status}</Tag></Descriptions.Item>
            <Descriptions.Item label="物料条目">{mrp.items?.length || 0}</Descriptions.Item>
          </Descriptions>
          <Table
            size="small"
            rowKey={(r: any, i) => r.material_id || String(i)}
            dataSource={mrp.items || []}
            locale={{ emptyText: '无物料需求' }}
            columns={[
              { title: '物料', dataIndex: 'material_id' },
              { title: '需求量', dataIndex: 'required_qty' },
              { title: '在库', dataIndex: 'on_hand_qty' },
              { title: '净需求', dataIndex: 'net_qty' },
              { title: '建议采购', dataIndex: 'suggested_order_qty' },
            ]}
          />
        </Card>
      )}

      <Modal title="新建生产计划" open={open} onCancel={() => setOpen(false)} onOk={submit} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={{ quantity: 1000, customer_level: 'b', priority: 50, required_date: dayjs().add(14, 'day') }}>
          <Form.Item label="产品ID" name="product_id" rules={[{ required: true }]}><Input placeholder="PROD-xxx" /></Form.Item>
          <Form.Item label="数量" name="quantity" rules={[{ required: true }]}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          <Form.Item label="需求日期" name="required_date" rules={[{ required: true }]}><DatePicker style={{ width: '100%' }} /></Form.Item>
          <Form.Item label="客户等级" name="customer_level"><Select options={[{ label: 'A 级', value: 'a' }, { label: 'B 级', value: 'b' }, { label: 'C 级', value: 'c' }]} /></Form.Item>
          <Form.Item label="优先级" name="priority"><InputNumber min={1} max={100} style={{ width: '100%' }} /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default PlanList
