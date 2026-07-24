import React, { useState, useMemo, useEffect } from 'react'
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
  DatabaseOutlined,
  LogoutOutlined,
  UserOutlined,
  SettingOutlined,
  SwapOutlined,
} from '@ant-design/icons'
import { getStoredUser, fetchMe, logout } from '../services/auth'
import { isTestMode } from '../services/testSwitch'
import RoleSwitcher from './RoleSwitcher'
import AIAssistantWidget from './AIAssistantWidget'
import GlobalSearch from './GlobalSearch'

const { Header, Sider, Content } = AntLayout

// 菜单图标映射
const menuIcons: Record<string, React.ReactElement> = {
  'g-dashboard': <DashboardOutlined />,
  '/dashboard': <DashboardOutlined />,
  '/production-data': <DatabaseOutlined />,
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
  '/tms': <ThunderboltOutlined />,
  '/quick-request': <EditOutlined />,
  '/work-order-templates': <FileTextOutlined />,
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
  const [user, setUser] = useState(getStoredUser())
  const displayName = user?.full_name || user?.username || '用户'
  const avatarChar = displayName.charAt(0).toUpperCase()
  const [switcherOpen, setSwitcherOpen] = useState(false)
  const testMode = isTestMode()

  // 每次进入布局时静默刷新用户信息（含 menu_items），避免缓存过旧导致菜单缺失
  useEffect(() => {
    let cancelled = false
    fetchMe()
      .then((fresh) => { if (!cancelled) setUser(fresh) })
      .catch(() => { /* token 失效等情况沿用缓存，由 RequireAuth 处理跳转 */ })
    return () => { cancelled = true }
  }, [])

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
      { key: 'settings', icon: <SettingOutlined />, label: '系统设置', onClick: () => navigate('/settings') },
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
          {/* 全站搜索 */}
          <GlobalSearch />
          {user?.factory_id && <Tag color="geekblue">厂区 {user.factory_id}</Tag>}
          
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

      {/* 全局 AI 助手浮窗 */}
      <AIAssistantWidget />
    </AntLayout>
  )
}

export default Layout
