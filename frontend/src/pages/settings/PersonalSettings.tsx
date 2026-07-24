/**
 * 个人设置页面
 * - 基本信息展示（用户名、姓名、角色、邮箱）
 * - 修改密码
 * - 界面偏好（语言、主题）
 */
import React, { useState } from 'react'
import { Card, Form, Input, Button, Avatar, Descriptions, Tag, Divider, message, Row, Col, Select, Switch } from 'antd'
import { UserOutlined, LockOutlined, SettingOutlined, SafetyOutlined, GlobalOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { getStoredUser } from '../../services/auth'
import { APP_LOCALES, getStoredLocale, setStoredLocale } from '../../services/locale'
import api from '../../services/api'

const PersonalSettings: React.FC = () => {
  const { t, i18n } = useTranslation()
  const user = getStoredUser()
  const [pwdForm] = Form.useForm()
  const [changingPwd, setChangingPwd] = useState(false)

  const handleChangePassword = async (values: any) => {
    if (values.new_password !== values.confirm_password) {
      message.error(t('settings.pwdMismatch'))
      return
    }
    setChangingPwd(true)
    try {
      await api.post('/api/v1/auth/change-password', {
        old_password: values.old_password,
        new_password: values.new_password,
      })
      message.success(t('settings.pwdSuccess'))
      pwdForm.resetFields()
    } catch (e: any) {
      message.error(`${t('settings.pwdFail')}: ` + (e?.response?.data?.detail || e?.message || ''))
    } finally {
      setChangingPwd(false)
    }
  }

  return (
    <div>
      <Row gutter={[16, 16]}>
        {/* 基本信息 */}
        <Col span={24}>
          <Card title={<><UserOutlined /> {t('settings.basicInfo')}</>} size="small">
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
              <Descriptions.Item label={t('settings.username')}>{user?.username || '-'}</Descriptions.Item>
              <Descriptions.Item label={t('settings.fullName')}>{user?.full_name || '-'}</Descriptions.Item>
              <Descriptions.Item label={t('settings.role')}>
                <Tag color="blue">{user?.role || '-'}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label={t('settings.email')}>{user?.email || '-'}</Descriptions.Item>
              <Descriptions.Item label={t('settings.factory')}>{user?.factory_id || '-'}</Descriptions.Item>
              <Descriptions.Item label={t('settings.status')}>
                <Tag color={user?.is_active !== false ? 'green' : 'red'}>
                  {user?.is_active !== false ? t('settings.active') : t('settings.disabled')}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        {/* 修改密码 */}
        <Col span={24} md={12}>
          <Card title={<><LockOutlined /> {t('settings.changePassword')}</>} size="small">
            <Form form={pwdForm} layout="vertical" onFinish={handleChangePassword}>
              <Form.Item name="old_password" label={t('settings.currentPassword')} rules={[{ required: true, message: t('settings.currentPassword') }]}>
                <Input.Password prefix={<LockOutlined />} placeholder={t('settings.currentPassword')} />
              </Form.Item>
              <Form.Item name="new_password" label={t('settings.newPassword')} rules={[{ required: true, min: 6, message: '≥6' }]}>
                <Input.Password prefix={<SafetyOutlined />} placeholder={t('settings.newPassword')} />
              </Form.Item>
              <Form.Item name="confirm_password" label={t('settings.confirmPassword')} rules={[{ required: true, message: t('settings.confirmPassword') }]}>
                <Input.Password prefix={<SafetyOutlined />} placeholder={t('settings.confirmPassword')} />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={changingPwd} block>
                {t('settings.confirmChange')}
              </Button>
            </Form>
          </Card>
        </Col>

        {/* 界面偏好 */}
        <Col span={24} md={12}>
          <Card title={<><SettingOutlined /> {t('settings.interfacePrefs')}</>} size="small">
            <Form layout="vertical">
              <Form.Item label={<span><GlobalOutlined /> {t('settings.language')}</span>}>
                <Select
                  value={getStoredLocale()}
                  onChange={(v) => { setStoredLocale(v); message.success(i18n.t('settings.langSwitched', { lng: v })) }}
                  options={APP_LOCALES.map((l) => ({ value: l.value, label: l.label }))}
                />
              </Form.Item>
              <Form.Item label={t('settings.notifications')}>
                <Switch defaultChecked checkedChildren={t('settings.on')} unCheckedChildren={t('settings.off')} />
              </Form.Item>
              <Form.Item label={t('settings.aiPopup')}>
                <Switch defaultChecked={false} checkedChildren={t('settings.on')} unCheckedChildren={t('settings.off')} />
              </Form.Item>
              <Divider style={{ margin: '12px 0' }} />
              <div style={{ color: '#999', fontSize: 12 }}>
                {t('settings.prefsNote')}
              </div>
            </Form>
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default PersonalSettings
