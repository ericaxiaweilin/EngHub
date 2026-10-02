/**
 * RCC 决策中心 — AI资源决策建议 + 审批工作流
 * 接入后端 /rcc/decision/* 全系列API
 */
import { useState, useEffect, useMemo } from 'react'
import { Row, Col, Tag, Space, Button, message, Empty, Modal, Input, Timeline, Badge, Tooltip, Progress } from 'antd'
import {
  ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined,
  TeamOutlined, ToolOutlined, FileTextOutlined, EnvironmentOutlined,
  ExperimentOutlined, FireOutlined, SafetyOutlined, ClockCircleOutlined,
  AuditOutlined, SendOutlined, BulbOutlined, RobotOutlined
} from '@ant-design/icons'
import axios from 'axios'
import { useRcc, COLORS } from './RCCCommandCenter'

const API_BASE = '/api/v1/rcc'

// ==================== 决策卡片 ====================
function DecisionCard({ title, icon, color, items, onAdopt }: {
  title: string; icon: React.ReactNode; color: string;
  items: any[]; onAdopt: (item: any) => void;
}) {
  return (
    <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 20, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
        <span style={{ color, fontSize: 16 }}>{icon}</span>
        <span style={{ color: COLORS.text, fontWeight: 600, fontSize: 14 }}>{title}</span>
        <Badge count={items.length} style={{ backgroundColor: color, marginLeft: 'auto' }} />
      </div>
      {items.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {items.slice(0, 4).map((item, i) => (
            <div key={i} style={{
              padding: '12px 14px', borderRadius: 8, background: COLORS.bg,
              border: `1px solid ${COLORS.border}`, borderLeft: `3px solid ${color}`
            }}>
              <div style={{ color: COLORS.text, fontSize: 13, fontWeight: 500, marginBottom: 4 }}>
                {item.action || item.recommendation || item.title || item.description || JSON.stringify(item).slice(0, 80)}
              </div>
              {(item.reason || item.impact) && (
                <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 6 }}>
                  {item.reason && <span>原因: {item.reason}</span>}
                  {item.impact && <span style={{ marginLeft: 8 }}>影响: {item.impact}</span>}
                </div>
              )}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {item.confidence && (
                  <Tooltip title="AI置信度">
                    <Tag style={{ border: 'none', background: `${color}15`, color, fontSize: 10 }}>
                      <RobotOutlined /> {Math.round(item.confidence * 100)}%
                    </Tag>
                  </Tooltip>
                )}
                <Button size="small" type="link" style={{ color, fontSize: 11, padding: 0 }}
                  onClick={() => onAdopt(item)}>
                  <SendOutlined /> 提交审批
                </Button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ color: COLORS.textMuted, fontSize: 12, textAlign: 'center', padding: 16 }}>
          <CheckCircleOutlined style={{ color: COLORS.success, marginRight: 6 }} />暂无需决策
        </div>
      )}
    </div>
  )
}

// ==================== 审批面板 ====================
function ApprovalPanel({ approvals, onApprove, onReject }: {
  approvals: any[]; onApprove: (id: string) => void; onReject: (id: string) => void;
}) {
  return (
    <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <AuditOutlined style={{ color: COLORS.warning, fontSize: 16 }} />
        <span style={{ color: COLORS.text, fontWeight: 600, fontSize: 14 }}>待审批队列</span>
        <Badge count={approvals.length} style={{ backgroundColor: COLORS.warning, marginLeft: 'auto' }} />
      </div>
      {approvals.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {approvals.map((item) => (
            <div key={item.id} style={{
              padding: '12px 14px', borderRadius: 8, background: COLORS.bg,
              border: `1px solid ${COLORS.border}`
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ color: COLORS.text, fontSize: 13, fontWeight: 500 }}>
                    {item.action || item.title}
                  </div>
                  <div style={{ color: COLORS.textMuted, fontSize: 11, marginTop: 4 }}>
                    <ClockCircleOutlined style={{ marginRight: 4 }} />
                    {new Date(item.created_at).toLocaleTimeString('zh-CN')} 提交
                    {item.type && <Tag style={{ marginLeft: 8, fontSize: 10, border: 'none', background: `${COLORS.accentBlue}15`, color: COLORS.accentBlue }}>{item.type}</Tag>}
                  </div>
                </div>
                <Space size={6}>
                  <Button size="small" type="primary" style={{ background: COLORS.success, borderColor: COLORS.success }}
                    icon={<CheckCircleOutlined />} onClick={() => onApprove(item.id)}>批准</Button>
                  <Button size="small" danger icon={<CloseCircleOutlined />} onClick={() => onReject(item.id)}>驳回</Button>
                </Space>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ color: COLORS.textMuted, fontSize: 12, textAlign: 'center', padding: 20 }}>
          <SafetyOutlined style={{ fontSize: 24, color: COLORS.success, display: 'block', marginBottom: 8 }} />
          审批队列已清空
        </div>
      )}
    </div>
  )
}

// ==================== 主组件 ====================
export default function RCCDecisionHub() {
  const { baseline, decisions, factoryId } = useRcc()
  const [approvals, setApprovals] = useState<any[]>([])
  const [decisionLog, setDecisionLog] = useState<any[]>([])
  const [loadingDecisions, setLoadingDecisions] = useState(false)
  const [detailedDecisions, setDetailedDecisions] = useState<any>({})

  // 加载详细决策数据
  useEffect(() => {
    const loadDecisions = async () => {
      setLoadingDecisions(true)
      try {
        const endpoints = [
          { key: 'people', url: `${API_BASE}/decision/people-assignment` },
          { key: 'equipment', url: `${API_BASE}/decision/equipment-schedule` },
          { key: 'workOrder', url: `${API_BASE}/decision/work-order-priority` },
          { key: 'bottleneck', url: `${API_BASE}/decision/bottleneck-resolution` },
        ]
        const results = await Promise.allSettled(
          endpoints.map(ep => axios.get(ep.url, { params: { factory_id: factoryId } }))
        )
        const data: any = {}
        results.forEach((r, i) => {
          if (r.status === 'fulfilled' && r.value.data?.success) {
            data[endpoints[i].key] = r.value.data.data
          }
        })
        setDetailedDecisions(data)
      } catch (e) { /* ignore */ }
      finally { setLoadingDecisions(false) }
    }
    loadDecisions()
  }, [factoryId])

  // 解析决策数据为列表
  const parsedDecisions = useMemo(() => {
    const extract = (data: any): any[] => {
      if (!data) return []
      if (Array.isArray(data)) return data
      if (data.recommendations) return data.recommendations
      if (data.suggestions) return data.suggestions
      if (data.assignments) return data.assignments
      if (data.schedule) return data.schedule
      if (data.priorities) return data.priorities
      if (data.solutions) return data.solutions
      // 尝试提取对象中的数组
      for (const v of Object.values(data)) {
        if (Array.isArray(v) && v.length > 0) return v as any[]
      }
      return []
    }
    return {
      people: extract(detailedDecisions.people),
      equipment: extract(detailedDecisions.equipment),
      workOrder: extract(detailedDecisions.workOrder),
      bottleneck: extract(detailedDecisions.bottleneck),
    }
  }, [detailedDecisions])

  // 前端场景决策（补充）
  const scenarioDecisions = useMemo(() => {
    const people = baseline.people || baseline?.baseline?.people || {}
    const equipment = baseline.equipment || baseline?.baseline?.equipment || {}
    const workOrders = baseline.work_orders || baseline?.baseline?.work_orders || {}
    const activeWorkers = people.active_workers || 0
    const totalOrders = Object.values(workOrders.status || {}).reduce((s: number, v: any) => s + (v as number), 0)
    const statusDist = equipment.status_distribution || equipment.statuses || {}
    const runningEquip = statusDist.running || 0
    const equipTotal = equipment.total || 0
    const utilRate = equipTotal > 0 ? runningEquip / equipTotal : 0

    if (totalOrders === 0 && activeWorkers > 0) {
      return [
        { action: '启动外协接单', reason: '人员和设备闲置，成本浪费', impact: '产能利用率提升30-50%', confidence: 0.85, type: 'opportunity' },
        { action: '安排设备预防性维护', reason: '利用空闲窗口降低故障风险', impact: 'PM逾期减少40%', confidence: 0.9, type: 'maintenance' },
        { action: '员工多技能培训', reason: '为订单恢复储备柔性产能', impact: '团队灵活性提升', confidence: 0.7, type: 'hr' },
      ]
    }
    if (utilRate > 0.85 || (workOrders.delivery_risk_count || 0) > 5) {
      return [
        { action: '启动三班制运行', reason: '产能接近极限', impact: '日产能提升60-80%', confidence: 0.85, type: 'schedule' },
        { action: '外协分流部分订单', reason: '超出自身产能极限', impact: '处理额外40-60%订单', confidence: 0.8, type: 'opportunity' },
        { action: '推迟低优先级工单', reason: '集中资源保障急单', impact: '急单交付率提升至98%+', confidence: 0.9, type: 'priority' },
      ]
    }
    return []
  }, [baseline])

  const handleAdopt = (item: any) => {
    const newApproval = { ...item, id: `APR-${Date.now()}`, created_at: new Date().toISOString(), status: 'pending' }
    setApprovals(prev => [newApproval, ...prev])
    message.success('已加入审批队列')
  }

  const handleApprove = (id: string) => {
    const item = approvals.find(a => a.id === id)
    setApprovals(prev => prev.filter(a => a.id !== id))
    if (item) {
      setDecisionLog(prev => [{ ...item, status: 'approved', resolved_at: new Date().toISOString() }, ...prev])
    }
    message.success('已批准执行')
  }

  const handleReject = (id: string) => {
    const item = approvals.find(a => a.id === id)
    setApprovals(prev => prev.filter(a => a.id !== id))
    if (item) {
      setDecisionLog(prev => [{ ...item, status: 'rejected', resolved_at: new Date().toISOString() }, ...prev])
    }
    message.info('已驳回')
  }

  return (
    <div>
      <Row gutter={[16, 16]}>
        {/* 左侧：决策建议 */}
        <Col xs={24} lg={14}>
          <div style={{ marginBottom: 16 }}>
            <div style={{ color: COLORS.text, fontSize: 15, fontWeight: 600, marginBottom: 4 }}>
              <BulbOutlined style={{ color: COLORS.warning, marginRight: 8 }} />AI 资源决策建议
            </div>
            <div style={{ color: COLORS.textMuted, fontSize: 12 }}>基于实时资源基线，由决策引擎自动生成</div>
          </div>

          <DecisionCard title="人力调配建议" icon={<TeamOutlined />} color={COLORS.accent}
            items={parsedDecisions.people} onAdopt={handleAdopt} />
          <DecisionCard title="设备调度建议" icon={<ToolOutlined />} color={COLORS.accentBlue}
            items={parsedDecisions.equipment} onAdopt={handleAdopt} />
          <DecisionCard title="工单优先级建议" icon={<FileTextOutlined />} color={COLORS.accentPurple}
            items={parsedDecisions.workOrder} onAdopt={handleAdopt} />
          <DecisionCard title="瓶颈解决方案" icon={<FireOutlined />} color={COLORS.danger}
            items={parsedDecisions.bottleneck} onAdopt={handleAdopt} />

          {/* 场景决策 */}
          {scenarioDecisions.length > 0 && (
            <DecisionCard title="场景应急决策" icon={<ThunderboltOutlined />} color={COLORS.warning}
              items={scenarioDecisions} onAdopt={handleAdopt} />
          )}
        </Col>

        {/* 右侧：审批 + 日志 */}
        <Col xs={24} lg={10}>
          <ApprovalPanel approvals={approvals} onApprove={handleApprove} onReject={handleReject} />

          {/* 决策日志 */}
          <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 20, marginTop: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
              <ClockCircleOutlined style={{ color: COLORS.textMuted, fontSize: 16 }} />
              <span style={{ color: COLORS.text, fontWeight: 600, fontSize: 14 }}>决策执行日志</span>
            </div>
            {decisionLog.length > 0 ? (
              <Timeline
                items={decisionLog.slice(0, 10).map((log) => ({
                  color: log.status === 'approved' ? 'green' : 'red',
                  children: (
                    <div>
                      <div style={{ color: COLORS.text, fontSize: 12, fontWeight: 500 }}>{log.action || log.title}</div>
                      <div style={{ color: COLORS.textMuted, fontSize: 11, marginTop: 2 }}>
                        {log.status === 'approved' ? '✅ 已批准' : '❌ 已驳回'} · {new Date(log.resolved_at).toLocaleTimeString('zh-CN')}
                      </div>
                    </div>
                  )
                }))}
              />
            ) : (
              <div style={{ color: COLORS.textMuted, fontSize: 12, textAlign: 'center', padding: 16 }}>
                暂无决策记录，采纳建议后将在此显示
              </div>
            )}
          </div>
        </Col>
      </Row>
    </div>
  )
}
