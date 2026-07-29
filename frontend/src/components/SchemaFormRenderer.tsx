/**
 * SchemaFormRenderer - 基于 form-render (X-Render) 的动态表单渲染器
 *
 * 将后端工单模板的字段 schema（key/label/type/required/options）
 * 转换为 form-render 标准 JSON Schema，自动渲染 Ant Design 表单控件。
 *
 * 字段类型映射：
 * - string      → Input
 * - text        → TextArea
 * - select      → Select（options 自动生成）
 * - integer     → InputNumber（整数）
 * - float       → InputNumber
 * - date        → DatePicker
 * - boolean     → Switch
 * - json_array  → 可编辑表格（tableList）
 * - json_object → TextArea + JSON 格式校验
 */
import React, { useMemo } from 'react'
import FormRender, { useForm } from 'form-render'

/** 后端模板字段定义 */
export interface TemplateField {
  key: string
  label: string
  type: string
  required?: boolean
  options?: string[]
}

/** json_array 通用表格列结构 */
const ARRAY_ITEM_SCHEMA = {
  type: 'object' as const,
  properties: {
    name: { title: '名称/项目', type: 'string', widget: 'input' },
    value: { title: '数值/数量', type: 'string', widget: 'input' },
    remark: { title: '备注', type: 'string', widget: 'input' },
  },
}

/** 后端字段 → form-render JSON Schema 单项 */
function convertField(field: TemplateField): Record<string, any> {
  const base: Record<string, any> = {
    title: field.label,
    required: !!field.required,
  }

  switch (field.type) {
    case 'string':
      return { ...base, type: 'string', widget: 'input' }
    case 'text':
      return { ...base, type: 'string', widget: 'textArea', props: { rows: 3, showCount: true } }
    case 'select':
      return {
        ...base,
        type: 'string',
        widget: 'select',
        props: {
          options: (field.options || []).map((opt) => ({ label: opt, value: opt })),
          placeholder: `请选择${field.label}`,
        },
      }
    case 'integer':
      return { ...base, type: 'number', widget: 'inputNumber', props: { precision: 0, min: 0, style: { width: '100%' } } }
    case 'float':
      return { ...base, type: 'number', widget: 'inputNumber', props: { precision: 2, min: 0, style: { width: '100%' } } }
    case 'date':
      return { ...base, type: 'string', widget: 'datePicker', props: { format: 'YYYY-MM-DD', style: { width: '100%' } } }
    case 'boolean':
      return { ...base, type: 'boolean', widget: 'switch' }
    case 'json_array':
    case 'array':
      return {
        ...base,
        type: 'array',
        widget: 'tableList',
        items: ARRAY_ITEM_SCHEMA,
        props: { hideCopy: true, hideMove: true },
      }
    case 'json_object':
      return {
        ...base,
        type: 'string',
        widget: 'textArea',
        props: { rows: 4, placeholder: '请输入 JSON 对象，如 {"key": "value"}' },
        rules: [
          {
            validator: (_: any, value: string) => {
              if (!value) return true
              try {
                const parsed = JSON.parse(value)
                if (typeof parsed !== 'object' || Array.isArray(parsed)) return false
                return true
              } catch {
                return false
              }
            },
            message: '请输入合法的 JSON 对象格式',
          },
        ],
      }
    default:
      return { ...base, type: 'string', widget: 'input' }
  }
}

/** 后端模板字段列表 → form-render 完整 JSON Schema */
export function buildFormSchema(fields: TemplateField[]): Record<string, any> {
  const properties: Record<string, any> = {}
  for (const field of fields) {
    properties[field.key] = convertField(field)
  }
  return {
    type: 'object',
    displayType: 'row',
    labelCol: 6,
    fieldCol: 17,
    properties,
  }
}

/** 提交前数据后处理：json_object 字符串 → 对象 */
export function normalizeFormData(fields: TemplateField[], data: Record<string, any>): Record<string, any> {
  const result = { ...data }
  for (const field of fields) {
    if (field.type === 'json_object' && typeof result[field.key] === 'string' && result[field.key]) {
      try {
        result[field.key] = JSON.parse(result[field.key])
      } catch {
        /* 校验已拦截，此处兜底 */
      }
    }
  }
  return result
}

interface SchemaFormRendererProps {
  fields: TemplateField[]
  form: ReturnType<typeof useForm>
  onFinish?: (data: Record<string, any>) => void
  watch?: Record<string, any>
}

/** 动态表单渲染器：传入后端字段定义，自动渲染对应 antd 控件 */
const SchemaFormRenderer: React.FC<SchemaFormRendererProps> = ({ fields, form, onFinish, watch }) => {
  const schema = useMemo(() => buildFormSchema(fields), [fields])

  return (
    <FormRender
      form={form}
      schema={schema}
      onFinish={onFinish ? (data) => onFinish(normalizeFormData(fields, data)) : undefined}
      watch={watch}
      footer={false}
    />
  )
}

export default SchemaFormRenderer
