/**
 * 生产数据（独立页面，看板二级菜单）
 *
 * 展示真实生产数据的生产全过程分析：
 * - 数据来源：工单 / 报工 / 设备 / 人员（后端聚合 is_simulation=false）
 * - 复用仿真结果 UI 组件渲染，但与仿真结果看板数据源完全不同
 * - 仿真结果请在「仿真引擎」中查看，不属于本看板
 */
import React, { useCallback, useEffect, useState } from 'react'
import { Card, Col, Empty, Row, Select, Space, Spin, Tabs, Tag, message } from 'antd'
import {
  AimOutlined, ApartmentOutlined, DashboardOutlined, NodeIndexOutlined,
  ProfileOutlined, RiseOutlined, SwapOutlined, TeamOutlined, AlertOutlined,
} from '@ant-design/icons'
import {
  getProductionDashboardResult, ProductionDashboardResult,
} from '../services/factorySim'
import {
  AlertPanel, BlockingAnalysisPanel, KpiStrip, LoadHeatmap, LoadMatrix,
  OrderGantt, OutputAnalysis, PoPanel, ProcessTracePanel, TransferPanel,
  WorkforcePanel, WipCurve,
} from './simulation/FactoryLoadSim'
import { getStoredUser } from '../services/auth'

const ProductionData: React.FC = () => {
  const [prodResult, setProdResult] = useState<ProductionDashboardResult | null>(null)
  const [prodLoading, setProdLoading] = useState(true)
  const [horizonDays, setHorizonDays] = useState(14) // 默认14天
  const [viewMode, setViewMode] = useState<'week' | 'month' | 'year'>('month')

  const user = getStoredUser()
  // 优先用顶部选择器选中的厂区（与其他页面一致），回退到用户所属厂区
  const factoryId = localStorage.getItem('active_factory_id') || user?.factory_id || 'F01'

  // 视图模式对应的天数
  const viewModeDays: Record<string, number> = {
    week: 7,
    month: 14,
    year: 30,
  }

  // 拉取生产看板聚合数据（后端返回 is_simulation=false，否则拒绝渲染）
  const fetchProdSummary = useCallback(async () => {
    setProdLoading(true)
    try {
      const res = await getProductionDashboardResult(factoryId, horizonDays)
      if (res && res.is_simulation === false) {
        setProdResult(res)
      } else {
        message.warning('生产数据接口返回数据缺少真实数据标记，已拒绝渲染')
        setProdResult(null)
      }
    } catch {
      setProdResult(null)
    } finally {
      setProdLoading(false)
    }
  }, [factoryId, horizonDays])

  useEffect(() => { fetchProdSummary() }, [fetchProdSummary])

  // 视图模式切换
  const handleViewModeChange = (mode: 'week' | 'month' | 'year') => {
    setViewMode(mode)
    setHorizonDays(viewModeDays[mode])
  }

  return (
    <Spin spinning={prodLoading}>
      {prodResult ? (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {/* 标题栏：明确标注真实数据属性，与仿真结果视觉区分 */}
          <Card size="small" style={{ border: '1px solid #52c41a', background: 'linear-gradient(90deg, #f6ffed 0%, #ffffff 70%)' }}
            styles={{ body: { padding: '10px 16px' } }}>
            <Row justify="space-between" align="middle">
              <Col>
                <Space size={10} wrap>
                  <span style={{ fontWeight: 700, fontSize: 15 }}>
                    <DashboardOutlined style={{ color: '#52c41a', marginRight: 6 }} />
                    生产全过程分析
                  </span>
                  <Tag color="green">真实生产数据</Tag>
                  <Tag color="default">来源：工单 / 报工 / 设备 / 人员</Tag>
                </Space>
              </Col>
              <Col>
                <Space size={12}>
                  {/* 视图切换 */}
                  <Select
                    value={viewMode}
                    onChange={handleViewModeChange}
                    size="small"
                    style={{ width: 100 }}
                    options={[
                      { value: 'week', label: '周视图' },
                      { value: 'month', label: '月视图' },
                      { value: 'year', label: '年视图' },
                    ]}
                  />
                  <span style={{ fontSize: 12, color: '#8c8c8c' }}>
                    回溯 {prodResult.horizon_days} 天 · {prodResult.order_count} 工单 · {prodResult.section_count} 工位
                  </span>
                </Space>
              </Col>
            </Row>
          </Card>

          {/* KPI 指标条（复用仿真结果组件） */}
          <KpiStrip result={prodResult} />

          {/* 多维度结果 Tabs（复用仿真结果组件，数据为真实生产记录） */}
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
                      <LoadHeatmap result={prodResult} />
                      <OrderGantt result={prodResult} />
                      <Card size="small" title="工单 × 工位 负荷贡献矩阵" styles={{ body: { padding: 0 } }}>
                        <LoadMatrix result={prodResult} />
                      </Card>
                      <Row gutter={12}>
                        <Col span={10}>
                          <Card size="small" title="在制品 WIP 曲线">
                            <WipCurve result={prodResult} />
                          </Card>
                        </Col>
                        <Col span={14}>
                          <Card size="small"
                            title={<Space size={6}><AlertOutlined />告警中心<Tag color="red">{prodResult.alerts.length}</Tag></Space>}
                            styles={{ body: { maxHeight: 240, overflowY: 'auto' } }}>
                            <AlertPanel result={prodResult} />
                          </Card>
                        </Col>
                      </Row>
                    </Space>
                  ),
                },
                { key: 'output', label: <span><RiseOutlined /> 产出分析</span>, children: <OutputAnalysis result={prodResult} /> },
                { key: 'workforce', label: <span><TeamOutlined /> 工人花名册</span>, children: <WorkforcePanel result={prodResult} /> },
                { key: 'po', label: <span><ProfileOutlined /> PO 工单</span>, children: <PoPanel result={prodResult} /> },
                { key: 'transfer', label: <span><SwapOutlined /> 流转记录</span>, children: <TransferPanel result={prodResult} /> },
                { key: 'trace', label: <span><NodeIndexOutlined /> 全流程追踪</span>, children: <ProcessTracePanel result={prodResult} /> },
                { key: 'blocking', label: <span><AimOutlined /> 卡点分析</span>, children: <BlockingAnalysisPanel result={prodResult} /> },
              ]}
            />
          </Card>
        </Space>
      ) : (
        !prodLoading && <Card><Empty description="暂无生产数据" /></Card>
      )}
    </Spin>
  )
}

export default ProductionData
