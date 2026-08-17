/**
 * RCC 标准模板中心 — 找回行业标准模板（8D/CAR/退料单/盘点差异单等）
 * 模板按业务模块分组展示，一键开程序工单（动态表单），支持关闭与查看
 */
import { useEffect, useState } from 'react'
import { Modal, Form, Input, Select, message, Tag, Empty, Drawer, Descriptions, Button } from 'antd'
import { FileTextOutlined, CheckCircleOutlined } from '@ant-design/icons'
import axios from '../../services/api'

const API = '/api/v1'
const C = {
  border: '#E3E7EE', text: '#172033', text2: '#596579', text3: '#93A0B4',
  brand: '#315DAA', brandSoft: '#EAF0FC', success: '#157C4F', successSoft: '#E5F6EE',
  danger: '#D64545', warn: '#B36A12', warnSoft: '#FBF0DA',
}

const MODULE_META: Record<string, { label: string; color: string; soft: string }> = {
  qms: { label: '品质 QMS', color: C.danger, soft: '#FBEAEA' },
  production: { label: '生产制造', color: C.brand, soft: C.brandSoft },
  wms: { label: '仓储物流', color: C.success, soft: C.successSoft },
  pmc: { label: 'PMC 计划', color: C.warn, soft: C.warnSoft },
  pp: { label: 'PMC 计划', color: C.warn, soft: C.warnSoft },
  equipment: { label: '设备管理', color: '#087F8C', soft: '#E4F4F4' },
}
const STATUS_META: Record<string, { label: string; color: string }> = {
  open: { label: '进行中', color: 'processing' },
  in_progress: { label: '处理中', color: 'processing' },
  closed: { label: '已关闭', color: 'default' },
}

interface TplField { key: string; label: string; type: string; required?: boolean; options?: string[]; placeholder?: string; span?: number }

export default function RCCStandardTemplates({ factoryId }: { factoryId: string }) {
  const [templates, setTemplates] = useState<any[]>([])
  const [orders, setOrders] = useState<any[]>([])
  const [creating, setCreating] = useState<any>(null)
  const [detail, setDetail] = useState<any>(null)
  const [form] = Form.useForm()

  const load = async () => {
    try {
      const [t, o] = await Promise.allSettled([
        axios.get(`${API}/work-order-templates`, { headers: { 'X-Factory-Id': factoryId } }),
        axios.get(`${API}/work-order-templates/orders`, { headers: { 'X-Factory-Id': factoryId } }),
      ])
      if (t.status === 'fulfilled') setTemplates(Array.isArray(t.value) ? t.value : [])
      if (o.status === 'fulfilled') setOrders((o.value as any)?.items || [])
    } catch { /* 静默 */ }
  }
  useEffect(() => { load() }, [factoryId])

  const submit = async () => {
    try {
      const values = await form.validateFields()
      const { title, priority, ...rest } = values
      const res: any = await axios.post(`${API}/work-order-templates/create`, {
        factory_id: factoryId, template_code: creating.template_code,
        title, priority: priority || creating.default_priority || 'medium', data: rest,
      }, { headers: { 'X-Factory-Id': factoryId } })
      message.success(`程序工单已创建：${res?.work_order_code || ''}`)
      setCreating(null)
      form.resetFields()
      load()
    } catch (e: any) {
      if (e?.errorFields) return
      message.error(String(e?.response?.data?.detail || e?.message || '创建失败').slice(0, 80))
    }
  }

  const closeOrder = async (id: string) => {
    try {
      await axios.post(`${API}/work-order-templates/orders/${id}/close`, {}, { headers: { 'X-Factory-Id': factoryId } })
      message.success('已关闭')
      load()
    } catch (e: any) { message.error(String(e?.response?.data?.detail || '关闭失败').slice(0, 60)) }
  }

  const modules = Object.keys(MODULE_META)
  const grouped = modules.map(m => ({ module: m, items: templates.filter(t => (t.module || 'production') === m) })).filter(g => g.items.length > 0)
  const openOrders = orders.filter(o => o.status !== 'closed')

  return (
    <div>
      {/* 头部统计 */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
        {[
          ['标准模板', templates.length, C.brand],
          ['进行中工单', openOrders.length, C.warn],
          ['累计开单', orders.length, C.text2],
        ].map(([k, v, color]) => (
          <div key={k as string} style={{ border: `1px solid ${C.border}`, borderRadius: 10, background: '#fff', padding: '8px 16px' }}>
            <span style={{ fontSize: 11, color: C.text3, fontWeight: 700 }}>{k}</span>{' '}
            <b style={{ fontSize: 15, fontFamily: 'monospace', color: color as string }}>{v}</b>
          </div>
        ))}
      </div>

      {/* 模板分组卡片 */}
      {grouped.length === 0 && <Empty description="当前工厂暂无标准模板" />}
      {grouped.map(g => (
        <div key={g.module} style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: MODULE_META[g.module].color, margin: '6px 2px' }}>
            {MODULE_META[g.module].label} <span style={{ color: C.text3, fontWeight: 600 }}>{g.items.length} 个模板</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(215px,1fr))', gap: 8 }}>
            {g.items.map(t => (
              <div key={`${t.template_code}-${t.id}`} onClick={() => { setCreating(t); form.resetFields() }}
                style={{ border: `1px solid ${C.border}`, borderRadius: 10, background: '#fff', padding: '10px 12px', cursor: 'pointer' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <span style={{ width: 26, height: 26, borderRadius: 7, background: MODULE_META[g.module].soft, color: MODULE_META[g.module].color, display: 'grid', placeItems: 'center', fontSize: 12 }}><FileTextOutlined /></span>
                  <b style={{ fontSize: 12.5 }}>{t.template_name}</b>
                  {t.badge_text && <Tag color="blue" style={{ marginLeft: 'auto', fontSize: 9.5 }}>{t.badge_text}</Tag>}
                </div>
                <div style={{ fontSize: 10.5, color: C.text3, marginTop: 6, lineHeight: 1.5 }}>
                  {(t.description || '—').slice(0, 60)}
                </div>
                <div style={{ display: 'flex', gap: 4, marginTop: 6, flexWrap: 'wrap' }}>
                  {t.standard_ref && <Tag style={{ fontSize: 9.5 }}>{t.standard_ref}</Tag>}
                  <Tag style={{ fontSize: 9.5 }}>{(t.form_fields || []).length} 字段</Tag>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* 已开程序工单 */}
      <div style={{ fontSize: 12, fontWeight: 800, color: C.text2, margin: '14px 2px 6px' }}>程序工单台账</div>
      <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, background: '#fff', overflow: 'hidden' }}>
        {orders.length === 0 ? <Empty description="暂无程序工单，点击上方模板即可开单" style={{ padding: 20 }} /> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: '#F7F9FC', color: C.text3, fontSize: 10.5 }}>
                {['单号', '模板', '标题', '状态', '优先级', '开单人', '时间', '操作'].map(h => (
                  <th key={h} style={{ padding: '7px 10px', textAlign: 'left', fontWeight: 700 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {orders.map(o => (
                <tr key={o.id} style={{ borderTop: `1px solid ${C.border}` }}>
                  <td style={{ padding: '7px 10px', fontFamily: 'monospace', fontWeight: 700 }}>{o.pwo_code}</td>
                  <td style={{ padding: '7px 10px' }}>{o.template_name}</td>
                  <td style={{ padding: '7px 10px', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{o.title}</td>
                  <td style={{ padding: '7px 10px' }}><Tag color={STATUS_META[o.status]?.color || 'default'}>{STATUS_META[o.status]?.label || o.status}</Tag></td>
                  <td style={{ padding: '7px 10px' }}>{o.priority}</td>
                  <td style={{ padding: '7px 10px' }}>{o.created_by}</td>
                  <td style={{ padding: '7px 10px', fontFamily: 'monospace', fontSize: 11 }}>{o.created_at}</td>
                  <td style={{ padding: '7px 10px' }}>
                    <Button size="small" type="link" onClick={() => setDetail(o)}>详情</Button>
                    {o.status !== 'closed' && <Button size="small" type="link" icon={<CheckCircleOutlined />} onClick={() => closeOrder(o.id)}>关闭</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 开单弹窗：动态表单 */}
      <Modal open={!!creating} title={creating ? `📝 ${creating.template_name} — 开单` : ''} onCancel={() => setCreating(null)} onOk={submit} okText="创建程序工单" width={720} destroyOnClose>
        <Form form={form} layout="vertical" style={{ maxHeight: 460, overflow: 'auto' }}>
          <Form.Item name="title" label="工单标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder={`例：${creating?.template_name || ''} - ${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`} />
          </Form.Item>
          <Form.Item name="priority" label="优先级" initialValue={creating?.default_priority || 'medium'}>
            <Select options={[{ value: 'low', label: '低' }, { value: 'medium', label: '中' }, { value: 'high', label: '高' }, { value: 'urgent', label: '紧急' }]} />
          </Form.Item>
          {(creating?.form_fields || []).map((f: TplField) => {
            if (f.type === 'select' && f.options?.length) {
              return <Form.Item key={f.key} name={f.key} label={f.label} rules={f.required ? [{ required: true, message: `请选择${f.label}` }] : []}>
                <Select placeholder={f.placeholder} options={f.options.map(o => ({ value: o, label: o }))} allowClear />
              </Form.Item>
            }
            if (f.type === 'textarea' || f.type === 'json_array') {
              return <Form.Item key={f.key} name={f.key} label={f.label} rules={f.required ? [{ required: true, message: `请填写${f.label}` }] : []}>
                <Input.TextArea rows={f.type === 'json_array' ? 4 : 3} placeholder={f.placeholder} />
              </Form.Item>
            }
            return <Form.Item key={f.key} name={f.key} label={f.label} rules={f.required ? [{ required: true, message: `请填写${f.label}` }] : []}>
              <Input placeholder={f.placeholder} />
            </Form.Item>
          })}
        </Form>
      </Modal>

      {/* 详情抽屉 */}
      <Drawer open={!!detail} onClose={() => setDetail(null)} title={detail ? `${detail.pwo_code} · ${detail.template_name}` : ''} width={520}>
        {detail && (
          <>
            <Descriptions column={1} size="small" bordered style={{ marginBottom: 14 }}>
              <Descriptions.Item label="标题">{detail.title}</Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={STATUS_META[detail.status]?.color}>{STATUS_META[detail.status]?.label || detail.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="优先级">{detail.priority}</Descriptions.Item>
              <Descriptions.Item label="开单人">{detail.created_by} · {detail.created_at}</Descriptions.Item>
              {detail.closed_at && <Descriptions.Item label="关闭时间">{detail.closed_at}</Descriptions.Item>}
            </Descriptions>
            <div style={{ fontSize: 12, fontWeight: 800, marginBottom: 6 }}>表单内容</div>
            <Descriptions column={1} size="small" bordered>
              {Object.entries(detail.form_data || {}).map(([k, v]) => (
                <Descriptions.Item key={k} label={k}>{String(v ?? '')}</Descriptions.Item>
              ))}
              {Object.keys(detail.form_data || {}).length === 0 && <Descriptions.Item label="—">无</Descriptions.Item>}
            </Descriptions>
          </>
        )}
      </Drawer>
    </div>
  )
}
