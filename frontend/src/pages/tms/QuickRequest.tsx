/**
 * 快速工单 - 员工端小工单快速发起页（v2.6 行业模板增强）
 * - 呼叫请求：4 类呼叫 × 行业定制字段（设备故障/物料呼叫/品质异常/支援请求）
 * - 工单模板：5 种通用工单模板（NCR/MAINT/ECR/FAI/SCRAP），参考行业标准
 * - 我的请求：默认隐藏，抽屉式查看
 */
import React, { useState, useEffect, useCallback } from 'react'
import {
  Card, Row, Col, Form, Input, Select, Button, message, Table, Tag, Space,
  Typography, Radio, Drawer, InputNumber, Divider, DatePicker, Tooltip, Upload, Modal,
} from 'antd'
import type { UploadFile, UploadProps } from 'antd'
import {
  PhoneOutlined, ToolOutlined, ExperimentOutlined, AuditOutlined,
  DeleteOutlined, AlertOutlined, ThunderboltOutlined, HistoryOutlined,
  ExclamationCircleOutlined, SafetyCertificateOutlined, SwapOutlined,
  ArrowLeftOutlined, ReloadOutlined, PlusOutlined, CameraOutlined,
  VideoCameraOutlined, EyeOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { tmsApi } from '../../services/tms'
import api from '../../services/api'
import { getStoredUser } from '../../services/auth'

const { TextArea } = Input
const { Text, Title } = Typography

/* ==================== 呼叫请求类型 ==================== */
const CALL_TYPES = [
  { value: 'equipment_fault', label: '设备故障呼叫', icon: <ToolOutlined />, color: '#f5222d', desc: '设备停机/异常报警' },
  { value: 'material_call', label: '物料呼叫', icon: <AlertOutlined />, color: '#fa8c16', desc: '缺料/补料/退料' },
  { value: 'quality_call', label: '品质呼叫', icon: <ExperimentOutlined />, color: '#722ed1', desc: '品质异常/巡检不合格' },
  { value: 'support_call', label: '支援呼叫', icon: <PhoneOutlined />, color: '#1890ff', desc: '技术支援/人员协助' },
]

/* ==================== 行业工单模板定义 ==================== */
interface TemplateFieldDef {
  key: string
  label: string
  type: 'text' | 'textarea' | 'select' | 'number' | 'date' | 'radio'
  required?: boolean
  options?: string[]
  placeholder?: string
  suffix?: string
  span?: number // 栅格占比(24满行)
}

interface TemplateDef {
  code: string
  name: string
  nameEn: string
  desc: string
  icon: React.ReactNode
  color: string
  bgColor: string
  badge: string // 卡片角标说明
  standard: string // 参考标准
  fields: TemplateFieldDef[]
}

const INDUSTRY_TEMPLATES: TemplateDef[] = [
  {
    code: 'NCR',
    name: '品质异常单',
    nameEn: 'Non-Conformance Report',
    desc: '记录不合格品/过程偏差，触发8D纠正措施流程，确保质量体系闭环',
    icon: <ExclamationCircleOutlined />,
    color: '#f5222d',
    bgColor: '#fff1f0',
    badge: '优先级: 高 (Critical)',
    standard: 'ISO 9001:2015 §8.7 / IATF 16949',
    fields: [
      { key: 'product_code', label: '产品编码', type: 'text', required: true, placeholder: '如: PRD-A1023', span: 12 },
      { key: 'batch_no', label: '批次号', type: 'text', required: true, placeholder: '如: B2026-0715-03', span: 12 },
      { key: 'defect_type', label: '缺陷类型', type: 'select', required: true, options: ['外观缺陷', '尺寸超差', '功能失效', '材料不良', '装配错误', '包装破损', '其他'] },
      { key: 'defect_qty', label: '不良数量', type: 'number', required: true, suffix: 'pcs', span: 8 },
      { key: 'sample_size', label: '抽样数', type: 'number', suffix: 'pcs', span: 8 },
      { key: 'batch_qty', label: '批次总量', type: 'number', suffix: 'pcs', span: 8 },
      { key: 'severity', label: '严重等级', type: 'radio', required: true, options: ['Critical 致命', 'Major 严重', 'Minor 一般'] },
      { key: 'defect_desc', label: '不良现象描述', type: 'textarea', required: true, placeholder: '描述缺陷现象、发现工位、检测方式...' },
      { key: 'containment', label: '围堵措施', type: 'select', options: ['隔离批次', '停线检查', '加严检验', '全数筛选', '暂不处理'] },
      { key: 'disposition', label: '处置方式', type: 'select', options: ['返工 Rework', '返修 Repair', '让步接收 Concession', '报废 Scrap', '退供应商 RTV'] },
      { key: 'root_cause', label: '初步根因分析', type: 'textarea', placeholder: '人/机/料/法/环 初步判断...' },
      { key: 'notify_supplier', label: '是否需通知供应商', type: 'radio', options: ['是', '否'] },
    ],
  },
  {
    code: 'MAINT',
    name: '设备维修工单',
    nameEn: 'Maintenance Work Order',
    desc: '设备故障报修/预防性维护请求，含停机影响评估与备件需求，追踪MTTR',
    icon: <ToolOutlined />,
    color: '#fa8c16',
    bgColor: '#fff7e6',
    badge: '响应时间: < 15min',
    standard: 'ISO 55001 资产管理 / TPM',
    fields: [
      { key: 'equipment_code', label: '设备编号', type: 'text', required: true, placeholder: '如: EQ-CNC-012', span: 12 },
      { key: 'equipment_name', label: '设备名称', type: 'text', required: true, placeholder: '如: CNC加工中心 #12', span: 12 },
      { key: 'location', label: '安装位置', type: 'text', required: true, placeholder: '如: A栋2层 机加工区', span: 12 },
      { key: 'fault_type', label: '故障类型', type: 'select', required: true, options: ['机械故障', '电气故障', '液压/气动', '控制系统/PLC', '精度异常', '异响/振动', '泄漏', '其他'] },
      { key: 'maint_type', label: '维修类型', type: 'radio', required: true, options: ['故障维修 BM', '预防维护 PM', '预测维护 PdM', '改善维修 CM'] },
      { key: 'downtime_start', label: '停机开始时间', type: 'date' },
      { key: 'production_impact', label: '生产影响', type: 'radio', required: true, options: ['整线停产', '单工位停机', '降速运行', '无影响'] },
      { key: 'impact_qty', label: '影响产量(预估)', type: 'number', suffix: 'pcs/班', span: 12 },
      { key: 'fault_desc', label: '故障现象描述', type: 'textarea', required: true, placeholder: '报警代码、异常现象、发生经过...' },
      { key: 'spare_parts', label: '所需备件', type: 'textarea', placeholder: '备件名称/型号/数量...' },
      { key: 'safety_risk', label: '安全风险', type: 'radio', options: ['高(需LOTO)', '中', '低'] },
      { key: 'need_vendor', label: '是否需外部厂商', type: 'radio', options: ['是', '否'] },
    ],
  },
  {
    code: 'ECR',
    name: '工艺变更申请',
    nameEn: 'Engineering Change Request',
    desc: '申请修改工艺参数/材料替代/流程调整，含风险评估与受影响范围分析',
    icon: <SwapOutlined />,
    color: '#1890ff',
    bgColor: '#e6f7ff',
    badge: '需审批: 3 层级',
    standard: 'ISO 9001 §8.5.6 / IATF PPAP',
    fields: [
      { key: 'change_type', label: '变更类型', type: 'select', required: true, options: ['工艺参数变更', '材料替代', '设备更换', '供应商变更', '设计变更', '流程优化', '成本降低 VA/VE'] },
      { key: 'product_line', label: '涉及产品/产线', type: 'text', required: true, placeholder: '如: PRD-A1023 / Line 4' },
      { key: 'current_spec', label: '现行规格/参数', type: 'textarea', required: true, placeholder: '当前工艺参数、材料规格、作业标准...' },
      { key: 'proposed_spec', label: '变更后规格/参数', type: 'textarea', required: true, placeholder: '拟变更的参数值、替代方案...' },
      { key: 'change_reason', label: '变更原因', type: 'select', required: true, options: ['品质改善', '成本降低', '交期缩短', '安全合规', '客户请求', '供应商停产', '持续改善'] },
      { key: 'risk_level', label: '风险等级', type: 'radio', required: true, options: ['高(需PPAP)', '中(需验证)', '低(直接实施)'] },
      { key: 'affected_wos', label: '受影响工单/批次', type: 'textarea', placeholder: '在制品工单号、库存批次...' },
      { key: 'validation_plan', label: '验证计划', type: 'textarea', placeholder: '试产数量、检验项目、验收标准...' },
      { key: 'effective_date', label: '期望生效日期', type: 'date' },
      { key: 'customer_notify', label: '是否需客户批准', type: 'radio', options: ['是', '否'] },
    ],
  },
  {
    code: 'FAI',
    name: '首件检验单',
    nameEn: 'First Article Inspection',
    desc: '批量生产前验证首件产品符合工程规格，覆盖关键尺寸与功能测试',
    icon: <SafetyCertificateOutlined />,
    color: '#52c41a',
    bgColor: '#f6ffed',
    badge: '状态: 等待采样',
    standard: 'AS9102 / PPAP §7 / IATF 16949',
    fields: [
      { key: 'work_order_no', label: '工单号', type: 'text', required: true, placeholder: '如: WO-2026-04521', span: 12 },
      { key: 'product_code', label: '产品编码', type: 'text', required: true, placeholder: '如: PRD-A1023', span: 12 },
      { key: 'process_step', label: '工序/工站', type: 'text', required: true, placeholder: '如: OP30 精加工 / ST-CNC-05' },
      { key: 'trigger', label: '首件触发原因', type: 'select', required: true, options: ['新批次开始', '换模/换刀', '设备维修后', '工艺参数调整', '换班/换人', '材料批次变更'] },
      { key: 'sample_qty', label: '抽样数量', type: 'number', required: true, suffix: 'pcs', span: 8 },
      { key: 'serial_no', label: '首件序列号', type: 'text', placeholder: '如: SN-001', span: 16 },
      { key: 'key_dimensions', label: '关键尺寸检测', type: 'textarea', required: true, placeholder: '特性编号 | 标准值±公差 | 实测值\n如: D1 | Ø25.0±0.05 | Ø25.02' },
      { key: 'visual_check', label: '外观检查', type: 'radio', required: true, options: ['合格', '不合格', '有条件接受'] },
      { key: 'functional_test', label: '功能测试', type: 'radio', required: true, options: ['合格', '不合格', '不适用'] },
      { key: 'measuring_tools', label: '使用量具', type: 'textarea', placeholder: '量具名称/编号/校准有效期...' },
      { key: 'inspector', label: '检验员', type: 'text', span: 12 },
      { key: 'result', label: '判定结果', type: 'radio', required: true, options: ['合格-允许量产', '不合格-停线整改', '有条件放行'] },
    ],
  },
  {
    code: 'SCRAP',
    name: '报废申请单',
    nameEn: 'Scrap Disposal Request',
    desc: '将无法修复的在制品/原材料正式报废，含成本估算与多级审批',
    icon: <DeleteOutlined />,
    color: '#595959',
    bgColor: '#fafafa',
    badge: '合规性: ISO-9001',
    standard: 'ISO 9001 §8.7 / 财务合规',
    fields: [
      { key: 'material_code', label: '物料/产品编码', type: 'text', required: true, placeholder: '如: MAT-AL6061 / PRD-A1023', span: 12 },
      { key: 'batch_no', label: '批次号', type: 'text', required: true, placeholder: '如: B2026-0701-11', span: 12 },
      { key: 'scrap_qty', label: '报废数量', type: 'number', required: true, suffix: 'pcs', span: 8 },
      { key: 'unit_cost', label: '单位成本', type: 'number', required: true, suffix: '元', span: 8 },
      { key: 'total_cost', label: '总损失金额', type: 'number', suffix: '元', span: 8 },
      { key: 'scrap_reason', label: '报废原因', type: 'select', required: true, options: ['加工不良', '材料缺陷', '设计变更', '过期变质', '客户取消', '试验损耗', '其他'] },
      { key: 'responsible_dept', label: '责任部门', type: 'select', options: ['生产部', '品质部', '仓储物流', '采购/供应商', '工程部', '客户责任'] },
      { key: 'detail_desc', label: '报废明细描述', type: 'textarea', required: true, placeholder: '报废品状态、缺陷详情、关联NCR编号...' },
      { key: 'disposal_method', label: '处置方式', type: 'radio', required: true, options: ['销毁', '回收再利用', '退供应商', '降级使用'] },
      { key: 'corrective_action', label: '纠正预防措施', type: 'textarea', placeholder: '防止再发措施...' },
      { key: 'attachments_note', label: '附件说明', type: 'text', placeholder: '照片/NCR报告/检验记录编号' },
    ],
  },
]

/* ==================== 呼叫类型专属字段 ==================== */
const CALL_EXTRA_FIELDS: Record<string, TemplateFieldDef[]> = {
  equipment_fault: [
    { key: 'equipment_code', label: '设备编号', type: 'text', required: true, placeholder: '如: EQ-CNC-012', span: 12 },
    { key: 'fault_symptom', label: '故障现象', type: 'select', required: true, options: ['完全停机', '异常报警', '精度异常', '异响/振动', '泄漏', '其他'] },
    { key: 'alarm_code', label: '报警代码', type: 'text', placeholder: '如: ALM-4021', span: 12 },
    { key: 'line_stopped', label: '是否停线', type: 'radio', required: true, options: ['是-整线停', '是-单站停', '否-可继续'] },
  ],
  material_call: [
    { key: 'material_code', label: '物料编码', type: 'text', required: true, placeholder: '如: MAT-AL6061', span: 12 },
    { key: 'need_qty', label: '需求数量', type: 'number', required: true, suffix: 'pcs/kg', span: 12 },
    { key: 'call_reason', label: '呼叫原因', type: 'select', required: true, options: ['缺料', '补料(损耗超标)', '退料(不良)', '换料(批次切换)'] },
    { key: 'need_by', label: '需求时限', type: 'radio', required: true, options: ['立即(<15min)', '1小时内', '本班次内'] },
  ],
  quality_call: [
    { key: 'product_code', label: '产品编码', type: 'text', required: true, placeholder: '如: PRD-A1023', span: 12 },
    { key: 'defect_type', label: '异常类型', type: 'select', required: true, options: ['外观不良', '尺寸超差', '功能异常', '过程参数偏移', '客户投诉'] },
    { key: 'defect_qty', label: '不良数量', type: 'number', required: true, suffix: 'pcs', span: 12 },
    { key: 'lot_hold', label: '是否需批次冻结', type: 'radio', required: true, options: ['是', '否'] },
  ],
  support_call: [
    { key: 'support_type', label: '支援类型', type: 'select', required: true, options: ['设备操作指导', '工艺技术支持', '品质判定协助', '人员临时调配', 'IT/系统问题'] },
    { key: 'skill_required', label: '所需技能', type: 'text', placeholder: '如: PLC编程 / 焊接 / 三坐标', span: 12 },
    { key: 'headcount', label: '需求人数', type: 'number', suffix: '人', span: 12 },
    { key: 'duration', label: '预计时长', type: 'radio', options: ['<30min', '30min-2h', '2h-1班', '>1班'] },
  ],
}

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

/* ==================== 主组件 ==================== */
const QuickRequest: React.FC = () => {
  const user = getStoredUser()
  const [mode, setMode] = useState<'call' | 'template'>('template')
  const [callForm] = Form.useForm()
  const [templateForm] = Form.useForm()
  const [selectedCallType, setSelectedCallType] = useState('equipment_fault')
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateDef | null>(null)
  const [myRequests, setMyRequests] = useState<any[]>([])
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerFilter, setDrawerFilter] = useState<'all' | 'active' | 'done'>('all')
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [uploadedFileIds, setUploadedFileIds] = useState<string[]>([])
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewUrl, setPreviewUrl] = useState('')
  const [previewIsVideo, setPreviewIsVideo] = useState(false)

  const fetchMyRequests = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await tmsApi.listTasks({ page_size: 50 })
      const tasks = res.items || res.data?.items || []
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

  /* ---------- 提交呼叫请求 ---------- */
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
          extra_fields: values,
          attachments: uploadedFileIds,
        } as any,
      })
      message.success('呼叫请求已发送，等待响应')
      callForm.resetFields()
      setFileList([])
      setUploadedFileIds([])
      fetchMyRequests()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error('提交失败: ' + (e?.response?.data?.detail || e.message))
    } finally {
      setSubmitting(false)
    }
  }

  /* ---------- 文件上传处理 ---------- */
  const handleUpload: UploadProps['customRequest'] = async (options) => {
    const { file, onSuccess, onError } = options
    const formData = new FormData()
    formData.append('file', file as File)
    formData.append('related_type', 'work_order_draft')
    try {
      const res: any = await api.post('/api/v1/files/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const fileId = res.id || res.data?.id
      if (fileId) {
        setUploadedFileIds(prev => [...prev, fileId])
      }
      onSuccess?.(res)
    } catch (e: any) {
      message.error('上传失败: ' + (e?.response?.data?.detail || e.message))
      onError?.(e)
    }
  }

  const handlePreview = (file: UploadFile) => {
    const url = file.url || (file.originFileObj ? URL.createObjectURL(file.originFileObj) : '')
    const isVideo = (file.type || '').startsWith('video/')
    setPreviewUrl(url)
    setPreviewIsVideo(isVideo)
    setPreviewOpen(true)
  }

  const beforeUpload = (file: File) => {
    const isImage = file.type.startsWith('image/')
    const isVideo = file.type.startsWith('video/')
    if (!isImage && !isVideo) {
      message.error('仅支持上传图片或视频文件')
      return Upload.LIST_IGNORE
    }
    const isLt100M = file.size / 1024 / 1024 < 100
    if (!isLt100M) {
      message.error('文件大小不能超过 100MB')
      return Upload.LIST_IGNORE
    }
    return true
  }

  /* ---------- 提交模板工单 ---------- */
  const submitTemplate = async () => {
    if (!selectedTemplate) return
    try {
      const values = await templateForm.validateFields()
      setSubmitting(true)
      await tmsApi.createTask({
        title: `${selectedTemplate.name} - ${user?.username}`,
        task_type: 'work_order_template',
        description: JSON.stringify(values),
        priority: values.priority || 'medium',
        metadata: {
          template_code: selectedTemplate.code,
          template_name: selectedTemplate.name,
          form_data: values,
          requested_by: user?.username,
          attachments: uploadedFileIds,
        } as any,
      })
      message.success(`${selectedTemplate.name} 已创建`)
      templateForm.resetFields()
      setFileList([])
      setUploadedFileIds([])
      setSelectedTemplate(null)
      fetchMyRequests()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error('提交失败: ' + (e?.response?.data?.detail || e.message))
    } finally {
      setSubmitting(false)
    }
  }

  /* ---------- 动态字段渲染 ---------- */
  const renderField = (field: TemplateFieldDef) => {
    const rules = field.required ? [{ required: true, message: `请填写${field.label}` }] : []
    const colProps = { span: field.span || 24 }
    let control: React.ReactNode
    switch (field.type) {
      case 'textarea':
        control = <TextArea rows={3} placeholder={field.placeholder} />
        break
      case 'select':
        control = <Select placeholder="请选择" options={(field.options || []).map(o => ({ value: o, label: o }))} />
        break
      case 'number':
        control = <InputNumber style={{ width: '100%' }} placeholder={field.placeholder} addonAfter={field.suffix} min={0} />
        break
      case 'date':
        control = <DatePicker showTime style={{ width: '100%' }} placeholder={field.placeholder || '选择时间'} />
        break
      case 'radio':
        control = (
          <Radio.Group>
            {(field.options || []).map(o => <Radio.Button key={o} value={o}>{o}</Radio.Button>)}
          </Radio.Group>
        )
        break
      default:
        control = <Input placeholder={field.placeholder} />
    }
    return (
      <Col {...colProps} key={field.key}>
        <Form.Item name={field.key} label={field.label} rules={rules}>{control}</Form.Item>
      </Col>
    )
  }

  /* ---------- 抽屉过滤 ---------- */
  const filteredRequests = myRequests.filter(r => {
    if (drawerFilter === 'active') return !['completed', 'cancelled'].includes(r.status)
    if (drawerFilter === 'done') return r.status === 'completed'
    return true
  })

  const requestColumns = [
    {
      title: '类型', key: 'type', width: 120,
      render: (_: any, r: any) => r.task_type === 'call_request'
        ? <Tag color="red"><PhoneOutlined /> {CALL_TYPES.find(c => c.value === r.metadata?.call_type)?.label?.replace('呼叫', '') || '呼叫'}</Tag>
        : <Tag color="blue">{r.metadata?.template_name || INDUSTRY_TEMPLATES.find(t => t.code === r.metadata?.template_code)?.name || '工单'}</Tag>,
    },
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
    {
      title: '优先级', dataIndex: 'priority', key: 'priority', width: 70,
      render: (v: string) => { const p = PRIORITY_OPTIONS.find(o => o.value === v); return <Tag color={p?.color}>{p?.label || v}</Tag> },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 85,
      render: (v: string) => { const s = STATUS_MAP[v] || { color: 'default', text: v }; return <Tag color={s.color}>{s.text}</Tag> },
    },
    { title: '处理人', dataIndex: 'assigned_to', key: 'assignee', width: 85, render: (v: string) => v || '-' },
    { title: '时间', dataIndex: 'created_at', key: 'time', width: 110, render: (v: string) => v ? dayjs(v).format('MM-DD HH:mm') : '-' },
  ]

  const activeCount = myRequests.filter(r => !['completed', 'cancelled'].includes(r.status)).length

  /* ==================== 渲染 ==================== */
  return (
    <div style={{ padding: '0 4px' }}>
      {/* 页头 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 20 }}>
        <div>
          <Text type="secondary" style={{ fontSize: 11, letterSpacing: 2, textTransform: 'uppercase' }}>Operational Quick Actions</Text>
          <Title level={3} style={{ margin: '4px 0' }}>快速工单创建</Title>
          <Text type="secondary">选择工单类型以立即启动流程，系统将根据分类自动通知相关部门。</Text>
        </div>
        <Button icon={<HistoryOutlined />} onClick={() => { setDrawerOpen(true); fetchMyRequests() }}>
          查看我的请求 {activeCount > 0 && <Tag color="blue" style={{ marginLeft: 6 }}>{activeCount}</Tag>}
        </Button>
      </div>

      {/* 模式切换 */}
      <div style={{ marginBottom: 16 }}>
        <Radio.Group value={mode} onChange={e => setMode(e.target.value)} buttonStyle="solid" size="large">
          <Radio.Button value="template"><AuditOutlined /> 工单模板</Radio.Button>
          <Radio.Button value="call"><PhoneOutlined /> 呼叫请求</Radio.Button>
        </Radio.Group>
      </div>

      {mode === 'template' ? (
        !selectedTemplate ? (
          /* ---------- 模板卡片网格 ---------- */
          <Row gutter={[16, 16]}>
            {INDUSTRY_TEMPLATES.map(tpl => (
              <Col xs={24} sm={12} lg={8} key={tpl.code}>
                <Card
                  hoverable
                  onClick={() => { setSelectedTemplate(tpl); templateForm.resetFields() }}
                  style={{ height: '100%', borderRadius: 12, overflow: 'hidden' }}
                  bodyStyle={{ padding: 24, display: 'flex', flexDirection: 'column', height: '100%' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{
                      width: 52, height: 52, borderRadius: 12, background: tpl.bgColor,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 26, color: tpl.color,
                    }}>
                      {tpl.icon}
                    </div>
                    <Tag style={{ fontSize: 10 }}>{tpl.badge}</Tag>
                  </div>
                  <div style={{ marginTop: 16, flex: 1 }}>
                    <Text strong style={{ fontSize: 16 }}>{tpl.name}</Text>
                    <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>{tpl.nameEn}</Text>
                    <p style={{ color: '#666', fontSize: 13, marginTop: 8, marginBottom: 12 }}>{tpl.desc}</p>
                  </div>
                  <Divider style={{ margin: '0 0 10px' }} />
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Text type="secondary" style={{ fontSize: 11 }}>{tpl.standard}</Text>
                    <Text style={{ color: tpl.color, fontSize: 12 }}>{tpl.fields.length} 个字段 →</Text>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>
        ) : (
          /* ---------- 模板表单 ---------- */
          <Card
            title={
              <Space>
                <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => setSelectedTemplate(null)}>返回</Button>
                <span style={{ color: selectedTemplate.color }}>{selectedTemplate.icon}</span>
                <span>{selectedTemplate.name}</span>
                <Text type="secondary" style={{ fontSize: 12 }}>{selectedTemplate.nameEn}</Text>
              </Space>
            }
            extra={<Tag>{selectedTemplate.standard}</Tag>}
            style={{ borderRadius: 12 }}
          >
            <Form form={templateForm} layout="vertical" initialValues={{ priority: 'medium' }}>
              <Row gutter={16}>
                {selectedTemplate.fields.map(renderField)}
              </Row>
              <Divider orientation="left" plain>
                <CameraOutlined /> 现场照片 / 视频记录
              </Divider>
              <Form.Item>
                <Upload
                  listType="picture-card"
                  fileList={fileList}
                  customRequest={handleUpload}
                  beforeUpload={beforeUpload}
                  onPreview={handlePreview}
                  onChange={({ fileList: fl }) => setFileList(fl)}
                  accept="image/*,video/*"
                  multiple
                >
                  {fileList.length >= 20 ? null : (
                    <div>
                      <PlusOutlined />
                      <div style={{ marginTop: 6, fontSize: 12 }}>照片/视频</div>
                    </div>
                  )}
                </Upload>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  支持 JPG/PNG/MP4/MOV，单个文件≤100MB，最多20个。首件照片、缺陷取证、工艺记录等。
                </Text>
              </Form.Item>
              <Divider />
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item name="priority" label="优先级" rules={[{ required: true }]}>
                    <Select options={PRIORITY_OPTIONS.map(p => ({ value: p.value, label: p.label }))} />
                  </Form.Item>
                </Col>
                <Col span={16}>
                  <Form.Item name="remark" label="补充说明">
                    <Input placeholder="其他需要补充的信息..." />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="primary" block size="large" loading={submitting} onClick={submitTemplate}
                style={{ background: selectedTemplate.color, borderColor: selectedTemplate.color }}>
                创建{selectedTemplate.name}
              </Button>
            </Form>
          </Card>
        )
      ) : (
        /* ---------- 呼叫请求模式 ---------- */
        <Card style={{ borderRadius: 12, maxWidth: 720 }}>
          <Form form={callForm} layout="vertical" initialValues={{ priority: 'high', call_type: 'equipment_fault' }}>
            <Form.Item name="call_type" label="呼叫类型" rules={[{ required: true }]}>
              <Radio.Group onChange={e => setSelectedCallType(e.target.value)}>
                <Row gutter={[8, 8]}>
                  {CALL_TYPES.map(ct => (
                    <Col span={12} key={ct.value}>
                      <Tooltip title={ct.desc}>
                        <Radio.Button value={ct.value} style={{ width: '100%', textAlign: 'center', height: 44, lineHeight: '44px' }}>
                          <span style={{ color: ct.color, marginRight: 6 }}>{ct.icon}</span>{ct.label}
                        </Radio.Button>
                      </Tooltip>
                    </Col>
                  ))}
                </Row>
              </Radio.Group>
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item name="station" label="工位/位置" rules={[{ required: true, message: '请输入工位' }]}>
                  <Input placeholder="如: ST-ASM-01 / A栋2层" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="priority" label="紧急程度" rules={[{ required: true }]}>
                  <Radio.Group>
                    {PRIORITY_OPTIONS.map(p => <Radio.Button key={p.value} value={p.value}>{p.label}</Radio.Button>)}
                  </Radio.Group>
                </Form.Item>
              </Col>
            </Row>
            {/* 呼叫类型专属字段 */}
            <Divider orientation="left" plain style={{ fontSize: 13 }}>
              {CALL_TYPES.find(c => c.value === selectedCallType)?.label} - 专属信息
            </Divider>
            <Row gutter={16}>
              {(CALL_EXTRA_FIELDS[selectedCallType] || []).map(renderField)}
            </Row>
            <Divider />
            <Form.Item name="description" label="问题描述" rules={[{ required: true, message: '请描述问题' }]}>
              <TextArea rows={3} placeholder="简要描述现场情况..." />
            </Form.Item>
            <Form.Item label={<span><CameraOutlined /> 现场照片/视频</span>}>
              <Upload
                listType="picture-card"
                fileList={fileList}
                customRequest={handleUpload}
                beforeUpload={beforeUpload}
                onPreview={handlePreview}
                onChange={({ fileList: fl }) => setFileList(fl)}
                accept="image/*,video/*"
                multiple
              >
                {fileList.length >= 10 ? null : (
                  <div><PlusOutlined /><div style={{ marginTop: 4, fontSize: 11 }}>拍照/录像</div></div>
                )}
              </Upload>
            </Form.Item>
            <Button type="primary" block size="large" icon={<ThunderboltOutlined />} loading={submitting} onClick={submitCallRequest}>
              发送呼叫请求
            </Button>
          </Form>
        </Card>
      )}

      {/* ---------- 我的请求抽屉 ---------- */}
      <Drawer
        title={
          <Space>
            <HistoryOutlined />
            <span>我的请求</span>
            <Tag color="blue">{filteredRequests.length}</Tag>
          </Space>
        }
        placement="right"
        width={640}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchMyRequests}>刷新</Button>}
      >
        <div style={{ marginBottom: 16 }}>
          <Radio.Group value={drawerFilter} onChange={e => setDrawerFilter(e.target.value)} buttonStyle="solid" size="small">
            <Radio.Button value="all">全部</Radio.Button>
            <Radio.Button value="active">进行中</Radio.Button>
            <Radio.Button value="done">已完成</Radio.Button>
          </Radio.Group>
        </div>
        <Table
          dataSource={filteredRequests}
          columns={requestColumns}
          rowKey="id"
          size="small"
          loading={loading}
          pagination={{ pageSize: 15, size: 'small' }}
          locale={{ emptyText: '暂无请求记录' }}
        />
      </Drawer>

      {/* ---------- 图片/视频预览 Modal ---------- */}
      <Modal
        open={previewOpen}
        title={previewIsVideo ? <span><VideoCameraOutlined /> 视频预览</span> : <span><EyeOutlined /> 图片预览</span>}
        footer={null}
        onCancel={() => setPreviewOpen(false)}
        width={previewIsVideo ? 720 : undefined}
      >
        {previewIsVideo ? (
          <video src={previewUrl} controls autoPlay style={{ width: '100%', maxHeight: 480 }} />
        ) : (
          <img src={previewUrl} alt="预览" style={{ width: '100%' }} />
        )}
      </Modal>
    </div>
  )
}

export default QuickRequest
