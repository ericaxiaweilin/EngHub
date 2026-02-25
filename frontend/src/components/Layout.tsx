import React from 'react'
import { Outlet, Link, useLocation } from 'react-router-dom'
import { Layout as AntLayout, Menu, Badge } from 'antd'
import {
  DashboardOutlined,
  FileTextOutlined,
  EditOutlined,
  SafetyOutlined,
  WarningOutlined,
  InboxOutlined,
} from '@ant-design/icons'

const { Header, Sider, Content } = AntLayout

const Layout: React.FC = () => {
  const location = useLocation()

  const menuItems = [
    { key: '/dashboard', icon: <DashboardOutlined />, label: <Link to="/dashboard">生产看板</Link> },
    { key: '/work-orders', icon: <FileTextOutlined />, label: <Link to="/work-orders">工单管理</Link> },
    { key: '/production-report', icon: <EditOutlined />, label: <Link to="/production-report">生产报工</Link> },
    { key: '/inspections', icon: <SafetyOutlined />, label: <Link to="/inspections">检验管理</Link> },
    { key: '/defects', icon: <WarningOutlined />, label: <Link to="/defects"><Badge count={5} size="small">不良品</Badge></Link> },
    { key: '/inventory', icon: <InboxOutlined />, label: <Link to="/inventory">库存管理</Link> },
  ]

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#fff', borderBottom: '1px solid #d9d9d9', padding: '0 24px' }}>
        <div style={{ fontSize: '18px', fontWeight: 'bold' }}>EngHub MES</div>
      </Header>
      <AntLayout>
        <Sider width={200} style={{ background: '#fff', borderRight: '1px solid #d9d9d9' }}>
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            style={{ height: '100%', borderRight: 0 }}
            items={menuItems}
          />
        </Sider>
        <Content style={{ padding: '24px', background: '#f5f5f5' }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  )
}

export default Layout
