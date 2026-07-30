/**
 * 岗位协同网络 - Collaboration Network
 * 对接后端 /api/v1/collaboration/*
 * 功能：协同网络全景、事件规则查询、岗位边界、事件模拟
 */
import React, { useState, useEffect, useCallback } from 'react'
import {
  Card, Row, Col, Tag, Table, Space, Button, Select, Typography,
  Empty, message, Tabs, Descriptions, Timeline, Alert, Spin,
} from 'antd'
import {
  TeamOutlined, NodeIndexOutlined, ThunderboltOutlined,
  SafetyOutlined, ExperimentOutlined, ReloadOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const { Text, Title } = Typography
const FACTORY = localStorage.getItem('active_factory_id') || 'FAC_MECH_001'

const CollaborationNetwork: React.FC = () => {
  const [network, setNetwork] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [eventKey, setEventKey] = useState('')
  const [eventRule, setEventRule] = useState<any>(null)
  const [roleKey, setRoleKey] = useState('')
  const [boundaries, setBoundaries] = useState<any>(null)
  const [simResult, setSimResult] = useState<any>(null)
  const [simLoading, setSimLoading] = useState(false)

  const fetchNetwork = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/collaboration/network', { params: { factory_id: FACTORY } })
      setNetwork(res)
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  useEffect(() => { fetchNetwork() }, [fetchNetwork])

  const queryEventRule = async () => {
    if (!eventKey) return message.warning('请输入事件标识')
    try {
      const res: any = await api.get('/api/v1/collaboration/event-rule', { params: { event_key: eventKey } })
      setEventRule(res)
    } catch { message.error('查询失败') }
  }

  const queryBoundaries = async () => {
    if (!roleKey) return message.warning('请选择岗位')
    try {
      const res: any = await api.get('/api/v1/collaboration/role-boundaries', { params: { role_key: roleKey } })
      setBoundaries(res)
    } catch { message.error('查询失败') }
  }

  const simulateEvent = async () => {
    if (!eventKey) return message.warning('请输入事件标识')
    setSimLoading(true)
    try {
      const res: any = await api.post(`/api/v1/collaboration/simulate-event?factory_id=${FACTORY}&event_key=${eventKey}`, {})
      setSimResult(res)
    } catch { message.error('模拟失败') }
    setSimLoading(false)
  }

  const roles = network?.roles || []
  const events = network?.events || []

  const roleColumns = [
    { title: '岗位', dataIndex: 'key', key: 'key', render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '职责', dataIndex: 'responsibilities', key: 'resp', render: (v: string[]) => v?.join('、') || '-' },
    { title: '协同连接', dataIndex: 'connections', key: 'conn', render: (v: number) => <Badge count={v} showZero color="#1890ff" /> },
  ]

  const eventColumns = [
    { title: '事件', dataIndex: 'key', key: 'key', render: (v: string) => <Tag color="orange">{v}</Tag> },
    { title: '描述', dataIndex: 'description', key: 'desc' },
    { title: '触发岗位', dataIndex: 'trigger_role', key: 'trigger' },
    { title: '通知对象', dataIndex: 'notify_roles', key: 'notify', render: (v: string[]) => v?.map((r: string) => <Tag key={r}>{r}</Tag>) },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}><TeamOutlined /> 岗位协同网络</Title>
        <Button icon={<ReloadOutlined />} onClick={fetchNetwork}>刷新</Button>
      </Space>

      <Tabs items={[
        {
          key: 'overview',
          label: '网络全景',
          children: (
            <Spin spinning={loading}>
              <Row gutter={16}>
                <Col span={12}>
                  <Card title="岗位节点" size="small">
                    <Table dataSource={roles} columns={roleColumns} rowKey="key" size="small" pagination={false} />
                  </Card>
                </Col>
                <Col span={12}>
                  <Card title="协同事件" size="small">
                    <Table dataSource={events} columns={eventColumns} rowKey="key" size="small" pagination={false} />
                  </Card>
                </Col>
              </Row>
            </Spin>
          ),
        },
        {
          key: 'event',
          label: '事件规则',
          children: (
            <Card size="small">
              <Space style={{ marginBottom: 16 }}>
                <Select showSearch placeholder="选择事件" style={{ width: 240 }} value={eventKey || undefined}
                  onChange={setEventKey} options={events.map((e: any) => ({ value: e.key, label: `${e.key} - ${e.description || ''}` }))} />
                <Button type="primary" icon={<NodeIndexOutlined />} onClick={queryEventRule}>查询规则</Button>
                <Button icon={<ExperimentOutlined />} onClick={simulateEvent} loading={simLoading}>模拟触发</Button>
              </Space>
              {eventRule && (
                <Descriptions bordered size="small" column={1} title="协同规则">
                  {Object.entries(eventRule).map(([k, v]) => (
                    <Descriptions.Item key={k} label={k}>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</Descriptions.Item>
                  ))}
                </Descriptions>
              )}
              {simResult && (
                <Card title="模拟结果" size="small" style={{ marginTop: 16 }}>
                  <Timeline items={(simResult.steps || simResult.flow || []).map((s: any, i: number) => ({
                    color: i === 0 ? 'green' : 'blue',
                    children: typeof s === 'string' ? s : `${s.role || s.actor || ''}: ${s.action || s.description || JSON.stringify(s)}`,
                  }))} />
                </Card>
              )}
            </Card>
          ),
        },
        {
          key: 'boundary',
          label: '岗位边界',
          children: (
            <Card size="small">
              <Space style={{ marginBottom: 16 }}>
                <Select showSearch placeholder="选择岗位" style={{ width: 200 }} value={roleKey || undefined}
                  onChange={setRoleKey} options={roles.map((r: any) => ({ value: r.key, label: r.name || r.key }))} />
                <Button type="primary" icon={<SafetyOutlined />} onClick={queryBoundaries}>查看边界</Button>
              </Space>
              {boundaries && (
                <Row gutter={16}>
                  <Col span={8}>
                    <Card title="可执行" size="small">
                      {(boundaries.can_do || boundaries.allowed || []).map((a: string) => <Tag color="green" key={a} style={{ margin: 2 }}>{a}</Tag>)}
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card title="不可执行" size="small">
                      {(boundaries.cannot_do || boundaries.denied || []).map((a: string) => <Tag color="red" key={a} style={{ margin: 2 }}>{a}</Tag>)}
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card title="协同连接" size="small">
                      {(boundaries.connections || boundaries.collaborators || []).map((c: any) => (
                        <Tag color="blue" key={typeof c === 'string' ? c : c.key} style={{ margin: 2 }}>
                          {typeof c === 'string' ? c : c.name || c.key}
                        </Tag>
                      ))}
                    </Card>
                  </Col>
                </Row>
              )}
            </Card>
          ),
        },
      ]} />
    </div>
  )
}

export default CollaborationNetwork
