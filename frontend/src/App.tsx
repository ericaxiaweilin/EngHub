import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Layout from './components/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import WorkOrderList from './pages/mes/WorkOrderList'
import ProductionReport from './pages/mes/ProductionReport'
import PlanBoard from './pages/pp/PlanBoard'
import InspectionList from './pages/qms/InspectionList'
import WarehouseList from './pages/wms/WarehouseList'

const queryClient = new QueryClient()

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            
            {/* MES 模块 */}
            <Route path="mes/work-orders" element={<WorkOrderList />} />
            <Route path="mes/production-report" element={<ProductionReport />} />
            
            {/* PP 模块 */}
            <Route path="pp/plan-board" element={<PlanBoard />} />
            
            {/* QMS 模块 */}
            <Route path="qms/inspections" element={<InspectionList />} />
            
            {/* WMS 模块 */}
            <Route path="wms/warehouses" element={<WarehouseList />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
