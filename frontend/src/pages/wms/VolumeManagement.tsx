import React, { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Col, Form, Input, InputNumber, Modal, Progress, Row, Select,
  Space, Statistic, Table, Tabs, Tag, message,
} from 'antd'
import {
  CalculatorOutlined, DatabaseOutlined, EditOutlined, PlusOutlined,
  ReloadOutlined, SendOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { getActiveFactoryId } from '../../utils/factory'

const CONTAINER_OPTIONS = [
  { value: '20GP', label: '20GP (29.7 m³)' },
  { value: '40GP', label: '40GP (52.2 m³)' },
  { value: '40HQ', label: '40HQ (60.9 m³)' },
]

function fmtNum(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return '-'
  return Number(value).toFixed(digits)
}

function useFactoryId() {
  return getActiveFactoryId('FAC_ELEC_DEMO_2026')
}

// ============== 库存体积汇总 ==============
const SummaryPanel: React.FC = () => {
  const factoryId = useFactoryId()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<any>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/wms/volume/summary', {
        params: { factory_id: factoryId },
      })
      setData(res)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '加载体积汇总失败')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [factoryId])

  useEffect(() => { load() }, [load])

  const columns: ColumnsType<any> = [
    { title: '物料编码', dataIndex: 'material_code', width: 140 },
    { title: '物料名称', dataIndex: 'material_name', ellipsis: true },
    { title: '库存数量', dataIndex: 'qty', width: 90, align: 'right' },
    {
      title: '单件体积(m³)', dataIndex: 'unit_volume_m3', width: 110, align: 'right',
      render: (v: number) => (v > 0 ? fmtNum(v, 4) : <Tag>未维护</Tag>),
    },
    {
      title: '单件重量(kg)', dataIndex: 'unit_weight_kg', width: 110, align: 'right',
      render: (v: number) => (v > 0 ? fmtNum(v, 2) : '-'),
    },
    {
      title: '总体积(m³)', dataIndex: 'total_volume_m3', width: 110, align: 'right',
      render: (v: number) => fmtNum(v, 4),
    },
    {
      title: '总重量(kg)', dataIndex: 'total_weight_kg', width: 110, align: 'right',
      render: (v: number) => fmtNum(v, 2),
    },
  ]

  return (
    <div>
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="SKU 数" value={data?.sku_count ?? 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="库存总量" value={data?.total_qty ?? 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="总体积 (m³)" value={fmtNum(data?.total_volume_m3, 4)} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="缺体积参数"
              value={data?.missing_volume_spec_count ?? 0}
              valueStyle={{ color: (data?.missing_volume_spec_count ?? 0) > 0 ? '#faad14' : '#52c41a' }}
            />
          </Card>
        </Col>
      </Row>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Table
        rowKey="material_code"
        size="small"
        loading={loading}
        dataSource={data?.items || []}
        columns={columns}
        pagination={{ pageSize: 10 }}
      />
    </div>
  )
}

// ============== 体积参数维护 ==============
const SpecPanel: React.FC = () => {
  const factoryId = useFactoryId()
  const [form] = Form.useForm()
  const [editForm] = Form.useForm()
  const [modalOpen, setModalOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [pickCodeOpen, setPickCodeOpen] = useState(false)
  const [pickCode, setPickCode] = useState('')
  const [editingCode, setEditingCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [lastResult, setLastResult] = useState<any>(null)

  const handleCreate = async () => {
    const vals = await form.validateFields()
    setSubmitting(true)
    try {
      const res: any = await api.post('/api/v1/wms/volume/track', {
        factory_id: factoryId,
        ...vals,
      })
      message.success(`已记录 ${vals.material_code} 体积参数`)
      setLastResult(res)
      setModalOpen(false)
      form.resetFields()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '保存失败')
    } finally {
      setSubmitting(false)
    }
  }

  const openEdit = (code: string) => {
    setEditingCode(code)
    editForm.setFieldsValue({ material_code: code })
    setEditOpen(true)
  }

  const handleUpdate = async () => {
    const vals = await editForm.validateFields()
    setSubmitting(true)
    try {
      const res: any = await api.put(`/api/v1/wms/volume/material/${encodeURIComponent(editingCode)}`, {
        factory_id: factoryId,
        length_cm: vals.length_cm,
        width_cm: vals.width_cm,
        height_cm: vals.height_cm,
        unit_weight_kg: vals.unit_weight_kg,
        material_name: vals.material_name,
      })
      message.success(`已更新 ${editingCode}`)
      setLastResult(res)
      setEditOpen(false)
      editForm.resetFields()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '更新失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          录入体积参数
        </Button>
        <Button icon={<EditOutlined />} onClick={() => { setPickCode(''); setPickCodeOpen(true) }}>
          更新已有参数
        </Button>
      </Space>

      {lastResult && (
        <Card size="small" title="最近一次操作结果" style={{ marginBottom: 12 }}>
          <Row gutter={12}>
            <Col span={6}><Statistic title="物料" value={lastResult.material_code} /></Col>
            <Col span={6}><Statistic title="单件体积(m³)" value={fmtNum(lastResult.unit_volume_m3, 4)} /></Col>
            <Col span={6}><Statistic title="单件重量(kg)" value={fmtNum(lastResult.unit_weight_kg, 2)} /></Col>
            <Col span={6}><Statistic title="库存占用体积(m³)" value={fmtNum(lastResult.total_volume_m3, 4)} /></Col>
          </Row>
        </Card>
      )}

      <Modal
        title="选择要更新的物料"
        open={pickCodeOpen}
        onOk={() => {
          const code = pickCode.trim()
          if (!code) {
            message.warning('请输入物料编码')
            return
          }
          setPickCodeOpen(false)
          openEdit(code)
        }}
        onCancel={() => setPickCodeOpen(false)}
      >
        <Input
          placeholder="物料编码"
          value={pickCode}
          onChange={(e) => setPickCode(e.target.value)}
        />
      </Modal>

      <Modal
        title="录入物料体积参数"
        open={modalOpen}
        onOk={handleCreate}
        confirmLoading={submitting}
        onCancel={() => setModalOpen(false)}
        width={520}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="material_code" label="物料编码" rules={[{ required: true }]}>
            <Input placeholder="如 PCB-BOARD" />
          </Form.Item>
          <Form.Item name="material_name" label="物料名称">
            <Input placeholder="可选" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="length_cm" label="长(cm)" rules={[{ required: true }]}>
                <InputNumber min={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="width_cm" label="宽(cm)" rules={[{ required: true }]}>
                <InputNumber min={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="height_cm" label="高(cm)" rules={[{ required: true }]}>
                <InputNumber min={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="unit_weight_kg" label="单件重量(kg)">
            <InputNumber min={0} step={0.01} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="quantity" label="计算用量(留空则按库存)" tooltip="不填则自动汇总当前库存数量">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`更新体积参数 · ${editingCode}`}
        open={editOpen}
        onOk={handleUpdate}
        confirmLoading={submitting}
        onCancel={() => setEditOpen(false)}
        width={520}
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="material_name" label="物料名称">
            <Input />
          </Form.Item>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="length_cm" label="长(cm)">
                <InputNumber min={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="width_cm" label="宽(cm)">
                <InputNumber min={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="height_cm" label="高(cm)">
                <InputNumber min={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="unit_weight_kg" label="单件重量(kg)">
            <InputNumber min={0} step={0.01} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ============== 发运装柜计算 ==============
const ShippingPanel: React.FC = () => {
  const factoryId = useFactoryId()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<any>(null)

  const handleCalc = async () => {
    const vals = await form.validateFields()
    const lines = (vals.lines || []).filter((l: any) => l?.material_code && l?.quantity > 0)
    if (!lines.length) {
      message.warning('请至少添加一行发运明细')
      return
    }
    setLoading(true)
    try {
      const res: any = await api.post('/api/v1/wms/volume/shipping', {
        factory_id: factoryId,
        container_type: vals.container_type || '40HQ',
        lines,
      })
      setResult(res)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '计算失败')
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const lineColumns: ColumnsType<any> = [
    { title: '物料编码', dataIndex: 'material_code' },
    { title: '数量', dataIndex: 'quantity', width: 80, align: 'right' },
    { title: '单件体积(m³)', dataIndex: 'unit_volume_m3', width: 120, align: 'right', render: (v) => fmtNum(v, 4) },
    { title: '行体积(m³)', dataIndex: 'total_volume_m3', width: 120, align: 'right', render: (v) => fmtNum(v, 4) },
    { title: '行重量(kg)', dataIndex: 'total_weight_kg', width: 120, align: 'right', render: (v) => fmtNum(v, 2) },
  ]

  return (
    <div>
      <Form form={form} layout="vertical" initialValues={{ container_type: '40HQ', lines: [{ material_code: '', quantity: 1 }] }}>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="container_type" label="集装箱规格">
              <Select options={CONTAINER_OPTIONS} />
            </Form.Item>
          </Col>
          <Col span={16} style={{ display: 'flex', alignItems: 'flex-end' }}>
            <Button type="primary" icon={<CalculatorOutlined />} loading={loading} onClick={handleCalc}>
              计算装柜需求
            </Button>
          </Col>
        </Row>
        <Form.List name="lines">
          {(fields, { add, remove }) => (
            <>
              {fields.map(({ key, name, ...rest }) => (
                <Row key={key} gutter={8} align="middle">
                  <Col span={8}>
                    <Form.Item {...rest} name={[name, 'material_code']} rules={[{ required: true, message: '必填' }]}>
                      <Input placeholder="物料编码" />
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item {...rest} name={[name, 'quantity']} rules={[{ required: true }]}>
                      <InputNumber min={1} style={{ width: '100%' }} placeholder="数量" />
                    </Form.Item>
                  </Col>
                  <Col span={3}>
                    <Form.Item {...rest} name={[name, 'length_cm']}><InputNumber min={0} placeholder="长cm" style={{ width: '100%' }} /></Form.Item>
                  </Col>
                  <Col span={3}>
                    <Form.Item {...rest} name={[name, 'width_cm']}><InputNumber min={0} placeholder="宽cm" style={{ width: '100%' }} /></Form.Item>
                  </Col>
                  <Col span={3}>
                    <Form.Item {...rest} name={[name, 'height_cm']}><InputNumber min={0} placeholder="高cm" style={{ width: '100%' }} /></Form.Item>
                  </Col>
                  <Col span={2}>
                    <Button type="link" danger onClick={() => remove(name)} disabled={fields.length <= 1}>删</Button>
                  </Col>
                </Row>
              ))}
              <Button type="dashed" onClick={() => add({ material_code: '', quantity: 1 })} block icon={<PlusOutlined />}>
                添加发运行
              </Button>
            </>
          )}
        </Form.List>
      </Form>

      {result && (
        <Card size="small" title="装柜计算结果" style={{ marginTop: 16 }}>
          <Row gutter={12} style={{ marginBottom: 12 }}>
            <Col span={6}><Statistic title="总体积(m³)" value={fmtNum(result.total_volume_m3, 4)} /></Col>
            <Col span={6}><Statistic title="总重量(kg)" value={fmtNum(result.total_weight_kg, 2)} /></Col>
            <Col span={6}><Statistic title="所需柜数" value={result.containers_needed} suffix="柜" /></Col>
            <Col span={6}>
              <Statistic
                title="容积利用率"
                value={fmtNum(result.volume_utilization_pct, 1)}
                suffix="%"
              />
            </Col>
          </Row>
          <Table
            rowKey="material_code"
            size="small"
            dataSource={result.lines || []}
            columns={lineColumns}
            pagination={false}
          />
        </Card>
      )}
    </div>
  )
}

// ============== 空间利用率 ==============
const SpacePanel: React.FC = () => {
  const factoryId = useFactoryId()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<any>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/wms/volume/space-utilization', {
        params: { factory_id: factoryId },
      })
      setData(res)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '加载空间利用率失败')
      setData(null)
    } finally {
      setLoading(false)
    }
  }, [factoryId])

  useEffect(() => { load() }, [load])

  const columns: ColumnsType<any> = [
    { title: '仓库编码', dataIndex: 'warehouse_code', width: 120 },
    { title: '仓库名称', dataIndex: 'warehouse_name', ellipsis: true },
    {
      title: '容量(m³)', dataIndex: 'capacity_m3', width: 100, align: 'right',
      render: (v: number) => (v > 0 ? fmtNum(v, 2) : <Tag>未设置</Tag>),
    },
    {
      title: '已用(m³)', dataIndex: 'used_volume_m3', width: 100, align: 'right',
      render: (v: number) => fmtNum(v, 4),
    },
    {
      title: '利用率', dataIndex: 'utilization_pct', width: 180,
      render: (v: number | null) => (
        v != null && v >= 0
          ? <Progress percent={Math.min(v, 100)} size="small" status={v >= 90 ? 'exception' : 'normal'} />
          : <Tag>待维护容量</Tag>
      ),
    },
    {
      title: '库位容量(件)', dataIndex: 'location_capacity_units', width: 110, align: 'right',
    },
  ]

  return (
    <div>
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={8}>
          <Card size="small">
            <Statistic title="仓库数" value={data?.warehouse_count ?? 0} prefix={<DatabaseOutlined />} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic title="总容量(m³)" value={fmtNum(data?.total_capacity_m3, 2)} />
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small">
            <Statistic
              title="整体利用率"
              value={data?.overall_utilization_pct != null ? fmtNum(data.overall_utilization_pct, 1) : '-'}
              suffix={data?.overall_utilization_pct != null ? '%' : undefined}
            />
          </Card>
        </Col>
      </Row>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
      </Space>
      <Table
        rowKey="warehouse_id"
        size="small"
        loading={loading}
        dataSource={data?.warehouses || []}
        columns={columns}
        pagination={false}
      />
    </div>
  )
}

const VolumeManagement: React.FC = () => (
  <Tabs
    size="small"
    defaultActiveKey="summary"
    items={[
      { key: 'summary', label: '库存体积汇总', children: <SummaryPanel /> },
      { key: 'spec', label: '体积参数', children: <SpecPanel /> },
      { key: 'shipping', label: <span><SendOutlined /> 发运装柜</span>, children: <ShippingPanel /> },
      { key: 'space', label: '空间利用率', children: <SpacePanel /> },
    ]}
  />
)

export default VolumeManagement
