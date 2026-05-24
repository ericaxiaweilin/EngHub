// 搜索数据类型定义
export interface SearchResult {
  id: string;
  type: SearchEntityType;
  title: string;
  description: string;
  score: number;
  highlights?: Record<string, string[]>;
  metadata: SearchMetadata;
  link: string;
  actions?: SearchAction[];
  breadcrumbs?: Breadcrumb[];
}

export type SearchEntityType = 
  | 'work_order'
  | 'station'
  | 'device'
  | 'material'
  | 'quality_report'
  | 'sop'
  | 'maintenance'
  | 'inventory'
  | 'user';

export interface SearchMetadata {
  status?: string;
  priority?: string;
  assignee?: string;
  createdAt?: string;
  updatedAt?: string;
  location?: string;
  oee?: number;
  defectRate?: number;
  stockLevel?: number;
  [key: string]: any;
}

export interface SearchAction {
  label: string;
  actionType: 'navigate' | 'trigger' | 'modal';
  target?: string;
  payload?: any;
  icon?: string;
}

export interface Breadcrumb {
  label: string;
  link?: string;
}

export interface SearchQuery {
  q: string;
  types?: SearchEntityType[];
  filters?: Record<string, any>;
  limit?: number;
  offset?: number;
  includeHighlights?: boolean;
  includeActions?: boolean;
}

export interface SearchStats {
  totalDocuments: number;
  documentsByType: Record<SearchEntityType, number>;
  lastIndexedAt: string;
  indexHealth: 'healthy' | 'degraded' | 'critical';
}

export interface SearchSuggestion {
  text: string;
  type: 'query' | 'entity' | 'filter';
  metadata?: any;
}
