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
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
