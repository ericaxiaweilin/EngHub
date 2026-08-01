import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select,
  message, Row, Col, Statistic, Popconfirm,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, FileSearchOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'
import { getActiveFactoryId } from '../../utils/factory'

interface MethodStudy {
  id: string
  factory_id: string
  operation_name: string
  current_method: string
  proposed_method: string
  time_saving_pct: number
  status: string
  analyst: string
  created_at: string
}

const MOCK_DATA: MethodStudy[] = [
  { id: 'ms-1', factory_id: 'factory-sh-01', operation_name: '轴承装配', current_method: '手动压入', proposed_method: '液压机压入', time_saving_pct: 35.0, status: 'implemented', analyst: 'IE-张工', created_at: '2026-05-01' },
  { id: 'ms-2', factory_id: 'factory-sh-01', operation_name: 'PCB焊接', current_method: '单点手工焊', proposed_method: '波峰焊批量', time_saving_pct: 60.0, status: 'proposed', analyst: 'IE-李工', created_at: '2026-05-10' },
  { id: 'ms-3', factory_id: 'factory-sh-01', operation_name: '外观检验', current_method: '人工目视', proposed_method: 'AOI自动光学检测', time_saving_pct: 75.0, status: 'evaluating', analyst: 'IE-张工', created_at: '2026-06-01' },
  { id: 'ms-4', factory_id: 'factory-sh-01', operation_name: '物料搬运', current_method: '人工推车', proposed_method: 'AGV自动导引车', time_saving_pct: 50.0, status: 'proposed', analyst: 'IE-王工', created_at: '2026-06-15' },
]

function normalizeMethodStudy(row: any): MethodStudy {
  const savingDetail = row.expected_time_saving_calculation_detail || {}
  const savingMin = Number(row.expected_time_saving_min ?? savingDetail.saving_min ?? 0)
  const standardMin = Number(row.total_standard_time_min ?? 0)
  const savingPct = Number(row.time_saving_pct ?? savingDetail.saving_pct ?? (standardMin > 0 ? (savingMin / standardMin) * 100 : 0))
  return {
    ...row,
    operation_name: row.operation_name || row.original_operation,
    current_method: row.current_method || row.old_method_description || row.description || '-',
    proposed_method: row.proposed_method || row.improved_operation || savingDetail.proposed_method || row.description || '-',
    time_saving_pct: savingPct,
    analyst: row.analyst || row.created_by || row.approved_by || '-',
  }
}

const MethodStudies: React.FC = () => {
  const [factory, setFactory] = useState(getActiveFactoryId())
  const [data, setData] = useState<MethodStudy[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<MethodStudy | null>(null)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.get(API_ENDPOINTS.IE_ADVANCED_METHOD_STUDIES, { params: { factory_id: factory, limit: 200 } })
      const items = res.items || res || []
      setData(items.map(normalizeMethodStudy))
    } catch { setData([]) } finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [factory])

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      if (editing) {
        await api.put(`${API_ENDPOINTS.IE_ADVANCED_METHOD_STUDIES}/${editing.id}`, values)
        message.success('更新成功')
      } else {
        await api.post(API_ENDPOINTS.IE_ADVANCED_METHOD_STUDIES, { ...values, factory_id: factory })
        message.success('创建成功')
      }
      setModalOpen(false); form.resetFields(); setEditing(null); fetchData()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    try { await api.delete(`${API_ENDPOINTS.IE_ADVANCED_METHOD_STUDIES}/${id}`); message.success('已删除'); fetchData() }
    catch { message.error('删除失败') }
  }

  const columns: ColumnsType<MethodStudy> = [
    { title: '工序', dataIndex: 'operation_name', key: 'operation_name', width: 130, ellipsis: true },
    { title: '现行方法', dataIndex: 'current_method', key: 'current_method', width: 180, ellipsis: true },
    { title: '改善方案', dataIndex: 'proposed_method', key: 'proposed_method', width: 180, ellipsis: true },
    {
      title: '节省时间', dataIndex: 'time_saving_pct', key: 'time_saving_pct', width: 100,
      sorter: (a, b) => a.time_saving_pct - b.time_saving_pct,
      render: v => <Tag color={v >= 20 ? 'green' : v >= 10 ? 'blue' : 'default'}>{(v || 0).toFixed(1)}%</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: v => <Tag color={v === 'implemented' ? 'green' : v === 'approved' ? 'blue' : v === 'pending' ? 'orange' : 'default'}>
        {v === 'implemented' ? '已实施' : v === 'approved' ? '已批准' : v === 'pending' ? '待审' : v || '-'}
      </Tag>,
    },
    { title: '分析员', dataIndex: 'analyst', key: 'analyst', width: 80, render: v => v || '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 100, render: v => v ? dayjs(v).format('YYYY-MM-DD') : '-' },
    {
      title: '操作', key: 'action', width: 90, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => { setEditing(r); form.setFieldsValue(r); setModalOpen(true) }} />
          <Popconfirm title="确认删除?" onConfirm={() => handleDelete(r.id)}><Button type="link" size="small" danger icon={<DeleteOutlined />} /></Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card size="small"><Statistic title="方案总数" value={data.length} prefix={<FileSearchOutlined />} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="已实施" value={data.filter(d => d.status === 'implemented').length} valueStyle={{ color: '#52c41a' }} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="平均节省" value={data.length ? (data.reduce((s, d) => s + (d.time_saving_pct || 0), 0) / data.length).toFixed(1) : 0} suffix="%" valueStyle={{ color: '#1890ff' }} /></Card></Col>
      </Row>

      <Card title="方法研究" extra={
        <Space>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }} size="small">
            <Select.Option value="FAC_ELEC_DEMO_2026">电子工厂</Select.Option><Select.Option value="FAC_MECH_001">机械工厂</Select.Option>
          </Select>
          <Button type="primary" icon={<PlusOutlined />} size="small" onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true) }}>新增</Button>
        </Space>
      }>
        <Table dataSource={data} columns={columns} loading={loading} rowKey="id" scroll={{ x: 1000 }} size="middle" pagination={{ pageSize: 15, showTotal: t => `共 ${t} 条` }} />
      </Card>

      <Modal title={editing ? '编辑方法研究' : '新增方法研究'} open={modalOpen} onOk={handleSave} onCancel={() => { setModalOpen(false); setEditing(null) }} okText="保存" cancelText="取消" width={560}>
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item name="operation_name" label="工序名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="current_method" label="现行方法" rules={[{ required: true }]}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="proposed_method" label="改善方案" rules={[{ required: true }]}><Input.TextArea rows={2} /></Form.Item>
          <Row gutter={16}>
            <Col span={8}><Form.Item name="time_saving_pct" label="节省时间(%)"><Input type="number" /></Form.Item></Col>
            <Col span={8}><Form.Item name="analyst" label="分析员"><Input /></Form.Item></Col>
            <Col span={8}>
              <Form.Item name="status" label="状态" initialValue="pending">
                <Select><Select.Option value="pending">待审</Select.Option><Select.Option value="approved">已批准</Select.Option><Select.Option value="implemented">已实施</Select.Option><Select.Option value="rejected">驳回</Select.Option></Select>
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  )
}

export default MethodStudies
