import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, InputNumber, Rate,
  message, Row, Col, Statistic, Popconfirm, Progress,
} from 'antd'
import { PlusOutlined, DeleteOutlined, AuditOutlined, CheckCircleOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'

interface FiveSAudit {
  id: string
  factory_id: string
  work_center_id: string
  auditor: string
  audit_date: string
  score_sort: number
  score_set_in_order: number
  score_shine: number
  score_standardize: number
  score_sustain: number
  total_score: number
  status: string
  created_at: string
}

const FiveSAudits: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<FiveSAudit[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.get(API_ENDPOINTS.IE_ADVANCED_5S_AUDITS, { params: { factory_id: factory, limit: 200 } })
      setData(res.items || res || [])
    } catch { setData([]) } finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [factory])

  const avgScore = data.length > 0 ? (data.reduce((s, d) => s + (d.total_score || 0), 0) / data.length).toFixed(1) : '0'
  const passCount = data.filter(d => (d.total_score || 0) >= 70).length

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      const total = (values.score_sort || 0) + (values.score_set_in_order || 0) +
        (values.score_shine || 0) + (values.score_standardize || 0) + (values.score_sustain || 0)
      await api.post(API_ENDPOINTS.IE_ADVANCED_5S_AUDITS, { ...values, total_score: total, factory_id: factory })
      message.success('审核已提交')
      setModalOpen(false); form.resetFields(); fetchData()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '提交失败')
    }
  }

  const handleDelete = async (id: string) => {
    try { await api.delete(`${API_ENDPOINTS.IE_ADVANCED_5S_AUDITS}/${id}`); message.success('已删除'); fetchData() }
    catch { message.error('删除失败') }
  }

  const columns: ColumnsType<FiveSAudit> = [
    { title: '工作中心', dataIndex: 'work_center_id', key: 'work_center_id', width: 110 },
    { title: '审核员', dataIndex: 'auditor', key: 'auditor', width: 90, render: v => v || '-' },
    { title: '审核日期', dataIndex: 'audit_date', key: 'audit_date', width: 110, render: v => v ? dayjs(v).format('YYYY-MM-DD') : '-' },
    { title: '整理', dataIndex: 'score_sort', key: 'score_sort', width: 60, render: v => v || 0 },
    { title: '整顿', dataIndex: 'score_set_in_order', key: 'score_set_in_order', width: 60, render: v => v || 0 },
    { title: '清扫', dataIndex: 'score_shine', key: 'score_shine', width: 60, render: v => v || 0 },
    { title: '清洁', dataIndex: 'score_standardize', key: 'score_standardize', width: 60, render: v => v || 0 },
    { title: '素养', dataIndex: 'score_sustain', key: 'score_sustain', width: 60, render: v => v || 0 },
    {
      title: '总分', dataIndex: 'total_score', key: 'total_score', width: 100,
      sorter: (a, b) => a.total_score - b.total_score,
      render: v => {
        const pct = Math.min(v || 0, 100)
        return <Progress percent={pct} size="small" strokeColor={pct >= 80 ? '#52c41a' : pct >= 60 ? '#faad14' : '#ff4d4f'} format={() => `${v}`} />
      },
    },
    {
      title: '等级', key: 'grade', width: 70,
      render: (_, r) => {
        const s = r.total_score || 0
        const grade = s >= 90 ? 'A' : s >= 80 ? 'B' : s >= 70 ? 'C' : s >= 60 ? 'D' : 'F'
        const color = s >= 90 ? 'green' : s >= 70 ? 'blue' : s >= 60 ? 'orange' : 'red'
        return <Tag color={color}>{grade}</Tag>
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
        <Col span={6}><Card size="small"><Statistic title="审核次数" value={data.length} prefix={<AuditOutlined />} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="平均分" value={avgScore} suffix="/100" valueStyle={{ color: '#1890ff' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="合格(≥70)" value={passCount} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="不合格" value={data.length - passCount} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
      </Row>

      <Card title="5S审核管理" extra={
        <Space>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }} size="small">
            <Select.Option value="F001">F001 厂区</Select.Option><Select.Option value="F01">F01 厂区</Select.Option>
          </Select>
          <Button type="primary" icon={<PlusOutlined />} size="small" onClick={() => { form.resetFields(); setModalOpen(true) }}>新增审核</Button>
        </Space>
      }>
        <Table dataSource={data} columns={columns} loading={loading} rowKey="id" scroll={{ x: 1100 }} size="middle" pagination={{ pageSize: 15, showTotal: t => `共 ${t} 条` }} />
      </Card>

      <Modal title="新增5S审核" open={modalOpen} onOk={handleCreate} onCancel={() => setModalOpen(false)} okText="提交" cancelText="取消" width={520}>
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="work_center_id" label="工作中心" rules={[{ required: true }]}><Input placeholder="如 WC-01" /></Form.Item></Col>
            <Col span={12}><Form.Item name="auditor" label="审核员" rules={[{ required: true }]}><Input /></Form.Item></Col>
          </Row>
          <Form.Item name="audit_date" label="审核日期" initialValue={dayjs().format('YYYY-MM-DD')}>
            <Input type="date" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="score_sort" label="整理(0-20)" rules={[{ required: true }]}><InputNumber min={0} max={20} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="score_set_in_order" label="整顿(0-20)" rules={[{ required: true }]}><InputNumber min={0} max={20} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="score_shine" label="清扫(0-20)" rules={[{ required: true }]}><InputNumber min={0} max={20} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="score_standardize" label="清洁(0-20)" rules={[{ required: true }]}><InputNumber min={0} max={20} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="score_sustain" label="素养(0-20)" rules={[{ required: true }]}><InputNumber min={0} max={20} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>
    </div>
  )
}

export default FiveSAudits
