

import { useState, useEffect, useRef, lazy, Suspense } from 'react'
import { Card, Button, Form, Input, message, Tag, Descriptions, Space, Modal, Spin } from 'antd'
import { PlusOutlined, FileTextOutlined, TableOutlined } from '@ant-design/icons'
import axios from '../../services/api'
import { useForm } from 'form-render'
import SchemaFormRenderer, { TemplateField } from '../../components/SchemaFormRenderer'
import type { SpreadsheetEditorHandle } from '../../components/SpreadsheetEditor'

// Univer 体积较大，懒加载：仅在打开电子表格弹窗时才下载对应分包
const SpreadsheetEditor = lazy(() => import('../../components/SpreadsheetEditor'))

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

const MODULE_LABEL: Record<string, string> = {
  qms: '品质 QMS', production: '生产制造', wms: '仓储物流', pmc: 'PMC 计划', pp: 'PMC 计划', equipment: '设备管理',
}

export default function WorkOrderTemplatesPage() {
  const [templates, setTemplates] = useState<any[]>([])
  const [fields, setFields] = useState<TemplateField[]>([])
  const [selectedCode, setSelectedCode] = useState('')
  const [selectedName, setSelectedName] = useState('')
  const [formVisible, setFormVisible] = useState(false)
  const [titleForm] = Form.useForm()
  const schemaForm = useForm()
  const factoryId = localStorage.getItem('active_factory_id') || 'FAC_MECH_001'

  // 电子表格录入弹窗（json_array 字段用类 Excel 方式填写）
  const [sheetField, setSheetField] = useState<TemplateField | null>(null)
  const sheetRef = useRef<SpreadsheetEditorHandle>(null)

  const fetchTemplates = async () => {
    try {
      // 统一 mes 端点：直接返回数组，按 x-factory-id 过滤当前厂
      const res = await axios.get(`${API_BASE}/work-order-templates`, { headers: { 'X-Factory-Id': factoryId } })
      setTemplates(Array.isArray(res) ? res : [])
    } catch (err) {
      console.error('获取模板列表失败:', err)
    }
  }

  useEffect(() => {
    fetchTemplates()
  }, [])

  const handleSelectTemplate = (tpl: any) => {
    setSelectedCode(tpl.template_code)
    setSelectedName(tpl.template_name)
    // 字段定义直接来自模板 form_fields（无需二次请求）
    setFields((tpl.form_fields || []).map((f: any) => ({ ...f, key: f.key, label: f.label, type: f.type, required: !!f.required, options: f.options })))
  }

  const handleCreate = async () => {
    try {
      const titleValues = await titleForm.validateFields()
      const data = await schemaForm.validateFields()
      const result: any = await axios.post(`${API_BASE}/work-order-templates/create`, {
        factory_id: factoryId,
        template_code: selectedCode,
        title: titleValues.title,
        data: data || {},
      }, { headers: { 'X-Factory-Id': factoryId } })
      message.success(`程序工单创建成功！工单号：${result?.work_order_code || '-'}`)
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
    <Card title="📝 程序工单模板引擎（行业标准模板库）">
      {/* 模板选择区：按模块分组 */}
      {Object.keys(MODULE_LABEL).map((mod) => {
        const items = templates.filter((t) => (t.module || 'production') === mod)
        if (items.length === 0) return null
        return (
          <div key={mod} style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, color: '#8c8c8c', fontWeight: 700, marginBottom: 6 }}>{MODULE_LABEL[mod]}</div>
            <Space wrap>
              {items.map((tpl: any) => (
                <Button
                  key={`${tpl.template_code}-${tpl.id}`}
                  type={selectedCode === tpl.template_code ? 'primary' : 'default'}
                  onClick={() => handleSelectTemplate(tpl)}
                  icon={<FileTextOutlined />}
                >
                  {tpl.template_name}{!tpl.factory_id && <span style={{ color: '#52c41a', fontWeight: 700 }}> ·公共</span>}
                </Button>
              ))}
            </Space>
          </div>
        )
      })}

      {/* 选中模板的JSON Schema字段预览 */}
      {selectedCode && fields.length > 0 && (
        <Card size="small" title={`${selectedName} - 动态表单字段`} style={{ marginBottom: 16, marginTop: 12 }}>
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
        style={{ marginTop: 8 }}
      >
        基于模板创建程序工单
      </Button>

      {/* 创建工单弹窗：动态表单（form-render 根据模板 schema 自动渲染控件） */}
      <Modal
        title={selectedCode ? `基于 ${selectedName} 创建工单` : '请选择模板'}
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
            <Input placeholder={`例：${selectedName} - ${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`} />
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

