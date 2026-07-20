import React, { useEffect, useState } from 'react'
import { Card, Tabs, Table, Tag, Empty } from 'antd'
import { listStations, listRoutings, listEquipment } from '../../services/modules'

function useList(fetcher: () => Promise<{ items: any[]; total: number }>) {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    setLoading(true)
    fetcher()
      .then((r) => setData(r.items || []))
      .catch(() => setData([]))
      .finally(() => setLoading(false))
  }, [])
  return { data, loading }
}

const StationTab: React.FC = () => {
  const { data, loading } = useList(() => listStations())
  return (
    <Table
      rowKey={(r) => r.id || r.station_code} loading={loading} dataSource={data}
      locale={{ emptyText: <Empty description="暂无工位数据" /> }}
      columns={[
        { title: '工位编号', dataIndex: 'station_code' },
        { title: '名称', dataIndex: 'station_name' },
        { title: '类型', dataIndex: 'station_type' },
        { title: '产线', dataIndex: 'line_id' },
        { title: '状态', dataIndex: 'status', render: (s: string) => <Tag color={s === 'active' ? 'success' : 'default'}>{s || '-'}</Tag> },
      ]}
    />
  )
}

const RoutingTab: React.FC = () => {
  const { data, loading } = useList(() => listRoutings())
  return (
    <Table
      rowKey={(r) => r.id || r.routing_code} loading={loading} dataSource={data}
      locale={{ emptyText: <Empty description="暂无工艺路线数据" /> }}
      columns={[
        { title: '路线编号', dataIndex: 'routing_code' },
        { title: '产品', dataIndex: 'product_id' },
        { title: '版本', dataIndex: 'version' },
        { title: '工序数', dataIndex: 'operations', render: (v: any[]) => (Array.isArray(v) ? v.length : '-') },
        { title: '状态', dataIndex: 'status', render: (s: string) => <Tag color={s === 'active' ? 'success' : 'default'}>{s || '-'}</Tag> },
      ]}
    />
  )
}

const EquipmentTab: React.FC = () => {
  const { data, loading } = useList(() => listEquipment())
  const statusColor: Record<string, string> = { running: 'success', idle: 'default', maintenance: 'warning', fault: 'error' }
  return (
    <Table
      rowKey={(r) => r.id || r.equipment_code} loading={loading} dataSource={data}
      locale={{ emptyText: <Empty description="暂无设备数据" /> }}
      columns={[
        { title: '设备编号', dataIndex: 'equipment_code' },
        { title: '名称', dataIndex: 'equipment_name' },
        { title: '所属工位', dataIndex: 'station_id' },
        { title: '状态', dataIndex: 'status', render: (s: string) => <Tag color={statusColor[s] || 'default'}>{s || '-'}</Tag> },
      ]}
    />
  )
}

const BaseData: React.FC = () => (
  <div>
    <h2 style={{ marginBottom: 16 }}>基础数据</h2>
    <Card>
      <Tabs
        items={[
          { key: 'station', label: '工位', children: <StationTab /> },
          { key: 'routing', label: '工艺路线', children: <RoutingTab /> },
          { key: 'equipment', label: '设备', children: <EquipmentTab /> },
        ]}
      />
    </Card>
  </div>
)

export default BaseData
