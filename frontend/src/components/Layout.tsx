import React, { useState } from 'react'
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { Layout as AntLayout, Menu, Badge, Avatar, Space, Tag, Dropdown, Modal, Form, Input, Select, Button, Typography, message } from 'antd'
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
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { getStoredUser, logout, createInvitation } from '../services/auth'

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
  const navigate = useNavigate()
  const user = getStoredUser()
  const displayName = user?.full_name || user?.username || '用户'
  const avatarChar = displayName.charAt(0).toUpperCase()
  const canInvite = user?.role === 'admin' || user?.role === 'manager'

  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteLink, setInviteLink] = useState('')
  const [inviteLoading, setInviteLoading] = useState(false)
  const [inviteForm] = Form.useForm<{ email: string; role: string }>()

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  const openInvite = () => {
    setInviteLink('')
    inviteForm.resetFields()
    setInviteOpen(true)
  }

  const submitInvite = async () => {
    try {
      const values = await inviteForm.validateFields()
      setInviteLoading(true)
      const inv = await createInvitation(values.email.trim(), values.role)
      const link = `${window.location.origin}/register?token=${inv.token}`
      setInviteLink(link)
      message.success('邀请已生成')
    } catch (err: any) {
      if (err?.response) {
        message.error(err.response.data?.detail || '生成邀请失败')
      }
    } finally {
      setInviteLoading(false)
    }
  }

  const userMenu = {
    items: [
      {
        key: 'info',
        label: (
          <div style={{ padding: '4px 0' }}>
            <div style={{ fontWeight: 600 }}>{displayName}</div>
            <div style={{ fontSize: 12, color: '#999' }}>{user?.role || '-'}</div>
          </div>
        ),
        disabled: true,
      },
      { type: 'divider' as const },
      ...(canInvite
        ? [{ key: 'invite', icon: <TeamOutlined />, label: '邀请成员', onClick: openInvite }]
        : []),
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: handleLogout },
    ],
  }

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Header style={{ background: '#001529', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Space size={12}>
          <Avatar shape="square" style={{ background: '#1890ff' }} icon={<ClusterOutlined />} />
          <span style={{ fontSize: 18, fontWeight: 700, color: '#fff', letterSpacing: 1 }}>EngHub MES</span>
          <Tag color="blue" style={{ marginLeft: 4 }}>v1.1</Tag>
        </Space>
        <Space size={16}>
          {user?.factory_id && <Tag color="geekblue">厂区 {user.factory_id}</Tag>}
          <Link to="/ai" style={{ color: 'rgba(255,255,255,0.85)' }}><RobotOutlined /> AI 助手</Link>
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

      <Modal
        title="邀请成员加入厂区"
        open={inviteOpen}
        onCancel={() => setInviteOpen(false)}
        footer={[
          <Button key="close" onClick={() => setInviteOpen(false)}>关闭</Button>,
          <Button key="submit" type="primary" loading={inviteLoading} onClick={submitInvite}>生成邀请链接</Button>,
        ]}
        destroyOnClose
      >
        <Form form={inviteForm} layout="vertical" initialValues={{ role: 'operator' }}>
          <Form.Item name="email" label="受邀人邮箱" rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}>
            <Input placeholder="member@example.com" allowClear />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select
              options={[
                { value: 'operator', label: '操作员 operator' },
                { value: 'manager', label: '主管 manager' },
                { value: 'admin', label: '管理员 admin' },
              ]}
            />
          </Form.Item>
        </Form>
        {inviteLink && (
          <div style={{ marginTop: 8 }}>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>将下方链接发送给受邀人，其打开后即可完成注册并加入本厂区：</Typography.Text>
            <Input.TextArea value={inviteLink} readOnly autoSize style={{ marginTop: 6 }} onFocus={(e) => e.target.select()} />
            <Button size="small" style={{ marginTop: 6 }} onClick={() => { navigator.clipboard?.writeText(inviteLink); message.success('已复制') }}>复制链接</Button>
          </div>
        )}
      </Modal>
    </AntLayout>
  )
}

export default Layout
