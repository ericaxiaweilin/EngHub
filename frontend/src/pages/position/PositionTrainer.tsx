import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
  Empty,
  Input,
  InputNumber,
  List,
  Progress,
  Radio,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Statistic,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  ArrowLeftOutlined,
  BookOutlined,
  CheckCircleOutlined,
  CompassOutlined,
  ReloadOutlined,
  RocketOutlined,
  TrophyOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../../services/api'
import { getActiveFactoryId } from '../../utils/factory'

const { Text, Title, Paragraph } = Typography

interface TrainingPosition {
  code: string
  title: string
  duties: string
}

interface TrainingQuestion {
  id: string
  question_code: string
  skill: string
  difficulty: number
  question_type: 'single' | 'multi' | 'multiple' | 'true_false' | 'fill' | 'calc' | 'order'
  prompt: string
  options: Array<{ value: string; label: string }>
  points: number
}

const QuizTab: React.FC<{
  pack: any
  loading: boolean
  error: string
  loadPack: () => void
  mode: 'focus' | 'idle'
  passScore: number
  factoryId: string
  positionCode: string
  onLoaded: (pack: any) => void
}> = ({ pack, loading, error, loadPack, mode, passScore, factoryId, positionCode }) => {
  const [answers, setAnswers] = useState<Record<string, string[]>>({})
  const [result, setResult] = useState<any>(null)
  const [submitting, setSubmitting] = useState(false)
  const packKey = pack?.quiz?.title

  const questions: TrainingQuestion[] = pack?.quiz?.questions || []
  const answeredCount = useMemo(
    () => questions.filter((question) => (answers[question.id] || []).length > 0).length,
    [answers, questions],
  )

  useEffect(() => {
    setAnswers({})
    setResult(null)
  }, [packKey, positionCode, mode])

  const submit = async () => {
    if (!questions.length) {
      message.warning('当前职位还没有可用题目')
      return
    }
    if (answeredCount < questions.length) {
      message.warning(`还有 ${questions.length - answeredCount} 道题未作答`)
      return
    }
    setSubmitting(true)
    try {
      const data: any = await api.post('/api/v1/trainer/attempts', {
        position_code: positionCode,
        factory_id: factoryId,
        mode,
        answers,
      })
      setResult(data)
      message.success(data.passed ? '已通过职位训练测试' : '已完成，请按错题复盘')
    } catch {
      message.error('提交训练测试失败')
    } finally {
      setSubmitting(false)
    }
  }

  const reset = () => {
    setAnswers({})
    setResult(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const setAnswer = (question: TrainingQuestion, values: string[]) => {
    setAnswers((current) => ({ ...current, [question.id]: values }))
  }

  if (loading) return <Card><Spin tip="加载职位训练包" /></Card>
  if (error) {
    return <Alert type="error" showIcon message={error} action={<Button icon={<ReloadOutlined />} onClick={loadPack}>重试</Button>} />
  }

  return (
    <>
      <Card
        size="small"
        title={<Space><TrophyOutlined style={{ color: '#1677ff' }} />{pack?.quiz?.title || '职位小测试'}</Space>}
        extra={
          <Space>
            <Tag color={mode === 'focus' ? 'blue' : 'green'}>{pack?.mode_label || (mode === 'focus' ? '专注答题' : '空闲答题')}</Tag>
            <Tag>{questions.length} 题 / 通过线 {passScore} 分</Tag>
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          message={pack?.mission || '先按职位流程核对输入、判断标准和交付物，再进入岗位小测试。'}
          description="题目、答案和评分由职位训练接口提供；完成后只显示本次结果和错题解释。"
          style={{ marginBottom: 14 }}
        />
        <Space direction="vertical" style={{ width: '100%' }} size={14}>
          {questions.map((question, index) => (
            <div key={question.id} style={{ padding: '8px 0 14px', borderBottom: '1px solid var(--color-border)' }}>
              <Space align="start">
                <Tag color={question.difficulty >= 3 ? 'red' : question.difficulty === 2 ? 'gold' : 'blue'}>{question.skill}</Tag>
                <Text strong>{index + 1}. {question.prompt}</Text>
              </Space>
              <div style={{ marginTop: 9, paddingLeft: 8 }}>
                {question.question_type === 'order' ? (
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Text type="secondary">点击选项按正确顺序排列（可重置）</Text>
                    <Space wrap>
                      {(question.options || []).map((option) => {
                        if ((answers[question.id] || []).includes(option.value)) return null
                        return (
                          <Button key={option.value} size="small" onClick={() => setAnswer(question, [...(answers[question.id] || []), option.value])}>
                            {option.label}
                          </Button>
                        )
                      })}
                    </Space>
                    {(answers[question.id] || []).length > 0 && (
                      <div>
                        <Space size={[4, 4]} wrap style={{ marginBottom: 8 }}>
                          {(answers[question.id] || []).map((value, idx) => {
                            const option = (question.options || []).find((o) => o.value === value)
                            return <Tag key={value} color="blue">{idx + 1}. {option?.label || value}</Tag>
                          })}
                        </Space>
                        <Button size="small" type="link" onClick={() => setAnswer(question, [])}>重置顺序</Button>
                      </div>
                    )}
                  </Space>
                ) : question.question_type === 'fill' ? (
                  <Input
                    style={{ maxWidth: 420 }}
                    placeholder="请输入答案"
                    value={(answers[question.id] || [])[0] || ''}
                    onChange={(event) => setAnswer(question, [event.target.value])}
                  />
                ) : question.question_type === 'calc' ? (
                  <InputNumber
                    style={{ minWidth: 180 }}
                    placeholder="请输入计算结果"
                    value={(answers[question.id] || [])[0] ? Number((answers[question.id] || [])[0]) : undefined}
                    onChange={(value) => setAnswer(question, value === null || value === undefined ? [] : [String(value)])}
                  />
                ) : question.question_type === 'multi' || question.question_type === 'multiple' ? (
                  <Checkbox.Group value={answers[question.id] || []} onChange={(values) => setAnswer(question, values.map(String))}>
                    <Space direction="vertical">
                      {(question.options || []).map((option) => <Checkbox key={option.value} value={option.value}>{option.label}</Checkbox>)}
                    </Space>
                  </Checkbox.Group>
                ) : (
                  <Radio.Group value={(answers[question.id] || [])[0]} onChange={(event) => setAnswer(question, [event.target.value])}>
                    <Space direction="vertical">
                      {(question.options || []).map((option) => <Radio key={option.value} value={option.value}>{option.label}</Radio>)}
                    </Space>
                  </Radio.Group>
                )}
              </div>
            </div>
          ))}
          <Space wrap>
            <Text type="secondary">已作答 {answeredCount}/{questions.length}</Text>
            <Progress percent={questions.length ? Math.round(answeredCount / questions.length * 100) : 0} size="small" style={{ width: 160 }} showInfo={false} />
            <Button type="primary" icon={<CheckCircleOutlined />} loading={submitting} onClick={submit}>提交测试</Button>
            <Button icon={<ReloadOutlined />} onClick={reset}>重新作答</Button>
          </Space>
        </Space>
      </Card>

      {result && (
        <Card size="small" title="测试结果">
          <Alert
            type={result.passed ? 'success' : 'warning'}
            showIcon
            message={`得分 ${result.score} · ${result.passed ? '通过' : '建议复盘错题'}`}
            description={`答对 ${result.earned_points}/${result.total_points} 分，通过线 ${passScore} 分。`}
          />
          {result.details?.some((item: any) => !item.correct) && (
            <>
              <Divider orientation="left" plain>错题复盘</Divider>
              <List
                size="small"
                dataSource={result.details.filter((item: any) => !item.correct)}
                renderItem={(item: any) => (
                  <List.Item>
                    <Space align="start"><Tag color="error">{item.question_code}</Tag><Text>{item.explanation}</Text></Space>
                  </List.Item>
                )}
              />
            </>
          )}
        </Card>
      )}
    </>
  )
}

const STATUS_COLOR: Record<string, string> = {
  suggest_review: 'red',
  practice: 'gold',
  solid: 'green',
}

const MasteryTab: React.FC<{ positionCode: string; factoryId: string }> = ({ positionCode, factoryId }) => {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res: any = await api.get('/api/v1/trainer/mastery', {
        params: { position_code: positionCode, factory_id: factoryId },
      })
      setData(res)
    } catch (err: any) {
      setError(err?.response?.data?.detail || '掌握度加载失败')
    } finally {
      setLoading(false)
    }
  }, [positionCode, factoryId])

  useEffect(() => { load() }, [load])

  if (loading) return <Card><Spin tip="计算技能掌握度" /></Card>
  if (error) return <Alert type="error" showIcon message={error} action={<Button icon={<ReloadOutlined />} onClick={load}>重试</Button>} />

  const skills: any[] = data?.skills || []
  const practiced = skills.filter((s) => s.accuracy !== null)
  const avgAccuracy = practiced.length
    ? Math.round(practiced.reduce((sum, s) => sum + (s.accuracy || 0), 0) / practiced.length)
    : null
  const overall = skills.length ? Math.round(skills.reduce((sum, s) => sum + (s.mastery || 0), 0) / skills.length) : 0

  return (
    <Card
      size="small"
      title={<Space><RocketOutlined style={{ color: '#1677ff' }} />技能掌握度雷达</Space>}
      extra={<Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>}
    >
      <Alert
        type="info"
        showIcon
        message="基于历史答题计算每个技能的正确率与掌握度"
        description={data?.legend ? Object.entries(data.legend).map(([k, v]) => `${v}`).join(' · ') : ''}
        style={{ marginBottom: 14 }}
      />
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={8} md={4}><Card size="small"><Statistic title="技能总数" value={skills.length} /></Card></Col>
        <Col xs={8} md={4}><Card size="small"><Statistic title="已练习技能" value={practiced.length} /></Card></Col>
        <Col xs={8} md={4}><Card size="small"><Statistic title="平均掌握度" value={overall} suffix="%" /></Card></Col>
        <Col xs={8} md={4}>
          <Card size="small">
            <Statistic title="平均正确率" value={avgAccuracy ?? '—'} suffix={avgAccuracy !== null ? '%' : ''} valueStyle={{ color: avgAccuracy === null ? undefined : (avgAccuracy >= 80 ? '#52c41a' : avgAccuracy >= 60 ? '#faad14' : '#f5222d') }} />
          </Card>
        </Col>
      </Row>
      <Space direction="vertical" style={{ width: '100%' }} size={10}>
        {skills.map((s) => (
          <div key={s.skill} style={{ padding: '8px 10px', borderRadius: 8, border: '1px solid var(--color-border)' }}>
            <Space style={{ width: '100%', justifyContent: 'space-between' }}>
              <Space>
                <Tag color={STATUS_COLOR[s.status] || 'default'}>{s.status === 'solid' ? '扎实' : s.status === 'practice' ? '待练' : '需复盘'}</Tag>
                <Text strong>{s.skill}</Text>
                <Text type="secondary">题库 {s.bank_size} 题 · 作答 {s.attempts} 次 · 均难度 {s.avg_difficulty}</Text>
              </Space>
              <Space>
                <Text style={{ width: 56, textAlign: 'right' }}>{s.accuracy === null ? '未练' : `${s.accuracy}%`}</Text>
                <Progress type="circle" size={40} percent={s.mastery} strokeColor={s.mastery >= 80 ? '#52c41a' : s.mastery >= 50 ? '#faad14' : '#f5222d'} />
              </Space>
            </Space>
            <Progress percent={s.mastery} strokeColor={s.mastery >= 80 ? '#52c41a' : s.mastery >= 50 ? '#faad14' : '#f5222d'} size="small" />
          </div>
        ))}
      </Space>
    </Card>
  )
}

const ReviewTab: React.FC<{ positionCode: string; factoryId: string }> = ({ positionCode, factoryId }) => {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res: any = await api.get('/api/v1/trainer/review', {
        params: { position_code: positionCode, factory_id: factoryId },
      })
      setData(res)
    } catch (err: any) {
      setError(err?.response?.data?.detail || '错题本加载失败')
    } finally {
      setLoading(false)
    }
  }, [positionCode, factoryId])

  useEffect(() => { load() }, [load])

  if (loading) return <Card><Spin tip="聚合历史错题" /></Card>
  if (error) return <Alert type="error" showIcon message={error} action={<Button icon={<ReloadOutlined />} onClick={load}>重试</Button>} />

  const skills: any[] = data?.skills || []
  const hasWrong = (data?.distinct_wrong ?? 0) > 0

  return (
    <Card
      size="small"
      title={<Space><BookOutlined style={{ color: '#faad14' }} />错题本</Space>}
      extra={<Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>}
    >
      <Alert
        type={hasWrong ? 'warning' : 'success'}
        showIcon
        message={hasWrong ? `共 ${data.distinct_wrong} 道错题（历史 ${data.total_attempts} 次练习）` : '暂无错题，继续保持！'}
        description={data?.mission || ''}
        style={{ marginBottom: 14 }}
      />
      {!hasWrong ? (
        <Card><Empty style={{ padding: 24 }} description="还没有历史错题" /></Card>
      ) : (
        skills.map((skill) => (
          <Card
            key={skill.skill}
            size="small"
            style={{ marginBottom: 12 }}
            title={<Space><Tag color="error">{skill.skill}</Tag><Text type="secondary">{skill.count} 道错题</Text></Space>}
          >
            <List
              size="small"
              dataSource={skill.questions}
              renderItem={(q: any, idx: number) => (
                <List.Item style={{ alignItems: 'flex-start' }}>
                  <Space align="start" style={{ width: '100%' }}>
                    <Tag color="red">{idx + 1}</Tag>
                    <div style={{ flex: 1 }}>
                      <div>
                        <Tag color={q.difficulty >= 3 ? 'red' : q.difficulty === 2 ? 'gold' : 'blue'}>难度{q.difficulty}</Tag>
                        <Text>{q.prompt || q.question_code}</Text>
                      </div>
                      <div style={{ marginTop: 6 }}>
                        <Space direction="vertical" size={4}>
                          <Text type="secondary">你的答案：{q.selected?.length ? q.selected.join('、') : '（空）'}</Text>
                          <Text style={{ color: '#52c41a' }}>正确答案：{q.answer?.join('、') || '—'}</Text>
                          {q.explanation && <Text type="secondary">解析：{q.explanation}</Text>}
                          {(q.reference_terms || []).length > 0 && (
                            <Text type="secondary">术语：{(q.reference_terms || []).join('、')}</Text>
                          )}
                        </Space>
                      </div>
                    </div>
                  </Space>
                </List.Item>
              )}
            />
          </Card>
        ))
      )}
    </Card>
  )
}

const LEVEL_DESC: Record<number, string> = {
  1: '基础判断 · 真实销售订单，判断评审结论',
  2: '缺料决策 · 真实工单缺料，选择处置动作',
  3: '综合排程 · 订单交期 × 系统缺料，综合决策',
}

const DrillsTab: React.FC<{ positionCode: string; factoryId: string }> = ({ positionCode, factoryId }) => {
  const [level, setLevel] = useState<number>(1)
  const [data, setData] = useState<any>(null)
  const [answers, setAnswers] = useState<Record<string, string[]>>({})
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    setAnswers({})
    setResult(null)
    try {
      const res: any = await api.get('/api/v1/trainer/drills', {
        params: { position_code: positionCode, factory_id: factoryId, level, limit: 3 },
      })
      setData(res)
    } catch (err: any) {
      setError(err?.response?.data?.detail || '实操演练加载失败')
    } finally {
      setLoading(false)
    }
  }, [positionCode, factoryId, level])

  useEffect(() => { load() }, [load])

  const drills: any[] = data?.drills || []
  const answeredCount = drills.filter((d) => (answers[d.id] || []).length > 0).length

  const submit = async () => {
    if (!drills.length) {
      message.warning('当前没有实操题')
      return
    }
    if (answeredCount < drills.length) {
      message.warning(`还有 ${drills.length - answeredCount} 道未作答`)
      return
    }
    setSubmitting(true)
    try {
      const res: any = await api.post('/api/v1/trainer/drills/attempts', {
        position_code: positionCode,
        factory_id: factoryId,
        level,
        answers,
      })
      setResult(res)
      message.success(res.passed ? '实操演练通过' : '请查看正确处置原则')
    } catch {
      message.error('提交失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card
      size="small"
      title={<Space><CompassOutlined style={{ color: '#13c2c2' }} />实操演练 · 真实数据驱动</Space>}
      extra={<Button icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新题目</Button>}
    >
      <Alert
        type="info"
        showIcon
        message="题目基于系统真实业务数据生成，不念经"
        description={data?.mission || '销售订单 / 工单缺料 / 库存 实时场景。'}
        style={{ marginBottom: 14 }}
      />
      <Space style={{ marginBottom: 14 }} align="center">
        <Text strong>难度梯度</Text>
        <Segmented
          value={level}
          onChange={(v) => setLevel(Number(v))}
          options={[
            { label: 'L1 基础', value: 1 },
            { label: 'L2 缺料', value: 2 },
            { label: 'L3 综合', value: 3 },
          ]}
        />
        <Text type="secondary">{LEVEL_DESC[level]}</Text>
      </Space>

      {loading && <Card><Spin tip="生成真实场景题" /></Card>}
      {!loading && error && <Alert type="error" showIcon message={error} action={<Button onClick={load}>重试</Button>} />}
      {!loading && !error && (
        <>
          {drills.map((drill, index) => (
            <div key={`${drill.scene}-${index}`} style={{ padding: '10px 12px', marginBottom: 12, borderRadius: 8, border: '1px solid var(--color-border)' }}>
              <Space align="start" wrap style={{ width: '100%' }}>
                <Tag color="cyan">{drill.type === 'order_review' ? '订单评审' : drill.type === 'shortage_action' ? '缺料处置' : '排程决策'}</Tag>
                <Text strong>{drill.scene}</Text>
              </Space>
              <div style={{ margin: '8px 0 4px', paddingLeft: 6 }}>
                {drill.type === 'order_review' && (
                  <Space wrap>
                    <Tag>{drill.data.product}</Tag>
                    <Tag>数量 {drill.data.qty}</Tag>
                    <Tag color="red">RDD {drill.data.rdd}</Tag>
                    <Tag color={drill.data.priority === 'high' ? 'red' : 'blue'}>优先级 {drill.data.priority}</Tag>
                    <Tag>{drill.data.material_ready}</Tag>
                    <Tag>状态 {drill.data.status}</Tag>
                  </Space>
                )}
                {drill.type === 'shortage_action' && (
                  <Space wrap>
                    <Tag>{drill.data.material}</Tag>
                    <Tag>需 {drill.data.required}</Tag>
                    <Tag color="green">可用 {drill.data.available}</Tag>
                    <Tag color="red">缺口 {drill.data.shortage}</Tag>
                  </Space>
                )}
                {drill.type === 'schedule_priority' && (
                  <Space wrap>
                    <Tag>{drill.data.product}</Tag>
                    <Tag>数量 {drill.data.qty}</Tag>
                    <Tag color="red">RDD {drill.data.rdd}</Tag>
                    <Tag color={drill.data.priority === 'high' ? 'red' : 'blue'}>优先级 {drill.data.priority}</Tag>
                    {(drill.data.system_shortages || []).map((s: string) => <Tag color="red" key={s}>{s}</Tag>)}
                  </Space>
                )}
              </div>
              <div style={{ margin: '6px 0 10px', paddingLeft: 6 }}>
                <Text strong>{index + 1}. {drill.prompt}</Text>
              </div>
              <Radio.Group
                value={(answers[drill.id] || [])[0]}
                onChange={(e) => setAnswers((cur) => ({ ...cur, [drill.id]: [e.target.value] }))}
              >
                <Space direction="vertical">
                  {(drill.options || []).map((opt: any) => <Radio key={opt.value} value={opt.value}>{opt.label}</Radio>)}
                </Space>
              </Radio.Group>
              {result && (
                <div style={{ marginTop: 10, padding: '8px 10px', borderRadius: 6, background: 'var(--color-fill-secondary)' }}>
                  {(() => {
                    const detail = result.details?.find((x: any) => x.id === drill.id)
                    return (
                      <Space direction="vertical" size={4}>
                        <Tag color={detail?.correct ? 'green' : 'red'}>{detail?.correct ? '✓ 正确' : '✗ 不正确'}</Tag>
                        {!detail?.correct && <Text>正确答案：{detail?.answer?.join('、')}</Text>}
                        <Text type="secondary">{drill.explanation}</Text>
                      </Space>
                    )
                  })()}
                </div>
              )}
            </div>
          ))}
          <Space wrap>
            <Text type="secondary">已作答 {answeredCount}/{drills.length}</Text>
            <Button type="primary" icon={<CheckCircleOutlined />} loading={submitting} onClick={submit}>提交演练</Button>
            <Button icon={<ReloadOutlined />} onClick={() => { setAnswers({}); setResult(null) }}>重新作答</Button>
          </Space>
        </>
      )}
    </Card>
  )
}

const PositionTrainer: React.FC<{ pmcMode?: boolean }> = ({ pmcMode = false }) => {
  const navigate = useNavigate()
  const factoryId = getActiveFactoryId()
  const [positions, setPositions] = useState<TrainingPosition[]>([])
  const [positionCode, setPositionCode] = useState('pmc')
  const [mode, setMode] = useState<'focus' | 'idle'>('focus')
  const [tab, setTab] = useState('quiz')
  const [pack, setPack] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadPositions = useCallback(async () => {
    try {
      const data: any = await api.get('/api/v1/trainer/positions')
      setPositions(data.positions || [])
    } catch {
      // 职位目录失败不影响训练包默认加载
    }
  }, [])

  const loadPack = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data: any = await api.get('/api/v1/trainer/pack', {
        params: { position_code: positionCode, factory_id: factoryId, mode },
      })
      setPack(data)
    } catch (err: any) {
      setPack(null)
      setError(err?.response?.data?.detail || '职位训练包加载失败，请确认训练数据接口和迁移已就绪。')
    } finally {
      setLoading(false)
    }
  }, [factoryId, positionCode, mode])

  useEffect(() => {
    loadPositions()
  }, [loadPositions])

  useEffect(() => {
    loadPack()
  }, [loadPack])

  const passScore = pack?.quiz?.pass_score ?? 80

  return (
    <div style={{ padding: 24, maxWidth: 1180, margin: '0 auto' }}>
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        <Space align="center" wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(pmcMode ? '/pmc' : '/')}>
            {pmcMode ? '返回 PMC 工作台' : '返回首页'}
          </Button>
          <Title level={3} style={{ margin: 0 }}>{pmcMode ? 'PMC 职位训练器' : '职位训练器'}</Title>
          <Tag color="blue">接口驱动</Tag>
        </Space>

        <Card size="small">
          <Space direction="vertical" style={{ width: '100%' }} size={10}>
            <Space wrap align="center">
              <Text strong>训练职位</Text>
              <Select
                showSearch
                value={positionCode}
                style={{ minWidth: 240 }}
                options={positions.map((position) => ({ value: position.code, label: position.title }))}
                onChange={setPositionCode}
                loading={!positions.length}
              />
              <Text type="secondary">工厂：{factoryId || '-'}</Text>
              <Segmented
                value={mode}
                onChange={(value) => setMode(value as 'focus' | 'idle')}
                options={[
                  { label: '专注答题', value: 'focus' },
                  { label: '空闲答题', value: 'idle' },
                ]}
              />
              <Button icon={<ReloadOutlined />} onClick={loadPack} loading={loading}>刷新训练包</Button>
            </Space>
            {pack?.position && (
              <>
                <Title level={4} style={{ margin: '4px 0 0' }}>{pack.position.title}</Title>
                <Paragraph style={{ margin: 0 }}>{pack.position.duties}</Paragraph>
                <Row gutter={[12, 12]}>
                  <Col xs={24} lg={15}>
                    <Card size="small" title="标准工作路径">
                      <List
                        size="small"
                        dataSource={pack.position.daily_flow || []}
                        renderItem={(item: any) => (
                          <List.Item>
                            <Space align="start">
                              <Tag color="blue">{item.step}</Tag>
                              <div><Text strong>{item.task}</Text><div><Text type="secondary">{item.detail}</Text></div></div>
                            </Space>
                          </List.Item>
                        )}
                      />
                    </Card>
                  </Col>
                  <Col xs={24} lg={9}>
                    <Card size="small" title="异常升级与工具">
                      <Paragraph style={{ marginBottom: 8 }}>{pack.position.escalation || '-'}</Paragraph>
                      <Text type="secondary">{pack.position.related_tools || '-'}</Text>
                    </Card>
                  </Col>
                </Row>
              </>
            )}
          </Space>
        </Card>

        <Tabs
          activeKey={tab}
          onChange={setTab}
          items={[
            {
              key: 'quiz',
              label: <Space><TrophyOutlined />刷题练习</Space>,
              children: (
                <QuizTab
                  pack={pack}
                  loading={loading}
                  error={error}
                  loadPack={loadPack}
                  mode={mode}
                  passScore={passScore}
                  factoryId={factoryId}
                  positionCode={positionCode}
                  onLoaded={() => undefined}
                />
              ),
            },
            {
              key: 'mastery',
              label: <Space><RocketOutlined />技能掌握度</Space>,
              children: <MasteryTab positionCode={positionCode} factoryId={factoryId} />,
            },
            {
              key: 'review',
              label: <Space><BookOutlined />错题本</Space>,
              children: <ReviewTab positionCode={positionCode} factoryId={factoryId} />,
            },
            {
              key: 'drills',
              label: <Space><CompassOutlined />实操演练</Space>,
              children: <DrillsTab positionCode={positionCode} factoryId={factoryId} />,
            },
          ]}
        />
      </Space>
    </div>
  )
}

export default PositionTrainer