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
  Badge,
  Typography,
  Timeline,
  Tooltip,
  message,
  Modal,
  Alert,
} from 'antd';
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  SyncOutlined,
  TrophyOutlined,
  PlusOutlined,
  ExclamationCircleOutlined,
  SafetyOutlined,
  BulbOutlined,
} from '@ant-design/icons';
import tmsApi, { TMSTask, DashboardStats, PendingApproval } from '../../services/tms';
import api from '../../services/api';

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

  // 从 auth 获取真实用户 ID
  const [currentUserId, setCurrentUserId] = useState<string>('');

  useEffect(() => {
    // 获取当前用户信息
    api.get('/api/v1/auth/me').then((res: any) => {
      if (res?.id) setCurrentUserId(res.id);
    }).catch(() => {});
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

  // 任务卡片组件
  const TaskCard: React.FC<{ task: TMSTask }> = ({ task }) => {
    const typeInfo = taskTypeLabels[task.task_type] || taskTypeLabels.custom;
    return (
      <Card
        hoverable
        size="small"
        style={{ marginBottom: 12 }}
        actions={[
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
          <Button type="primary" icon={<PlusOutlined />}>
            发布任务
          </Button>
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

        {/* 右侧：最近动态 */}
        <Col span={8}>
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
    </div>
  );
};

export default ApprovalCenter;
