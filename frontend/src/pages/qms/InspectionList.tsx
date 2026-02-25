import React, { useState } from 'react'
import { Table, Button, Select, Tag, Card, Space, Modal, Form, Input, InputNumber } from 'antd'
import { PlusOutlined } from '@ant-design/icons'

const { Option } = Select

const InspectionList: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [form] = Form.useForm()

  const columns = [
    { title: '检验单号', dataIndex: 'code', key: 'code' },
    { title: '类型', dataIndex: 'type', key: 'type', render: (type: string) => {
      const typeMap: Record<string, string> = { iqc: '来料', ipqc: '过程', fqc: '成品', oqc: '出货' }
      return typeMap[type] || type
    }},
    { title: '物料/产品', dataIndex: 'material', key: 'material' },
    { title: '批次', dataIndex: 'batch', key: 'batch' },
    { title: '批量', dataIndex: 'batch_size', key: 'batch_size' },
    { title: '不良数', dataIndex: 'defect_qty', key: 'defect_qty' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (status: string) => {
      const colorMap: Record<string, string> = { pending: 'default', passed: 'success', failed: 'error' }
      const textMap: Record<string, string> = { pending: '待检', passed: '合格', failed: '不合格' }
      return <Tag color={colorMap[status]}>{textMap[status]}</Tag>
    }},
    { title: '操作', key: 'action', render: () => (
      <Button type="link" size="small">录入结果</Button>
    )},
  ]

  const data = [
    { key: '1', code: 'INS-IQC-001', type: 'iqc', material: 'RES-10K-0603', batch: 'BATCH-001', batch_size: 10000, defect_qty: 0, status: 'pending' },
    { key: '2', code: 'INS-IPQC-001', type: 'ipqc', material: 'PCBA-A001', batch: 'WO-001', batch_size: 1000, defect_qty: 5, status: 'failed' },
  ]

  const handleSubmit = (values: any) => {
    console.log('新建检验单:', values)
    setIsModalOpen(false)
    form.resetFields()
  }

  return (
    <div>
      <h2 style={{ marginBottom: '24px' }}>检验管理</h2>
      
      <Card style={{ marginBottom: '24px' }}>
        <Space>
          <Select placeholder="检验类型" style={{ width: 120 }} allowClear>
            <Option value="iqc">来料检验</Option>
            <Option value="ipqc">过程检验</Option>
            <Option value="fqc">成品检验</Option>
            <Option value="oqc">出货检验</Option>
          </Select>
          <Select placeholder="状态" style={{ width: 120 }} allowClear>
            <Option value="pending">待检</Option>
            <Option value="passed">合格</Option>
            <Option value="failed">不合格</Option>
          </Select>
          <Button type="primary">查询</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsModalOpen(true)}>
            新建检验单
          </Button>
        </Space>
      </Card>

      <Table columns={columns} dataSource={data} rowKey="key" />

      <Modal
        title="新建检验单"
        open={isModalOpen}
        onCancel={() => setIsModalOpen(false)}
        footer={null}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item label="检验类型" name="inspection_type" rules={[{ required: true }]}>
            <Select placeholder="选择类型">
              <Option value="iqc">来料检验 (IQC)</Option>
              <Option value="ipqc">过程检验 (IPQC)</Option>
              <Option value="fqc">成品检验 (FQC)</Option>
              <Option value="oqc">出货检验 (OQC)</Option>
            </Select>
          </Form.Item>
          <Form.Item label="物料/产品" name="material_id" rules={[{ required: true }]}>
            <Input placeholder="输入物料编码" />
          </Form.Item>
          <Form.Item label="批次号" name="batch_id">
            <Input placeholder="输入批次号" />
          </Form.Item>
          <Form.Item label="批量" name="batch_size" rules={[{ required: true }]}>
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" block>创建</Button>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default InspectionList
