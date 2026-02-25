import React from 'react'
import { Table, Tag, Button, Card, Space, Select } from 'antd'

const { Option } = Select

const DefectList: React.FC = () => {
  const columns = [
    { title: '不良单号', dataIndex: 'code', key: 'code' },
    { title: '来源', dataIndex: 'source', key: 'source' },
    { title: '不良类型', dataIndex: 'defect_type', key: 'defect_type' },
    { title: '数量', dataIndex: 'qty', key: 'qty' },
    { title: '严重等级', dataIndex: 'severity', key: 'severity', render: (severity: string) => {
      const colorMap: Record<string, string> = { critical: 'red', major: 'orange', minor: 'default' }
      const textMap: Record<string, string> = { critical: '致命', major: '重大', minor: '轻微' }
      return <Tag color={colorMap[severity]}>{textMap[severity]}</Tag>
    }},
    { title: '状态', dataIndex: 'status', key: 'status', render: (status: string) => {
      const colorMap: Record<string, string> = { open: 'error', in_progress: 'processing', resolved: 'success' }
      const textMap: Record<string, string> = { open: '待处理', in_progress: '处理中', resolved: '已解决' }
      return <Tag color={colorMap[status]}>{textMap[status]}</Tag>
    }},
    { title: '处置方式', dataIndex: 'disposition', key: 'disposition', render: (d: string) => d || '-' },
    { title: '操作', key: 'action', render: () => (
      <Button type="link" size="small">处理</Button>
    )},
  ]

  const data = [
    { key: '1', code: 'DEF-001', source: 'INS-IPQC-001', defect_type: '外观缺陷', qty: 5, severity: 'minor', status: 'open', disposition: '' },
    { key: '2', code: 'DEF-002', source: 'WO-001', defect_type: '功能不良', qty: 2, severity: 'major', status: 'in_progress', disposition: 'rework' },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: '24px' }}>不良品管理</h2>
      
      <Card style={{ marginBottom: '24px' }}>
        <Space>
          <Select placeholder="状态" style={{ width: 120 }} allowClear>
            <Option value="open">待处理</Option>
            <Option value="in_progress">处理中</Option>
            <Option value="resolved">已解决</Option>
          </Select>
          <Select placeholder="严重等级" style={{ width: 120 }} allowClear>
            <Option value="critical">致命</Option>
            <Option value="major">重大</Option>
            <Option value="minor">轻微</Option>
          </Select>
          <Button type="primary">查询</Button>
        </Space>
      </Card>

      <Table columns={columns} dataSource={data} rowKey="key" />
    </div>
  )
}

export default DefectList
