/**
 * 个人工作任务计划表 — 按人聚合今日工作
 * 我的工单 / 我的跟进任务 / 待审批 / 通知 / 今日变更
 */
import { useEffect, useState } from 'react'
import { Tag, Spin, Card, Row, Col, List, Empty } from 'antd'
import { CalendarOutlined, CarryOutOutlined, AuditOutlined, BellOutlined, SwapOutlined } from '@ant-design/icons'
import axios from 'axios'

const API = '/api/v1'

const TYPE_LABEL: Record<string, string> = {
  reschedule: '改期', rush_insert: '插单', priority_change: '优先级', cancel: '撤单', qty_change: '数量',
}

export default function PersonalPlanCard({ person = 'eric', factoryId = 'FAC_MECH_001' }: { person?: string, factoryId?: string }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get(`${API}/pmc/personal-plan`, { params: { person } })
      .then(r => setData(r.data))
      .finally(() => setLoading(false))
  }, [person])

  if (loading) return <div style={{ textAlign: 'center', padding: 30 }}><Spin /></div>
  if (!data) return <Empty description="无计划数据" />

  const s = data.summary || {}
  const statusColor: Record<string, string> = {
    pending: 'gold', released: 'blue', in_progress: 'cyan', blocked: 'red', done: 'green',
  }

  return (
    <div style={{ background: '#fff', border: '1px solid #d9e5f5', borderRadius: 12, padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        <CalendarOutlined style={{ color: '#315DAA', fontSize: 16 }} />
        <b>个人工作任务计划表</b>
        <Tag color="blue">{data.person}</Tag>
        <Tag>{data.date}</Tag>
      </div>

      {/* 今日概览 */}
      <Row gutter={[8, 8]} style={{ marginBottom: 12 }}>
        {[
          { label: '我的工单', value: s.work_orders, color: '#315DAA' },
          { label: '跟进任务', value: s.tasks, color: '#E67E22' },
          { label: '待我审批', value: s.approvals, color: '#D64545' },
          { label: '未读通知', value: s.notifications, color: '#8E44AD' },
          { label: '今日变更', value: s.changes_today, color: '#16A085' },
        ].map(kpi => (
          <Col span={4} key={kpi.label} style={{ textAlign: 'center', background: '#F6FAFF', borderRadius: 8, padding: '8px 4px' }}>
            <div style={{ fontSize: 20, fontWeight: 800, color: kpi.color }}>{kpi.value}</div>
            <div style={{ fontSize: 11, color: '#93A0B4' }}>{kpi.label}</div>
          </Col>
        ))}
      </Row>

      <Row gutter={[10, 10]}>
        {/* 我的工单 */}
        <Col span={12}>
          <Card size="small" title={<span><CarryOutOutlined /> 我的工单（{data.work_orders.length}）</span>} bodyStyle={{ padding: 8, maxHeight: 260, overflow: 'auto' }}>
            {data.work_orders.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
              <List size="small" dataSource={data.work_orders} renderItem={(w: any) => (
                <List.Item style={{ padding: '6px 4px' }}>
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <b style={{ fontSize: 12 }}>{w.code}</b>
                      <Tag color={w.priority === 'urgent' ? 'red' : w.priority === 'high' ? 'orange' : 'default'} style={{ fontSize: 10 }}>{w.priority}</Tag>
                      <Tag color={statusColor[w.status] || 'default'} style={{ fontSize: 10 }}>{w.status}</Tag>
                    </div>
                    <div style={{ fontSize: 11, color: '#93A0B4' }}>{w.product} · {w.qty}件 · 交期 {w.due}</div>
                  </div>
                </List.Item>
              )} />
            )}
          </Card>
        </Col>

        {/* 跟进任务 */}
        <Col span={12}>
          <Card size="small" title={<span><CarryOutOutlined /> 跟进任务（{data.tasks.length}）</span>} bodyStyle={{ padding: 8, maxHeight: 260, overflow: 'auto' }}>
            {data.tasks.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
              <List size="small" dataSource={data.tasks} renderItem={(t: any) => (
                <List.Item style={{ padding: '6px 4px' }}>
                  <div style={{ width: '100%' }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <span style={{ fontSize: 12 }}>{t.title}</span>
                      <Tag color={statusColor[t.status] || 'default'} style={{ fontSize: 10 }}>{t.status}</Tag>
                    </div>
                    <div style={{ fontSize: 11, color: '#93A0B4' }}>进度 {t.progress}% · 下次跟进 {t.next_follow}</div>
                  </div>
                </List.Item>
              )} />
            )}
          </Card>
        </Col>

        {/* 待审批 */}
        <Col span={8}>
          <Card size="small" title={<span><AuditOutlined /> 待审批（{data.approvals.length}）</span>} bodyStyle={{ padding: 8, maxHeight: 180, overflow: 'auto' }}>
            {data.approvals.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
              <List size="small" dataSource={data.approvals} renderItem={(a: any) => (
                <List.Item style={{ padding: '5px 2px' }}>
                  <div>
                    <div style={{ fontSize: 11.5 }}>{a.title}</div>
                    <div style={{ fontSize: 10, color: '#93A0B4' }}>{a.code} · {a.type} · {a.created}</div>
                  </div>
                </List.Item>
              )} />
            )}
          </Card>
        </Col>

        {/* 通知 */}
        <Col span={8}>
          <Card size="small" title={<span><BellOutlined /> 未读通知（{data.notifications.length}）</span>} bodyStyle={{ padding: 8, maxHeight: 180, overflow: 'auto' }}>
            {data.notifications.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
              <List size="small" dataSource={data.notifications} renderItem={(n: any) => (
                <List.Item style={{ padding: '5px 2px' }}>
                  <div>
                    <div style={{ fontSize: 11.5 }}>{n.title}</div>
                    <div style={{ fontSize: 10, color: '#93A0B4' }}>{n.category} · {n.at}</div>
                  </div>
                </List.Item>
              )} />
            )}
          </Card>
        </Col>

        {/* 今日变更 */}
        <Col span={8}>
          <Card size="small" title={<span><SwapOutlined /> 今日变更（{data.changes.length}）</span>} bodyStyle={{ padding: 8, maxHeight: 180, overflow: 'auto' }}>
            {data.changes.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
              <List size="small" dataSource={data.changes} renderItem={(c: any) => (
                <List.Item style={{ padding: '5px 2px' }}>
                  <div>
                    <div style={{ fontSize: 11.5 }}>
                      <Tag color="orange" style={{ fontSize: 10 }}>{TYPE_LABEL[c.type] || c.type}</Tag>
                      {c.target} <span style={{ color: '#93A0B4' }}>{c.change}</span>
                    </div>
                    <div style={{ fontSize: 10, color: '#93A0B4' }}>{c.reason} · {c.at}</div>
                  </div>
                </List.Item>
              )} />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}
