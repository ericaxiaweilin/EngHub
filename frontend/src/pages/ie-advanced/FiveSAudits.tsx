import React, { useEffect, useState } from 'react'
import { Card, Table, Button, Tag, Space, message, Empty, Row, Col, InputNumber, Select, DatePicker, Form, message as antMessage } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import { API_ENDPOINTS } from '../../../config/api'

interface FiveSAudit {
  id: string
  work_center_id: string
  audit_date: string
  total_score: number
  score_percentage: number
}

const FiveSAudits: React.FC = () => {
  const [workCenter, setWorkCenter] = useState('WC001')
  const [factory, setFactory] = useState('F001')
  const [data, setData] = useState<FiveSAudit[]>([])
  const [loading, setLoading] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [form] = Form.useForm()

  const fetchData = async () => {
    setLoading(true)
    try {
      const res = await fetch(`http://localhost:8000/api/v1/ie-advanced/5s-audits/work-centers/${work_center}?factory_id=${factory}&limit=50`)
      // Simplified - backend may return different structure
      const result = await res.json()
      setData(Array.isArray(result) ? result : [])
    } catch (e) {
      console.error('Error fetching 5S audits', e)
      setData([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [workCenter, factory])

  const columns: ColumnsType<FiveSAudit> = [
    { title: '工站ID', dataIndex: 'work_center_id', key: 'work_center_id', width: 120 },
    { title: '审计日期', dataIndex: 'audit_date', key: 'audit_date', width: 120, render: (val: string) => dayjs(val).format('YYYY-MM-DD') },
    { title: '总分', dataIndex: 'total_score', key: 'total_score', width: 100, render: (val: number) => `${val}/100` },
    { title: '得分率', dataIndex: 'score_percentage', key: 'score_percentage', width: 100, render: (val: number) => <Tag color={val > 90 ? 'green' : val > 75 ? 'blue' : 'orange'}>{val.toFixed(1)}%</Tag> },
  ]

  const submitAudit = async () => {
    const values = form.getFieldsValue()
    antMessage.info('5S audit submission not implemented yet');
    setShowForm(false);
    form.resetFields();
  };

  return (
    <Card title="5S审核管理">
      <Row gutter={16} align="middle" style={{ marginBottom: 16 }}>
        <Col span={3}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setShowForm(true)}>
            新增审核
          </Button>
        </Col>
        <Col span={4}>
          <Select value={workCenter} onChange={setWorkCenter} style={{ width: 120 }}>
            <Select.Option value="WC001">工位 WC001</Select.Option>
            <Select.Option value="WC002">工位 WC002</Select.Option>
          </Select>
        </Col>
        <Col span={4}>
          <Select value={factory} onChange={setFactory} style={{ width: 120 }}>
            <Select.Option value="F001">F001 厂区</Select.Option>
          </Select>
        </Col>
        <Col span={3}>
          <Button type="link" onClick={fetchData}>刷新列表</Button>
        </Col>
      </Row>

      {showForm && (
        <Modal
          title="新建5S审核"
          open={true}
          okText="提交"
          onCancel={() => { setShowForm(false); form.resetFields(); }}
          onOk={submitAudit}
          footer={(_, { OkBtn }) => <OkBtn />}
        >
          <Form form={form} layout="vertical">
            <InputNumber label="审核工站" placeholder="输入工站ID" style={{ width: 200 }} />
            <DatePicker label="审核日期" style={{ width: 200 }} />
            <InputNumber label="整理(Seiri) 评分(0-20)" min={0} max={20} style={{ width: 200 }} />
            <InputNumber label="整顿(Seiton) 评分(0-20)" min={0} max={20} style={{ width: 200 }} />
            <InputNumber label="清扫(Seiso) 评分(0-20)" min={0} max={20} style={{ width: 200 }} />
            <InputNumber label="清洁(Seiketsu) 评分(0-20)" min={0} max={20} style={{ width: 200 }} />
            <InputNumber label="素养(Shitsuke) 评分(0-20)" min={0} max={20} style={{ width: 200 }} />
          </Form>
        </Modal>
      )}

      {data.length > 0 ? (
        <Table dataSource={data} columns={columns} loading={loading} pagination={{ pageSize: 10 }} rowKey="id" />
      ) : (
        <Empty description={loading ? '加载中...' : '暂无5S审核记录'} style={{ margin: '40px 0' }} />
      )}
    </Card>
  )
}

export default FiveSAudits