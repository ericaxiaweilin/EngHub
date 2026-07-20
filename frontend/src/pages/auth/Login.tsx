import React, { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Form, Input, Button, Card, Typography, message, Avatar } from 'antd'
import { UserOutlined, LockOutlined, AppstoreOutlined } from '@ant-design/icons'
import { login, fetchMe } from '../../services/auth'

const { Title, Text } = Typography

const Login: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const location = useLocation() as any
  const from = location.state?.from || '/dashboard'

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      await login(values.username.trim(), values.password)
      try {
        await fetchMe()
      } catch {
        // /me 失败不阻断登录，令牌已获取
      }
      message.success('登录成功')
      navigate(from, { replace: true })
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '登录失败'
      message.error(detail)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #001529 0%, #003a70 100%)',
        padding: 16,
      }}
    >
      <Card
        style={{ width: 380, boxShadow: '0 12px 32px rgba(0,0,0,0.25)', borderRadius: 12 }}
        styles={{ body: { padding: '32px 32px 24px' } }}
      >
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <Avatar size={56} icon={<AppstoreOutlined />} style={{ background: '#1890ff' }} />
          <Title level={3} style={{ margin: '16px 0 4px' }}>
            EngHub MES
          </Title>
          <Text type="secondary">制造执行系统 · 登录</Text>
        </div>

        <Form name="login" onFinish={onFinish} size="large" autoComplete="off">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" allowClear />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登 录
            </Button>
          </Form.Item>
        </Form>

        <Text type="secondary" style={{ fontSize: 12, display: 'block', textAlign: 'center' }}>
          默认账号 admin，如无法登录请联系管理员初始化
        </Text>
      </Card>
    </div>
  )
}

export default Login
