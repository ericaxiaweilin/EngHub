import React, { useEffect, useRef, useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Form, Input, Button, Card, Typography, message, Avatar, Checkbox, Alert, Tag, Modal } from 'antd'
import { UserOutlined, LockOutlined, AppstoreOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { login, fetchMe, loadCredentials, clearCredentials, resetPassword, SESSION_HOURS } from '../../services/auth'

const { Title, Text } = Typography

const Login: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()
  const navigate = useNavigate()
  const location = useLocation() as any
  const from = location.state?.from || '/'

  // 忘记密码弹窗
  const [resetOpen, setResetOpen] = useState(false)
  const [resetLoading, setResetLoading] = useState(false)
  const [resetForm] = Form.useForm()

  // 会话过期标记（由路由守卫/401 拦截器设置）
  const [expired] = useState(() => sessionStorage.getItem('session_expired') === '1')

  // 标记当前密码是否来自「记住密码」自动填充。
  // 自动填充的密码在服务端重置后会过期，且掩码框用户看不见，需在失败时特殊处理
  const autofilledPwd = useRef(false)

  useEffect(() => {
    // 自动填充已保存的凭据
    const saved = loadCredentials()
    if (saved) {
      form.setFieldsValue({ username: saved.username, password: saved.password, remember: true })
      autofilledPwd.current = true
    }
    // 清除过期标记（只展示一次）
    sessionStorage.removeItem('session_expired')
  }, [form])

  const onFinish = async (values: { username: string; password: string; remember?: boolean }) => {
    setLoading(true)
    try {
      await login(values.username.trim(), values.password.trim(), values.remember)
      try {
        await fetchMe()
      } catch {
        // /me 失败不阻断登录，令牌已获取
      }
      message.success('登录成功')
      navigate(from, { replace: true })
    } catch (err: any) {
      if (autofilledPwd.current) {
        // 提交的密码来自「记住密码」自动填充：服务端重置密码后旧密码已失效，
        // 而掩码框让用户无法察觉，只会看到莫名其妙的「用户名或密码错误」。
        // 这里清除失效凭据和密码框，并明确提示重新输入，避免反复踩坑
        clearCredentials()
        form.setFieldsValue({ password: '' })
        autofilledPwd.current = false
        message.error('自动填充的密码可能已失效，请重新输入密码')
      } else {
        const detail = err?.response?.data?.detail || err?.message || '登录失败'
        message.error(detail)
      }
    } finally {
      setLoading(false)
    }
  }

  const onReset = async (values: { username: string; newPassword: string; confirm: string }) => {
    setResetLoading(true)
    try {
      await resetPassword(values.username.trim(), values.newPassword.trim())
      message.success('密码已重置，请用新密码登录')
      clearCredentials()
      form.setFieldsValue({ username: values.username.trim(), password: '' })
      setResetOpen(false)
      resetForm.resetFields()
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '重置失败'
      message.error(typeof detail === 'string' ? detail : '重置失败')
    } finally {
      setResetLoading(false)
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
            EngHub
          </Title>
          <Text type="secondary">智能制造执行系统 · 登录</Text>
        </div>

        {expired && (
          <Alert
            type="warning"
            showIcon
            icon={<ClockCircleOutlined />}
            message={`登录状态已超过 ${SESSION_HOURS} 小时，请重新登录`}
            style={{ marginBottom: 16 }}
          />
        )}

        <Form
          form={form}
          name="login"
          onFinish={onFinish}
          size="large"
          autoComplete="off"
          initialValues={{ remember: true }}
        >
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" allowClear />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="密码"
              onChange={() => {
                // 用户手动修改过密码后，不再视为自动填充
                autofilledPwd.current = false
              }}
            />
          </Form.Item>
          <Form.Item name="remember" valuePropName="checked" style={{ marginBottom: 12 }}>
            <Checkbox>记住密码（本机自动填充）</Checkbox>
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" block loading={loading}>
              登 录
            </Button>
          </Form.Item>
          <div style={{ textAlign: 'right', marginBottom: 8 }}>
            <Button type="link" size="small" style={{ padding: 0 }} onClick={() => {
              const uname = form.getFieldValue('username')
              resetForm.setFieldsValue({ username: uname || '' })
              setResetOpen(true)
            }}>忘记密码？</Button>
          </div>
        </Form>

        <div style={{ textAlign: 'center' }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block' }}>
            登录状态保持 {SESSION_HOURS} 小时，届时需重新登录
          </Text>
          <div style={{ marginTop: 8 }}>
            <Tag color="blue" style={{ marginRight: 4 }}>厂长</Tag>
            <Tag color="green" style={{ marginRight: 4 }}>经理</Tag>
            <Tag color="orange" style={{ marginRight: 4 }}>课长</Tag>
            <Tag color="purple" style={{ marginRight: 4 }}>线长</Tag>
            <Tag color="cyan" style={{ marginRight: 4 }}>工程师</Tag>
            <Tag color="default">操作员</Tag>
          </div>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
            默认账号 admin，如无法登录请联系管理员初始化
          </Text>
        </div>
        <Modal
          title="重置密码"
          open={resetOpen}
          onCancel={() => setResetOpen(false)}
          onOk={() => resetForm.submit()}
          confirmLoading={resetLoading}
          okText="确认重置"
          cancelText="取消"
          destroyOnClose
        >
          <Alert type="info" showIcon style={{ marginBottom: 16 }}
            message="输入用户名和新密码即可直接重置（内网自助）。" />
          <Form form={resetForm} layout="vertical" onFinish={onReset} autoComplete="off">
            <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input prefix={<UserOutlined />} placeholder="用户名" allowClear />
            </Form.Item>
            <Form.Item name="newPassword" label="新密码" rules={[{ required: true, message: '请输入新密码' }, { min: 6, message: '新密码至少 6 位' }]}>
              <Input.Password prefix={<LockOutlined />} placeholder="新密码（至少 6 位）" />
            </Form.Item>
            <Form.Item name="confirm" label="确认新密码" dependencies={['newPassword']}
              rules={[{ required: true, message: '请再次输入新密码' }, ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('newPassword') === value) return Promise.resolve()
                  return Promise.reject(new Error('两次输入的密码不一致'))
                },
              })]}>
              <Input.Password prefix={<LockOutlined />} placeholder="再次输入新密码" />
            </Form.Item>
          </Form>
        </Modal>
      </Card>
    </div>
  )
}

export default Login
