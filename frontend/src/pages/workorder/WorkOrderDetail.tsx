import React from 'react'
import { useParams } from 'react-router-dom'
import { Card, Descriptions, Tag, Button, Space, Table, Steps } from 'antd'

const { Step } = Steps

const WorkOrderDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()

  const materialColumns = [
    { title: '物料编码', dataIndex: 'code', key: 'code' },
    { title: '物料名称', dataIndex: 'name', key: 'name' },
    { title: '需求数量', dataIndex: 'required', key: 'required' },
    { title: '已发数量', dataIndex: 'issued', key: 'issued' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (status: string) => (
      <Tag color={status === '齐套' ? 'success' : 'warning'}>{status}</Tag>
    )},
  ]

  const materialData = [
    { key: '1', code: 'RES-10K-0603', name: '贴片电阻10K', required: 10000, issued: 10000, status: '齐套' },
    { key: '2', code: 'CAP-100NF-0603', name: '贴片电容100NF', required: 5000, issued: 3000, status: '欠料' },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: '24px' }}>工单详情 #{id}</h2>
      
      <Card style={{ marginBottom: '24px' }}>
        <Descriptions title="基本信息" bordered column={3}>
          <Descriptions.Item label="工单号">WO-20260224-001</Descriptions.Item>
          <Descriptions.Item label="产品">PCBA-A001</Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color="success">生产中</Tag></Descriptions.Item>
          <Descriptions.Item label="计划数量">1000</Descriptions.Item>
          <Descriptions.Item label="完成数量">850</Descriptions.Item>
          <Descriptions.Item label="良品率">98.5%</Descriptions.Item>
          <Descriptions.Item label="计划交期">2026-02-28</Descriptions.Item>
          <Descriptions.Item label="产线">SMT-01</Descriptions.Item>
          <Descriptions.Item label="优先级">高</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card style={{ marginBottom: '24px' }}>
        <Steps current={1}>
          <Step title="创建" description="2026-02-20" />
          <Step title="下达" description="2026-02-21" />
          <Step title="开工" description="2026-02-22" />
          <Step title="完工" />
          <Step title="入库" />
        </Steps>
      </Card>

      <Card title="物料清单" style={{ marginBottom: '24px' }}>
        <Table columns={materialColumns} dataSource={materialData} pagination={false} size="small" />
      </Card>

      <Space>
        <Button type="primary">报工</Button>
        <Button>拆分工单</Button>
        <Button danger>取消工单</Button>
      </Space>
    </div>
  )
}

export default WorkOrderDetail
