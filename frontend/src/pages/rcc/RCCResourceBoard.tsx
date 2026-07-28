/**
 * RCC 资源调度 — 人/机/单三维资源统筹面板
 * 实时资源分配 + 负荷热力 + 调度建议
 */
import { useState, useMemo } from 'react'
import { Row, Col, Tag, Space, Progress, Empty, Table, Tooltip, Badge } from 'antd'
import {
  TeamOutlined, ToolOutlined, FileTextOutlined, SwapOutlined,
  FireOutlined, CheckCircleOutlined, WarningOutlined, UserOutlined,
  ClockCircleOutlined, ThunderboltOutlined
} from '@ant-design/icons'
import { useRcc, COLORS } from './RCCCommandCenter'

// ==================== 负荷条 ====================
function LoadBar({ percent, label }: { percent: number; label?: string }) {
  const color = percent >= 85 ? COLORS.danger : percent >= 70 ? COLORS.warning : percent >= 40 ? COLORS.accentBlue : COLORS.success
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {label && <span style={{ color: COLORS.textDim, fontSize: 12, minWidth: 60 }}>{label}</span>}
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: COLORS.bg, overflow: 'hidden' }}>
        <div style={{ width: `${Math.min(percent, 100)}%`, height: '100%', borderRadius: 3, background: color, transition: 'width 0.6s ease' }} />
      </div>
      <span style={{ color, fontSize: 12, fontWeight: 600, minWidth: 36, textAlign: 'right' }}>{Math.round(percent)}%</span>
    </div>
  )
}

// ==================== 人员资源面板 ====================
function PeoplePanel({ people }: { people: any }) {
  const workCenterLoad = people.work_center_load || []
  const topBusy = people.top_busy_employees || []
  const headcount = people.headcount || {}
  const skills = people.skill_distribution || people.skills || {}

  return (
    <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 20, height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 14 }}>
          <TeamOutlined style={{ color: COLORS.accent, marginRight: 8 }} />人力资源
        </div>
        <Tag style={{ background: 'rgba(0,212,170,0.1)', border: 'none', color: COLORS.accent }}>
          {people.active_workers || 0} 在岗
        </Tag>
      </div>

      {/* 工位负荷 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1 }}>工位负荷</div>
        {workCenterLoad.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {workCenterLoad.slice(0, 6).map((wc: any, i: number) => (
              <LoadBar key={i} label={wc.name || `工位${i + 1}`} percent={(wc.load_rate || 0) * 100} />
            ))}
          </div>
        ) : (
          <div style={{ color: COLORS.textMuted, fontSize: 12, textAlign: 'center', padding: 12 }}>暂无工位负荷数据</div>
        )}
      </div>

      {/* 最忙人员 TOP5 */}
      <div>
        <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1 }}>
          <FireOutlined style={{ color: COLORS.danger, marginRight: 4 }} />高负荷人员
        </div>
        {topBusy.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {topBusy.slice(0, 5).map((emp: any, i: number) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
                borderRadius: 8, background: COLORS.bg, border: `1px solid ${COLORS.border}`
              }}>
                <div style={{
                  width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: (emp.load_rate || 0) > 0.85 ? 'rgba(248,113,113,0.2)' : 'rgba(79,172,254,0.2)',
                  color: (emp.load_rate || 0) > 0.85 ? COLORS.danger : COLORS.accentBlue, fontSize: 12, fontWeight: 700
                }}>{emp.name?.[0] || '?'}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ color: COLORS.text, fontSize: 12, fontWeight: 500 }}>{emp.name}</div>
                  <div style={{ color: COLORS.textMuted, fontSize: 11 }}>{emp.department} · {emp.current_task || '待分配'}</div>
                </div>
                <Tag style={{
                  border: 'none', fontSize: 11,
                  background: (emp.load_rate || 0) > 0.85 ? 'rgba(248,113,113,0.15)' : 'rgba(79,172,254,0.15)',
                  color: (emp.load_rate || 0) > 0.85 ? COLORS.danger : COLORS.accentBlue,
                }}>{Math.round((emp.load_rate || 0) * 100)}%</Tag>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ color: COLORS.textMuted, fontSize: 12, textAlign: 'center', padding: 12 }}>暂无高负荷人员</div>
        )}
      </div>

      {/* 技能分布 */}
      {Object.keys(skills).length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1 }}>技能分布</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {Object.entries(skills).slice(0, 8).map(([skill, count]) => (
              <Tag key={skill} style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, color: COLORS.textDim, fontSize: 11 }}>
                {skill}: {count as number}
              </Tag>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ==================== 设备资源面板 ====================
function EquipmentPanel({ equipment }: { equipment: any }) {
  const statusDist = equipment.status_distribution || equipment.statuses || {}
  const overloaded = equipment.overloaded_devices || []
  const total = equipment.total || 0
  const oee = equipment.oee_actual_pct || 0
  const pmOverdue = equipment.pm_overdue_count || 0

  const statusConfig: Record<string, { color: string; label: string }> = {
    running: { color: COLORS.success, label: '运行' },
    idle: { color: COLORS.textMuted, label: '空闲' },
    maintenance: { color: COLORS.warning, label: '维护' },
    broken: { color: COLORS.danger, label: '故障' },
    setup: { color: COLORS.accentBlue, label: '换型' },
  }

  return (
    <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 20, height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 14 }}>
          <ToolOutlined style={{ color: COLORS.accentBlue, marginRight: 8 }} />设备资源
        </div>
        <Space size={8}>
          <Tag style={{ background: 'rgba(79,172,254,0.1)', border: 'none', color: COLORS.accentBlue }}>OEE {oee}%</Tag>
          {pmOverdue > 0 && <Tag style={{ background: 'rgba(248,113,113,0.1)', border: 'none', color: COLORS.danger }}>PM逾期 {pmOverdue}</Tag>}
        </Space>
      </div>

      {/* 设备状态环形 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {Object.entries(statusDist).map(([status, count]) => {
          const cfg = statusConfig[status] || { color: COLORS.textMuted, label: status }
          return (
            <div key={status} style={{
              flex: '1 1 auto', minWidth: 70, textAlign: 'center', padding: '10px 8px',
              borderRadius: 8, background: `${cfg.color}10`, border: `1px solid ${cfg.color}25`
            }}>
              <div style={{ color: cfg.color, fontSize: 20, fontWeight: 700 }}>{count as number}</div>
              <div style={{ color: COLORS.textDim, fontSize: 11, marginTop: 2 }}>{cfg.label}</div>
            </div>
          )
        })}
      </div>

      {/* 利用率 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ color: COLORS.textMuted, fontSize: 12 }}>综合利用率</span>
          <span style={{ color: COLORS.accentBlue, fontSize: 12, fontWeight: 600 }}>
            {total > 0 ? Math.round(((statusDist.running || 0) / total) * 100) : 0}%
          </span>
        </div>
        <Progress
          percent={total > 0 ? Math.round(((statusDist.running || 0) / total) * 100) : 0}
          strokeColor={{ from: COLORS.accentBlue, to: COLORS.accent }}
          trailColor={COLORS.bg} showInfo={false} size="small"
        />
      </div>

      {/* 高负荷设备 */}
      <div>
        <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1 }}>
          <WarningOutlined style={{ color: COLORS.warning, marginRight: 4 }} />高负荷设备
        </div>
        {overloaded.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {overloaded.slice(0, 5).map((dev: any, i: number) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
                borderRadius: 8, background: COLORS.bg, border: `1px solid ${COLORS.border}`
              }}>
                <ToolOutlined style={{ color: (dev.utilization_rate || 0) > 0.85 ? COLORS.danger : COLORS.warning }} />
                <div style={{ flex: 1 }}>
                  <div style={{ color: COLORS.text, fontSize: 12, fontWeight: 500 }}>{dev.name || dev.equipment_name}</div>
                  <div style={{ color: COLORS.textMuted, fontSize: 11 }}>{dev.status === 'running' ? '运行中' : dev.status}</div>
                </div>
                <Tag style={{
                  border: 'none', fontSize: 11,
                  background: (dev.utilization_rate || 0) > 0.85 ? 'rgba(248,113,113,0.15)' : 'rgba(251,191,36,0.15)',
                  color: (dev.utilization_rate || 0) > 0.85 ? COLORS.danger : COLORS.warning,
                }}>{Math.round((dev.utilization_rate || 0) * 100)}%</Tag>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ color: COLORS.textMuted, fontSize: 12, textAlign: 'center', padding: 12 }}>设备负荷正常</div>
        )}
      </div>
    </div>
  )
}

// ==================== 工单资源面板 ====================
function WorkOrderPanel({ workOrders }: { workOrders: any }) {
  const statusMap = workOrders.status || {}
  const riskyOrders = workOrders.risky_orders || []
  const urgentCount = workOrders.urgent_count || 0
  const deliveryRisk = workOrders.delivery_risk_count || 0
  const total = Object.values(statusMap).reduce((s: number, v: any) => s + (v as number), 0)

  const priorityColors: Record<string, string> = { P0: COLORS.danger, P1: COLORS.warning, P2: COLORS.accentBlue, P3: COLORS.textMuted }

  return (
    <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 20, height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 14 }}>
          <FileTextOutlined style={{ color: COLORS.accentPurple, marginRight: 8 }} />工单统筹
        </div>
        <Space size={8}>
          <Tag style={{ background: 'rgba(167,139,250,0.1)', border: 'none', color: COLORS.accentPurple }}>{total} 在制</Tag>
          {urgentCount > 0 && <Tag style={{ background: 'rgba(248,113,113,0.1)', border: 'none', color: COLORS.danger }}>{urgentCount} 急单</Tag>}
        </Space>
      </div>

      {/* 状态分布 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {Object.entries(statusMap).map(([status, count]) => (
          <div key={status} style={{ padding: '6px 12px', borderRadius: 6, background: COLORS.bg, border: `1px solid ${COLORS.border}` }}>
            <span style={{ color: COLORS.text, fontSize: 14, fontWeight: 600 }}>{count as number}</span>
            <span style={{ color: COLORS.textMuted, fontSize: 11, marginLeft: 6 }}>{status}</span>
          </div>
        ))}
      </div>

      {/* 风险工单 */}
      <div>
        <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 1 }}>
          <ClockCircleOutlined style={{ color: COLORS.danger, marginRight: 4 }} />交期风险工单
        </div>
        {riskyOrders.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {riskyOrders.slice(0, 6).map((wo: any, i: number) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
                borderRadius: 8, background: COLORS.bg, border: `1px solid ${COLORS.border}`
              }}>
                <div style={{
                  padding: '2px 6px', borderRadius: 4, fontSize: 10, fontWeight: 700,
                  background: `${priorityColors[wo.priority] || COLORS.textMuted}20`,
                  color: priorityColors[wo.priority] || COLORS.textMuted,
                }}>{wo.priority || 'P2'}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ color: COLORS.text, fontSize: 12, fontWeight: 500 }}>{wo.code || wo.work_order_code}</div>
                  <div style={{ color: COLORS.textMuted, fontSize: 11 }}>{wo.product || ''} · 截止 {wo.due_date || '-'}</div>
                </div>
                {wo.status === 'delayed' && <Tag color="red" style={{ fontSize: 10, lineHeight: '16px' }}>延误</Tag>}
              </div>
            ))}
          </div>
        ) : (
          <div style={{ color: COLORS.textMuted, fontSize: 12, textAlign: 'center', padding: 12 }}>
            <CheckCircleOutlined style={{ color: COLORS.success, marginRight: 6 }} />无交期风险
          </div>
        )}
      </div>
    </div>
  )
}

// ==================== 主组件 ====================
export default function RCCResourceBoard() {
  const { baseline, decisions } = useRcc()

  const people = baseline.people || baseline?.baseline?.people || {}
  const equipment = baseline.equipment || baseline?.baseline?.equipment || {}
  const workOrders = baseline.work_orders || baseline?.baseline?.work_orders || {}

  // 调度建议
  const schedulingAdvice = useMemo(() => {
    const advice: { type: string; icon: React.ReactNode; color: string; text: string }[] = []
    const wcLoad = people.work_center_load || []
    const overloaded = wcLoad.filter((w: any) => (w.load_rate || 0) > 0.85)
    const underloaded = wcLoad.filter((w: any) => (w.load_rate || 0) < 0.3)

    if (overloaded.length > 0) {
      advice.push({ type: 'balance', icon: <SwapOutlined />, color: COLORS.warning, text: `${overloaded.length}个工位超负荷，建议从低负荷工位调配人员` })
    }
    if (underloaded.length > 0 && overloaded.length > 0) {
      advice.push({ type: 'transfer', icon: <TeamOutlined />, color: COLORS.accentBlue, text: `${underloaded.map((w: any) => w.name).join('、')} 负荷不足，可支援繁忙工位` })
    }
    if ((equipment.pm_overdue_count || 0) > 0) {
      advice.push({ type: 'pm', icon: <ToolOutlined />, color: COLORS.danger, text: `${equipment.pm_overdue_count}台设备PM逾期，建议利用空闲时段安排维护` })
    }
    if ((workOrders.urgent_count || 0) > 3) {
      advice.push({ type: 'priority', icon: <ThunderboltOutlined />, color: COLORS.danger, text: `${workOrders.urgent_count}个急单并行，建议集中资源保障P0/P1` })
    }
    if (advice.length === 0) {
      advice.push({ type: 'ok', icon: <CheckCircleOutlined />, color: COLORS.success, text: '资源分配均衡，无需紧急调度' })
    }
    return advice
  }, [people, equipment, workOrders])

  return (
    <div>
      {/* 调度建议横幅 */}
      <div style={{ marginBottom: 20, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {schedulingAdvice.map((a, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 12, padding: '10px 16px',
            borderRadius: 8, background: `${a.color}08`, border: `1px solid ${a.color}25`
          }}>
            <span style={{ color: a.color, fontSize: 16 }}>{a.icon}</span>
            <span style={{ color: COLORS.text, fontSize: 13 }}>{a.text}</span>
          </div>
        ))}
      </div>

      {/* 三维资源面板 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={8}><PeoplePanel people={people} /></Col>
        <Col xs={24} lg={8}><EquipmentPanel equipment={equipment} /></Col>
        <Col xs={24} lg={8}><WorkOrderPanel workOrders={workOrders} /></Col>
      </Row>
    </div>
  )
}
