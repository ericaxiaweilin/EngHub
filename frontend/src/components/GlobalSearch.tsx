/**
 * 全站系统搜索组件（参考 luaguage site_search_engine 交互模式）
 * 顶栏搜索框 → 防抖请求 → 分类下拉结果 → 点击跳转
 */
import React, { useState, useRef, useCallback, useEffect } from 'react'
import { Input, Tag, Spin, Empty, Typography } from 'antd'
import { SearchOutlined, FileTextOutlined, AppstoreOutlined, ToolOutlined, InboxOutlined, TeamOutlined, HomeOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'

const { Text } = Typography

interface SearchResult {
  source: string
  source_label: string
  title: string
  subtitle: string
  route: string
  id: string
}

const sourceIcons: Record<string, React.ReactNode> = {
  work_order: <FileTextOutlined />,
  product: <AppstoreOutlined />,
  equipment: <ToolOutlined />,
  inventory: <InboxOutlined />,
  station: <HomeOutlined />,
  warehouse: <InboxOutlined />,
  employee: <TeamOutlined />,
}

const sourceColors: Record<string, string> = {
  work_order: 'blue',
  product: 'green',
  equipment: 'orange',
  inventory: 'cyan',
  station: 'purple',
  warehouse: 'geekblue',
  employee: 'magenta',
}

export default function GlobalSearch() {
  const [keyword, setKeyword] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [facets, setFacets] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const navigate = useNavigate()
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)

  // 防抖搜索
  const doSearch = useCallback(async (kw: string) => {
    if (!kw.trim()) {
      setResults([])
      setFacets({})
      setOpen(false)
      return
    }
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/search', { params: { q: kw, limit: 6 } })
      setResults(res.results || [])
      setFacets(res.facets || {})
      setOpen(true)
      setActiveIdx(-1)
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [])

  const onChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value
    setKeyword(val)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => doSearch(val), 350)
  }

  const goResult = (item: SearchResult) => {
    setOpen(false)
    setKeyword('')
    navigate(item.route)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault()
      goResult(results[activeIdx])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  // 点击外部关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // 按 source 分组
  const grouped = results.reduce<Record<string, SearchResult[]>>((acc, item) => {
    ;(acc[item.source] = acc[item.source] || []).push(item)
    return acc
  }, {})

  return (
    <div ref={boxRef} style={{ position: 'relative', width: 260 }}>
      <Input
        prefix={<SearchOutlined style={{ color: 'rgba(255,255,255,0.5)' }} />}
        placeholder="全站搜索 (工单/产品/设备/员工...)"
        value={keyword}
        onChange={onChange}
        onKeyDown={onKeyDown}
        onFocus={() => keyword.trim() && results.length > 0 && setOpen(true)}
        suffix={loading ? <Spin size="small" /> : undefined}
        style={{
          borderRadius: 16,
          background: 'rgba(255,255,255,0.1)',
          border: '1px solid rgba(255,255,255,0.2)',
          color: '#fff',
        }}
        allowClear
      />

      {/* 下拉结果面板 */}
      {open && (
        <div style={{
          position: 'absolute',
          top: 40,
          left: 0,
          width: 380,
          maxHeight: 420,
          overflowY: 'auto',
          background: '#fff',
          borderRadius: 8,
          boxShadow: '0 6px 24px rgba(0,0,0,0.15)',
          zIndex: 1100,
          padding: '8px 0',
        }}>
          {/* Facets 统计条 */}
          {Object.keys(facets).length > 0 && (
            <div style={{ padding: '4px 12px 8px', borderBottom: '1px solid #f0f0f0', display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {Object.entries(facets).map(([src, cnt]) => (
                <Tag key={src} color={sourceColors[src] || 'default'} style={{ fontSize: 11, margin: 0 }}>
                  {results.find(r => r.source === src)?.source_label || src} {cnt}
                </Tag>
              ))}
            </div>
          )}

          {results.length === 0 && !loading ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无匹配结果" style={{ padding: '16px 0' }} />
          ) : (
            Object.entries(grouped).map(([source, items]) => (
              <div key={source}>
                <div style={{ padding: '6px 12px 2px', fontSize: 11, color: '#999', fontWeight: 600 }}>
                  {sourceIcons[source]} {items[0]?.source_label}
                </div>
                {items.map((item, idx) => {
                  const globalIdx = results.indexOf(item)
                  return (
                    <div
                      key={`${item.source}-${item.id}-${idx}`}
                      onClick={() => goResult(item)}
                      onMouseEnter={() => setActiveIdx(globalIdx)}
                      style={{
                        padding: '6px 12px 6px 24px',
                        cursor: 'pointer',
                        background: globalIdx === activeIdx ? '#f0f5ff' : 'transparent',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                      }}
                    >
                      <Text strong style={{ fontSize: 13 }}>{item.title}</Text>
                      {item.subtitle && item.subtitle !== item.title && (
                        <Text type="secondary" style={{ fontSize: 12 }}>{item.subtitle}</Text>
                      )}
                    </div>
                  )
                })}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
