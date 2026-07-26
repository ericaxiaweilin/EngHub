/**
 * v2.6 - 三位一体调度系统前端 UI
 * RCC + 参数化面板 + Chatbot工单 + 资源调度视图（接入真实基线数据）
 */

import { useState, useEffect } from 'react'
import { Card, Tabs, Table, Button, Space, Tag, Descriptions, Modal, Form, Input, Select, message, Tree, Breadcrumb, Alert, Row, Col, Statistic } from 'antd'
import { SettingOutlined, TeamOutlined, CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined, SwapOutlined, SafetyOutlined, ThunderboltOutlined, ToolOutlined, FileTextOutlined, EnvironmentOutlined, ProfileOutlined } from '@ant-design/icons'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1/rcc'

interface RccDataResponse {
  success: boolean
  mode?: string
  factory_id?: string
  generated_at?: string
  params_summary: { total: number; high_sensitive: number; people_params: number; equipment_params: number; wo_params: number; env_params: number; process_params: number }
  chains_summary: { total: number; enabled_count: number; disabled_count: number }
  baseline: Record<string, any>
  decisions: Record<string, any>
}

export default function RCCDashboard() {
  const [selectedOrg, setSelectedOrg] = useState('rcc-root')
  const [orgTree, setOrgTree] = useState([])
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
      // 从 API 动态获取工厂列表
      let factoryList = [
        'FAC_ELEC_DEMO_2026',
        'FAC_MECH_001'
      ]
      
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
      }));
      setOrgTree([{
        title: '🏭 RCC 资源控制中心',
        key: 'rcc-root',
        children: [...treeItems, { title: '📊 全局汇总', key: 'rcc-root' }],
      } as any])
    } catch (err) {
      console.error('获取组织树失败:', err)
    }
  }

  const fetchAll = async () => {
    await Promise.all([
      fetchParams(),
      fetchTasks(),
      fetchTickets(),
      fetchLogicChains(),
      fetchRccData(),
    ])
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

  const fetchRccData = async () => {
    setLoadingData(true)
    try {
      // RCC 全局视角默认走 mode=global，遍历所有工厂汇总
      const res = await axios.get(`${API_BASE}/data?mode=global`)
      setRccData(res.data)
    } catch (err: any) {
      console.error('获取RCC综合数据失败:', err)
      const detail = err.response?.data?.detail || '获取综合数据失败'
      if (!detail.includes('404')) {
        console.warn(detail)
      }
    } finally {
      setLoadingData(false)
    }
  }

  const fetchFactoryBaseline = async (fid: string) => {
    setLoadingData(true)
    try {
      const res = await axios.get(`${API_BASE}/data?mode=single&factory_id=${fid}`)
      setRccData(res.data)
    } catch (err: any) {
      console.error(`获取工厂 ${fid} 基线失败:`, err)
    } finally {
      setLoadingData(false)
    }
  }

  const _unusedHandleAdjustParam = async (paramId: string, newValue: string, reason: string) => {
    try {
      await axios.put(`${API_BASE}/params/${paramId}`, {
        new_value: newValue,
        changed_by: "user",
        reason: reason,
        source: "panel",
      })
      message.success('参数调整成功')
      fetchParams()
      fetchRccData()
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

  const handleAnalyzeImpact = async (paramId: string) => {
    try {
      const res = await axios.get(`${API_BASE}/params/${paramId}/impact?new_value=test`)
      setSelectedParam({ ...selectedParam, impact_analysis: res.data?.data || null })
    } catch (err) {
      message.error('获取影响分析失败')
    }
  }

  const handleApproveTask = async (taskId: string) => {
    try {
      await axios.post(`${API_BASE}/tasks/${taskId}/approve`)
      message.success('任务已通过')
      fetchTasks()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '审批失败')
    }
  }

  const handleRejectTask = async (taskId: string) => {
    try {
      await axios.post(`${API_BASE}/tasks/${taskId}/reject`, { reason: "测试驳回" })
      message.success('任务已驳回')
      fetchTasks()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '拒绝失败')
    }
  }

  const getStatValue = (path: string | string[], fallback: number = 0): number => {
    const keys = (Array.isArray(path) ? path : path.split('.')).map(String)
    let val: any = rccData
    for (const k of keys) {
      if (val === null || val === undefined) return fallback
      val = val[k]
    }
    return typeof val === 'number' ? val : fallback
  }

  return (
    <Card title="🔗 EngHub v2.6 — 三位一体调度系统" loading={loadingData}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <Tree
          treeData={orgTree}
          onSelect={(keys) => {
            if (keys.length > 0 && keys[0] !== 'rcc-root') {
              setSelectedOrg(keys[0] as string)
              fetchFactoryBaseline(keys[0] as string)
            }
          }}
          defaultExpandAll
        />
        <Space>
          <Tag color="blue">当前模式: {rccData?.mode === 'global' ? '全局汇总' : rccData?.factory_id || '单工厂'}</Tag>
          <Button icon={<SwapOutlined />} onClick={() => {
            setSelectedOrg('rcc-root')
            fetchRccData()
          }}>返回全局</Button>
        </Space>
      </div>
      
      <Breadcrumb items={[
        { title: '首页' },
        { title: 'RCC资源控制中心' },
        { title: selectedOrg === 'rcc-root' ? '全局视图' : selectedOrg },
      ]} />

      <Tabs defaultActiveKey="overview">
        {/* Tab 1: 总览 */}
        <Tabs.TabPane tab="📊 总览" key="overview">
          <Space wrap style={{ marginBottom: 16 }}>
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => fetchAll()}>刷新全部</Button>
            <Button icon={<SwapOutlined />} onClick={() => fetchRccData()} loading={loadingData}>刷新RCC基线</Button>
            <Button icon={<SafetyOutlined />} onClick={() => fetchLogicChains()}>刷新逻辑链</Button>
            <Button type="dashed" icon={<SettingOutlined />} onClick={() => setNewTicketVisible(true)}>新建Chatbot工单</Button>
          </Space>

          <Row gutter={16}>
            <Col span={6}>
              <Card size="small">
                <Statistic title="可调参数数" value={getStatValue('params_summary.total')} prefix={<SettingOutlined />} suffix={`(高敏 ${getStatValue('params_summary.high_sensitive')})`} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="激活逻辑链" value={getStatValue('chains_summary.enabled_count')} prefix={<SafetyOutlined />} suffix={`/ 共 ${getStatValue('chains_summary.total')}`} />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="在岗人数" value={getStatValue(['baseline', 'people', 'active_workers'], 0)} prefix={<TeamOutlined />} suffix="人" />
              </Card>
            </Col>
            <Col span={6}>
              <Card size="small">
                <Statistic title="待审批RCC任务" value={rccTasks.filter(t => t.status === 'pending').length} prefix={<ClockCircleOutlined />} />
              </Card>
            </Col>
          </Row>

          {/* 五维基线卡片 */}
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={8}>
              <Card size="small" title={<><TeamOutlined /> 人力统筹</>}>
                <Descriptions column={1} size="small" bordered>
                  <Descriptions.Item label="在岗人数">{getStatValue(['baseline', 'people', 'active_workers'], 0)} / {getStatValue(['baseline', 'people', 'alert_count'])} 预警</Descriptions.Item>
                  <Descriptions.Item label="出勤率">{getStatValue(['baseline', 'people', 'attendance_rate_pct'], 0)}%</Descriptions.Item>
                  <Descriptions.Item label="技能分布">{JSON.stringify(rccData?.baseline?.people?.skills || {})}</Descriptions.Item>
                </Descriptions>
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small" title={<><ToolOutlined /> 设备统筹</>}>
                <Descriptions column={1} size="small" bordered>
                  <Descriptions.Item label="设备总数">{getStatValue(['baseline', 'equipment', 'total'], 0)}</Descriptions.Item>
                  <Descriptions.Item label="OEE目标">{getStatValue(['baseline', 'equipment', 'oee_target_pct'], 0)}%</Descriptions.Item>
                  <Descriptions.Item label="PM逾期">{getStatValue(['baseline', 'equipment', 'pm_overdue_count'], 0)} 台</Descriptions.Item>
                </Descriptions>
              </Card>
            </Col>
            <Col span={8}>
              <Card size="small" title={<><FileTextOutlined /> 工单统筹</>}>
                <Descriptions column={1} size="small" bordered>
                  <Descriptions.Item label="急单数量">{getStatValue(['baseline', 'work_orders', 'urgent_count'], 0)}</Descriptions.Item>
                  <Descriptions.Item label="交期风险">{getStatValue(['baseline', 'work_orders', 'delivery_risk_count'], 0)}</Descriptions.Item>
                  <Descriptions.Item label="状态分布">{JSON.stringify(rccData?.baseline?.work_orders?.status || {})}</Descriptions.Item>
                </Descriptions>
              </Card>
            </Col>
          </Row>

          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={12}>
              <Card size="small" title={<><EnvironmentOutlined /> 环境基线</>}>
                <Descriptions column={1} size="small" bordered>
                  <Descriptions.Item label="有数据">{rccData?.baseline?.environment?.has_data ? '✅' : '❌'}</Descriptions.Item>
                  <Descriptions.Item label="预警数">{getStatValue(['baseline', 'environment', 'warning_count'], 0)}</Descriptions.Item>
                  <Descriptions.Item label="告警">{rccData?.baseline?.environment?.alert ? <Tag color="red">有告警</Tag> : <Tag color="green">正常</Tag>}</Descriptions.Item>
                </Descriptions>
              </Card>
            </Col>
            <Col span={12}>
              <Card size="small" title={<><ProfileOutlined /> 工艺基线</>}>
                <Descriptions column={1} size="small" bordered>
                  <Descriptions.Item label="良品率(30d)">{rccData?.baseline?.process?.yield_baseline_30d || '-'}%</Descriptions.Item>
                  <Descriptions.Item label="工艺路线数">{getStatValue(['baseline', 'process', 'routing_count'], 0)}</Descriptions.Item>
                  <Descriptions.Item label="Top缺陷">{(rccData?.baseline?.process?.top_defects || []).map((d: any) => `${d.defect_type}(${d.cnt})`).join(', ') || '-'}</Descriptions.Item>
                </Descriptions>
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
              { title: '参数代码', dataIndex: 'param_code', width: 250 },
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
          <Alert message="RCC调度任务由业务事件自动触发（如设备故障、物料齐套不足等），当前由逻辑链引擎驱动" type="info" showIcon style={{ marginBottom: 16 }} />
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

        {/* Tab 5: 资源调度视图 */}
        <Tabs.TabPane tab="📈 资源调度视图" key="resource-view">
          {rccData ? (
            <Row gutter={16}>
              <Col span={24}>
                <Card title="资源决策概览" size="small">
                  <Descriptions column={1} bordered size="small">
                    <Descriptions.Item label="工厂ID">{rccData.factory_id}</Descriptions.Item>
                    <Descriptions.Item label="生成时间">{rccData.generated_at ? new Date(rccData.generated_at).toLocaleString() : '-'}</Descriptions.Item>
                  </Descriptions>
                </Card>
              </Col>
            </Row>
          ) : (
            <Alert message="请刷新RCC基线后查看资源调度视图" type="info" showIcon />
          )}
        </Tabs.TabPane>

        {/* Tab 6: 确定性逻辑链 */}
        <Tabs.TabPane tab="🔗 逻辑链" key="logic-chains">
          <Table
            dataSource={logicChains}
            rowKey="id"
            pagination={false}
            size="small"
            columns={[
              { title: '链代码', dataIndex: 'chain_code', width: 250 },
              { title: '链名称', dataIndex: 'chain_name', width: 250 },
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
