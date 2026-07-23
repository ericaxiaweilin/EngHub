import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert as AntAlert, Badge, Button, Card, Col, Divider, Empty, InputNumber, Progress, Rate, Row, Segmented,
  Select, Slider, Space, Switch, Table, Tabs, Tag, Tooltip, Typography, message,
} from 'antd'
import {
  AimOutlined, ApartmentOutlined, BankOutlined, ClusterOutlined, ControlOutlined, DashboardOutlined,
  DeleteOutlined, DeploymentUnitOutlined, ExperimentOutlined, ExportOutlined, FieldTimeOutlined,
  NodeIndexOutlined, PlusOutlined, ProfileOutlined, ReloadOutlined, RiseOutlined, SwapOutlined,
  TeamOutlined, ThunderboltOutlined, WarningOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  BLOCKING_TYPE_COLOR, BLOCKING_TYPE_LABEL, FactoryScenarioMeta, FactorySimConfig,
  FactorySimResult, OrderInput, OrderResult, OrderSectionLoad, OutboundOrder, PRIORITY_COLOR,
  PRIORITY_LABEL, Priority, ProductionOrderResult, ProductionStrategy, SectionConfig, STRATEGY_LABEL,
  WorkshopConfig, getFactoryScenario, getFactoryScenarios, runFactorySimulation,
} from '../../services/factorySim'
import FlowTopology from './FlowTopology'

const { Text } = Typography

/* ==================== 常量 & 工具 ==================== */

const DOW = ['一', '二', '三', '四', '五', '六', '日']
const SECTION_PALETTE = ['#1890ff', '#13c2c2', '#52c41a', '#faad14', '#722ed1', '#eb2f96', '#fa541c', '#2f54eb']
const LEVEL_ORDER: Record<string, number> = { critical: 0, warning: 1, info: 2 }
const CATEGORY_LABEL: Record<string, string> = {
  overload: '过载', delay: '延期', bottleneck: '瓶颈', idle: '闲置', imbalance: '分化',
}

const pct = (v: number, digits = 1) => `${(v * 100).toFixed(digits)}%`

/** 负荷率 → 热力色（绿 → 黄 → 橙 → 红，1.3 封顶） */
const heatCell = (rate: number, isWorkday: boolean): { background: string; color: string } => {
  if (!isWorkday) return { background: '#f0f0f0', color: '#c0c0c0' }
  if (rate <= 0.001) return { background: '#ffffff', color: '#c8c8c8' }
  const t = Math.min(rate, 1.3) / 1.3
  const hue = 120 - t * 120
  const light = 90 - t * 38
  return { background: `hsl(${hue}, 72%, ${light}%)`, color: light < 62 ? '#fff' : '#333' }
}

/** 订单负荷占比 → 矩阵底色 */
const shareBg = (v: number): string =>
  v <= 0.01 ? '#fff' : `rgba(24,144,255,${Math.min(0.85, 0.08 + (v / 100) * 0.85)})`

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div>
    <div style={{ fontSize: 11, color: '#8c8c8c', marginBottom: 2 }}>{label}</div>
    {children}
  </div>
)

/* ==================== KPI 指标条 ==================== */

export const KpiStrip: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const k = result.kpis
  const items: { title: string; value: string; suffix?: string; color: string; tip?: string }[] = [
    { title: '平均负荷率', value: pct(k.avg_load_rate), color: k.avg_load_rate > 0.9 ? '#fa8c16' : '#1890ff' },
    { title: '峰值负荷率', value: pct(k.peak_load_rate, 0), color: k.peak_load_rate > 1 ? '#f5222d' : '#52c41a' },
    { title: '订单准时率', value: pct(k.on_time_rate, 0), color: k.on_time_rate >= 0.8 ? '#52c41a' : '#f5222d' },
    { title: '延期订单', value: `${k.delayed_orders}`, suffix: `/ ${result.order_count}`, color: k.delayed_orders > 0 ? '#f5222d' : '#52c41a' },
    { title: '瓶颈工段', value: `${k.bottleneck_sections}`, color: k.bottleneck_sections > 0 ? '#f5222d' : '#52c41a' },
    {
      title: '负荷不均衡指数', value: k.imbalance_index.toFixed(2),
      color: k.imbalance_index > 0.4 ? '#fa8c16' : '#52c41a',
      tip: '各工段平均负荷率的极差。越大说明订单结构对不同部门的负荷拉动分化越明显',
    },
    { title: '加班工时', value: k.overtime_hours.toFixed(0), suffix: 'h', color: '#722ed1' },
    { title: 'WIP 峰值', value: `${k.wip_peak}`, suffix: '件', color: '#13c2c2' },
    { title: '成品产出', value: `${k.total_output.toLocaleString()}`, suffix: '件', color: '#52c41a', tip: '计划期成品产出总量（末道工序完工）' },
    { title: '综合良品率', value: pct(k.avg_yield_rate), color: k.avg_yield_rate >= 0.97 ? '#52c41a' : '#fa8c16', tip: `良品 ${k.good_output.toLocaleString()} / 报废 ${k.scrap_output.toLocaleString()}` },
    { title: '在岗人数', value: `${k.headcount}`, suffix: '人', color: '#2f54eb', tip: '全厂在岗总人数（单班人数×班次）' },
    { title: 'PO 完工/延期', value: `${k.po_completed}/${k.po_delayed}`, color: k.po_delayed > 0 ? '#f5222d' : '#52c41a', tip: '准时完工 PO 数 / 延期 PO 数' },
    { title: '卡点工段', value: `${k.blocking_point_count}`, color: k.blocking_point_count > 0 ? '#f5222d' : '#52c41a', tip: '出现过载的卡点工段数（物流停滞处）' },
    { title: '峰值积压', value: `${k.max_section_wip.toLocaleString()}`, suffix: '件', color: '#fa8c16', tip: '单工段单日在制积压峰值（物料堆在哪）' },
    { title: '出库总量', value: `${k.total_outbound.toLocaleString()}`, suffix: '件', color: '#52c41a', tip: `计划期成品出库总量；待出库 ${k.pending_outbound} 单` },
  ]
  return (
    <Row gutter={[12, 12]}>
      {items.map((it) => (
        <Col span={6} xl={3} key={it.title}>
          <Card size="small" styles={{ body: { padding: '10px 14px' } }}>
            <Tooltip title={it.tip}>
              <div style={{ fontSize: 11, color: '#8c8c8c' }}>{it.title}</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: it.color, lineHeight: 1.3 }}>
                {it.value}
                {it.suffix && <span style={{ fontSize: 12, fontWeight: 400, marginLeft: 2 }}>{it.suffix}</span>}
              </div>
            </Tooltip>
          </Card>
        </Col>
      ))}
    </Row>
  )
}

/* ==================== 工段 × 日 负荷热力图 ==================== */

export const LoadHeatmap: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const horizon = result.horizon_days
  const showNum = horizon <= 16
  const groups = useMemo(() => {
    const m = new Map<string, FactorySimResult['sections']>()
    result.sections.forEach((s) => {
      const arr = m.get(s.workshop_name) || []
      arr.push(s)
      m.set(s.workshop_name, arr)
    })
    return Array.from(m.entries())
  }, [result])

  return (
    <Card
      size="small"
      title={<Space size={6}><ApartmentOutlined />工段 × 日 负荷热力图</Space>}
      extra={
        <Space size={4} style={{ fontSize: 11 }}>
          <span>低</span>
          <div style={{ width: 110, height: 10, borderRadius: 5, background: 'linear-gradient(90deg, hsl(120,72%,88%), hsl(60,72%,72%), hsl(25,72%,58%), hsl(0,72%,52%))' }} />
          <span>130%+</span>
          <Divider type="vertical" />
          <div style={{ width: 14, height: 10, background: '#f0f0f0', borderRadius: 2 }} />
          <span>休息日</span>
        </Space>
      }
      styles={{ body: { padding: 12, overflowX: 'auto' } }}
    >
      <div style={{ display: 'grid', gridTemplateColumns: `170px repeat(${horizon}, minmax(16px, 1fr))`, gap: 2, minWidth: 170 + horizon * 18 }}>
        <div />
        {Array.from({ length: horizon }, (_, d) => (
          <div key={d} style={{ textAlign: 'center', fontSize: 10, lineHeight: 1.2, paddingBottom: 2 }}>
            <div style={{ color: d % 7 === 6 ? '#d9b8b8' : '#b0b0b0' }}>{DOW[d % 7]}</div>
            <div style={{ fontWeight: 600, color: d % 7 === 6 ? '#c9a0a0' : '#595959' }}>{d + 1}</div>
          </div>
        ))}
        {groups.map(([wsName, secs]) => (
          <React.Fragment key={wsName}>
            <div style={{ gridColumn: '1 / -1', background: '#f7f9fc', fontSize: 11, fontWeight: 600, padding: '3px 8px', borderRadius: 3, color: '#595959' }}>
              <ClusterOutlined style={{ marginRight: 4 }} />{wsName} · {secs.length} 个工段
            </div>
            {secs.map((s) => (
              <React.Fragment key={s.section_id}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, paddingRight: 8, whiteSpace: 'nowrap' }}>
                  <Tag color={s.strategy === 'mts' ? 'cyan' : 'blue'} style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                    {s.strategy.toUpperCase()}
                  </Tag>
                  <span style={{ fontWeight: 600 }}>{s.name}</span>
                  {s.is_bottleneck && (
                    <Tag color="red" style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>瓶颈</Tag>
                  )}
                </div>
                {s.series.map((cell) => {
                  const st = heatCell(cell.load_rate, cell.is_workday)
                  return (
                    <Tooltip
                      key={cell.day}
                      title={`第${cell.day + 1}天(周${DOW[cell.day % 7]}) · 负荷 ${cell.load_hours}h / 产能 ${cell.capacity_hours}h · ${pct(cell.load_rate, 0)}`}
                    >
                      <div style={{
                        background: st.background, color: st.color, height: 26, lineHeight: '26px',
                        textAlign: 'center', fontSize: 10, borderRadius: 2, border: '1px solid rgba(255,255,255,0.6)',
                      }}>
                        {showNum && cell.is_workday && cell.load_hours > 0 ? Math.round(cell.load_hours) : ''}
                      </div>
                    </Tooltip>
                  )
                })}
              </React.Fragment>
            ))}
          </React.Fragment>
        ))}
      </div>
    </Card>
  )
}

/* ==================== 订单排程甘特图 ==================== */

export const OrderGantt: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const horizon = result.horizon_days
  const axisStep = horizon > 31 ? 5 : 1
  const colorOf = useMemo(() => {
    const m = new Map<string, string>()
    result.sections.forEach((s, i) => m.set(s.section_id, SECTION_PALETTE[i % SECTION_PALETTE.length]))
    return m
  }, [result])

  return (
    <Card size="small" title={<Space size={6}><FieldTimeOutlined />订单排程甘特图</Space>} styles={{ body: { padding: 12 } }}>
      <div style={{ display: 'grid', gridTemplateColumns: '210px 1fr', gap: 8 }}>
        <div />
        <div style={{ position: 'relative', height: 16 }}>
          {Array.from({ length: horizon }, (_, d) =>
            d % axisStep === 0 ? (
              <div key={d} style={{ position: 'absolute', left: `${((d + 0.5) / horizon) * 100}%`, fontSize: 10, color: d % 7 === 6 ? '#c9a0a0' : '#8c8c8c', transform: 'translateX(-50%)' }}>
                {d + 1}
              </div>
            ) : null,
          )}
        </div>
        {result.orders.map((o) => (
          <React.Fragment key={o.order_id}>
            <div style={{ fontSize: 12, lineHeight: '26px', whiteSpace: 'nowrap', overflow: 'hidden' }}>
              <Space size={4}>
                <Text strong style={{ color: o.delay_days > 0 ? '#f5222d' : '#262626', fontSize: 12 }}>{o.order_id}</Text>
                <Tag color={PRIORITY_COLOR[o.priority]} style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                  {PRIORITY_LABEL[o.priority]}
                </Tag>
                <Text type="secondary" style={{ fontSize: 11 }}>×{o.quantity}</Text>
                <Text style={{ fontSize: 11, color: o.on_time ? '#52c41a' : '#f5222d' }}>
                  完D{o.completion_day + 1}{o.delay_days > 0 ? ` +${o.delay_days}d` : ''}
                </Text>
              </Space>
            </div>
            <div style={{ position: 'relative', height: 26, background: '#fafafa', borderRadius: 3 }}>
              {/* 交期标记 */}
              <Tooltip title={`交期 D${o.due_day + 1}`}>
                <div style={{ position: 'absolute', left: `${((o.due_day + 1) / horizon) * 100}%`, top: 0, bottom: 0, borderLeft: '1px dashed #f5222d', zIndex: 2 }} />
              </Tooltip>
              {o.ops.map((op) => {
                const s = Math.min(op.start_day, horizon - 1)
                const e = Math.min(op.end_day, horizon - 1)
                const overflow = op.end_day >= horizon
                return (
                  <Tooltip key={op.op_no} title={`${op.name}(${op.section_name}) · D${op.start_day + 1}→D${op.end_day + 1} · ${op.work_hours}h`}>
                    <div style={{
                      position: 'absolute',
                      left: `${(s / horizon) * 100}%`,
                      width: `${((e - s + 1) / horizon) * 100}%`,
                      top: 4, height: 18,
                      background: colorOf.get(op.section_id) || '#1890ff',
                      opacity: 0.88, borderRadius: 2,
                      color: '#fff', fontSize: 10, lineHeight: '18px', textAlign: 'center',
                      overflow: 'hidden', whiteSpace: 'nowrap',
                      border: overflow ? '1px solid #f5222d' : undefined,
                      cursor: 'default',
                    }}>
                      {op.name}{overflow ? '→' : ''}
                    </div>
                  </Tooltip>
                )
              })}
            </div>
          </React.Fragment>
        ))}
      </div>
      <Divider style={{ margin: '10px 0 6px' }} />
      <Space size={[12, 4]} wrap style={{ fontSize: 11 }}>
        {result.sections.map((s, i) => (
          <span key={s.section_id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: SECTION_PALETTE[i % SECTION_PALETTE.length], display: 'inline-block' }} />
            {s.name}
            <Text type="secondary" style={{ fontSize: 11 }}>({STRATEGY_LABEL[s.strategy]})</Text>
          </span>
        ))}
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 0, height: 12, borderLeft: '1px dashed #f5222d', display: 'inline-block' }} />
          交期
        </span>
      </Space>
    </Card>
  )
}

/* ==================== 订单 × 工段 负荷贡献矩阵 ==================== */

export const LoadMatrix: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const idx = useMemo(() => {
    const m = new Map<string, OrderSectionLoad>()
    result.order_section_loads.forEach((l) => m.set(`${l.order_id}|${l.section_id}`, l))
    return m
  }, [result])

  const columns: any[] = [
    {
      title: '订单', key: 'order', width: 190, fixed: 'left' as const,
      render: (_: unknown, o: OrderResult) => (
        <Space direction="vertical" size={0}>
          <Space size={4}>
            <Text strong style={{ fontSize: 12 }}>{o.order_id}</Text>
            <Tag color={PRIORITY_COLOR[o.priority]} style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
              {PRIORITY_LABEL[o.priority]}
            </Tag>
          </Space>
          <Text type="secondary" style={{ fontSize: 11 }}>{o.product_name} ×{o.quantity} · 交D{o.due_day + 1}</Text>
        </Space>
      ),
    },
    ...result.sections.map((s) => ({
      title: <span style={{ fontSize: 12 }}>{s.name}</span>,
      key: s.section_id, align: 'center' as const, width: 96,
      render: (_: unknown, o: OrderResult) => {
        const l = idx.get(`${o.order_id}|${s.section_id}`)
        if (!l) return <span style={{ color: '#d9d9d9' }}>—</span>
        return (
          <div style={{ background: shareBg(l.share_pct), color: l.share_pct > 55 ? '#fff' : '#333', borderRadius: 3, padding: '2px 0', fontSize: 11 }}>
            <div style={{ fontWeight: 700 }}>{l.share_pct}%</div>
            <div style={{ opacity: 0.75 }}>{l.work_hours}h</div>
          </div>
        )
      },
    })),
  ]

  return (
    <Table
      dataSource={result.orders}
      columns={columns}
      rowKey="order_id"
      pagination={false}
      size="small"
      scroll={{ x: 'max-content' }}
    />
  )
}

/* ==================== WIP 曲线 ==================== */

export const WipCurve: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const { wip_curve, horizon_days, kpis } = result
  const max = Math.max(1, ...wip_curve.map((p) => p.wip_qty))
  const n = Math.max(1, horizon_days - 1)
  const pts = wip_curve.map((p) => `${(p.day / n) * 100},${95 - (p.wip_qty / max) * 85}`).join(' ')
  return (
    <div>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: '100%', height: 110, display: 'block' }}>
        <polygon points={`0,100 ${pts} 100,100`} fill="rgba(24,144,255,0.12)" />
        <polyline points={pts} fill="none" stroke="#1890ff" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#8c8c8c' }}>
        <span>D1</span>
        <span>峰值 {kpis.wip_peak} 件</span>
        <span>D{horizon_days}</span>
      </div>
    </div>
  )
}

/* ==================== 告警中心 ==================== */

export const AlertPanel: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const alerts = [...result.alerts].sort((a, b) => (LEVEL_ORDER[a.level] ?? 9) - (LEVEL_ORDER[b.level] ?? 9))
  if (!alerts.length) return <AntAlert type="success" showIcon message="本次仿真未触发任何告警" />
  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      {alerts.map((a, i) => (
        <AntAlert
          key={i}
          type={a.level === 'critical' ? 'error' : a.level === 'warning' ? 'warning' : 'info'}
          showIcon
          message={
            <Space size={6} wrap>
              <span style={{ fontWeight: 600, fontSize: 12 }}>{a.title}</span>
              <Tag style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                {CATEGORY_LABEL[a.category] || a.category}
              </Tag>
              {a.day != null && (
                <Tag style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>D{a.day + 1}</Tag>
              )}
            </Space>
          }
          description={<span style={{ fontSize: 12 }}>{a.detail}</span>}
        />
      ))}
    </Space>
  )
}

/* ==================== 工段参数编辑器 ==================== */

const SectionEditor: React.FC<{ section: SectionConfig; onPatch: (p: Partial<SectionConfig>) => void }> = ({ section: s, onPatch }) => (
  <div style={{ border: '1px solid #f0f0f0', borderRadius: 4, padding: '8px 10px', height: '100%', background: '#fff' }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <Space size={6}>
        <Text strong style={{ fontSize: 13 }}>{s.name}</Text>
        <Text type="secondary" style={{ fontSize: 10 }}>{s.section_id}</Text>
      </Space>
      <Segmented
        size="small"
        value={s.strategy}
        onChange={(v) => onPatch({ strategy: v as ProductionStrategy })}
        options={[
          { label: 'MTS 备料', value: 'mts' },
          { label: 'MTO 订单', value: 'mto' },
        ]}
      />
    </div>
    <Row gutter={[8, 4]} style={{ marginTop: 6 }}>
      <Col span={6}>
        <Field label="人数">
          <InputNumber size="small" min={1} max={500} value={s.workers} onChange={(v) => onPatch({ workers: v || 1 })} style={{ width: '100%' }} />
        </Field>
      </Col>
      <Col span={6}>
        <Field label="设备">
          <InputNumber size="small" min={0} max={200} value={s.machines} onChange={(v) => onPatch({ machines: v || 0 })} style={{ width: '100%' }} />
        </Field>
      </Col>
      <Col span={6}>
        <Field label="班次/日">
          <Select size="small" value={s.shifts_per_day} onChange={(v) => onPatch({ shifts_per_day: v })}
            options={[1, 2, 3].map((x) => ({ label: `${x}`, value: x }))} style={{ width: '100%' }} />
        </Field>
      </Col>
      <Col span={6}>
        <Field label="时/班">
          <Select size="small" value={s.hours_per_shift} onChange={(v) => onPatch({ hours_per_shift: v })}
            options={[6, 8, 10, 12].map((h) => ({ label: `${h}h`, value: h }))} style={{ width: '100%' }} />
        </Field>
      </Col>
    </Row>
    <Row gutter={[8, 0]} style={{ marginTop: 4 }}>
      <Col span={12}>
        <Field label={`综合效率 ${pct(s.efficiency, 0)}`}>
          <Slider min={0.3} max={1} step={0.05} value={s.efficiency} onChange={(v) => onPatch({ efficiency: v })} />
        </Field>
      </Col>
      <Col span={12}>
        <Field label={`加班上限 ${pct(s.max_overtime_pct, 0)}`}>
          <Slider min={0} max={1} step={0.1} value={s.max_overtime_pct} onChange={(v) => onPatch({ max_overtime_pct: v })} />
        </Field>
      </Col>
    </Row>
    {s.description && <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 2 }}>{s.description}</div>}
  </div>
)

/* ==================== 产出分析 ==================== */

export const OutputAnalysis: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const { daily_output, section_outputs, horizon_days, kpis } = result
  const maxDaily = Math.max(1, ...daily_output.map((p) => p.output_qty))
  const maxCum = Math.max(1, ...daily_output.map((p) => p.cumulative))
  const n = Math.max(1, horizon_days - 1)
  const barW = 100 / horizon_days
  const cumPts = daily_output.map((p) => `${(p.day / n) * 100},${95 - (p.cumulative / maxCum) * 85}`).join(' ')
  const soColumns: any[] = [
    { title: '工段', dataIndex: 'name', key: 'name' },
    { title: '计划量', dataIndex: 'planned_qty', key: 'planned_qty', align: 'right' as const, render: (v: number) => v.toLocaleString() },
    { title: '良品', dataIndex: 'good_qty', key: 'good_qty', align: 'right' as const, render: (v: number) => <span style={{ color: '#52c41a' }}>{v.toLocaleString()}</span> },
    { title: '报废', dataIndex: 'scrap_qty', key: 'scrap_qty', align: 'right' as const, render: (v: number) => <span style={{ color: '#f5222d' }}>{v.toLocaleString()}</span> },
    { title: '良品率', dataIndex: 'yield_rate', key: 'yield_rate', width: 200, render: (v: number) => <Progress percent={Number((v * 100).toFixed(1))} size="small" status={v < 0.95 ? 'exception' : 'normal'} /> },
  ]
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small" title={<Space size={6}><RiseOutlined />日成品产出曲线</Space>}
        extra={
          <Space size={12} style={{ fontSize: 11 }}>
            <span><span style={{ display: 'inline-block', width: 10, height: 10, background: 'rgba(82,196,26,0.55)', borderRadius: 2 }} /> 日产出</span>
            <span><span style={{ display: 'inline-block', width: 14, height: 0, borderTop: '2px solid #1890ff' }} /> 累计</span>
          </Space>
        }>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: '100%', height: 150, display: 'block' }}>
          {daily_output.map((p) => {
            const h = (p.output_qty / maxDaily) * 80
            return <rect key={p.day} x={p.day * barW + barW * 0.15} y={95 - h} width={barW * 0.7} height={h} fill="rgba(82,196,26,0.55)" />
          })}
          <polyline points={cumPts} fill="none" stroke="#1890ff" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
        </svg>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#8c8c8c' }}>
          <span>D1</span><span>累计成品 {kpis.total_output.toLocaleString()} 件</span><span>D{horizon_days}</span>
        </div>
      </Card>
      <Card size="small" title="工段产出明细" styles={{ body: { padding: 0 } }}>
        <Table dataSource={section_outputs} columns={soColumns} rowKey="section_id" pagination={false} size="small" />
      </Card>
    </Space>
  )
}

/* ==================== 工人花名册 ==================== */

export const WorkforcePanel: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const [secFilter, setSecFilter] = useState<string>('all')
  const allWorkers = useMemo(() => result.workforce.flatMap((w) => w.workers), [result])
  const workers = secFilter === 'all' ? allWorkers : allWorkers.filter((w) => w.section_id === secFilter)
  const wColumns: any[] = [
    { title: '工号', dataIndex: 'worker_id', key: 'worker_id', width: 150 },
    { title: '姓名', dataIndex: 'name', key: 'name', width: 90, render: (v: string) => <Text strong>{v}</Text> },
    { title: '工段', dataIndex: 'section_name', key: 'section_name' },
    { title: '工种', dataIndex: 'role', key: 'role', render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '技能', dataIndex: 'skill_level', key: 'skill_level', width: 150, render: (v: number) => <Rate disabled value={v} style={{ fontSize: 12 }} /> },
    { title: '班次', dataIndex: 'shift', key: 'shift', width: 70, align: 'center' as const, render: (v: number) => <Tag>{v} 班</Tag> },
    { title: '出勤率', dataIndex: 'attendance_rate', key: 'attendance_rate', width: 90, align: 'right' as const, render: (v: number) => pct(v) },
  ]
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Row gutter={[12, 12]}>
        {result.workforce.map((w) => (
          <Col span={8} xl={6} key={w.section_id}>
            <Card size="small" styles={{ body: { padding: '10px 12px' } }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text strong style={{ fontSize: 13 }}>{w.name}</Text>
                <Tag color="geekblue" style={{ margin: 0 }}>{w.headcount} 人</Tag>
              </div>
              <div style={{ fontSize: 11, color: '#8c8c8c', margin: '4px 0' }}>{w.per_shift} 人/班 × {Object.keys(w.shift_headcount).length} 班</div>
              <div style={{ display: 'flex', gap: 12, fontSize: 11, marginBottom: 4 }}>
                <span>平均技能 <b style={{ color: '#fa8c16' }}>{w.avg_skill}</b></span>
                <span>出勤 <b style={{ color: '#52c41a' }}>{pct(w.avg_attendance, 0)}</b></span>
              </div>
              <div style={{ fontSize: 11, color: '#8c8c8c' }}>人力利用率</div>
              <Progress percent={Number((Math.min(w.labor_utilization, 1.5) / 1.5 * 100).toFixed(0))} size="small"
                format={() => pct(w.labor_utilization, 0)} status={w.labor_utilization > 1 ? 'exception' : 'normal'} />
            </Card>
          </Col>
        ))}
      </Row>
      <Card size="small" title={<Space size={6}><TeamOutlined />工人花名册<Tag color="blue">{workers.length} 人</Tag></Space>}
        extra={<Select size="small" value={secFilter} onChange={setSecFilter} style={{ width: 160 }}
          options={[{ value: 'all', label: '全部工段' }, ...result.workforce.map((w) => ({ value: w.section_id, label: w.name }))]} />}
        styles={{ body: { padding: 0 } }}>
        <Table dataSource={workers} columns={wColumns} rowKey="worker_id" size="small"
          pagination={{ pageSize: 10, showSizeChanger: false, size: 'small' }} />
      </Card>
    </Space>
  )
}

/* ==================== PO 工单 ==================== */

const PO_STATUS: Record<string, { color: string; label: string }> = {
  released: { color: 'default', label: '已下达' },
  in_progress: { color: 'processing', label: '生产中' },
  completed: { color: 'success', label: '已完工' },
  delayed: { color: 'error', label: '延期' },
}

export const PoPanel: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const pos = result.production_orders
  const releases = useMemo(() => {
    const m = new Map<number, ProductionOrderResult[]>()
    pos.forEach((po) => { const arr = m.get(po.release_day) || []; arr.push(po); m.set(po.release_day, arr) })
    return Array.from(m.entries()).sort((a, b) => a[0] - b[0])
  }, [pos])
  const poColumns: any[] = [
    { title: 'PO 号', dataIndex: 'po_id', key: 'po_id', width: 130, render: (v: string) => <Text code style={{ fontSize: 11 }}>{v}</Text> },
    { title: '产品', dataIndex: 'product_name', key: 'product_name' },
    { title: '数量', dataIndex: 'quantity', key: 'quantity', align: 'right' as const, render: (v: number) => v.toLocaleString() },
    { title: '下达', dataIndex: 'release_day', key: 'release_day', align: 'center' as const, width: 60, render: (v: number) => `D${v + 1}` },
    { title: '开工', dataIndex: 'start_day', key: 'start_day', align: 'center' as const, width: 60, render: (v: number) => `D${v + 1}` },
    { title: '完工', dataIndex: 'completion_day', key: 'completion_day', align: 'center' as const, width: 60, render: (v: number, r: ProductionOrderResult) => <span style={{ color: r.on_time ? '#52c41a' : '#f5222d' }}>D{v + 1}</span> },
    { title: '交期', dataIndex: 'due_day', key: 'due_day', align: 'center' as const, width: 60, render: (v: number) => `D${v + 1}` },
    { title: '良品/报废', key: 'yield', align: 'right' as const, width: 120, render: (_: unknown, r: ProductionOrderResult) => <span><span style={{ color: '#52c41a' }}>{r.good_qty.toLocaleString()}</span> / <span style={{ color: '#f5222d' }}>{r.scrap_qty.toLocaleString()}</span></span> },
    { title: '当前工段', dataIndex: 'current_section', key: 'current_section' },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (v: string) => <Tag color={PO_STATUS[v]?.color}>{PO_STATUS[v]?.label || v}</Tag> },
  ]
  const opColumns: any[] = [
    { title: '工序', dataIndex: 'op_no', key: 'op_no', width: 60 },
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '工段', dataIndex: 'section_name', key: 'section_name' },
    { title: '开工→完工', key: 'span', width: 120, render: (_: unknown, r: any) => `D${r.start_day + 1} → D${r.end_day + 1}` },
    { title: '数量', dataIndex: 'qty', key: 'qty', align: 'right' as const, render: (v: number) => v.toLocaleString() },
    { title: '良品/报废', key: 'g', align: 'right' as const, render: (_: unknown, r: any) => <span><span style={{ color: '#52c41a' }}>{r.good_qty}</span> / <span style={{ color: '#f5222d' }}>{r.scrap_qty}</span></span> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 80, render: (v: string) => <Tag color={v === 'delayed' ? 'error' : 'success'}>{v === 'delayed' ? '延期' : '完成'}</Tag> },
  ]
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small" title={<Space size={6}><ProfileOutlined />PO 下达时间线</Space>}>
        <Space size={[8, 8]} wrap>
          {releases.map(([day, list]) => (
            <Tooltip key={day} title={<span>{list.map((p) => `${p.po_id} · ${p.product_name} ×${p.quantity}`).join('；')}</span>}>
              <Tag color="processing" style={{ fontSize: 12, padding: '2px 8px' }}>D{day + 1} 下达 {list.length} 张</Tag>
            </Tooltip>
          ))}
        </Space>
      </Card>
      <Card size="small" title="生产工单（PO）列表" styles={{ body: { padding: 0 } }}>
        <Table dataSource={pos} columns={poColumns} rowKey="po_id" size="small" pagination={false} scroll={{ x: 'max-content' }}
          expandable={{ expandedRowRender: (po: ProductionOrderResult) => <Table dataSource={po.ops} columns={opColumns} rowKey="op_no" size="small" pagination={false} /> }} />
      </Card>
    </Space>
  )
}

/* ==================== 流转记录 ==================== */

export const TransferPanel: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const lanes = useMemo(() => {
    const m = new Map<string, { from: string; to: string; qty: number; count: number }>()
    result.transfers.forEach((t) => {
      const key = `${t.from_section_id}->${t.to_section_id}`
      const cur = m.get(key) || { from: t.from_section_name, to: t.to_section_name, qty: 0, count: 0 }
      cur.qty += t.qty; cur.count += 1; m.set(key, cur)
    })
    return Array.from(m.values())
  }, [result])
  const maxLane = Math.max(1, ...lanes.map((l) => l.qty))
  const tColumns: any[] = [
    { title: '流转单号', dataIndex: 'transfer_id', key: 'transfer_id', width: 160, render: (v: string) => <Text code style={{ fontSize: 11 }}>{v}</Text> },
    { title: '订单', dataIndex: 'order_id', key: 'order_id', width: 100 },
    { title: '产品', dataIndex: 'product_name', key: 'product_name' },
    { title: '流向', key: 'flow', render: (_: unknown, t: any) => <Space size={4}><Tag color="cyan" style={{ margin: 0 }}>{t.from_section_name}</Tag>→<Tag color="blue" style={{ margin: 0 }}>{t.to_section_name}</Tag></Space> },
    { title: '数量', dataIndex: 'qty', key: 'qty', align: 'right' as const, render: (v: number) => v.toLocaleString() },
    { title: '离开', dataIndex: 'depart_day', key: 'depart_day', align: 'center' as const, width: 60, render: (v: number) => `D${v + 1}` },
    { title: '到达', dataIndex: 'arrive_day', key: 'arrive_day', align: 'center' as const, width: 60, render: (v: number) => `D${v + 1}` },
    { title: '在途', key: 'transit', align: 'center' as const, width: 70, render: (_: unknown, t: any) => `${Math.max(0, t.arrive_day - t.depart_day)}d` },
  ]
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small" title={<Space size={6}><SwapOutlined />工段流转通道</Space>}>
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          {lanes.map((l, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
              <span style={{ width: 210, whiteSpace: 'nowrap' }}>{l.from} → {l.to}</span>
              <Progress percent={Number((l.qty / maxLane * 100).toFixed(0))} size="small" showInfo={false} style={{ flex: 1, margin: 0 }} />
              <span style={{ width: 140, textAlign: 'right', whiteSpace: 'nowrap' }}>{l.qty.toLocaleString()} 件 / {l.count} 批</span>
            </div>
          ))}
        </Space>
      </Card>
      <Card size="small" title="流转记录明细" styles={{ body: { padding: 0 } }}>
        <Table dataSource={result.transfers} columns={tColumns} rowKey="transfer_id" size="small"
          pagination={{ pageSize: 10, showSizeChanger: false, size: 'small' }} scroll={{ x: 'max-content' }} />
      </Card>
    </Space>
  )
}

/* ==================== 全流程追踪（下达 → 工段流转 → 出库） ==================== */

export const ProcessTracePanel: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const horizon = result.horizon_days
  const colorOf = useMemo(() => {
    const m = new Map<string, string>()
    result.sections.forEach((s, i) => m.set(s.section_id, SECTION_PALETTE[i % SECTION_PALETTE.length]))
    return m
  }, [result])
  const outboundByOrder = useMemo(() => {
    const m = new Map<string, OutboundOrder>()
    result.outbound_orders.forEach((o) => m.set(o.order_id, o))
    return m
  }, [result])

  const obColumns: any[] = [
    { title: '出库单号', dataIndex: 'outbound_id', key: 'outbound_id', width: 110, render: (v: string) => <Text code style={{ fontSize: 11 }}>{v}</Text> },
    { title: '订单', dataIndex: 'order_id', key: 'order_id', width: 100 },
    { title: 'PO 号', dataIndex: 'po_id', key: 'po_id', width: 130 },
    { title: '产品', dataIndex: 'product_name', key: 'product_name' },
    { title: '数量', dataIndex: 'quantity', key: 'quantity', align: 'right' as const, render: (v: number) => v.toLocaleString() },
    { title: '良品', dataIndex: 'good_qty', key: 'good_qty', align: 'right' as const, render: (v: number) => <span style={{ color: '#52c41a' }}>{v.toLocaleString()}</span> },
    { title: '出库日', dataIndex: 'outbound_day', key: 'outbound_day', align: 'center' as const, width: 70, render: (v: number) => `D${v + 1}` },
    { title: '仓库', dataIndex: 'warehouse', key: 'warehouse', width: 90 },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (v: string) => (v === 'shipped' ? <Tag color="success">已出库</Tag> : <Tag color="warning">待出库</Tag>) },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card
        size="small"
        title={<Space size={6}><NodeIndexOutlined />订单全流程追踪（下达 → 工段流转 → 出库）</Space>}
        extra={
          <Space size={12} style={{ fontSize: 11 }}>
            <span><span style={{ display: 'inline-block', width: 10, height: 10, background: 'repeating-linear-gradient(45deg,#ff7875,#ff7875 2px,#ffd8d8 2px,#ffd8d8 4px)', borderRadius: 2 }} /> 等待卡点</span>
            <span><span style={{ display: 'inline-block', width: 10, height: 10, background: '#1890ff', borderRadius: 2 }} /> 工序生产</span>
            <span><span style={{ display: 'inline-block', width: 0, height: 12, borderLeft: '2px solid #52c41a' }} /> 出库</span>
          </Space>
        }
        styles={{ body: { padding: 12 } }}
      >
        {result.production_orders.map((po) => {
          const ob = outboundByOrder.get(po.order_id)
          return (
            <div key={po.po_id} style={{ marginBottom: 12 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '210px 1fr', gap: 8 }}>
                <div style={{ fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden' }}>
                  <Space size={4}>
                    <Text strong style={{ color: po.on_time ? '#262626' : '#f5222d', fontSize: 12 }}>{po.order_id}</Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>×{po.quantity}</Text>
                    <Tag color={po.on_time ? 'success' : 'error'} style={{ margin: 0, fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                      {po.on_time ? '准时' : '延期'}
                    </Tag>
                  </Space>
                  <div style={{ fontSize: 11, color: '#8c8c8c' }}>{po.product_name} · 下达D{po.release_day + 1}</div>
                </div>
                <div style={{ position: 'relative', height: 30, background: '#fafafa', borderRadius: 3 }}>
                  {po.ops.map((op) => {
                    const waitStart = Math.max(0, op.start_day - op.wait_days)
                    const s = Math.min(op.start_day, horizon - 1)
                    const e = Math.min(op.end_day, horizon - 1)
                    return (
                      <React.Fragment key={op.op_no}>
                        {op.wait_days > 0 && (
                          <Tooltip title={`等待卡点：${op.section_name} 开工前等待 ${op.wait_days} 天`}>
                            <div style={{
                              position: 'absolute',
                              left: `${(waitStart / horizon) * 100}%`,
                              width: `${(Math.max(1, op.start_day - waitStart) / horizon) * 100}%`,
                              top: 4, height: 22, borderRadius: 2,
                              background: 'repeating-linear-gradient(45deg,#ff7875,#ff7875 3px,#ffd8d8 3px,#ffd8d8 6px)',
                              border: '1px solid #ff7875',
                            }} />
                          </Tooltip>
                        )}
                        <Tooltip title={`${op.name}(${op.section_name}) · D${op.start_day + 1}→D${op.end_day + 1}${op.wait_days > 0 ? ` · 等待${op.wait_days}d` : ''}`}>
                          <div style={{
                            position: 'absolute',
                            left: `${(s / horizon) * 100}%`,
                            width: `${((e - s + 1) / horizon) * 100}%`,
                            top: 6, height: 18,
                            background: colorOf.get(op.section_id) || '#1890ff',
                            opacity: 0.9, borderRadius: 2,
                            color: '#fff', fontSize: 10, lineHeight: '18px', textAlign: 'center',
                            overflow: 'hidden', whiteSpace: 'nowrap',
                          }}>
                            {op.section_name}
                          </div>
                        </Tooltip>
                      </React.Fragment>
                    )
                  })}
                  {ob && (
                    <Tooltip title={`${ob.outbound_id} · ${ob.status === 'shipped' ? '已出库' : '待出库'} · D${ob.outbound_day + 1} · 良品${ob.good_qty}`}>
                      <div style={{
                        position: 'absolute',
                        left: `${(Math.min(ob.outbound_day, horizon - 1) / horizon) * 100}%`,
                        top: 0, bottom: 0,
                        borderLeft: `2px solid ${ob.status === 'shipped' ? '#52c41a' : '#faad14'}`,
                        zIndex: 2,
                      }}>
                        <ExportOutlined style={{ fontSize: 10, color: ob.status === 'shipped' ? '#52c41a' : '#faad14', position: 'relative', top: -2, left: -5 }} />
                      </div>
                    </Tooltip>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </Card>
      <Card size="small" title={<Space size={6}><ExportOutlined />货物出库单<Tag color="green">{result.outbound_orders.filter((o) => o.status === 'shipped').length} 已出库</Tag><Tag color="orange">{result.outbound_orders.filter((o) => o.status === 'pending').length} 待出库</Tag></Space>}
        styles={{ body: { padding: 0 } }}>
        <Table dataSource={result.outbound_orders} columns={obColumns} rowKey="outbound_id" size="small" pagination={false} scroll={{ x: 'max-content' }} />
      </Card>
    </Space>
  )
}

/* ==================== 卡点分析 ==================== */

export const BlockingAnalysisPanel: React.FC<{ result: FactorySimResult }> = ({ result }) => {
  const horizon = result.horizon_days
  const bps = result.blocking_points
  const maxWip = Math.max(1, ...result.sections.flatMap((s) => s.series.map((c) => c.wip_qty)))
  const wipCell = (q: number): { background: string; color: string } => {
    if (q <= 0) return { background: '#ffffff', color: '#d0d0d0' }
    const t = Math.min(1, q / maxWip)
    const hue = 220 - t * 220
    const light = 92 - t * 42
    return { background: `hsl(${hue}, 75%, ${light}%)`, color: light < 58 ? '#fff' : '#333' }
  }
  const sevColor = (v: number) => (v >= 60 ? '#f5222d' : v >= 30 ? '#fa8c16' : '#52c41a')
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small" title={<Space size={6}><AimOutlined />卡点排行榜<Tag color="red">{bps.length} 处</Tag></Space>}
        extra={<Text type="secondary" style={{ fontSize: 11 }}>严重度 = 0.5×过载 + 0.3×积压 + 0.2×等待</Text>}>
        {bps.length === 0 && <AntAlert type="success" showIcon message="未检测到卡点，物流顺畅" />}
        {bps.map((bp) => (
          <div key={bp.section_id} style={{ display: 'flex', gap: 12, alignItems: 'flex-start', padding: '10px 0', borderBottom: '1px dashed #f0f0f0' }}>
            <div style={{
              width: 30, height: 30, borderRadius: '50%', flexShrink: 0,
              background: bp.rank <= 3 ? (bp.rank === 1 ? '#f5222d' : bp.rank === 2 ? '#fa8c16' : '#faad14') : '#f0f0f0',
              color: bp.rank <= 3 ? '#fff' : '#8c8c8c',
              fontWeight: 700, fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              {bp.rank}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Space size={6} wrap>
                <Text strong style={{ fontSize: 13 }}>{bp.section_name}</Text>
                <Text type="secondary" style={{ fontSize: 11 }}>{bp.workshop_name}</Text>
                <Tag color={BLOCKING_TYPE_COLOR[bp.blocking_type]} style={{ margin: 0, fontSize: 10 }}>
                  {BLOCKING_TYPE_LABEL[bp.blocking_type]}
                </Tag>
                {bp.delayed_orders > 0 && <Tag color="red" style={{ margin: 0, fontSize: 10 }}>{bp.delayed_orders} 单延期</Tag>}
              </Space>
              <div style={{ fontSize: 11, color: '#8c8c8c', margin: '3px 0' }}>{bp.detail}</div>
              <Progress percent={Math.min(100, bp.severity)} size="small" strokeColor={sevColor(bp.severity)}
                format={() => `严重度 ${bp.severity}`} />
            </div>
            <div style={{ width: 150, flexShrink: 0, fontSize: 11, color: '#595959', lineHeight: 1.7, textAlign: 'right' }}>
              <div>峰值负荷 <b style={{ color: bp.peak_load_rate > 1 ? '#f5222d' : '#52c41a' }}>{pct(bp.peak_load_rate, 0)}</b>（D{bp.peak_day + 1}）</div>
              <div>过载 <b>{bp.overload_days}</b> 天 · 积压 <b style={{ color: '#fa8c16' }}>{bp.wip_peak.toLocaleString()}</b> 件</div>
              <div>平均等待 <b>{bp.avg_wait_days}</b> 天</div>
            </div>
          </div>
        ))}
      </Card>
      <Card
        size="small"
        title={<Space size={6}><ClusterOutlined />WIP 积压热力图（工段 × 日）</Space>}
        extra={
          <Space size={4} style={{ fontSize: 11 }}>
            <span>无</span>
            <div style={{ width: 110, height: 10, borderRadius: 5, background: 'linear-gradient(90deg, hsl(220,75%,90%), hsl(110,75%,70%), hsl(0,75%,50%))' }} />
            <span>{maxWip.toLocaleString()} 件</span>
          </Space>
        }
        styles={{ body: { padding: 12, overflowX: 'auto' } }}
      >
        <div style={{ display: 'grid', gridTemplateColumns: `170px repeat(${horizon}, minmax(16px, 1fr))`, gap: 2, minWidth: 170 + horizon * 18 }}>
          <div />
          {Array.from({ length: horizon }, (_, d) => (
            <div key={d} style={{ textAlign: 'center', fontSize: 10, fontWeight: 600, color: d % 7 === 6 ? '#c9a0a0' : '#595959', paddingBottom: 2 }}>
              {d + 1}
            </div>
          ))}
          {result.sections.map((s) => (
            <React.Fragment key={s.section_id}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, paddingRight: 8, whiteSpace: 'nowrap' }}>
                <span style={{ fontWeight: 600 }}>{s.name}</span>
              </div>
              {s.series.map((cell) => {
                const st = wipCell(cell.wip_qty)
                return (
                  <Tooltip key={cell.day} title={`第${cell.day + 1}天 · ${s.name} 在制积压 ${cell.wip_qty.toLocaleString()} 件`}>
                    <div style={{
                      background: st.background, color: st.color, height: 24, lineHeight: '24px',
                      textAlign: 'center', fontSize: 9, borderRadius: 2, border: '1px solid rgba(0,0,0,0.04)',
                    }}>
                      {horizon <= 16 && cell.wip_qty > 0 ? cell.wip_qty : ''}
                    </div>
                  </Tooltip>
                )
              })}
            </React.Fragment>
          ))}
        </div>
        <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 8 }}>颜色越深代表在制积压越多——物料堆在哪里，卡点就在哪里。</div>
      </Card>
    </Space>
  )
}

/* ==================== 主面板 ==================== */

const FactoryLoadSim: React.FC = () => {
  const [config, setConfig] = useState<FactorySimConfig | null>(null)
  const [result, setResult] = useState<FactorySimResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [booting, setBooting] = useState(true)
  const [desc, setDesc] = useState('')
  const [hints, setHints] = useState<string[]>([])
  /* 多工厂场景库 */
  const [scenarios, setScenarios] = useState<FactoryScenarioMeta[]>([])
  const [activeId, setActiveId] = useState<string>('')
  const [tags, setTags] = useState<string[]>([])
  /* 三区工作台视图：产线组态 / 参数配置 / 仿真结果 */
  const [view, setView] = useState<'topology' | 'config' | 'results'>('topology')

  /* ---------- 运行仿真（成功返回 true） ---------- */
  const runSim = useCallback(async (cfg: FactorySimConfig): Promise<boolean> => {
    if (!cfg.orders.length) { message.warning('至少保留一张订单'); return false }
    for (const o of cfg.orders) {
      if (o.release_day >= cfg.horizon_days) {
        message.error(`订单 ${o.order_id}：投放日(D${o.release_day + 1})超出计划期(${cfg.horizon_days}天)`)
        return false
      }
      if (o.due_day <= o.release_day) {
        message.error(`订单 ${o.order_id}：交期日必须晚于投放日`)
        return false
      }
    }
    setLoading(true)
    try {
      const res = await runFactorySimulation(cfg)
      setResult(res)
      return true
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '仿真运行失败')
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  const loadScenario = useCallback(async (id?: string) => {
    setBooting(true)
    try {
      const sc = await getFactoryScenario(id)
      setConfig(sc.config)
      setDesc(sc.description)
      setHints(sc.hints)
      setTags(sc.tags || [])
      setActiveId(sc.scenario_id)
      setResult(null)
      await runSim(sc.config)
    } catch {
      message.error('场景加载失败')
    } finally {
      setBooting(false)
    }
  }, [runSim])

  /* 首次进入：拉取工厂场景列表 + 默认工厂 */
  useEffect(() => {
    getFactoryScenarios().then(setScenarios).catch(() => { /* 列表拉取失败不阻塞 */ })
  }, [])
  useEffect(() => { loadScenario() }, [loadScenario])

  /* ---------- 参数修改 ---------- */
  const patch = useCallback((p: Partial<FactorySimConfig>) => setConfig((c) => (c ? { ...c, ...p } : c)), [])
  const patchWorkshop = useCallback((wid: string, p: Partial<WorkshopConfig>) => {
    setConfig((c) => c && { ...c, workshops: c.workshops.map((w) => (w.workshop_id === wid ? { ...w, ...p } : w)) })
  }, [])
  const patchSection = useCallback((sid: string, p: Partial<SectionConfig>) => {
    setConfig((c) => c && { ...c, sections: c.sections.map((s) => (s.section_id === sid ? { ...s, ...p } : s)) })
  }, [])
  const patchOrder = useCallback((oid: string, p: Partial<OrderInput>) => {
    setConfig((c) => c && { ...c, orders: c.orders.map((o) => (o.order_id === oid ? { ...o, ...p } : o)) })
  }, [])
  const removeOrder = useCallback((oid: string) => {
    setConfig((c) => c && { ...c, orders: c.orders.filter((o) => o.order_id !== oid) })
  }, [])
  const addOrder = useCallback(() => {
    setConfig((c) => {
      if (!c) return c
      const ids = new Set(c.orders.map((o) => o.order_id))
      let k = c.orders.length + 1
      let oid = `SO-24${String(k).padStart(2, '0')}`
      while (ids.has(oid)) { k += 1; oid = `SO-24${String(k).padStart(2, '0')}` }
      const product = c.routings[0]?.product_id || ''
      return {
        ...c,
        orders: [...c.orders, {
          order_id: oid, product_id: product, quantity: 500,
          release_day: 0, due_day: Math.max(2, Math.min(c.horizon_days - 1, 10)), priority: 'medium' as Priority,
        }],
      }
    })
  }, [])

  /* ---------- 结构编辑（组态编辑器用） ---------- */
  const addWorkshop = useCallback(() => {
    setConfig((c) => {
      if (!c) return c
      let n = c.workshops.length + 1
      let wid = `WS-${String(n).padStart(2, '0')}`
      while (c.workshops.some((w) => w.workshop_id === wid)) { n += 1; wid = `WS-${String(n).padStart(2, '0')}` }
      let sn = c.sections.length + 1
      let sid = `SEC-${String(sn).padStart(2, '0')}`
      while (c.sections.some((s) => s.section_id === sid)) { sn += 1; sid = `SEC-${String(sn).padStart(2, '0')}` }
      const ws: WorkshopConfig = { workshop_id: wid, name: `新车间 ${n}`, working_days_per_week: 5, description: '' }
      const sec: SectionConfig = {
        section_id: sid, name: `新工段 ${sn}`, workshop_id: wid, strategy: 'mto',
        workers: 10, machines: 2, shifts_per_day: 1, hours_per_shift: 8,
        efficiency: 0.85, max_overtime_pct: 0.2, yield_rate: 0.98, role_name: '操作工', description: '',
      }
      return { ...c, workshops: [...c.workshops, ws], sections: [...c.sections, sec] }
    })
  }, [])

  const addSection = useCallback((workshopId: string) => {
    setConfig((c) => {
      if (!c) return c
      let sn = c.sections.length + 1
      let sid = `SEC-${String(sn).padStart(2, '0')}`
      while (c.sections.some((s) => s.section_id === sid)) { sn += 1; sid = `SEC-${String(sn).padStart(2, '0')}` }
      const sec: SectionConfig = {
        section_id: sid, name: `新工段 ${sn}`, workshop_id: workshopId, strategy: 'mto',
        workers: 10, machines: 2, shifts_per_day: 1, hours_per_shift: 8,
        efficiency: 0.85, max_overtime_pct: 0.2, yield_rate: 0.98, role_name: '操作工', description: '',
      }
      return { ...c, sections: [...c.sections, sec] }
    })
  }, [])

  const removeWorkshop = useCallback((wid: string) => {
    setConfig((c) => {
      if (!c) return c
      const secIds = new Set(c.sections.filter((s) => s.workshop_id === wid).map((s) => s.section_id))
      if (c.routings.some((r) => r.operations.some((op) => secIds.has(op.section_id)))) {
        message.warning('该车间下的工段被工艺路线引用，请先调整工艺路线')
        return c
      }
      return {
        ...c,
        workshops: c.workshops.filter((w) => w.workshop_id !== wid),
        sections: c.sections.filter((s) => s.workshop_id !== wid),
      }
    })
  }, [])

  const removeSection = useCallback((sid: string) => {
    setConfig((c) => {
      if (!c) return c
      if (c.routings.some((r) => r.operations.some((op) => op.section_id === sid))) {
        message.warning('该工段被工艺路线工序引用，请先调整工艺路线')
        return c
      }
      return { ...c, sections: c.sections.filter((s) => s.section_id !== sid) }
    })
  }, [])

  const moveSection = useCallback((sid: string, targetWid: string, beforeSid: string | null) => {
    setConfig((c) => {
      if (!c) return c
      const sec = c.sections.find((s) => s.section_id === sid)
      if (!sec) return c
      const rest = c.sections.filter((s) => s.section_id !== sid)
      const moved = { ...sec, workshop_id: targetWid }
      if (!beforeSid) return { ...c, sections: [...rest, moved] }
      const idx = rest.findIndex((s) => s.section_id === beforeSid)
      if (idx < 0) return { ...c, sections: [...rest, moved] }
      const next = [...rest]
      next.splice(idx, 0, moved)
      return { ...c, sections: next }
    })
  }, [])

  if (!config) {
    return <Card><Empty description={booting ? '场景加载中…' : '场景加载失败'} /></Card>
  }

  /* ---------- 订单组合表格列（表内编辑 + 分页） ---------- */
  const orderColumns: any[] = [
    { title: '订单号', dataIndex: 'order_id', key: 'order_id', width: 96, render: (v: string) => <Text code style={{ fontSize: 11 }}>{v}</Text> },
    {
      title: '产品', dataIndex: 'product_id', key: 'product_id',
      render: (v: string, o: OrderInput) => (
        <Select size="small" value={v} onChange={(nv) => patchOrder(o.order_id, { product_id: nv })}
          options={config.routings.map((r) => ({ label: r.product_name, value: r.product_id }))} style={{ width: '100%' }} />
      ),
    },
    {
      title: '数量', dataIndex: 'quantity', key: 'quantity', width: 92,
      render: (v: number, o: OrderInput) => (
        <InputNumber size="small" min={1} value={v} onChange={(nv) => patchOrder(o.order_id, { quantity: nv || 1 })} style={{ width: '100%' }} />
      ),
    },
    {
      title: '投放日', dataIndex: 'release_day', key: 'release_day', width: 78,
      render: (v: number, o: OrderInput) => (
        <InputNumber size="small" min={0} value={v} onChange={(nv) => patchOrder(o.order_id, { release_day: nv ?? 0 })} style={{ width: '100%' }} />
      ),
    },
    {
      title: '交期日', dataIndex: 'due_day', key: 'due_day', width: 78,
      render: (v: number, o: OrderInput) => (
        <InputNumber size="small" min={1} value={v} onChange={(nv) => patchOrder(o.order_id, { due_day: nv ?? 1 })} style={{ width: '100%' }} />
      ),
    },
    {
      title: '优先级', dataIndex: 'priority', key: 'priority', width: 88,
      render: (v: Priority, o: OrderInput) => (
        <Select size="small" value={v} onChange={(nv) => patchOrder(o.order_id, { priority: nv })}
          options={(Object.keys(PRIORITY_LABEL) as Priority[]).map((p) => ({ label: PRIORITY_LABEL[p], value: p }))} style={{ width: '100%' }} />
      ),
    },
    {
      title: '', key: 'op', width: 40,
      render: (_: unknown, o: OrderInput) => (
        <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={() => removeOrder(o.order_id)} />
      ),
    },
  ]

  return (
    <div>
      {/* 场景控制条：工厂切换器 + 场景说明 + 运行 */}
      <Card size="small" style={{ marginBottom: 12 }} styles={{ body: { padding: '10px 14px' } }}>
        <Row justify="space-between" align="middle" gutter={[8, 8]}>
          <Col flex="auto">
            <Space size={10} wrap align="center">
              <Space size={6}>
                <Text type="secondary" style={{ fontSize: 12 }}>样本工厂</Text>
                <Select
                  value={activeId || undefined}
                  style={{ minWidth: 230 }}
                  loading={booting}
                  onChange={(v) => loadScenario(v)}
                  options={scenarios.map((s) => ({
                    value: s.scenario_id,
                    label: (
                      <Space size={6}>
                        <BankOutlined style={{ color: '#1890ff' }} />
                        <span style={{ fontWeight: 600 }}>{s.scenario_name}</span>
                      </Space>
                    ),
                  }))}
                />
              </Space>
              {tags.map((t) => <Tag key={t} color="geekblue" style={{ fontSize: 11 }}>{t}</Tag>)}
            </Space>
            <div style={{ marginTop: 6 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>{desc}</Text>
            </div>
            {hints.length > 0 && (
              <div style={{ marginTop: 6 }}>
                <Space size={[6, 6]} wrap>
                  <Text type="secondary" style={{ fontSize: 12 }}>试试：</Text>
                  {hints.map((h, i) => <Tag key={i} color="processing" style={{ fontSize: 11 }}>{h}</Tag>)}
                </Space>
              </div>
            )}
          </Col>
          <Col>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => loadScenario(activeId)}>重置场景</Button>
              <Button type="primary" icon={<ThunderboltOutlined />} loading={loading}
                onClick={async () => { if (await runSim(config)) setView('results') }}>
                运行仿真
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {/* ===== 三区工作台：产线组态 / 参数配置 / 仿真结果 ===== */}
      <Tabs
        activeKey={view}
        onChange={(k) => setView(k as 'topology' | 'config' | 'results')}
        items={[
          {
            key: 'topology',
            label: <span><DeploymentUnitOutlined /> 产线组态</span>,
            children: (
              <FlowTopology
                config={config} result={result} scenarioId={activeId}
                onPatchSection={patchSection} onPatchWorkshop={patchWorkshop}
                onAddWorkshop={addWorkshop} onAddSection={addSection}
                onRemoveWorkshop={removeWorkshop} onRemoveSection={removeSection}
                onMoveSection={moveSection}
              />
            ),
          },
          {
            key: 'config',
            label: <span><ControlOutlined /> 参数配置</span>,
            children: (
              <Row gutter={[12, 12]}>
                <Col xs={24} lg={8}>
                  <Card size="small" title={<Space size={6}><ControlOutlined />仿真参数</Space>} style={{ height: '100%' }}>
                    <Field label={`计划期 ${config.horizon_days} 天`}>
                      <Slider min={5} max={60} value={config.horizon_days}
                        marks={{ 7: '7', 14: '14', 30: '30', 60: '60' }}
                        onChange={(v) => patch({ horizon_days: v })} />
                    </Field>
                    <Field label={`日需求波动 ±${pct(config.demand_variability_pct, 0)}`}>
                      <Slider min={0} max={0.5} step={0.05} value={config.demand_variability_pct}
                        onChange={(v) => patch({ demand_variability_pct: v })} />
                    </Field>
                    <Row justify="space-between" align="middle" style={{ marginTop: 4 }}>
                      <span style={{ fontSize: 12 }}>允许加班</span>
                      <Switch size="small" checked={config.overtime_allowed} onChange={(v) => patch({ overtime_allowed: v })} />
                    </Row>
                    {config.demand_variability_pct > 0 && (
                      <Field label="随机种子（可复现）">
                        <InputNumber size="small" min={0} value={config.seed} onChange={(v) => patch({ seed: v ?? 42 })} style={{ width: 120 }} />
                      </Field>
                    )}
                  </Card>
                </Col>
                <Col xs={24} lg={16}>
                  <Card size="small" title={<Space size={6}><ExperimentOutlined />订单组合</Space>}
                    extra={
                      <Space size={8}>
                        <Tag color="blue" style={{ margin: 0 }}>{config.orders.length} 张</Tag>
                        <Button size="small" type="primary" ghost icon={<PlusOutlined />} onClick={addOrder}>新增订单</Button>
                      </Space>
                    }
                    styles={{ body: { padding: 0 } }}>
                    <Table dataSource={config.orders} columns={orderColumns} rowKey="order_id" size="small"
                      pagination={{ pageSize: 8, size: 'small', showSizeChanger: false, showTotal: (t) => `共 ${t} 张订单` }} />
                  </Card>
                </Col>
                <Col span={24}>
                  <Card size="small" title={<Space size={6}><ClusterOutlined />车间 · 工段参数</Space>}
                    extra={<Text type="secondary" style={{ fontSize: 11 }}>{config.sections.length} 个工段 · 网格内可直接调参</Text>}>
                    {config.workshops.map((ws) => (
                      <div key={ws.workshop_id} style={{ marginBottom: 14 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#f7f9fc', padding: '6px 10px', borderRadius: 4, marginBottom: 8 }}>
                          <Space size={6}>
                            <Text strong style={{ fontSize: 13 }}>{ws.name}</Text>
                            <Text type="secondary" style={{ fontSize: 10 }}>{ws.workshop_id}</Text>
                          </Space>
                          <Segmented
                            size="small"
                            value={ws.working_days_per_week}
                            onChange={(v) => patchWorkshop(ws.workshop_id, { working_days_per_week: Number(v) })}
                            options={[
                              { label: '双休', value: 5 },
                              { label: '单休', value: 6 },
                              { label: '全周', value: 7 },
                            ]}
                          />
                        </div>
                        <Row gutter={[10, 10]}>
                          {config.sections.filter((s) => s.workshop_id === ws.workshop_id).map((s) => (
                            <Col xs={24} md={12} xl={8} key={s.section_id}>
                              <SectionEditor section={s} onPatch={(p) => patchSection(s.section_id, p)} />
                            </Col>
                          ))}
                        </Row>
                      </div>
                    ))}
                  </Card>
                </Col>
              </Row>
            ),
          },
          {
            key: 'results',
            label: <span><DashboardOutlined /> 仿真结果 {result ? <Badge status="success" /> : <Badge status="default" />}</span>,
            children: result ? (
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0 2px' }}>
                  <Space size={12} style={{ fontSize: 12, color: '#8c8c8c' }} wrap>
                    <span>仿真 #{result.simulation_id.slice(0, 8)}</span>
                    <span>引擎 v{result.engine_version}</span>
                    <span>{result.workshop_count} 车间 / {result.section_count} 工段 / {result.order_count} 订单 / {result.horizon_days} 天</span>
                  </Space>
                  <Text type="secondary" style={{ fontSize: 12 }}>生成于 {dayjs(result.created_at).format('HH:mm:ss')}</Text>
                </div>
                <KpiStrip result={result} />
                <Tabs
                  defaultActiveKey="load"
                  size="small"
                  items={[
                    {
                      key: 'load', label: <span><ApartmentOutlined /> 负荷排程</span>,
                      children: (
                        <Space direction="vertical" size={12} style={{ width: '100%' }}>
                          <LoadHeatmap result={result} />
                          <OrderGantt result={result} />
                          <Card size="small" title="订单 × 工段 负荷贡献矩阵" styles={{ body: { padding: 0 } }}>
                            <LoadMatrix result={result} />
                          </Card>
                          <Row gutter={12}>
                            <Col span={10}>
                              <Card size="small" title="在制品 WIP 曲线">
                                <WipCurve result={result} />
                              </Card>
                            </Col>
                            <Col span={14}>
                              <Card size="small"
                                title={<Space size={6}><WarningOutlined />告警中心<Tag color="red">{result.alerts.length}</Tag></Space>}
                                styles={{ body: { maxHeight: 240, overflowY: 'auto' } }}>
                                <AlertPanel result={result} />
                              </Card>
                            </Col>
                          </Row>
                        </Space>
                      ),
                    },
                    { key: 'output', label: <span><RiseOutlined /> 产出分析</span>, children: <OutputAnalysis result={result} /> },
                    { key: 'workforce', label: <span><TeamOutlined /> 工人花名册</span>, children: <WorkforcePanel result={result} /> },
                    { key: 'po', label: <span><ProfileOutlined /> PO 工单</span>, children: <PoPanel result={result} /> },
                    { key: 'transfer', label: <span><SwapOutlined /> 流转记录</span>, children: <TransferPanel result={result} /> },
                    { key: 'trace', label: <span><NodeIndexOutlined /> 全流程追踪</span>, children: <ProcessTracePanel result={result} /> },
                    { key: 'blocking', label: <span><AimOutlined /> 卡点分析</span>, children: <BlockingAnalysisPanel result={result} /> },
                  ]}
                />
              </Space>
            ) : (
              <Card><Empty description={booting ? '场景加载中…' : '点击“运行仿真”查看结果'} /></Card>
            ),
          },
        ]}
      />
    </div>
  )
}

export default FactoryLoadSim
