import { Card, Form, Input, Select, Button, Table, message, Space } from 'antd'
import { SaveOutlined } from '@ant-design/icons'
import { useState } from 'react'

export default function ProductionReport() {
  const [form] = Form.useForm()
  const [reportData, setReportData] = useState<any[]>([])

  const columns = [
    { title: '工单号', dataIndex: 'work_order_code', key: 'work_order_code' },
    { title: '工位', dataIndex: 'workstation', key: 'workstation' },
    { title: '良品数量', dataIndex: 'good_quantity', key: 'good_quantity' },
    { title: '不良品数量', dataIndex: 'defect_quantity', key: 'defect_quantity' },
    { title: '报废数量', dataIndex: 'scrap_quantity', key: 'scrap_quantity' },
    { title: '操作员', dataIndex: 'operator', key: 'operator' },
    { title: '报工时间', dataIndex: 'report_time', key: 'report_time' },
  ]

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      console.log('报工数据:', values)
      
      // 模拟提交成功
      setReportData([
        ...reportData,
        {
          ...values,
          report_time: new Date().toLocaleString(),
        },
      ])
      
      message.success('报工成功！')
      form.resetFields()
    } catch (error) {
      console.error('验证失败:', error)
    }
  }

  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>生产报工</h1>

      <Card title="报工录入" style={{ marginBottom: 24 }}>
        <Form form={form} layout="inline">
          <Form.Item name="work_order_code" label="工单号" rules={[{ required: true }]}>
            <Input placeholder="请输入工单号" />
          </Form.Item>
          <Form.Item name="workstation" label="工位" rules={[{ required: true }]}>
            <Select style={{ width: 150 }}>
              <Select.Option value="WS-001">WS-001</Select.Option>
              <Select.Option value="WS-002">WS-002</Select.Option>
              <Select.Option value="WS-003">WS-003</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="good_quantity" label="良品数" rules={[{ required: true }]}>
            <Input type="number" style={{ width: 100 }} placeholder="0" />
          </Form.Item>
          <Form.Item name="defect_quantity" label="不良品数" rules={[{ required: true }]}>
            <Input type="number" style={{ width: 100 }} placeholder="0" />
          </Form.Item>
          <Form.Item name="scrap_quantity" label="报废数" rules={[{ required: true }]}>
            <Input type="number" style={{ width: 100 }} placeholder="0" />
          </Form.Item>
          <Form.Item name="operator" label="操作员" rules={[{ required: true }]}>
            <Input placeholder="请输入操作员" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" icon={<SaveOutlined />} onClick={handleSubmit}>
              提交报工
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Card title="报工记录">
        <Table
          columns={columns}
          dataSource={reportData}
          rowKey={(record, index) => index.toString()}
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </div>
  )
}
