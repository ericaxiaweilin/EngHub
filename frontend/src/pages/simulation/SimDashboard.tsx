/**
 * 仿真结果看板（独立页面）
 *
 * 与生产看板（Dashboard）完全分离：
 * - 生产看板 = 真实生产数据（人/机/料/法/环）
 * - 仿真看板 = 参数计算结果（is_simulation: true）
 *
 * 复用 FactoryLoadSim 的结果面板组件，Tab 切换展示各维度仿真结果。
 */
import React, { useCallback, useEffect, useState } from 'react'
import { Card, Col, Empty, Row, Space, Spin, Tabs, Tag } from 'antd'
import {
  AimOutlined, ApartmentOutlined, ExperimentOutlined, NodeIndexOutlined,
  ProfileOutlined, RiseOutlined, SwapOutlined, TeamOutlined, ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { getFactorySimDashboardResult, SimDashboardFullResult } from '../../services/factorySim'
import {
  AlertPanel, BlockingAnalysisPanel, KpiStrip, LoadHeatmap, LoadMatrix,
  OrderGantt, OutputAnalysis, PoPanel, ProcessTracePanel, TransferPanel,
  WorkforcePanel, WipCurve,
} from './FactoryLoadSim'

const SimDashboard: React.FC = () => {
  const [result, setResult] = useState<SimDashboardFullResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await getFactorySimDashboardResult()
      if (res && res.is_simulation) {
        setResult(res)
      } else {
        setError('接口返回数据缺少仿真标记，已拒绝渲染')
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || '仿真数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div>
      {/* 页头：明确标注仿真属性 */}
      <Card size="small" style={{ marginBottom: 12, border: '1px dashed #722ed1', background: 'linear-gradient(90deg, #faf5ff 0%, #ffffff 70%)' }}>
        <Row justify="space-between" align="middle">
          <Col>
            <Space size={10} wrap>
              <span style={{ fontWeight: 700, fontSize: 15 }}>
                <ExperimentOutlined style={{ color: '#722ed1', marginRight: 6 }} />
                仿真结果看板
              </span>
              <Tag color="purple">仿真数据 · 参数计算</Tag>
              <Tag color="default">与真实生产数据无关</Tag>
            </Space>
            {result && (
              <div style={{ marginTop: 6, fontSize: 12, color: '#8c8c8c' }}>
                <ThunderboltOutlined style={{ marginRight: 4 }} />
                场景 {result.scenario_name} · 计划期 {result.horizon_days} 天 · {result.order_count} 订单 ·{' '}
                {result.workshop_count} 车间 / {result.section_count} 工段 · 引擎 v{result.engine_version}
                {result.alerts.filter((a) => a.level === 'critical').length > 0 && (
                  <Tag color="red" style={{ marginLeft: 8 }}>
                    {result.alerts.filter((a) => a.level === 'critical').length} 条严重预警
                  </Tag>
                )}
                <span style={{ marginLeft: 8 }}>生成于 {dayjs(result.created_at).format('MM-DD HH:mm')}</span>
              </div>
            )}
          </Col>
        </Row>
      </Card>

      <Spin spinning={loading}>
        {error ? (
          <Card><Empty description={error} /></Card>
        ) : result ? (
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            {/* KPI 指标条 */}
            <KpiStrip result={result} />

            {/* 多维度仿真结果 Tabs */}
            <Card size="small" styles={{ body: { paddingTop: 4 } }}>
              <Tabs
                defaultActiveKey="load"
                size="small"
                items={[
                  {
                    key: 'load',
                    label: <span><ApartmentOutlined /> 负荷排程</span>,
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
            </Card>
          </Space>
        ) : (
          !loading && <Card><Empty description="暂无仿真数据" /></Card>
        )}
      </Spin>
    </div>
  )
}

export default SimDashboard
