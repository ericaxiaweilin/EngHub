/**
 * RCC 资源调度决策中心 — 厂长级指挥中心
 * 深色主题 + 多维资源统筹 + AI决策引擎 + 审批流程
 */
import { useState, useEffect, useCallback, createContext, useContext } from 'react'
import { Layout, Menu, Space, Tag, Badge, Select, Button, message, Spin, Tooltip } from 'antd'
import {
  DashboardOutlined, TeamOutlined, ToolOutlined, ThunderboltOutlined,
  FundOutlined, ReloadOutlined, ApiOutlined, ClockCircleOutlined,
  AlertOutlined, SettingOutlined, RadarChartOutlined
} from '@ant-design/icons'
import axios from 'axios'
import RCCOverview from './RCCOverview'
import RCCResourceBoard from './RCCResourceBoard'
import RCCDecisionHub from './RCCDecisionHub'
import RCCAnalysis from './RCCAnalysis'
import RCCOrgBubbles from './RCCOrgBubbles'

const API_BASE = '/api/v1/rcc'
const { Sider, Content, Header } = Layout

// ==================== 全局上下文 ====================
export interface RccContextType {
  baseline: any
  decisions: any
  factoryId: string
  loading: boolean
  lastSync: string | null
  refresh: () => void
}

export const RccContext = createContext<RccContextType>({
  baseline: {}, decisions: {}, factoryId: 'FAC_ELEC_DEMO_2026',
  loading: false, lastSync: null, refresh: () => {}
})

export const useRcc = () => useContext(RccContext)

// ==================== 样式常量 ====================
const COLORS = {
  bg: '#0f1923',
  bgCard: '#1a2733',
  bgHover: '#243442',
  border: '#2a3f50',
  accent: '#00d4aa',
  accentBlue: '#4facfe',
  accentPurple: '#a78bfa',
  warning: '#fbbf24',
  danger: '#f87171',
  success: '#34d399',
  text: '#e2e8f0',
  textDim: '#94a3b8',
  textMuted: '#64748b',
}

export { COLORS }

// ==================== 主组件 ====================
export default function RCCCommandCenter() {
  const [activeView, setActiveView] = useState('overview')
  const [factoryId, setFactoryId] = useState(() => localStorage.getItem('active_factory_id') || 'FAC_ELEC_DEMO_2026')
  const [baseline, setBaseline] = useState<any>({})
  const [decisions, setDecisions] = useState<any>({})
  const [loading, setLoading] = useState(false)
  const [lastSync, setLastSync] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [factories, setFactories] = useState<string[]>([factoryId, 'FAC_ELEC_DEMO_2026', 'FAC_MECH_001'])

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [dataRes, decisionRes] = await Promise.allSettled([
        axios.get(`${API_BASE}/data`, { params: { factory_id: factoryId, mode: 'single' } }),
        axios.get(`${API_BASE}/decision/full`, { params: { factory_id: factoryId } }),
      ])
      if (dataRes.status === 'fulfilled' && dataRes.value.data?.success) {
        setBaseline(dataRes.value.data.baseline || {})
        // 提取工厂列表
        if (dataRes.value.data.factories) setFactories(dataRes.value.data.factories)
      }
      if (decisionRes.status === 'fulfilled' && decisionRes.value.data?.success) {
        setDecisions(decisionRes.value.data.data || {})
      }
      setLastSync(new Date().toLocaleTimeString('zh-CN'))
    } catch (e) {
      message.error('RCC数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [factoryId])

  const handleFactoryChange = (nextFactoryId: string) => {
    setFactoryId(nextFactoryId)
    localStorage.setItem('active_factory_id', nextFactoryId)
  }

  useEffect(() => { fetchData() }, [fetchData])

  useEffect(() => {
    if (!autoRefresh) return
    const timer = setInterval(fetchData, 30000)
    return () => clearInterval(timer)
  }, [autoRefresh, fetchData])

  const menuItems = [
    { key: 'overview', icon: <DashboardOutlined />, label: '指挥总览' },
    { key: 'org-bubbles', icon: <TeamOutlined />, label: '任务智慧中心' },
    { key: 'resources', icon: <RadarChartOutlined />, label: '资源调度' },
    { key: 'decisions', icon: <ThunderboltOutlined />, label: '决策中心' },
    { key: 'analysis', icon: <FundOutlined />, label: '瓶颈分析' },
  ]

  return (
    <RccContext.Provider value={{ baseline, decisions, factoryId, loading, lastSync, refresh: fetchData }}>
      <Layout style={{ minHeight: '100vh', background: COLORS.bg }}>
        {/* 左侧导航 */}
        <Sider width={220} style={{ background: COLORS.bgCard, borderRight: `1px solid ${COLORS.border}` }}>
          <div style={{ padding: '20px 16px', borderBottom: `1px solid ${COLORS.border}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{
                width: 36, height: 36, borderRadius: 8,
                background: `linear-gradient(135deg, ${COLORS.accent}, ${COLORS.accentBlue})`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 18, fontWeight: 700, color: '#fff'
              }}>R</div>
              <div>
                <div style={{ color: COLORS.text, fontWeight: 700, fontSize: 15 }}>RCC 决策中心</div>
                <div style={{ color: COLORS.textMuted, fontSize: 11 }}>Resource Command Center</div>
              </div>
            </div>
          </div>
          <Menu
            mode="inline"
            selectedKeys={[activeView]}
            onClick={({ key }) => setActiveView(key)}
            items={menuItems}
            style={{ background: 'transparent', border: 'none', padding: '12px 8px' }}
          />
          <div style={{ position: 'absolute', bottom: 16, left: 16, right: 16 }}>
            <div style={{ padding: '12px', borderRadius: 8, background: COLORS.bg, border: `1px solid ${COLORS.border}` }}>
              <div style={{ color: COLORS.textMuted, fontSize: 11, marginBottom: 6 }}>数据同步</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Badge status={autoRefresh ? 'processing' : 'default'} color={autoRefresh ? COLORS.accent : COLORS.textMuted} />
                <span style={{ color: COLORS.textDim, fontSize: 12 }}>
                  {lastSync ? `最近: ${lastSync}` : '未同步'}
                </span>
              </div>
            </div>
          </div>
        </Sider>

        {/* 主内容区 */}
        <Layout style={{ background: COLORS.bg }}>
          <Header style={{
            background: COLORS.bgCard, borderBottom: `1px solid ${COLORS.border}`,
            padding: '0 24px', height: 56, display: 'flex', alignItems: 'center', justifyContent: 'space-between'
          }}>
            <Space size={16}>
              <span style={{ color: COLORS.text, fontSize: 16, fontWeight: 600 }}>
                {menuItems.find(m => m.key === activeView)?.label}
              </span>
              <Tag style={{ background: COLORS.bg, border: `1px solid ${COLORS.border}`, color: COLORS.accent }}>
                <ApiOutlined /> 实时
              </Tag>
            </Space>
            <Space size={12}>
              <Select
                value={factoryId}
                onChange={handleFactoryChange}
                style={{ width: 160 }}
                popupClassName="rcc-dark-dropdown"
                options={Array.from(new Set(factories.filter(Boolean))).map(f => ({ value: f, label: `工厂 ${f}` }))}
              />
              <Tooltip title={autoRefresh ? '停止自动刷新' : '开启30s自动刷新'}>
                <Button
                  icon={autoRefresh ? <ClockCircleOutlined /> : <ReloadOutlined />}
                  type={autoRefresh ? 'primary' : 'default'}
                  ghost={autoRefresh}
                  onClick={() => setAutoRefresh(!autoRefresh)}
                  style={autoRefresh ? { borderColor: COLORS.accent, color: COLORS.accent } : {}}
                />
              </Tooltip>
              <Button icon={<ReloadOutlined spin={loading} />} onClick={fetchData}
                style={{ borderColor: COLORS.border, color: COLORS.textDim }}>
                刷新
              </Button>
            </Space>
          </Header>

          <Content style={{ padding: 24, overflow: 'auto' }}>
            <Spin spinning={loading && !lastSync}>
              {activeView === 'overview' && <RCCOverview />}
              {activeView === 'org-bubbles' && <RCCOrgBubbles factoryId={factoryId} />}
              {activeView === 'resources' && <RCCResourceBoard />}
              {activeView === 'decisions' && <RCCDecisionHub />}
              {activeView === 'analysis' && <RCCAnalysis />}
            </Spin>
          </Content>
        </Layout>
      </Layout>
    </RccContext.Provider>
  )
}
