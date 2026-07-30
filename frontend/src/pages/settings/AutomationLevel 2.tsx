/**
 * 自动化等级配置 - Automation Level Config
 * 对接后端 /api/v1/automation-level/*
 * 功能：工作流自动化等级查看/设置/批量设置/模拟切换
 */
import React, { useState, useEffect, useCallback } from 'react'
import {
  Card, Row, Col, Tag, Table, Space, Button, Select, Typography,
  message, Slider, Modal, Descriptions, Alert, Spin, Progress, Tooltip,
} from 'antd'
import {
  ControlOutlined, ThunderboltOutlined, SettingOutlined,
  ExperimentOutlined, ReloadOutlined, RocketOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const { Text, Title } = Typography
const FACTORY = localStorage.getItem('active_factory_id') || 'FAC_MECH_001'

const LEVEL_CONFIG: Record<number, { color: string; label: string; desc: string }> = {
  0: { color: 'default', label: 'L0 手工', desc: '系统只记录，全部人做' },
  1: { color: 'blue', label: 'L1 辅助', desc: '系统预警+建议，人决定+执行' },
  2: { color: 'orange', label: 'L2 半自动', desc: '标准件自动，异常人处理' },
  3: { color: 'green', label: 'L3 全自动', desc: '全部自动+异常自动升级' },
}

const AutomationLevel: React.FC = () => {
  const [config, setConfig] = useState<any>(null)
  const [definitions, setDefinitions] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [simModal, setSimModal] = useState(false)
  const [simResult, setSimResult] = useState<any>(null)
  const [simLoading, setSimLoading] = useState(false)
  const [batchLevel, setBatchLevel] = useState<number | null>(null)

  const fetchConfig = useCallback(async () => {
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/automation-level/config', { params: { factory_id: FACTORY } })
      setConfig(res)
    } catch { /* ignore */ }
    setLoading(false)
  }, [])

  const fetchDefinitions = useCallback(async () => {
    try {
      const res: any = await api.get('/api/v1/automation-level/definitions')
      setDefinitions(res)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchConfig(); fetchDefinitions() }, [fetchConfig, fetchDefinitions])

  const setLevel = async (workflowKey: string, level: number) => {
    try {
      await api.post('/api/v1/automation-level/set', null, {
        params: { factory_id: FACTORY, workflow_key: workflowKey, level },
      })
      message.success(`已设置 ${workflowKey} → L${level}`)
      fetchConfig()
    } catch { message.error('设置失败') }
  }

  const batchSet = async () => {
    if (batchLevel === null) return
    Modal.confirm({
      title: `确认全厂切换到 L${batchLevel}？`,
      content: LEVEL_CONFIG[batchLevel]?.desc,
      onOk: async () => {
        try {
          await api.post('/api/v1/automation-level/batch-set', null, {
            params: { factory_id: FACTORY, level: batchLevel },
          })
          message.success('全厂等级已更新')
          fetchConfig()
        } catch { message.error('批量设置失败') }
      },
    })
  }

  const simulate = async (workflowKey: string, targetLevel: number) => {
    setSimLoading(true)
    setSimModal(true)
    try {
      const res: any = await api.get('/api/v1/automation-level/simulate', {
        params: { factory_id: FACTORY, workflow_key: workflowKey, target_level: targetLevel },
      })
      setSimResult(res)
    } catch { message.error('模拟失败') }
    setSimLoading(false)
  }

  const workflows = config?.workflows || config?.items || []

  const columns = [
    { title: '工作流', dataIndex: 'workflow_key', key: 'key', render: (v: string, r: any) => <Text strong>{r.name || v}</Text> },
    {
      title: '当前等级', dataIndex: 'level', key: 'level',
      render: (v: number) => {
        const lc = LEVEL_CONFIG[v] || LEVEL_CONFIG[0]
        return <Tooltip title={lc.desc}><Tag color={lc.color}>{lc.label}</Tag></Tooltip>
      },
    },
    {
      title: '成熟度', dataIndex: 'maturity_score', key: 'maturity',
      render: (v: number) => <Progress percent={v || 0} size="small" style={{ width: 100 }} />,
    },
    { title: '建议', dataIndex: 'suggestion', key: 'suggestion', render: (v: string) => <Text type="secondary">{v || '-'}</Text> },
    {
      title: '操作', key: 'action',
      render: (_: any, record: any) => (
        <Space>
          <Select size="small" style={{ width: 90 }} value={record.level}
            onChange={(v) => setLevel(record.workflow_key, v)}
            options={[0, 1, 2, 3].map(l => ({ value: l, label: `L${l}` }))} />
          <Button size="small" icon={<ExperimentOutlined />}
            onClick={() => simulate(record.workflow_key, Math.min((record.level || 0) + 1, 3))}>
            模拟+1
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}><ControlOutlined /> 自动化等级配置</Title>
        <Space>
          <Select placeholder="全厂等级" style={{ width: 120 }} value={batchLevel}
            onChange={setBatchLevel} options={[0, 1, 2, 3].map(l => ({ value: l, label: LEVEL_CONFIG[l].label }))} />
          <Button type="primary" icon={<RocketOutlined />} onClick={batchSet} disabled={batchLevel === null}>
            一键全厂
          </Button>
          <Button icon={<ReloadOutlined />} onClick={fetchConfig}>刷新</Button>
        </Space>
      </Row>

      {definitions && (
        <Alert type="info" showIcon style={{ marginBottom: 16 }}
          message={
            <Space wrap>
              {Object.entries(definitions.level_description || {}).map(([k, v]) => (
                <Tag key={k}>{k}: {v as string}</Tag>
              ))}
            </Space>
          }
        />
      )}

      <Card size="small">
        <Table dataSource={workflows} columns={columns} rowKey="workflow_key" size="small"
          loading={loading} pagination={false} />
      </Card>

      <Modal title="模拟切换结果" open={simModal} onCancel={() => setSimModal(false)} footer={null} width={600}>
        <Spin spinning={simLoading}>
          {simResult ? (
            <Descriptions bordered size="small" column={1}>
              {Object.entries(simResult).map(([k, v]) => (
                <Descriptions.Item key={k} label={k}>
                  {typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v)}
                </Descriptions.Item>
              ))}
            </Descriptions>
          ) : <Text type="secondary">加载中...</Text>}
        </Spin>
      </Modal>
    </div>
  )
}

export default AutomationLevel
