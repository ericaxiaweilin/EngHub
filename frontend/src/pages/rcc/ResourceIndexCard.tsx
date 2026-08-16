/**
 * RCC 资源可用指数卡片 — 人力×设备×物料×时间 四维乘积
 */
import { useEffect, useState } from 'react'
import { Spin, Progress, Tag } from 'antd'
import { DashboardOutlined } from '@ant-design/icons'
import axios from 'axios'

const API = '/api/v1'

const DIM_LABEL: Record<string, string> = {
  manpower: '可用人力', equipment: '可用设备', material: '可用物料', time: '可工作时间',
}

export default function ResourceIndexCard({ factoryId = 'FAC_MECH_001' }: { factoryId?: string }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get(`${API}/rcc/resource-index`, { params: { date: new Date().toISOString().slice(0, 10) } })
      .then(r => setData(r.data))
      .finally(() => setLoading(false))
  }, [factoryId])

  if (loading) return <div style={{ textAlign: 'center', padding: 30 }}><Spin /></div>
  if (!data) return null

  const dims = data.dimensions || {}
  const color = data.level === 'green' ? '#157C4F' : data.level === 'warning' ? '#B36A12' : '#D64545'

  return (
    <div style={{ background: '#fff', border: '1px solid #d9e5f5', borderRadius: 12, padding: 14, marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <DashboardOutlined style={{ color: '#315DAA', fontSize: 16 }} />
        <b style={{ fontSize: 14 }}>RCC 资源可用指数</b>
        <Tag color={data.level === 'green' ? 'green' : data.level === 'warning' ? 'orange' : 'red'}>
          {data.level === 'green' ? '充足' : data.level === 'warning' ? '吃紧' : '危险'}
        </Tag>
        <Tag color="blue">瓶颈: {DIM_LABEL[data.bottleneck] || data.bottleneck}</Tag>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: '#93A0B4' }}>
          可用产能 = 人力 × 设备 × 物料 × 时间（任一为 0 → 产能 0）
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        {/* 指数大数字 */}
        <div style={{ textAlign: 'center', padding: '0 14px', minWidth: 110 }}>
          <div style={{ fontSize: 38, fontWeight: 800, color, fontFamily: 'monospace' }}>{data.index}%</div>
          <div style={{ fontSize: 10.5, color: '#93A0B4' }}>今日资源可用指数</div>
        </div>
        {/* 四维进度 */}
        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 20px' }}>
          {Object.entries(dims).map(([k, v]: [string, any]) => (
            <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11.5, color: '#596579', width: 70, whiteSpace: 'nowrap' }}>
                {DIM_LABEL[k] || k}
              </span>
              <Progress
                percent={v.pct}
                size="small"
                style={{ flex: 1, margin: 0 }}
                strokeColor={v.pct >= 90 ? '#157C4F' : v.pct >= 75 ? '#B36A12' : '#D64545'}
              />
              <span style={{ fontSize: 11, color: '#93A0B4', width: 60, textAlign: 'right', fontFamily: 'monospace' }}>
                {v.available}/{v.total}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 8, fontSize: 11, color: '#93A0B4', background: '#F6FAFF', borderRadius: 6, padding: '6px 10px' }}>
        计算：{data.formula} · {data.message}
      </div>
    </div>
  )
}
