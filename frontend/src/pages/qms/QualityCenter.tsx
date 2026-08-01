import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Tabs, Table, Button, Tag, Space, Row, Col, Statistic, Modal, Form,
  Input, InputNumber, Select, message, Empty, Spin, Descriptions, Progress, Drawer,
} from 'antd'
import {
  LineChartOutlined, FileProtectOutlined,
  DashboardOutlined, PlusOutlined,
} from '@ant-design/icons'
import api from '../../services/api'
import { getStoredUser } from '../../services/auth'
import { Line } from '@ant-design/charts'

const getFactory = () => localStorage.getItem('active_factory_id') || getStoredUser()?.factory_id || 'FAC_ELEC_DEMO_2026'

// ============== SPC 控制图组件 (Xbar + MR 组合图) ==============
const SpcControlChart: React.FC<{ points: any[]; characteristicName?: string }> = ({ points, characteristicName }) => {
  const [selected, setSelected] = useState<any>(null)
  if (!points?.length) return <Empty />

  const ucl = points[0]?.ucl ?? 1
  const cl = points[0]?.cl ?? 0
  const lcl = points[0]?.lcl ?? 0
  const sigma = (ucl - cl) / 3 || 1

  // 计算移动极差 (MR)
  const mrData = points.map((p: any, i: number) => {
    const val = p.value ?? p.measured_value ?? 0
    const prev = i > 0 ? (points[i - 1].value ?? points[i - 1].measured_value ?? 0) : val
    return { index: i + 1, mr: Math.abs(val - prev), ooc: p.is_out_of_control }
  })
  const mrCl = mrData.slice(1).reduce((s, d) => s + d.mr, 0) / Math.max(mrData.length - 1, 1)
  const mrUcl = mrCl * 3.267 // D4 for n=2

  // Xbar 图数据
  const xbarData = points.map((p: any, i: number) => ({
    index: i + 1,
    value: p.value ?? p.measured_value ?? 0,
    type: p.is_out_of_control ? '异常点' : '受控点',
    raw: p,
  }))

  // 过程能力
  const values = points.map((p: any) => p.value ?? p.measured_value ?? 0)
  const mean = values.reduce((a, b) => a + b, 0) / values.length
  const std = Math.sqrt(values.reduce((s, v) => s + (v - mean) ** 2, 0) / values.length) || 0.001
  const cp = ((ucl - lcl) / (6 * sigma)).toFixed(2)
  const cpk = (Math.min(ucl - mean, mean - lcl) / (3 * sigma)).toFixed(2)

  const xbarConfig: any = {
    data: xbarData,
    xField: 'index',
    yField: 'value',
    colorField: 'type',
    scale: { color: { range: ['#1890ff', '#f5222d'] } },
    axis: { x: { title: false }, y: { title: 'Xbar' } },
    style: { lineWidth: 2 },
    point: {
      shapeField: 'point',
      sizeField: (d: any) => d.type === '异常点' ? 5 : 3,
      style: (d: any) => ({ fill: d.type === '异常点' ? '#f5222d' : '#1890ff', stroke: '#fff', lineWidth: 1, cursor: 'pointer' }),
    },
    annotations: [
      { type: 'lineY', yField: ucl, style: { stroke: '#f5222d', lineWidth: 1.5, lineDash: [6, 3] }, label: { text: `UCL=${ucl.toFixed(3)}`, position: 'right', style: { fill: '#f5222d', fontSize: 10 } } },
      { type: 'lineY', yField: cl, style: { stroke: '#52c41a', lineWidth: 1.5, lineDash: [4, 2] }, label: { text: `CL=${cl.toFixed(3)}`, position: 'right', style: { fill: '#52c41a', fontSize: 10 } } },
      { type: 'lineY', yField: lcl, style: { stroke: '#f5222d', lineWidth: 1.5, lineDash: [6, 3] }, label: { text: `LCL=${lcl.toFixed(3)}`, position: 'right', style: { fill: '#f5222d', fontSize: 10 } } },
      { type: 'rangeY', yField: [cl + sigma, cl + 2 * sigma], style: { fill: '#fffbe6', opacity: 0.3 } },
      { type: 'rangeY', yField: [cl - 2 * sigma, cl - sigma], style: { fill: '#fffbe6', opacity: 0.3 } },
      { type: 'rangeY', yField: [cl + 2 * sigma, ucl], style: { fill: '#fff1f0', opacity: 0.2 } },
      { type: 'rangeY', yField: [lcl, cl - 2 * sigma], style: { fill: '#fff1f0', opacity: 0.2 } },
    ],
    tooltip: { title: (d: any) => `样本 #${d.index}`, items: [{ channel: 'y', name: '测量值' }] },
    height: 220,
    onReady: ({ chart }: any) => {
      chart.on('point:click', (ev: any) => {
        const idx = ev.data?.data?.index
        if (idx) setSelected(points[idx - 1])
      })
    },
  }

  const mrConfig: any = {
    data: mrData,
    xField: 'index',
    yField: 'mr',
    axis: { x: { title: '样本组' }, y: { title: 'MR' } },
    style: { lineWidth: 1.5, stroke: '#722ed1' },
    point: {
      shapeField: 'point',
      sizeField: 2,
      style: (d: any) => ({ fill: d.mr > mrUcl ? '#f5222d' : '#722ed1', stroke: '#fff', lineWidth: 1 }),
    },
    annotations: [
      { type: 'lineY', yField: mrUcl, style: { stroke: '#f5222d', lineWidth: 1, lineDash: [6, 3] }, label: { text: `UCL=${mrUcl.toFixed(3)}`, position: 'right', style: { fill: '#f5222d', fontSize: 9 } } },
      { type: 'lineY', yField: mrCl, style: { stroke: '#52c41a', lineWidth: 1, lineDash: [4, 2] }, label: { text: `CL=${mrCl.toFixed(3)}`, position: 'right', style: { fill: '#52c41a', fontSize: 9 } } },
    ],
    tooltip: { title: (d: any) => `样本 #${d.index}`, items: [{ channel: 'y', name: '移动极差' }] },
    height: 130,
  }

  return (
    <div>
      {/* 过程能力指标 */}
      <Row gutter={12} style={{ marginBottom: 8 }}>
        <Col span={6}><Statistic title="Cp" value={cp} valueStyle={{ fontSize: 14, color: Number(cp) >= 1.33 ? '#52c41a' : '#f5222d' }} /></Col>
        <Col span={6}><Statistic title="Cpk" value={cpk} valueStyle={{ fontSize: 14, color: Number(cpk) >= 1.33 ? '#52c41a' : '#f5222d' }} /></Col>
        <Col span={6}><Statistic title="均值" value={mean.toFixed(3)} valueStyle={{ fontSize: 14 }} /></Col>
        <Col span={6}><Statistic title="标准差 σ" value={sigma.toFixed(4)} valueStyle={{ fontSize: 14 }} /></Col>
      </Row>
      {/* Xbar 图 */}
      <div style={{ border: '1px solid #f0f0f0', borderRadius: 4, padding: '8px 4px 0', marginBottom: 4 }}>
        <div style={{ fontSize: 11, color: '#999', paddingLeft: 8 }}>Xbar 控制图 — {characteristicName}</div>
        <Line {...xbarConfig} />
      </div>
      {/* MR 图 */}
      <div style={{ border: '1px solid #f0f0f0', borderRadius: 4, padding: '8px 4px 0' }}>
        <div style={{ fontSize: 11, color: '#999', paddingLeft: 8 }}>移动极差 (MR) 图</div>
        <Line {...mrConfig} />
      </div>
      <div style={{ textAlign: 'center', fontSize: 11, color: '#999', marginTop: 4 }}>点击数据点查看详情 | 黄色区域 ±2σ | 红色区域 ±3σ</div>

      {/* 异常点详情 Drawer */}
      <Drawer title="数据点详情" open={!!selected} onClose={() => setSelected(null)} width={360}>
        {selected && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="样本组">#{selected.sample_group ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="测量值">
              <span style={{ fontWeight: 700, color: selected.is_out_of_control ? '#f5222d' : '#1890ff' }}>
                {(selected.value ?? selected.measured_value)?.toFixed(4)}
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={selected.is_out_of_control ? 'error' : 'success'}>{selected.is_out_of_control ? '⚠ 失控' : '✓ 受控'}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="UCL">{selected.ucl?.toFixed(3)}</Descriptions.Item>
            <Descriptions.Item label="CL">{selected.cl?.toFixed(3)}</Descriptions.Item>
            <Descriptions.Item label="LCL">{selected.lcl?.toFixed(3)}</Descriptions.Item>
            <Descriptions.Item label="偏差">{((selected.value ?? selected.measured_value ?? 0) - (selected.cl ?? 0)).toFixed(4)} ({(((selected.value ?? 0) - (selected.cl ?? 0)) / sigma * 100).toFixed(0)}% σ)</Descriptions.Item>
            <Descriptions.Item label="工位">{selected.station_id || '-'}</Descriptions.Item>
            <Descriptions.Item label="控制图类型">{selected.control_chart_type || 'Xbar-R'}</Descriptions.Item>
            <Descriptions.Item label="测量时间">{selected.measured_at?.replace('T', ' ').slice(0, 19)}</Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  )
}

// ============== SPC 控制面板 ==============
const SpcPanel: React.FC = () => {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [charCode, setCharCode] = useState('')
  const [configs, setConfigs] = useState<any[]>([])
  const [addModal, setAddModal] = useState(false)
  const [form] = Form.useForm()

  const loadChart = useCallback(async (code: string) => {
    if (!code) return
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/qms/spc', { params: { factory_id: getFactory(), characteristic_code: code } })
      setData(res)
    } catch { setData(null) } finally { setLoading(false) }
  }, [])

  // 自动加载可用特性列表并查询第一个
  useEffect(() => {
    (async () => {
      try {
        const list: any = await api.get('/api/v1/qms/spc/configs', { params: { factory_id: getFactory() } })
        setConfigs(list || [])
        if (list?.length > 0) {
          setCharCode(list[0].code)
          loadChart(list[0].code)
        }
      } catch { /* */ }
    })()
  }, [loadChart])

  const handleAdd = async () => {
    const vals = await form.validateFields()
    try {
      const res: any = await api.post('/api/v1/qms/spc', { ...vals, factory_id: getFactory() })
      message.success(res.is_out_of_control ? '⚠️ 数据点超出控制限！' : '数据点已记录')
      setAddModal(false)
      form.resetFields()
      if (vals.characteristic_code) { setCharCode(vals.characteristic_code); loadChart(vals.characteristic_code) }
    } catch (e: any) { message.error(e?.response?.data?.detail || '失败') }
  }

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        {configs.length > 0 ? (
          <Select value={charCode} onChange={(v) => { setCharCode(v); loadChart(v) }} style={{ width: 220 }}
            options={configs.map((c: any) => ({ value: c.code, label: `${c.code} (${c.name})` }))} />
        ) : (
          <Input placeholder="质量特性编码" value={charCode} onChange={e => setCharCode(e.target.value)}
            onPressEnter={() => loadChart(charCode)} style={{ width: 200 }} />
        )}
        <Button onClick={() => loadChart(charCode)}>查询</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddModal(true)}>记录数据</Button>
      </Space>

      <Spin spinning={loading}>
        {!data || data.points.length === 0 ? (
          <Empty description="输入质量特性编码查询 SPC 控制图" />
        ) : (
          <Card size="small" title={`${data.characteristic_name || data.characteristic_code} 控制图`}
            extra={<Tag color={data.ooc_count > 0 ? 'error' : 'success'}>{data.ooc_count} 个异常点</Tag>}>
            <SpcControlChart points={data.points} characteristicName={data.characteristic_name || data.characteristic_code} />
          </Card>
        )}
      </Spin>

      <Modal title="记录 SPC 数据点" open={addModal} onOk={handleAdd} onCancel={() => setAddModal(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="characteristic_code" label="质量特性编码" rules={[{ required: true }]}>
            <Input placeholder="如: OD-001 (外径)" />
          </Form.Item>
          <Form.Item name="characteristic_name" label="特性名称"><Input /></Form.Item>
          <Form.Item name="measured_value" label="实测值" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} step={0.01} />
          </Form.Item>
          <Form.Item name="station_id" label="工位"><Input /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ============== 8D 报告 ==============
const EightDPanel: React.FC = () => {
  const [reports, setReports] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<any>(null)
  const [createModal, setCreateModal] = useState(false)
  const [form] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/qms/8d', { params: { factory_id: getFactory() } })
      setReports(res.items || [])
    } catch { /* */ } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const handleCreate = async () => {
    const vals = await form.validateFields()
    try {
      await api.post('/api/v1/qms/8d', { ...vals, factory_id: getFactory() })
      message.success('8D 报告已创建')
      setCreateModal(false); form.resetFields(); load()
    } catch (e: any) { message.error(e?.response?.data?.detail || '失败') }
  }

  const statusColor: Record<string, string> = { open: 'error', in_progress: 'processing', closed: 'success', verified: 'default' }

  return (
    <div>
      <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)} style={{ marginBottom: 12 }}>新建 8D</Button>
      <Table dataSource={reports} rowKey="id" size="small" loading={loading} pagination={false}
        onRow={r => ({ onClick: () => setDetail(r), style: { cursor: 'pointer' } })}
        columns={[
          { title: '编号', dataIndex: 'report_code', width: 180 },
          { title: '标题', dataIndex: 'title', ellipsis: true },
          { title: '严重度', dataIndex: 'severity', width: 80, render: (v: string) => <Tag color={v === 'critical' ? 'red' : 'orange'}>{v}</Tag> },
          { title: '状态', dataIndex: 'status', width: 100, render: (v: string) => <Tag color={statusColor[v]}>{v}</Tag> },
          { title: '创建时间', dataIndex: 'created_at', width: 120, render: (v: string) => v?.slice(0, 10) },
        ]}
      />

      <Modal title="新建 8D 报告" open={createModal} onOk={handleCreate} onCancel={() => setCreateModal(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="severity" label="严重度" initialValue="major">
            <Select options={[{ value: 'critical', label: 'Critical' }, { value: 'major', label: 'Major' }, { value: 'minor', label: 'Minor' }]} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer title={`8D报告: ${detail?.report_code}`} open={!!detail} onClose={() => setDetail(null)} width={720}
        extra={detail && <Tag color={detail.status === 'verified' ? 'success' : detail.status === 'closed' ? 'default' : 'processing'}>{detail.status}</Tag>}>
        {detail && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="标题" span={2}>{detail.title}</Descriptions.Item>
              <Descriptions.Item label="严重度"><Tag color={detail.severity === 'critical' ? 'red' : 'orange'}>{detail.severity}</Tag></Descriptions.Item>
              <Descriptions.Item label="创建时间">{detail.created_at?.slice(0, 10)}</Descriptions.Item>
            </Descriptions>
            {[
              { key: 'd1_team', label: 'D1 团队', color: '#1890ff' },
              { key: 'd2_problem_description', label: 'D2 问题描述', color: '#1890ff' },
              { key: 'd3_containment_action', label: 'D3 临时措施', color: '#faad14' },
              { key: 'd4_root_cause', label: 'D4 根因分析', color: '#f5222d' },
              { key: 'd5_corrective_action', label: 'D5 纠正措施', color: '#52c41a' },
              { key: 'd6_implementation', label: 'D6 效果验证', color: '#722ed1' },
              { key: 'd7_preventive_action', label: 'D7 预防措施', color: '#13c2c2' },
              { key: 'd8_congratulations', label: 'D8 总结表彰', color: '#eb2f96' },
            ].map(({ key, label, color }) => (
              <Card key={key} size="small"
                title={<span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 4, background: color, marginRight: 8 }} />{label}</span>}>
                <div style={{ whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.8, color: '#333' }}>
                  {detail[key] || <span style={{ color: '#999' }}>待填写</span>}
                </div>
              </Card>
            ))}
          </div>
        )}
      </Drawer>
    </div>
  )
}

// ============== 质量看板 ==============
const DashboardPanel: React.FC = () => {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    (async () => {
      setLoading(true)
      try {
        const res: any = await api.get('/api/v1/qms/dashboard', { params: { factory_id: getFactory() } })
        setData(res)
      } catch { /* */ } finally { setLoading(false) }
    })()
  }, [])

  if (loading) return <Spin />
  if (!data) return <Empty />

  return (
    <div>
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col span={6}><Card size="small"><Statistic title="检验合格率" value={data.inspection?.pass_rate} suffix="%" valueStyle={{ color: (data.inspection?.pass_rate || 0) >= 95 ? '#52c41a' : '#f5222d' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="总检验数" value={data.inspection?.total} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="SPC 异常点" value={data.spc_ooc_count} valueStyle={{ color: data.spc_ooc_count > 0 ? '#f5222d' : undefined }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="8D 进行中" value={(data.eight_d?.in_progress || 0) + (data.eight_d?.open || 0)} /></Card></Col>
      </Row>
      <Card size="small" title="Top 缺陷类型">
        {data.top_defects?.length ? (
          <Space direction="vertical" style={{ width: '100%' }}>
            {data.top_defects.map((d: any, i: number) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>{d.type}</span>
                <Progress percent={Math.round(d.qty / (data.top_defects[0]?.qty || 1) * 100)} size="small" style={{ width: 200 }} />
                <span>{d.qty}</span>
              </div>
            ))}
          </Space>
        ) : <Empty description="暂无缺陷数据" />}
      </Card>
    </div>
  )
}

// ============== 主页面 ==============
const QualityCenter: React.FC = () => {
  return (
    <Tabs size="small" defaultActiveKey="dashboard" items={[
      { key: 'dashboard', label: <span><DashboardOutlined /> 质量看板</span>, children: <DashboardPanel /> },
      { key: 'spc', label: <span><LineChartOutlined /> SPC 控制图</span>, children: <SpcPanel /> },
      { key: '8d', label: <span><FileProtectOutlined /> 8D 报告</span>, children: <EightDPanel /> },
    ]} />
  )
}

export default QualityCenter
