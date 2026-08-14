import React, { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Collapse, Space, Spin, Tag, Typography } from 'antd'
import { ArrowLeftOutlined, BookOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../../services/api'
import { getActiveFactoryId } from '../../utils/factory'
import PmcKnowledgeGraph, { SkillPanel, NEURAL_COLORS } from './PmcKnowledgeGraph'

const { Text, Title, Paragraph } = Typography

/** PMC 知识库：神经蛛网式 RAG 可视化。内容复用训练包接口。 */
const PmcKnowledge: React.FC = () => {
  const navigate = useNavigate()
  const factoryId = getActiveFactoryId()
  const [pack, setPack] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data: any = await api.get('/api/v1/trainer/pack', {
        params: { position_code: 'pmc', factory_id: factoryId },
      })
      setPack(data)
    } catch (err: any) {
      setPack(null)
      setError(err?.response?.data?.detail || 'PMC 知识库加载失败，请稍后重试。')
    } finally {
      setLoading(false)
    }
  }, [factoryId])

  useEffect(() => { load() }, [load])

  const position = pack?.position
  const terms = Array.from(new Set([
    ...(pack?.terms || []).map((item: any) => item.term || item),
    ...(pack?.quiz?.questions || []).flatMap((question: any) => question.reference_terms || []),
  ])) as string[]

  return (
    <div style={{ padding: 24, maxWidth: 1280, margin: '0 auto' }}>
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        <Space align="center" wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/pmc')}>返回 PMC 工作台</Button>
          <Title level={3} style={{ margin: 0, color: NEURAL_COLORS.text }}>PMC 知识库</Title>
          <Tag color="cyan" style={{ background: NEURAL_COLORS.bgCard, border: `1px solid ${NEURAL_COLORS.border}`, color: NEURAL_COLORS.accent }}>神经蛛网 · RAG 检索式</Tag>
        </Space>

        {loading && <Card><Spin tip="加载 PMC 知识库" /></Card>}
        {!loading && error && <Alert type="error" showIcon message={error} action={<Button icon={<ReloadOutlined />} onClick={load}>重试</Button>} />}
        {!loading && !error && (
          <>
            <Card
              size="small"
              title={
                <Space>
                  <BookOutlined style={{ color: NEURAL_COLORS.accent }} />
                  <Text style={{ color: NEURAL_COLORS.text }}>PMC 知识图谱</Text>
                </Space>
              }
              extra={<Text style={{ color: NEURAL_COLORS.textDim }}>工厂：{pack?.factory_id || factoryId || '-'}</Text>}
              style={{ background: NEURAL_COLORS.bgCard, border: `1px solid ${NEURAL_COLORS.border}` }}
            >
              <Space direction="vertical" style={{ width: '100%' }} size={10}>
                <Space wrap align="center">
                  <Title level={4} style={{ margin: 0, color: NEURAL_COLORS.text }}>{position?.title || 'PMC 计划员'}</Title>
                  <Tag color="blue" style={{ background: NEURAL_COLORS.bg, border: `1px solid ${NEURAL_COLORS.border}`, color: NEURAL_COLORS.accentBlue }}>中心节点</Tag>
                </Space>
                <Paragraph style={{ margin: 0, color: NEURAL_COLORS.textDim }}>{position?.duties || '负责订单、物料、产能、交期和异常闭环。'}</Paragraph>
                <Text style={{ color: NEURAL_COLORS.textDim, fontSize: 12 }}>
                  悬停节点查看关系，点击技能节点或底部标签下钻该技能题目，中心节点重置视图。
                </Text>
                <PmcKnowledgeGraph pack={pack} onSelectSkill={setSelectedSkill} selectedSkill={selectedSkill} />
              </Space>
            </Card>

            {selectedSkill && (
              <SkillPanel pack={pack} skill={selectedSkill} onClose={() => setSelectedSkill(null)} />
            )}

            <Card
              size="small"
              title={<Text style={{ color: NEURAL_COLORS.text }}>知识术语索引</Text>}
              style={{ background: NEURAL_COLORS.bgCard, border: `1px solid ${NEURAL_COLORS.border}` }}
            >
              <Space wrap>{terms.map((term) => <Tag key={term} color="cyan" style={{ color: NEURAL_COLORS.text }}>{term}</Tag>)}</Space>
            </Card>

            <Card
              size="small"
              title={<Text style={{ color: NEURAL_COLORS.text }}>标准工作路径</Text>}
              style={{ background: NEURAL_COLORS.bgCard, border: `1px solid ${NEURAL_COLORS.border}` }}
            >
              <Space direction="vertical" style={{ width: '100%' }} size={10}>
                {(position?.daily_flow || []).map((item: any) => (
                  <div key={item.step} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                    <Tag color="blue" style={{ background: NEURAL_COLORS.bg, border: `1px solid ${NEURAL_COLORS.border}`, color: NEURAL_COLORS.accentBlue }}>{item.step}</Tag>
                    <div>
                      <Text strong style={{ color: NEURAL_COLORS.text }}>{item.task}</Text>
                      <div><Text style={{ color: NEURAL_COLORS.textDim }}>{item.detail}</Text></div>
                    </div>
                  </div>
                ))}
              </Space>
            </Card>

            <Card
              size="small"
              title={<Text style={{ color: NEURAL_COLORS.text }}>异常升级与关联工具</Text>}
              style={{ background: NEURAL_COLORS.bgCard, border: `1px solid ${NEURAL_COLORS.border}` }}
            >
              <Paragraph style={{ color: NEURAL_COLORS.textDim }}>{position?.escalation || '-'}</Paragraph>
              <Text style={{ color: NEURAL_COLORS.textDim }}>{position?.related_tools || '-'}</Text>
            </Card>

            <Card
              size="small"
              title={<Text style={{ color: NEURAL_COLORS.text }}>快速索引</Text>}
              style={{ background: NEURAL_COLORS.bgCard, border: `1px solid ${NEURAL_COLORS.border}` }}
            >
              <Collapse
                items={(pack?.quiz?.questions || []).map((question: any, index: number) => ({
                  key: question.id,
                  label: <Space><Tag color={question.difficulty >= 3 ? 'red' : question.difficulty === 2 ? 'gold' : 'blue'}>{question.skill}</Tag><Text style={{ color: NEURAL_COLORS.text }}>{index + 1}. {question.prompt}</Text></Space>,
                  children: <Text style={{ color: NEURAL_COLORS.textDim }}>参考术语：{(question.reference_terms || []).join('、') || '-'}</Text>,
                }))}
              />
            </Card>
          </>
        )}
      </Space>
    </div>
  )
}

export default PmcKnowledge