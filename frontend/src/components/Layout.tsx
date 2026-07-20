import React from 'react'
import { Outlet, Link, useLocation } from 'react-router-dom'
import { Layout as AntLayout, Menu, Badge, Avatar, Space, Tag } from 'antd'
import {
  AuditOutlined,
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
} from '@ant-design/icons'

const { Header, Sider, Content } = AntLayout

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: <Link to="/dashboard">生产看板</Link> },
  {
    key: 'g-mfg', icon: <ClusterOutlined />, label: '生产制造',
    children: [
      { key: '/work-orders', icon: <FileTextOutlined />, label: <Link to="/work-orders">工单管理</Link> },
      { key: '/production-report', icon: <EditOutlined />, label: <Link to="/production-report">生产报工</Link> },
      { key: '/base-data', icon: <ApartmentOutlined />, label: <Link to="/base-data">工位/工艺/设备</Link> },
    ],
  },
  {
    key: 'g-plan', icon: <ScheduleOutlined />, label: '计划物料',
    children: [
      { key: '/plans', icon: <ScheduleOutlined />, label: <Link to="/plans">生产计划</Link> },
      { key: '/inventory', icon: <InboxOutlined />, label: <Link to="/inventory">库存管理</Link> },
      { key: '/warehouses', icon: <HddOutlined />, label: <Link to="/warehouses">仓库管理</Link> },
    ],
  },
  {
    key: 'g-qms', icon: <SafetyOutlined />, label: '质量管理',
    children: [
      { key: '/inspections', icon: <SafetyOutlined />, label: <Link to="/inspections">检验管理</Link> },
      { key: '/defects', icon: <WarningOutlined />, label: <Link to="/defects"><Badge count={5} size="small" offset={[8, 0]}>不良品</Badge></Link> },
    ],
  },
  {
    key: 'g-hr', icon: <TeamOutlined />, label: '人员',
    children: [
      { key: '/skill-matrix', icon: <TeamOutlined />, label: <Link to="/skill-matrix">员工技能矩阵</Link> },
    ],
  },
  {
    key: 'g-sim', icon: <ThunderboltOutlined />, label: '合规仿真',
    children: [
      { key: '/sim-erp/run', icon: <ThunderboltOutlined />, label: <Link to="/sim-erp/run">仿真引擎</Link> },
      { key: '/sim-erp/audits', icon: <AuditOutlined />, label: <Link to="/sim-erp/audits">合规审计</Link> },
    ],
  },
  {
    key: 'g-tms', icon: <CheckSquareOutlined />, label: 'TMS 任务管理',
    children: [
      { key: '/tms/approval', icon: <CheckSquareOutlined />, label: <Link to="/tms/approval"><Badge count={24} size="small" offset={[8, 0]}>审批中心</Badge></Link> },
      { key: '/tms/distribution', icon: <ThunderboltOutlined />, label: <Link to="/tms/distribution">分发看板</Link> },
      { key: '/tms/agent', icon: <RobotOutlined />, label: <Link to="/tms/agent">Agent 控制台</Link> },
    ],
  },
  { key: '/ai', icon: <RobotOutlined />, label: <Link to="/ai">AI 助手</Link> },
]

const Layout: React.FC = () => {
  const location = useLocation()

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#001529', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Space size={12}>
          <Avatar shape="square" style={{ background: '#1890ff' }} icon={<ClusterOutlined />} />
          <span style={{ fontSize: 18, fontWeight: 700, color: '#fff', letterSpacing: 1 }}>EngHub MES</span>
          <Tag color="blue" style={{ marginLeft: 4 }}>v1.1</Tag>
        </Space>
        <Space>
          <Link to="/ai" style={{ color: 'rgba(255,255,255,0.85)' }}><RobotOutlined /> AI 助手</Link>
          <Avatar style={{ background: '#52c41a' }}>管</Avatar>
        </Space>
      </Header>
      <AntLayout>
        <Sider width={220} theme="light" style={{ borderRight: '1px solid #f0f0f0' }}>
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            defaultOpenKeys={['g-mfg', 'g-plan', 'g-qms', 'g-hr', 'g-sim', 'g-tms']}
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
    </AntLayout>
  )
}

export default Layout
