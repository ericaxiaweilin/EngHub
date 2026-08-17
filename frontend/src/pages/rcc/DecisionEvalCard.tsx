/**
 * RCC 决策效果回评估卡片 — 决策中心的质量闭环
 * 上游决策必然波及下游：执行后持续追踪效果，量化下游波及，定论通报
 */
import { useEffect, useState } from 'react'
import { Spin, Tag, Button, Tooltip, message } from 'antd'
import { AuditOutlined, ThunderboltOutlined } from '@ant-design/icons'
import axios from '../../services/api'

const API = '/api/v1'

const STATUS_META: Record<string, { label: string; color: string }> = {
  tracking: { label: '追踪中', color: 'processing' },
  achieved: { label: '达成', color: 'green' },
  partial: { label: '部分达成', color: 'orange' },
  failed: { label: '未达成', color: 'red' },
}

export default function DecisionEvalCard({ factoryId = 'FAC_MECH_001' }: { factoryId?: string }) {
  const [summary, setSummary] = useState<any>(null)
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    Promise.all([
      axios.get(`${API}/rcc/decision-evaluations/summary`, { params: { factory_id: factoryId } }),
      axios.get(`${API}/rcc/decision-evaluations`, { params: { factory_id: factoryId, limit: 8 } }),
    ])
      .then(([s, l]: any[]) => {
        setSummary(s)
        setItems(l?.items || [])
      })
      .finally(() => setLoading(false))
  }
  useEffect(load, [factoryId])

  const forceEval = async (id: string) => {
    await axios.post(`${API}/rcc/decision-evaluations/${id}/evaluate`)
    message.success('已完成一次复评')
    load()
  }

  if (loading) return <div style={{ textAlign: 'center', padding: 30 }}><Spin /></div>

  const t = summary?.totals || {}
  const rate = summary?.achievement_rate_pct
  const rateColor = rate == null ? '#93A0B4' : rate >= 70 ? '#157C4F' : rate >= 40 ? '#B36A12' : '#D64545'

  return (
    <div style={{ background: '#fff', border: '1px solid #d9e5f5', borderRadius: 12, padding: 14, marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <AuditOutlined style={{ color: '#315DAA', fontSize: 16 }} />
        <b style={{ fontSize: 14 }}>决策效果回评估</b>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: '#93A0B4' }}>
          决策→执行→验证→反馈：上游决策的下游波及全程可见
        </span>
      </div>

      <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 10 }}>
        <div style={{ textAlign: 'center', padding: '0 14px', minWidth: 110 }}>
          <div style={{ fontSize: 38, fontWeight: 800, color: rateColor, fontFamily: 'monospace' }}>
            {rate == null ? '--' : `${rate}%`}
          </div>
          <div style={{ fontSize: 10.5, color: '#93A0B4' }}>决策达成率（已定论）</div>
        </div>
        <div style={{ display: 'flex', gap: 14, fontSize: 12 }}>
          <Tooltip title="执行后持续追踪中的决策">
            <span>追踪中 <b style={{ color: '#315DAA' }}>{t.tracking || 0}</b></span>
          </Tooltip>
          <span>达成 <b style={{ color: '#157C4F' }}>{t.achieved || 0}</b></span>
          <span>部分 <b style={{ color: '#B36A12' }}>{t.partial || 0}</b></span>
          <span>未达成 <b style={{ color: '#D64545' }}>{t.failed || 0}</b></span>
        </div>
      </div>

      {items.length === 0 ? (
        <div style={{ color: '#93A0B4', fontSize: 12, padding: '8px 0' }}>
          暂无决策评估记录——审批并执行任一 RCC 决策后，系统将自动追踪其效果并通报下游部门
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map(it => {
            const sm = STATUS_META[it.status] || STATUS_META.tracking
            const dw = it.downstream_impact || {}
            const od = dw?.production?.overdue_delta
            return (
              <div key={it.id} style={{
                display: 'flex', alignItems: 'center', gap: 8, fontSize: 12,
                padding: '6px 10px', background: '#F6F9FE', borderRadius: 8,
              }}>
                <Tag color={sm.color} style={{ margin: 0 }}>{sm.label}</Tag>
                <Tag style={{ margin: 0 }}>{it.action}</Tag>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  <Tooltip title={it.verdict_note || it.expectations?.summary || ''}>
                    <span>{it.target || '—'}</span>
                  </Tooltip>
                </span>
                {od != null && (
                  <Tooltip title="决策后全厂逾期工单变化（下游波及）">
                    <span style={{ color: od > 0 ? '#D64545' : '#157C4F' }}>
                      逾期{od > 0 ? '+' : ''}{od}
                    </span>
                  </Tooltip>
                )}
                {it.status === 'tracking' && (
                  <Button size="small" type="link" icon={<ThunderboltOutlined />}
                          onClick={() => forceEval(it.id)}>立即复评</Button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
