import React, { useEffect, useMemo, useState } from 'react'
import { Button, Descriptions, Drawer, Empty, List, Space, Spin, Table, Tag, Timeline, Typography, message } from 'antd'
import { BranchesOutlined, DatabaseOutlined, LinkOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../services/api'

const { Text } = Typography

interface TraceSource {
  key: string
  label: string
  route?: string
  count: number
  columns: string[]
  records: Record<string, any>[]
  error?: string
}

interface TraceData {
  success: boolean
  factory_id: string
  domain: string
  title: string
  lineage: string[]
  summary: {
    source_count: number
    total_records: number
    generated_at: string
  }
  sources: TraceSource[]
}

interface Props {
  open: boolean
  factoryId: string
  domain: string | null
  title?: string
  onClose: () => void
}

const formatValue = (value: any) => {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const TraceabilityDrawer: React.FC<Props> = ({ open, factoryId, domain, title, onClose }) => {
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<TraceData | null>(null)

  const fetchTrace = async () => {
    if (!open || !factoryId || !domain) return
    setLoading(true)
    try {
      const res: TraceData = await api.get('/api/v1/traceability/drill-through', {
        params: { factory_id: factoryId, domain, limit: 8 },
      })
      setData(res)
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '追溯数据加载失败')
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTrace()
  }, [open, factoryId, domain])

  const sourceItems = useMemo(() => data?.sources || [], [data])

  return (
    <Drawer
      title={
        <Space>
          <BranchesOutlined />
          <span>{title || data?.title || '穿透式追溯'}</span>
          {domain && <Tag color="blue">{domain}</Tag>}
        </Space>
      }
      open={open}
      onClose={onClose}
      width={760}
      extra={
        <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={fetchTrace}>
          刷新
        </Button>
      }
    >
      <Spin spinning={loading}>
        {!data ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无追溯数据" />
        ) : (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Descriptions size="small" bordered column={3}>
              <Descriptions.Item label="工厂">{data.factory_id}</Descriptions.Item>
              <Descriptions.Item label="来源数">{data.summary.source_count}</Descriptions.Item>
              <Descriptions.Item label="记录数">{data.summary.total_records}</Descriptions.Item>
            </Descriptions>

            <div>
              <div style={{ marginBottom: 8, fontWeight: 600 }}>
                <BranchesOutlined /> 数据链路
              </div>
              <Timeline
                items={data.lineage.map((item) => ({ children: <Text>{item}</Text> }))}
              />
            </div>

            <List
              dataSource={sourceItems}
              renderItem={(source) => (
                <List.Item style={{ display: 'block', padding: '12px 0' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                    <Space>
                      <DatabaseOutlined style={{ color: '#1677ff' }} />
                      <Text strong>{source.label}</Text>
                      <Tag>{source.key}</Tag>
                      <Tag color={source.count > 0 ? 'green' : 'default'}>{source.count} 条</Tag>
                      {source.error && <Tag color="red">降级</Tag>}
                    </Space>
                    {source.route && (
                      <Button
                        size="small"
                        type="link"
                        icon={<LinkOutlined />}
                        onClick={() => navigate(source.route!)}
                      >
                        打开模块
                      </Button>
                    )}
                  </div>
                  {source.error ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>{source.error}</Text>
                  ) : source.records.length === 0 ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该来源暂无记录" />
                  ) : (
                    <Table
                      size="small"
                      rowKey={(record, index) => String(record.id || index)}
                      dataSource={source.records}
                      columns={source.columns.map((column) => ({
                        title: column,
                        dataIndex: column,
                        key: column,
                        ellipsis: true,
                        render: formatValue,
                      }))}
                      pagination={false}
                      scroll={{ x: 'max-content' }}
                    />
                  )}
                </List.Item>
              )}
            />
          </Space>
        )}
      </Spin>
    </Drawer>
  )
}

export default TraceabilityDrawer
