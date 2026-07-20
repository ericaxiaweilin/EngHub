/**
 * TMS 审批中心 - Approval Center
 * 
 * 基于 EngFlow TMS 设计，增强为：
 * - 状态卡片：候选中 / 进行中 / 已完成 / 本周积分 + SLA 达标率
 * - 任务卡片：AI 推荐分发、一键审批、Agent 建议
 * - 右侧 AI 面板：风险预警 + 任务撮合 + Agent 实时对话
 * - 底部 Chat 输入框：命令式交互
 */
import React, { useState, useEffect } from 'react';
import {
  Card,
  Row,
  Col,
  Statistic,
  Tag,
  Button,
  Tabs,
  List,
  Space,
  Input,
  Badge,
  Typography,
  Alert,
  Timeline,
  Progress,
  Tooltip,
  message,
  Modal,
  Drawer,
} from 'antd';
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  SyncOutlined,
  TrophyOutlined,
  RobotOutlined,
  SendOutlined,
  PlusOutlined,
  ExclamationCircleOutlined,
  BulbOutlined,
  TeamOutlined,
  SafetyOutlined,
} from '@ant-design/icons';
import tmsApi, { TMSTask, DashboardStats, PendingApproval } from '../../services/tms';

const { Title, Text, Paragraph } = Typography;
const { TabPane } = Tabs;

// 优先级颜色映射
const priorityColors: Record<string, string> = {
  low: 'default',
  medium: 'blue',
  high: 'orange',
  urgent: 'red',
};

// 任务类型标签
const taskTypeLabels: Record<string, { label: string; color: string }> = {
  ecn_release: { label: 'ECN 发布', color: 'purple' },
  ecr_approval: { label: 'ECR 审批', color: 'geekblue' },
  inspection: { label: '检验任务', color: 'cyan' },
  custom: { label: '自定义', color: 'default' },
};

const ApprovalCenter: React.FC = () => {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [tasks, setTasks] = useState<TMSTask[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<PendingApproval[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('recommended');
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState<Array<{ role: 'user' | 'ai'; content: string }>>([]);
  const [aiDrawerVisible, setAiDrawerVisible] = useState(false);

  // 模拟用户 ID（生产环境从 auth context 获取）
  const currentUserId = 'current-user-id';

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      // 并行加载数据
      const [statsRes, tasksRes, approvalsRes] = await Promise.all([
        tmsApi.getDashboardStats().catch(() => ({ data: null })),
        tmsApi.getRecommendedTasks(currentUserId, 10).catch(() => ({ data: { items: [] } })),
        tmsApi.getPendingApprovals(currentUserId).catch(() => ({ data: { items: [] } })),
      ]);

      if (statsRes.data) setStats(statsRes.data);
      if (tasksRes.data?.items) setTasks(tasksRes.data.items);
      if (approvalsRes.data?.items) setPendingApprovals(approvalsRes.data.items);
    } catch (error) {
      console.error('Failed to load data:', error);
    } finally {
      setLoading(false);
    }
  };

  // 处理审批操作
  const handleApprove = async (flowId: string) => {
    try {
      await tmsApi.approveTask(flowId, { approver_id: currentUserId, comment: '审批通过' });
      message.success('审批通过');
      loadData();
    } catch (error) {
      message.error('审批失败');
    }
  };

  const handleReject = async (flowId: string) => {
    Modal.confirm({
      title: '确认驳回',
      icon: <ExclamationCircleOutlined />,
      content: '确定要驳回此审批吗？',
      onOk: async () => {
        try {
          await tmsApi.rejectTask(flowId, { approver_id: currentUserId, comment: '驳回' });
          message.success('已驳回');
          loadData();
        } catch (error) {
          message.error('操作失败');
        }
      },
    });
  };

  // 处理 Chat 命令
  const handleChatSend = async () => {
    if (!chatInput.trim()) return;

    const userMessage = chatInput.trim();
    setChatHistory(prev => [...prev, { role: 'user', content: userMessage }]);
    setChatInput('');

    // 解析命令
    let response = '';
    try {
      if (userMessage.startsWith('/')) {
        const [cmd, ...args] = userMessage.slice(1).split(' ');
        const result = await tmsApi.agentCommand({
          agent_id: 'web-chat',
          command: cmd,
          params: { query: args.join(' ') },
        });
        response = result.data?.message || '命令已执行';
      } else {
        // 普通对话 - 调用 AI 建议
        response = `收到: "${userMessage}"。我可以帮你：\n- /query_tasks 查询任务\n- /get_recommendation 获取分发建议\n- /assign_task 分配任务`;
      }
    } catch (error) {
      response = '命令执行失败，请检查格式';
    }

    setChatHistory(prev => [...prev, { role: 'ai', content: response }]);
  };

  // 任务卡片组件
  const TaskCard: React.FC<{ task: TMSTask }> = ({ task }) => {
    const typeInfo = taskTypeLabels[task.task_type] || taskTypeLabels.custom;
    return (
      <Card
        hoverable
        size="small"
        style={{ marginBottom: 12 }}
        actions={[
          <Tooltip title="AI 推荐分发" key="ai">
            <Button
              type="text"
              icon={<RobotOutlined />}
              onClick={() => handleAiRecommend(task)}
            />
          </Tooltip>,
          <Tooltip title="去审批" key="approve">
            <Button
              type="primary"
              size="small"
              onClick={() => task.approval_flow_id && handleApprove(task.approval_flow_id)}
            >
              去审批
            </Button>
          </Tooltip>,
        ]}
      >
        <Space direction="vertical" style={{ width: '100%' }} size={4}>
          <Space>
            <Tag color={typeInfo.color}>{typeInfo.label}</Tag>
            <Tag color={priorityColors[task.priority]}>{task.priority.toUpperCase()}</Tag>
            {task.points > 0 && (
              <Tag icon={<TrophyOutlined />} color="gold">+{task.points} 积分</Tag>
            )}
          </Space>
          <Text strong>{task.task_code}</Text>
          <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0, fontSize: 12 }}>
            {task.title}
          </Paragraph>
          {task.ai_recommendation && (
            <Alert
              message={task.ai_recommendation}
              type="info"
              showIcon
              icon={<BulbOutlined />}
              style={{ padding: '4px 8px', fontSize: 11 }}
            />
          )}
          <Space size={4}>
            {task.required_skills?.slice(0, 3).map(skill => (
              <Tag key={skill} style={{ fontSize: 10 }}>{skill}</Tag>
            ))}
          </Space>
        </Space>
      </Card>
    );
  };

  const handleAiRecommend = async (task: TMSTask) => {
    try {
      const result = await tmsApi.agentCommand({
        agent_id: 'web-ui',
        command: 'get_recommendation',
        params: { task_id: task.id },
      });
      const recommendations = result.data?.data?.recommendations || [];
      Modal.info({
        title: `AI 分发建议 - ${task.task_code}`,
        width: 500,
        content: (
          <List
            size="small"
            dataSource={recommendations}
            renderItem={(item: any) => (
              <List.Item>
                <Space>
                  <TeamOutlined />
                  <Text>{item.full_name}</Text>
                  <Progress percent={item.score * 100} size="small" style={{ width: 100 }} />
                  <Text type="secondary">{item.reasons?.join(', ')}</Text>
                </Space>
              </List.Item>
            )}
          />
        ),
      });
    } catch (error) {
      message.error('获取 AI 建议失败');
    }
  };

  return (
    <div style={{ padding: 24 }}>
      {/* 页面标题 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Title level={3} style={{ marginBottom: 0 }}>
            审批队列
          </Title>
          <Text type="secondary">实时任务流与工业级智能协同</Text>
        </Col>
        <Col>
          <Space>
            <Button icon={<RobotOutlined />} onClick={() => setAiDrawerVisible(true)}>
              AI 助手
            </Button>
            <Button type="primary" icon={<PlusOutlined />}>
              发布任务
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 状态卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={4}>
          <Card>
            <Statistic
              title="候选中"
              value={stats?.pending_distribution || 0}
              prefix={<ClockCircleOutlined style={{ color: '#faad14' }} />}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="进行中"
              value={(stats?.in_progress || 0) + (stats?.claimed || 0)}
              prefix={<SyncOutlined spin style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="已完成"
              value={stats?.completed || 0}
              prefix={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="本周积分"
              value={stats?.weekly_points || 0}
              prefix={<TrophyOutlined style={{ color: '#faad14' }} />}
              suffix="pts"
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="SLA 达标率"
              value={stats?.sla_rate || 100}
              suffix="%"
              valueStyle={{ color: (stats?.sla_rate || 100) >= 90 ? '#52c41a' : '#f5222d' }}
              prefix={<SafetyOutlined />}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card>
            <Statistic
              title="待审批"
              value={stats?.pending_approval || 0}
              prefix={<Badge count={pendingApprovals.length} size="small" />}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={24}>
        {/* 左侧：任务列表 */}
        <Col span={16}>
          <Card>
            <Tabs activeKey={activeTab} onChange={setActiveTab}>
              <TabPane tab="推荐任务" key="recommended">
                <List
                  loading={loading}
                  grid={{ gutter: 16, column: 2 }}
                  dataSource={tasks}
                  renderItem={(task) => (
                    <List.Item>
                      <TaskCard task={task} />
                    </List.Item>
                  )}
                  locale={{ emptyText: '暂无推荐任务' }}
                />
              </TabPane>
              <TabPane tab="待审批" key="pending">
                <List
                  loading={loading}
                  dataSource={pendingApprovals}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        <Button type="primary" size="small" onClick={() => handleApprove(item.flow_id)}>
                          通过
                        </Button>,
                        <Button danger size="small" onClick={() => handleReject(item.flow_id)}>
                          驳回
                        </Button>,
                      ]}
                    >
                      <List.Item.Meta
                        title={
                          <Space>
                            <Text>{item.task_code}</Text>
                            <Tag color={priorityColors[item.priority]}>{item.priority}</Tag>
                          </Space>
                        }
                        description={
                          <>
                            <div>{item.task_title}</div>
                            <Text type="secondary">
                              当前步骤: {item.step_name} | 发起人: {item.initiated_by}
                            </Text>
                          </>
                        }
                      />
                    </List.Item>
                  )}
                  locale={{ emptyText: '暂无待审批任务' }}
                />
              </TabPane>
              <TabPane tab="高积分优先" key="high_points">
                <List
                  loading={loading}
                  grid={{ gutter: 16, column: 2 }}
                  dataSource={[...tasks].sort((a, b) => b.points - a.points)}
                  renderItem={(task) => (
                    <List.Item>
                      <TaskCard task={task} />
                    </List.Item>
                  )}
                />
              </TabPane>
            </Tabs>
          </Card>
        </Col>

        {/* 右侧：AI 面板 */}
        <Col span={8}>
          {/* AI 智能分析 */}
          <Card
            title={
              <Space>
                <RobotOutlined style={{ color: '#722ed1' }} />
                <span>AI 智能分析</span>
                <Tag color="purple">NEURAL CO-PILOT v4</Tag>
              </Space>
            }
            style={{ marginBottom: 16 }}
          >
            <Space direction="vertical" style={{ width: '100%' }} size={12}>
              <Alert
                message="风险预警"
                description="检测到零件 PN-1189 存在版本兼容风险，建议由 EE 介入分析。"
                type="warning"
                showIcon
              />
              <Alert
                message="任务撮合"
                description="根据您的技能匹配，'信号完整性评估'任务获准概率为 98%。"
                type="info"
                showIcon
                icon={<BulbOutlined />}
              />
              <Button type="primary" block icon={<RobotOutlined />}>
                询问 AI 任务建议
              </Button>
            </Space>
          </Card>

          {/* 最近动态 */}
          <Card title="最近动态" size="small">
            <Timeline
              items={[
                {
                  color: 'green',
                  children: (
                    <>
                      <Text>张伟 提交了 PCB 仿真报告</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 11 }}>10 分钟前</Text>
                    </>
                  ),
                },
                {
                  color: 'blue',
                  children: (
                    <>
                      <Text>系统 发布了 紧急采购单 #098</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 11 }}>45 分钟前</Text>
                    </>
                  ),
                },
                {
                  color: 'gray',
                  children: (
                    <>
                      <Text>李工 完成了 结构力学分析</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 11 }}>2 小时前</Text>
                    </>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>

      {/* 底部 Chat 输入框 */}
      <Card
        size="small"
        style={{
          position: 'fixed',
          bottom: 0,
          left: 200,
          right: 0,
          borderRadius: 0,
          boxShadow: '0 -2px 8px rgba(0,0,0,0.1)',
        }}
      >
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="Ask anything... (支持 /query_tasks, /assign_task 等命令)"
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onPressEnter={handleChatSend}
            prefix={<RobotOutlined style={{ color: '#722ed1' }} />}
          />
          <Button type="primary" icon={<SendOutlined />} onClick={handleChatSend}>
            Chat
          </Button>
        </Space.Compact>
        {chatHistory.length > 0 && (
          <div style={{ maxHeight: 150, overflow: 'auto', marginTop: 8 }}>
            {chatHistory.map((msg, idx) => (
              <div
                key={idx}
                style={{
                  textAlign: msg.role === 'user' ? 'right' : 'left',
                  marginBottom: 8,
                }}
              >
                <Tag color={msg.role === 'user' ? 'blue' : 'purple'}>
                  {msg.role === 'user' ? 'You' : 'AI'}
                </Tag>
                <Text style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</Text>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* AI 助手抽屉 */}
      <Drawer
        title="AI 任务助手"
        placement="right"
        width={400}
        open={aiDrawerVisible}
        onClose={() => setAiDrawerVisible(false)}
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Alert
            message="可用命令"
            description={
              <ul style={{ paddingLeft: 16, margin: 0 }}>
                <li>/query_tasks - 查询任务列表</li>
                <li>/get_recommendation - 获取 AI 分发建议</li>
                <li>/assign_task - 分配任务</li>
                <li>/approve_task - 代审批（需确认）</li>
                <li>/escalate_task - 升级审批</li>
              </ul>
            }
            type="info"
          />
          <Text type="secondary">
            提示：高危操作（审批、批量分发）需要人工确认后才会执行。
          </Text>
        </Space>
      </Drawer>
    </div>
  );
};

export default ApprovalCenter;
