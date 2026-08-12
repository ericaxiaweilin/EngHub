import axios from 'axios';
import { API_BASE_URL } from '../../config/api';

// Quality Red Tag types
export interface RedTag {
  id: string;
  red_tag_no: string;
  defect_id: string;
  inspection_id?: string;
  red_tag_type: string;
  defect_description?: string;
  nonconforming_qty: number;
  batch_no?: string;
  work_order_id?: string;
  station_id?: string;
  discovered_by?: string;
  discovered_at?: string;
  severity: string;
  quarantine_status: string;
  disposition?: string;
  disposition_by?: string;
  disposition_date?: string;
  disposition_notes?: string;
  created_at?: string;
  updated_at?: string;
  created_by?: string;
}

export interface RedTagCreate {
  factory_id: string;
  defect_id: string;
  red_tag_type: string;
  defect_description?: string;
  nonconforming_qty: number;
  batch_no?: string;
  work_order_id?: string;
  station_id?: string;
  discovered_by?: string;
  severity?: string;
}

export interface RedTagUpdate {
  defect_description?: string;
  nonconforming_qty?: number;
  batch_no?: string;
  work_order_id?: string;
  station_id?: string;
  severity?: string;
  quarantine_status?: string;
}

export interface DispositionSubmit {
  disposition: string;
  disposition_by: string;
  disposition_notes?: string;
}

export interface RedTagListResponse {
  total: number;
  limit: number;
  offset: number;
  red_tags: RedTag[];
}

export interface RedTagStatistics {
  total: number;
  by_status: Record<string, number>;
  by_disposition: Record<string, number>;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
}

// Red Tag API
export const redTagApi = {
  // Create red tag
  create: (data: RedTagCreate) => 
    axios.post(`${API_BASE_URL}/qms/red-tags/`, data),
  
  // List red tags
  list: (params: {
    factory_id: string;
    limit?: number;
    offset?: number;
    red_tag_type?: string;
    quarantine_status?: string;
    disposition?: string;
    severity?: string;
    defect_id?: string;
    date_from?: string;
    date_to?: string;
  }) => 
    axios.get<RedTagListResponse>(`${API_BASE_URL}/qms/red-tags/`, { params }),
  
  // Get red tag by ID
  get: (id: string) => 
    axios.get<RedTag>(`${API_BASE_URL}/qms/red-tags/${id}`),
  
  // Update red tag
  update: (id: string, data: RedTagUpdate) => 
    axios.put<RedTag>(`${API_BASE_URL}/qms/red-tags/${id}`, data),
  
  // Delete red tag
  delete: (id: string) => 
    axios.delete(`${API_BASE_URL}/qms/red-tags/${id}`),
  
  // Submit disposition
  submitDisposition: (id: string, data: DispositionSubmit) => 
    axios.post<RedTag>(`${API_BASE_URL}/qms/red-tags/${id}/disposition`, data),
  
  // Get statistics
  getStatistics: (factoryId: string) => 
    axios.get<RedTagStatistics>(`${API_BASE_URL}/qms/red-tags/statistics`, {
      params: { factory_id: factoryId }
    }),
  
  // Get red tags by defect
  getByDefect: (defectId: string) => 
    axios.get<RedTag[]>(`${API_BASE_URL}/qms/red-tags/defects/${defectId}/red-tags`)
};
