import React, { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Space, Button, Modal, Form, Input, InputNumber, Select,
  message, Typography, Row, Col, Statistic, Descriptions, Badge,
} from 'antd'
import {
  AuditOutlined, PlusOutlined, CheckCircleOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'

const { Title, Text } = Typography
const FACTORY = 'F001'

const typeColors: Record<string, string> = { IQC: 'blue', IPQC: 'green', FQC: 'orange', OQC: 'purple' }
const statusConfig: Record<string, { color: string; label: string }> = {
  pending: { color: 'default', label: '待检' },
  inspecting: { color: 'processing', label: '检验中' },
  passed: { color: 'success', label: '合格' },
  failed: { color: 'error', label: '不合格' },
  conditional: { color: 'warning', label: '让步接收' },
}

const InspectionTerminal: React.FC = () => {
  const [tasks, setTasks] = useState<any[]>([])
  const [kpi, setKpi] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [createVisible, setCreateVisible] = useState(false)
  const [detail, setDetail] = useState<any>(null)
  const [form] = Form.useForm()

  const loadTasks = async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/qms/inspection/tasks', { params: { factory_id: FACTORY } })
      setTasks(res?.items || [])
    } catch { /* ignore */ } finally { setLoading(false) }
  }

  const loadKpi = async () => {
    try {
      const res: any = await api.get('/api/v1/qms/quality-kpi', { params: { factory_id: FACTORY } })
      setKpi(res)
    } catch { /* ignore */ }
  }

  useEffect(() => { loadTasks(); loadKpi() }, [])

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      await api.post('/api/v1/qms/inspection', { ...values, factory_id: FACTORY })
      message.success('检验任务创建成功')
      setCreateVisible(false)
      form.resetFields()
      loadTasks()
    } catch (e: any) {
      if (e?.response) message.error(e.response.data?.detail || '创建失败')
    }
  }

  const handleStart = async (taskId: string) => {
    await api.post(`/api/v1/qms/inspection/${taskId}/start`)
    message.success('开始检验')
    loadTasks()
  }

  const openDetail = async (taskId: string) => {
    try {
      const res: any = await api.get(`/api/v1/qms/inspection/${taskId}`)
      setDetail(res)
    } catch { /* ignore */ }
  }

  const columns: ColumnsType<any> = [
    { title: '任务号', dataIndex: 'task_code', key: 'code', width: 160,
      render: (v: string) => <Text strong>{v}</Text> },
    { title: '类型', dataIndex: 'inspect_type', key: 'type', width: 70,
      render: (v: string) => <Tag color={typeColors[v]}>{v}</Tag> },
    { title: '物料/产品', key: 'material', width: 130,
      render: (_, r) => r.material_name || r.material_code || r.product_id || '—' },
    { title: '批量/抽样', key: 'qty', width: 100,
      render: (_, r) => `${r.batch_qty || 0} / ${r.sample_qty || 0}` },
    { title: '不良率', dataIndex: 'defect_rate', key: 'rate', width: 80,
      render: (v: number) => v > 0 ? <Text type="danger">{v}%</Text> : <Text type="success">0%</Text> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => <Tag color={statusConfig[v]?.color}>{statusConfig[v]?.label || v}</Tag> },
    { title: '检验员', dataIndex: 'inspector', key: 'inspector', width: 80 },
    { title: '操作', key: 'action', width: 140,
      render: (_, r) => (
        <Space size="small">
          {r.status === 'pending' && <Button size="small" onClick={() => handleStart(r.id)}>开始</Button>}
          <Button size="small" type="link" onClick={() => openDetail(r.id)}>详情</Button>
        </Space>
      )},
  ]

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <AuditOutlined style={{ fontSize: 22, color: '#52c41a' }} />
            <Title level={4} style={{ margin: 0 }}>检验终端</Title>
            <Tag color="green">IQC / IPQC / FQC / OQC</Tag>
          </Space>
        </Col>
        <Col>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateVisible(true)}>新建检验</Button>
        </Col>
      </Row>

      {/* KPI */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card size="small"><Statistic title="近7天检验" value={kpi?.total_tasks || 0} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="合格率" value={kpi?.pass_rate || 100} suffix="%" valueStyle={{ color: '#52c41a' }} prefix={<CheckCircleOutlined />} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="不合格" value={kpi?.failed || 0} valueStyle={{ color: '#f5222d' }} prefix={<CloseCircleOutlined />} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="平均不良率" value={kpi?.avg_defect_rate || 0} suffix="%" /></Card></Col>
      </Row>

      <Card>
        <Table columns={columns} dataSource={tasks} rowKey="id" loading={loading} size="small" pagination={{ pageSize: 15 }} />
      </Card>

      {/* 新建检验 */}
      <Modal title="新建检验任务" open={createVisible} onOk={handleCreate} onCancel={() => setCreateVisible(false)} width={500}>
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="inspect_type" label="检验类型" rules={[{ required: true }]}>
                <Select options={[{ value: 'IQC', label: 'IQC 来料检' }, { value: 'IPQC', label: 'IPQC 过程检' }, { value: 'FQC', label: 'FQC 终检' }, { value: 'OQC', label: 'OQC 出货检' }]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="material_code" label="物料编码">
                <Input placeholder="物料编码" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="material_name" label="物料名称">
                <Input placeholder="物料名称" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="station_id" label="工位">
                <Input placeholder="工位ID（可选）" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="batch_qty" label="批量" initialValue={0}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="sample_qty" label="抽样数" initialValue={0}>
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 详情弹窗 */}
      <Modal title="检验详情" open={!!detail} onCancel={() => setDetail(null)} footer={null} width={600}>
        {detail && (
          <div>
            <Descriptions size="small" column={2} bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="任务号">{detail.task?.task_code}</Descriptions.Item>
              <Descriptions.Item label="类型"><Tag color={typeColors[detail.task?.inspect_type]}>{detail.task?.inspect_type}</Tag></Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={statusConfig[detail.task?.status]?.color}>{statusConfig[detail.task?.status]?.label}</Tag></Descriptions.Item>
              <Descriptions.Item label="检验员">{detail.task?.inspector || '—'}</Descriptions.Item>
            </Descriptions>
            <Text strong>检验项：</Text>
            <Table
              dataSource={detail.items || []}
              rowKey="id"
              size="small"
              pagination={false}
              style={{ marginTop: 8 }}
              columns={[
                { title: '#', dataIndex: 'seq', width: 40 },
                { title: '检验项', dataIndex: 'item_name', width: 150 },
                { title: '规格', dataIndex: 'spec_value', width: 100 },
                { title: '实测', dataIndex: 'measured_value', width: 80, render: (v) => v ?? '—' },
                { title: '判定', dataIndex: 'is_pass', width: 70, render: (v) => v === null ? '—' : v ? <Badge status="success" text="OK" /> : <Badge status="error" text="NG" /> },
              ]}
            />
          </div>
        )}
      </Modal>
    </div>
  )
}

export default InspectionTerminal
