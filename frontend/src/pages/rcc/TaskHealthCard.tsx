/**
 * RCC 任务健康指数卡片 — 任务域抓手（非生产部门核心）
 * 闭环率 × 及时率 × 接管率 + 未分配/卡点/每人负载
 */
import { useEffect, useState } from 'react'
import { Spin, Progress, Tag, Button, message } from 'antd'
import { CarryOutOutlined } from '@ant-design/icons'
import axios from '../../services/api'

const API = '/api/v1'

export default function TaskHealthCard({ factoryId = 'FAC_MECH_001' }: { factoryId?: string }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    axios.get(`${API}/rcc/task-health`)
      .then(r => setData(r as any))
      .finally(() => setLoading(false))
  }
  useEffect(load, [factoryId])

  if (loading) return <div style={{ textAlign: 'center', padding: 30 }}><Spin /></div>
  if (!data) return null

  const m = data.metrics || {}
  const color = data.level === 'green' ? '#157C4F' : data.level === 'warning' ? '#B36A12' : '#D64545'

  const claim = async () => {
    await axios.post(`${API}/rcc/claim-tasks`, {})
    message.success('已认领未分配任务')
    load()
  }

  return (
    <div style={{ background: '#fff', border: '1px solid #d9e5f5', borderRadius: 12, padding: 14, marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <CarryOutOutlined style={{ color: '#315DAA', fontSize: 16 }} />
        <b style={{ fontSize: 14 }}>RCC 任务健康指数</b>
        <Tag color={data.level === 'green' ? 'green' : data.level === 'warning' ? 'orange' : 'red'}>
          {data.level === 'green' ? '健康' : data.level === 'warning' ? '亚健康' : '危险'}
        </Tag>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: '#93A0B4' }}>
          非生产核心：每个任务处理好（闭环/及时/可接管），不是一人干多少件
        </span>
        <Button size="small" onClick={claim}>认领未分配</Button>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <div style={{ textAlign: 'center', padding: '0 14px', minWidth: 110 }}>
          <div style={{ fontSize: 38, fontWeight: 800, color, fontFamily: 'monospace' }}>{data.index}%</div>
          <div style={{ fontSize: 10.5, color: '#93A0B4' }}>任务健康指数</div>
        </div>
        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 20px' }}>
          {[
            { k: '闭环率', v: m.closed_rate, desc: `${m.done}/${m.total} 善终` },
            { k: '及时率', v: m.timely_rate, desc: '按时完成占比' },
            { k: 'AI接管率', v: m.takeover_rate, desc: 'chatbot 接管任务' },
            { k: '未分配', v: m.total ? Math.round(m.unassigned / m.total * 100) : 0, desc: `${m.unassigned} 条无人认领` },
          ].map(x => (
            <div key={x.k} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 11.5, color: '#596579', width: 70 }}>{x.k}</span>
              <Progress percent={x.v} size="small" style={{ flex: 1, margin: 0 }}
                strokeColor={x.v >= 80 ? '#157C4F' : x.v >= 50 ? '#B36A12' : '#D64545'} />
              <span style={{ fontSize: 10.5, color: '#93A0B4', width: 90, textAlign: 'right' }}>{x.desc}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 卡点 + 每人负载 */}
      <div style={{ display: 'flex', gap: 16, marginTop: 10 }}>
        <div style={{ flex: 1, fontSize: 11, color: '#596579', background: '#F6FAFF', borderRadius: 6, padding: '6px 10px' }}>
          <b style={{ color: '#315DAA' }}>卡点：</b>
          {(data.blockers || []).slice(0, 4).map((b: any) => `${b.who}×${b.count}`).join(' · ') || '无'}
        </div>
        <div style={{ flex: 1, fontSize: 11, color: '#596579', background: '#F6FAFF', borderRadius: 6, padding: '6px 10px' }}>
          <b style={{ color: '#315DAA' }}>每人负载：</b>
          {(data.loads || []).slice(0, 4).map((l: any) => `${l.who} ${l.total}(blocked ${l.blocked})`).join(' · ') || '无'}
        </div>
      </div>
      <div style={{ marginTop: 8, fontSize: 11, color: '#93A0B4' }}>
        计算：{data.formula} · {data.message}
      </div>
    </div>
  )
}
