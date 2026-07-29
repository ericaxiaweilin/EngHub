import api from './api'

export interface CodeTableItem {
  id: string
  category: string
  code: string
  name: string
  name_en?: string
  description?: string
  keywords?: string[]
  extra?: Record<string, any>
  sort_order: number
  is_active: boolean
  is_system: boolean
  factory_id?: string
}

export interface CategoryInfo {
  category: string
  count: number
}

// 分类中文标签
export const CATEGORY_LABELS: Record<string, string> = {
  wo_type: '工单类型',
  process_code: '工序代码',
  priority: '优先级',
  wo_status: '工单状态',
}

/** 获取所有码表分类 */
export const getCategories = (): Promise<CategoryInfo[]> =>
  api.get('/api/v1/code-tables/categories')

/** 按分类获取码表条目 */
export const getCodeTableItems = (category: string, includeInactive = false): Promise<{ category: string; items: CodeTableItem[]; total: number }> =>
  api.get(`/api/v1/code-tables/${category}`, { params: { include_inactive: includeInactive } })

/** 新增码表条目 */
export const createCodeTableItem = (category: string, data: Partial<CodeTableItem>): Promise<CodeTableItem> =>
  api.post(`/api/v1/code-tables/${category}`, { ...data, category })

/** 更新码表条目 */
export const updateCodeTableItem = (category: string, id: string, data: Partial<CodeTableItem>): Promise<CodeTableItem> =>
  api.put(`/api/v1/code-tables/${category}/${id}`, data)

/** 删除码表条目 */
export const deleteCodeTableItem = (category: string, id: string): Promise<void> =>
  api.delete(`/api/v1/code-tables/${category}/${id}`)
