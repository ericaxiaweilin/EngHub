

import { useState, useEffect } from 'react'
import { Card, Button, Form, Input, message, Tag, Descriptions, Space, Modal } from 'antd'
import { PlusOutlined, FileTextOutlined } from '@ant-design/icons'
import axios from 'axios'
import { workOrderTemplatesApi } from '../../services/workOrderTemplates'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

export default function WorkOrderTemplatesPage() {
  const [templates, setTemplates] = useState<any[]>([])
  const [fields, setFields] = useState<any[]>([])
  const [selectedCode, setSelectedCode] = useState('')
  const [formVisible, setFormVisible] = useState(false)
  const [form] = Form.useForm()

  const fetchTemplates = async () => {
    try {
      const res = await axios.get(`${API_BASE}/work-order-templates/`)
      setTemplates(res.data.templates || [])
    } catch (err) {
      console.error('获取模板列表失败:', err)
    }
  }

  const fetchFields = async (code: string) => {
    try {
      const res = await axios.get(`${API_BASE}/work-order-templates/preview/${code}`)
      setFields(res.data.fields || [])
    } catch (err) {
      console.error('获取模板字段失败:', err)
    }
  }

  useEffect(() => {
    fetchTemplates()
  }, [])

  const handleSelectTemplate = (code: string) => {
    setSelectedCode(code)
    fetchFields(code)
  }

  const handleCreate = async () => {
    try {
      const values = await form.validateFields()
      const result = await workOrderTemplatesApi.createFromTemplate({
        factory_id: 'factory-001',
        template_code: selectedCode,
        title: values.title,
        data: values.data || {},
      })
      message.success(`程序工单创建成功！工单号：${result.data?.work_order_code || '-'}`)
      form.resetFields()
      setFormVisible(false)
    } catch (err: any) {
      message.error(err.response?.data?.detail || '创建失败')
    }
  }

  const templateMeta: Record<string, { name: string; desc: string; color: string }> = {
    NCR: { name: '品质异常单', desc: '关联缺陷代码、8D报告、处置方式', color: 'red' },
    MAINT: { name: '设备维修工单', desc: '记录故障现象、备件消耗、MTTR计算', color: 'orange' },
    ECR: { name: '工艺变更申请', desc: '风险评估、受影响工单自动关联', color: 'blue' },
    FAI: { name: '首件检验单', desc: '关键尺寸实测值与公差自动对比', color: 'green' },
    SCRAP: { name: '报废申请单', desc: '成本估算、财务审批流', color: 'default' },
  }

  return (
    <Card title="📝 程序工单模板引擎">
      {/* 模板选择区 */}
      <Space wrap style={{ marginBottom: 16 }}>
        {templates.map((tpl: any) => (
          <Button
            key={tpl.template_code}
            type={selectedCode === tpl.template_code ? 'primary' : 'default'}
            onClick={() => handleSelectTemplate(tpl.template_code)}
            size="large"
            icon={<FileTextOutlined />}
          >
            {templateMeta[tpl.template_code]?.name || tpl.name}
          </Button>
        ))}
      </Space>

      {/* 选中模板的JSON Schema字段预览 */}
      {selectedCode && fields.length > 0 && (
        <Card size="small" title={`${templateMeta[selectedCode]?.name} - 动态表单字段`} style={{ marginBottom: 16 }}>
          <Descriptions column={2} size="small">
            {fields.map((field: any) => (
              <Descriptions.Item key={field.key} label={field.label}>
                <Tag color={field.required ? 'red' : 'default'}>
                  {field.type}{field.required ? ' *' : ''}
                </Tag>
                {field.options && field.options.map((opt: string) => (
                  <Tag key={opt} style={{ marginLeft: 4 }}>{opt}</Tag>
                ))}
              </Descriptions.Item>
            ))}
          </Descriptions>
        </Card>
      )}

      <Button
        type="primary"
        icon={<PlusOutlined />}
        onClick={() => setFormVisible(true)}
        disabled={!selectedCode}
      >
        基于模板创建程序工单
      </Button>

      {/* 创建工单弹窗 */}
      <Modal
        title={selectedCode ? `基于 ${templateMeta[selectedCode]?.name} 创建工单` : '请选择模板'}
        open={formVisible}
        onOk={handleCreate}
        onCancel={() => setFormVisible(false)}
        okText="创建"
        cancelText="取消"
        width={700}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="工单标题" rules={[{ required: true }]}>
            <Input placeholder={`例：${templateMeta[selectedCode]?.name} - 20260722-001`} />
          </Form.Item>
          <Form.Item name="data" label="模板数据（JSON）" extra="此处为简化版，实际应使用前端JSON Schema渲染器生成UI">
            <Input.TextArea rows={8} placeholder='{"defect_code":"DC-001","severity":"major"}' />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}


