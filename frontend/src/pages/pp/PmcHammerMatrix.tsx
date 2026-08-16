/**
 * PMC 锤子图 — 工单 × 开关 影响热力矩阵
 * y 轴 = 工单（按交期排序） | x 轴 = 参数变量开关
 * 单元格 = 该开关对工单的影响（偏移天数 + 颜色：绿=提前/改善, 黄=轻微延后, 红=严重延后）
 */
import { useEffect, useState } from 'react'
import { Tag, Tooltip, Spin, Space, Button } from 'antd'
import { ThunderboltOutlined, ReloadOutlined } from '@ant-design/icons'
import axios from 'axios'

const API = '/api/v1'

const LEVEL_COLOR: Record<string, string> = {
  ok: '#E8F7EF',        // 绿：提前/改善
  warning: '#FEF5E7',   // 黄：轻微延后
  danger: '#FDECEA',    // 红：严重延后
  na: '#F5F6F8',        // 灰：无法计算
}

const LEVEL_TEXT: Record<string, string> = {
  ok: '#157C4F', warning: '#B36A12', danger: '#D64545', na: '#93A0B4',
}

export default function PmcHammerMatrix({ factoryId = 'FAC_MECH_001' }: { factoryId?: string }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [limit, setLimit] = useState(8)

  const load = async () => {
    setLoading(true)
    try {
      const r = await axios.post(`${API}/pmc/work-matrix/hammer`, { factory_id: factoryId, limit })
      setData(r.data)
    } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [limit])

  const switches = data?.switches || []
  const rows = data?.rows || []

  return (
    <div style={{ background: '#fff', border: '1px solid #d9e5f5', borderRadius: 12, padding: '14px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <ThunderboltOutlined style={{ color: '#315DAA', fontSize: 16 }} />
        <b style={{ fontSize: 14 }}>PMC 锤子图 · 工单 × 开关影响矩阵</b>
        <Tag color="blue">y轴=工单 · x轴=参数变量开关</Tag>
        <span style={{ fontSize: 11, color: '#93A0B4' }}>每格 = 切换该开关后对工单交期的影响（天）</span>
        <Space style={{ marginLeft: 'auto' }} size={8}>
          {[6, 8, 12].map(n => (
            <Button key={n} size="small" type={limit === n ? 'primary' : 'default'} onClick={() => setLimit(n)}>{n} 单</Button>
          ))}
          <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
        </Space>
      </div>

      {/* 图例 */}
      <div style={{ display: 'flex', gap: 14, marginBottom: 10, fontSize: 11, color: '#596579' }}>
        <span><i style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 3, background: LEVEL_COLOR.ok, marginRight: 4, border: '1px solid #d5e8dc' }} />提前/改善</span>
        <span><i style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 3, background: LEVEL_COLOR.warning, marginRight: 4, border: '1px solid #f0e0c0' }} />轻微延后</span>
        <span><i style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 3, background: LEVEL_COLOR.danger, marginRight: 4, border: '1px solid #f0c8c4' }} />严重延后</span>
      </div>

      {loading ? <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div> : rows.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 30, color: '#93A0B4', fontSize: 12 }}>暂无工单数据</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 900, fontSize: 12 }}>
            <thead>
              <tr style={{ background: '#F6FAFF' }}>
                <th style={{ padding: '10px 12px', border: '1px solid #e8eef5', textAlign: 'left', minWidth: 170 }}>
                  <div style={{ color: '#315DAA', fontWeight: 700 }}>工单</div>
                  <div style={{ color: '#93A0B4', fontWeight: 400, fontSize: 10.5 }}>y 轴 · 按交期</div>
                </th>
                <th style={{ padding: '10px 8px', border: '1px solid #e8eef5', textAlign: 'center', minWidth: 90 }}>
                  <div style={{ color: '#315DAA', fontWeight: 700 }}>基准</div>
                  <div style={{ color: '#93A0B4', fontWeight: 400, fontSize: 10.5 }}>当前排程</div>
                </th>
                {switches.map((sw: any) => (
                  <th key={sw.key + sw.label} style={{ padding: '10px 8px', border: '1px solid #e8eef5', textAlign: 'center', minWidth: 92 }}>
                    <Tooltip title={sw.desc}>
                      <div style={{ fontWeight: 700, color: '#172033', whiteSpace: 'nowrap' }}>{sw.label}</div>
                    </Tooltip>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row: any) => (
                <tr key={row.work_order_code} style={{ borderBottom: '1px solid #f0f4f9' }}>
                  {/* y 轴：工单 */}
                  <td style={{ padding: '9px 12px', border: '1px solid #e8eef5' }}>
                    <div style={{ fontWeight: 650, whiteSpace: 'nowrap' }}>{row.work_order_code}</div>
                    <div style={{ color: '#93A0B4', fontSize: 10.5, marginTop: 2 }}>
                      {row.product_id} · {row.qty}件 · 交期 {row.due}
                      {row.priority === 'urgent' && <Tag color="red" style={{ marginLeft: 6, fontSize: 10 }}>急</Tag>}
                      {row.priority === 'high' && <Tag color="orange" style={{ marginLeft: 6, fontSize: 10 }}>高</Tag>}
                    </div>
                  </td>
                  {/* 基准列 */}
                  <td style={{ padding: '9px 8px', border: '1px solid #e8eef5', textAlign: 'center', background: '#FAFBFD' }}>
                    <div style={{ fontWeight: 700, color: (row.base_offset_days || 0) > 0 ? '#D64545' : '#157C4F', fontFamily: 'monospace' }}>
                      {row.base_offset_days != null ? `${row.base_offset_days > 0 ? '+' : ''}${Math.round(row.base_offset_days * 10) / 10}天` : '—'}
                    </div>
                    <div style={{ color: '#93A0B4', fontSize: 10 }}>{row.base_eta || ''}</div>
                  </td>
                  {/* 开关列 */}
                  {row.cells.map((cell: any) => {
                    const bg = LEVEL_COLOR[cell.level] || '#F5F6F8'
                    const fg = LEVEL_TEXT[cell.level] || '#93A0B4'
                    const off = cell.offset_days
                    return (
                      <td key={cell.switch + cell.label} style={{
                        padding: '9px 8px', border: '1px solid #e8eef5', textAlign: 'center', background: bg,
                      }}>
                        <Tooltip title={`${cell.label}：${off != null ? (off > 0 ? `延后 ${Math.round(off * 10) / 10} 天` : off < 0 ? `提前 ${Math.abs(Math.round(off * 10) / 10)} 天` : '无影响') : '无法计算'} · ${cell.desc || ''}`}>
                          <div style={{ fontWeight: 800, color: fg, fontFamily: 'monospace', fontSize: 13 }}>
                            {off != null ? `${off > 0 ? '+' : ''}${Math.round(off * 10) / 10}` : '—'}
                          </div>
                          <div style={{ color: fg, opacity: 0.75, fontSize: 10 }}>天</div>
                        </Tooltip>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 洞察提示 */}
      {!loading && rows.length > 0 && (
        <div style={{ marginTop: 12, padding: '9px 12px', background: '#F6FAFF', borderRadius: 8, fontSize: 11.5, color: '#596579' }}>
          <b style={{ color: '#315DAA' }}>怎么看：</b>
          每一行是工单，每一列是一个参数开关。绿色=切换后交期改善，红色=切换后严重延后。
          某行大片红 = 该工单对排程敏感（需要重点保障）；某列普遍红 = 该开关是全局风险点。
        </div>
      )}
    </div>
  )
}
