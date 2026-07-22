import React, { useState, useEffect } from 'react'
import { Drawer, List, Tag, Button, Spin, message, Space, Divider } from 'antd'
import { SwapOutlined, CheckCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { getAvailableRoles, switchRole } from '../services/testSwitch'

interface RoleItem {
  code: string
  name: string
  position: string
  department: string
  description: string
  permissions: any[]
  data_scope: { type: string }
  is_system: boolean
  sample_users: string[]
}

const POSITION_COLORS: Record<string, string> = {
  factory_manager: 'gold',
  manager: 'red',
  director: 'orange',
  section_chief: 'blue',
  team_leader: 'cyan',
  line_leader: 'purple',
  engineer: 'green',
  specialist: 'default',
  operator: 'default',
}

const DATA_SCOPE_LABELS: Record<string, string> = {
  all: '全厂',
  factory: '工厂级',
  department: '科室级',
  line: '产线级',
  own: '个人级',
}

interface RoleSwitcherProps {
  open: boolean
  onClose: () => void
  currentRole: string
}

const RoleSwitcher: React.FC<RoleSwitcherProps> = ({ open, onClose, currentRole }) => {
  const [roles, setRoles] = useState<RoleItem[]>([])
  const [loading, setLoading] = useState(false)
  const [switching, setSwitching] = useState<string | null>(null)

  useEffect(() => {
    if (open) loadRoles()
  }, [open])

  const loadRoles = async () => {
    setLoading(true)
    try {
      const data = await getAvailableRoles()
      setRoles(data)
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '加载角色列表失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSwitch = async (roleCode: string) => {
    if (roleCode === currentRole) return
    
    setSwitching(roleCode)
    try {
      const result = await switchRole(roleCode)
      message.success(`已切换到 [${result.full_name || roleCode}] (${result.role})`)
      // 刷新页面以更新菜单和路由
      window.location.reload()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '切换失败')
    } finally {
      setSwitching(null)
    }
  }

  const groupedRoles = roles.reduce((acc: Record<string, RoleItem[]>, role) => {
    const group = role.department === 'all' ? '系统' : role.department
    if (!acc[group]) acc[group] = []
    acc[group].push(role)
    return acc
  }, {})

  return (
    <Drawer
      title={
        <Space>
          <SwapOutlined />
          <span>测试模式：角色切换</span>
          <Tag color="red">TEST MODE</Tag>
        </Space>
      }
      placement="right"
      width={420}
      open={open}
      onClose={onClose}
      extra={
        <Button icon={<ReloadOutlined />} onClick={loadRoles} size="small">
          刷新
        </Button>
      }
    >
      <div style={{ marginBottom: 16 }}>
        <p style={{ fontSize: 13, color: '#999' }}>
          💡 当前角色：<Tag color="blue">{currentRole}</Tag>
          <br />
          点击下方角色卡片即可一键切换，无需重新登录。
        </p>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin />
        </div>
      ) : (
        Object.entries(groupedRoles).map(([group, groupRoles]) => (
          <div key={group}>
            <Divider orientation="left" plain>
              {group}
            </Divider>
            <List
              dataSource={groupRoles}
              locale={{ emptyText: '暂无角色' }}
              renderItem={(role) => (
                <List.Item
                  actions={[
                    <Button
                      key="switch"
                      type="primary"
                      size="small"
                      icon={role.code === currentRole ? <CheckCircleOutlined /> : <SwapOutlined />}
                      loading={switching === role.code}
                      disabled={role.code === currentRole}
                      onClick={() => handleSwitch(role.code)}
                    >
                      {role.code === currentRole ? '当前' : '切换'}
                    </Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space>
                        <span style={{ fontWeight: 600 }}>{role.name}</span>
                        <Tag color={POSITION_COLORS[role.position] || 'default'}>
                          {role.position}
                        </Tag>
                        {role.is_system && <Tag color="red">系统</Tag>}
                      </Space>
                    }
                    description={
                      <Space direction="vertical" size={2} style={{ width: '100%' }}>
                        <span style={{ fontSize: 12, color: '#666' }}>{role.description}</span>
                        <Space size={8}>
                          <Tag color="geekblue">{DATA_SCOPE_LABELS[role.data_scope?.type] || role.data_scope?.type}</Tag>
                          <Tag>{role.department}</Tag>
                        </Space>
                        <div style={{ fontSize: 12, color: '#999' }}>
                          权限数: {role.permissions?.length || 0} | 示例用户: {role.sample_users?.join(', ') || '-'}
                        </div>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </div>
        ))
      )}
    </Drawer>
  )
}

export default RoleSwitcher
