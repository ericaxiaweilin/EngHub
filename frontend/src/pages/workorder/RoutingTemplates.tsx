/**
 * 工艺路线模板管理页面（016）
 * - 模板 CRUD
 * - 步骤编辑：工序代码下拉 / 标准工时 / 并行标记 / QC门标记
 */
import React, { useEffect, useState, useCallback } from 'react'
import {
  Table, Button, Card, Space, Modal, Form, Input, InputNumber, Switch, Select,
  Tag, message, Popconfirm, Divider,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined, OrderedListOutlined } from '@ant-design/icons'
import {
  getRoutingTemplates, createRoutingTemplate, updateRoutingTemplate, deleteRoutingTemplate,
  RoutingTemplate, RoutingTemplateStep,
} from '../../services/mes'
import { getStoredUser } from '../../services/auth'

const PROCESS_OPTIONS = [
  { value: 'CUT', label: '下料 (CUT)' },
  { value: 'MACH', label: '机加 (MACH)' },
  { value: 'GRD', label: '研磨 (GRD)' },
  { value: 'WCUT', label: '慢走丝 (WCUT)' },
  { value: 'EDM', label: '电火花 (EDM)' },
  { value: 'HT', label: '热处理 (HT)' },
  { value: 'WELD', label: '焊接 (WELD)' },
  { value: 'FIN', label: '表面处理 (FIN)' },
  { value: 'ASSY', label: '装配 (ASSY)' },
  { value: 'QC', label: '检验 (QC)' },
  { value: 'PKG', label: '包装 (PKG)' },
  { value: 'INJ', label: '注塑 (INJ)' },
  { value: 'SMT', label: '贴片 (SMT)' },
  { value: 'STMP', label: '冲压 (STMP)' },
]

const PROCESS_NAME: Record<string, string> = Object.fromEntries(PROCESS_OPTIONS.map(o => [o.value, o.label.split(' ')[0]]))

const RoutingTemplates: React.FC = () => {
  const user = getStoredUser()
  const factoryId = user?.factory_id || ''
  const [loading, setLoading] = useState(false)
  const [templates, setTemplates] = useState<RoutingTemplate[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<RoutingTemplate | null>(null)
  const [form] = Form.useForm()
  const [steps, setSteps] = useState<RoutingTemplateStep[]>([])

  const fetchData = useCallback(async () => {
    if (!factoryId) return
    setLoading(true)
    try {
      const res = await getRoutingTemplates(factoryId)
      setTemplates(res.items || [])
    } catch (e: any) {
      message.error('加载失败')
    } finally {
      setLoading(false)
    }
  }, [factoryId])

  useEffect(() => { fetchData() }, [fetchData])

  const openCreate = () => {
    setEditing(null)
    form.resetFields()
    setSteps([{ seq: 1, process_code: 'CUT', operation_name: '下料', standard_hours: 1, is_parallel: false, is_qc_gate: false }])
    setModalOpen(true)
  }

  const openEdit = (tpl: RoutingTemplate) => {
    setEditing(tpl)
    form.setFieldsValue({ template_code: tpl.template_code, template_name: tpl.template_name, description: tpl.description })
    setSteps(tpl.steps.map(s => ({ ...s })))
    setModalOpen(true)
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      const payload = {
        ...values,
        factory_id: factoryId,
        steps: steps.map((s, i) => ({ ...s, seq: i + 1 })),
      }
      if (editing) {
        await updateRoutingTemplate(editing.id, payload)
        message.success('已更新')
      } else {
        await createRoutingTemplate(payload)
        message.success('已创建')
      }
      setModalOpen(false)
      fetchData()
    } catch (e: any) {
      if (e?.response?.data?.detail) message.error(e.response.data.detail)
    }
  }

  const handleDelete = async (id: string) => {
    await deleteRoutingTemplate(id)
    message.success('已停用')
    fetchData()
  }

  const addStep = () => {
    setSteps([...steps, { seq: steps.length + 1, process_code: 'MACH', operation_name: '', standard_hours: 1, is_parallel: false, is_qc_gate: false }])
  }

  const removeStep = (idx: number) => {
    setSteps(steps.filter((_, i) => i !== idx))
  }

  const updateStep = (idx: number, field: string, value: any) => {
    const newSteps = [...steps]
    newSteps[idx] = { ...newSteps[idx], [field]: value }
    // 自动填充工序名称
    if (field === 'process_code') {
      newSteps[idx].operation_name = PROCESS_NAME[value] || value
    }
    setSteps(newSteps)
  }

  const columns = [
    { title: '模板编码', dataIndex: 'template_code', key: 'code', width: 150 },
    { title: '模板名称', dataIndex: 'template_name', key: 'name', width: 180 },
    {
      title: '工序数', key: 'step_count', width: 80, align: 'center' as const,
      render: (_: any, r: RoutingTemplate) => <Tag>{r.steps?.length || 0} 道</Tag>,
    },
    {
      title: '工序流程', key: 'flow', ellipsis: true,
      render: (_: any, r: RoutingTemplate) => (
        <Space size={2} wrap>
          {(r.steps || []).map((s, i) => (
            <React.Fragment key={i}>
              {i > 0 && <span style={{ color: '#d9d9d9' }}>→</span>}
              <Tag color={s.is_qc_gate ? 'red' : s.is_parallel ? 'orange' : 'blue'} style={{ margin: 0 }}>
                {s.operation_name || s.process_code}
              </Tag>
            </React.Fragment>
          ))}
        </Space>
      ),
    },
    { title: '描述', dataIndex: 'description', key: 'desc', ellipsis: true, width: 150 },
    {
      title: '操作', key: 'action', width: 120,
      render: (_: any, r: RoutingTemplate) => (
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Popconfirm title="确认停用？" onConfirm={() => handleDelete(r.id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={<Space><OrderedListOutlined /> 工艺路线模板</Space>}
        extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建模板</Button>}
      >
        <Table rowKey="id" columns={columns} dataSource={templates} loading={loading} size="small" pagination={false} />
      </Card>

      <Modal
        title={editing ? '编辑工艺路线模板' : '新建工艺路线模板'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        width={720}
        okText="保存"
      >
        <Form form={form} layout="vertical" size="small">
          <Form.Item name="template_code" label="模板编码" rules={[{ required: true }]}>
            <Input placeholder="如 RT-MOLD-STD" disabled={!!editing} />
          </Form.Item>
          <Form.Item name="template_name" label="模板名称" rules={[{ required: true }]}>
            <Input placeholder="如 标准塑胶模工艺路线" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>

        <Divider>工序步骤</Divider>
        {steps.map((step, idx) => (
          <Space key={idx} style={{ display: 'flex', marginBottom: 8 }} align="start">
            <Tag style={{ marginTop: 4 }}>{idx + 1}</Tag>
            <Select
              value={step.process_code}
              onChange={(v) => updateStep(idx, 'process_code', v)}
              options={PROCESS_OPTIONS}
              style={{ width: 150 }}
              size="small"
            />
            <Input
              value={step.operation_name}
              onChange={(e) => updateStep(idx, 'operation_name', e.target.value)}
              placeholder="工序名称"
              style={{ width: 100 }}
              size="small"
            />
            <InputNumber
              value={step.standard_hours}
              onChange={(v) => updateStep(idx, 'standard_hours', v || 0)}
              min={0}
              step={0.5}
              addonAfter="h"
              style={{ width: 90 }}
              size="small"
            />
            <Switch
              checked={step.is_parallel}
              onChange={(v) => updateStep(idx, 'is_parallel', v)}
              checkedChildren="并行"
              unCheckedChildren="串行"
              size="small"
            />
            <Switch
              checked={step.is_qc_gate}
              onChange={(v) => updateStep(idx, 'is_qc_gate', v)}
              checkedChildren="QC门"
              unCheckedChildren="无"
              size="small"
            />
            {steps.length > 1 && (
              <Button size="small" danger onClick={() => removeStep(idx)}>×</Button>
            )}
          </Space>
        ))}
        <Button type="dashed" block icon={<PlusOutlined />} onClick={addStep} size="small">
          添加工序
        </Button>
      </Modal>
    </div>
  )
}

export default RoutingTemplates
