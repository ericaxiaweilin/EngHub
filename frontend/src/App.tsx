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
import AuditCenter from './pages/sim-erp/AuditCenter'
import SimulationRunner from './pages/sim-erp/SimulationRunner'
import PlanList from './pages/pp/PlanList'
import BaseData from './pages/basedata/BaseData'
import SkillMatrix from './pages/hr/SkillMatrix'
import WarehouseList from './pages/wms/WarehouseList'
import Assistant from './pages/ai/Assistant'
// TMS 模块
import ApprovalCenter from './pages/tms/ApprovalCenter'
import TaskDistribution from './pages/tms/TaskDistribution'
import AgentConsole from './pages/tms/AgentConsole'

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

const App: React.FC = () => {
  return (
    <ConfigProvider locale={zhCN} theme={theme}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="work-orders" element={<WorkOrderList />} />
            <Route path="work-orders/:id" element={<WorkOrderDetail />} />
            <Route path="production-report" element={<ProductionReport />} />
            <Route path="inspections" element={<InspectionList />} />
            <Route path="defects" element={<DefectList />} />
            <Route path="inventory" element={<InventoryList />} />
            <Route path="warehouses" element={<WarehouseList />} />
            <Route path="plans" element={<PlanList />} />
            <Route path="base-data" element={<BaseData />} />
            <Route path="skill-matrix" element={<SkillMatrix />} />
            <Route path="sim-erp/run" element={<SimulationRunner />} />
            <Route path="sim-erp/audits" element={<AuditCenter />} />
            <Route path="ai" element={<Assistant />} />
            {/* TMS 任务管理系统 */}
            <Route path="tms/approval" element={<ApprovalCenter />} />
            <Route path="tms/distribution" element={<TaskDistribution />} />
            <Route path="tms/agent" element={<AgentConsole />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
