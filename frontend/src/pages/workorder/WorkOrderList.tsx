import React, { useState } from 'react'
import { Table, Button, Input, Select, Tag, Space, Card } from 'antd'
import { PlusOutlined, SearchOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'

const { Option } = Select

const WorkOrderList: React.FC = () => {
  const [status, setStatus] = useState<string>('')

  const columns = [
    { title: '工单号', dataIndex: 'code', key: 'code', render: (text: string, record: any) => (
      <Link to={`/work-orders/${record.id}`}>{text}</Link>
    )},
    { title: '产品', dataIndex: 'product', key: 'product' },
    { title: '计划数量', dataIndex: 'planned_qty', key: 'planned_qty' },
    { title: '完成数量', dataIndex: 'completed_qty', key: 'completed_qty' },
    { title: '交期', dataIndex: 'due_date', key: 'due_date' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (status: string) => {
      const colorMap: Record<string, string> = {
        'draft': 'default',
        'pending': 'processing',
        'in_progress': 'success',
        'completed': 'default',
        'cancelled': 'error',
      }
      const textMap: Record<string, string> = {
        'draft': '草稿',
        'pending': '待生产',
        'in_progress': '生产中',
        'completed': '已完成',
        'cancelled': '已取消',
      }
      return <Tag color={colorMap[status]}>{textMap[status] || status}</Tag>
    }},
    { title: '操作', key: 'action', render: () => (
      <Space>
        <Button type="link" size="small">编辑</Button>
        <Button type="link" size="small">下达</Button>
      </Space>
    )},
  ]

  const data = [
    { id: '1', code: 'WO-20260224-001', product: 'PCBA-A001', planned_qty: 1000, completed_qty: 850, due_date: '2026-02-28', status: 'in_progress' },
    { id: '2', code: 'WO-20260224-002', product: 'PCBA-A002', planned_qty: 500, completed_qty: 0, due_date: '2026-03-01', status: 'pending' },
    { id: '3', code: 'WO-20260224-003', product: 'PCBA-A003', planned_qty: 2000, completed_qty: 2000, due_date: '2026-02-20', status: 'completed' },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: '24px' }}>工单管理</h2>
      
      <Card style={{ marginBottom: '24px' }}>
        <Space>
          <Input placeholder="工单号/产品" prefix={<SearchOutlined />} style={{ width: 200 }} />
          <Select placeholder="状态" style={{ width: 120 }} value={status} onChange={setStatus} allowClear>
            <Option value="draft">草稿</Option>
            <Option value="pending">待生产</Option>
            <Option value="in_progress">生产中</Option>
            <Option value="completed">已完成</Option>
          </Select>
          <Button type="primary">查询</Button>
          <Button type="primary" icon={<PlusOutlined />}>新建工单</Button>
        </Space>
      </Card>

      <Table columns={columns} dataSource={data} rowKey="id" />
    </div>
  )
}

export default WorkOrderList
