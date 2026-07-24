import React, { useState, useMemo, useEffect } from 'react'
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { Layout as AntLayout, Menu, Avatar, Space, Tag, Dropdown, Button } from 'antd'
import { useTranslation } from 'react-i18next'
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
  ToolOutlined,
  AppstoreOutlined,
  FieldTimeOutlined,
  AlertOutlined,
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
  'g-mes': <AppstoreOutlined />,
  'g-qms': <SafetyOutlined />,
  'g-wms': <InboxOutlined />,
  'g-equipment': <ToolOutlined />,
  'g-aps': <FieldTimeOutlined />,
  'g-collab': <ThunderboltOutlined />,
  'g-hr': <TeamOutlined />,
  '/dashboard': <DashboardOutlined />,
  '/production-data': <DatabaseOutlined />,
  '/work-orders': <FileTextOutlined />,
  '/process-queue': <ApartmentOutlined />,
  '/production-report': <EditOutlined />,
  '/base-data': <ApartmentOutlined />,
  '/routing-templates': <FileTextOutlined />,
  '/plans': <ScheduleOutlined />,
  '/scheduling': <FieldTimeOutlined />,
  '/inventory': <InboxOutlined />,
  '/warehouses': <HddOutlined />,
  '/wms-center': <InboxOutlined />,
  '/inspections': <SafetyOutlined />,
  '/defects': <WarningOutlined />,
  '/quality-center': <SafetyOutlined />,
  '/equipment-center': <ToolOutlined />,
  '/skill-matrix': <TeamOutlined />,
  '/simulation': <ThunderboltOutlined />,
  '/tms/approval': <CheckSquareOutlined />,
  '/tms/distribution': <ThunderboltOutlined />,
  '/tms/agent': <RobotOutlined />,
  '/quick-request': <EditOutlined />,
  '/andon': <AlertOutlined />,
  '/my-tasks': <CheckSquareOutlined />,
  '/alert-intelligence': <AlertOutlined />,
  '/settings': <SettingOutlined />,
}

// 将后端 menu_items 转换为 Ant Design Menu 格式（label 优先取 i18n 翻译，缺失时回退后端原文）
function convertMenuItems(items: any[], t: (key: string, opts?: any) => string): any[] {
  if (!items || !items.length) return []

  return items.map((item: any) => {
    const label = t(`menu.${item.key}`, { defaultValue: item.label })
    if (item.children && item.children.length > 0) {
      return {
        key: item.key,
        icon: menuIcons[item.key] || <ClusterOutlined />,
        label,
        children: convertMenuItems(item.children, t),
      }
    }
    return {
      key: item.key,
      icon: menuIcons[item.key] || <DashboardOutlined />,
      label: <Link to={item.key}>{label}</Link>,
    }
  })
}

// 路由前缀 → 菜单分组 key 映射（用于侧边栏只显示当前模块）
const ROUTE_MODULE_MAP: [string, string][] = [
  ['/work-orders', 'g-mes'], ['/process-queue', 'g-mes'], ['/my-tasks', 'g-mes'],
  ['/routing-templates', 'g-mes'], ['/production-report', 'g-mes'], ['/base-data', 'g-mes'],
  ['/plant-floor', 'g-mes'], ['/report-terminal', 'g-mes'], ['/production-live', 'g-mes'],
  ['/report-center', 'g-mes'], ['/alert-intelligence', 'g-mes'],
  ['/inspections', 'g-qms'], ['/defects', 'g-qms'], ['/quality-center', 'g-qms'],
  ['/quality-goals', 'g-qms'], ['/inspection-terminal', 'g-qms'], ['/spc-dashboard', 'g-qms'],
  ['/inventory', 'g-wms'], ['/warehouses', 'g-wms'], ['/wms-center', 'g-wms'],
  ['/wms-terminal', 'g-wms'], ['/stock-alerts', 'g-wms'],
  ['/equipment-center', 'g-equipment'], ['/equipment/', 'g-equipment'],
  ['/orders', 'g-aps'], ['/plans', 'g-aps'], ['/scheduling', 'g-aps'],
  ['/andon', 'g-collab'], ['/tms/', 'g-collab'], ['/quick-request', 'g-collab'],
  ['/war-room', 'g-collab'], ['/work-order-templates', 'g-collab'],
  ['/simulation', '/simulation'], ['/sim-erp', '/simulation'],
  ['/skill-matrix', 'g-hr'],
  ['/dashboard', 'g-mes'], ['/production-data', 'g-mes'],
  ['/settings', '/settings'],
]

function getActiveModule(pathname: string): string | null {
  for (const [prefix, group] of ROUTE_MODULE_MAP) {
    if (pathname.startsWith(prefix)) return group
  }
  return null
}

const Layout: React.FC = () => {
  const { t } = useTranslation()
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

  // 根据当前路由只显示对应模块的菜单
  const activeModule = getActiveModule(location.pathname)
  const menuItems = useMemo(() => {
    if (!user) return []
    const allItems = convertMenuItems(user.menu_items || [], t)
    if (!activeModule) return []  // 模块选择页不显示侧边栏
    // 找到当前模块分组，将其 children 提升为顶级
    const group = allItems.find((i: any) => i.key === activeModule)
    if (group && group.children) {
      // MES 模块合并看板组
      if (activeModule === 'g-mes') {
        const dashGroup = allItems.find((i: any) => i.key === 'g-dashboard')
        const dashChildren = dashGroup?.children || []
        return [...dashChildren, ...group.children]
      }
      return group.children
    }
    // 非分组类型（如 /simulation, /settings）直接返回
    const single = allItems.find((i: any) => i.key === activeModule)
    return single ? [single] : []
  }, [user, t, activeModule])

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
      { key: 'settings', icon: <SettingOutlined />, label: t('layout.settings'), onClick: () => navigate('/settings') },
      { key: 'logout', icon: <LogoutOutlined />, label: t('layout.logout'), onClick: handleLogout },
    ],
  }

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#001529', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Space size={12} style={{ cursor: 'pointer' }} onClick={() => navigate('/')}>
          <Avatar shape="square" style={{ background: '#1890ff' }} icon={<ClusterOutlined />} />
          <span style={{ fontSize: 18, fontWeight: 700, color: '#fff', letterSpacing: 1 }}>EngHub</span>
          <Tag color="blue" style={{ marginLeft: 4 }}>v1.2</Tag>
          {testMode && <Tag color="red">{t('layout.testMode')}</Tag>}
        </Space>
        <Space size={16}>
          {/* 全站搜索 */}
          <GlobalSearch />
          {user?.factory_id && <Tag color="geekblue">{t('layout.factory')} {user.factory_id}</Tag>}
          
          {/* 测试模式：角色切换按钮 */}
          {testMode && (
            <Button
              type="primary"
              ghost
              icon={<SwapOutlined />}
              onClick={() => setSwitcherOpen(true)}
              style={{ color: '#fff', borderColor: 'rgba(255,255,255,0.5)' }}
            >
              {t('layout.switchRole')}
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
        {menuItems.length > 0 && (
        <Sider width={220} theme="light" style={{ borderRight: '1px solid #f0f0f0' }}>
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            defaultOpenKeys={menuItems.filter((i: any) => i.children).map((i: any) => i.key)}
            style={{ height: '100%', borderRight: 0, paddingTop: 8 }}
            items={menuItems}
          />
        </Sider>
        )}
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

      {/* 全局 AI 助手浮窗（模块选择页不渲染，避免遵住右下角的 RCC 卡片） */}
      {activeModule && <AIAssistantWidget />}
    </AntLayout>
  )
}

export default Layout
