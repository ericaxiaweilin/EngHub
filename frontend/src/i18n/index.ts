/**
 * i18n 初始化（i18next + react-i18next）
 * - 业务文案多语言：菜单 / 顶栏 / 设置页等（组件库级文案由 locale.ts 的 antd locale 负责）
 * - 语言来源与 locale.ts 统一（localStorage 持久化），并监听其变更事件实时切换
 * - 回退语言为简体中文：缺失的翻译键自动回退，保证不出现空白
 */
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import { getStoredLocale, LOCALE_CHANGE_EVENT } from '../services/locale'

import zhCN from './locales/zh-CN.json'
import zhTW from './locales/zh-TW.json'
import en from './locales/en.json'
import viVN from './locales/vi-VN.json'

i18n.use(initReactI18next).init({
  resources: {
    'zh-CN': { translation: zhCN },
    'zh-TW': { translation: zhTW },
    'en': { translation: en },
    'vi-VN': { translation: viVN },
  },
  lng: getStoredLocale(),
  fallbackLng: 'zh-CN',
  // 翻译缺失时回退到回退语言，而非返回键名
  returnNull: false,
  interpolation: { escapeValue: false }, // React 已默认转义
})

// 与 locale.ts 联动：个人设置切换语言 -> setStoredLocale 广播事件 -> 此处实时切换 i18n 语言
window.addEventListener(LOCALE_CHANGE_EVENT, () => {
  const lng = getStoredLocale()
  if (i18n.language !== lng) {
    i18n.changeLanguage(lng)
  }
})

export default i18n
