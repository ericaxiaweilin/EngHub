/**
 * RCC 共享主题 + 上下文（独立文件打破循环依赖）
 * 子组件从这导入 COLORS/useRcc，RCCCommandCenter 不再被反向引用
 */
import { createContext, useContext } from 'react'

// 深色主题（旧子组件兼容）
export const COLORS = {
  bg: '#0f1923', bgCard: '#1a2733', bgHover: '#243442', border: '#2a3f50',
  accent: '#00d4aa', accentBlue: '#4facfe', accentPurple: '#a78bfa',
  warning: '#fbbf24', danger: '#f87171', success: '#34d399',
  text: '#e2e8f0', textDim: '#94a3b8', textMuted: '#64748b',
}

export const RccContext = createContext<any>({
  baseline: {}, decisions: {}, factoryId: 'FAC_MECH_001',
  loading: false, lastSync: null, refresh: () => {},
})
export const useRcc = () => useContext(RccContext)
