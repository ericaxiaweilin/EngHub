/**
 * 应用多语言服务
 * - 维护可选语言清单（含越南语）
 * - 语言偏好持久化到 localStorage
 * - 切换语言时广播事件，App 层实时更新 antd ConfigProvider locale
 *
 * 说明：当前为「组件库级」多语言（antd 日期/分页/空状态等随语言切换）。
 * 业务文案的完整 i18n 翻译可在此基础上扩展（引入 i18next 时复用 APP_LOCALES 清单）。
 */
import zhCN from 'antd/locale/zh_CN'
import zhTW from 'antd/locale/zh_TW'
import enUS from 'antd/locale/en_US'
import viVN from 'antd/locale/vi_VN'

export interface AppLocale {
  value: string
  label: string
  antd: any
}

/** 可选语言清单（label 使用各语言原生写法） */
export const APP_LOCALES: AppLocale[] = [
  { value: 'zh-CN', label: '简体中文', antd: zhCN },
  { value: 'zh-TW', label: '繁體中文', antd: zhTW },
  { value: 'en', label: 'English', antd: enUS },
  { value: 'vi-VN', label: 'Tiếng Việt', antd: viVN },
]

const LOCALE_KEY = 'app_locale'
export const LOCALE_CHANGE_EVENT = 'app-locale-change'

/** 读取已存储的语言（默认简体中文） */
export function getStoredLocale(): string {
  const v = localStorage.getItem(LOCALE_KEY)
  return APP_LOCALES.some((l) => l.value === v) ? (v as string) : 'zh-CN'
}

/** 保存语言偏好并广播变更事件（App 层监听后实时切换 antd locale） */
export function setStoredLocale(value: string): void {
  localStorage.setItem(LOCALE_KEY, value)
  window.dispatchEvent(new Event(LOCALE_CHANGE_EVENT))
}

/** 语言值 -> antd locale 包 */
export function getAntdLocale(value?: string): any {
  const v = value || getStoredLocale()
  return APP_LOCALES.find((l) => l.value === v)?.antd || zhCN
}
