import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout as AntLayout, Menu, Button, Avatar, Dropdown, Space } from 'antd'
import {
  DashboardOutlined,
  FileTextOutlined,
  ScheduleOutlined,
  CheckCircleOutlined,
  WarehouseOutlined,
  SettingOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons'

const { Header, Sider, Content } = AntLayout

const menuItems = [
  {
    key: '/dashboard',
    icon: <DashboardOutlined />,
    label: '工作台',
  },
  {
    type: 'divider',
  },
  {
    key: 'mes',
    icon: <FileTextOutlined />,
    label: '生产执行',
    children: [
      { key: '/mes/work-orders', label: '工单管理' },
      { key: '/mes/production-report', label: '生产报工' },
    ],
  },
  {
    key: 'pp',
    icon: <ScheduleOutlined />,
    label: '生产计划',
    children: [
      { key: '/pp/plan-board', label: '计划看板' },
    ],
  },
  {
    key: 'qms',
    icon: <CheckCircleOutlined />,
    label: '质量管理',
    children: [
      { key: '/qms/inspections', label: '质量检验' },
    ],
  },
  {
    key: 'wms',
    icon: <WarehouseOutlined />,
    label: '仓库管理',
    children: [
      { key: '/wms/warehouses', label: '仓库列表' },
    ],
  },
]

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  const handleMenuClick = ({ key }: { key: string }) => {
    navigate(key)
  }

  const handleLogout = () => {
    localStorage.removeItem('access_token')
    navigate('/login')
  }

  const userMenu = {
    items: [
      {
        key: 'profile',
        icon: <SettingOutlined />,
        label: '个人设置',
      },
      {
        type: 'divider',
      },
      {
        key: 'logout',
        icon: <LogoutOutlined />,
        label: '退出登录',
        onClick: handleLogout,
      },
    ],
  }

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider trigger={null} collapsible collapsed={collapsed} theme="dark">
        <div style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#001529',
        }}>
          {collapsed ? (
            <span style={{ color: 'white', fontSize: 20, fontWeight: 'bold' }}>M</span>
          ) : (
            <span style={{ color: 'white', fontSize: 18, fontWeight: 'bold' }}>EngHub MES</span>
          )}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={handleMenuClick}
        />
      </Sider>
      <AntLayout>
        <Header style={{
          padding: '0 24px',
          background: '#fff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          boxShadow: '0 1px 4px rgba(0,21,41,.08)',
        }}>
          <Button
            type="text"
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed(!collapsed)}
            style={{ fontSize: 16, width: 64, height: 64 }}
          />
          <Space>
            <span>管理员</span>
            <Dropdown menu={userMenu}>
              <Avatar style={{ backgroundColor: '#1890ff', cursor: 'pointer' }}>A</Avatar>
            </Dropdown>
          </Space>
        </Header>
        <Content style={{
          margin: '24px 16px',
          padding: 24,
          background: '#fff',
          borderRadius: 4,
          minHeight: 280,
        }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  )
}
