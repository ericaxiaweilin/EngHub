import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { getAntdLocale, getStoredLocale, LOCALE_CHANGE_EVENT } from './services/locale'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import WorkOrderList from './pages/workorder/WorkOrderList'
import WorkOrderDetail from './pages/workorder/WorkOrderDetail'
import ProcessQueue from './pages/workorder/ProcessQueue'
import MyTasks from './pages/workorder/MyTasks'
import RoutingTemplates from './pages/workorder/RoutingTemplates'
import WorkOrderSplitPage from './pages/workorder/WorkOrderSplitPage'
import AlertIntelligence from './pages/alerts/AlertIntelligence'
import ProductionReport from './pages/reporting/ProductionReport'
import InspectionList from './pages/qms/InspectionList'
import DefectList from './pages/qms/DefectList'
import OcapList from './pages/qms/OcapList'  // #9 OCAP闭环 - 新增OCAP管理页面
import OcapDetail from './pages/qms/OcapDetail'  // #9 OCAP闭环 - OCAP详情页面
import InventoryList from './pages/wms/InventoryList'
import SimulationEngine from './pages/simulation/SimulationEngine'
import ProductionData from './pages/ProductionData'
import PlanList from './pages/pp/PlanList'
import SchedulingCenter from './pages/pp/SchedulingCenter'
import OrderManagement from './pages/pp/OrderManagement'
import QualityCenter from './pages/qms/QualityCenter'
import QualityGoals from './pages/qms/QualityGoals'
import InspectionTerminal from './pages/qms/InspectionTerminal'
import SpcDashboard from './pages/qms/SpcDashboard'
import MaintenanceCenter from './pages/equipment/MaintenanceCenter'
import OeeDashboard from './pages/equipment/OeeDashboard'
import EquipmentCenter from './pages/equipment/EquipmentCenter'
import WmsCenter from './pages/wms/WmsCenter'
import WmsTerminal from './pages/wms/WmsTerminal'
import StockAlerts from './pages/wms/StockAlerts'
import PlantFloor from './pages/mes/PlantFloor'
import ReportTerminal from './pages/mes/ReportTerminal'
import ProductionLive from './pages/mes/ProductionLive'
import ReportCenter from './pages/mes/ReportCenter'
import BaseData from './pages/basedata/BaseData'
import SkillMatrix from './pages/hr/SkillMatrix'
import HrRoster from './pages/hr/HrRoster'
import WarehouseList from './pages/wms/WarehouseList'
import Login from './pages/auth/Login'
import ModuleSelector from './pages/ModuleSelector'
// v2.5 Modules
import WarRoom from './pages/war-room/WarRoom'
import AgentSupervisor from './pages/war-room/AgentSupervisor'
import AndonDashboard from './pages/andon/AndonDashboard'
import WorkOrderTemplatesPage from './pages/templates/WorkOrderTemplates'
import RCCCommandCenter from './pages/rcc/RCCCommandCenter'
import { isAuthenticated, getStoredUser } from './services/auth'
// TMS 模块
import ApprovalCenter from './pages/tms/ApprovalCenter'
import TaskDistribution from './pages/tms/TaskDistribution'
import AgentConsole from './pages/tms/AgentConsole'
import QuickRequest from './pages/tms/QuickRequest'
import SystemSettings from './pages/settings/SystemSettings'
import NotificationCenter from './pages/settings/NotificationCenter'
import CollaborationNetwork from './pages/settings/CollaborationNetwork'
import AutomationLevel from './pages/settings/AutomationLevel'
import WorkflowAnalytics from './pages/settings/WorkflowAnalytics'
import ExpertSystemChat from './pages/expert/ExpertChat'
// IE 精益生产模块
import StandardTimes from './pages/ie/StandardTimes'
import TimeStudies from './pages/ie/TimeStudies'
import LineBalanceAnalyses from './pages/ie/LineBalanceAnalyses'
import ProcessAnalyses from './pages/ie/ProcessAnalyses'
import LeanMetrics from './pages/ie/LeanMetrics'
import ActionStudies from './pages/ie-advanced/ActionStudies'
import MethodStudies from './pages/ie-advanced/MethodStudies'
import WorkCells from './pages/ie-advanced/WorkCells'
import Kanbans from './pages/ie-advanced/Kanbans'
import FiveSAudits from './pages/ie-advanced/FiveSAudits'

// 纯色主题配置
const theme = {
  token: {
    colorPrimary: '#1890ff',
    colorSuccess: '#52c41a',
    colorWarning: '#faad14',
    colorError: '#f5222d',
    colorText: '#262626',
    colorTextSecondary: '#595959',
    colorBorder: '#d9d9d9',
    colorBgLayout: '#f5f5f5',
    borderRadius: 4,
  },
}

/**
 * 路由权限守卫：根据用户菜单项决定页面是否可访问
 */
const RequireAuth: React.FC<{ children: React.ReactElement }> = ({ children }) => {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace state={{ from: window.location.pathname }} />
  }
  return children
}

/**
 * 权限门禁：包裹页面组件，path 不在用户菜单中则重定向到 /dashboard
 * 注意：react-router v6 要求 <Route> 子元素必须是字面 <Route>，
 * 因此权限逻辑放在 element 内部而非自定义 Route 组件
 */
const PermissionGate: React.FC<{ path: string; children: React.ReactElement }> = ({ path, children }) => {
  const user = getStoredUser()
  if (!user) return null

  // 管理员/超管直通，不受菜单数据新旧影响
  if (user.is_superuser || user.role === 'admin') return children

  const menuPath = path.startsWith('/') ? path : `/${path}`
  const menuItems = user.menu_items || []
  const hasAccess = menuItems.some((item: any) => {
    if (item.key === menuPath) return true
    // 检查子菜单
    if (item.children && item.children.some((child: any) => child.key === menuPath)) return true
    return false
  })

  if (!hasAccess && menuPath !== '/dashboard') {
    return <Navigate to="/" replace />
  }

  return children
}

const App: React.FC = () => {
  // 多语言：监听语言偏好变更，实时切换 antd locale
  const [antdLocale, setAntdLocale] = React.useState(() => getAntdLocale(getStoredLocale()))
  React.useEffect(() => {
    const handler = () => setAntdLocale(getAntdLocale(getStoredLocale()))
    window.addEventListener(LOCALE_CHANGE_EVENT, handler)
    return () => window.removeEventListener(LOCALE_CHANGE_EVENT, handler)
  }, [])

  return (
    <ConfigProvider locale={antdLocale} theme={theme}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route index element={<ModuleSelector />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="production-data" element={<ProductionData />} />
            <Route path="work-orders" element={<PermissionGate path="/work-orders"><WorkOrderList /></PermissionGate>} />
            <Route path="work-orders/:id" element={<PermissionGate path="/work-orders"><WorkOrderDetail /></PermissionGate>} />

            <Route path="work-orders/:id/split" element={<PermissionGate path="/work-orders/split"><WorkOrderSplitPage /></PermissionGate>} />
                        <Route path="process-queue" element={<PermissionGate path="/process-queue"><ProcessQueue /></PermissionGate>} />
                        <Route path="my-tasks" element={<MyTasks />} />
                        <Route path="routing-templates" element={<PermissionGate path="/routing-templates"><RoutingTemplates /></PermissionGate>} />
                        <Route path="alert-intelligence" element={<PermissionGate path="/alert-intelligence"><AlertIntelligence /></PermissionGate>} />
            <Route path="production-report" element={<PermissionGate path="/production-report"><ProductionReport /></PermissionGate>} />
            <Route path="inspections" element={<PermissionGate path="/inspections"><InspectionList /></PermissionGate>} />
            <Route path="defects" element={<PermissionGate path="/defects"><DefectList /></PermissionGate>} />
            // #9 OCAP闭环 - 新增OCAP管理路由
            <Route path="ocaps" element={<PermissionGate path="/qms/ocaps"><OcapList /></PermissionGate>} />
            <Route path="ocaps/:id" element={<PermissionGate path="/qms/ocaps/detail"><OcapDetail /></PermissionGate>} />
            <Route path="quality-center" element={<PermissionGate path="/quality-center"><QualityCenter /></PermissionGate>} />
            <Route path="quality-goals" element={<PermissionGate path="/quality-goals"><QualityGoals /></PermissionGate>} />
            <Route path="inspection-terminal" element={<PermissionGate path="/inspection-terminal"><InspectionTerminal /></PermissionGate>} />
            <Route path="spc-dashboard" element={<PermissionGate path="/spc-dashboard"><SpcDashboard /></PermissionGate>} />
            <Route path="equipment/maintenance" element={<PermissionGate path="/equipment/maintenance"><MaintenanceCenter /></PermissionGate>} />
            <Route path="equipment/oee" element={<PermissionGate path="/equipment/oee"><OeeDashboard /></PermissionGate>} />
            <Route path="inventory" element={<PermissionGate path="/inventory"><InventoryList /></PermissionGate>} />
            <Route path="warehouses" element={<PermissionGate path="/warehouses"><WarehouseList /></PermissionGate>} />
            <Route path="wms-center" element={<PermissionGate path="/wms-center"><WmsCenter /></PermissionGate>} />
            <Route path="wms-terminal" element={<PermissionGate path="/wms-terminal"><WmsTerminal /></PermissionGate>} />
            <Route path="stock-alerts" element={<PermissionGate path="/stock-alerts"><StockAlerts /></PermissionGate>} />
            <Route path="plans" element={<PermissionGate path="/plans"><PlanList /></PermissionGate>} />
            <Route path="scheduling" element={<PermissionGate path="/scheduling"><SchedulingCenter /></PermissionGate>} />
            <Route path="orders" element={<PermissionGate path="/orders"><OrderManagement /></PermissionGate>} />
            <Route path="base-data" element={<PermissionGate path="/base-data"><BaseData /></PermissionGate>} />
            <Route path="plant-floor" element={<PermissionGate path="/plant-floor"><PlantFloor /></PermissionGate>} />
            <Route path="report-terminal" element={<PermissionGate path="/report-terminal"><ReportTerminal /></PermissionGate>} />
            <Route path="production-live" element={<PermissionGate path="/production-live"><ProductionLive /></PermissionGate>} />
            <Route path="report-center" element={<PermissionGate path="/report-center"><ReportCenter /></PermissionGate>} />
            <Route path="equipment-center" element={<PermissionGate path="/equipment-center"><EquipmentCenter /></PermissionGate>} />
            <Route path="skill-matrix" element={<PermissionGate path="/skill-matrix"><SkillMatrix /></PermissionGate>} />
            <Route path="hr-roster" element={<PermissionGate path="/hr-roster"><HrRoster /></PermissionGate>} />
            {/* 仿真引擎：车间负荷 / 人因合规 / 审计记录 统一模块 */}
            <Route path="simulation" element={<PermissionGate path="/simulation"><SimulationEngine /></PermissionGate>} />
            <Route path="sim-erp/factory" element={<Navigate to="/simulation?tab=factory" replace />} />
            <Route path="sim-erp/run" element={<Navigate to="/simulation?tab=compliance" replace />} />
            <Route path="sim-erp/audits" element={<Navigate to="/simulation?tab=audit" replace />} />
            {/* TMS 任务管理系统 */}
            <Route path="tms/approval" element={<PermissionGate path="/tms/approval"><ApprovalCenter /></PermissionGate>} />
            <Route path="tms/distribution" element={<PermissionGate path="/tms/distribution"><TaskDistribution /></PermissionGate>} />
            <Route path="tms/agent" element={<PermissionGate path="/tms/agent"><AgentConsole /></PermissionGate>} />
            <Route path="quick-request" element={<QuickRequest />} />
            <Route path="settings" element={<SystemSettings />} />
            <Route path="settings/code-tables" element={<SystemSettings defaultTab="codetables" />} />
            <Route path="notifications" element={<NotificationCenter />} />
            <Route path="collaboration" element={<CollaborationNetwork />} />
            <Route path="automation-level" element={<AutomationLevel />} />
            <Route path="workflow-analytics" element={<WorkflowAnalytics />} />
            {/* v2.5 Smart Collaboration */}
            <Route path="andon" element={<PermissionGate path="/andon"><AndonDashboard /></PermissionGate>} />
            <Route path="work-order-templates" element={<PermissionGate path="/work-order-templates"><WorkOrderTemplatesPage /></PermissionGate>} />
            <Route path="work-order-templates" element={<PermissionGate path="/work-order-templates"><WorkOrderTemplatesPage /></PermissionGate>} />
            <Route path="rcc" element={<PermissionGate path="/rcc"><RCCCommandCenter /></PermissionGate>} />
            <Route path="expert" element={<PermissionGate path="/ai"><ExpertSystemChat /></PermissionGate>} />
            <Route path="war-room" element={<PermissionGate path="/simulation"><WarRoom /></PermissionGate>} />
                        <Route path="agent-supervisor" element={<PermissionGate path="/simulation"><AgentSupervisor /></PermissionGate>} />
            {/* IE 精益生产 */}
            <Route path="ie/standard-times" element={<PermissionGate path="/ie/standard-times"><StandardTimes /></PermissionGate>} />
            <Route path="ie/time-studies" element={<PermissionGate path="/ie/standard-times"><TimeStudies /></PermissionGate>} />
            <Route path="ie/line-balance" element={<PermissionGate path="/ie/standard-times"><LineBalanceAnalyses /></PermissionGate>} />
            <Route path="ie/process-analyses" element={<PermissionGate path="/ie/standard-times"><ProcessAnalyses /></PermissionGate>} />
            <Route path="ie/lean-metrics" element={<PermissionGate path="/ie/standard-times"><LeanMetrics /></PermissionGate>} />
            <Route path="ie/action-studies" element={<PermissionGate path="/ie/standard-times"><ActionStudies /></PermissionGate>} />
            <Route path="ie/method-studies" element={<PermissionGate path="/ie/standard-times"><MethodStudies /></PermissionGate>} />
            <Route path="ie/work-cells" element={<PermissionGate path="/ie/standard-times"><WorkCells /></PermissionGate>} />
            <Route path="ie/kanbans" element={<PermissionGate path="/ie/standard-times"><Kanbans /></PermissionGate>} />
            <Route path="ie/5s-audits" element={<PermissionGate path="/ie/standard-times"><FiveSAudits /></PermissionGate>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
