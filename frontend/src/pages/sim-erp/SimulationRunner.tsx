import React, { useEffect, useState } from 'react'
import {
  Card, Row, Col, Form, InputNumber, Select, Input, Button, Statistic,
  Tag, Alert, Divider, Space, Progress, Empty, message,
} from 'antd'
import { ThunderboltOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import {
  runSimulation, getSimPlugins, PluginManifest, SimulationRequest, SimulationResult,
} from '../../services/modules'

const DEFAULT_PLUGINS = ['VN_Legal_2024', 'Johnson_Global_Standard', 'Factory_Policy_Default']

const statusColor: Record<string, string> = {
  allowed: 'success', approved: 'success', blocked: 'error',
  warning: 'warning', conditional: 'warning',
}

const SimulationRunner: React.FC = () => {
  const [form] = Form.useForm()
  const [plugins, setPlugins] = useState<PluginManifest[]>([])
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SimulationResult | null>(null)

  useEffect(() => {
    getSimPlugins()
      .then(setPlugins)
      .catch(() => setPlugins([]))
  }, [])

  const pluginOptions = (plugins.length
    ? plugins.map((p) => p.plugin_name)
    : DEFAULT_PLUGINS
  ).map((name) => ({ label: name, value: name }))

  const onFinish = async (v: any) => {
    setLoading(true)
    const payload: SimulationRequest = {
      time_step_minutes: v.time_step_minutes,
      step_count: v.step_count,
      load_weight_kg: v.load_weight_kg,
      posture_angle_deg: v.posture_angle_deg,
      continuous_work_minutes: v.continuous_work_minutes,
      distance_meters: v.distance_meters,
      environment: {
        temperature_c: v.temperature_c,
        humidity_percent: v.humidity_percent,
        noise_db: v.noise_db ?? null,
        terrain: v.terrain,
        floor_incline_percent: v.floor_incline_percent ?? 0,
      },
      work_context: {
        worker_ref: v.worker_ref,
        shift_id: v.shift_id,
        task_type: v.task_type,
        zone_id: v.zone_id,
        action_type: v.action_type,
      },
      plugin_names: v.plugin_names,
    }
    try {
      const res = await runSimulation(payload)
      setResult(res)
      message.success('仿真完成')
    } catch {
      /* interceptor already reports */
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>
        <ThunderboltOutlined style={{ color: '#1890ff', marginRight: 8 }} />
        合规仿真引擎
      </h2>
      <Alert
        type="info"
        message="基于步进式疲劳/能耗物理模型 + 多法规插件裁决 (越南劳动法 / Johnson 全球标准 / 工厂策略)，评估作业场景的合规性与人因风险。"
        style={{ marginBottom: 16 }}
      />

      <Row gutter={16}>
        <Col xs={24} lg={14}>
          <Card title="作业场景参数">
            <Form
              form={form}
              layout="vertical"
              onFinish={onFinish}
              initialValues={{
                time_step_minutes: 30, step_count: 5000, load_weight_kg: 12,
                posture_angle_deg: 30, continuous_work_minutes: 240, distance_meters: 800,
                temperature_c: 36, humidity_percent: 70, noise_db: 78,
                terrain: 'flat', floor_incline_percent: 0,
                worker_ref: 'worker-001', shift_id: 'shift-day', task_type: 'assembly',
                zone_id: 'line-a', action_type: 'walk', plugin_names: DEFAULT_PLUGINS,
              }}
            >
              <Divider orientation="left" plain>物理输入</Divider>
              <Row gutter={16}>
                <Col span={8}><Form.Item label="时间步长(分钟)" name="time_step_minutes" rules={[{ required: true }]}><InputNumber min={1} max={480} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={8}><Form.Item label="步数" name="step_count" rules={[{ required: true }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={8}><Form.Item label="负重(kg)" name="load_weight_kg"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={8}><Form.Item label="姿态角度(°)" name="posture_angle_deg"><InputNumber min={0} max={180} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={8}><Form.Item label="连续作业(分钟)" name="continuous_work_minutes"><InputNumber min={0} max={1440} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={8}><Form.Item label="移动距离(m)" name="distance_meters"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
              </Row>

              <Divider orientation="left" plain>环境</Divider>
              <Row gutter={16}>
                <Col span={8}><Form.Item label="温度(℃)" name="temperature_c" rules={[{ required: true }]}><InputNumber min={-20} max={80} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={8}><Form.Item label="湿度(%)" name="humidity_percent"><InputNumber min={0} max={100} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={8}><Form.Item label="噪声(dB)" name="noise_db"><InputNumber min={0} max={150} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={8}><Form.Item label="地形" name="terrain"><Select options={[{ label: '平地', value: 'flat' }, { label: '斜坡', value: 'incline' }, { label: '楼梯', value: 'stairs' }]} /></Form.Item></Col>
                <Col span={8}><Form.Item label="坡度(%)" name="floor_incline_percent"><InputNumber min={0} max={100} style={{ width: '100%' }} /></Form.Item></Col>
              </Row>

              <Divider orientation="left" plain>作业上下文</Divider>
              <Row gutter={16}>
                <Col span={8}><Form.Item label="工人" name="worker_ref" rules={[{ required: true }]}><Input /></Form.Item></Col>
                <Col span={8}><Form.Item label="班次" name="shift_id"><Input /></Form.Item></Col>
                <Col span={8}><Form.Item label="任务类型" name="task_type"><Input /></Form.Item></Col>
                <Col span={8}><Form.Item label="区域" name="zone_id"><Input /></Form.Item></Col>
                <Col span={8}><Form.Item label="动作" name="action_type"><Select options={[{ label: '行走', value: 'walk' }, { label: '搬运', value: 'lift' }, { label: '站立', value: 'stand' }, { label: '操作', value: 'operate' }]} /></Form.Item></Col>
              </Row>

              <Divider orientation="left" plain>法规插件</Divider>
              <Form.Item name="plugin_names" rules={[{ required: true, message: '至少选择一个插件' }]}>
                <Select mode="multiple" options={pluginOptions} placeholder="选择参与裁决的法规插件" />
              </Form.Item>

              <Button type="primary" htmlType="submit" loading={loading} icon={<ThunderboltOutlined />} block>
                运行仿真
              </Button>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="仿真结果" style={{ minHeight: 400 }}>
            {!result ? (
              <Empty description="填写参数后点击「运行仿真」" style={{ marginTop: 80 }} />
            ) : (
              <>
                <Space align="center" style={{ marginBottom: 16 }}>
                  <SafetyCertificateOutlined style={{ fontSize: 22, color: result.legal_blocked ? '#f5222d' : '#52c41a' }} />
                  <Tag color={statusColor[result.final_status] || 'default'} style={{ fontSize: 14, padding: '4px 12px' }}>
                    {result.final_status.toUpperCase()}
                  </Tag>
                  {result.legal_blocked && <Tag color="error">法规阻断</Tag>}
                </Space>

                <Row gutter={16}>
                  <Col span={12}>
                    <Statistic title="疲劳评分" value={result.fatigue_score} precision={1} />
                    <Progress percent={Math.min(100, result.fatigue_score)} showInfo={false}
                      strokeColor={result.fatigue_score > 70 ? '#f5222d' : result.fatigue_score > 40 ? '#faad14' : '#52c41a'} />
                  </Col>
                  <Col span={12}><Statistic title="能耗(kcal)" value={result.energy_kcal} precision={1} /></Col>
                  <Col span={12} style={{ marginTop: 16 }}><Statistic title="成本增量" value={result.total_cost_delta} precision={2} prefix="¥" /></Col>
                  <Col span={12} style={{ marginTop: 16 }}><Statistic title="强制休息(分钟)" value={result.max_required_break_minutes} /></Col>
                </Row>

                <Divider orientation="left" plain>阻断规则</Divider>
                {result.blocking_rules.length ? (
                  <Space wrap>{result.blocking_rules.map((r) => <Tag color="error" key={r}>{r}</Tag>)}</Space>
                ) : <Tag color="success">无</Tag>}

                <Divider orientation="left" plain>告警</Divider>
                {result.warnings.length ? (
                  <Space wrap>{result.warnings.map((r) => <Tag color="warning" key={r}>{r}</Tag>)}</Space>
                ) : <Tag color="success">无</Tag>}

                <Divider />
                <span style={{ color: '#999', fontSize: 12 }}>仿真ID: {result.simulation_id}</span>
              </>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default SimulationRunner
