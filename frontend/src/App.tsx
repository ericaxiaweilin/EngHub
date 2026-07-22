import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import WorkOrderList from './pages/workorder/WorkOrderList'
import WorkOrderDetail from './pages/workorder/WorkOrderDetail'
import ProductionReport from './pages/reporting/ProductionReport'
import InspectionList from './pages/qms/InspectionList'
import DefectList from './pages/qms/DefectList'
import InventoryList from './pages/wms/InventoryList'
import SimulationEngine from './pages/simulation/SimulationEngine'
import PlanList from './pages/pp/PlanList'
import BaseData from './pages/basedata/BaseData'
import SkillMatrix from './pages/hr/SkillMatrix'
import WarehouseList from './pages/wms/WarehouseList'
import Assistant from './pages/ai/Assistant'
import Login from './pages/auth/Login'
// v2.5 Modules
import ExpertSystemChat from './pages/expert/ExpertChat'
import WarRoom from './pages/war-room/WarRoom'
import AndonDashboard from './pages/andon/AndonDashboard'
import WorkOrderTemplatesPage from './pages/templates/WorkOrderTemplates'
import { isAuthenticated, getStoredUser } from './services/auth'
// TMS 模块
import ApprovalCenter from './pages/tms/ApprovalCenter'
import TaskDistribution from './pages/tms/TaskDistribution'
import AgentConsole from './pages/tms/AgentConsole'
import QuickRequest from './pages/tms/QuickRequest'

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

  const menuPath = path.startsWith('/') ? path : `/${path}`
  const menuItems = user.menu_items || []
  const hasAccess = menuItems.some((item: any) => {
    if (item.key === menuPath) return true
    // 检查子菜单
    if (item.children && item.children.some((child: any) => child.key === menuPath)) return true
    return false
  })

  if (!hasAccess && menuPath !== '/dashboard') {
    return <Navigate to="/dashboard" replace />
  }

  return children
}

const App: React.FC = () => {
  return (
    <ConfigProvider locale={zhCN} theme={theme}>
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
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="work-orders" element={<PermissionGate path="/work-orders"><WorkOrderList /></PermissionGate>} />
            <Route path="work-orders/:id" element={<PermissionGate path="/work-orders"><WorkOrderDetail /></PermissionGate>} />
            <Route path="production-report" element={<PermissionGate path="/production-report"><ProductionReport /></PermissionGate>} />
            <Route path="inspections" element={<PermissionGate path="/inspections"><InspectionList /></PermissionGate>} />
            <Route path="defects" element={<PermissionGate path="/defects"><DefectList /></PermissionGate>} />
            <Route path="inventory" element={<PermissionGate path="/inventory"><InventoryList /></PermissionGate>} />
            <Route path="warehouses" element={<PermissionGate path="/warehouses"><WarehouseList /></PermissionGate>} />
            <Route path="plans" element={<PermissionGate path="/plans"><PlanList /></PermissionGate>} />
            <Route path="base-data" element={<PermissionGate path="/base-data"><BaseData /></PermissionGate>} />
            <Route path="skill-matrix" element={<PermissionGate path="/skill-matrix"><SkillMatrix /></PermissionGate>} />
            {/* 仿真引擎：车间负荷 / 人因合规 / 审计记录 统一模块 */}
            <Route path="simulation" element={<PermissionGate path="/simulation"><SimulationEngine /></PermissionGate>} />
            <Route path="sim-erp/factory" element={<Navigate to="/simulation?tab=factory" replace />} />
            <Route path="sim-erp/run" element={<Navigate to="/simulation?tab=compliance" replace />} />
            <Route path="sim-erp/audits" element={<Navigate to="/simulation?tab=audit" replace />} />
            <Route path="ai" element={<PermissionGate path="/ai"><Assistant /></PermissionGate>} />
            {/* TMS 任务管理系统 */}
            <Route path="tms/approval" element={<PermissionGate path="/tms/approval"><ApprovalCenter /></PermissionGate>} />
            <Route path="tms/distribution" element={<PermissionGate path="/tms/distribution"><TaskDistribution /></PermissionGate>} />
            <Route path="tms/agent" element={<PermissionGate path="/tms/agent"><AgentConsole /></PermissionGate>} />
            <Route path="quick-request" element={<QuickRequest />} />
            {/* v2.5 Smart Collaboration */}
            <Route path="andon" element={<PermissionGate path="/andon"><AndonDashboard /></PermissionGate>} />
            <Route path="work-order-templates" element={<PermissionGate path="/work-order-templates"><WorkOrderTemplatesPage /></PermissionGate>} />
            <Route path="expert" element={<PermissionGate path="/ai"><ExpertSystemChat /></PermissionGate>} />
            <Route path="war-room" element={<PermissionGate path="/simulation"><WarRoom /></PermissionGate>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
