import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Tabs, Table, Tag, Button, Space, Modal, Form, Input, InputNumber,
  Select, message, Popconfirm, Descriptions,
} from 'antd'
import { PlusOutlined, ReloadOutlined, EyeOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getStations, createStation, deleteStation,
  getRoutings, getRouting, deactivateRouting,
  getEquipment, createEquipment, updateEquipmentStatus,
  Station, Routing, Equipment,
} from '../../services/mes'
import { getStoredUser } from '../../services/auth'
import RecordDetailDrawer, { DetailField } from '../../components/trace/RecordDetailDrawer'
import { makeStationResolver, makeEquipmentResolver } from '../../components/trace/resolvers'

const { Option } = Select

const MOCK_STATIONS: any[] = [
  { id: 'st-1', station_code: 'ST-01', station_name: 'CNC加工工位', station_type: 'machining', status: 'active', factory_id: 'factory-sh-01' },
  { id: 'st-2', station_code: 'ST-02', station_name: '装配工位A', station_type: 'assembly', status: 'active', factory_id: 'factory-sh-01' },
  { id: 'st-3', station_code: 'ST-03', station_name: '焊接工位', station_type: 'welding', status: 'active', factory_id: 'factory-sh-01' },
  { id: 'st-4', station_code: 'ST-04', station_name: '检验工位', station_type: 'inspection', status: 'active', factory_id: 'factory-sh-01' },
]

const MOCK_ROUTINGS: any[] = [
  { id: 'rt-1', routing_code: 'RT-PRD001-V1', product_id: 'PRD-001', version: 'V1', steps_count: 5, is_active: true },
  { id: 'rt-2', routing_code: 'RT-PRD002-V1', product_id: 'PRD-002', version: 'V1', steps_count: 4, is_active: true },
  { id: 'rt-3', routing_code: 'RT-PRD003-V2', product_id: 'PRD-003', version: 'V2', steps_count: 6, is_active: true },
]

const MOCK_EQUIPMENT: any[] = [
  { id: 'eq-1', equipment_code: 'CNC-01', equipment_name: 'CNC加工中心-01', equipment_type: 'machining', status: 'running', station_id: 'st-1', factory_id: 'factory-sh-01' },
  { id: 'eq-2', equipment_code: 'CNC-02', equipment_name: 'CNC加工中心-02', equipment_type: 'machining', status: 'available', station_id: 'st-1', factory_id: 'factory-sh-01' },
  { id: 'eq-3', equipment_code: 'WLD-01', equipment_name: '焊接机器人-01', equipment_type: 'welding', status: 'maintenance', station_id: 'st-3', factory_id: 'factory-sh-01' },
  { id: 'eq-4', equipment_code: 'INJ-01', equipment_name: '注塑机-01', equipment_type: 'molding', status: 'running', station_id: 'st-2', factory_id: 'factory-sh-01' },
]

const EQUIPMENT_STATUS: Record<string, { color: string; text: string }> = {
  available: { color: 'success', text: '可用' },
  running: { color: 'processing', text: '运行中' },
  maintenance: { color: 'warning', text: '保养中' },
  fault: { color: 'error', text: '故障' },
  idle: { color: 'default', text: '空闲' },
}

// ============== 工位 Tab ==============
const StationTab: React.FC<{ factoryId: string }> = ({ factoryId }) => {
  const [data, setData] = useState<Station[]>([])
  const [loading, setLoading] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()
  const [equipment, setEquipment] = useState<Equipment[]>([])
  // 追溯：工位详情抽屉
  const [detail, setDetail] = useState<Station | null>(null)

  const fetch = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getStations({ factory_id: factoryId, page_size: 100 })
      const items = res.items || []
      setData(items)
    } catch { setData([]) } finally { setLoading(false) }
  }, [factoryId])

  useEffect(() => { fetch() }, [fetch])

  // 拉取设备用于关联设备可读化（equipment_ids → 设备编码+名称）
  useEffect(() => {
    getEquipment({ factory_id: factoryId, page_size: 100 })
      .then(res => setEquipment(res.items || []))
      .catch(() => {})
  }, [factoryId])

  const handleCreate = async (values: any) => {
    try {
      await createStation({ ...values, factory_id: factoryId })
      message.success('工位创建成功')
      setCreateOpen(false)
      form.resetFields()
      fetch()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '创建失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteStation(id)
      message.success('已删除')
      fetch()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '删除失败')
    }
  }

  // ===== 追溯：工位详情字段（含关联设备）=====
  const equipLabel = makeEquipmentResolver(equipment)
  const stationFields: DetailField[] = [
    { label: '工位编号', key: 'station_code' },
    { label: '名称', key: 'station_name' },
    { label: '类型', key: 'station_type', render: (v: string) => v || '-' },
    { label: '车间', key: 'workshop_id', render: (v: string) => v || '-' },
    { label: '产能/小时', key: 'capacity_per_hour', render: (v: number) => v ?? '-' },
    { label: '状态', key: 'status', render: (s: string) => <Tag color={s === 'active' ? 'success' : 'default'}>{s === 'active' ? '启用' : s}</Tag> },
    { label: '关联设备', key: 'equipment_ids', span: 2, render: (v: string[]) => (v && v.length > 0) ? v.map(id => equipLabel(id)).join('、') : '-' },
    { label: '创建时间', key: 'created_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-') },
  ]

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button size="small" icon={<ReloadOutlined />} onClick={fetch}>刷新</Button>
        <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建工位</Button>
      </Space>
      <Table
        rowKey="id" loading={loading} dataSource={data} size="small"
        onRow={(r) => ({ onClick: () => setDetail(r), style: { cursor: 'pointer' } })}
        columns={[
          { title: '工位编号', dataIndex: 'station_code', width: 120 },
          { title: '名称', dataIndex: 'station_name', width: 140 },
          { title: '类型', dataIndex: 'station_type', width: 100 },
          { title: '车间', dataIndex: 'workshop_id', width: 100, render: (v: string) => v || '-' },
          { title: '产能/小时', dataIndex: 'capacity_per_hour', width: 90 },
          { title: '设备数', dataIndex: 'equipment_ids', width: 70, render: (v: string[]) => (v || []).length },
          { title: '状态', dataIndex: 'status', width: 80, render: (s: string) => <Tag color={s === 'active' ? 'success' : 'default'}>{s === 'active' ? '启用' : s}</Tag> },
          {
            title: '操作', key: 'action', width: 80,
            render: (_: any, r: Station) => (
              <Popconfirm title="确定删除该工位？" onConfirm={() => handleDelete(r.id)}>
                <Button type="link" size="small" danger onClick={(e) => e.stopPropagation()}>删除</Button>
              </Popconfirm>
            ),
          },
        ]}
      />
      <Modal title="新建工位" open={createOpen} onCancel={() => setCreateOpen(false)} footer={null} width={480}>
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item label="工位编号" name="station_code" rules={[{ required: true }]}>
            <Input placeholder="如 SMT-01" />
          </Form.Item>
          <Form.Item label="工位名称" name="station_name" rules={[{ required: true }]}>
            <Input placeholder="如 SMT贴片线1号" />
          </Form.Item>
          <Form.Item label="类型" name="station_type" rules={[{ required: true }]}>
            <Select placeholder="选择类型">
              <Option value="smt">SMT</Option>
              <Option value="assembly">组装</Option>
              <Option value="testing">测试</Option>
              <Option value="packaging">包装</Option>
              <Option value="inspection">检验</Option>
            </Select>
          </Form.Item>
          <Form.Item label="产能/小时" name="capacity_per_hour" rules={[{ required: true }]}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="车间" name="workshop_id">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item><Button type="primary" htmlType="submit" block>创建</Button></Form.Item>
        </Form>
      </Modal>

      {/* 追溯：工位详情 */}
      <RecordDetailDrawer
        open={!!detail}
        onClose={() => setDetail(null)}
        title="工位详情"
        record={detail}
        fields={stationFields}
      />
    </>
  )
}

// ============== 工艺路线 Tab ==============
const RoutingTab: React.FC<{ factoryId: string }> = ({ factoryId }) => {
  const [data, setData] = useState<Routing[]>([])
  const [loading, setLoading] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detail, setDetail] = useState<Routing | null>(null)

  const fetch = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getRoutings({ factory_id: factoryId, page_size: 100 })
      const items = res.items || []
      setData(items)
    } catch { setData([]) } finally { setLoading(false) }
  }, [factoryId])

  useEffect(() => { fetch() }, [fetch])

  const showDetail = async (id: string) => {
    try {
      const res = await getRouting(id)
      setDetail(res)
      setDetailOpen(true)
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '获取详情失败')
    }
  }

  const handleDeactivate = async (id: string) => {
    try {
      await deactivateRouting(id)
      message.success('已停用')
      fetch()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '操作失败')
    }
  }

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button size="small" icon={<ReloadOutlined />} onClick={fetch}>刷新</Button>
      </Space>
      <Table
        rowKey="id" loading={loading} dataSource={data} size="small"
        columns={[
          { title: '路线编号', dataIndex: 'routing_code', width: 140 },
          { title: '产品', dataIndex: 'product_id', width: 120 },
          { title: '版本', dataIndex: 'version', width: 70 },
          { title: '工序数', dataIndex: 'steps_count', width: 70, render: (v: number, r: Routing) => v ?? (r.steps ? r.steps.length : '-') },
          { title: '状态', dataIndex: 'is_active', width: 80, render: (v: boolean) => <Tag color={v ? 'success' : 'default'}>{v ? '激活' : '停用'}</Tag> },
          {
            title: '操作', key: 'action', width: 140,
            render: (_: any, r: Routing) => (
              <Space size={4}>
                <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => showDetail(r.id)}>详情</Button>
                {r.is_active && (
                  <Popconfirm title="确定停用？" onConfirm={() => handleDeactivate(r.id)}>
                    <Button type="link" size="small" danger>停用</Button>
                  </Popconfirm>
                )}
              </Space>
            ),
          },
        ]}
      />
      <Modal title={`工艺路线: ${detail?.routing_code || ''}`} open={detailOpen} onCancel={() => setDetailOpen(false)} footer={null} width={640}>
        {detail && (
          <>
            <Descriptions size="small" column={3} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="产品">{detail.product_id}</Descriptions.Item>
              <Descriptions.Item label="版本">{detail.version}</Descriptions.Item>
              <Descriptions.Item label="状态">{detail.is_active ? '激活' : '停用'}</Descriptions.Item>
            </Descriptions>
            <Table
              rowKey={(s: any) => s.step_no}
              dataSource={detail.steps || []}
              size="small"
              pagination={false}
              columns={[
                { title: '步骤', dataIndex: 'step_no', width: 60 },
                { title: '工序名称', dataIndex: 'name' },
                { title: '工位', dataIndex: 'station_id', render: (v: string) => v || '-' },
                { title: '工时(分)', dataIndex: 'duration_min', render: (v: number) => v ?? '-' },
                { title: '说明', dataIndex: 'description', render: (v: string) => v || '-' },
              ]}
            />
          </>
        )}
      </Modal>
    </>
  )
}

// ============== 设备 Tab ==============
const EquipmentTab: React.FC<{ factoryId: string }> = ({ factoryId }) => {
  const [data, setData] = useState<Equipment[]>([])
  const [loading, setLoading] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [specOpen, setSpecOpen] = useState<Equipment | null>(null)
  const [form] = Form.useForm()
  const [stations, setStations] = useState<Station[]>([])
  // 追溯：设备详情抽屉
  const [detail, setDetail] = useState<Equipment | null>(null)

  const fetch = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getEquipment({ factory_id: factoryId, page_size: 100 })
      const items = res.items || []
      setData(items)
    } catch { setData([]) } finally { setLoading(false) }
  }, [factoryId])

  useEffect(() => { fetch() }, [fetch])

  // 拉取工位用于关联工位可读化（station_id → 工位编码+名称）
  useEffect(() => {
    getStations({ factory_id: factoryId, page_size: 100 })
      .then(res => setStations(res.items || []))
      .catch(() => {})
  }, [factoryId])

  const handleCreate = async (values: any) => {
    try {
      await createEquipment({ ...values, factory_id: factoryId })
      message.success('设备创建成功')
      setCreateOpen(false)
      form.resetFields()
      fetch()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '创建失败')
    }
  }

  const handleStatusChange = async (id: string, status: string) => {
    try {
      await updateEquipmentStatus(id, status)
      message.success('状态已更新')
      fetch()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '操作失败')
    }
  }

  // ===== 追溯：设备详情字段（spec/保养/关联工位）=====
  const stationLabel = makeStationResolver(stations)
  const equipFields: DetailField[] = [
    { label: '设备编号', key: 'equipment_code' },
    { label: '名称', key: 'equipment_name' },
    { label: '类型', key: 'equipment_type', render: (v: string) => v || '-' },
    { label: '当前状态', key: 'status', render: (s: string) => { const i = EQUIPMENT_STATUS[s] || { color: 'default', text: s }; return <Tag color={i.color}>{i.text}</Tag> } },
    { label: '关联工位', key: 'station_id', render: (v: string) => stationLabel(v) },
    { label: '上次保养', key: 'last_maintenance_date', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD') : '-') },
    { label: '下次保养', key: 'next_maintenance_date', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD') : '-') },
    { label: '规格参数', key: 'spec', span: 2, render: (v: Record<string, any>) => (v && Object.keys(v).length > 0) ? Object.entries(v).map(([k, val]) => `${k}: ${String(val)}`).join('、') : '-' },
    { label: '创建时间', key: 'created_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-') },
  ]

  return (
    <>
      <Space style={{ marginBottom: 12 }}>
        <Button size="small" icon={<ReloadOutlined />} onClick={fetch}>刷新</Button>
        <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建设备</Button>
      </Space>
      <Table
        rowKey="id" loading={loading} dataSource={data} size="small"
        onRow={(r) => ({ onClick: () => setDetail(r), style: { cursor: 'pointer' } })}
        columns={[
          { title: '设备编号', dataIndex: 'equipment_code', width: 120 },
          { title: '名称', dataIndex: 'equipment_name', width: 140 },
          { title: '类型', dataIndex: 'equipment_type', width: 100, render: (v: string) => v || '-' },
          { title: '所属工位', dataIndex: 'station_id', width: 100, render: (v: string) => v || '-' },
          {
            title: '状态', dataIndex: 'status', width: 90,
            render: (s: string) => { const info = EQUIPMENT_STATUS[s] || { color: 'default', text: s }; return <Tag color={info.color}>{info.text}</Tag> },
          },
          { title: '上次保养', dataIndex: 'last_maintenance_date', width: 100, render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD') : '-' },
          { title: '下次保养', dataIndex: 'next_maintenance_date', width: 100, render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD') : '-' },
          {
            title: '操作', key: 'action', width: 180,
            render: (_: any, r: Equipment) => (
              <Space size={4}>
                <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); setSpecOpen(r) }}>规格</Button>
                <span onClick={(e) => e.stopPropagation()}>
                  <Select size="small" value={r.status} style={{ width: 90 }} onChange={(v) => handleStatusChange(r.id, v)}>
                    <Option value="available">可用</Option>
                    <Option value="running">运行中</Option>
                    <Option value="maintenance">保养中</Option>
                    <Option value="fault">故障</Option>
                  </Select>
                </span>
              </Space>
            ),
          },
        ]}
      />
      <Modal title="新建设备" open={createOpen} onCancel={() => setCreateOpen(false)} footer={null} width={480}>
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item label="设备编号" name="equipment_code" rules={[{ required: true }]}>
            <Input placeholder="如 EQ-SMT-001" />
          </Form.Item>
          <Form.Item label="设备名称" name="equipment_name" rules={[{ required: true }]}>
            <Input placeholder="如 贴片机Yamaha YS12" />
          </Form.Item>
          <Form.Item label="类型" name="equipment_type">
            <Select placeholder="选择类型" allowClear>
              <Option value="smt">SMT设备</Option>
              <Option value="assembly">组装设备</Option>
              <Option value="testing">测试设备</Option>
              <Option value="auxiliary">辅助设备</Option>
            </Select>
          </Form.Item>
          <Form.Item label="所属工位" name="station_id">
            <Input placeholder="可选，工位编码" />
          </Form.Item>
          <Form.Item><Button type="primary" htmlType="submit" block>创建</Button></Form.Item>
        </Form>
      </Modal>
      <Modal title={`设备规格: ${specOpen?.equipment_code || ''}`} open={!!specOpen} onCancel={() => setSpecOpen(null)} footer={null}>
        {specOpen && (
          Object.keys(specOpen.spec || {}).length > 0 ? (
            <Descriptions size="small" column={1} bordered>
              {Object.entries(specOpen.spec).map(([k, v]) => (
                <Descriptions.Item key={k} label={k}>{String(v)}</Descriptions.Item>
              ))}
            </Descriptions>
          ) : <p style={{ color: '#999' }}>暂无规格参数</p>
        )}
      </Modal>

      {/* 追溯：设备详情 */}
      <RecordDetailDrawer
        open={!!detail}
        onClose={() => setDetail(null)}
        title="设备详情"
        record={detail}
        fields={equipFields}
      />
    </>
  )
}

// ============== 主页面 ==============
const BaseData: React.FC = () => {
  const user = getStoredUser()
  const factoryId = localStorage.getItem('active_factory_id') || user?.factory_id || 'F01'

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>基础数据</h2>
      <Card>
        <Tabs
          items={[
            { key: 'station', label: '工位', children: <StationTab factoryId={factoryId} /> },
            { key: 'routing', label: '工艺路线', children: <RoutingTab factoryId={factoryId} /> },
            { key: 'equipment', label: '设备', children: <EquipmentTab factoryId={factoryId} /> },
          ]}
        />
      </Card>
    </div>
  )
}

export default BaseData
