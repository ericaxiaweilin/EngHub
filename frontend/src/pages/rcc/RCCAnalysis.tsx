/**
 * RCC 瓶颈分析 + 参数控制台
 * 产能瓶颈识别 + 可调参数管理 + 逻辑链配置
 */
import { useState, useEffect, useMemo } from 'react'
import { Row, Col, Tag, Space, Table, Progress, Empty, Switch, Tooltip, Button, message, InputNumber, Modal } from 'antd'
import {
  FundOutlined, WarningOutlined, SettingOutlined, BranchesOutlined,
  ThunderboltOutlined, CheckCircleOutlined, ToolOutlined, TeamOutlined,
  ExperimentOutlined, ControlOutlined, HistoryOutlined, ApiOutlined
} from '@ant-design/icons'
import axios from 'axios'
import { useRcc, COLORS } from './RCCCommandCenter'

const API_BASE = '/api/v1/rcc'

// ==================== 瓶颈热力条 ====================
function BottleneckBar({ name, loadRate, capacity, actual }: {
  name: string; loadRate: number; capacity?: number; actual?: number;
}) {
  const percent = Math.round(loadRate * 100)
  const color = percent >= 90 ? COLORS.danger : percent >= 75 ? COLORS.warning : percent >= 50 ? COLORS.accentBlue : COLORS.success
  const status = percent >= 90 ? '瓶颈' : percent >= 75 ? '紧张' : percent >= 50 ? '正常' : '空闲'

  return (
    <div style={{ padding: '10px 14px', borderRadius: 8, background: COLORS.bg, border: `1px solid ${COLORS.border}`, marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ color: COLORS.text, fontSize: 13, fontWeight: 500 }}>{name}</span>
        <Space size={8}>
          <Tag style={{
            border: 'none', fontSize: 10, padding: '0 6px',
            background: `${color}15`, color
          }}>{status}</Tag>
          <span style={{ color, fontSize: 13, fontWeight: 700 }}>{percent}%</span>
        </Space>
      </div>
      <div style={{ height: 8, borderRadius: 4, background: COLORS.bgHover, overflow: 'hidden' }}>
        <div style={{
          width: `${Math.min(percent, 100)}%`, height: '100%', borderRadius: 4,
          background: `linear-gradient(90deg, ${color}80, ${color})`,
          transition: 'width 0.6s ease'
        }} />
      </div>
      {(capacity || actual) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
          <span style={{ color: COLORS.textMuted, fontSize: 10 }}>实际: {actual || '-'}</span>
          <span style={{ color: COLORS.textMuted, fontSize: 10 }}>产能: {capacity || '-'}</span>
        </div>
      )}
    </div>
  )
}

// ==================== 参数控制行 ====================
function ParamRow({ param, onAdjust }: { param: any; onAdjust: (id: string, value: any) => void }) {
  const sensitivityColors: Record<string, string> = {
    high: COLORS.danger, medium: COLORS.warning, low: COLORS.success
  }
  const sensitivityLabels: Record<string, string> = {
    high: '高敏感', medium: '中敏感', low: '低敏感'
  }

  return (
    <div style={{
      padding: '12px 16px', borderRadius: 8, background: COLORS.bg,
      border: `1px solid ${COLORS.border}`, marginBottom: 8,
      display: 'flex', alignItems: 'center', gap: 12
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: COLORS.text, fontSize: 13, fontWeight: 500 }}>
            {param.param_name || param.param_code}
          </span>
          <Tag style={{
            border: 'none', fontSize: 10, padding: '0 6px',
            background: `${sensitivityColors[param.sensitivity] || COLORS.textMuted}15`,
            color: sensitivityColors[param.sensitivity] || COLORS.textMuted
          }}>
            {sensitivityLabels[param.sensitivity] || param.sensitivity}
          </Tag>
        </div>
        <div style={{ color: COLORS.textMuted, fontSize: 11, marginTop: 2 }}>
          {param.category} · {param.param_code}
          {param.unit && <span> · 单位: {param.unit}</span>}
        </div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div style={{ color: COLORS.accent, fontSize: 16, fontWeight: 700 }}>
          {param.current_value ?? '-'}
        </div>
        {param.target_value && param.target_value !== param.current_value && (
          <div style={{ color: COLORS.textMuted, fontSize: 10 }}>目标: {param.target_value}</div>
        )}
      </div>
      {param.sensitivity !== 'high' && (
        <Button size="small" type="link" style={{ color: COLORS.accentBlue, fontSize: 11 }}
          onClick={() => onAdjust(param.id, param.current_value)}>
          调整
        </Button>
      )}
      {param.sensitivity === 'high' && (
        <Tooltip title="高敏感参数需通过RCC审批">
          <Tag style={{ border: 'none', background: 'rgba(248,113,113,0.1)', color: COLORS.danger, fontSize: 10 }}>
            需审批
          </Tag>
        </Tooltip>
      )}
    </div>
  )
}

// ==================== 主组件 ====================
export default function RCCAnalysis() {
  const { baseline, factoryId } = useRcc()
  const [params, setParams] = useState<any[]>([])
  const [logicChains, setLogicChains] = useState<any[]>([])
  const [loadingParams, setLoadingParams] = useState(false)
  const [activeSection, setActiveSection] = useState<'bottleneck' | 'params' | 'chains'>('bottleneck')

  // 加载参数和逻辑链
  useEffect(() => {
    const load = async () => {
      setLoadingParams(true)
      try {
        const [paramRes, chainRes] = await Promise.allSettled([
          axios.get(`${API_BASE}/params`),
          axios.get(`${API_BASE}/logic-chains`),
        ])
        if (paramRes.status === 'fulfilled') setParams(paramRes.value.data?.items || [])
        if (chainRes.status === 'fulfilled') setLogicChains(chainRes.value.data?.items || [])
      } catch (e) { /* ignore */ }
      finally { setLoadingParams(false) }
    }
    load()
  }, [])

  // 瓶颈数据
  const bottlenecks = useMemo(() => {
    const people = baseline.people || baseline?.baseline?.people || {}
    const equipment = baseline.equipment || baseline?.baseline?.equipment || {}
    const items: { name: string; loadRate: number; type: string }[] = []

    // 工位负荷瓶颈
    (people.work_center_load || []).forEach((wc: any) => {
      items.push({ name: `${wc.name} (工位)`, loadRate: wc.load_rate || 0, type: 'people' })
    })

    // 设备利用率瓶颈
    (equipment.overloaded_devices || equipment.equipment_details || []).forEach((dev: any) => {
      items.push({ name: `${dev.name || dev.equipment_name} (设备)`, loadRate: dev.utilization_rate || 0, type: 'equipment' })
    })

    // 按负荷排序
    return items.sort((a, b) => b.loadRate - a.loadRate)
  }, [baseline])

  const handleAdjustParam = (id: string, currentValue: any) => {
    Modal.confirm({
      title: '调整参数',
      content: `确认调整参数 ${id}？当前值: ${currentValue}`,
      okText: '确认', cancelText: '取消',
      onOk: () => message.success('参数调整已提交'),
    })
  }

  const sectionTabs = [
    { key: 'bottleneck', label: '瓶颈识别', icon: <FundOutlined /> },
    { key: 'params', label: '参数控制台', icon: <ControlOutlined /> },
    { key: 'chains', label: '逻辑链', icon: <BranchesOutlined /> },
  ]

  return (
    <div>
      {/* 区域切换 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {sectionTabs.map(tab => (
          <button key={tab.key} onClick={() => setActiveSection(tab.key as any)} style={{
            padding: '8px 16px', borderRadius: 8, border: `1px solid ${activeSection === tab.key ? COLORS.accent : COLORS.border}`,
            background: activeSection === tab.key ? `${COLORS.accent}10` : COLORS.bgCard,
            color: activeSection === tab.key ? COLORS.accent : COLORS.textDim,
            cursor: 'pointer', fontSize: 13, fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6,
            transition: 'all 0.2s'
          }}>
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {/* 瓶颈识别 */}
      {activeSection === 'bottleneck' && (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={14}>
            <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 20 }}>
              <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 14, marginBottom: 16 }}>
                <FundOutlined style={{ color: COLORS.danger, marginRight: 8 }} />
                产能负荷排行（按瓶颈程度）
              </div>
              {bottlenecks.length > 0 ? (
                bottlenecks.map((item, i) => (
                  <BottleneckBar key={i} name={item.name} loadRate={item.loadRate} />
                ))
              ) : (
                <Empty description={<span style={{ color: COLORS.textMuted }}>暂无负荷数据</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </div>
          </Col>
          <Col xs={24} lg={10}>
            <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 20 }}>
              <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 14, marginBottom: 16 }}>
                <WarningOutlined style={{ color: COLORS.warning, marginRight: 8 }} />
                瓶颈诊断摘要
              </div>
              {bottlenecks.filter(b => b.loadRate >= 0.75).length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {bottlenecks.filter(b => b.loadRate >= 0.75).slice(0, 5).map((b, i) => (
                    <div key={i} style={{
                      padding: '10px 14px', borderRadius: 8,
                      background: b.loadRate >= 0.9 ? 'rgba(248,113,113,0.08)' : 'rgba(251,191,36,0.08)',
                      border: `1px solid ${b.loadRate >= 0.9 ? 'rgba(248,113,113,0.25)' : 'rgba(251,191,36,0.25)'}`
                    }}>
                      <div style={{ color: COLORS.text, fontSize: 12, fontWeight: 500 }}>{b.name}</div>
                      <div style={{ color: COLORS.textMuted, fontSize: 11, marginTop: 4 }}>
                        负荷 {Math.round(b.loadRate * 100)}% — {b.loadRate >= 0.9 ? '严重瓶颈，需立即调度' : '接近满载，建议预防性调配'}
                      </div>
                    </div>
                  ))}
                  <div style={{ padding: '10px 14px', borderRadius: 8, background: COLORS.bg, border: `1px solid ${COLORS.border}` }}>
                    <div style={{ color: COLORS.accent, fontSize: 12, fontWeight: 500 }}>
                      <ThunderboltOutlined style={{ marginRight: 6 }} />建议措施
                    </div>
                    <ul style={{ color: COLORS.textDim, fontSize: 11, margin: '8px 0 0', paddingLeft: 16 }}>
                      <li>从低负荷工位调配人员支援</li>
                      <li>评估是否启动加班或外协</li>
                      <li>检查是否有设备可替代分担</li>
                    </ul>
                  </div>
                </div>
              ) : (
                <div style={{ textAlign: 'center', padding: 30, color: COLORS.textMuted }}>
                  <CheckCircleOutlined style={{ fontSize: 28, color: COLORS.success, display: 'block', marginBottom: 8 }} />
                  当前无产能瓶颈，资源分配均衡
                </div>
              )}
            </div>
          </Col>
        </Row>
      )}

      {/* 参数控制台 */}
      {activeSection === 'params' && (
        <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 14 }}>
              <ControlOutlined style={{ color: COLORS.accentBlue, marginRight: 8 }} />
              全局可调参数 ({params.length})
            </div>
            <Space>
              <Tag style={{ background: 'rgba(248,113,113,0.1)', border: 'none', color: COLORS.danger, fontSize: 11 }}>
                高敏感: {params.filter(p => p.sensitivity === 'high').length}
              </Tag>
              <Tag style={{ background: 'rgba(251,191,36,0.1)', border: 'none', color: COLORS.warning, fontSize: 11 }}>
                中敏感: {params.filter(p => p.sensitivity === 'medium').length}
              </Tag>
            </Space>
          </div>
          {params.length > 0 ? (
            params.map(p => <ParamRow key={p.id} param={p} onAdjust={handleAdjustParam} />)
          ) : (
            <Empty description={<span style={{ color: COLORS.textMuted }}>暂无可调参数配置</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </div>
      )}

      {/* 逻辑链 */}
      {activeSection === 'chains' && (
        <div style={{ background: COLORS.bgCard, borderRadius: 12, border: `1px solid ${COLORS.border}`, padding: 20 }}>
          <div style={{ color: COLORS.text, fontWeight: 600, fontSize: 14, marginBottom: 16 }}>
            <BranchesOutlined style={{ color: COLORS.accentPurple, marginRight: 8 }} />
            确定性逻辑链 ({logicChains.length})
          </div>
          {logicChains.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {logicChains.map((chain) => (
                <div key={chain.id} style={{
                  padding: '14px 16px', borderRadius: 8, background: COLORS.bg,
                  border: `1px solid ${COLORS.border}`, borderLeft: `3px solid ${chain.enabled ? COLORS.success : COLORS.textMuted}`
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <div style={{ color: COLORS.text, fontSize: 13, fontWeight: 500 }}>
                        {chain.chain_name || chain.chain_code}
                      </div>
                      <div style={{ color: COLORS.textMuted, fontSize: 11, marginTop: 2 }}>
                        触发: {chain.trigger_event} · 顺序: {chain.execution_order}
                      </div>
                    </div>
                    <Tag style={{
                      border: 'none', fontSize: 10,
                      background: chain.enabled ? 'rgba(52,211,153,0.1)' : 'rgba(100,116,139,0.1)',
                      color: chain.enabled ? COLORS.success : COLORS.textMuted
                    }}>
                      {chain.enabled ? '已启用' : '已停用'}
                    </Tag>
                  </div>
                  {chain.conditions && (
                    <div style={{ marginTop: 8, padding: '6px 10px', borderRadius: 6, background: COLORS.bgHover }}>
                      <span style={{ color: COLORS.textMuted, fontSize: 10 }}>
                        条件: {typeof chain.conditions === 'string' ? chain.conditions : JSON.stringify(chain.conditions).slice(0, 100)}
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <Empty description={<span style={{ color: COLORS.textMuted }}>暂无逻辑链配置</span>} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </div>
      )}
    </div>
  )
}
