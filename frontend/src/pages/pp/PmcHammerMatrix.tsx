/**
 * PMC 锤子图 — 工单 × 参数影响矩阵（可调参版）
 * y 轴 = 工单 | x 轴 = 参数维度（表头下拉可调）
 * 每维度一个 Select：切换档位 → 后端按新组合重算 → 基准列=当前组合 ETA
 * 单元格 = 该维度切到其他档位时的相对偏移（当前档显示为「基准」）
 */
import { useEffect, useState } from 'react'
import { Tag, Tooltip, Spin, Space, Button, Select } from 'antd'
import { ThunderboltOutlined, ReloadOutlined } from '@ant-design/icons'
import axios from 'axios'

const API = '/api/v1'

const LEVEL_COLOR: Record<string, string> = {
  ok: '#E8F7EF',
  warning: '#FEF5E7',
  danger: '#FDECEA',
  na: '#F5F6F8',
}
const LEVEL_TEXT: Record<string, string> = {
  ok: '#157C4F', warning: '#B36A12', danger: '#D64545', na: '#93A0B4',
}

export default function PmcHammerMatrix({ factoryId = 'FAC_MECH_001' }: { factoryId?: string }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [limit, setLimit] = useState(8)
  const [params, setParams] = useState<Record<string, any>>({})

  const load = async (p: Record<string, any>, lim: number) => {
    setLoading(true)
    try {
      const r = await axios.post(`${API}/pmc/work-matrix/hammer`, {
        factory_id: factoryId, limit: lim, params: p,
      })
      setData(r.data)
    } finally { setLoading(false) }
  }
  useEffect(() => { load(params, limit) }, [limit])

  const dimensions: any[] = data?.dimensions || []
  const rows: any[] = data?.rows || []
  const curParams: Record<string, any> = data?.params || {}

  const setDim = (key: string, value: any) => {
    const next = { ...params, [key]: value }
    setParams(next)
    load(next, limit)
  }

  return (
    <div style={{ background: '#fff', border: '1px solid #d9e5f5', borderRadius: 12, padding: '14px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
        <ThunderboltOutlined style={{ color: '#315DAA', fontSize: 16 }} />
        <b style={{ fontSize: 14 }}>PMC 锤子图 · 工单 × 参数影响矩阵</b>
        <Tag color="blue">表头可调参 · 实时重算</Tag>
        <Space style={{ marginLeft: 'auto' }} size={8}>
          {[6, 8, 12].map(n => (
            <Button key={n} size="small" type={limit === n ? 'primary' : 'default'} onClick={() => setLimit(n)}>{n} 单</Button>
          ))}
          <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={() => load(params, limit)}>刷新</Button>
        </Space>
      </div>

      {/* 参数面板：每个维度一个下拉 */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap', padding: '10px 12px', background: '#F6FAFF', borderRadius: 8 }}>
        {dimensions.map((dim: any) => (
          <div key={dim.key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 12, color: '#596579', whiteSpace: 'nowrap' }}>{dim.label}</span>
            <Select
              size="small"
              style={{ width: 128 }}
              value={curParams[dim.key] !== undefined ? curParams[dim.key] : dim.default}
              options={dim.options.map((o: any) => ({ value: o.value, label: o.label }))}
              onChange={(v) => setDim(dim.key, v)}
            />
          </div>
        ))}
      </div>

      {/* 图例 */}
      <div style={{ display: 'flex', gap: 14, marginBottom: 10, fontSize: 11, color: '#596579' }}>
        <span><i style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 3, background: LEVEL_COLOR.ok, marginRight: 4, border: '1px solid #d5e8dc' }} />提前/改善</span>
        <span><i style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 3, background: LEVEL_COLOR.warning, marginRight: 4, border: '1px solid #f0e0c0' }} />轻微延后</span>
        <span><i style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 3, background: LEVEL_COLOR.danger, marginRight: 4, border: '1px solid #f0c8c4' }} />严重延后</span>
        <span style={{ marginLeft: 8, color: '#93A0B4' }}>基准列 = 当前参数组合的排程偏移；单元格 = 切换该档位后的相对变化</span>
      </div>

      {loading ? <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div> : rows.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 30, color: '#93A0B4', fontSize: 12 }}>暂无工单数据</div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 1100, fontSize: 12 }}>
            <thead>
              <tr style={{ background: '#F6FAFF' }}>
                <th style={{ padding: '10px 12px', border: '1px solid #e8eef5', textAlign: 'left', minWidth: 170 }}>
                  <div style={{ color: '#315DAA', fontWeight: 700 }}>工单</div>
                  <div style={{ color: '#93A0B4', fontWeight: 400, fontSize: 10.5 }}>y 轴 · 按交期</div>
                </th>
                <th style={{ padding: '10px 8px', border: '1px solid #e8eef5', textAlign: 'center', minWidth: 90 }}>
                  <div style={{ color: '#315DAA', fontWeight: 700 }}>基准</div>
                  <div style={{ color: '#93A0B4', fontWeight: 400, fontSize: 10.5 }}>当前参数</div>
                </th>
                {dimensions.map((dim: any) => (
                  <th key={dim.key} colSpan={Math.max(1, dim.options.length - 1)}
                      style={{ padding: '8px 4px', border: '1px solid #e8eef5', textAlign: 'center', minWidth: 120 }}>
                    <div style={{ fontWeight: 700, color: '#315DAA', whiteSpace: 'nowrap' }}>{dim.label}</div>
                    <div style={{ color: '#93A0B4', fontWeight: 400, fontSize: 10 }}>
                      当前: {dim.options.find((o: any) => o.value === curParams[dim.key])?.label || ''}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row: any) => (
                <tr key={row.work_order_code} style={{ borderBottom: '1px solid #f0f4f9' }}>
                  <td style={{ padding: '9px 12px', border: '1px solid #e8eef5' }}>
                    <div style={{ fontWeight: 650, whiteSpace: 'nowrap' }}>{row.work_order_code}</div>
                    <div style={{ color: '#93A0B4', fontSize: 10.5, marginTop: 2 }}>
                      {row.product_id} · {row.qty}件 · 交期 {row.due}
                      {row.priority === 'urgent' && <Tag color="red" style={{ marginLeft: 6, fontSize: 10 }}>急</Tag>}
                      {row.priority === 'high' && <Tag color="orange" style={{ marginLeft: 6, fontSize: 10 }}>高</Tag>}
                    </div>
                  </td>
                  <td style={{ padding: '9px 8px', border: '1px solid #e8eef5', textAlign: 'center', background: '#FAFBFD' }}>
                    <div style={{ fontWeight: 700, color: (row.base_offset_days || 0) > 0 ? '#D64545' : '#157C4F', fontFamily: 'monospace' }}>
                      {row.base_offset_days != null ? `${row.base_offset_days > 0 ? '+' : ''}${Math.round(row.base_offset_days * 10) / 10}天` : '—'}
                    </div>
                    <div style={{ color: '#93A0B4', fontSize: 10 }}>{row.base_eta || ''}</div>
                  </td>
                  {dimensions.map((dim: any) => {
                    const dimCells = row.cells.filter((c: any) => c.switch === dim.key)
                    return (
                      <td key={dim.key} colSpan={Math.max(1, dim.options.length - 1)}
                          style={{ padding: 0, border: '1px solid #e8eef5' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                          <tbody>
                            <tr>
                              {dimCells.map((cell: any) => {
                                const bg = LEVEL_COLOR[cell.level] || '#F5F6F8'
                                const fg = LEVEL_TEXT[cell.level] || '#93A0B4'
                                const off = cell.offset_days
                                return (
                                  <td key={cell.option_value} style={{ padding: '9px 6px', textAlign: 'center', background: bg, borderRight: '1px solid #e8eef5', minWidth: 110 }}>
                                    <Tooltip title={`${cell.label}：${off != null ? (off > 0 ? `延后 ${Math.round(off * 10) / 10} 天` : off < 0 ? `提前 ${Math.abs(Math.round(off * 10) / 10)} 天` : '无影响') : '无法计算'} · ${cell.desc || ''}`}>
                                      <div style={{ fontSize: 10.5, color: fg, opacity: 0.9 }}>{cell.option_label}</div>
                                      <div style={{ fontWeight: 800, color: fg, fontFamily: 'monospace', fontSize: 13 }}>
                                        {off != null ? `${off > 0 ? '+' : ''}${Math.round(off * 10) / 10}` : '—'}
                                      </div>
                                    </Tooltip>
                                  </td>
                                )
                              })}
                            </tr>
                          </tbody>
                        </table>
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
          <b style={{ color: '#315DAA' }}>怎么用：</b>
          表头每个参数维度可下拉调整（如班次单班↔双班↔三班），切换后全矩阵按新组合实时重算。
          基准列=当前组合下的排程偏移；单元格=该维度切到其他档位时的相对变化。
          绿色=提前/改善，红色=延后。某行大片红=该工单敏感；某维度普遍红=该参数是全局风险点。
        </div>
      )}
    </div>
  )
}
