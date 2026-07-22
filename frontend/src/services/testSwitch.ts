/**
 * 测试模式角色切换服务
 * 用于开发/测试阶段快速切换不同职位账号
 */
import axios from 'axios'

const TEST_SWITCH_KEY = 'test_switch_enabled'

// 测试切换基础 URL（与 auth router prefix 一致）
const AUTH_BASE_URL = '/api/v1/auth'

/** 获取测试模式状态 */
export async function getTestModeStatus(): Promise<{ enabled: boolean; message: string }> {
  const token = localStorage.getItem('token')
  const { data } = await axios.get(`${AUTH_BASE_URL}/test/status`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  return data
}

/** 获取所有可切换的角色列表 */
export async function getAvailableRoles(): Promise<any[]> {
  const token = localStorage.getItem('token')
  const { data } = await axios.get(`${AUTH_BASE_URL}/test/roles`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  return data
}

/** 切换到指定角色 */
export async function switchRole(roleCode: string): Promise<any> {
  const token = localStorage.getItem('token')
  const { data } = await axios.post(
    `${AUTH_BASE_URL}/test/switch-role`,
    { role_code: roleCode },
    {
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        'Content-Type': 'application/json',
      },
    }
  )
  
  // 更新本地存储的 token 和用户信息
  localStorage.setItem('token', data.access_token)
  if (data.refresh_token) localStorage.setItem('refresh_token', data.refresh_token)
  localStorage.setItem('user', JSON.stringify(data))
  localStorage.setItem(TEST_SWITCH_KEY, 'true')
  
  return data
}

/** 清除测试模式标记 */
export function clearTestMode(): void {
  localStorage.removeItem(TEST_SWITCH_KEY)
}

/** 检查是否处于测试模式 */
export function isTestMode(): boolean {
  return localStorage.getItem(TEST_SWITCH_KEY) === 'true'
}
