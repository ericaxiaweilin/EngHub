/**
 * 系统设置（统一入口）
 * 将原先分散的「个人设置」「码表管理」合并为一个系统设置页，按 Tab 组织：
 * - 个人设置：基本信息 / 修改密码 / 界面偏好（多语言，含越南语）
 * - 码表管理：仅管理员可见（基础数据字典维护）
 */
import React, { useMemo } from 'react'
import { Card, Tabs } from 'antd'
import { SettingOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import PersonalSettings from './PersonalSettings'
import CodeTableSettings from './CodeTableSettings'
import { getStoredUser } from '../../services/auth'

interface SystemSettingsProps {
  /** 默认激活的 Tab（/settings/code-tables 旧路由直达码表管理） */
  defaultTab?: string
}

const SystemSettings: React.FC<SystemSettingsProps> = ({ defaultTab }) => {
  const { t } = useTranslation()
  const user = getStoredUser()
  const isAdmin = user?.role === 'admin' || user?.role === 'super_admin'
  const [searchParams, setSearchParams] = useSearchParams()

  // 优先 URL ?tab= 参数，其次 defaultTab，默认个人设置
  const activeKey = searchParams.get('tab') || defaultTab || 'personal'

  const items = useMemo(() => {
    const list = [
      { key: 'personal', label: t('settings.personalTab'), children: <PersonalSettings /> },
    ]
    if (isAdmin) {
      list.push({ key: 'codetables', label: t('settings.codeTablesTab'), children: <CodeTableSettings /> })
    }
    return list
  }, [isAdmin, t])

  return (
    <Card
      title={<><SettingOutlined /> {t('settings.title')}</>}
      size="small"
      styles={{ body: { paddingTop: 8 } }}
    >
      <Tabs
        activeKey={items.some((i) => i.key === activeKey) ? activeKey : 'personal'}
        onChange={(key) => setSearchParams({ tab: key }, { replace: true })}
        items={items}
        destroyInactiveTabPane={false}
      />
    </Card>
  )
}

export default SystemSettings
