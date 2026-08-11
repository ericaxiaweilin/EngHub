import React, { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Collapse, List, Space, Spin, Tag, Typography } from 'antd'
import { ArrowLeftOutlined, BookOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import api from '../../services/api'
import { getActiveFactoryId } from '../../utils/factory'

const { Text, Title, Paragraph } = Typography

/** PMC 旧版知识库入口。内容复用训练包接口，避免菜单恢复后再次落到空页面。 */
const PmcKnowledge: React.FC = () => {
  const navigate = useNavigate()
  const factoryId = getActiveFactoryId()
  const [pack, setPack] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

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
    <div style={{ padding: 24, maxWidth: 1180, margin: '0 auto' }}>
      <Space direction="vertical" style={{ width: '100%' }} size={16}>
        <Space align="center" wrap>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/pmc')}>返回 PMC 工作台</Button>
          <Title level={3} style={{ margin: 0 }}>PMC 知识库</Title>
          <Tag color="blue">接口驱动</Tag>
        </Space>

        {loading && <Card><Spin tip="加载 PMC 知识库" /></Card>}
        {!loading && error && <Alert type="error" showIcon message={error} action={<Button icon={<ReloadOutlined />} onClick={load}>重试</Button>} />}
        {!loading && !error && (
          <>
            <Card size="small" title={<Space><BookOutlined style={{ color: '#1677ff' }} />PMC 岗位判断框架</Space>} extra={<Text type="secondary">工厂：{pack?.factory_id || factoryId || '-'}</Text>}>
              <Space direction="vertical" style={{ width: '100%' }} size={10}>
                <Title level={4} style={{ margin: 0 }}>{position?.title || 'PMC 计划员'}</Title>
                <Paragraph style={{ margin: 0 }}>{position?.duties || '负责订单、物料、产能、交期和异常闭环。'}</Paragraph>
                <Space wrap>{terms.map((term) => <Tag key={term} color="cyan">{term}</Tag>)}</Space>
              </Space>
            </Card>

            <Card size="small" title="标准工作路径">
              <List
                dataSource={position?.daily_flow || []}
                locale={{ emptyText: '暂无标准工作路径' }}
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

            <Card size="small" title="异常升级与关联工具">
              <Paragraph>{position?.escalation || '-'}</Paragraph>
              <Text type="secondary">{position?.related_tools || '-'}</Text>
            </Card>

            <Card size="small" title="快速索引">
              <Collapse
                items={(pack?.quiz?.questions || []).map((question: any, index: number) => ({
                  key: question.id,
                  label: <Space><Tag color={question.difficulty >= 3 ? 'red' : question.difficulty === 2 ? 'gold' : 'blue'}>{question.skill}</Tag><Text>{index + 1}. {question.prompt}</Text></Space>,
                  children: <Text type="secondary">参考术语：{(question.reference_terms || []).join('、') || '-'}</Text>,
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
