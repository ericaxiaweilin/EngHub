import React, { useState } from 'react'
import { Form, Input, InputNumber, Select, Button, Card, Radio, Space, message } from 'antd'

const { Option } = Select

const ProductionReport: React.FC = () => {
  const [form] = Form.useForm()
  const [reportType, setReportType] = useState('normal')

  const onFinish = (values: any) => {
    console.log('报工数据:', values)
    message.success('报工提交成功')
  }

  return (
    <div>
      <h2 style={{ marginBottom: '24px' }}>生产报工</h2>
      
      <Card style={{ maxWidth: '600px' }}>
        <Form
          form={form}
          layout="vertical"
          onFinish={onFinish}
          initialValues={{ report_type: 'normal', shift: 'day', good_qty: 0, defect_qty: 0 }}
        >
          <Form.Item label="报工类型">
            <Radio.Group value={reportType} onChange={(e) => setReportType(e.target.value)}>
              <Radio.Button value="normal">正常报工</Radio.Button>
              <Radio.Button value="additional">补报</Radio.Button>
              <Radio.Button value="rework">返工</Radio.Button>
            </Radio.Group>
          </Form.Item>

          <Form.Item label="工单号" name="work_order_id" rules={[{ required: true }]}>
            <Input placeholder="扫描或输入工单号" />
          </Form.Item>

          <Form.Item label="工位" name="station_id" rules={[{ required: true }]}>
            <Select placeholder="选择工位">
              <Option value="SMT-01">SMT-01</Option>
              <Option value="ASM-01">ASM-01</Option>
              <Option value="TST-01">TST-01</Option>
            </Select>
          </Form.Item>

          <Form.Item label="班次" name="shift">
            <Radio.Group>
              <Radio.Button value="day">白班</Radio.Button>
              <Radio.Button value="night">夜班</Radio.Button>
            </Radio.Group>
          </Form.Item>

          <Space size="large">
            <Form.Item label="良品数" name="good_qty" rules={[{ required: true }]}>
              <InputNumber min={0} style={{ width: '120px' }} />
            </Form.Item>

            <Form.Item label="不良数" name="defect_qty">
              <InputNumber min={0} style={{ width: '120px' }} />
            </Form.Item>
          </Space>

          <Form.Item label="备注" name="remark">
            <Input.TextArea rows={2} placeholder="如有不良品，请说明不良类型" />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" size="large" block>
              提交报工
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Card title="今日报工记录" style={{ marginTop: '24px' }}>
        <p style={{ color: '#999' }}>暂无记录</p>
      </Card>
    </div>
  )
}

export default ProductionReport
