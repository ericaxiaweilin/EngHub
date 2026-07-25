

/**
 * v2.6 - 三位一体调度系统前端 UI
 * RCC + 参数化面板 + Chatbot工单
 */

import React, { useState, useEffect } from 'react'
import { Card, Tabs, Table, Button, Space, Tag, Descriptions, Modal, Form, Input, Select, message, Tree, Breadcrumb, Alert } from 'antd'
import { SettingOutlined, RobotOutlined, TeamOutlined, CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined, SwapOutlined, SafetyOutlined, ThunderboltOutlined } from '@ant-design/icons'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1/rcc'

export default function RCCDashboard() {
  const [selectedOrg, setSelectedOrg] = useState('rcc-root')
  const [orgTree, setOrgTree] = useState([])
  const [params, setParams] = useState([])
  const [rccTasks, setRccTasks] = useState([])
  const [chatbotTickets, setChatbotTickets] = useState([])
  const [logicChains, setLogicChains] = useState([])
  const [selectedParam, setSelectedParam] = useState(null)
  const [newTicketVisible, setNewTicketVisible] = useState(false)
  const [newTicketForm] = Form.useForm()

  useEffect(() => {
    fetchOrgTree()
    fetchParams()
    fetchTasks()
    fetchTickets()
    fetchLogicChains()
  }, [])

  const fetchOrgTree = async () => {
    try {
      // 简化版：使用预设组织树
      setOrgTree([
        { title: 'RCC 资源控制中心', key: 'rcc-root', children: [
          { title: '产线A', key: 'line-a', children: [
            { title: 'SMT贴片工位01', key: 'smt-station-01' },
            { title: 'CNC加工中心01', key: 'cnc-station-01' },
          ]},
          { title: '产线B', key: 'line-b' },
          { title: '品质部', key: 'quality-dept' },
          { title: '人力资源部', key: 'hr-office' },
        ]}
      ])
    } catch (err) {
      console.error('获取组织树失败:', err)
    }
  }

  const fetchParams = async () => {
    try {
      const res = await axios.get(`${API_BASE}/params`)
      setParams(res.data.items || [])
    } catch (err) {
      console.error('获取参数失败:', err)
    }
  }

  const fetchTasks = async () => {
    try {
      const res = await axios.get(`${API_BASE}/tasks`)
      setRccTasks(res.data.items || [])
    } catch (err) {
      console.error('获取RCC任务失败:', err)
    }
  }

  const fetchTickets = async () => {
    try {
      const res = await axios.get(`${API_BASE}/chatbot/tickets`)
      setChatbotTickets(res.data.items || [])
    } catch (err) {
      console.error('获取Chatbot工单失败:', err)
    }
  }

  const fetchLogicChains = async () => {
    try {
      const res = await axios.get(`${API_BASE}/logic-chains`)
      setLogicChains(res.data.items || [])
    } catch (err) {
      console.error('获取逻辑链失败:', err)
    }
  }

  const handleAdjustParam = async (paramId: string, newValue: string, reason: string) => {
    try {
      await axios.put(`${API_BASE}/params/${paramId}`, {
        new_value: newValue,
        changed_by: "user",
        reason: reason,
        source: "panel",
      })
      message.success('参数调整成功')
      fetchParams()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '参数调整失败')
    }
  }

  const handleCreateTicket = async (values: any) => {
    try {
      await axios.post(`${API_BASE}/chatbot/tickets/create`, {
        message: values.message,
        requester_id: "user",
        ticket_type: values.ticket_type,
        parsed_intents: {},
        parsed_slots: {},
      })
      message.success('Chatbot工单创建成功')
      newTicketForm.resetFields()
      setNewTicketVisible(false)
      fetchTickets()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '创建失败')
    }
  }

  const paramSensitivityColor = (sensitivity: string) => {
    switch(sensitivity) {
      case 'low': return 'green'
      case 'normal': return 'blue'
      case 'high': return 'orange'
      case 'strategic': return 'red'
      default: return 'default'
    }
  }

  const rccTaskStatusColor = (status: string) => {
    switch(status) {
      case 'pending': return 'orange'
      case 'approved': return 'green'
      case 'rejected': return 'red'
      case 'executing': return 'processing'
      case 'completed': return 'success'
      default: return 'default'
    }
  }

  return (
    <Card title="🔗 EngHub v2.6 — 三位一体调度系统">
      <Breadcrumb items={[
        { title: '首页' },
        { title: 'RCC资源控制中心' },
        { title: selectedOrg === 'rcc-root' ? '全局视图' : selectedOrg },
      ]} />

      <Tabs defaultActiveKey="overview">
        {/* Tab 1: 总览 */}
        <Tabs.TabPane tab="📊 总览" key="overview">
          <Space wrap style={{ marginBottom: 16 }}>
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => fetchParams()}>刷新参数</Button>
            <Button icon={<SwapOutlined />} onClick={() => fetchTasks()}>刷新RCC任务</Button>
            <Button icon={<RobotOutlined />} onClick={() => fetchTickets()}>刷新Chatbot工单</Button>
            <Button icon={<SafetyOutlined />} onClick={() => fetchLogicChains()}>刷新逻辑链</Button>
            <Button type="dashed" icon={<SettingOutlined />} onClick={() => setNewTicketVisible(true)}>新建Chatbot工单</Button>
          </Space>

          <Row gutter={16}>
            <Col span={6}>
              <Card size="small">
                <Statistic title="可调参数数" value={params.length} prefix={<SettingOutlined />} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="待审批RCC任务" value={rccTasks.filter(t => t.status === 'pending').length} prefix={<ClockCircleOutlined />} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="活跃Chatbot工单" value={chatbotTickets.filter(t => t.status === 'open').length} prefix={<RobotOutlined />} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="激活逻辑链" value={logicChains.filter(c => c.enabled).length} prefix={<SafetyOutlined />} />
              </Card>
            </Col>
          </Row>
        </Tabs.TabPane>

        {/* Tab 2: 参数化面板 */}
        <Tabs.TabPane tab="⚙️ 参数化面板" key="parameters">
          <Table
            dataSource={params}
            rowKey="id"
            pagination={false}
            size="small"
            columns={[
              { title: '参数代码', dataIndex: 'param_code', width: 200 },
              { title: '参数名称', dataIndex: 'param_name', width: 200 },
              { title: '类别', dataIndex: 'category', width: 100, render: (cat: string) => <Tag color="blue">{cat}</Tag> },
              { title: '类型', dataIndex: 'param_type', width: 80 },
              { title: '当前值', dataIndex: 'current_value', width: 150 },
              { title: '目标值', dataIndex: 'target_value', width: 150 },
              { title: '敏感度', dataIndex: 'sensitivity', width: 80, render: (s: string) => <Tag color={paramSensitivityColor(s)}>{s}</Tag> },
              { title: '修改人', dataIndex: 'changed_by', width: 100 },
              { title: '操作', key: 'action', width: 100, render: (_, record: any) => (
                <Space>
                  <Button size="small" type="link" onClick={() => setSelectedParam(record)}>调整</Button>
                  <Button size="small" type="link" onClick={() => handleAnalyzeImpact(record.id)}>影响分析</Button>
                </Space>
              )},
            ]}
          />
        </Tabs.TabPane>

        {/* Tab 3: RCC任务审批 */}
        <Tabs.TabPane tab="🏛️ RCC调度任务" key="rcc-tasks">
          <Table
            dataSource={rccTasks}
            rowKey="id"
            pagination={{ pageSize: 10 }}
            size="small"
            columns={[
              { title: '任务代码', dataIndex: 'task_code', width: 200 },
              { title: '类型', dataIndex: 'task_type', width: 100 },
              { title: '标题', dataIndex: 'title', ellipsis: true },
              { title: '状态', dataIndex: 'status', width: 100, render: (s: string) => <Tag color={rccTaskStatusColor(s)}>{s}</Tag> },
              { title: '请求人', dataIndex: 'requested_by', width: 100 },
              { title: '创建时间', dataIndex: 'created_at', width: 150, render: (t: string) => t ? new Date(t).toLocaleString() : '-' },
              { title: '操作', key: 'action', width: 100, render: (_, record: any) => (
                <Space>
                  {record.status === 'pending' && (
                    <>
                      <Button size="small" type="primary" onClick={() => handleApproveTask(record.id)}>通过</Button>
                      <Button size="small" danger onClick={() => handleRejectTask(record.id)}>拒绝</Button>
                    </>
                  )}
                </Space>
              )},
            ]}
          />
        </Tabs.TabPane>

        {/* Tab 4: Chatbot工单 */}
        <Tabs.TabPane tab="🤖 Chatbot工单" key="chatbot-tickets">
          <Table
            dataSource={chatbotTickets}
            rowKey="id"
            pagination={{ pageSize: 10 }}
            size="small"
            columns={[
              { title: '工单代码', dataIndex: 'ticket_code', width: 200 },
              { title: '类型', dataIndex: 'ticket_type', width: 100 },
              { title: '原始消息', dataIndex: 'raw_message', ellipsis: true },
              { title: '状态', dataIndex: 'status', width: 80, render: (s: string) => <Tag color={s === 'open' ? 'blue' : s === 'resolved' ? 'green' : 'default'}>{s}</Tag> },
              { title: '优先级', dataIndex: 'priority', width: 80 },
              { title: '请求人', dataIndex: 'requester_id', width: 100 },
              { title: '路由到', dataIndex: 'routed_to_position', width: 100 },
              { title: '创建时间', dataIndex: 'created_at', width: 150, render: (t: string) => t ? new Date(t).toLocaleString() : '-' },
            ]}
          />
        </Tabs.TabPane>

        {/* Tab 5: 确定性逻辑链 */}
        <Tabs.TabPane tab="🔗 逻辑链" key="logic-chains">
          <Table
            dataSource={logicChains}
            rowKey="id"
            pagination={false}
            size="small"
            columns={[
              { title: '链代码', dataIndex: 'chain_code', width: 200 },
              { title: '链名称', dataIndex: 'chain_name', width: 200 },
              { title: '触发事件', dataIndex: 'trigger_event', width: 200 },
              { title: '条件数量', dataIndex: 'conditions', width: 80, render: (c: any) => c ? c.length : 0 },
              { title: '动作数量', dataIndex: 'action_sequence', width: 80, render: (a: any) => a ? a.length : 0 },
              { title: '启用', dataIndex: 'enabled', width: 60, render: (e: boolean) => e ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: '#f5222d' }} /> },
            ]}
          />
        </Tabs.TabPane>
      </Tabs>

      {/* 新建Chatbot工单弹窗 */}
      <Modal
        title="新建Chatbot工单"
        open={newTicketVisible}
        onOk={() => newTicketForm.submit()}
        onCancel={() => setNewTicketVisible(false)}
        okText="提交"
        cancelText="取消"
      >
        <Form form={newTicketForm} layout="vertical" onFinish={handleCreateTicket}>
          <Form.Item name="message" label="问题/需求描述" rules={[{ required: true }]}>
            <Input.TextArea rows={4} placeholder="自然语言描述您的需求，例如：我需要一台CNC-001设备用于加急订单" />
          </Form.Item>
          <Form.Item name="ticket_type" label="工单类型" initialValue="resource_request">
            <Select>
              <Select.Option value="resource_request">资源申请</Select.Option>
              <Select.Option value="quality_alert">质量异常</Select.Option>
              <Select.Option value="equipment_issue">设备故障</Select.Option>
              <Select.Option value="process_change">工艺变更</Select.Option>
              <Select.Option value="support_request">技术支持</Select.Option>
            </Select>
          </Form.Item>
        </Form>
      </Modal>

      {/* 参数影响分析弹窗 */}
      <Modal
        title="参数影响分析"
        open={!!selectedParam?.impact_analysis}
        onCancel={() => setSelectedParam({ ...selectedParam, impact_analysis: null })}
        footer={null}
      >
        {selectedParam?.impact_analysis && (
          <Descriptions column={1} bordered>
            <Descriptions.Item label="参数">{selectedParam.param_name}</Descriptions.Item>
            <Descriptions.Item label="当前值">{selectedParam.current_value}</Descriptions.Item>
            <Descriptions.Item label="风险级别">{selectedParam.impact_analysis.risk_level}</Descriptions.Item>
            <Descriptions.Item label="受影响逻辑链">
              {selectedParam.impact_analysis.affected_logic_chains?.length || 0} 条
            </Descriptions.Item>
            <Descriptions.Item label="受影响任务">
              {selectedParam.impact_analysis.affected_tasks?.length || 0} 个
            </Descriptions.Item>
            <Descriptions.Item label="受影响实体">
              {selectedParam.impact_analysis.affected_entities?.length || 0} 个
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </Card>
  )
}


