/**
 * MES 生产专家系统 - 聊天界面
 */
import React, { useState, useRef, useEffect } from 'react';
import { Card, Input, Button, message, Spin, Tag, Typography, Space, Divider, Alert } from 'antd';
import { SendOutlined, RobotOutlined, UserOutlined, ReloadOutlined } from '@ant-design/icons';

const { TextArea } = Input;
const { Title, Text } = Typography;

interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  confidence?: number;
  sources?: string[];
  suggested_actions?: string[];
}

interface ChatContext {
  station_id?: string;
  work_order_id?: string;
  user_role?: string;
}

const ExpertChat: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [context] = useState<ChatContext>({
    user_role: 'production_manager',
  });
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async () => {
    if (!inputValue.trim()) {
      message.warning('请输入问题');
      return;
    }

    const userMessage: Message = {
      role: 'user',
      content: inputValue.trim(),
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setLoading(true);

    try {
      const response = await fetch('/api/v1/expert/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: userMessage.content,
          context,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      const assistantMessage: Message = {
        role: 'assistant',
        content: data.answer || '抱歉，我暂时无法回答这个问题。',
        timestamp: new Date(),
        confidence: data.confidence,
        sources: data.sources,
        suggested_actions: data.suggested_actions,
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      console.error('Chat error:', error);
      message.error('连接专家系统失败，请稍后重试');
      
      const errorMessage: Message = {
        role: 'assistant',
        content: '系统错误：无法连接到专家服务。请确认后端服务已启动。',
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const clearChat = () => {
    setMessages([]);
    message.info('对话已清空');
  };

  const getConfidenceColor = (confidence?: number) => {
    if (!confidence) return 'default';
    if (confidence >= 0.8) return 'success';
    if (confidence >= 0.6) return 'blue';
    if (confidence >= 0.4) return 'warning';
    return 'red';
  };

  const quickQuestions = [
    'SMT-01 工位的 OEE 是多少？',
    '今天的质量指标如何？',
    '有哪些缺料风险？',
    'WO-2025-0115-001 工单进度如何？',
  ];

  return (
    <div style={{ maxWidth: 900, margin: '0 auto', padding: '24px' }}>
      <Card
        title={
          <Space>
            <RobotOutlined style={{ fontSize: 24, color: '#1890ff' }} />
            <Title level={3} style={{ margin: 0 }}>MES 生产专家系统</Title>
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={clearChat}>
            清空对话
          </Button>
        }
        style={{ borderRadius: 8 }}
      >
        {/* 快捷问题 */}
        {messages.length === 0 && (
          <Alert
            message="我可以帮您解答以下问题"
            description={
              <Space direction="vertical" style={{ width: '100%' }}>
                {quickQuestions.map((q, idx) => (
                  <Tag
                    key={idx}
                    color="blue"
                    style={{ cursor: 'pointer', margin: '4px' }}
                    onClick={() => setInputValue(q)}
                  >
                    {q}
                  </Tag>
                ))}
              </Space>
            }
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}

        {/* 消息列表 */}
        <div
          style={{
            maxHeight: '60vh',
            overflowY: 'auto',
            padding: '16px',
            backgroundColor: '#f5f5f5',
            borderRadius: 8,
            marginBottom: 16,
          }}
        >
          {messages.length === 0 ? (
            <div style={{ textAlign: 'center', color: '#999', padding: '40px' }}>
              <RobotOutlined style={{ fontSize: 48, marginBottom: 16 }} />
              <div>您好！我是 MES 生产专家助手</div>
              <div style={{ fontSize: 12, marginTop: 8 }}>
                可以为您解答生产、质量、设备、库存等相关问题
              </div>
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  marginBottom: 16,
                }}
              >
                <div
                  style={{
                    maxWidth: '75%',
                    padding: '12px 16px',
                    borderRadius: 12,
                    backgroundColor: msg.role === 'user' ? '#1890ff' : '#ffffff',
                    color: msg.role === 'user' ? '#ffffff' : '#333333',
                    boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
                  }}
                >
                  <Space style={{ marginBottom: 8 }}>
                    {msg.role === 'user' ? (
                      <UserOutlined />
                    ) : (
                      <RobotOutlined style={{ color: '#1890ff' }} />
                    )}
                    <Text strong={msg.role === 'user'}>
                      {msg.role === 'user' ? '您' : '专家助手'}
                    </Text>
                    <Text style={{ fontSize: 12, color: '#999' }}>
                      {msg.timestamp.toLocaleTimeString()}
                    </Text>
                  </Space>

                  <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                    {msg.content}
                  </div>

                  {/* 置信度 */}
                  {msg.confidence !== undefined && msg.role === 'assistant' && (
                    <div style={{ marginTop: 8 }}>
                      <Tag color={getConfidenceColor(msg.confidence)}>
                        置信度：{(msg.confidence * 100).toFixed(0)}%
                      </Tag>
                    </div>
                  )}

                  {/* 知识来源 */}
                  {msg.sources && msg.sources.length > 0 && msg.role === 'assistant' && (
                    <div style={{ marginTop: 8 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        来源:
                      </Text>
                      <div style={{ marginTop: 4 }}>
                        {msg.sources.map((source, sIdx) => (
                          <Tag key={sIdx} color="green" style={{ fontSize: 11 }}>
                            {source.split('/').pop()}
                          </Tag>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* 建议行动 */}
                  {msg.suggested_actions && msg.suggested_actions.length > 0 && msg.role === 'assistant' && (
                    <div style={{ marginTop: 12 }}>
                      <Divider style={{ margin: '8px 0' }} />
                      <Text strong>💡 建议行动:</Text>
                      <ul style={{ margin: '8px 0', paddingLeft: 20 }}>
                        {msg.suggested_actions.map((action, aIdx) => (
                          <li key={aIdx} style={{ marginBottom: 4 }}>
                            {action}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            ))
          )}

          {loading && (
            <div style={{ textAlign: 'center', padding: 20 }}>
              <Spin tip="专家正在分析..." />
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* 输入区域 */}
        <div style={{ display: 'flex', gap: 8 }}>
          <TextArea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="请输入您的生产相关问题... (Shift+Enter 换行)"
            rows={3}
            disabled={loading}
            style={{ flex: 1, resize: 'none' }}
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            onClick={sendMessage}
            loading={loading}
            size="large"
            style={{ minWidth: 100 }}
          >
            发送
          </Button>
        </div>

        {/* 上下文设置 */}
        <Divider orientation="left">当前上下文</Divider>
        <Space size="middle">
          <div>
            <Text type="secondary">角色:</Text>
            <Tag color="purple">{context.user_role}</Tag>
          </div>
          {context.station_id && (
            <div>
              <Text type="secondary">工位:</Text>
              <Tag color="blue">{context.station_id}</Tag>
            </div>
          )}
          {context.work_order_id && (
            <div>
              <Text type="secondary">工单:</Text>
              <Tag color="orange">{context.work_order_id}</Tag>
            </div>
          )}
        </Space>
      </Card>
    </div>
  );
};

export default ExpertChat;
