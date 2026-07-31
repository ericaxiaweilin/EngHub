import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Tabs, Table, Button, Tag, Space, Row, Col, Statistic, Modal, Form,
  Input, InputNumber, Select, message, Empty, Spin, Descriptions, Progress,
} from 'antd'
import {
  LineChartOutlined, FileProtectOutlined,
  DashboardOutlined, PlusOutlined,
} from '@ant-design/icons'
import api from '../../services/api'
import { getStoredUser } from '../../services/auth'
import { Line } from '@ant-design/charts'

const getFactory = () => localStorage.getItem('active_factory_id') || getStoredUser()?.factory_id || 'FAC_ELEC_DEMO_2026'

// ============== SPC 控制图组件 (@ant-design/charts) ==============
const SpcControlChart: React.FC<{ points: any[] }> = ({ points }) => {
  if (!points?.length) return <Empty />

  const ucl = points[0]?.ucl ?? 1
  const cl = points[0]?.cl ?? 0
  const lcl = points[0]?.lcl ?? 0

  const chartData = points.map((p: any, i: number) => ({
    index: i + 1,
    value: p.value ?? p.measured_value ?? 0,
    type: p.is_out_of_control ? '异常点' : '受控点',
  }))

  const config: any = {
    data: chartData,
    xField: 'index',
    yField: 'value',
    colorField: 'type',
    scale: { color: { range: ['#1890ff', '#f5222d'] } },
    axis: {
      x: { title: '样本组', labelAutoRotate: false },
      y: { title: '测量值' },
    },
    style: { lineWidth: 2 },
    point: {
      shapeField: 'point',
      sizeField: 3,
      style: (datum: any) => ({
        fill: datum.type === '异常点' ? '#f5222d' : '#1890ff',
        stroke: '#fff',
        lineWidth: 1,
      }),
    },
    annotations: [
      { type: 'lineY', yField: ucl, style: { stroke: '#f5222d', lineWidth: 1.5, lineDash: [6, 3] }, label: { text: `UCL=${ucl.toFixed(2)}`, position: 'right', style: { fill: '#f5222d', fontSize: 10 } } },
      { type: 'lineY', yField: cl, style: { stroke: '#52c41a', lineWidth: 1.5, lineDash: [4, 2] }, label: { text: `CL=${cl.toFixed(2)}`, position: 'right', style: { fill: '#52c41a', fontSize: 10 } } },
      { type: 'lineY', yField: lcl, style: { stroke: '#f5222d', lineWidth: 1.5, lineDash: [6, 3] }, label: { text: `LCL=${lcl.toFixed(2)}`, position: 'right', style: { fill: '#f5222d', fontSize: 10 } } },
    ],
    tooltip: {
      title: (d: any) => `样本 #${d.index}`,
      items: [{ channel: 'y', name: '测量值' }],
    },
    height: 280,
  }

  return <Line {...config} />
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
            <SpcControlChart points={data.points} />
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

      <Modal title={`8D: ${detail?.report_code}`} open={!!detail} onCancel={() => setDetail(null)} footer={null} width={640}>
        {detail && (
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="标题">{detail.title}</Descriptions.Item>
            <Descriptions.Item label="D1 团队">{detail.d1_team || '待填写'}</Descriptions.Item>
            <Descriptions.Item label="D2 问题描述">{detail.d2_problem_description || '待填写'}</Descriptions.Item>
            <Descriptions.Item label="D3 临时措施">{detail.d3_containment_action || '待填写'}</Descriptions.Item>
            <Descriptions.Item label="D4 根因">{detail.d4_root_cause || '待填写'}</Descriptions.Item>
            <Descriptions.Item label="D5 纠正措施">{detail.d5_corrective_action || '待填写'}</Descriptions.Item>
            <Descriptions.Item label="D6 验证">{detail.d6_implementation || '待填写'}</Descriptions.Item>
            <Descriptions.Item label="D7 预防">{detail.d7_preventive_action || '待填写'}</Descriptions.Item>
            <Descriptions.Item label="D8 总结">{detail.d8_congratulations || '待填写'}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
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
