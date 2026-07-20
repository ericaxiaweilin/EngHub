import React, { useState, useEffect } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { Form, Input, Button, Card, Typography, message, Avatar, Alert } from 'antd'
import { UserOutlined, LockOutlined, MailOutlined, AppstoreOutlined, ClusterOutlined } from '@ant-design/icons'
import { register, login, fetchMe } from '../../services/auth'

const { Title, Text } = Typography

interface RegisterForm {
  username: string
  email: string
  password: string
  full_name?: string
  factory_id?: string
  invitation_token?: string
}

const Register: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm<RegisterForm>()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const invitedToken = params.get('token') || ''

  useEffect(() => {
    if (invitedToken) form.setFieldsValue({ invitation_token: invitedToken })
  }, [invitedToken, form])

  const onFinish = async (values: RegisterForm) => {
    setLoading(true)
    try {
      await register({
        username: values.username.trim(),
        email: values.email.trim(),
        password: values.password,
        full_name: values.full_name?.trim() || undefined,
        factory_id: values.factory_id?.trim() || undefined,
        invitation_token: values.invitation_token?.trim() || undefined,
      })
      message.success('注册成功，正在登录…')
      // 注册后自动登录
      try {
        await login(values.username.trim(), values.password)
        await fetchMe()
        navigate('/dashboard', { replace: true })
      } catch {
        navigate('/login', { replace: true })
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '注册失败'
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
        style={{ width: 400, boxShadow: '0 12px 32px rgba(0,0,0,0.25)', borderRadius: 12 }}
        styles={{ body: { padding: '32px 32px 24px' } }}
      >
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <Avatar size={56} icon={<AppstoreOutlined />} style={{ background: '#1890ff' }} />
          <Title level={3} style={{ margin: '16px 0 4px' }}>
            EngHub MES
          </Title>
          <Text type="secondary">制造执行系统 · 注册</Text>
        </div>

        {invitedToken ? (
          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 16 }}
            message="您收到一个邀请"
            description="请填写邮箱（需与邀请邮箱一致）完成加入，厂区与角色由邀请决定。"
          />
        ) : (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="创建新厂区(租户)"
            description="填写一个尚不存在的厂区编号，您将成为该厂区的管理员。加入已有厂区需邀请码。"
          />
        )}

        <Form form={form} name="register" onFinish={onFinish} size="large" layout="vertical" autoComplete="off">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" allowClear />
          </Form.Item>
          <Form.Item name="email" rules={[{ required: true, type: 'email', message: '请输入有效邮箱' }]}>
            <Input prefix={<MailOutlined />} placeholder="邮箱" allowClear />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, min: 6, message: '密码至少 6 位' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item name="full_name">
            <Input prefix={<UserOutlined />} placeholder="姓名（可选）" allowClear />
          </Form.Item>
          {!invitedToken && (
            <Form.Item name="factory_id" rules={[{ required: true, message: '请输入厂区编号' }]}>
              <Input prefix={<ClusterOutlined />} placeholder="厂区编号，如 F002" allowClear />
            </Form.Item>
          )}
          <Form.Item name="invitation_token" hidden={!invitedToken}>
            <Input placeholder="邀请码" allowClear />
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" block loading={loading}>
              注 册
            </Button>
          </Form.Item>
        </Form>

        <Text type="secondary" style={{ fontSize: 12, display: 'block', textAlign: 'center' }}>
          已有账号？<Link to="/login">去登录</Link>
        </Text>
      </Card>
    </div>
  )
}

export default Register
