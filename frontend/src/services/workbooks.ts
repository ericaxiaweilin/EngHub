import api from './api'

export interface WorkbookMeta {
  id: string
  name: string
  factory_id?: string
  source_file_id?: string
  created_at?: string
  updated_at?: string
}

export interface WorkbookRecord extends WorkbookMeta {
  snapshot: Record<string, any>
}

export const workbooksApi = {
  list(limit = 100) {
    return api.get<any, { count: number; workbooks: WorkbookMeta[] }>('/api/v1/workbooks', { params: { limit } })
  },
  get(id: string) {
    return api.get<any, WorkbookRecord>(`/api/v1/workbooks/${id}`)
  },
  create(data: { name: string; snapshot: Record<string, any> }) {
    return api.post<any, WorkbookMeta>('/api/v1/workbooks', data)
  },
  createPmcTemplate() {
    return api.post<any, WorkbookRecord>('/api/v1/workbooks/templates/pmc', {})
  },
  update(id: string, data: { name?: string; snapshot: Record<string, any> }) {
    return api.put<any, WorkbookMeta>(`/api/v1/workbooks/${id}`, data)
  },
  import(file: File, name?: string) {
    const form = new FormData()
    form.append('file', file)
    if (name) form.append('name', name)
    return api.post<any, WorkbookRecord>('/api/v1/workbooks/import', form, {
      headers: { 'Content-Type': undefined },
    })
  },
  operations(id: string, operations: Record<string, any>[]) {
    return api.post<any, { success: boolean; snapshot: Record<string, any>; changed: Record<string, any>[] }>(`/api/v1/workbooks/${id}/operations`, { operations })
  },
  pivot(id: string, data: { sheet?: string; row_field: string; value_field: string; aggregation: string; output_sheet_name?: string }) {
    return api.post<any, WorkbookRecord & { summary: Record<string, any> }>(`/api/v1/workbooks/${id}/pivot`, data)
  },
}
