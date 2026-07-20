import React, { useEffect, useRef, useState } from 'react'
import { Card, Input, Button, Avatar, Tag, Space, Typography, Empty } from 'antd'
import { RobotOutlined, UserOutlined, SendOutlined, ClearOutlined } from '@ant-design/icons'
import { sendChat, getChatHealth, ChatMessage } from '../../services/modules'

const { TextArea } = Input
const { Text } = Typography

const SUGGESTIONS = [
  '当前有哪些在制工单？',
  '不良品率偏高怎么排查？',
  '仿真引擎如何评估高温加班合规性？',
  'MRP 计算需要哪些输入？',
]

const Assistant: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [health, setHealth] = useState<{ reachable: boolean; model: string } | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getChatHealth()
      .then((h) => setHealth({ reachable: h.reachable, model: h.model }))
      .catch(() => setHealth({ reachable: false, model: '-' }))
  }, [])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  const send = async (text: string) => {
    const content = text.trim()
    if (!content || loading) return
    const next: ChatMessage[] = [...messages, { role: 'user', content }]
    setMessages(next)
    setInput('')
    setLoading(true)
    try {
      const res = await sendChat(next)
      setMessages([...next, { role: 'assistant', content: res.reply }])
    } catch {
      setMessages([...next, { role: 'assistant', content: '⚠️ 请求失败，请稍后重试。' }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>AI 助手</h2>
        <Space>
          {health && (
            <Tag color={health.reachable ? 'success' : 'default'}>
              {health.reachable ? `在线 · ${health.model}` : '离线降级模式'}
            </Tag>
          )}
          <Button icon={<ClearOutlined />} onClick={() => setMessages([])} disabled={!messages.length}>
            清空
          </Button>
        </Space>
      </div>

      <Card
        styles={{ body: { padding: 0, display: 'flex', flexDirection: 'column', height: 'calc(100vh - 220px)' } }}
      >
        <div ref={listRef} style={{ flex: 1, overflowY: 'auto', padding: 24 }}>
          {messages.length === 0 && (
            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <Empty
                image={<RobotOutlined style={{ fontSize: 56, color: '#1890ff' }} />}
                description={<Text type="secondary">我是 EngHub MES 智能助手，试试下面的问题：</Text>}
              />
              <Space wrap style={{ justifyContent: 'center', marginTop: 16 }}>
                {SUGGESTIONS.map((s) => (
                  <Button key={s} size="small" onClick={() => send(s)}>
                    {s}
                  </Button>
                ))}
              </Space>
            </div>
          )}

          {messages.map((m, i) => (
            <div
              key={i}
              style={{
                display: 'flex',
                gap: 12,
                marginBottom: 20,
                flexDirection: m.role === 'user' ? 'row-reverse' : 'row',
              }}
            >
              <Avatar
                icon={m.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                style={{ background: m.role === 'user' ? '#52c41a' : '#1890ff', flexShrink: 0 }}
              />
              <div
                style={{
                  maxWidth: '72%',
                  padding: '10px 14px',
                  borderRadius: 8,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  background: m.role === 'user' ? '#e6f7ff' : '#f5f5f5',
                  border: '1px solid #f0f0f0',
                }}
              >
                {m.content}
              </div>
            </div>
          ))}

          {loading && (
            <div style={{ display: 'flex', gap: 12 }}>
              <Avatar icon={<RobotOutlined />} style={{ background: '#1890ff' }} />
              <div style={{ padding: '10px 14px', borderRadius: 8, background: '#f5f5f5', color: '#999' }}>
                正在思考…
              </div>
            </div>
          )}
        </div>

        <div style={{ borderTop: '1px solid #f0f0f0', padding: 16, display: 'flex', gap: 12 }}>
          <TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入问题，Enter 发送，Shift+Enter 换行"
            autoSize={{ minRows: 1, maxRows: 4 }}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault()
                send(input)
              }
            }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={loading}
            onClick={() => send(input)}
            style={{ height: 'auto' }}
          >
            发送
          </Button>
        </div>
      </Card>
    </div>
  )
}

export default Assistant
