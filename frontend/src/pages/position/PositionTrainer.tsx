import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
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
  Tag,
  Typography,
  message,
} from 'antd'
import { ArrowLeftOutlined, CheckCircleOutlined, ReloadOutlined, TrophyOutlined } from '@ant-design/icons'
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

const PositionTrainer: React.FC<{ pmcMode?: boolean }> = ({ pmcMode = false }) => {
  const navigate = useNavigate()
  const factoryId = getActiveFactoryId()
  const [positions, setPositions] = useState<TrainingPosition[]>([])
  const [positionCode, setPositionCode] = useState('pmc')
  const [mode, setMode] = useState<'focus' | 'idle'>('focus')
  const [pack, setPack] = useState<any>(null)
  const [answers, setAnswers] = useState<Record<string, string[]>>({})
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const loadPositions = useCallback(async () => {
    try {
      const data: any = await api.get('/api/v1/trainer/positions')
      setPositions(data.positions || [])
    } catch {
      // 训练包仍然可以按默认职位加载；职位目录失败会在页面上保留当前职位。
    }
  }, [])

  const loadPack = useCallback(async () => {
    setLoading(true)
    setError('')
    setAnswers({})
    setResult(null)
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

  const questions: TrainingQuestion[] = pack?.quiz?.questions || []
  const answeredCount = useMemo(
    () => questions.filter((question) => (answers[question.id] || []).length > 0).length,
    [answers, questions],
  )
  const passScore = pack?.quiz?.pass_score ?? 80

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

        {loading && <Card><Spin tip="加载职位训练包" /></Card>}
        {!loading && error && (
          <Alert type="error" showIcon message={error} action={<Button icon={<ReloadOutlined />} onClick={loadPack}>重试</Button>} />
        )}
        {!loading && !error && (
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
        )}

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
      </Space>
    </div>
  )
}

export default PositionTrainer
