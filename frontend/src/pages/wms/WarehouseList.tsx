import React, { useEffect, useState } from 'react'
import { Card, Table, Tag, Empty } from 'antd'
import { listWarehouses } from '../../services/modules'

const WarehouseList: React.FC = () => {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    listWarehouses()
      .then((r) => setData(r.items || []))
      .catch(() => setData([]))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>仓库管理</h2>
      <Card>
        <Table
          rowKey={(r) => r.id || r.warehouse_code} loading={loading} dataSource={data}
          locale={{ emptyText: <Empty description="暂无仓库数据" /> }}
          columns={[
            { title: '仓库编号', dataIndex: 'warehouse_code' },
            { title: '名称', dataIndex: 'warehouse_name' },
            { title: '类型', dataIndex: 'warehouse_type', render: (v: string) => v || '-' },
            { title: '库位数', dataIndex: 'location_count', render: (v: number) => v ?? '-' },
            { title: '状态', dataIndex: 'status', render: (s: string) => <Tag color={s === 'active' ? 'success' : 'default'}>{s || '-'}</Tag> },
          ]}
        />
      </Card>
    </div>
  )
}

export default WarehouseList
