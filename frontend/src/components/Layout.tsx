import React, { useState, useMemo } from 'react'
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { Layout as AntLayout, Menu, Avatar, Space, Tag, Dropdown, Button } from 'antd'
import {
  DashboardOutlined,
  FileTextOutlined,
  EditOutlined,
  SafetyOutlined,
  WarningOutlined,
  InboxOutlined,
  ThunderboltOutlined,
  RobotOutlined,
  ScheduleOutlined,
  ApartmentOutlined,
  TeamOutlined,
  HddOutlined,
  ClusterOutlined,
  CheckSquareOutlined,
  LogoutOutlined,
  UserOutlined,
  SettingOutlined,
  SwapOutlined,
} from '@ant-design/icons'
import { getStoredUser, logout } from '../services/auth'
import { isTestMode } from '../services/testSwitch'
import RoleSwitcher from './RoleSwitcher'

const { Header, Sider, Content } = AntLayout

// 菜单图标映射
const menuIcons: Record<string, React.ReactElement> = {
  '/dashboard': <DashboardOutlined />,
  '/work-orders': <FileTextOutlined />,
  '/production-report': <EditOutlined />,
  '/base-data': <ApartmentOutlined />,
  '/plans': <ScheduleOutlined />,
  '/inventory': <InboxOutlined />,
  '/warehouses': <HddOutlined />,
  '/inspections': <SafetyOutlined />,
  '/defects': <WarningOutlined />,
  '/skill-matrix': <TeamOutlined />,
  '/simulation': <ThunderboltOutlined />,
  '/tms/approval': <CheckSquareOutlined />,
  '/tms/distribution': <ThunderboltOutlined />,
  '/tms/agent': <RobotOutlined />,
  '/ai': <RobotOutlined />,
  '/users': <UserOutlined />,
  '/roles': <SettingOutlined />,
}

// 将后端 menu_items 转换为 Ant Design Menu 格式
function convertMenuItems(items: any[]): any[] {
  if (!items || !items.length) return []

  return items.map((item: any) => {
    if (item.children && item.children.length > 0) {
      return {
        key: item.key,
        icon: menuIcons[item.key] || <ClusterOutlined />,
        label: item.label,
        children: convertMenuItems(item.children),
      }
    }
    return {
      key: item.key,
      icon: menuIcons[item.key] || <DashboardOutlined />,
      label: <Link to={item.key}>{item.label}</Link>,
    }
  })
}

const Layout: React.FC = () => {
  const location = useLocation()
  const navigate = useNavigate()
  const user = getStoredUser()
  const displayName = user?.full_name || user?.username || '用户'
  const avatarChar = displayName.charAt(0).toUpperCase()
  const [switcherOpen, setSwitcherOpen] = useState(false)
  const testMode = isTestMode()

  // 根据用户权限动态生成菜单
  const menuItems = useMemo(() => {
    if (!user) return []
    return convertMenuItems(user.menu_items || [])
  }, [user])

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  const userMenu = {
    items: [
      {
        key: 'info',
        label: (
          <div style={{ padding: '4px 0' }}>
            <div style={{ fontWeight: 600 }}>{displayName}</div>
            <div style={{ fontSize: 12, color: '#999' }}>
              {user?.role ? `${user.role}` : '-'}
            </div>
          </div>
        ),
        disabled: true,
      },
      { type: 'divider' as const },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: handleLogout },
    ],
  }

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#001529', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Space size={12}>
          <Avatar shape="square" style={{ background: '#1890ff' }} icon={<ClusterOutlined />} />
          <span style={{ fontSize: 18, fontWeight: 700, color: '#fff', letterSpacing: 1 }}>EngHub MES</span>
          <Tag color="blue" style={{ marginLeft: 4 }}>v1.2</Tag>
          {testMode && <Tag color="red">测试模式</Tag>}
        </Space>
        <Space size={16}>
          {user?.factory_id && <Tag color="geekblue">厂区 {user.factory_id}</Tag>}
          <Link to="/ai" style={{ color: 'rgba(255,255,255,0.85)' }}><RobotOutlined /> AI 助手</Link>
          
          {/* 测试模式：角色切换按钮 */}
          {testMode && (
            <Button
              type="primary"
              ghost
              icon={<SwapOutlined />}
              onClick={() => setSwitcherOpen(true)}
              style={{ color: '#fff', borderColor: 'rgba(255,255,255,0.5)' }}
            >
              切换角色
            </Button>
          )}

          <Dropdown menu={userMenu} placement="bottomRight">
            <Space style={{ cursor: 'pointer', color: 'rgba(255,255,255,0.9)' }}>
              <Avatar style={{ background: '#52c41a' }} icon={!avatarChar ? <UserOutlined /> : undefined}>{avatarChar}</Avatar>
              <span>{displayName}</span>
            </Space>
          </Dropdown>
        </Space>
      </Header>
      <AntLayout>
        <Sider width={220} theme="light" style={{ borderRight: '1px solid #f0f0f0' }}>
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            defaultOpenKeys={menuItems.filter((i: any) => i.children).map((i: any) => i.key)}
            style={{ height: '100%', borderRight: 0, paddingTop: 8 }}
            items={menuItems}
          />
        </Sider>
        <Content style={{ padding: 24, background: '#f0f2f5' }}>
          <div style={{ background: 'transparent' }}>
            <Outlet />
          </div>
        </Content>
      </AntLayout>

      {/* 角色切换抽屉 */}
      <RoleSwitcher
        open={switcherOpen}
        onClose={() => setSwitcherOpen(false)}
        currentRole={user?.role || ''}
      />
    </AntLayout>
  )
}

export default Layout
