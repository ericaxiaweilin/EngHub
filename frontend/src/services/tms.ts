/**
 * TMS API Service - 任务管理系统前端服务
 */
import api from './api';

// ============== Types ==============

export interface TMSTask {
  id: string;
  task_code: string;
  title: string;
  description?: string;
  task_type: string;
  source: string;
  priority: 'low' | 'medium' | 'high' | 'urgent';
  points: number;
  status: string;
  distribution_strategy?: string;
  assigned_to?: string;
  assigned_by?: string;
  candidate_pool: Array<{ user_id: string; score?: number }>;
  required_skills: string[];
  required_roles: string[];
  deadline?: string;
  approval_flow_id?: string;
  agent_context: Record<string, any>;
  metadata: Record<string, any>;
  created_by?: string;
  created_at: string;
  updated_at: string;
  // 推荐任务附加字段
  match_rate?: number;
  ai_recommendation?: string;
}

export interface DashboardStats {
  pending_distribution: number;
  distributed: number;
  claimed: number;
  in_progress: number;
  pending_approval: number;
  completed: number;
  rejected: number;
  total: number;
  weekly_points: number;
  sla_rate: number;
}

export interface PendingApproval {
  flow_id: string;
  flow_code: string;
  task_id: string;
  task_code: string;
  task_title: string;
  task_type: string;
  priority: string;
  current_step: number;
  step_name: string;
  initiated_by?: string;
  created_at?: string;
}

export interface AgentCommandResponse {
  success: boolean;
  command: string;
  data: Record<string, any>;
  message: string;
  requires_confirmation: boolean;
  confirmation_id?: string;
  action_id?: string;
}

export interface DistributionStats {
  status_distribution: Record<string, number>;
  strategy_usage: Record<string, number>;
  total_distributions: number;
}

// ============== Task API ==============

export const tmsApi = {
  // Tasks
  createTask: (data: {
    title: string;
    task_type?: string;
    description?: string;
    priority?: string;
    points?: number;
    required_skills?: string[];
    deadline?: string;
  }) => api.post('/api/v1/tms/tasks', data),

  listTasks: (params?: {
    status?: string;
    task_type?: string;
    priority?: string;
    assigned_to?: string;
    page?: number;
    page_size?: number;
  }) => api.get('/api/v1/tms/tasks', { params }),

  getTask: (taskId: string) => api.get(`/api/v1/tms/tasks/${taskId}`),

  updateTask: (taskId: string, data: Partial<TMSTask>) =>
    api.put(`/api/v1/tms/tasks/${taskId}`, data),

  // Distribution
  distributeTask: (taskId: string, data: {
    strategy?: string;
    mode?: string;
    target_user_id?: string;
  }) => api.post(`/api/v1/tms/tasks/${taskId}/distribute`, data),

  claimTask: (taskId: string, userId: string) =>
    api.post(`/api/v1/tms/tasks/${taskId}/claim`, { user_id: userId }),

  getDistributionStats: () => api.get('/api/v1/tms/distribution/stats'),

  // Approvals
  initiateApproval: (data: {
    task_id: string;
    flow_type?: string;
    steps?: Array<Record<string, any>>;
  }) => api.post('/api/v1/tms/approvals', data),

  approveTask: (flowId: string, data: { approver_id: string; comment?: string }) =>
    api.post(`/api/v1/tms/approvals/${flowId}/approve`, data),

  rejectTask: (flowId: string, data: { approver_id: string; comment?: string }) =>
    api.post(`/api/v1/tms/approvals/${flowId}/reject`, data),

  delegateApproval: (flowId: string, data: { from_user_id: string; to_user_id: string }) =>
    api.post(`/api/v1/tms/approvals/${flowId}/delegate`, data),

  escalateApproval: (flowId: string, data: { reason: string }) =>
    api.post(`/api/v1/tms/approvals/${flowId}/escalate`, data),

  getPendingApprovals: (approverId: string) =>
    api.get('/api/v1/tms/approvals/pending', { params: { approver_id: approverId } }),

  getApprovalFlow: (flowId: string) => api.get(`/api/v1/tms/approvals/${flowId}`),

  // Agent API
  agentCommand: (data: {
    agent_id: string;
    command: string;
    params: Record<string, any>;
    idempotency_key?: string;
  }) => api.post('/api/v1/tms/agent/command', data),

  confirmAgentAction: (data: {
    action_id: string;
    confirmed_by: string;
    approved?: boolean;
  }) => api.post('/api/v1/tms/agent/confirm', data),

  registerAgent: (data: {
    agent_id: string;
    permission_level?: number;
    whitelisted?: boolean;
  }) => api.post('/api/v1/tms/agent/register', data),

  registerWebhook: (data: {
    agent_id: string;
    event_types: string[];
    webhook_url: string;
    secret?: string;
  }) => api.post('/api/v1/tms/agent/webhook', data),

  getAgentContext: (taskId: string) => api.get(`/api/v1/tms/agent/context/${taskId}`),

  // Dashboard
  getDashboardStats: () => api.get('/api/v1/tms/dashboard/stats'),

  getRecommendedTasks: (userId: string, limit?: number) =>
    api.get('/api/v1/tms/dashboard/recommended', { params: { user_id: userId, limit } }),
};

export default tmsApi;
