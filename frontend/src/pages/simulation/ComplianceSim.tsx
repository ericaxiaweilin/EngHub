import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Row, Col, Form, InputNumber, Select, Input, Button, Statistic,
  Tag, Divider, Space, Progress, Empty, message, Tooltip, Slider,
  Descriptions, Table, Collapse, Typography, Badge,
} from 'antd'
import {
  ThunderboltOutlined, SafetyCertificateOutlined, ExperimentOutlined,
  FireOutlined, DashboardOutlined, EnvironmentOutlined, UserOutlined,
  InfoCircleOutlined, WarningOutlined, CheckCircleOutlined,
  ClockCircleOutlined, AuditOutlined, ControlOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  runSimulation, getSimPlugins, PluginManifest, SimulationRequest, SimulationResult,
  RuleDecision, PluginRecord,
} from '../../services/modules'

const { Text } = Typography

const DEFAULT_PLUGINS = ['VN_Legal_2024', 'Johnson_Global_Standard', 'Factory_Policy_Default']

/* ── 场景预设 ── */
const SCENARIOS: Record<string, { label: string; icon: React.ReactNode; desc: string; values: Record<string, any> }> = {
  standard: {
    label: '标准装配', icon: <ExperimentOutlined />, desc: '常温常湿、轻载、标准工时',
    values: {
      time_step_minutes: 30, step_count: 5000, load_weight_kg: 5, posture_angle_deg: 15,
      continuous_work_minutes: 240, distance_meters: 400,
      temperature_c: 26, humidity_percent: 55, noise_db: 65, terrain: 'flat', floor_incline_percent: 0,
      worker_ref: 'worker-001', shift_id: 'shift-day', task_type: 'assembly', zone_id: 'line-a', action_type: 'assemble',
    },
  },
  high_heat: {
    label: '高温加班', icon: <FireOutlined />, desc: '36°C 高温、高湿、连续作业 4h',
    values: {
      time_step_minutes: 30, step_count: 8000, load_weight_kg: 12, posture_angle_deg: 30,
      continuous_work_minutes: 240, distance_meters: 800,
      temperature_c: 36, humidity_percent: 70, noise_db: 78, terrain: 'flat', floor_incline_percent: 0,
      worker_ref: 'worker-001', shift_id: 'shift-day', task_type: 'assembly', zone_id: 'line-a', action_type: 'walk',
    },
  },
  heavy_lift: {
    label: '重载搬运', icon: <DashboardOutlined />, desc: '25kg 负重、斜坡地形、频繁弯腰',
    values: {
      time_step_minutes: 15, step_count: 3000, load_weight_kg: 25, posture_angle_deg: 60,
      continuous_work_minutes: 180, distance_meters: 600,
      temperature_c: 30, humidity_percent: 60, noise_db: 80, terrain: 'slope', floor_incline_percent: 8,
      worker_ref: 'worker-002', shift_id: 'shift-day', task_type: 'logistics', zone_id: 'warehouse-b', action_type: 'lift',
    },
  },
  night_patrol: {
    label: '夜间巡检', icon: <ClockCircleOutlined />, desc: '夜班、长距离行走、低噪声环境',
    values: {
      time_step_minutes: 60, step_count: 12000, load_weight_kg: 3, posture_angle_deg: 5,
      continuous_work_minutes: 420, distance_meters: 2000,
      temperature_c: 22, humidity_percent: 50, noise_db: 45, terrain: 'flat', floor_incline_percent: 0,
      worker_ref: 'worker-003', shift_id: 'shift-night', task_type: 'inspection', zone_id: 'plant-all', action_type: 'walk',
    },
  },
}

/* ── 字段工程提示 ── */
const FIELD_TIPS: Record<string, string> = {
  time_step_minutes: '仿真离散时间步长。越小精度越高但计算量越大，工业场景推荐 15-60 min',
  step_count: '单步长内行走步数。成人正常步频 ~100 步/min，8000 步 ≈ 80 min 行走',
  load_weight_kg: '搬运负重。越南劳动法: 女工 ≤ 20kg / 男工 ≤ 50kg (连续); Johnson 标准更严格',
  posture_angle_deg: '躯干前倾角度。> 30° 触发人因工程告警，> 60° 触发法规阻断',
  continuous_work_minutes: '连续作业时长。越南法: 高温 > 32°C 时连续作业 ≤ 180 min',
  distance_meters: '单步长移动距离。影响能耗计算 (MET 系数)',
  temperature_c: '环境温度。> 32°C 触发高温保护规则，> 40°C 强制停工',
  humidity_percent: '相对湿度。与温度联合计算 WBGT 湿球黑球温度指数',
  noise_db: '环境噪声。> 85 dB 需佩戴 PPE，> 100 dB 触发职业健康阻断',
  terrain: '地形类型。斜坡/楼梯增加能耗系数 (slope +15%, stairs +30%)',
  floor_incline_percent: '地面坡度百分比。> 5% 增加滑倒风险权重',
  worker_ref: '工人标识符。关联技能等级、PPE 状态、历史疲劳档案',
  shift_id: '班次标识。夜班 (shift-night) 触发额外疲劳系数 ×1.3',
  task_type: '任务类型。影响基础代谢率 (assembly 1.2 MET / logistics 2.5 MET)',
  zone_id: '作业区域。关联区域环境传感器数据和风险等级',
  action_type: '当前动作。walk/lift/push/pull/assemble/inspect/idle 各有不同能耗模型',
}

const statusColor: Record<string, string> = {
  allowed: 'success', approved: 'success', accepted: 'success',
  blocked: 'error', rejected: 'error',
  warning: 'warning', conditional: 'warning',
}

const priorityColor: Record<string, string> = {
  P0: 'red', P1: 'orange', P2: 'blue', P3: 'default',
}

const decisionTypeColor: Record<string, string> = {
  VIOLATION: 'error', WARNING: 'warning', REQUIRED_ACTION: 'processing',
  COST_MODIFIER: 'gold', ADVISORY: 'default',
}

/* ── 实时风险预估 (客户端启发式) ── */
function useRiskHint(form: any) {
  const [hint, setHint] = useState<{ level: 'safe' | 'warn' | 'danger'; text: string } | null>(null)
  const check = () => {
    const v = form.getFieldsValue()
    const risks: string[] = []
    if (v.temperature_c > 32) risks.push(`高温 ${v.temperature_c}°C > 32°C 阈值`)
    if (v.load_weight_kg > 20) risks.push(`负重 ${v.load_weight_kg}kg 超过女工限值`)
    if (v.posture_angle_deg > 30) risks.push(`姿态角 ${v.posture_angle_deg}° 超人因工程阈值`)
    if (v.continuous_work_minutes > 180 && v.temperature_c > 32) risks.push('高温下连续作业超限')
    if (v.noise_db > 85) risks.push(`噪声 ${v.noise_db}dB 需 PPE`)
    if (risks.length === 0) setHint({ level: 'safe', text: '当前参数在安全范围内' })
    else if (risks.some(r => r.includes('超限') || r.includes('超过'))) setHint({ level: 'danger', text: risks.join('；') })
    else setHint({ level: 'warn', text: risks.join('；') })
  }
  return { hint, check }
}

/* ── 合规仿真流程管线图（组态风格） ── */
const VERDICT_COLOR: Record<string, string> = {
  allowed: '#95de64', approved: '#95de64', accepted: '#95de64',
  blocked: '#ff7875', rejected: '#ff7875',
}

const CompliancePipeline: React.FC<{ result: SimulationResult | null }> = ({ result }) => {
  const stages: { no: string; icon: React.ReactNode; name: string; en: string; desc: string; live: React.ReactNode }[] = [
    {
      no: '01', icon: <ControlOutlined />, name: '场景参数', en: 'SCENARIO INPUT',
      desc: '环境 · 负重 · 姿态 · 班次 · 动作',
      live: result ? `仿真 #${result.simulation_id.slice(0, 8)}` : '21 项工程字段待输入',
    },
    {
      no: '02', icon: <ExperimentOutlined />, name: '物理引擎', en: 'PHYSICS CORE',
      desc: '步进式疲劳 / 能耗代谢模型',
      live: result
        ? `疲劳 ${result.fatigue_score.toFixed(0)} · ${result.energy_kcal.toFixed(0)} kcal`
        : '步进模型待启动',
    },
    {
      no: '03', icon: <SafetyCertificateOutlined />, name: '法规插件仲裁', en: 'PLUGIN ARBITER',
      desc: '越南劳动法 · Johnson · 厂策 并行裁决',
      live: result
        ? `${result.all_decisions.length} 条裁决 · ${result.blocking_rules.length} 阻断`
        : `${DEFAULT_PLUGINS.length} 个插件待命`,
    },
    {
      no: '04', icon: <AuditOutlined />, name: '合规裁决', en: 'VERDICT',
      desc: '最终状态 · 强制休息 · 成本变动',
      live: result ? (
        <span style={{ color: VERDICT_COLOR[result.final_status] || '#ffd666' }}>
          {result.final_status.toUpperCase()}
          {result.max_required_break_minutes > 0 ? ` · 休息 ${result.max_required_break_minutes}min` : ''}
        </span>
      ) : '待仿真',
    },
  ]
  return (
    <div className="sim-console" style={{ padding: '14px 18px 12px', marginBottom: 16 }}>
      <div style={{ position: 'relative', zIndex: 1 }}>
        <Space size={10} align="baseline" wrap style={{ marginBottom: 14 }}>
          <ThunderboltOutlined style={{ color: '#36cfc9', fontSize: 17 }} />
          <span style={{ color: '#fff', fontWeight: 800, fontSize: 15, letterSpacing: 2 }}>合规仿真管线</span>
          <span style={{ color: 'rgba(255,255,255,0.38)', fontSize: 10, letterSpacing: 2 }}>COMPLIANCE PIPELINE</span>
          <span style={{ color: 'rgba(255,255,255,0.55)', fontSize: 11 }}>
            场景参数 → 疲劳/能耗物理模型 → 多法规插件仲裁 → 合规裁决
          </span>
        </Space>
        <div style={{ display: 'flex', alignItems: 'stretch', overflowX: 'auto' }}>
          {stages.map((s, i) => (
            <React.Fragment key={s.no}>
              {i > 0 && <div className="pipe-arrow" />}
              <div className="pipe-stage">
                <span className="pipe-stage-no">{s.no}</span>
                <div style={{ color: '#fff', fontWeight: 800, fontSize: 13 }}>{s.icon} {s.name}</div>
                <div style={{ color: 'rgba(255,255,255,0.32)', fontSize: 9, letterSpacing: 2, margin: '1px 0 5px' }}>{s.en}</div>
                <div style={{ color: 'rgba(255,255,255,0.55)', fontSize: 10 }}>{s.desc}</div>
                <div style={{ marginTop: 6, borderTop: '1px dashed rgba(255,255,255,0.14)', paddingTop: 5, fontSize: 11, color: '#36cfc9', fontWeight: 700 }}>
                  {s.live}
                </div>
              </div>
            </React.Fragment>
          ))}
        </div>
      </div>
    </div>
  )
}

const ComplianceSim: React.FC = () => {
  const [form] = Form.useForm()
  const [plugins, setPlugins] = useState<PluginManifest[]>([])
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SimulationResult | null>(null)
  const [activeScenario, setActiveScenario] = useState<string>('high_heat')
  const { hint, check } = useRiskHint(form)

  useEffect(() => {
    getSimPlugins().then(setPlugins).catch(() => setPlugins([]))
  }, [])

  const pluginOptions = (plugins.length ? plugins.map(p => p.plugin_name) : DEFAULT_PLUGINS)
    .map(name => ({ label: name, value: name }))

  const applyScenario = (key: string) => {
    setActiveScenario(key)
    form.setFieldsValue(SCENARIOS[key].values)
    check()
  }

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
    } catch { /* interceptor reports */ }
    finally { setLoading(false) }
  }

  /* ── 决策表列定义 ── */
  const decisionColumns: ColumnsType<RuleDecision> = [
    {
      title: '规则', dataIndex: 'rule_code', width: 160,
      render: (v: string, r) => (
        <Tooltip title={`${r.plugin_name} v${r.rule_version}`}>
          <Text code style={{ fontSize: 11 }}>{v}</Text>
        </Tooltip>
      ),
    },
    {
      title: '类型', dataIndex: 'decision_type', width: 110,
      render: (v: string) => <Tag color={decisionTypeColor[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '优先级', dataIndex: 'priority', width: 70,
      render: (v: string) => <Tag color={priorityColor[v] || 'default'}>{v}</Tag>,
    },
    {
      title: '裁决信息', dataIndex: 'message', ellipsis: true,
      render: (v: string, r) => (
        <Space direction="vertical" size={0}>
          <Text style={{ fontSize: 12 }}>{v}</Text>
          {r.evidence.length > 0 && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              证据: {r.evidence.map(e => `${e.field}=${e.observed_value}${e.expected ? ` (限值 ${e.expected})` : ''}`).join(', ')}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '阻断', dataIndex: 'blocking', width: 60, align: 'center',
      render: (v: boolean) => v ? <Tag color="error">是</Tag> : <Tag color="success">否</Tag>,
    },
    {
      title: '成本 Δ', dataIndex: 'cost_delta', width: 90, align: 'right',
      render: (v: number) => v !== 0 ? <Text type={v > 0 ? 'danger' : 'success'}>{v > 0 ? '+' : ''}{v.toLocaleString()}</Text> : '-',
    },
    {
      title: '罚分', dataIndex: 'penalty_score', width: 60, align: 'center',
      render: (v: number) => v > 0 ? <Badge count={v} color="#f5222d" /> : '-',
    },
  ]

  const pluginColumns: ColumnsType<PluginRecord> = [
    { title: '插件', dataIndex: 'plugin_name', width: 200 },
    {
      title: '优先级', dataIndex: 'priority', width: 70,
      render: (v: string) => <Tag color={priorityColor[v] || 'default'}>{v}</Tag>,
    },
    { title: '法规包', dataIndex: 'legislation_pack', width: 140, render: (v: string) => v || '-' },
    {
      title: '耗时', dataIndex: 'duration_ms', width: 80, align: 'right',
      render: (v: number) => `${v.toFixed(1)} ms`,
    },
    {
      title: '状态', dataIndex: 'status', width: 80,
      render: (v: string, r) => v === 'ok' ? <Tag color="success">OK</Tag> : <Tag color="error">{r.error || v}</Tag>,
    },
    {
      title: '裁决数', dataIndex: 'decisions', width: 70, align: 'center',
      render: (d: RuleDecision[]) => (
        <Badge count={d.length} color={d.some(x => x.blocking) ? '#f5222d' : d.length ? '#1890ff' : '#d9d9d9'} />
      ),
    },
  ]

  /* ── 疲劳等级 ── */
  const fatigueLevel = useMemo(() => {
    if (!result) return null
    const s = result.fatigue_score
    if (s >= 70) return { text: '重度疲劳', color: '#f5222d' }
    if (s >= 40) return { text: '中度疲劳', color: '#faad14' }
    return { text: '轻度/正常', color: '#52c41a' }
  }, [result])

  const tipIcon = (field: string) => (
    <Tooltip title={FIELD_TIPS[field]}><InfoCircleOutlined style={{ color: '#999', marginLeft: 4 }} /></Tooltip>
  )

  return (
    <div>
      {/* 合规仿真流程管线图 */}
      <CompliancePipeline result={result} />

      {/* 场景预设 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Text strong>场景预设：</Text>
          {Object.entries(SCENARIOS).map(([key, s]) => (
            <Button
              key={key}
              type={activeScenario === key ? 'primary' : 'default'}
              icon={s.icon}
              onClick={() => applyScenario(key)}
            >
              {s.label}
            </Button>
          ))}
          {activeScenario && (
            <Text type="secondary" style={{ fontSize: 12 }}>{SCENARIOS[activeScenario].desc}</Text>
          )}
        </Space>
      </Card>

      <Row gutter={16}>
        {/* ── 左侧：参数表单 ── */}
        <Col xs={24} lg={14}>
          <Card title="作业场景参数" extra={
            hint && (
              <Tag color={hint.level === 'safe' ? 'success' : hint.level === 'warn' ? 'warning' : 'error'}>
                {hint.level === 'safe' ? <CheckCircleOutlined /> : <WarningOutlined />} {hint.text}
              </Tag>
            )
          }>
            <Form
              form={form}
              layout="vertical"
              onFinish={onFinish}
              onValuesChange={check}
              initialValues={{
                ...SCENARIOS.high_heat.values,
                plugin_names: DEFAULT_PLUGINS,
              }}
            >
              <Divider orientation="left" plain><ExperimentOutlined /> 物理输入</Divider>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item label={<span>时间步长(min){tipIcon('time_step_minutes')}</span>} name="time_step_minutes" rules={[{ required: true }]}>
                    <InputNumber min={1} max={480} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>步数{tipIcon('step_count')}</span>} name="step_count" rules={[{ required: true }]}>
                    <InputNumber min={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>负重(kg){tipIcon('load_weight_kg')}</span>} name="load_weight_kg">
                    <InputNumber min={0} max={500} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>姿态角度(°){tipIcon('posture_angle_deg')}</span>} name="posture_angle_deg">
                    <Slider min={0} max={180} marks={{ 0: '0°', 30: '30°', 60: '60°', 180: '180°' }}
                      tooltip={{ formatter: v => `${v}°` }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>连续作业(min){tipIcon('continuous_work_minutes')}</span>} name="continuous_work_minutes">
                    <InputNumber min={0} max={1440} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>移动距离(m){tipIcon('distance_meters')}</span>} name="distance_meters">
                    <InputNumber min={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>

              <Divider orientation="left" plain><EnvironmentOutlined /> 环境</Divider>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item label={<span>温度(℃){tipIcon('temperature_c')}</span>} name="temperature_c" rules={[{ required: true }]}>
                    <Slider min={-20} max={80} marks={{ '-20': '-20', 0: '0', 32: '32', 40: '40', 80: '80' }}
                      tooltip={{ formatter: v => `${v}°C` }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>湿度(%){tipIcon('humidity_percent')}</span>} name="humidity_percent">
                    <InputNumber min={0} max={100} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>噪声(dB){tipIcon('noise_db')}</span>} name="noise_db">
                    <InputNumber min={0} max={150} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>地形{tipIcon('terrain')}</span>} name="terrain">
                    <Select options={[
                      { label: '平地 (flat)', value: 'flat' },
                      { label: '斜坡 (slope)', value: 'slope' },
                      { label: '楼梯 (stairs)', value: 'stairs' },
                      { label: '不平地面 (uneven)', value: 'uneven' },
                    ]} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>坡度(%){tipIcon('floor_incline_percent')}</span>} name="floor_incline_percent">
                    <InputNumber min={0} max={100} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>

              <Divider orientation="left" plain><UserOutlined /> 作业上下文</Divider>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item label={<span>工人{tipIcon('worker_ref')}</span>} name="worker_ref" rules={[{ required: true }]}>
                    <Input placeholder="worker-001" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>班次{tipIcon('shift_id')}</span>} name="shift_id">
                    <Select options={[
                      { label: '白班 (shift-day)', value: 'shift-day' },
                      { label: '夜班 (shift-night)', value: 'shift-night' },
                      { label: '中班 (shift-swing)', value: 'shift-swing' },
                    ]} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>任务类型{tipIcon('task_type')}</span>} name="task_type">
                    <Select options={[
                      { label: '装配 (assembly)', value: 'assembly' },
                      { label: '物流 (logistics)', value: 'logistics' },
                      { label: '检验 (inspection)', value: 'inspection' },
                      { label: '包装 (packaging)', value: 'packaging' },
                      { label: '焊接 (welding)', value: 'welding' },
                    ]} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>区域{tipIcon('zone_id')}</span>} name="zone_id">
                    <Input placeholder="line-a" />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label={<span>动作{tipIcon('action_type')}</span>} name="action_type">
                    <Select options={[
                      { label: '行走 (walk)', value: 'walk' },
                      { label: '搬运 (lift)', value: 'lift' },
                      { label: '推 (push)', value: 'push' },
                      { label: '拉 (pull)', value: 'pull' },
                      { label: '装配 (assemble)', value: 'assemble' },
                      { label: '检验 (inspect)', value: 'inspect' },
                      { label: '待机 (idle)', value: 'idle' },
                    ]} />
                  </Form.Item>
                </Col>
              </Row>

              <Divider orientation="left" plain><SafetyCertificateOutlined /> 法规插件</Divider>
              <Form.Item name="plugin_names" rules={[{ required: true, message: '至少选择一个插件' }]}>
                <Select mode="multiple" options={pluginOptions} placeholder="选择参与裁决的法规插件" />
              </Form.Item>

              <Button type="primary" htmlType="submit" loading={loading} icon={<ThunderboltOutlined />} block size="large">
                运行仿真
              </Button>
            </Form>
          </Card>
        </Col>

        {/* ── 右侧：仿真结果 ── */}
        <Col xs={24} lg={10}>
          <Card title="仿真结果" style={{ minHeight: 400 }}>
            {!result ? (
              <Empty description="填写参数后点击「运行仿真」" style={{ marginTop: 80 }} />
            ) : (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                {/* 状态总览 */}
                <Card size="small" style={{
                  background: result.legal_blocked ? '#fff2f0' : result.final_status === 'accepted' ? '#f6ffed' : '#fffbe6',
                  border: `1px solid ${result.legal_blocked ? '#ffccc7' : result.final_status === 'accepted' ? '#b7eb8f' : '#ffe58f'}`,
                }}>
                  <Space align="center" style={{ width: '100%', justifyContent: 'space-between' }}>
                    <Space>
                      <SafetyCertificateOutlined style={{ fontSize: 24, color: result.legal_blocked ? '#f5222d' : '#52c41a' }} />
                      <div>
                        <Tag color={statusColor[result.final_status] || 'default'} style={{ fontSize: 14, padding: '4px 12px' }}>
                          {result.final_status.toUpperCase()}
                        </Tag>
                        {result.legal_blocked && <Tag color="error">法规阻断</Tag>}
                      </div>
                    </Space>
                    {result.winning_priority && (
                      <Tag color={priorityColor[result.winning_priority]}>
                        胜出优先级: {result.winning_priority}
                      </Tag>
                    )}
                  </Space>
                </Card>

                {/* 核心指标 */}
                <Row gutter={12}>
                  <Col span={12}>
                    <Card size="small">
                      <div style={{ textAlign: 'center' }}>
                        <Progress
                          type="dashboard"
                          percent={Math.min(100, result.fatigue_score)}
                          strokeColor={fatigueLevel?.color}
                          format={() => result.fatigue_score.toFixed(1)}
                          size={100}
                        />
                        <div style={{ marginTop: 4 }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>疲劳评分</Text>
                          <br />
                          <Tag color={fatigueLevel?.color} style={{ marginTop: 4 }}>{fatigueLevel?.text}</Tag>
                        </div>
                      </div>
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Space direction="vertical" size={8} style={{ width: '100%' }}>
                      <Card size="small"><Statistic title="能耗" value={result.energy_kcal} precision={1} suffix="kcal" /></Card>
                      <Card size="small"><Statistic title="成本增量" value={result.total_cost_delta} precision={0} prefix="VND" valueStyle={{ color: result.total_cost_delta > 0 ? '#f5222d' : '#52c41a' }} /></Card>
                      <Card size="small"><Statistic title="强制休息" value={result.max_required_break_minutes} suffix="min" prefix={<ClockCircleOutlined />} /></Card>
                    </Space>
                  </Col>
                </Row>

                {/* 阻断 & 告警 */}
                {(result.blocking_rules.length > 0 || result.warnings.length > 0) && (
                  <Card size="small" title={<span><WarningOutlined style={{ color: '#faad14' }} /> 阻断 & 告警</span>}>
                    {result.blocking_rules.length > 0 && (
                      <div style={{ marginBottom: 8 }}>
                        <Text strong style={{ color: '#f5222d', fontSize: 12 }}>阻断规则:</Text>
                        <div>{result.blocking_rules.map(r => <Tag color="error" key={r} style={{ margin: '2px' }}>{r}</Tag>)}</div>
                      </div>
                    )}
                    {result.warnings.length > 0 && (
                      <div>
                        <Text strong style={{ color: '#faad14', fontSize: 12 }}>告警:</Text>
                        <div>{result.warnings.map(r => <Tag color="warning" key={r} style={{ margin: '2px' }}>{r}</Tag>)}</div>
                      </div>
                    )}
                  </Card>
                )}

                {/* 强制措施 */}
                {result.applied_actions.length > 0 && (
                  <Card size="small" title={<span><SafetyCertificateOutlined style={{ color: '#1890ff' }} /> 强制措施</span>}>
                    {result.applied_actions.map((a, i) => (
                      <div key={i} style={{ marginBottom: 8, padding: '6px 10px', background: '#f0f5ff', borderRadius: 4 }}>
                        <Text strong style={{ fontSize: 12 }}>{a.action_code}</Text>
                        <br />
                        <Text style={{ fontSize: 12 }}>{a.description}</Text>
                        {a.break_minutes > 0 && <Tag color="blue" style={{ marginLeft: 8 }}>休息 {a.break_minutes} min</Tag>}
                      </div>
                    ))}
                  </Card>
                )}

                {/* 插件执行记录 */}
                {result.plugin_records.length > 0 && (
                  <Collapse size="small" items={[{
                    key: 'plugins',
                    label: <span><SafetyCertificateOutlined /> 插件执行记录 ({result.plugin_records.length})</span>,
                    children: (
                      <Table
                        size="small"
                        rowKey="plugin_name"
                        columns={pluginColumns}
                        dataSource={result.plugin_records}
                        pagination={false}
                        scroll={{ x: 600 }}
                      />
                    ),
                  }]} />
                )}

                {/* 全部裁决明细 */}
                {result.all_decisions.length > 0 && (
                  <Collapse size="small" items={[{
                    key: 'decisions',
                    label: <span><DashboardOutlined /> 裁决明细 ({result.all_decisions.length})</span>,
                    children: (
                      <Table
                        size="small"
                        rowKey={(r, i) => `${r.rule_code}-${i}`}
                        columns={decisionColumns}
                        dataSource={result.all_decisions}
                        pagination={false}
                        scroll={{ x: 700 }}
                      />
                    ),
                  }]} />
                )}

                {/* 物理快照 */}
                {result.snapshot && (
                  <Collapse size="small" items={[{
                    key: 'snapshot',
                    label: <span><ExperimentOutlined /> 物理快照</span>,
                    children: (
                      <Descriptions column={2} size="small" bordered>
                        <Descriptions.Item label="工人">{result.snapshot.worker_ref}</Descriptions.Item>
                        <Descriptions.Item label="班次">{result.snapshot.shift_id}</Descriptions.Item>
                        <Descriptions.Item label="任务">{result.snapshot.task_type}</Descriptions.Item>
                        <Descriptions.Item label="区域">{result.snapshot.zone_id}</Descriptions.Item>
                        <Descriptions.Item label="动作">{result.snapshot.action_type}</Descriptions.Item>
                        <Descriptions.Item label="地形">{result.snapshot.terrain}</Descriptions.Item>
                        <Descriptions.Item label="温度">{result.snapshot.temperature_c}°C</Descriptions.Item>
                        <Descriptions.Item label="湿度">{result.snapshot.humidity_percent}%</Descriptions.Item>
                        <Descriptions.Item label="噪声">{result.snapshot.noise_db ?? '-'} dB</Descriptions.Item>
                        <Descriptions.Item label="坡度">{result.snapshot.floor_incline_percent}%</Descriptions.Item>
                        <Descriptions.Item label="步数">{result.snapshot.step_count}</Descriptions.Item>
                        <Descriptions.Item label="距离">{result.snapshot.distance_meters} m</Descriptions.Item>
                        <Descriptions.Item label="负重">{result.snapshot.load_weight_kg} kg</Descriptions.Item>
                        <Descriptions.Item label="姿态角">{result.snapshot.posture_angle_deg}°</Descriptions.Item>
                        <Descriptions.Item label="连续作业">{result.snapshot.continuous_work_minutes} min</Descriptions.Item>
                        <Descriptions.Item label="时间戳">{result.snapshot.timestamp}</Descriptions.Item>
                      </Descriptions>
                    ),
                  }]} />
                )}

                {/* 元信息 */}
                <div style={{ textAlign: 'center' }}>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    仿真ID: {result.simulation_id} | 物理核心: {result.physics_core_version} | 仲裁器: {result.arbiter_version}
                  </Text>
                </div>
              </Space>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default ComplianceSim
