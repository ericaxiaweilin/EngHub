import React, { useEffect, useState } from 'react'
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, InputNumber,
  message, Row, Col, Statistic, Popconfirm, Tooltip,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, AimOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'

interface ActionStudy {
  id: string
  factory_id: string
  operation_name: string
  station_id: string
  motion_type: string
  motion_distance_cm: number
  time_seconds: number
  difficulty_level: string
  improvement_note: string
  created_at: string
}

const MOTION_MAP: Record<string, string> = {
  reach: '伸手', grasp: '抓取', move: '移动', position: '定位',
  release: '释放', inspect: '检验', assemble: '装配', use_tool: '使用工具',
}

const ActionStudies: React.FC = () => {
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<ActionStudy[]>([])
  const [loading, setLoading] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<ActionStudy | null>(null)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await api.get(API_ENDPOINTS.IE_ADVANCED_ACTION_STUDIES, { params: { factory_id: factory, limit: 200 } })
      setData(res.items || res || [])
    } catch { setData([]) } finally { setLoading(false) }
  }

  useEffect(() => { fetchData() }, [factory])

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      if (editing) {
        await api.put(`${API_ENDPOINTS.IE_ADVANCED_ACTION_STUDIES}/${editing.id}`, values)
        message.success('更新成功')
      } else {
        await api.post(API_ENDPOINTS.IE_ADVANCED_ACTION_STUDIES, { ...values, factory_id: factory })
        message.success('创建成功')
      }
      setModalOpen(false); form.resetFields(); setEditing(null); fetchData()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(e?.response?.data?.detail || '操作失败')
    }
  }

  const handleDelete = async (id: string) => {
    try { await api.delete(`${API_ENDPOINTS.IE_ADVANCED_ACTION_STUDIES}/${id}`); message.success('已删除'); fetchData() }
    catch { message.error('删除失败') }
  }

  const columns: ColumnsType<ActionStudy> = [
    { title: '作业名称', dataIndex: 'operation_name', key: 'operation_name', width: 140, ellipsis: true },
    { title: '工位', dataIndex: 'station_id', key: 'station_id', width: 90 },
    {
      title: '动作类型', dataIndex: 'motion_type', key: 'motion_type', width: 90,
      render: v => <Tag>{MOTION_MAP[v] || v}</Tag>,
    },
    { title: '距离(cm)', dataIndex: 'motion_distance_cm', key: 'motion_distance_cm', width: 90, render: v => (v || 0).toFixed(1) },
    {
      title: '时间(s)', dataIndex: 'time_seconds', key: 'time_seconds', width: 80,
      sorter: (a, b) => a.time_seconds - b.time_seconds,
      render: v => <span style={{ fontWeight: 600 }}>{(v || 0).toFixed(2)}</span>,
    },
    {
      title: '难度', dataIndex: 'difficulty_level', key: 'difficulty_level', width: 70,
      render: v => <Tag color={v === 'high' ? 'red' : v === 'medium' ? 'orange' : 'green'}>{v === 'high' ? '高' : v === 'medium' ? '中' : '低'}</Tag>,
    },
    { title: '改善备注', dataIndex: 'improvement_note', key: 'improvement_note', width: 160, ellipsis: true, render: v => v || '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 100, render: v => v ? dayjs(v).format('YYYY-MM-DD') : '-' },
    {
      title: '操作', key: 'action', width: 90, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => { setEditing(r); form.setFieldsValue(r); setModalOpen(true) }} />
          <Popconfirm title="确认删除?" onConfirm={() => handleDelete(r.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}><Card size="small"><Statistic title="动作记录" value={data.length} prefix={<AimOutlined />} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="平均动作时间" value={data.length ? (data.reduce((s, d) => s + d.time_seconds, 0) / data.length).toFixed(2) : 0} suffix="s" valueStyle={{ color: '#1890ff' }} /></Card></Col>
        <Col span={8}><Card size="small"><Statistic title="高难度动作" value={data.filter(d => d.difficulty_level === 'high').length} valueStyle={{ color: '#ff4d4f' }} /></Card></Col>
      </Row>

      <Card title="动作研究" extra={
        <Space>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }} size="small">
            <Select.Option value="F001">F001 厂区</Select.Option><Select.Option value="F01">F01 厂区</Select.Option>
          </Select>
          <Button type="primary" icon={<PlusOutlined />} size="small" onClick={() => { setEditing(null); form.resetFields(); setModalOpen(true) }}>新增</Button>
        </Space>
      }>
        <Table dataSource={data} columns={columns} loading={loading} rowKey="id" scroll={{ x: 1000 }} size="middle"
          pagination={{ pageSize: 15, showTotal: t => `共 ${t} 条` }} />
      </Card>

      <Modal title={editing ? '编辑动作研究' : '新增动作研究'} open={modalOpen} onOk={handleSave} onCancel={() => { setModalOpen(false); setEditing(null) }} okText="保存" cancelText="取消" width={520}>
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}><Form.Item name="operation_name" label="作业名称" rules={[{ required: true }]}><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="station_id" label="工位ID"><Input /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="motion_type" label="动作类型" rules={[{ required: true }]}>
                <Select>{Object.entries(MOTION_MAP).map(([k, v]) => <Select.Option key={k} value={k}>{v}</Select.Option>)}</Select>
              </Form.Item>
            </Col>
            <Col span={8}><Form.Item name="motion_distance_cm" label="距离(cm)"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="time_seconds" label="时间(s)" rules={[{ required: true }]}><InputNumber min={0} step={0.01} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="difficulty_level" label="难度" initialValue="low">
                <Select><Select.Option value="low">低</Select.Option><Select.Option value="medium">中</Select.Option><Select.Option value="high">高</Select.Option></Select>
              </Form.Item>
            </Col>
            <Col span={16}><Form.Item name="improvement_note" label="改善备注"><Input.TextArea rows={1} /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>
    </div>
  )
}

export default ActionStudies
