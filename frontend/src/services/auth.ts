import axios from 'axios'
import { API_ENDPOINTS } from '../config/api'

export interface CurrentUser {
  id: string
  username: string
  email: string
  full_name?: string | null
  factory_id?: string | null
  role: string
  is_active: boolean
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

/** 登录：后端使用 OAuth2 表单 (username/password)，返回 JWT */
export async function login(username: string, password: string): Promise<LoginResult> {
  const body = new URLSearchParams()
  body.append('username', username)
  body.append('password', password)
  const { data } = await axios.post<LoginResult>(API_ENDPOINTS.AUTH_LOGIN, body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  localStorage.setItem(TOKEN_KEY, data.access_token)
  if (data.refresh_token) localStorage.setItem(REFRESH_KEY, data.refresh_token)
  return data
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
  return !!localStorage.getItem(TOKEN_KEY)
}
