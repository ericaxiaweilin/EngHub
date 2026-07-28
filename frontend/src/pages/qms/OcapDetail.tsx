import React, { useEffect, useState } from 'react'
import { Button, Card, Form, Input, Select, message, Space } from 'antd'
import { useNavigate, useParams } from 'react-router-dom'
import { getDefect, updateDefectOCAP } from '../../services/mes'
import { getStoredUser } from '../../services/auth'

const { TextArea } = Input
const { Option } = Select

interface DefectWithOCAP extends Defect {
  ocap_status?: string
  ocap_trigger_reason?: string
  root_cause?: string
  corrective_action?: string
  preventive_action?: string
}

interface Defect {
  id: string
  defect_code?: string
  severity?: string
  description?: string
  root_cause?: string
  // ...其他字段
}

const OcapDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const user = getStoredUser()
  const [loading, setLoading] = useState(true)
  const [defect, setDefect] = useState<DefectWithOCAP | null>(null)
  const [form] = Form.useForm()

  useEffect(() => {
    if (!id) return
    setLoading(true)
    getDefect(id).then(data => {
      setDefect(data)
      form.setFieldsValue({
        ocapan_status: data.ocap_status || 'triggered',
        trigger_reason: data.ocap_trigger_reason || '',
        root_cause: data.root_cause || '',
        corrective_action: data.corrective_action || '',
        preventive_action: data.preventive_action || '',
      })
      setLoading(false)
    }).catch(() => {
      message.error('加载缺陷详情失败')
      setLoading(false)
      navigate('/qms/ocaps')
    })
  }, [id, navigate, form])

  const handleSubmit = async (values: any) => {
    try await updateDefectOCAP(id, values)
    message.success('OCAP信息已更新')
    navigate('/qms/ocaps')
  }

  if (!loading && !defect) return <div>缺陷不存在</div>

  return (
    <div style={{ padding: 24 }}>
      <Card title={`OCAP工作流 - ${defect?.defect_code || defect?.id}`}>
        <Form
          form={form}
          labelCol={{ span: 4 }}
          wrapperCol={{ span: 16 }}
          onSubmit={handleSubmit}
          layout="horizontal"
          disabled={loading}
        >
          <Form.Item label="OCAP状态" name="ocap_status" rules={[{ required: true }]} >
            <Select>
              <Option value="triggered">已触发</Option>
              <Option value="in_progress">处理中</Option>
              <Option value="closed">已关闭</Option>
            </Select>
          </Form.Item>
          <Form.Item label="触发原因" name="ocap_trigger_reason">
            <TextArea rows={4} placeholder="说明触发OCAP的具体原因" />
          </Form.Item>
          <Form.Item label="根因分析（5M1E）" name="root_cause">
            <TextArea rows={4} placeholder="从人、机、料、法、环、测角度分析根本原因" />
          </Form.Item>
          <Form.Item label="纠正措施" name="corrective_action">
            <TextArea rows={4} placeholder="针对当前问题的立即处置措施" />
          </Form.Item>
          <Form.Item label="预防措施" name="preventive_action">
            <TextArea rows={4} placeholder="防止问题再次发生的系统性改进" />
          </Form.Item>
          <Form.Item wrapperCol={{ offset: 4 }}>
            <Space>
              <Button type="primary" htmlType="submit">保存OCAP信息</Button>
              <Button onClick={() => navigate('/qms/ocaps')}>返回列表</Button>
            </Space>
          </Form.FormItem>
        </Form>
      </Card>
    </div>
  )
}

export default OcapDetail