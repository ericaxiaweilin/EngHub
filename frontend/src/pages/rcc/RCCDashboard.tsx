/**
 * v2.6 - 三位一体调度系统前端 UI
 * RCC + 参数化面板 + Chatbot工单 + 资源调度视图（接入真实基线数据）
 */

import { useState, useEffect } from 'react'
import { Card, Tabs, Table, Button, Space, Tag, Descriptions, Modal, Form, Input, Select, message, Tree, Breadcrumb, Alert, Row, Col, Statistic } from 'antd'
import { SettingOutlined, RobotOutlined, TeamOutlined, CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined, SwapOutlined, SafetyOutlined, ThunderboltOutlined, WarningOutlined, ToolOutlined, FileTextOutlined, EnvironmentOutlined, ProfileOutlined } from '@ant-design/icons'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1/rcc'

interface RccDataResponse {
  success: boolean
  factory_id?: string
  generated_at?: string
  params_summary: { total: number; high_sensitive: number }
  chains_summary: { total: number; enabled_count: number }
  baseline: Record<string, any>
  decisions: Record<string, any>
}

export default function RCCDashboard() {
  const [selectedOrg, setSelectedOrg] = useState('rcc-root')
  const [orgTree, setOrgTree] = useState<any[]>([])
  const [params, setParams] = useState<any[]>([])
  const [rccTasks, setRccTasks] = useState<any[]>([])
  const [chatbotTickets, setChatbotTickets] = useState<any[]>([])
  const [logicChains, setLogicChains] = useState<any[]>([])
  const [rccData, setRccData] = useState<RccDataResponse | null>(null)
  const [loadingData, setLoadingData] = useState(false)
  const [selectedParam, setSelectedParam] = useState<any>(null)
  const [newTicketVisible, setNewTicketVisible] = useState(false)
  const [newTicketForm] = Form.useForm()

  useEffect(() => {
    fetchOrgTree()
    fetchAll()
  }, [])

  const fetchOrgTree = async () => {
    try {
      let factoryList: string[] = ['FAC_ELEC_DEMO_2026', 'FAC_MECH_001']
      try {
        const res = await axios.get(`${API_BASE}/data?mode=global`)
        if (res.data?.factories_aggregated) {
          factoryList = res.data.factories_aggregated
        }
      } catch (e) {
        console.warn('获取工厂列表失败，使用默认列表')
      }

      const treeItems = factoryList.map((f) => ({
        title: `${f}`,
        key: f,
        onClick: () => { fetchFactoryBaseline(f); setSelectedOrg(f); fetchRccData(); },
      }))
      setOrgTree([{
        title: '🏭 RCC 资源控制中心',
        key: 'rcc-root',
        children: [...treeItems, { title: '📊 全局汇总', key: 'rcc-root' }]
      }])
    } catch (err) {
      console.error('获取组织树失败:', err)
    }
  }

  const fetchAll = async () => {
    await Promise.all([fetchParams(), fetchTasks(), fetchTickets(), fetchLogicChains(), fetchRccData()])
  }

  const fetchParams = async () => {
    try { setParams((await axios.get(`${API_BASE}/params`)).data.items || []) } catch (e) {}
  }

  const fetchTasks = async () => {
    try { setRccTasks((await axios.get(`${API_BASE}/tasks`)).data.items || []) } catch (e) {}
  }

  const fetchTickets = async () => {
    try { setChatbotTickets((await axios.get(`${API_BASE}/chatbot/tickets`)).data.items || []) } catch (e) {}
  }

  const fetchLogicChains = async () => {
    try { setLogicChains((await axios.get(`${API_BASE}/logic-chains`)).data.items || []) } catch (e) {}
  }

  const fetchRccData = async () => {
    setLoadingData(true)
    try { setRccData((await axios.get(`${API_BASE}/data?mode=global`)).data) } catch (e: any) {}
    finally { setLoadingData(false) }
  }

  const fetchFactoryBaseline = async (fid: string) => {
    setLoadingData(true)
    try { setRccData((await axios.get(`${API_BASE}/data?mode=single&factory_id=${fid}`)).data) } catch (e: any) {}
    finally { setLoadingData(false) }
  }

  const handleAdjustParam = async (paramId: string, newValue: string, reason: string) => {
    try {
      await axios.put(`${API_BASE}/params/${paramId}`, { new_value: newValue, changed_by: 'user', reason, source: 'panel' })
      message.success('参数调整成功'); fetchParams(); fetchRccData()
    } catch (e: any) { message.error(e.response?.data?.detail || '参数调整失败') }
  }

  const handleCreateTicket = async (values: any) => {
    try {
      await axios.post(`${API_BASE}/chatbot/tickets/create`, { message: values.message, requester_id: 'user', ticket_type: values.ticket_type })
      message.success('创建成功'); newTicketForm.resetFields(); setNewTicketVisible(false); fetchTickets()
    } catch (e: any) { message.error(e.response?.data?.detail || '创建失败') }
  }

  const paramSensitivityColor = (s: string) => ({ low: 'green', normal: 'blue', high: 'orange', strategic: 'red' }[s] || 'default')
  const rccTaskStatusColor = (s: string) => ({ pending: 'orange', approved: 'green', rejected: 'red', executing: 'processing', completed: 'success' }[s] || 'default')

  const handleAnalyzeImpact = async (paramId: string) => {
    try {
      const res = await axios.get(`${API_BASE}/params/${paramId}/impact?new_value=test`)
      setSelectedParam({ ...selectedParam, impact_analysis: res.data?.data || null })
    } catch (e) { message.error('获取影响分析失败') }
  }

  const handleApproveTask = async (taskId: string) => {
    try { await axios.post(`${API_BASE}/tasks/${taskId}/approve`); message.success('通过'); fetchTasks() } catch (e: any) { message.error(e.response?.data?.detail || '审批失败') }
  }

  const handleRejectTask = async (taskId: string) => {
    try { await axios.post(`${API_BASE}/tasks/${taskId}/reject`, { reason: '测试驳回' }); message.success('已驳回'); fetchTasks() } catch (e: any) { message.error(e.response?.data?.detail || '拒绝失败') }
  }

  const getStatValue = (path: string | string[], fallback: number = 0): number => {
    const keys = Array.isArray(path) ? path : path.split('.')
    let val: any = rccData
    for (const k of keys) { if (val === null || val === undefined) return fallback; val = val[k] }
    return typeof val === 'number' ? val : fallback
  }

  const isGlobalMode = rccData?.mode === 'global'

  return (
    <Card title="EngHub v2.6 — 三位一体调度系统" loading={loadingData}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <Tree treeData={orgTree} onSelect={(keys) => { if (keys.length > 0 && keys[0] !== 'rcc-root') { setSelectedOrg(keys[0] as string); fetchFactoryBaseline(keys[0] as string) } }} defaultExpandAll />
        <Space>
          <Tag color="blue">{isGlobalMode ? '全局汇总' : rccData?.factory_id}</Tag>
          <Button icon={<SwapOutlined />} onClick={() => { setSelectedOrg('rcc-root'); fetchRccData() }}>返回全局</Button>
        </Space>
      </div>
      <Breadcrumb items={[{ title: '首页' }, { title: 'RCC资源控制中心' }, { title: selectedOrg === 'rcc-root' ? '全局视图' : selectedOrg }]} />

      <Tabs defaultActiveKey="overview">
        <Tabs.TabPane tab="总览" key="overview">
          <Space wrap style={{ marginBottom: 16 }}>
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => fetchAll()}>刷新全部</Button>
            <Button icon={<SwapOutlined />} onClick={() => fetchRccData()} loading={loadingData}>刷新RCC基线</Button>
            <Button icon={<SafetyOutlined />} onClick={() => fetchLogicChains()}>刷新逻辑链</Button>
            <Button type="dashed" icon={<RobotOutlined />} onClick={() => setNewTicketVisible(true)}>新建Chatbot工单</Button>
          </Space>
          <Row gutter={16}>
            <Col span={6}><Card size="small"><Statistic title="可调参数数" value={getStatValue('params_summary.total')} prefix={<SettingOutlined />} suffix={`(高敏 ${getStatValue('params_summary.high_sensitive')})`} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="激活逻辑链" value={getStatValue('chains_summary.enabled_count')} prefix={<SafetyOutlined />} suffix={`/ 共 ${getStatValue('chains_summary.total')}`} /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="在岗人数" value={getStatValue(['baseline', 'people', 'active_workers'], 0)} prefix={<TeamOutlined />} suffix="人" /></Card></Col>
            <Col span={6}><Card size="small"><Statistic title="待审批RCC任务" value={rccTasks.filter(t => t.status === 'pending').length} prefix={<ClockCircleOutlined />} /></Card></Col>
          </Row>
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={8}><Card size="small" title={<><TeamOutlined /> 人力统筹</>}>
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="在岗人数">{getStatValue(['baseline', 'people', 'active_workers'], 0)}</Descriptions.Item>
                <Descriptions.Item label="出勤率">{getStatValue(['baseline', 'people', 'attendance_rate_pct'], 0)}%</Descriptions.Item>
              </Descriptions>
            </Card></Col>
            <Col span={8}><Card size="small" title={<><ToolOutlined /> 设备统筹</>}>
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="设备总数">{getStatValue(['baseline', 'equipment', 'total'], 0)}</Descriptions.Item>
                <Descriptions.Item label="OEE目标">{getStatValue(['baseline', 'equipment', 'oee_target_pct'], 0)}%</Descriptions.Item>
              </Descriptions>
            </Card></Col>
            <Col span={8}><Card size="small" title={<><FileTextOutlined /> 工单统筹</>}>
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="急单数量">{getStatValue(['baseline', 'work_orders', 'urgent_count'], 0)}</Descriptions.Item>
                <Descriptions.Item label="交期风险">{getStatValue(['baseline', 'work_orders', 'delivery_risk_count'], 0)}</Descriptions.Item>
              </Descriptions>
            </Card></Col>
          </Row>
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={12}><Card size="small" title={<><EnvironmentOutlined /> 环境基线</>}>
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="预警数">{getStatValue(['baseline', 'environment', 'warning_count'], 0)}</Descriptions.Item>
                <Descriptions.Item label="告警">{rccData?.baseline?.environment?.alert ? <Tag color="red">有告警</Tag> : <Tag color="green">正常</Tag>}</Descriptions.Item>
              </Descriptions>
            </Card></Col>
            <Col span={12}><Card size="small" title={<><ProfileOutlined /> 工艺基线</>}>
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="良品率(30d)">{rccData?.baseline?.process?.yield_baseline_30d || '-'}%</Descriptions.Item>
                <Descriptions.Item label="工艺路线数">{getStatValue(['baseline', 'process', 'routing_count'], 0)}</Descriptions.Item>
              </Descriptions>
            </Card></Col>
          </Row>
        </Tabs.TabPane>

        <Tabs.TabPane tab="参数化面板" key="parameters">
          <Table dataSource={params} rowKey="id" pagination={false} size="small" columns={[
            { title: '参数代码', dataIndex: 'param_code', width: 250 },
            { title: '参数名称', dataIndex: 'param_name', width: 200 },
            { title: '当前值', dataIndex: 'current_value', width: 150 },
            { title: '敏感度', dataIndex: 'sensitivity', width: 80, render: (s: string) => <Tag color={paramSensitivityColor(s)}>{s}</Tag> },
            { title: '操作', key: 'action', width: 100, render: (_: any, record: any) => <Space><Button size="small" type="link" onClick={() => setSelectedParam(record)}>调整</Button><Button size="small" type="link" onClick={() => handleAnalyzeImpact(record.id)}>影响分析</Button></Space> },
          ]} />
        </Tabs.TabPane>

        <Tabs.TabPane tab="RCC调度任务" key="rcc-tasks">
          <Alert message="RCC调度任务由业务事件自动触发，当前由逻辑链引擎驱动" type="info" showIcon style={{ marginBottom: 16 }} />
          <Table dataSource={rccTasks} rowKey="id" pagination={{ pageSize: 10 }} size="small" columns={[
            { title: '任务代码', dataIndex: 'task_code', width: 200 },
            { title: '类型', dataIndex: 'task_type', width: 100 },
            { title: '标题', dataIndex: 'title', ellipsis: true },
            { title: '状态', dataIndex: 'status', width: 100, render: (s: string) => <Tag color={rccTaskStatusColor(s)}>{s}</Tag> },
            { title: '请求人', dataIndex: 'requested_by', width: 100 },
            { title: '操作', key: 'action', width: 150, render: (_: any, record: any) => record.status === 'pending' ? <Space><Button size="small" type="primary" onClick={() => handleApproveTask(record.id)}>通过</Button><Button size="small" danger onClick={() => handleRejectTask(record.id)}>拒绝</Button></Space> : null },
          ]} />
        </Tabs.TabPane>

        <Tabs.TabPane tab="Chatbot工单" key="chatbot-tickets">
          <Table dataSource={chatbotTickets} rowKey="id" pagination={{ pageSize: 10 }} size="small" columns={[
            { title: '工单代码', dataIndex: 'ticket_code', width: 200 },
            { title: '类型', dataIndex: 'ticket_type', width: 100 },
            { title: '原始消息', dataIndex: 'raw_message', ellipsis: true },
            { title: '状态', dataIndex: 'status', width: 80, render: (s: string) => <Tag color={s === 'open' ? 'blue' : s === 'resolved' ? 'green' : 'default'}>{s}</Tag> },
            { title: '优先级', dataIndex: 'priority', width: 80 },
          ]} />
        </Tabs.TabPane>

        <Tabs.TabPane tab="逻辑链" key="logic-chains">
          <Table dataSource={logicChains} rowKey="id" pagination={false} size="small" columns={[
            { title: '链代码', dataIndex: 'chain_code', width: 250 },
            { title: '链名称', dataIndex: 'chain_name', width: 250 },
            { title: '触发事件', dataIndex: 'trigger_event', width: 200 },
            { title: '启用', dataIndex: 'enabled', width: 60, render: (e: boolean) => e ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <CloseCircleOutlined style={{ color: '#f5222d' }} /> },
          ]} />
        </Tabs.TabPane>
      </Tabs>

      <Modal title="新建Chatbot工单" open={newTicketVisible} onOk={() => newTicketForm.submit()} onCancel={() => setNewTicketVisible(false)} okText="提交" cancelText="取消">
        <Form form={newTicketForm} layout="vertical" onFinish={handleCreateTicket}>
          <Form.Item name="message" label="问题描述" rules={[{ required: true }]}><Input.TextArea rows={4} placeholder="自然语言描述您的需求" /></Form.Item>
          <Form.Item name="ticket_type" label="工单类型" initialValue="resource_request"><Select><Select.Option value="resource_request">资源申请</Select.Option><Select.Option value="quality_alert">质量异常</Select.Option><Select.Option value="equipment_issue">设备故障</Select.Option><Select.Option value="process_change">工艺变更</Select.Option><Select.Option value="support_request">技术支持</Select.Option></Select></Form.Item>
        </Form>
      </Modal>

      <Modal title="参数影响分析" open={!!selectedParam?.impact_analysis} onCancel={() => setSelectedParam({ ...selectedParam, impact_analysis: null })} footer={null}>
        {selectedParam?.impact_analysis && <Descriptions column={1} bordered>
          <Descriptions.Item label="参数">{selectedParam.param_name}</Descriptions.Item>
          <Descriptions.Item label="当前值">{selectedParam.current_value}</Descriptions.Item>
          <Descriptions.Item label="风险级别">{selectedParam.impact_analysis.risk_level}</Descriptions.Item>
        </Descriptions>}
      </Modal>
    </Card>
  )
}
