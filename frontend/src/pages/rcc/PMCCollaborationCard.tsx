/**
 * PMC 供应链协同卡片 — 行业标准工作流可视化
 * ① PR 请购审批队列（金额分级）② PO 收货进度/逾期 ③ GR 收货 IQC 检验放行
 */
import { useEffect, useState, type CSSProperties } from 'react'
import { Tag, Button, message, InputNumber, Empty } from 'antd'
import { CheckOutlined, CloseOutlined, ExperimentOutlined } from '@ant-design/icons'
import axios from '../../services/api'

const API = '/api/v1'
const C = {
  border: '#E3E7EE', text: '#172033', text2: '#596579', text3: '#93A0B4',
  brand: '#315DAA', brandSoft: '#EAF0FC', success: '#157C4F', successSoft: '#E5F6EE',
  danger: '#D64545', dangerSoft: '#FBEAEA', warn: '#B36A12', warnSoft: '#FBF0DA',
}

const GR_STATUS: Record<string, { label: string; color: string }> = {
  pending: { label: '待检', color: 'default' },
  inspecting: { label: '检验中', color: 'processing' },
  passed: { label: '合格放行', color: 'success' },
  conditional: { label: '让步接收', color: 'warning' },
  rejected: { label: '拒收退供', color: 'error' },
}
const PO_STATUS: Record<string, { label: string; color: string }> = {
  draft: { label: '草稿', color: 'default' }, ordered: { label: '已下单', color: 'blue' },
  confirmed: { label: '已确认', color: 'cyan' }, in_transit: { label: '在途', color: 'processing' },
  partially_received: { label: '部分收货', color: 'warning' }, received: { label: '已收货', color: 'success' },
  cancelled: { label: '已取消', color: 'default' },
}

const cardStyle: CSSProperties = { border: `1px solid ${C.border}`, borderRadius: 12, background: '#fff', padding: '12px 14px', marginBottom: 12 }
const headStyle: CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }
const titleStyle: CSSProperties = { fontSize: 13, fontWeight: 800 }

export default function PMCCollaborationCard({ factoryId }: { factoryId: string }) {
  const [summary, setSummary] = useState<any>(null)
  const [prs, setPrs] = useState<any[]>([])
  const [pos, setPos] = useState<any[]>([])
  const [grs, setGrs] = useState<any[]>([])
  const [recvQty, setRecvQty] = useState<Record<string, number>>({})

  const load = async () => {
    const hdr = { headers: { 'X-Factory-Id': factoryId } }
    const [s, p, po, gr] = await Promise.allSettled([
      axios.get(`${API}/pmc/purchase-requisitions/summary?factory_id=${factoryId}`, hdr),
      axios.get(`${API}/pmc/purchase-requisitions?factory_id=${factoryId}&status=pending&limit=8`, hdr),
      axios.get(`${API}/pmc/purchase-orders?factory_id=${factoryId}&limit=8`, hdr),
      axios.get(`${API}/pmc/goods-receipts?factory_id=${factoryId}&limit=8`, hdr),
    ])
    if (s.status === 'fulfilled') setSummary(s.value)
    if (p.status === 'fulfilled') setPrs((p.value as any)?.items || [])
    if (po.status === 'fulfilled') setPos((po.value as any)?.items || [])
    if (gr.status === 'fulfilled') setGrs((gr.value as any)?.items || [])
  }
  useEffect(() => { load() }, [factoryId])

  const approvePr = async (id: string) => {
    try {
      await axios.post(`${API}/pmc/purchase-requisitions/${id}/approve?action=approve&comment=RCC审批`, null, { headers: { 'X-Factory-Id': factoryId } })
      message.success('已批准请购单')
      load()
    } catch (e: any) { message.error(String(e?.response?.data?.detail || '审批失败').slice(0, 60)) }
  }
  const rejectPr = async (id: string) => {
    const reason = prompt('驳回原因：')
    if (!reason || reason.length < 2) return
    try {
      await axios.post(`${API}/pmc/purchase-requisitions/${id}/reject?reason=${encodeURIComponent(reason)}`, null, { headers: { 'X-Factory-Id': factoryId } })
      message.success('已驳回')
      load()
    } catch (e: any) { message.error(String(e?.response?.data?.detail || '驳回失败').slice(0, 60)) }
  }
  const receivePo = async (id: string) => {
    const q = recvQty[id] || 0
    if (q <= 0) { message.warning('请输入收货数量'); return }
    try {
      const res: any = await axios.post(`${API}/pmc/purchase-orders/${id}/receive?quantity=${q}`, null, { headers: { 'X-Factory-Id': factoryId } })
      message.success(res?.message || '收货成功')
      load()
    } catch (e: any) { message.error(String(e?.response?.data?.detail || '收货失败').slice(0, 60)) }
  }
  const inspectGr = async (id: string, result: string) => {
    try {
      const res: any = await axios.post(`${API}/pmc/goods-receipts/${id}/inspect?result=${result}`, null, { headers: { 'X-Factory-Id': factoryId } })
      message.success(result === 'rejected' ? '已拒收，请开退供单' : `已放行 ${res?.effects?.released_to_stock || 0} 件入库`)
      load()
    } catch (e: any) { message.error(String(e?.response?.data?.detail || '检验失败').slice(0, 60)) }
  }

  const activePos = pos.filter(p => !['received', 'cancelled', 'completed'].includes(p.status))
  const activeGrs = grs.filter(g => ['pending', 'inspecting'].includes(g.iqc_status))

  return (
    <div>
      {/* ① PR 审批队列 */}
      <div style={cardStyle}>
        <div style={headStyle}>
          <span style={titleStyle}>📋 请购单审批队列</span>
          {summary && (
            <span style={{ fontSize: 11, color: C.text3 }}>
              待审批 <b style={{ color: C.warn }}>{summary.pending_total}</b> 笔 · 需人工复核（&gt;¥{summary.auto_approve_limit}）
              <b style={{ color: C.danger }}> {summary.needs_manual_review}</b> 笔
            </span>
          )}
        </div>
        {prs.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无待审批请购单" /> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
            <thead><tr style={{ color: C.text3, fontSize: 10 }}>
              {['单号', '物料', '数量', '需求日', '预估金额', '来源', '操作'].map(h => <th key={h} style={{ padding: '4px 6px', textAlign: 'left' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {prs.map(p => (
                <tr key={p.id} style={{ borderTop: `1px solid ${C.border}` }}>
                  <td style={{ padding: '5px 6px', fontFamily: 'monospace', fontWeight: 700 }}>{p.pr_code}</td>
                  <td style={{ padding: '5px 6px' }}>{p.material_name || p.material_code}</td>
                  <td style={{ padding: '5px 6px', fontFamily: 'monospace' }}>{p.qty} {p.unit}</td>
                  <td style={{ padding: '5px 6px' }}>{p.required_date || '-'}</td>
                  <td style={{ padding: '5px 6px' }}>
                    {p.needs_manual && <Tag color="red" style={{ fontSize: 9.5 }}>人工</Tag>}¥{p.estimated_cost.toFixed(0)}
                  </td>
                  <td style={{ padding: '5px 6px' }}>{p.source || '-'}</td>
                  <td style={{ padding: '5px 6px' }}>
                    <Button size="small" type="link" icon={<CheckOutlined />} onClick={() => approvePr(p.id)}>批准</Button>
                    <Button size="small" type="link" danger icon={<CloseOutlined />} onClick={() => rejectPr(p.id)}>驳回</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ② PO 收货进度 */}
      <div style={cardStyle}>
        <div style={headStyle}>
          <span style={titleStyle}>🚚 采购订单收货进度</span>
          <span style={{ fontSize: 11, color: C.text3 }}>活跃 {activePos.length} 单 · 逾期 {pos.filter(p => p.overdue_days > 0).length} 单</span>
        </div>
        {pos.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无采购订单" /> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
            <thead><tr style={{ color: C.text3, fontSize: 10 }}>
              {['单号', '供应商', '物料', '收货进度', '预计交期', '状态', '收货操作'].map(h => <th key={h} style={{ padding: '4px 6px', textAlign: 'left' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {pos.map(p => (
                <tr key={p.id} style={{ borderTop: `1px solid ${C.border}` }}>
                  <td style={{ padding: '5px 6px', fontFamily: 'monospace', fontWeight: 700 }}>{p.po_code}</td>
                  <td style={{ padding: '5px 6px' }}>{(p.supplier_name || p.supplier_id || '-').slice(0, 12)}</td>
                  <td style={{ padding: '5px 6px' }}>{p.material_name || p.material_code}</td>
                  <td style={{ padding: '5px 6px', fontFamily: 'monospace' }}>{p.received_qty}/{p.qty} ({p.receipt_pct}%)</td>
                  <td style={{ padding: '5px 6px' }}>
                    {p.expected_date}{p.overdue_days > 0 && <Tag color="red" style={{ marginLeft: 4, fontSize: 9.5 }}>逾期{p.overdue_days}天</Tag>}
                  </td>
                  <td style={{ padding: '5px 6px' }}><Tag color={PO_STATUS[p.status]?.color || 'default'}>{PO_STATUS[p.status]?.label || p.status}</Tag></td>
                  <td style={{ padding: '5px 6px' }}>
                    {!['received', 'cancelled', 'closed'].includes(p.status) && (
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                        <InputNumber size="small" min={0} max={p.qty - p.received_qty} style={{ width: 72 }} placeholder="数量"
                          onChange={(v) => setRecvQty({ ...recvQty, [p.id]: Number(v || 0) })} />
                        <Button size="small" type="link" onClick={() => receivePo(p.id)}>收货</Button>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* ③ GR IQC 检验 */}
      <div style={cardStyle}>
        <div style={headStyle}>
          <span style={titleStyle}><ExperimentOutlined /> 来料检验（IQC）</span>
          <span style={{ fontSize: 11, color: C.text3 }}>待检 {activeGrs.length} 批 · 合格即放行入库，拒收自动扣回</span>
        </div>
        {grs.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无收货记录" /> : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
            <thead><tr style={{ color: C.text3, fontSize: 10 }}>
              {['收货单', 'PO', '物料', '数量', '检验单', 'IQC状态', '检验操作'].map(h => <th key={h} style={{ padding: '4px 6px', textAlign: 'left' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {grs.map(g => (
                <tr key={g.id} style={{ borderTop: `1px solid ${C.border}` }}>
                  <td style={{ padding: '5px 6px', fontFamily: 'monospace', fontWeight: 700 }}>{g.gr_code}</td>
                  <td style={{ padding: '5px 6px', fontFamily: 'monospace' }}>{g.po_code || '-'}</td>
                  <td style={{ padding: '5px 6px' }}>{g.material_code}</td>
                  <td style={{ padding: '5px 6px', fontFamily: 'monospace' }}>{g.quantity}</td>
                  <td style={{ padding: '5px 6px', fontFamily: 'monospace' }}>{g.inspection_task_code || '-'}</td>
                  <td style={{ padding: '5px 6px' }}><Tag color={GR_STATUS[g.iqc_status]?.color || 'default'}>{GR_STATUS[g.iqc_status]?.label || g.iqc_status}</Tag></td>
                  <td style={{ padding: '5px 6px' }}>
                    {['pending', 'inspecting'].includes(g.iqc_status) && (
                      <>
                        <Button size="small" type="link" onClick={() => inspectGr(g.id, 'passed')}>合格放行</Button>
                        <Button size="small" type="link" danger onClick={() => inspectGr(g.id, 'rejected')}>拒收</Button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
