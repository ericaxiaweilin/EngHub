/**
 * RCC 指挥总览 — 厂长级执行仪表板
 * 五维资源健康度 + KPI大数字 + 实时告警 + 趋势指示
 */
import { useMemo, useState } from 'react'
import { Row, Col, Progress, Tag, Space, Tooltip, Empty, Button } from 'antd'
import {
  TeamOutlined, ToolOutlined, FileTextOutlined, EnvironmentOutlined,
  ExperimentOutlined, ArrowUpOutlined, ArrowDownOutlined, WarningOutlined,
  CheckCircleOutlined, FireOutlined, ThunderboltOutlined, ClockCircleOutlined,
  EyeOutlined
} from '@ant-design/icons'
import { useRcc, COLORS } from './RCCCommandCenter'
import TraceabilityDrawer from '../../components/TraceabilityDrawer'

// ==================== KPI 卡片组件 ====================
function KpiCard({ icon, label, value, suffix, sub, trend, color, onClick }: {
  icon: React.ReactNode; label: string; value: number | string; suffix?: string;
  sub?: string; trend?: 'up' | 'down' | 'flat'; color: string; onClick?: () => void;
}) {
  return (
    <div onClick={onClick} style={{
      background: COLORS.bgCard, borderRadius: 12, padding: '20px 24px',
      border: `1px solid ${COLORS.border}`, cursor: onClick ? 'pointer' : 'default',
      transition: 'all 0.2s', position: 'relative', overflow: 'hidden',
    }}>
      {/* 顶部光条 */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: color }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ color: COLORS.textMuted, fontSize: 12, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ color }}>{icon}</span> {label}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
            <span style={{ color: COLORS.text, fontSize: 32, fontWeight: 700, lineHeight: 1 }}>{value}</span>
            {suffix && <span style={{ color: COLORS.textDim, fontSize: 14 }}>{suffix}</span>}
          </div>
          {sub && <div style={{ color: COLORS.textMuted, fontSize: 12, marginTop: 8 }}>{sub}</div>}
        </div>
        {trend && (
          <div style={{
            padding: '4px 8px', borderRadius: 6, fontSize: 12,
            background: trend === 'up' ? 'rgba(248,113,113,0.1)' : trend === 'down' ? 'rgba(52,211,153,0.1)' : 'rgba(148,163,184,0.1)',
            color: trend === 'up' ? COLORS.danger : trend === 'down' ? COLORS.success : COLORS.textMuted,
          }}>
            {trend === 'up' ? <ArrowUpOutlined /> : trend === 'down' ? <ArrowDownOutlined /> : '—'}
          </div>
        )}
      </div>
    </div>
  )
}

// ==================== 资源健康度环形图 ====================
function HealthRing({ label, percent, color, icon, onClick }: { label: string; percent: number; color: string; icon: React.ReactNode; onClick?: () => void }) {
  const status = percent >= 80 ? '良好' : percent >= 60 ? '注意' : '警告'
  return (
    <div onClick={onClick} style={{ textAlign: 'center', padding: '16px 12px', cursor: onClick ? 'pointer' : 'default' }}>
      <Progress
        type="circle" size={90} percent={Math.round(percent)}
        strokeColor={color} trailColor={COLORS.bg}
        format={(p) => <span style={{ color: COLORS.text, fontSize: 18, fontWeight: 700 }}>{p}%</span>}
      />
      <div style={{ color: COLORS.textDim, fontSize: 12, marginTop: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
        <span style={{ color }}>{icon}</span> {label}
      </div>
      <Tag style={{
        marginTop: 6, fontSize: 11, border: 'none',
        background: percent >= 80 ? 'rgba(52,211,153,0.1)' : percent >= 60 ? 'rgba(251,191,36,0.1)' : 'rgba(248,113,113,0.1)',
        color: percent >= 80 ? COLORS.success : percent >= 60 ? COLORS.warning : COLORS.danger,
      }}>{status}</Tag>
    </div>
  )
}

// ==================== 告警条 ====================
function AlertBanner({ alerts }: { alerts: any[] }) {
  if (!alerts || alerts.length === 0) return null
  return (
    <div style={{
      background: 'rgba(248,113,113,0.08)', border: '1px solid rgba(248,113,113,0.3)',
      borderRadius: 10, padding: '12px 20px', marginBottom: 20,
      display: 'flex', alignItems: 'center', gap: 12,
    }}>
      <WarningOutlined style={{ color: COLORS.danger, fontSize: 18 }} />
      <div style={{ flex: 1 }}>
        <span style={{ color: COLORS.danger, fontWeight: 600, fontSize: 13 }}>
          {alerts.length} 项资源告警需要关注
        </span>
        <span style={{ color: COLORS.textDim, fontSize: 12, marginLeft: 12 }}>
          {alerts.slice(0, 3).map((a: any) => a.message || a).join(' | ')}
        </span>
      </div>
      <Tag color="red" style={{ borderRadius: 4 }}>{alerts.length}</Tag>
    </div>
  )
}

// ==================== 工单状态分布条 ====================
function OrderStatusBar({ statusMap }: { statusMap: Record<string, number> }) {
  const total = Object.values(statusMap).reduce((s, v) => s + v, 0) || 1
  const colorMap: Record<string, string> = {
    in_progress: COLORS.accentBlue, completed: COLORS.success, pending: COLORS.warning,
    delayed: COLORS.danger, planned: COLORS.accentPurple, released: COLORS.accent,
  }
  return (
    <div>
      <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', marginBottom: 12 }}>
        {Object.entries(statusMap).map(([k, v]) => (
          <div key={k} style={{ width: `${(v / total) * 100}%`, background: colorMap[k] || COLORS.textMuted, transition: 'width 0.5s' }} />
        ))}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
        {Object.entries(statusMap).map(([k, v]) => (
          <Space key={k} size={4}>
            <div style={{ width: 8, height: 8, borderRadius: 2, background: colorMap[k] || COLORS.textMuted }} />
            <span style={{ color: COLORS.textDim, fontSize: 12 }}>{k}: {v}</span>
          </Space>
        ))}
      </div>
    </div>
  )
}

// ==================== 主组件 ====================
export default function RCCOverview() {
  const { baseline, decisions, factoryId } = useRcc()
  const [traceTarget, setTraceTarget] = useState<{ domain: string; title: string } | null>(null)

  const people = baseline.people || baseline?.baseline?.people || {}
  const equipment = baseline.equipment || baseline?.baseline?.equipment || {}
  const workOrders = baseline.work_orders || baseline?.baseline?.work_orders || {}
  const environment = baseline.environment || baseline?.baseline?.environment || {}
  const process = baseline.process || baseline?.baseline?.process || {}

  // 计算核心指标
  const metrics = useMemo(() => {
    const activeWorkers = people.active_workers || 0
    const attendanceRate = people.attendance_rate_pct || 0
    const equipTotal = equipment.total || 0
    const statusDist = equipment.status_distribution || equipment.statuses || {}
    const runningEquip = statusDist.running || 0
    const oee = equipment.oee_actual_pct || 0
    const woStatus = workOrders.status || {}
    const totalOrders = Object.values(woStatus).reduce((s: number, v: any) => s + (v as number), 0)
    const urgentCount = workOrders.urgent_count || 0
    const deliveryRisk = workOrders.delivery_risk_count || 0
    const pmOverdue = equipment.pm_overdue_count || 0

    // 健康度计算
    const peopleHealth = activeWorkers > 0 ? Math.min(attendanceRate, 100) : 0
    const equipHealth = equipTotal > 0 ? (runningEquip / equipTotal) * 100 : 0
    const orderHealth = totalOrders > 0 ? Math.max(0, 100 - (deliveryRisk / totalOrders) * 100) : 100
    const envHealth = environment.alert ? 40 : environment.warnings?.length ? 70 : 95
    const processHealth = process.yield_baseline_30d || 92

    // 告警汇总
    const alerts: any[] = [
      ...(people.alerts || []),
      ...(environment.warnings || []),
      ...(pmOverdue > 0 ? [{ message: `${pmOverdue}台设备PM逾期` }] : []),
      ...(deliveryRisk > 0 ? [{ message: `${deliveryRisk}个工单交期风险` }] : []),
    ]

    return {
      activeWorkers, attendanceRate, equipTotal, runningEquip, oee,
      totalOrders, urgentCount, deliveryRisk, pmOverdue, statusDist, woStatus,
      peopleHealth, equipHealth, orderHealth, envHealth, processHealth, alerts
    }
  }, [people, equipment, workOrders, environment, process])

  const openTrace = (domain: string, title: string) => setTraceTarget({ domain, title })

  return (
    <div>
      {/* 告警横幅 */}
      <AlertBanner alerts={metrics.alerts} />

      {/* 核心KPI - 第一行 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 20 }}>
        <Col xs={24} sm={12} lg={6}>
          <KpiCard
            icon={<TeamOutlined />} label="在岗人力" color={COLORS.accent}
            value={metrics.activeWorkers} suffix="人"
            sub={`出勤率 ${metrics.attendanceRate}%`}
            trend={metrics.attendanceRate > 95 ? 'down' : metrics.attendanceRate < 85 ? 'up' : 'flat'}
            onClick={() => openTrace('people', '在岗人力追溯')}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <KpiCard
            icon={<ToolOutlined />} label="设备OEE" color={COLORS.accentBlue}
            value={metrics.oee} suffix="%"
            sub={`${metrics.runningEquip}/${metrics.equipTotal} 台运行中`}
            trend={metrics.oee >= 85 ? 'down' : 'up'}
            onClick={() => openTrace('equipment', '设备OEE追溯')}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <KpiCard
            icon={<FileTextOutlined />} label="在制工单" color={COLORS.accentPurple}
            value={metrics.totalOrders} suffix="个"
            sub={`急单 ${metrics.urgentCount} · 风险 ${metrics.deliveryRisk}`}
            trend={metrics.urgentCount > 3 ? 'up' : 'flat'}
            onClick={() => openTrace('work_orders', '在制工单追溯')}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <KpiCard
            icon={<ThunderboltOutlined />} label="PM逾期" color={metrics.pmOverdue > 0 ? COLORS.danger : COLORS.success}
            value={metrics.pmOverdue} suffix="台"
            sub={metrics.pmOverdue > 0 ? '需立即安排维护' : '设备维护正常'}
            trend={metrics.pmOverdue > 0 ? 'up' : 'flat'}
            onClick={() => openTrace('pm', 'PM逾期追溯')}
          />
        </Col>
      </Row>

      {/* 五维健康度 + 工单分布 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 24 }}>
            <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 14, marginBottom: 16 }}>
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <span><ExperimentOutlined style={{ color: COLORS.accent, marginRight: 8 }} />五维资源健康度</span>
                <Tooltip title="追溯五维来源">
                  <Button type="text" size="small" icon={<EyeOutlined />} onClick={() => openTrace('rcc', '五维资源健康追溯')} style={{ color: COLORS.textDim }} />
                </Tooltip>
              </Space>
            </div>
            <Row gutter={8}>
              <Col span={4} offset={1}><HealthRing label="人力" percent={metrics.peopleHealth} color={COLORS.accent} icon={<TeamOutlined />} onClick={() => openTrace('people', '人力健康度追溯')} /></Col>
              <Col span={4} offset={1}><HealthRing label="设备" percent={metrics.equipHealth} color={COLORS.accentBlue} icon={<ToolOutlined />} onClick={() => openTrace('equipment', '设备健康度追溯')} /></Col>
              <Col span={4} offset={1}><HealthRing label="工单" percent={metrics.orderHealth} color={COLORS.accentPurple} icon={<FileTextOutlined />} onClick={() => openTrace('work_orders', '工单健康度追溯')} /></Col>
              <Col span={4} offset={1}><HealthRing label="环境" percent={metrics.envHealth} color={COLORS.warning} icon={<EnvironmentOutlined />} onClick={() => openTrace('qms', '环境/质量预警追溯')} /></Col>
              <Col span={4} offset={1}><HealthRing label="工艺" percent={metrics.processHealth} color={COLORS.success} icon={<ExperimentOutlined />} onClick={() => openTrace('process', '工艺健康度追溯')} /></Col>
            </Row>
          </div>
        </Col>
        <Col xs={24} lg={10}>
          <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 24, height: '100%' }}>
            <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 14, marginBottom: 16 }}>
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <span><FileTextOutlined style={{ color: COLORS.accentPurple, marginRight: 8 }} />工单状态分布</span>
                <Tooltip title="追溯工单来源">
                  <Button type="text" size="small" icon={<EyeOutlined />} onClick={() => openTrace('work_orders', '工单状态分布追溯')} style={{ color: COLORS.textDim }} />
                </Tooltip>
              </Space>
            </div>
            {Object.keys(metrics.woStatus).length > 0 ? (
              <>
                <OrderStatusBar statusMap={metrics.woStatus} />
                <div style={{ marginTop: 20, padding: '12px 16px', borderRadius: 8, background: COLORS.bg }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ color: COLORS.textDim, fontSize: 12 }}>交期风险率</span>
                    <span style={{ color: metrics.deliveryRisk > 3 ? COLORS.danger : COLORS.success, fontSize: 12, fontWeight: 600 }}>
                      {metrics.totalOrders > 0 ? Math.round((metrics.deliveryRisk / metrics.totalOrders) * 100) : 0}%
                    </span>
                  </div>
                  <Progress
                    percent={metrics.totalOrders > 0 ? Math.round((metrics.deliveryRisk / metrics.totalOrders) * 100) : 0}
                    strokeColor={metrics.deliveryRisk > 3 ? COLORS.danger : COLORS.success}
                    trailColor={COLORS.bgHover} showInfo={false} size="small"
                  />
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12, marginBottom: 8 }}>
                    <span style={{ color: COLORS.textDim, fontSize: 12 }}>急单占比</span>
                    <span style={{ color: metrics.urgentCount > 5 ? COLORS.warning : COLORS.textDim, fontSize: 12, fontWeight: 600 }}>
                      {metrics.totalOrders > 0 ? Math.round((metrics.urgentCount / metrics.totalOrders) * 100) : 0}%
                    </span>
                  </div>
                  <Progress
                    percent={metrics.totalOrders > 0 ? Math.round((metrics.urgentCount / metrics.totalOrders) * 100) : 0}
                    strokeColor={COLORS.warning} trailColor={COLORS.bgHover} showInfo={false} size="small"
                  />
                </div>
              </>
            ) : (
              <Empty description={<span style={{ color: COLORS.textMuted }}>暂无工单数据</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </div>
        </Col>
      </Row>

      {/* 设备状态 + 决策摘要 */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={10}>
          <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 24 }}>
            <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 14, marginBottom: 16 }}>
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <span><ToolOutlined style={{ color: COLORS.accentBlue, marginRight: 8 }} />设备状态矩阵</span>
                <Tooltip title="追溯设备来源">
                  <Button type="text" size="small" icon={<EyeOutlined />} onClick={() => openTrace('equipment', '设备状态矩阵追溯')} style={{ color: COLORS.textDim }} />
                </Tooltip>
              </Space>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(80px, 1fr))', gap: 8 }}>
              {Object.entries(metrics.statusDist).map(([status, count]) => {
                const colorMap: Record<string, string> = { running: COLORS.success, idle: COLORS.textMuted, maintenance: COLORS.warning, broken: COLORS.danger, setup: COLORS.accentBlue }
                const labelMap: Record<string, string> = { running: '运行', idle: '空闲', maintenance: '维护', broken: '故障', setup: '换型' }
                return (
                  <div key={status} style={{
                    textAlign: 'center', padding: '12px 8px', borderRadius: 8,
                    background: `${colorMap[status] || COLORS.textMuted}15`,
                    border: `1px solid ${colorMap[status] || COLORS.textMuted}30`,
                  }}>
                    <div style={{ color: colorMap[status] || COLORS.textMuted, fontSize: 22, fontWeight: 700 }}>{count as number}</div>
                    <div style={{ color: COLORS.textDim, fontSize: 11, marginTop: 4 }}>{labelMap[status] || status}</div>
                  </div>
                )
              })}
              {Object.keys(metrics.statusDist).length === 0 && (
                <div style={{ gridColumn: '1/-1', color: COLORS.textMuted, textAlign: 'center', padding: 20 }}>暂无设备数据</div>
              )}
            </div>
          </div>
        </Col>
        <Col xs={24} lg={14}>
          <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 24 }}>
            <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 14, marginBottom: 16 }}>
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <span><ThunderboltOutlined style={{ color: COLORS.warning, marginRight: 8 }} />AI 决策摘要</span>
                <Tooltip title="追溯RCC决策链">
                  <Button type="text" size="small" icon={<EyeOutlined />} onClick={() => openTrace('rcc', 'AI决策摘要追溯')} style={{ color: COLORS.textDim }} />
                </Tooltip>
              </Space>
            </div>
            {decisions && Object.keys(decisions).length > 0 ? (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                {Object.entries(decisions).slice(0, 6).map(([key, val]: [string, any]) => {
                  const label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
                  const count = Array.isArray(val) ? val.length : typeof val === 'object' ? Object.keys(val || {}).length : 0
                  return (
                    <div key={key} style={{ padding: '12px 16px', borderRadius: 8, background: COLORS.bg, border: `1px solid ${COLORS.border}` }}>
                      <div style={{ color: COLORS.textDim, fontSize: 11, marginBottom: 4 }}>{label}</div>
                      <div style={{ color: COLORS.text, fontSize: 16, fontWeight: 600 }}>
                        {count > 0 ? `${count} 项建议` : '正常'}
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: 30, color: COLORS.textMuted }}>
                <CheckCircleOutlined style={{ fontSize: 32, color: COLORS.success, marginBottom: 12 }} />
                <div>当前资源状态良好，无需紧急决策</div>
              </div>
            )}
          </div>
        </Col>
      </Row>
      <TraceabilityDrawer
        open={!!traceTarget}
        factoryId={factoryId}
        domain={traceTarget?.domain || null}
        title={traceTarget?.title}
        onClose={() => setTraceTarget(null)}
      />
    </div>
  )
}
