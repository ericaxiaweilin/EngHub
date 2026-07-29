import React, { useEffect, useState, useCallback } from 'react'
import {
  Table, Input, Button, Card, Space, Tag, message, Row, Col, Statistic, Select,
} from 'antd'
import { SearchOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import { getInventory, InventoryItem, getWarehouses, Warehouse } from '../../services/mes'
import { getStoredUser } from '../../services/auth'
import DrillDownDrawer from '../../components/trace/DrillDownDrawer'
import RecordDetailDrawer, { DetailField } from '../../components/trace/RecordDetailDrawer'

const { Option } = Select

const LOW_STOCK_THRESHOLD = 100

interface DrillConfig {
  title: string
  headline?: React.ReactNode
  formula?: string
  columns: ColumnsType<any>
  records: any[]
  onRowClick?: (r: any) => void
}

const InventoryList: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<InventoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string | undefined>()

  const [warehouses, setWarehouses] = useState<Warehouse[]>([])
  // 追溯交互状态：统计下钻抽屉 / 库存详情
  const [drill, setDrill] = useState<DrillConfig | null>(null)
  const [detail, setDetail] = useState<InventoryItem | null>(null)

  const user = getStoredUser()
  const factoryId = localStorage.getItem('active_factory_id') || user?.factory_id || 'F01'

  const MOCK_INVENTORY: any[] = [
    { id: 'inv-1', material_code: 'MAT-1001', material_name: '轴承 6205', quantity: 2400, unit: '个', warehouse_id: 'WH-01', location: 'A-01-01', safety_stock: 500, max_stock: 5000, status: 'normal', factory_id: 'factory-sh-01', updated_at: '2026-07-20' },
    { id: 'inv-2', material_code: 'MAT-2003', material_name: 'M8螺栓', quantity: 180, unit: '个', warehouse_id: 'WH-01', location: 'A-02-03', safety_stock: 200, max_stock: 3000, status: 'below_safety', factory_id: 'factory-sh-01', updated_at: '2026-07-19' },
    { id: 'inv-3', material_code: 'MAT-3010', material_name: 'PCB主板', quantity: 850, unit: '块', warehouse_id: 'WH-02', location: 'B-01-02', safety_stock: 100, max_stock: 2000, status: 'normal', factory_id: 'factory-sh-01', updated_at: '2026-07-18' },
    { id: 'inv-4', material_code: 'MAT-4005', material_name: '密封圈', quantity: 5200, unit: '个', warehouse_id: 'WH-02', location: 'B-03-01', safety_stock: 1000, max_stock: 5000, status: 'above_max', factory_id: 'factory-sh-01', updated_at: '2026-07-17' },
    { id: 'inv-5', material_code: 'MAT-5002', material_name: '铝合金棒材', quantity: 320, unit: 'kg', warehouse_id: 'WH-03', location: 'C-01-01', safety_stock: 100, max_stock: 1000, status: 'normal', factory_id: 'factory-sh-01', updated_at: '2026-07-16' },
  ]

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, any> = { factory_id: factoryId, page, page_size: 20 }
      if (search) params.material_code = search
      if (statusFilter) params.status = statusFilter
      const res = await getInventory(params)
      const items = res.items || []
      setData(items)
      setTotal(res.total ?? items.length)
    } catch (err: any) {
      setData([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [factoryId, page, search, statusFilter])

  useEffect(() => { fetchData() }, [fetchData])

  // 拉取仓库用于外键可读化（warehouse_id → 仓库编码+名称）
  useEffect(() => {
    getWarehouses({ factory_id: factoryId, page_size: 50 })
      .then(res => setWarehouses(res.items || []))
      .catch(() => {})
  }, [factoryId])

  const lowStockCount = data.filter(i => i.available_qty < LOW_STOCK_THRESHOLD).length
  const totalReserved = data.reduce((s, i) => s + i.reserved_qty, 0)
  const totalAvailable = data.reduce((s, i) => s + i.available_qty, 0)

  // ===== 追溯：ID 可读化 =====
  const warehouseLabel = (id?: string | null): string => {
    if (!id) return '-'
    const w = warehouses.find(x => x.id === id)
    return w ? `${w.warehouse_code} ${w.warehouse_name}` : id
  }

  const statusTag = (s: string) => {
    const map: Record<string, { color: string; text: string }> = {
      available: { color: 'success', text: '正常' },
      low_stock: { color: 'warning', text: '低库存' },
      frozen: { color: 'error', text: '冻结' },
    }
    const info = map[s] || { color: 'default', text: s }
    return <Tag color={info.color}>{info.text}</Tag>
  }

  // ===== 追溯：库存详情字段（全字段）=====
  const detailFields: DetailField[] = [
    { label: '物料编码', key: 'material_code' },
    { label: '物料ID', key: 'material_id' },
    { label: '批次号', key: 'batch_code', render: (v: string) => v || '-' },
    { label: '仓库', key: 'warehouse_id', render: (v: string) => warehouseLabel(v) },
    { label: '库位', key: 'location_id', render: (v: string) => v || '-' },
    { label: '总库存', key: 'total_qty', render: (v: number) => <span style={{ fontWeight: 600 }}>{v}</span> },
    { label: '可用', key: 'available_qty', render: (v: number) => <span style={{ color: v < LOW_STOCK_THRESHOLD ? '#f5222d' : '#52c41a', fontWeight: 600 }}>{v}</span> },
    { label: '预留', key: 'reserved_qty', render: (v: number) => <span style={{ color: '#faad14' }}>{v}</span> },
    { label: '单位成本', key: 'unit_cost', render: (v: number) => (v != null ? `¥${Number(v).toFixed(2)}` : '-') },
    { label: '状态', key: 'status', render: (s: string) => statusTag(s) },
    { label: '创建时间', key: 'created_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-') },
    { label: '更新时间', key: 'updated_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-') },
  ]

  // ===== 追溯：库存下钻共用列 =====
  const drillColumns: ColumnsType<any> = [
    { title: '物料编码', dataIndex: 'material_code', key: 'code', width: 140 },
    { title: '批次号', dataIndex: 'batch_code', key: 'batch', width: 110, render: (v: string) => v || '-' },
    { title: '仓库', dataIndex: 'warehouse_id', key: 'wh', width: 130, render: (v: string) => warehouseLabel(v) },
    { title: '总库存', dataIndex: 'total_qty', key: 'total', width: 80 },
    { title: '可用', dataIndex: 'available_qty', key: 'avail', width: 80, render: (v: number) => <span style={{ color: v < LOW_STOCK_THRESHOLD ? '#f5222d' : '#52c41a' }}>{v}</span> },
    { title: '预留', dataIndex: 'reserved_qty', key: 'resv', width: 70 },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (s: string) => statusTag(s) },
  ]

  // ===== 追溯：顶部 3 个统计的下钻配置 =====
  const statDrills = {
    available: (): DrillConfig => ({
      title: '可用库存总量 · 追溯',
      headline: `${totalAvailable}`,
      formula: `${totalAvailable} = ${data.length} 个库存项可用量之和`,
      columns: drillColumns,
      records: data,
      onRowClick: (r) => setDetail(r),
    }),
    reserved: (): DrillConfig => ({
      title: '预留总量 · 追溯',
      headline: `${totalReserved}`,
      formula: `${totalReserved} = ${data.length} 个库存项预留量之和`,
      columns: drillColumns,
      records: data.filter(i => i.reserved_qty > 0),
      onRowClick: (r) => setDetail(r),
    }),
    lowStock: (): DrillConfig => ({
      title: '低库存物料 · 追溯',
      headline: `${lowStockCount} 项`,
      formula: `${lowStockCount} 项可用量低于 ${LOW_STOCK_THRESHOLD} / ${data.length} 总库存项`,
      columns: drillColumns,
      records: data.filter(i => i.available_qty < LOW_STOCK_THRESHOLD),
      onRowClick: (r) => setDetail(r),
    }),
  }

  const columns = [
    { title: '物料编码', dataIndex: 'material_code', key: 'code', width: 140 },
    { title: '物料ID', dataIndex: 'material_id', key: 'mid', width: 120 },
    { title: '批次号', dataIndex: 'batch_code', key: 'batch', width: 120, render: (v: string) => v || '-' },
    {
      title: '总库存', dataIndex: 'total_qty', key: 'total', width: 90,
      sorter: (a: InventoryItem, b: InventoryItem) => a.total_qty - b.total_qty,
    },
    {
      title: '可用', dataIndex: 'available_qty', key: 'available', width: 90,
      render: (v: number) => (
        <span style={{ color: v < LOW_STOCK_THRESHOLD ? '#f5222d' : '#52c41a', fontWeight: 500 }}>
          {v < LOW_STOCK_THRESHOLD && <WarningOutlined style={{ marginRight: 4 }} />}{v}
        </span>
      ),
      sorter: (a: InventoryItem, b: InventoryItem) => a.available_qty - b.available_qty,
    },
    { title: '预留', dataIndex: 'reserved_qty', key: 'reserved', width: 80 },
    {
      title: '单位成本', dataIndex: 'unit_cost', key: 'cost', width: 100,
      render: (v: number) => v != null ? `¥${Number(v).toFixed(2)}` : '-',
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => statusTag(s),
    },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated', width: 130, render: (v: string) => v ? dayjs(v).format('MM-DD HH:mm') : '-' },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>库存管理</h2>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.available())}>
            <Statistic title="可用库存总量" value={totalAvailable} valueStyle={{ color: '#1890ff' }} />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.reserved())}>
            <Statistic title="预留总量" value={totalReserved} valueStyle={{ color: '#faad14' }} />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.lowStock())}>
            <Statistic title="低库存物料" value={lowStockCount} valueStyle={{ color: lowStockCount > 0 ? '#f5222d' : undefined }} suffix="项" />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
      </Row>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input
            placeholder="物料编码" prefix={<SearchOutlined />} style={{ width: 180 }}
            allowClear value={search} onChange={(e) => setSearch(e.target.value)}
            onPressEnter={() => { setPage(1); fetchData() }}
          />
          <Select placeholder="状态" style={{ width: 120 }} allowClear value={statusFilter} onChange={(v) => { setStatusFilter(v); setPage(1) }}>
            <Option value="available">正常</Option>
            <Option value="low_stock">低库存</Option>
            <Option value="frozen">冻结</Option>
          </Select>
          <Button type="primary" onClick={() => { setPage(1); fetchData() }}>查询</Button>
          <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
        </Space>
      </Card>

      <Table
        columns={columns}
        dataSource={data.map((item, i) => ({ ...item, key: item.id || i }))}
        loading={loading}
        size="middle"
        rowClassName={(r: InventoryItem) => r.available_qty < LOW_STOCK_THRESHOLD ? 'row-low-stock' : ''}
        onRow={(r) => ({ onClick: () => setDetail(r), style: { cursor: 'pointer' } })}
        pagination={{
          current: page, pageSize: 20, total, showTotal: (t) => `共 ${t} 条`,
          onChange: (p) => setPage(p),
        }}
      />

      {/* 追溯：统计数字下钻抽屉 */}
      {drill && (
        <DrillDownDrawer
          open
          onClose={() => setDrill(null)}
          title={drill.title}
          headline={drill.headline}
          formula={drill.formula}
          columns={drill.columns}
          records={drill.records}
          onRowClick={drill.onRowClick}
        />
      )}

      {/* 追溯：库存详情 */}
      <RecordDetailDrawer
        open={!!detail}
        onClose={() => setDetail(null)}
        title="库存详情"
        record={detail}
        fields={detailFields}
      />
    </div>
  )
}

export default InventoryList
