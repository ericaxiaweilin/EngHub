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

export interface RegisterPayload {
  username: string
  email: string
  password: string
  full_name?: string
  factory_id?: string
  invitation_token?: string
}

export interface Invitation {
  id: string
  email: string
  factory_id: string
  role: string
  token: string
  accepted: boolean
  expires_at: string
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

function authHeader() {
  const token = localStorage.getItem(TOKEN_KEY)
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** 自助注册 (邀请制多租户)。成功后返回创建的用户 */
export async function register(payload: RegisterPayload): Promise<CurrentUser> {
  const { data } = await axios.post<CurrentUser>(API_ENDPOINTS.AUTH_REGISTER, payload)
  return data
}

/** 管理员创建邀请，返回含安全 token 的邀请 */
export async function createInvitation(email: string, role: string, factory_id?: string): Promise<Invitation> {
  const { data } = await axios.post<Invitation>(
    API_ENDPOINTS.AUTH_INVITATIONS,
    { email, role, factory_id },
    { headers: authHeader() },
  )
  return data
}

/** 列出当前管理员厂区的邀请 */
export async function listInvitations(): Promise<Invitation[]> {
  const { data } = await axios.get<Invitation[]>(API_ENDPOINTS.AUTH_INVITATIONS, { headers: authHeader() })
  return data
}
