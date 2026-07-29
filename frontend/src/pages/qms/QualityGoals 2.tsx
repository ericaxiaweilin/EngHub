import React, { useEffect, useState, useCallback } from 'react'
import {
  Card, Row, Col, Tag, Space, Statistic, Empty, Spin, Progress, Button,
  Modal, Form, Input, InputNumber, Select, message,
} from 'antd'
import {
  AimOutlined, PlusOutlined, WarningOutlined,
  TrophyOutlined, LineChartOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../../services/api'

const FACTORY = 'F001'

const metricLabels: Record<string, string> = {
  yield_rate: '良品率',
  defect_ppm: '缺陷PPM',
  customer_complaint: '客诉次数',
  inspection_pass: '检验通过率',
}

const QualityGoals: React.FC = () => {
  const [goals, setGoals] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [createModal, setCreateModal] = useState(false)
  const [reviewModal, setReviewModal] = useState<any>(null)
  const [form] = Form.useForm()
  const [reviewForm] = Form.useForm()

  const loadGoals = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/qms/goals', { params: { factory_id: FACTORY } })
      setGoals(res.items || res || [])
    } catch { setGoals([]) } finally { setLoading(false) }
  }, [])

  useEffect(() => { loadGoals() }, [loadGoals])

  const handleCreate = async () => {
    const vals = await form.validateFields()
    try {
      await api.post('/api/v1/qms/goals', { ...vals, factory_id: FACTORY })
      message.success('质量目标创建成功')
      setCreateModal(false)
      form.resetFields()
      loadGoals()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '创建失败')
    }
  }

  const handleReview = async () => {
    const vals = await reviewForm.validateFields()
    try {
      await api.post(`/api/v1/qms/goals/${reviewModal.id}/review`, vals)
      message.success('评审已提交')
      setReviewModal(null)
      reviewForm.resetFields()
      loadGoals()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '提交失败')
    }
  }

  // 达成率计算
  const getAchievement = (goal: any) => {
    if (!goal.current_value && goal.current_value !== 0) return null
    if (goal.metric_type === 'defect_ppm' || goal.metric_type === 'customer_complaint') {
      // 越低越好
      return goal.current_value <= goal.target_value ? 100 : Math.max(0, Math.round((1 - (goal.current_value - goal.target_value) / goal.target_value) * 100))
    }
    // 越高越好
    return Math.min(100, Math.round((goal.current_value / goal.target_value) * 100))
  }

  return (
    <div>
      {/* 标题栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Space>
          <AimOutlined style={{ fontSize: 22, color: '#722ed1' }} />
          <span style={{ fontSize: 18, fontWeight: 700 }}>质量目标管理</span>
          <Tag color="purple">{goals.length} 项目标</Tag>
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModal(true)}>
          新建目标
        </Button>
      </div>

      <Spin spinning={loading}>
        {goals.length === 0 ? (
          <Empty description="暂无质量目标，点击「新建目标」设定第一个质量KPI" style={{ marginTop: 60 }} />
        ) : (
          <Row gutter={[16, 16]}>
            {goals.map((goal) => {
              const achievement = getAchievement(goal)
              const isGood = achievement !== null && achievement >= 100
              const isRisk = achievement !== null && achievement >= 70 && achievement < 100
              const isBad = achievement !== null && achievement < 70
              const ringColor = isGood ? '#52c41a' : isRisk ? '#faad14' : isBad ? '#f5222d' : '#1890ff'

              return (
                <Col key={goal.id} xs={24} sm={12} lg={8}>
                  <Card
                    hoverable
                    style={{ borderRadius: 12, border: `1px solid ${isGood ? '#b7eb8f' : isBad ? '#ffccc7' : '#f0f0f0'}` }}
                    bodyStyle={{ padding: 20 }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>{goal.goal_name}</div>
                        <Space size={4}>
                          <Tag color="blue">{metricLabels[goal.metric_type] || goal.metric_type}</Tag>
                          <Tag>{goal.period === 'monthly' ? '月度' : goal.period === 'quarterly' ? '季度' : goal.period}</Tag>
                        </Space>
                      </div>
                      {achievement !== null && (
                        <Progress
                          type="circle"
                          size={64}
                          percent={achievement}
                          strokeColor={ringColor}
                          format={(p) => <span style={{ fontSize: 14, fontWeight: 700, color: ringColor }}>{p}%</span>}
                        />
                      )}
                    </div>

                    {/* 目标 vs 实际 */}
                    <Row gutter={16} style={{ marginTop: 16 }}>
                      <Col span={8}>
                        <Statistic title="目标值" value={goal.target_value} suffix={goal.unit} valueStyle={{ fontSize: 16 }} />
                      </Col>
                      <Col span={8}>
                        <Statistic
                          title="当前值"
                          value={goal.current_value ?? '-'}
                          suffix={goal.current_value !== null ? goal.unit : ''}
                          valueStyle={{ fontSize: 16, color: ringColor }}
                        />
                      </Col>
                      <Col span={8}>
                        <Statistic
                          title="状态"
                          value={isGood ? '达标' : isRisk ? '风险' : isBad ? '落后' : '待评'}
                          valueStyle={{ fontSize: 16, color: ringColor }}
                          prefix={isGood ? <TrophyOutlined /> : isBad ? <WarningOutlined /> : <LineChartOutlined />}
                        />
                      </Col>
                    </Row>

                    {/* 底部操作 */}
                    <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: 12, color: '#999' }}>
                        {goal.responsible && `负责人: ${goal.responsible}`}
                        {goal.last_reviewed_at && ` | 上次评审: ${dayjs(goal.last_reviewed_at).format('MM-DD')}`}
                      </span>
                      <Button size="small" type="link" onClick={() => { setReviewModal(goal); reviewForm.setFieldsValue({ measured_value: goal.current_value }) }}>
                        评审
                      </Button>
                    </div>
                  </Card>
                </Col>
              )
            })}
          </Row>
        )}
      </Spin>

      {/* 创建目标 Modal */}
      <Modal title="新建质量目标" open={createModal} onOk={handleCreate} onCancel={() => setCreateModal(false)} okText="创建">
        <Form form={form} layout="vertical">
          <Form.Item name="goal_name" label="目标名称" rules={[{ required: true }]}>
            <Input placeholder="如：月度成品良品率 ≥ 99%" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="metric_type" label="指标类型" rules={[{ required: true }]}>
                <Select options={Object.entries(metricLabels).map(([v, l]) => ({ value: v, label: l }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="period" label="周期" initialValue="monthly">
                <Select options={[{ value: 'daily', label: '日' }, { value: 'weekly', label: '周' }, { value: 'monthly', label: '月' }, { value: 'quarterly', label: '季' }]} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="target_value" label="目标值" rules={[{ required: true }]}>
                <InputNumber style={{ width: '100%' }} placeholder="99" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="unit" label="单位" initialValue="%">
                <Select options={[{ value: '%', label: '%' }, { value: 'ppm', label: 'PPM' }, { value: '次', label: '次' }]} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="responsible" label="负责人">
            <Input placeholder="品质课长" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 评审 Modal */}
      <Modal title={`评审: ${reviewModal?.goal_name || ''}`} open={!!reviewModal} onOk={handleReview} onCancel={() => setReviewModal(null)} okText="提交评审">
        <Form form={reviewForm} layout="vertical">
          <Form.Item name="measured_value" label="实测值" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="status" label="判定" initialValue="on_track">
            <Select options={[
              { value: 'on_track', label: '✅ 达标' },
              { value: 'at_risk', label: '⚠️ 风险' },
              { value: 'off_track', label: '❌ 落后' },
            ]} />
          </Form.Item>
          <Form.Item name="action_plan" label="改善措施">
            <Input.TextArea rows={3} placeholder="如不达标，填写改善计划" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default QualityGoals
