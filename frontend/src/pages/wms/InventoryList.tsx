import React from 'react'
import { Table, Input, Button, Card, Space, Tag } from 'antd'
import { SearchOutlined } from '@ant-design/icons'

const InventoryList: React.FC = () => {
  const columns = [
    { title: '物料编码', dataIndex: 'code', key: 'code' },
    { title: '物料名称', dataIndex: 'name', key: 'name' },
    { title: '仓库', dataIndex: 'warehouse', key: 'warehouse' },
    { title: '总库存', dataIndex: 'total', key: 'total' },
    { title: '可用库存', dataIndex: 'available', key: 'available' },
    { title: '预留', dataIndex: 'reserved', key: 'reserved' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (status: string) => (
      <Tag color={status === '正常' ? 'success' : 'warning'}>{status}</Tag>
    )},
    { title: '操作', key: 'action', render: () => (
      <Button type="link" size="small">明细</Button>
    )},
  ]

  const data = [
    { key: '1', code: 'RES-10K-0603', name: '贴片电阻10K', warehouse: '原料仓', total: 50000, available: 48000, reserved: 2000, status: '正常' },
    { key: '2', code: 'CAP-100NF-0603', name: '贴片电容100NF', warehouse: '原料仓', total: 30000, available: 25000, reserved: 5000, status: '正常' },
    { key: '3', code: 'PCBA-A001', name: '主板组件A001', warehouse: '成品仓', total: 500, available: 300, reserved: 200, status: '预警' },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: '24px' }}>库存管理</h2>
      
      <Card style={{ marginBottom: '24px' }}>
        <Space>
          <Input placeholder="物料编码/名称" prefix={<SearchOutlined />} style={{ width: 200 }} />
          <Button type="primary">查询</Button>
          <Button>入库</Button>
          <Button>出库</Button>
          <Button>盘点</Button>
        </Space>
      </Card>

      <Table columns={columns} dataSource={data} rowKey="key" />
    </div>
  )
}

export default InventoryList
