/**
 * 个人设置页面
 * - 基本信息展示（用户名、姓名、角色、邮箱）
 * - 修改密码
 * - 界面偏好（语言、主题）
 */
import React, { useState } from 'react'
import { Card, Form, Input, Button, Avatar, Descriptions, Tag, Divider, message, Row, Col, Select, Switch } from 'antd'
import { UserOutlined, LockOutlined, SettingOutlined, SafetyOutlined } from '@ant-design/icons'
import { getStoredUser } from '../../services/auth'
import api from '../../services/api'

const PersonalSettings: React.FC = () => {
  const user = getStoredUser()
  const [pwdForm] = Form.useForm()
  const [changingPwd, setChangingPwd] = useState(false)

  const handleChangePassword = async (values: any) => {
    if (values.new_password !== values.confirm_password) {
      message.error('两次输入的密码不一致')
      return
    }
    setChangingPwd(true)
    try {
      await api.post('/api/v1/auth/change-password', {
        old_password: values.old_password,
        new_password: values.new_password,
      })
      message.success('密码修改成功，下次登录请使用新密码')
      pwdForm.resetFields()
    } catch (e: any) {
      message.error('修改失败: ' + (e?.response?.data?.detail || e?.message || '请检查旧密码是否正确'))
    } finally {
      setChangingPwd(false)
    }
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto' }}>
      <Row gutter={[16, 16]}>
        {/* 基本信息 */}
        <Col span={24}>
          <Card title={<><UserOutlined /> 基本信息</>} size="small">
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
              <Avatar size={64} style={{ background: '#1890ff', fontSize: 24 }}>
                {(user?.full_name || user?.username || '?')[0]?.toUpperCase()}
              </Avatar>
              <div>
                <div style={{ fontSize: 18, fontWeight: 600 }}>{user?.full_name || user?.username}</div>
                <div style={{ color: '#999' }}>@{user?.username}</div>
              </div>
            </div>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="用户名">{user?.username || '-'}</Descriptions.Item>
              <Descriptions.Item label="姓名">{user?.full_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="角色">
                <Tag color="blue">{user?.role || '-'}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="邮箱">{user?.email || '-'}</Descriptions.Item>
              <Descriptions.Item label="厂区">{user?.factory_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={user?.is_active !== false ? 'green' : 'red'}>
                  {user?.is_active !== false ? '正常' : '停用'}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        {/* 修改密码 */}
        <Col span={24} md={12}>
          <Card title={<><LockOutlined /> 修改密码</>} size="small">
            <Form form={pwdForm} layout="vertical" onFinish={handleChangePassword}>
              <Form.Item name="old_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
                <Input.Password prefix={<LockOutlined />} placeholder="输入当前密码" />
              </Form.Item>
              <Form.Item name="new_password" label="新密码" rules={[{ required: true, min: 6, message: '至少6位' }]}>
                <Input.Password prefix={<SafetyOutlined />} placeholder="至少6位新密码" />
              </Form.Item>
              <Form.Item name="confirm_password" label="确认新密码" rules={[{ required: true, message: '请再次输入' }]}>
                <Input.Password prefix={<SafetyOutlined />} placeholder="再次输入新密码" />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={changingPwd} block>
                确认修改
              </Button>
            </Form>
          </Card>
        </Col>

        {/* 界面偏好 */}
        <Col span={24} md={12}>
          <Card title={<><SettingOutlined /> 界面偏好</>} size="small">
            <Form layout="vertical">
              <Form.Item label="界面语言">
                <Select defaultValue="zh-CN" options={[
                  { value: 'zh-CN', label: '简体中文' },
                  { value: 'zh-TW', label: '繁體中文' },
                  { value: 'en', label: 'English' },
                ]} />
              </Form.Item>
              <Form.Item label="消息通知">
                <Switch defaultChecked checkedChildren="开" unCheckedChildren="关" />
              </Form.Item>
              <Form.Item label="AI 助手自动弹出">
                <Switch defaultChecked={false} checkedChildren="开" unCheckedChildren="关" />
              </Form.Item>
              <Divider style={{ margin: '12px 0' }} />
              <div style={{ color: '#999', fontSize: 12 }}>
                偏好设置保存在本地浏览器，清除缓存后需重新配置。
              </div>
            </Form>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default PersonalSettings
