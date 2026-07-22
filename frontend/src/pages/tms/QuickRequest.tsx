/**
 * 快速工单 - 员工端小工单快速发起页
 * 呼叫请求 + 5种通用工单模板，与 TMS 联动
 */
import React, { useState, useEffect, useCallback } from 'react'
import { Card, Row, Col, Form, Input, Select, Button, message, Table, Tag, Space, Typography, Radio } from 'antd'
import {
  PhoneOutlined, ToolOutlined, ExperimentOutlined, AuditOutlined,
  DeleteOutlined, AlertOutlined, ThunderboltOutlined,
  ClockCircleOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { tmsApi } from '../../services/tms'
import api from '../../services/api'
import { getStoredUser } from '../../services/auth'

const { TextArea } = Input
const { Text } = Typography

// 呼叫请求类型
const CALL_TYPES = [
  { value: 'equipment_fault', label: '设备故障呼叫', icon: <ToolOutlined />, color: '#f5222d' },
  { value: 'material_call', label: '物料呼叫', icon: <AlertOutlined />, color: '#fa8c16' },
  { value: 'quality_call', label: '品质呼叫', icon: <ExperimentOutlined />, color: '#722ed1' },
  { value: 'support_call', label: '支援呼叫', icon: <PhoneOutlined />, color: '#1890ff' },
]

// 通用工单模板卡片
const TEMPLATE_CARDS = [
  { code: 'NCR', name: '品质异常单', desc: '缺陷记录/8D报告/处置', icon: <ExclamationCircleOutlined />, color: '#f5222d' },
  { code: 'MAINT', name: '设备维修工单', desc: '故障现象/备件/MTTR', icon: <ToolOutlined />, color: '#fa8c16' },
  { code: 'ECR', name: '工艺变更申请', desc: '风险评估/受影响工单', icon: <AuditOutlined />, color: '#1890ff' },
  { code: 'FAI', name: '首件检验单', desc: '关键尺寸/公差对比', icon: <ExperimentOutlined />, color: '#52c41a' },
  { code: 'SCRAP', name: '报废申请单', desc: '成本估算/财务审批', icon: <DeleteOutlined />, color: '#8c8c8c' },
]

const PRIORITY_OPTIONS = [
  { value: 'low', label: '低', color: 'default' },
  { value: 'medium', label: '中', color: 'blue' },
  { value: 'high', label: '高', color: 'orange' },
  { value: 'urgent', label: '紧急', color: 'red' },
]

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  created: { color: 'default', text: '待分发' },
  pending: { color: 'default', text: '待分发' },
  distributed: { color: 'processing', text: '已分发' },
  assigned: { color: 'processing', text: '已指派' },
  claimed: { color: 'processing', text: '已认领' },
  in_progress: { color: 'processing', text: '处理中' },
  completed: { color: 'success', text: '已完成' },
  cancelled: { color: 'default', text: '已取消' },
}

const QuickRequest: React.FC = () => {
  const user = getStoredUser()
  const [mode, setMode] = useState<'call' | 'template'>('call')
  const [callForm] = Form.useForm()
  const [templateForm] = Form.useForm()
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null)
  const [templateFields, setTemplateFields] = useState<any[]>([])
  const [myRequests, setMyRequests] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const fetchMyRequests = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await tmsApi.listTasks({ page_size: 50 })
      const tasks = res.items || res.data?.items || []
      // 只显示自己发起的（呼叫请求 + 模板工单）
      const mine = tasks.filter((t: any) =>
        t.created_by === user?.username || t.task_type === 'call_request' || t.metadata?.template_code
      )
      setMyRequests(mine)
    } catch (e) {
      console.error('获取我的请求失败', e)
    } finally {
      setLoading(false)
    }
  }, [user?.username])

  useEffect(() => { fetchMyRequests() }, [fetchMyRequests])

  // 加载模板字段
  const loadTemplateFields = async (code: string) => {
    setSelectedTemplate(code)
    templateForm.resetFields()
    try {
      const data: any = await api.post(`/api/v1/work-order-templates/preview/${code}`)
      setTemplateFields(data.fields || [])
    } catch (e) {
      console.error('加载模板字段失败', e)
      setTemplateFields([])
    }
  }

  // 提交呼叫请求
  const submitCallRequest = async () => {
    try {
      const values = await callForm.validateFields()
      setSubmitting(true)
      const callType = CALL_TYPES.find(c => c.value === values.call_type)
      await tmsApi.createTask({
        title: `${callType?.label || '呼叫请求'} - ${values.station}`,
        task_type: 'call_request',
        description: values.description,
        priority: values.priority,
        required_skills: [],
        metadata: {
          call_type: values.call_type,
          station: values.station,
          requested_by: user?.username,
        } as any,
      })
      message.success('呼叫请求已发送，等待响应')
      callForm.resetFields()
      fetchMyRequests()
    } catch (e: any) {
      if (e?.errorFields) return // 表单校验失败
      message.error('提交失败: ' + (e?.response?.data?.detail || e.message))
    } finally {
      setSubmitting(false)
    }
  }

  // 提交模板工单
  const submitTemplate = async () => {
    if (!selectedTemplate) return
    try {
      const values = await templateForm.validateFields()
      setSubmitting(true)
      const tpl = TEMPLATE_CARDS.find(t => t.code === selectedTemplate)
      await tmsApi.createTask({
        title: `${tpl?.name || selectedTemplate} - ${user?.username}`,
        task_type: 'work_order_template',
        description: JSON.stringify(values),
        priority: values.priority || 'medium',
        metadata: {
          template_code: selectedTemplate,
          form_data: values,
          requested_by: user?.username,
        } as any,
      })
      message.success(`${tpl?.name} 已创建`)
      templateForm.resetFields()
      setSelectedTemplate(null)
      setTemplateFields([])
      fetchMyRequests()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error('提交失败: ' + (e?.response?.data?.detail || e.message))
    } finally {
      setSubmitting(false)
    }
  }

  // 动态渲染模板字段
  const renderTemplateField = (field: any) => {
    const rules = field.required ? [{ required: true, message: `请填写${field.label}` }] : []
    switch (field.type) {
      case 'text':
        return <Form.Item key={field.key} name={field.key} label={field.label} rules={rules}><TextArea rows={3} /></Form.Item>
      case 'select':
        return (
          <Form.Item key={field.key} name={field.key} label={field.label} rules={rules}>
            <Select options={(field.options || []).map((o: string) => ({ value: o, label: o }))} />
          </Form.Item>
        )
      case 'integer':
      case 'float':
        return <Form.Item key={field.key} name={field.key} label={field.label} rules={rules}><Input type="number" /></Form.Item>
      case 'boolean':
        return (
          <Form.Item key={field.key} name={field.key} label={field.label} valuePropName="checked" rules={rules}>
            <Radio.Group><Radio value={true}>是</Radio><Radio value={false}>否</Radio></Radio.Group>
          </Form.Item>
        )
      case 'date':
        return <Form.Item key={field.key} name={field.key} label={field.label} rules={rules}><Input type="date" /></Form.Item>
      default:
        return <Form.Item key={field.key} name={field.key} label={field.label} rules={rules}><Input /></Form.Item>
    }
  }

  const columns = [
    {
      title: '类型', key: 'type', width: 110,
      render: (_: any, r: any) => r.task_type === 'call_request'
        ? <Tag color="red"><PhoneOutlined /> {CALL_TYPES.find(c => c.value === r.metadata?.call_type)?.label || '呼叫'}</Tag>
        : <Tag color="blue">{TEMPLATE_CARDS.find(t => t.code === r.metadata?.template_code)?.name || '工单'}</Tag>,
    },
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
    {
      title: '优先级', dataIndex: 'priority', key: 'priority', width: 80,
      render: (v: string) => { const p = PRIORITY_OPTIONS.find(o => o.value === v); return <Tag color={p?.color}>{p?.label || v}</Tag> },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (v: string) => { const s = STATUS_MAP[v] || { color: 'default', text: v }; return <Tag color={s.color}>{s.text}</Tag> },
    },
    { title: '处理人', dataIndex: 'assigned_to', key: 'assignee', width: 90, render: (v: string) => v || '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'time', width: 130, render: (v: string) => v ? dayjs(v).format('MM-DD HH:mm') : '-' },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>快速工单</h2>

      <Row gutter={16}>
        {/* 左侧：发起区 */}
        <Col xs={24} lg={10}>
          <Card
            title={
              <Space>
                <Button type={mode === 'call' ? 'primary' : 'default'} size="small" icon={<PhoneOutlined />} onClick={() => setMode('call')}>呼叫请求</Button>
                <Button type={mode === 'template' ? 'primary' : 'default'} size="small" icon={<AuditOutlined />} onClick={() => setMode('template')}>工单模板</Button>
              </Space>
            }
          >
            {mode === 'call' ? (
              <Form form={callForm} layout="vertical" initialValues={{ priority: 'high', call_type: 'equipment_fault' }}>
                <Form.Item name="call_type" label="呼叫类型" rules={[{ required: true }]}>
                  <Radio.Group>
                    <Row gutter={[8, 8]}>
                      {CALL_TYPES.map(ct => (
                        <Col span={12} key={ct.value}>
                          <Radio.Button value={ct.value} style={{ width: '100%', textAlign: 'center' }}>
                            <span style={{ color: ct.color }}>{ct.icon}</span> {ct.label}
                          </Radio.Button>
                        </Col>
                      ))}
                    </Row>
                  </Radio.Group>
                </Form.Item>
                <Form.Item name="station" label="工位/位置" rules={[{ required: true, message: '请输入工位' }]}>
                  <Input placeholder="如: ST-ASM-01 / A栋2层" />
                </Form.Item>
                <Form.Item name="priority" label="紧急程度" rules={[{ required: true }]}>
                  <Radio.Group>
                    {PRIORITY_OPTIONS.map(p => <Radio.Button key={p.value} value={p.value}>{p.label}</Radio.Button>)}
                  </Radio.Group>
                </Form.Item>
                <Form.Item name="description" label="问题描述" rules={[{ required: true, message: '请描述问题' }]}>
                  <TextArea rows={3} placeholder="简要描述现场情况..." />
                </Form.Item>
                <Button type="primary" block icon={<ThunderboltOutlined />} loading={submitting} onClick={submitCallRequest}>
                  发送呼叫请求
                </Button>
              </Form>
            ) : (
              <div>
                {!selectedTemplate ? (
                  <Row gutter={[12, 12]}>
                    {TEMPLATE_CARDS.map(tpl => (
                      <Col span={12} key={tpl.code}>
                        <Card
                          hoverable size="small"
                          onClick={() => loadTemplateFields(tpl.code)}
                          style={{ textAlign: 'center' }}
                        >
                          <div style={{ fontSize: 28, color: tpl.color, marginBottom: 8 }}>{tpl.icon}</div>
                          <Text strong>{tpl.name}</Text>
                          <div><Text type="secondary" style={{ fontSize: 12 }}>{tpl.desc}</Text></div>
                        </Card>
                      </Col>
                    ))}
                  </Row>
                ) : (
                  <div>
                    <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Text strong>{TEMPLATE_CARDS.find(t => t.code === selectedTemplate)?.name}</Text>
                      <Button size="small" onClick={() => { setSelectedTemplate(null); setTemplateFields([]) }}>返回</Button>
                    </div>
                    <Form form={templateForm} layout="vertical">
                      {templateFields.map(renderTemplateField)}
                      <Button type="primary" block loading={submitting} onClick={submitTemplate}>
                        创建{TEMPLATE_CARDS.find(t => t.code === selectedTemplate)?.name}
                      </Button>
                    </Form>
                  </div>
                )}
              </div>
            )}
          </Card>
        </Col>

        {/* 右侧：我的请求 */}
        <Col xs={24} lg={14}>
          <Card title={<span><ClockCircleOutlined /> 我的请求</span>} extra={<Button size="small" onClick={fetchMyRequests}>刷新</Button>}>
            <Table
              dataSource={myRequests}
              columns={columns}
              rowKey="id"
              size="small"
              loading={loading}
              pagination={{ pageSize: 10, size: 'small' }}
              locale={{ emptyText: '暂无请求记录' }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default QuickRequest
