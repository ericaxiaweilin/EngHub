

import { useState, useEffect, useRef, lazy, Suspense } from 'react'
import { Card, Button, Form, Input, message, Tag, Descriptions, Space, Modal, Spin } from 'antd'
import { PlusOutlined, FileTextOutlined, TableOutlined } from '@ant-design/icons'
import axios from 'axios'
import { useForm } from 'form-render'
import { workOrderTemplatesApi } from '../../services/workOrderTemplates'
import SchemaFormRenderer, { TemplateField } from '../../components/SchemaFormRenderer'
import type { SpreadsheetEditorHandle } from '../../components/SpreadsheetEditor'

// Univer 体积较大，懒加载：仅在打开电子表格弹窗时才下载对应分包
const SpreadsheetEditor = lazy(() => import('../../components/SpreadsheetEditor'))

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

export default function WorkOrderTemplatesPage() {
  const [templates, setTemplates] = useState<any[]>([])
  const [fields, setFields] = useState<TemplateField[]>([])
  const [selectedCode, setSelectedCode] = useState('')
  const [formVisible, setFormVisible] = useState(false)
  const [titleForm] = Form.useForm()
  const schemaForm = useForm()

  // 电子表格录入弹窗（json_array 字段用类 Excel 方式填写）
  const [sheetField, setSheetField] = useState<TemplateField | null>(null)
  const sheetRef = useRef<SpreadsheetEditorHandle>(null)

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
      const titleValues = await titleForm.validateFields()
      // 触发 form-render 校验，通过后由 onFinish 提交
      const data = await schemaForm.validateFields()
      const result = await workOrderTemplatesApi.createFromTemplate({
        factory_id: 'factory-001',
        template_code: selectedCode,
        title: titleValues.title,
        data: data || {},
      })
      message.success(`程序工单创建成功！工单号：${result.data?.work_order_code || '-'}`)
      titleForm.resetFields()
      schemaForm.resetFields()
      setFormVisible(false)
    } catch (err: any) {
      if (err?.response?.data?.detail) {
        message.error(err.response.data.detail)
      } else if (err?.errorFields) {
        message.warning('请检查表单必填项')
      }
    }
  }

  const templateMeta: Record<string, { name: string; desc: string; color: string }> = {
    NCR: { name: '品质异常单', desc: '关联缺陷代码、8D报告、处置方式', color: 'red' },
    MAINT: { name: '设备维修工单', desc: '记录故障现象、备件消耗、MTTR计算', color: 'orange' },
    ECR: { name: '工艺变更申请', desc: '风险评估、受影响工单自动关联', color: 'blue' },
    FAI: { name: '首件检验单', desc: '关键尺寸实测值与公差自动对比', color: 'green' },
    SCRAP: { name: '报废申请单', desc: '成本估算、财务审批流', color: 'default' },
  }

  /** 电子表格确认：二维数组 → [{name, value, remark}] 写入表单字段 */
  const handleSheetConfirm = () => {
    if (!sheetField || !sheetRef.current) return
    const rows = sheetRef.current.getData().filter((row) => row.some((c) => c !== '' && c !== null && c !== undefined))
    const arr = rows.map((row) => ({
      name: row[0] != null ? String(row[0]) : '',
      value: row[1] != null ? String(row[1]) : '',
      remark: row[2] != null ? String(row[2]) : '',
    }))
    schemaForm.setValueByPath(sheetField.key, arr)
    message.success(`已录入 ${arr.length} 行数据到「${sheetField.label}」`)
    setSheetField(null)
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
                {(field.type === 'json_array' || field.type === 'array') && (
                  <Button
                    type="link"
                    size="small"
                    icon={<TableOutlined />}
                    style={{ padding: '0 4px' }}
                    onClick={() => setSheetField(field)}
                  >
                    电子表格录入
                  </Button>
                )}
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

      {/* 创建工单弹窗：动态表单（form-render 根据模板 schema 自动渲染控件） */}
      <Modal
        title={selectedCode ? `基于 ${templateMeta[selectedCode]?.name} 创建工单` : '请选择模板'}
        open={formVisible}
        onOk={handleCreate}
        onCancel={() => setFormVisible(false)}
        okText="创建"
        cancelText="取消"
        width={760}
        destroyOnClose
      >
        <Form form={titleForm} layout="vertical" style={{ marginBottom: 8 }}>
          <Form.Item name="title" label="工单标题" rules={[{ required: true, message: '请输入工单标题' }]}>
            <Input placeholder={`例：${templateMeta[selectedCode]?.name} - 20260722-001`} />
          </Form.Item>
        </Form>
        {fields.length > 0 && (
          <SchemaFormRenderer fields={fields} form={schemaForm} />
        )}
      </Modal>

      {/* 电子表格录入弹窗（类 Excel，支持公式/粘贴） */}
      <Modal
        title={sheetField ? `${sheetField.label} - 电子表格录入` : '电子表格录入'}
        open={!!sheetField}
        onOk={handleSheetConfirm}
        onCancel={() => setSheetField(null)}
        okText="确认录入"
        cancelText="取消"
        width={900}
        destroyOnClose
      >
        <div style={{ marginBottom: 8, color: '#8c8c8c', fontSize: 12 }}>
          支持从 Excel 直接复制粘贴 · 列结构：名称/项目 | 数值/数量 | 备注
        </div>
        {sheetField && (
          <Suspense fallback={<div style={{ height: 380, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin tip="加载电子表格组件..." /></div>}>
            <SpreadsheetEditor
              ref={sheetRef}
              headers={['名称/项目', '数值/数量', '备注']}
              height={380}
              sheetName={sheetField.label}
            />
          </Suspense>
        )}
      </Modal>
    </Card>
  )
}


