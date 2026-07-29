

import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1'

export interface WorkOrderTemplate {
  template_code: string
  name: string
  description: string
}

export interface TemplateField {
  key: string
  label: string
  type: string
  required?: boolean
  options?: string[]
}

// ==================== API ====================

export const workOrderTemplatesApi = {
  /** 获取所有模板定义 */
  list: async (): Promise<WorkOrderTemplate[]> => {
    const { data } = await axios.get(`${API_BASE}/work-order-templates/`)
    return data.templates
  },

  /** 预览指定模板字段 */
  previewFields: async (templateCode: string): Promise<TemplateField[]> => {
    const { data } = await axios.get(`${API_BASE}/work-order-templates/preview/${templateCode}`)
    return data.fields || []
  },

  /** 基于模板创建程序工单 */
  createFromTemplate: async (payload: {
    factory_id: string
    template_code: string
    title: string
    priority?: string
    data: Record<string, any>
  }): Promise<any> => {
    const { data } = await axios.post(`${API_BASE}/work-order-templates/create`, payload)
    return data
  },

  /** 一键将临时小工单转为正式程序工单 */
  convertFromSmallTicket: async (andonTicketId: string, templateCode: string, title: string): Promise<any> => {
    const { data } = await axios.post(`${API_BASE}/work-order-templates/create`, {
      factory_id: 'default',
      template_code: templateCode,
      title,
      metadata_: { source_ticket_id: andonTicketId },
    })
    return data
  },
}

