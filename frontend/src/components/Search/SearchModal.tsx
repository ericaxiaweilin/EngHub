import React, { useState, useEffect, useRef } from 'react';
import { useSearch } from '../../hooks/useSearch';
import { SearchResult, SearchEntityType } from '../../types/search';

interface SearchModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const ENTITY_CONFIG: Record<SearchEntityType, { label: string; color: string; icon: string }> = {
  work_order: { label: '工单', color: 'bg-blue-100 text-blue-800', icon: '📋' },
  station: { label: '工位', color: 'bg-green-100 text-green-800', icon: '🏭' },
  device: { label: '设备', color: 'bg-purple-100 text-purple-800', icon: '⚙️' },
  material: { label: '物料', color: 'bg-yellow-100 text-yellow-800', icon: '📦' },
  quality_report: { label: '质量报告', color: 'bg-red-100 text-red-800', icon: '📊' },
  sop: { label: 'SOP', color: 'bg-indigo-100 text-indigo-800', icon: '📖' },
  maintenance: { label: '维护计划', color: 'bg-orange-100 text-orange-800', icon: '🔧' },
  inventory: { label: '库存', color: 'bg-teal-100 text-teal-800', icon: '📈' },
  user: { label: '用户', color: 'bg-gray-100 text-gray-800', icon: '👤' },
};

export const SearchModal: React.FC<SearchModalProps> = ({ isOpen, onClose }) => {
  const [query, setQuery] = useState('');
  const [selectedTypes, setSelectedTypes] = useState<SearchEntityType[]>([]);
  const { results, loading, search, getSuggestions } = useSearch();
  const inputRef = useRef<HTMLInputElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        if (!isOpen) return;
        inputRef.current?.focus();
      }
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (modalRef.current && !modalRef.current.contains(e.target as Node)) {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => document.removeEventListener('mousedown', handleClickOutside);
    }
  }, [isOpen, onClose]);

  const handleSearch = async (searchQuery: string) => {
    await search({
      q: searchQuery,
      types: selectedTypes.length > 0 ? selectedTypes : undefined,
      limit: 10,
      includeHighlights: true,
      includeActions: true,
    });
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setQuery(value);
    if (value.length >= 2) {
      handleSearch(value);
    } else {
      // Clear results for short queries
    }
  };

  const toggleType = (type: SearchEntityType) => {
    setSelectedTypes(prev =>
      prev.includes(type) ? prev.filter(t => t !== type) : [...prev, type]
    );
  };

  const handleResultClick = (result: SearchResult) => {
    window.location.href = result.link;
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-start justify-center pt-20 z-50">
      <div
        ref={modalRef}
        className="bg-white rounded-lg shadow-2xl w-full max-w-3xl overflow-hidden"
      >
        {/* Search Input */}
        <div className="p-4 border-b border-gray-200">
          <div className="flex items-center gap-3">
            <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={handleInputChange}
              placeholder="搜索工单、设备、物料、SOP..."
              className="flex-1 outline-none text-lg"
            />
            <kbd className="hidden sm:inline-block px-2 py-1 text-xs font-semibold text-gray-500 bg-gray-100 border border-gray-200 rounded-md">
              ESC
            </kbd>
          </div>

          {/* Type Filters */}
          <div className="flex flex-wrap gap-2 mt-3">
            {(Object.keys(ENTITY_CONFIG) as SearchEntityType[]).map(type => (
              <button
                key={type}
                onClick={() => toggleType(type)}
                className={`px-3 py-1 text-sm rounded-full transition-colors ${
                  selectedTypes.includes(type)
                    ? 'bg-blue-500 text-white'
                    : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                }`}
              >
                {ENTITY_CONFIG[type].icon} {ENTITY_CONFIG[type].label}
              </button>
            ))}
          </div>
        </div>

        {/* Results */}
        <div className="max-h-[60vh] overflow-y-auto">
          {loading && (
            <div className="p-8 text-center text-gray-500">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto"></div>
              <p className="mt-2">搜索中...</p>
            </div>
          )}

          {!loading && results.length === 0 && query.length >= 2 && (
            <div className="p-8 text-center text-gray-500">
              <p>未找到相关结果</p>
            </div>
          )}

          {!loading && results.map((result, index) => (
            <div
              key={`${result.type}-${result.id}`}
              onClick={() => handleResultClick(result)}
              className="p-4 hover:bg-gray-50 cursor-pointer border-b border-gray-100 transition-colors"
            >
              <div className="flex items-start gap-3">
                <div className={`px-2 py-1 rounded text-xs font-medium ${ENTITY_CONFIG[result.type].color}`}>
                  {ENTITY_CONFIG[result.type].icon} {ENTITY_CONFIG[result.type].label}
                </div>
                <div className="flex-1">
                  <h3 className="font-semibold text-gray-900">{result.title}</h3>
                  <p className="text-sm text-gray-600 mt-1">{result.description}</p>
                  
                  {result.breadcrumbs && result.breadcrumbs.length > 0 && (
                    <div className="flex items-center gap-2 mt-2 text-xs text-gray-500">
                      {result.breadcrumbs.map((crumb, i) => (
                        <React.Fragment key={i}>
                          {i > 0 && <span>/</span>}
                          <span>{crumb.label}</span>
                        </React.Fragment>
                      ))}
                    </div>
                  )}

                  {result.metadata && (
                    <div className="flex flex-wrap gap-2 mt-2">
                      {result.metadata.status && (
                        <span className="px-2 py-0.5 text-xs rounded bg-gray-100 text-gray-700">
                          状态：{result.metadata.status}
                        </span>
                      )}
                      {result.metadata.priority && (
                        <span className="px-2 py-0.5 text-xs rounded bg-gray-100 text-gray-700">
                          优先级：{result.metadata.priority}
                        </span>
                      )}
                      {result.metadata.assignee && (
                        <span className="px-2 py-0.5 text-xs rounded bg-gray-100 text-gray-700">
                          负责人：{result.metadata.assignee}
                        </span>
                      )}
                    </div>
                  )}
                </div>
                <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="p-3 bg-gray-50 border-t border-gray-200 text-xs text-gray-500 flex justify-between">
          <span>{results.length} 个结果</span>
          <div className="flex gap-4">
            <span>↑↓ 导航</span>
            <span>↵ 打开</span>
            <span>ESC 关闭</span>
          </div>
        </div>
      </div>
    </div>
  );
};
