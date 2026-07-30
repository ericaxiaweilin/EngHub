import axios from 'axios'
import { API_ENDPOINTS } from '../config/api'

export interface CurrentUser {
  id: string
  username: string
  email: string
  full_name?: string | null
  factory_id?: string | null
  role: string
  position?: string | null
  department?: string | null
  permissions: Array<{ module: string; actions: string[] }>
  data_scope: { type: string }
  menu_items: Array<any>
  is_active: boolean
  is_superuser?: boolean
}

export interface LoginResult {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
}

const TOKEN_KEY = 'token'
const REFRESH_KEY = 'refresh_token'
const USER_KEY = 'user'
const LOGIN_AT_KEY = 'login_at'
const CRED_KEY = 'saved_credentials'

/** 会话策略：12 小时强制重新登录 */
export const SESSION_HOURS = 12

/** 登录：后端使用 OAuth2 表单 (username/password)，返回 JWT */
export async function login(username: string, password: string, remember?: boolean): Promise<LoginResult> {
  const body = new URLSearchParams()
  body.append('username', username)
  body.append('password', password)
  const { data } = await axios.post<LoginResult>(API_ENDPOINTS.AUTH_LOGIN, body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  localStorage.setItem(TOKEN_KEY, data.access_token)
  if (data.refresh_token) localStorage.setItem(REFRESH_KEY, data.refresh_token)
  localStorage.setItem(LOGIN_AT_KEY, String(Date.now()))
  // 记住密码：base64 编码存储，下次自动填充
  if (remember !== false) {
    saveCredentials(username, password)
  } else {
    clearCredentials()
  }
  return data
}

/** 保存凭据（base64 编码，仅用于本机自动填充） */
export function saveCredentials(username: string, password: string): void {
  try {
    localStorage.setItem(CRED_KEY, btoa(encodeURIComponent(JSON.stringify({ u: username, p: password }))))
  } catch { /* ignore */ }
}

/** 读取已保存凭据 */
export function loadCredentials(): { username: string; password: string } | null {
  try {
    const raw = localStorage.getItem(CRED_KEY)
    if (!raw) return null
    const { u, p } = JSON.parse(decodeURIComponent(atob(raw)))
    return u ? { username: u, password: p || '' } : null
  } catch {
    return null
  }
}

/** 清除已保存凭据 */
export function clearCredentials(): void {
  localStorage.removeItem(CRED_KEY)
}

/** 忘记密码自助重置: 凭用户名直接设新密码(内网信任环境) */
export async function resetPassword(username: string, newPassword: string): Promise<{ message: string }> {
  const { data } = await axios.post<{ message: string }>(API_ENDPOINTS.AUTH_RESET_PASSWORD, {
    username,
    new_password: newPassword,
  })
  return data
}

/** 会话是否超过 12 小时（强制重新登录） */
export function isSessionExpired(): boolean {
  const loginAt = localStorage.getItem(LOGIN_AT_KEY)
  if (!loginAt) return true
  const elapsed = Date.now() - Number(loginAt)
  return elapsed >= SESSION_HOURS * 3600 * 1000
}

/** 获取当前登录用户信息并缓存 */
export async function fetchMe(): Promise<CurrentUser> {
  const token = localStorage.getItem(TOKEN_KEY)
  const { data } = await axios.get<CurrentUser>(API_ENDPOINTS.AUTH_ME, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  localStorage.setItem(USER_KEY, JSON.stringify(data))
  return data
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(LOGIN_AT_KEY)
  // 注意：不清除 saved_credentials，保留记住密码供下次自动填充
}

export function getStoredUser(): CurrentUser | null {
  const raw = localStorage.getItem(USER_KEY)
  try {
    return raw ? (JSON.parse(raw) as CurrentUser) : null
  } catch {
    return null
  }
}

export function isAuthenticated(): boolean {
  if (!localStorage.getItem(TOKEN_KEY)) return false
  // 12 小时强制重新登录：过期则清除会话（保留记住密码）并跳转登录页
  if (isSessionExpired()) {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem(USER_KEY)
    localStorage.removeItem(LOGIN_AT_KEY)
    sessionStorage.setItem('session_expired', '1')
    return false
  }
  return true
}

/** 检查用户是否有指定模块的操作权限 */
export function hasPermission(module: string, action: string): boolean {
  const user = getStoredUser()
  if (!user) return false
  // 管理员/超管拥有所有权限
  if (user.is_superuser || user.role === 'admin') return true
  return user.permissions.some(p => p.module === module && p.actions.includes(action))
}

/** 检查用户是否有任一权限 */
export function hasAnyPermission(checks: Array<{ module: string; action: string }>): boolean {
  return checks.some(c => hasPermission(c.module, c.action))
}
