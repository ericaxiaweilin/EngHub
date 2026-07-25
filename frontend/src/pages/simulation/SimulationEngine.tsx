import React, { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Button, Card, Col, Progress, Row, Space, Table, Tag, message } from 'antd'
import {
  AuditOutlined, CheckCircleOutlined, CloseCircleOutlined, HeatMapOutlined,
  ReloadOutlined, SafetyCertificateOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import api from '../../services/api'
import { API_ENDPOINTS } from '../../config/api'
import FactoryLoadSim from './FactoryLoadSim'
import ComplianceSim from './ComplianceSim'
import AuditRecords from './AuditRecords'

/* ====================================================================
 * 仿真引擎 —— 统一模块外壳
 * 车间负荷仿真 / 人因合规仿真 / 合规审计记录 属于同一个"仿真引擎"功能，
 * 本组件负责：模块身份头部（引擎活状态）、能力面 Tab 选择、URL 同步、面板保活。
 * ==================================================================== */

const TAB_KEYS = ['factory', 'compliance', 'audit', 'selftest'] as const
type TabKey = typeof TAB_KEYS[number]

interface TabDef {
  key: TabKey
  icon: React.ReactNode
  name: string
  desc: string
  accent: string
  node: React.ReactNode
}

/* ==================== 引擎自检面板 ==================== */

interface SelfTestScenario {
  id: string
  name: string
  passed: number
  failed: number
  total: number
  ok: boolean
}

interface SelfTestReport {
  engine_version: string
  scenarios: SelfTestScenario[]
  total_checks: number
  passed: number
  failed: number
  design_quality_score: number
  is_simulation: boolean
  timestamp: string
}

const EngineSelfTest: React.FC = () => {
  const [report, setReport] = useState<SelfTestReport | null>(null)
  const [loading, setLoading] = useState(false)

  const runTest = useCallback(async () => {
    setLoading(true)
    try {
      const r: any = await api.get(API_ENDPOINTS.SIM_FACTORY_SELF_TEST, { params: { include_live: true } })
      setReport(r)
      if (r.failed === 0) message.success(`引擎自检通过：${r.passed}/${r.total_checks} 项不变式全过`)
      else message.warning(`引擎自检：${r.failed} 项未通过`)
    } catch {
      message.error('引擎自检请求失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { runTest() }, [runTest])

  const columns: any[] = [
    { title: '场景', dataIndex: 'name', key: 'name', render: (v: string, r: SelfTestScenario) => <Space size={6}><span style={{ fontWeight: 600 }}>{v}</span><Tag style={{ margin: 0, fontSize: 10 }}>{r.id}</Tag></Space> },
    { title: '通过', dataIndex: 'passed', key: 'passed', width: 80, align: 'center' as const, render: (v: number) => <span style={{ color: '#52c41a', fontWeight: 700 }}>{v}</span> },
    { title: '失败', dataIndex: 'failed', key: 'failed', width: 80, align: 'center' as const, render: (v: number) => <span style={{ color: v > 0 ? '#f5222d' : '#52c41a', fontWeight: 700 }}>{v}</span> },
    { title: '总计', dataIndex: 'total', key: 'total', width: 80, align: 'center' as const },
    { title: '状态', dataIndex: 'ok', key: 'ok', width: 90, align: 'center' as const, render: (v: boolean) => v ? <Tag color="success" icon={<CheckCircleOutlined />}>通过</Tag> : <Tag color="error" icon={<CloseCircleOutlined />}>失败</Tag> },
  ]

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small"
        title={<Space size={6}><ThunderboltOutlined />引擎设计质量自检</Space>}
        extra={<Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={runTest}>重新自检</Button>}
      >
        {report ? (
          <Row gutter={[16, 16]} align="middle">
            <Col span={6} style={{ textAlign: 'center' }}>
              <Progress
                type="circle"
                percent={Number(report.design_quality_score.toFixed(1))}
                size={100}
                strokeColor={report.design_quality_score >= 100 ? '#52c41a' : report.design_quality_score >= 80 ? '#faad14' : '#f5222d'}
                format={(p) => <span style={{ fontSize: 18, fontWeight: 700 }}>{p}%</span>}
              />
              <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 6 }}>设计质量分</div>
            </Col>
            <Col span={18}>
              <Row gutter={[12, 12]}>
                <Col span={8}>
                  <Card size="small" styles={{ body: { padding: '10px 14px' } }}>
                    <div style={{ fontSize: 11, color: '#8c8c8c' }}>引擎版本</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#1890ff' }}>v{report.engine_version}</div>
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small" styles={{ body: { padding: '10px 14px' } }}>
                    <div style={{ fontSize: 11, color: '#8c8c8c' }}>不变式检查</div>
                    <div style={{ fontSize: 18, fontWeight: 700 }}>
                      <span style={{ color: '#52c41a' }}>{report.passed}</span>
                      <span style={{ color: '#8c8c8c', fontSize: 13 }}> / {report.total_checks}</span>
                    </div>
                  </Card>
                </Col>
                <Col span={8}>
                  <Card size="small" styles={{ body: { padding: '10px 14px' } }}>
                    <div style={{ fontSize: 11, color: '#8c8c8c' }}>场景数</div>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#722ed1' }}>{report.scenarios.length}</div>
                  </Card>
                </Col>
              </Row>
              <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 8 }}>
                自检时间：{new Date(report.timestamp).toLocaleString()} · 仿真数据（is_simulation=true）
              </div>
            </Col>
          </Row>
        ) : (
          <div style={{ textAlign: 'center', padding: 24, color: '#8c8c8c' }}>{loading ? '正在运行引擎自检…' : '点击“重新自检”开始'}</div>
        )}
      </Card>
      {report && (
        <Card size="small" title="场景明细" styles={{ body: { padding: 0 } }}>
          <Table dataSource={report.scenarios} columns={columns} rowKey="id" size="small" pagination={false} />
        </Card>
      )}
    </Space>
  )
}

const TABS: TabDef[] = [
  {
    key: 'factory', icon: <HeatMapOutlined />, accent: '#1890ff',
    name: '车间负荷仿真', desc: '工段×订单 有限产能排程 · MTS/MTO 双策略',
    node: <FactoryLoadSim />,
  },
  {
    key: 'compliance', icon: <SafetyCertificateOutlined />, accent: '#52c41a',
    name: '人因合规仿真', desc: '疲劳/能耗物理模型 + 多法规插件仲裁',
    node: <ComplianceSim />,
  },
  {
    key: 'audit', icon: <AuditOutlined />, accent: '#722ed1',
    name: '合规审计记录', desc: '仿真留痕 · 裁决回放 · CSV 导出',
    node: <AuditRecords />,
  },
  {
    key: 'selftest', icon: <CheckCircleOutlined />, accent: '#13c2c2',
    name: '引擎自检', desc: '不变式验证 · 设计质量分 · 确定性检查',
    node: <EngineSelfTest />,
  },
]

const SimulationEngine: React.FC = () => {
  const [params, setParams] = useSearchParams()
  const rawTab = params.get('tab') || 'factory'
  const tab: TabKey = (TAB_KEYS as readonly string[]).includes(rawTab) ? (rawTab as TabKey) : 'factory'

  /* 面板保活：首次访问才挂载，挂载后不卸载（保留参数编辑与仿真结果状态） */
  const [visited, setVisited] = useState<TabKey[]>(['factory'])
  useEffect(() => {
    setVisited((v) => (v.includes(tab) ? v : [...v, tab]))
  }, [tab])

  /* 引擎活状态 */
  const [engines, setEngines] = useState<{ factory: string; erp: string }>({
    factory: 'FactoryLoadEngine', erp: 'Sim-ERP Engine',
  })
  useEffect(() => {
    api.get(API_ENDPOINTS.SIM_FACTORY_STATUS)
      .then((r: any) => r?.engine && setEngines((s) => ({ ...s, factory: r.engine })))
      .catch(() => { /* 状态拉取失败不阻塞页面 */ })
    api.get(API_ENDPOINTS.SIM_ERP_STATUS)
      .then((r: any) => r?.engine && setEngines((s) => ({ ...s, erp: r.engine })))
      .catch(() => { /* 状态拉取失败不阻塞页面 */ })
  }, [])

  return (
    <div>
      {/* ── 控制台头部 ── */}
      <div className="sim-console" style={{ padding: '18px 22px 16px', marginBottom: 12 }}>
        <div style={{ position: 'relative', zIndex: 1 }}>
          <Row justify="space-between" align="top" gutter={[12, 12]}>
            <Col>
              <Space size={14} align="center">
                <div style={{
                  width: 42, height: 42, borderRadius: 6,
                  background: 'rgba(54,207,201,0.14)', border: '1px solid rgba(54,207,201,0.45)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <ThunderboltOutlined style={{ color: '#36cfc9', fontSize: 20 }} />
                </div>
                <div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                    <span style={{ color: '#fff', fontSize: 24, fontWeight: 800, letterSpacing: 3 }}>仿真引擎</span>
                    <span style={{ color: 'rgba(255,255,255,0.4)', fontSize: 11, letterSpacing: 2 }}>SIMULATION ENGINE</span>
                  </div>
                  <div style={{ color: 'rgba(255,255,255,0.62)', fontSize: 12, marginTop: 2 }}>
                    车间负荷 · 人因合规 · 审计追溯 —— 一体化仿真平台
                  </div>
                </div>
              </Space>
            </Col>
            <Col>
              <Space size={8} wrap>
                <span style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  background: 'rgba(82,196,26,0.12)', border: '1px solid rgba(82,196,26,0.4)',
                  borderRadius: 20, padding: '3px 12px',
                }}>
                  <span className="sim-status-dot" style={{ width: 7, height: 7, borderRadius: '50%', background: '#52c41a', display: 'inline-block' }} />
                  <span style={{ color: '#95de64', fontSize: 12 }}>引擎运行中</span>
                </span>
                <Tag style={{ margin: 0, background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.22)', color: 'rgba(255,255,255,0.78)' }}>
                  {engines.factory}
                </Tag>
                <Tag style={{ margin: 0, background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.22)', color: 'rgba(255,255,255,0.78)' }}>
                  {engines.erp}
                </Tag>
              </Space>
            </Col>
          </Row>

          {/* ── 能力面 Tab 选择器 ── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginTop: 18 }}>
            {TABS.map((t) => {
              const active = t.key === tab
              return (
                <div
                  key={t.key}
                  className={`sim-tab-card${active ? ' active' : ''}`}
                  onClick={() => setParams({ tab: t.key }, { replace: true })}
                  style={{
                    background: active ? '#fff' : 'rgba(255,255,255,0.07)',
                    border: `1px solid ${active ? '#fff' : 'rgba(255,255,255,0.16)'}`,
                    borderRadius: 6,
                    padding: '10px 14px',
                    position: 'relative',
                    overflow: 'hidden',
                  }}
                >
                  {active && (
                    <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: t.accent }} />
                  )}
                  <Space size={10} align="center">
                    <span style={{ fontSize: 20, color: active ? t.accent : 'rgba(255,255,255,0.65)' }}>{t.icon}</span>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 14, color: active ? '#262626' : 'rgba(255,255,255,0.88)' }}>
                        {t.name}
                      </div>
                      <div style={{ fontSize: 11, color: active ? '#8c8c8c' : 'rgba(255,255,255,0.45)' }}>
                        {t.desc}
                      </div>
                    </div>
                  </Space>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* ── 面板区（保活：切 Tab 不丢参数与结果） ── */}
      {TABS.filter((t) => visited.includes(t.key)).map((t) => (
        <div key={t.key} className="sim-panel" style={{ display: t.key === tab ? 'block' : 'none' }}>
          {t.node}
        </div>
      ))}
    </div>
  )
}

export default SimulationEngine
