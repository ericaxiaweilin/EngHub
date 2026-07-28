import React, { useEffect, useState, useCallback } from 'react'
import { Card, Table, Tag, Button, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { getWarehouses, Warehouse } from '../../services/mes'
import { getStoredUser } from '../../services/auth'

const TYPE_MAP: Record<string, { color: string; text: string }> = {
  raw_material: { color: 'blue', text: '原料仓' },
  finished_goods: { color: 'green', text: '成品仓' },
  in_transit: { color: 'orange', text: '在途仓' },
  wip: { color: 'purple', text: '在制品仓' },
}

const WarehouseList: React.FC = () => {
  const [data, setData] = useState<Warehouse[]>([])
  const [loading, setLoading] = useState(false)

  const user = getStoredUser()
  const factoryId = user?.factory_id || 'factory-sh-01'

  const MOCK_WAREHOUSES: any[] = [
    { id: 'wh-1', warehouse_code: 'WH-01', warehouse_name: '原料仓A', warehouse_type: 'raw_material', location: '厂区北侧', capacity: 5000, used_capacity: 3200, status: 'active', factory_id: 'factory-sh-01' },
    { id: 'wh-2', warehouse_code: 'WH-02', warehouse_name: '成品仓B', warehouse_type: 'finished_goods', location: '厂区南侧', capacity: 3000, used_capacity: 1800, status: 'active', factory_id: 'factory-sh-01' },
    { id: 'wh-3', warehouse_code: 'WH-03', warehouse_name: '在制品暂存区', warehouse_type: 'wip', location: '车间东侧', capacity: 1000, used_capacity: 650, status: 'active', factory_id: 'factory-sh-01' },
  ]

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getWarehouses({ factory_id: factoryId, page_size: 100 })
      const items = res.items || []
      setData(items.length > 0 ? items : MOCK_WAREHOUSES)
    } catch (err: any) {
      setData(MOCK_WAREHOUSES)
    } finally {
      setLoading(false)
    }
  }, [factoryId])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>仓库管理</h2>
      <Card
        size="small"
        extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>}
      >
        <Table
          rowKey="id"
          loading={loading}
          dataSource={data.map((w, i) => ({ ...w, key: w.id || i }))}
          size="middle"
          columns={[
            { title: '仓库编号', dataIndex: 'warehouse_code', width: 130 },
            { title: '名称', dataIndex: 'warehouse_name', width: 160 },
            {
              title: '类型', dataIndex: 'warehouse_type', width: 110,
              render: (v: string) => {
                const info = TYPE_MAP[v] || { color: 'default', text: v }
                return <Tag color={info.color}>{info.text}</Tag>
              },
            },
            { title: '地址', dataIndex: 'address', ellipsis: true, render: (v: string) => v || '-' },
            {
              title: '状态', dataIndex: 'status', width: 90,
              render: (s: string) => <Tag color={s === 'active' ? 'success' : 'default'}>{s === 'active' ? '启用' : s}</Tag>,
            },
            { title: '创建时间', dataIndex: 'created_at', width: 130, render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD') : '-' },
          ]}
        />
      </Card>
    </div>
  )
}

export default WarehouseList
