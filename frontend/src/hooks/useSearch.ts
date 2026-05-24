import { useState, useEffect, useCallback } from 'react';
import { SearchResult, SearchQuery, SearchStats, SearchSuggestion } from '../types/search';

const API_BASE = '/api/v1/search';

export function useSearch() {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<SearchStats | null>(null);

  const search = useCallback(async (query: SearchQuery) => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch(`${API_BASE}/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(query),
      });
      
      if (!response.ok) throw new Error('Search failed');
      
      const data = await response.json();
      setResults(data.results || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  const getStats = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/stats`);
      if (!response.ok) throw new Error('Failed to fetch stats');
      const data = await response.json();
      setStats(data);
    } catch (err) {
      console.error('Failed to fetch stats:', err);
    }
  }, []);

  const getSuggestions = useCallback(async (query: string): Promise<SearchSuggestion[]> => {
    try {
      const response = await fetch(`${API_BASE}/suggest?q=${encodeURIComponent(query)}`);
      if (!response.ok) throw new Error('Failed to fetch suggestions');
      return await response.json();
    } catch (err) {
      console.error('Failed to fetch suggestions:', err);
      return [];
    }
  }, []);

  useEffect(() => {
    getStats();
  }, [getStats]);

  return {
    results,
    loading,
    error,
    stats,
    search,
    getSuggestions,
    refreshStats: getStats,
  };
}
