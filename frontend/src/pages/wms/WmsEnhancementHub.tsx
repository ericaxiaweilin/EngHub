import React, { useCallback, useEffect, useState } from 'react'
import {
  Button, Card, Col, Form, Input, InputNumber, Row, Select, Space, Table, Tabs,
  Tag, message, Modal, Statistic, Progress,
} from 'antd'
import {
  AlertOutlined, ApiOutlined, BarcodeOutlined, BlockOutlined, ClusterOutlined,
  DatabaseOutlined, FileSearchOutlined, LockOutlined, ReloadOutlined, SwapOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { getActiveFactoryId } from '../../utils/factory'

const FACTORY = () => getActiveFactoryId('FAC_ELEC_DEMO_2026')
const enh = (path: string, opts?: any) => api.get(`/api/v1/wms/enhancement${path}`, opts)
const enhPost = (path: string, data?: any) => api.post(`/api/v1/wms/enhancement${path}`, data)
const enhPut = (path: string, data?: any) => api.put(`/api/v1/wms/enhancement${path}`, data)

// ========== 1 批次 ==========
const BatchPanel: React.FC = () => {
  const [expiring, setExpiring] = useState<any[]>([])
  const [invId, setInvId] = useState('')
  const load = useCallback(async () => {
    try {
      const res: any = await enh('/batch/expiring', { params: { factory_id: FACTORY(), within_days: 60 } })
      setExpiring(res.items || [])
    } catch { setExpiring([]) }
  }, [])
  useEffect(() => { load() }, [load])
  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Input placeholder="库存ID" value={invId} onChange={e => setInvId(e.target.value)} style={{ width: 280 }} />
        <Button onClick={async () => {
          if (!invId) return
          await enhPost(`/batch/${invId}/lock`, { reason: '质检冻结' })
          message.success('已锁定')
        }}>锁定批次</Button>
        <Button onClick={async () => {
          if (!invId) return
          await enhPost(`/batch/${invId}/unlock`)
          message.success('已解锁')
        }}>解锁</Button>
        <Button icon={<ReloadOutlined />} onClick={load}>刷新过期列表</Button>
      </Space>
      <Table size="small" rowKey="id" dataSource={expiring} pagination={{ pageSize: 8 }}
        columns={[
          { title: '物料', dataIndex: 'material_code' },
          { title: '批次', dataIndex: 'batch_code' },
          { title: '数量', dataIndex: 'total_qty', width: 80 },
          { title: '过期日', dataIndex: 'expiry_date', width: 110 },
          { title: '剩余天', dataIndex: 'days_left', width: 80, render: (v: number) => <Tag color={v <= 7 ? 'red' : 'gold'}>{v}</Tag> },
        ]} />
    </div>
  )
}

// ========== 2 库位 ==========
const LocationPanel: React.FC = () => {
  const [whId, setWhId] = useState('')
  const [items, setItems] = useState<any[]>([])
  const load = async () => {
    if (!whId) { message.warning('输入仓库ID'); return }
    const res: any = await enh('/locations', { params: { warehouse_id: whId } })
    setItems(res.items || [])
  }
  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Input placeholder="仓库ID" value={whId} onChange={e => setWhId(e.target.value)} />
        <Button type="primary" onClick={load}>查询库位</Button>
        <Button onClick={async () => {
          if (!whId) return
          await api.post('/api/v1/wms/enhancement/locations/sync-occupancy', null, { params: { warehouse_id: whId } })
          message.success('已同步占用状态'); load()
        }}>同步占用</Button>
      </Space>
      <Table size="small" rowKey="id" dataSource={items} pagination={{ pageSize: 10 }}
        columns={[
          { title: '库位', dataIndex: 'location_code' },
          { title: '排', dataIndex: 'row_num', width: 50 },
          { title: '列', dataIndex: 'col_num', width: 50 },
          { title: '层', dataIndex: 'level_num', width: 50 },
          { title: '容量', dataIndex: 'capacity', width: 70 },
          { title: '已用', dataIndex: 'used_qty', width: 70 },
          { title: '状态', dataIndex: 'occupancy_status', width: 90, render: (v: string) => {
            const c = v === 'occupied' ? 'blue' : v === 'locked' ? 'red' : 'green'
            return <Tag color={c}>{v || 'idle'}</Tag>
          }},
          { title: '利用率', dataIndex: 'utilization_pct', width: 120, render: (v: number) => v != null ? <Progress percent={Math.min(v, 100)} size="small" /> : '-' },
        ]} />
    </div>
  )
}

// ========== 3 预警 ==========
const AlertEnhPanel: React.FC = () => {
  const [alerts, setAlerts] = useState<any[]>([])
  const load = async () => {
    await api.post('/api/v1/wms/enhancement/alerts/run-full-check', null, { params: { factory_id: FACTORY() } })
    const res: any = await api.get('/api/v1/wms/alerts', { params: { factory_id: FACTORY() } })
    setAlerts(res.items || [])
  }
  useEffect(() => { load() }, [])
  const typeMap: Record<string, string> = {
    below_safety: '低库存', above_max: '超库存', dead_stock: '呆滞',
    slow_moving: '慢销', expiring: '即将过期',
  }
  return (
    <div>
      <Button icon={<ReloadOutlined />} onClick={load} style={{ marginBottom: 12 }}>运行全量预警检查</Button>
      <Table size="small" rowKey="id" dataSource={alerts} pagination={{ pageSize: 10 }}
        columns={[
          { title: '类型', dataIndex: 'alert_type', render: (v: string) => typeMap[v] || v },
          { title: '物料', dataIndex: 'material_code' },
          { title: '当前量', dataIndex: 'current_qty', width: 80 },
          { title: '严重度', dataIndex: 'severity', width: 80, render: (v: string) => <Tag color={v === 'critical' ? 'red' : 'orange'}>{v}</Tag> },
          { title: '状态', dataIndex: 'status', width: 80 },
        ]} />
    </div>
  )
}

// ========== 4 报表 ==========
const ReportPanel: React.FC = () => {
  const [turnover, setTurnover] = useState<any>(null)
  const [abc, setAbc] = useState<any>(null)
  const [cost, setCost] = useState<any>(null)
  const loadAll = async () => {
    const [t, c]: any[] = await Promise.all([
      enh('/reports/turnover', { params: { factory_id: FACTORY() } }),
      enh('/reports/cost', { params: { factory_id: FACTORY() } }),
    ])
    setTurnover(t)
    setCost(c)
    const a: any = await api.post('/api/v1/wms/enhancement/reports/abc', null, { params: { factory_id: FACTORY() } })
    setAbc(a)
  }
  useEffect(() => { loadAll() }, [])
  return (
    <div>
      <Button icon={<ReloadOutlined />} onClick={loadAll} style={{ marginBottom: 12 }}>刷新报表</Button>
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={8}><Card size="small"><Statistic title="平均周转率" value={turnover?.avg_turnover_rate ?? '-'} suffix="次/年" /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="ABC-A类" value={abc?.distribution?.A ?? 0} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="库存总成本" value={cost?.grand_total_cost ?? 0} prefix="¥" /></Card></Col>
      </Row>
      <Tabs size="small" items={[
        { key: 't', label: '周转率', children: <Table size="small" rowKey="material_code" dataSource={turnover?.items || []} pagination={{ pageSize: 8 }}
          columns={[{ title: '物料', dataIndex: 'material_code' }, { title: '在库', dataIndex: 'on_hand' }, { title: '出库', dataIndex: 'outbound_qty' }, { title: '周转率', dataIndex: 'turnover_rate' }]} /> },
        { key: 'a', label: 'ABC', children: <Table size="small" rowKey="material_code" dataSource={abc?.items || []} pagination={{ pageSize: 8 }}
          columns={[{ title: '物料', dataIndex: 'material_code' }, { title: '价值', dataIndex: 'value' }, { title: '分类', dataIndex: 'abc_class', render: (v: string) => <Tag color={v === 'A' ? 'red' : v === 'B' ? 'blue' : 'default'}>{v}</Tag> }]} /> },
        { key: 'c', label: '成本', children: <Table size="small" rowKey="warehouse_code" dataSource={cost?.warehouses || []} pagination={false}
          columns={[{ title: '仓库', dataIndex: 'warehouse_code' }, { title: '数量', dataIndex: 'total_qty' }, { title: '成本', dataIndex: 'total_cost' }]} /> },
      ]} />
    </div>
  )
}

// ========== 5 条码RFID ==========
const BarcodePanel: React.FC = () => {
  const [form] = Form.useForm()
  const [lastBc, setLastBc] = useState('')
  return (
    <Form form={form} layout="vertical" style={{ maxWidth: 480 }}>
      <Form.Item name="material_code" label="物料编码" rules={[{ required: true }]}><Input /></Form.Item>
      <Form.Item name="material_id" label="物料ID"><Input /></Form.Item>
      <Space>
        <Button type="primary" icon={<BarcodeOutlined />} onClick={async () => {
          const v = await form.validateFields()
          const res: any = await enhPost('/barcode/generate', { factory_id: FACTORY(), material_id: v.material_id || v.material_code, material_code: v.material_code })
          setLastBc(res.barcode); message.success(`条码: ${res.barcode}`)
        }}>生成条码</Button>
        {lastBc && <Tag>{lastBc}</Tag>}
      </Space>
      <Form.Item name="scan_qty" label="扫描入库数量" style={{ marginTop: 16 }}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
      <Form.Item name="warehouse_id" label="仓库ID"><Input /></Form.Item>
      <Button onClick={async () => {
        const v = form.getFieldsValue()
        if (!lastBc || !v.warehouse_id) { message.warning('先生成条码并填仓库'); return }
        await enhPost('/barcode/scan-inbound', { factory_id: FACTORY(), barcode: lastBc, quantity: v.scan_qty || 1, warehouse_id: v.warehouse_id })
        message.success('扫码入库成功')
      }}>扫码入库</Button>
      <Card size="small" title="RFID" style={{ marginTop: 16 }}>
        <Space>
          <Button onClick={async () => {
            const res: any = await enhPost('/rfid/count/start', { factory_id: FACTORY() })
            message.success(`RFID盘点会话 ${res.session_code}`)
          }}>启动RFID盘点</Button>
        </Space>
      </Card>
    </Form>
  )
}

// ========== 6 自动化 ==========
const AutomationPanel: React.FC = () => {
  const [jobs, setJobs] = useState<any[]>([])
  const load = async () => {
    const res: any = await enh('/automation/jobs', { params: { factory_id: FACTORY() } })
    setJobs(res.items || [])
  }
  useEffect(() => { load() }, [])
  const dispatch = async (job_type: string) => {
    await enhPost('/automation/dispatch', { factory_id: FACTORY(), job_type, material_code: 'MAT-DEMO', quantity: 1, source_location: 'A-01', target_location: 'B-02' })
    message.success(`${job_type} 任务已下发`); load()
  }
  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ApiOutlined />} onClick={() => dispatch('agv_dispatch')}>AGV调度</Button>
        <Button onClick={() => dispatch('stacker_move')}>堆垛机</Button>
        <Button onClick={() => dispatch('auto_sort')}>自动分拣</Button>
        <Button icon={<ReloadOutlined />} onClick={load} />
      </Space>
      <Table size="small" rowKey="id" dataSource={jobs} pagination={{ pageSize: 8 }}
        columns={[
          { title: '任务号', dataIndex: 'job_code' },
          { title: '类型', dataIndex: 'job_type' },
          { title: '状态', dataIndex: 'status', render: (v: string) => <Tag>{v}</Tag> },
          { title: '物料', dataIndex: 'material_code' },
        ]} />
    </div>
  )
}

// ========== 7 多仓 ==========
const MultiWhPanel: React.FC = () => {
  const [traceCode, setTraceCode] = useState('PCB-BOARD')
  const [trace, setTrace] = useState<any>(null)
  const [pools, setPools] = useState<any[]>([])
  useEffect(() => {
    enh('/pools', { params: { factory_id: FACTORY() } }).then((r: any) => setPools(r.items || []))
  }, [])
  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Input value={traceCode} onChange={e => setTraceCode(e.target.value)} placeholder="物料编码" />
        <Button icon={<FileSearchOutlined />} onClick={async () => {
          const res: any = await enh('/trace/cross-warehouse', { params: { factory_id: FACTORY(), material_code: traceCode } })
          setTrace(res)
        }}>跨仓追溯</Button>
      </Space>
      {trace && <Card size="small" title={`跨仓追溯 · ${traceCode}`} style={{ marginBottom: 12 }}>
        <p>分布仓库: {trace.warehouses?.length ?? 0} · 流水: {trace.transactions?.length ?? 0} · 调拨: {trace.transfers?.length ?? 0}</p>
      </Card>}
      <Table size="small" rowKey="id" dataSource={pools} pagination={false}
        columns={[{ title: '共享池', dataIndex: 'pool_code' }, { title: '物料', dataIndex: 'material_code' }, { title: '共享量', dataIndex: 'shared_qty' }]} />
    </div>
  )
}

// ========== 8 调拨审批 ==========
const TransferPanel: React.FC = () => {
  const [items, setItems] = useState<any[]>([])
  const [form] = Form.useForm()
  const load = async () => {
    const res: any = await enh('/transfers', { params: { factory_id: FACTORY() } })
    setItems(res.items || [])
  }
  useEffect(() => { load() }, [])
  return (
    <div>
      <Form form={form} layout="inline" style={{ marginBottom: 12 }}>
        <Form.Item name="material_code" rules={[{ required: true }]}><Input placeholder="物料编码" /></Form.Item>
        <Form.Item name="quantity" initialValue={10}><InputNumber min={1} /></Form.Item>
        <Form.Item name="from_wh" rules={[{ required: true }]}><Input placeholder="源仓库ID" /></Form.Item>
        <Form.Item name="to_wh" rules={[{ required: true }]}><Input placeholder="目标仓库ID" /></Form.Item>
        <Button type="primary" icon={<SwapOutlined />} onClick={async () => {
          const v = await form.validateFields()
          await enhPost('/transfers', {
            factory_id: FACTORY(), material_id: v.material_code, material_code: v.material_code,
            quantity: v.quantity, from_warehouse_id: v.from_wh, to_warehouse_id: v.to_wh, submit: true,
          })
          message.success('调拨申请已提交'); load()
        }}>提交调拨申请</Button>
      </Form>
      <Table size="small" rowKey="id" dataSource={items} pagination={{ pageSize: 8 }}
        columns={[
          { title: '单号', dataIndex: 'request_code' },
          { title: '物料', dataIndex: 'material_code' },
          { title: '数量', dataIndex: 'quantity', width: 70 },
          { title: '状态', dataIndex: 'status', render: (v: string) => <Tag>{v}</Tag> },
          { title: '操作', key: 'act', width: 140, render: (_: any, r: any) => r.status === 'pending' ? (
            <Space>
              <Button size="small" type="link" onClick={async () => { await enhPost(`/transfers/${r.id}/approve`); load() }}>批准</Button>
              <Button size="small" type="link" danger onClick={async () => { await enhPost(`/transfers/${r.id}/reject`, { reason: '库存不足' }); load() }}>驳回</Button>
            </Space>
          ) : null },
        ]} />
    </div>
  )
}

// ========== 9 冻结 ==========
const FreezePanel: React.FC = () => {
  const [items, setItems] = useState<any[]>([])
  const [invId, setInvId] = useState('')
  const load = async () => {
    const res: any = await enh('/freeze', { params: { factory_id: FACTORY(), status: 'active' } })
    setItems(res.items || [])
  }
  useEffect(() => { load() }, [])
  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Input placeholder="库存ID" value={invId} onChange={e => setInvId(e.target.value)} />
        <Button icon={<LockOutlined />} onClick={async () => {
          if (!invId) return
          await enhPost(`/freeze/${invId}`, { reason_code: 'QC_HOLD', reason_text: '质检待判', auto_unfreeze: false })
          message.success('已冻结'); load()
        }}>冻结</Button>
        <Button onClick={async () => {
          await api.post('/api/v1/wms/enhancement/freeze/auto-unfreeze', null, { params: { factory_id: FACTORY() } })
          message.success('自动解冻检查完成'); load()
        }}>自动解冻</Button>
      </Space>
      <Table size="small" rowKey="id" dataSource={items} pagination={{ pageSize: 8 }}
        columns={[
          { title: '物料', dataIndex: 'material_code' },
          { title: '原因', dataIndex: 'reason_code' },
          { title: '到期', dataIndex: 'freeze_until', width: 160 },
          { title: '操作', key: 'a', width: 80, render: (_: any, r: any) => (
            <Button size="small" type="link" onClick={async () => { await enhPost(`/freeze/${r.id}/release`); load() }}>解冻</Button>
          )},
        ]} />
    </div>
  )
}

// ========== 10 盘点差异 ==========
const VariancePanel: React.FC = () => {
  const [data, setData] = useState<any>(null)
  const [taskId, setTaskId] = useState('')
  const load = async () => {
    const res: any = await enh('/variance/analysis', { params: { factory_id: FACTORY(), task_id: taskId || undefined } })
    setData(res)
  }
  useEffect(() => { load() }, [])
  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Input placeholder="盘点任务ID(可选)" value={taskId} onChange={e => setTaskId(e.target.value)} />
        <Button icon={<ReloadOutlined />} onClick={load}>差异分析</Button>
        {taskId && <>
          <Button onClick={async () => { await enhPost(`/variance/cycle-count/${taskId}/submit`); message.success('已提交审批') }}>提交审批</Button>
          <Button type="primary" onClick={async () => { await enhPost(`/variance/cycle-count/${taskId}/approve`); message.success('已审批并调整'); load() }}>审批调整</Button>
        </>}
      </Space>
      {data && <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={8}><Statistic title="差异项" value={data.variance_count} /></Col>
        <Col span={8}><Statistic title="盘盈" value={data.gain_qty} valueStyle={{ color: '#52c41a' }} /></Col>
        <Col span={8}><Statistic title="盘亏" value={data.loss_qty} valueStyle={{ color: '#f5222d' }} /></Col>
      </Row>}
      <Table size="small" rowKey="id" dataSource={data?.items || []} pagination={{ pageSize: 8 }}
        columns={[
          { title: '任务', dataIndex: 'task_code' },
          { title: '物料', dataIndex: 'material_code' },
          { title: '系统', dataIndex: 'system_qty', width: 70 },
          { title: '实盘', dataIndex: 'counted_qty', width: 70 },
          { title: '差异', dataIndex: 'diff_qty', width: 70, render: (v: number) => <Tag color={v ? 'red' : 'green'}>{v}</Tag> },
        ]} />
    </div>
  )
}

const WmsEnhancementHub: React.FC = () => (
  <Tabs size="small" type="card" items={[
    { key: '1', label: <span><DatabaseOutlined /> 批次</span>, children: <BatchPanel /> },
    { key: '2', label: '库位', children: <LocationPanel /> },
    { key: '3', label: <span><AlertOutlined /> 预警</span>, children: <AlertEnhPanel /> },
    { key: '4', label: '报表', children: <ReportPanel /> },
    { key: '5', label: <span><BarcodeOutlined /> 条码RFID</span>, children: <BarcodePanel /> },
    { key: '6', label: <span><ApiOutlined /> 自动化</span>, children: <AutomationPanel /> },
    { key: '7', label: <span><ClusterOutlined /> 多仓</span>, children: <MultiWhPanel /> },
    { key: '8', label: <span><SwapOutlined /> 调拨审批</span>, children: <TransferPanel /> },
    { key: '9', label: <span><BlockOutlined /> 冻结</span>, children: <FreezePanel /> },
    { key: '10', label: '盘点差异', children: <VariancePanel /> },
  ]} />
)

export default WmsEnhancementHub
