/**
 * TMS 分发看板 - Task Distribution Dashboard
 * 
 * 可视化任务分发状态、候选人评分、分发策略使用统计
 */
import React, { useState, useEffect } from 'react';
import {
  Card,
  Row,
  Col,
  Table,
  Tag,
  Button,
  Space,
  Select,
  Statistic,
  Progress,
  Typography,
  Modal,
  Form,
  Input,
  message,
  Descriptions,
  List,
  Badge,
} from 'antd';
import {
  ThunderboltOutlined,
  TeamOutlined,
  AimOutlined,
  BarChartOutlined,
  ReloadOutlined,
  RobotOutlined,
  UserOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import tmsApi, { TMSTask, DistributionStats } from '../../services/tms';

const { Title, Text } = Typography;
const { Option } = Select;

// 状态配置
const statusConfig: Record<string, { label: string; color: string }> = {
  pending_distribution: { label: '待分发', color: 'default' },
  distributed: { label: '已分发', color: 'blue' },
  claimed: { label: '已认领', color: 'cyan' },
  in_progress: { label: '进行中', color: 'processing' },
  pending_approval: { label: '待审批', color: 'warning' },
  completed: { label: '已完成', color: 'success' },
  rejected: { label: '已驳回', color: 'error' },
};

// 策略配置
const strategyConfig: Record<string, { label: string; description: string }> = {
  skill_match: { label: '技能匹配', description: '基于员工技能等级匹配' },
  load_balance: { label: '负载均衡', description: '优先分配给负载最低的员工' },
  round_robin: { label: '轮询分配', description: '按顺序轮流分配' },
  priority_queue: { label: '优先级队列', description: '高优先级任务分配给高技能人员' },
  agent_decide: { label: 'Agent 决策', description: '由 AI Agent 智能决定' },
  manual: { label: '手动分配', description: '手动指定分配对象' },
};

const TaskDistribution: React.FC = () => {
  const [tasks, setTasks] = useState<TMSTask[]>([]);
  const [stats, setStats] = useState<DistributionStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [distributeModalVisible, setDistributeModalVisible] = useState(false);
  const [selectedTask, setSelectedTask] = useState<TMSTask | null>(null);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [form] = Form.useForm();

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [tasksRes, statsRes] = await Promise.all([
        tmsApi.listTasks({ page_size: 50 }).catch(() => ({ data: { items: [] } })),
        tmsApi.getDistributionStats().catch(() => ({ data: null })),
      ]);
      if (tasksRes.data?.items) setTasks(tasksRes.data.items);
      if (statsRes.data) setStats(statsRes.data);
    } catch (error) {
      console.error('Failed to load data:', error);
    } finally {
      setLoading(false);
    }
  };

  // 打开分发弹窗
  const openDistributeModal = async (task: TMSTask) => {
    setSelectedTask(task);
    setDistributeModalVisible(true);
    
    // 获取 AI 推荐
    try {
      const result = await tmsApi.agentCommand({
        agent_id: 'distribution-dashboard',
        command: 'get_recommendation',
        params: { task_id: task.id },
      });
      setRecommendations(result.data?.data?.recommendations || []);
    } catch (error) {
      setRecommendations([]);
    }
  };

  // 执行分发
  const handleDistribute = async (values: any) => {
    if (!selectedTask) return;
    
    try {
      const result = await tmsApi.distributeTask(selectedTask.id, {
        strategy: values.strategy,
        mode: values.mode,
        target_user_id: values.target_user_id,
      });
      
      if (result.data?.success) {
        message.success(result.data.message || '分发成功');
        setDistributeModalVisible(false);
        loadData();
      } else {
        message.error(result.data?.message || '分发失败');
      }
    } catch (error) {
      message.error('分发失败');
    }
  };

  // 表格列定义
  const columns: ColumnsType<TMSTask> = [
    {
      title: '任务编号',
      dataIndex: 'task_code',
      key: 'task_code',
      width: 150,
      render: (code: string) => <Text code>{code}</Text>,
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
    },
    {
      title: '类型',
      dataIndex: 'task_type',
      key: 'task_type',
      width: 100,
      render: (type: string) => <Tag>{type}</Tag>,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (priority: string) => (
        <Tag color={priority === 'urgent' ? 'red' : priority === 'high' ? 'orange' : 'blue'}>
          {priority}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const config = statusConfig[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      },
    },
    {
      title: '分发策略',
      dataIndex: 'distribution_strategy',
      key: 'distribution_strategy',
      width: 100,
      render: (strategy: string) =>
        strategy ? (
          <Tag icon={<AimOutlined />}>{strategyConfig[strategy]?.label || strategy}</Tag>
        ) : (
          <Text type="secondary">未设置</Text>
        ),
    },
    {
      title: '候选人数',
      key: 'candidates',
      width: 80,
      render: (_, record) => (
        <Badge count={record.candidate_pool?.length || 0} showZero color="#1890ff" />
      ),
    },
    {
      title: '积分',
      dataIndex: 'points',
      key: 'points',
      width: 70,
      render: (points: number) => (
        <Text strong style={{ color: points > 0 ? '#faad14' : undefined }}>
          +{points}
        </Text>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_, record) => (
        <Space>
          {record.status === 'pending_distribution' && (
            <Button
              type="primary"
              size="small"
              icon={<ThunderboltOutlined />}
              onClick={() => openDistributeModal(record)}
            >
              分发
            </Button>
          )}
          <Button
            size="small"
            icon={<RobotOutlined />}
            onClick={() => handleAiRecommend(record)}
          >
            AI
          </Button>
        </Space>
      ),
    },
  ];

  const handleAiRecommend = async (task: TMSTask) => {
    try {
      const result = await tmsApi.agentCommand({
        agent_id: 'distribution-dashboard',
        command: 'get_recommendation',
        params: { task_id: task.id },
      });
      const recs = result.data?.data?.recommendations || [];
      Modal.info({
        title: `AI 分发建议 - ${task.task_code}`,
        width: 550,
        content: (
          <List
            size="small"
            dataSource={recs}
            renderItem={(item: any, index: number) => (
              <List.Item>
                <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Space>
                    <Tag color={index === 0 ? 'gold' : 'default'}>#{index + 1}</Tag>
                    <UserOutlined />
                    <Text strong>{item.full_name}</Text>
                  </Space>
                  <Space>
                    <Progress
                      percent={Math.round(item.score * 100)}
                      size="small"
                      style={{ width: 120 }}
                    />
                    <Text type="secondary">{item.reasons?.join(', ')}</Text>
                  </Space>
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
            <ThunderboltOutlined style={{ color: '#722ed1', marginRight: 8 }} />
            任务分发看板
          </Title>
          <Text type="secondary">智能分发引擎 - 技能匹配 / 负载均衡 / Agent 决策</Text>
        </Col>
        <Col>
          <Button icon={<ReloadOutlined />} onClick={loadData}>
            刷新
          </Button>
        </Col>
      </Row>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="总分发次数"
              value={stats?.total_distributions || 0}
              prefix={<ThunderboltOutlined style={{ color: '#722ed1' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="待分发任务"
              value={stats?.status_distribution?.pending_distribution || 0}
              prefix={<TeamOutlined style={{ color: '#faad14' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="进行中"
              value={(stats?.status_distribution?.in_progress || 0) + (stats?.status_distribution?.claimed || 0)}
              prefix={<BarChartOutlined style={{ color: '#1890ff' }} />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="已完成"
              value={stats?.status_distribution?.completed || 0}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 策略使用统计 */}
      {stats?.strategy_usage && Object.keys(stats.strategy_usage).length > 0 && (
        <Card title="分发策略使用统计" style={{ marginBottom: 24 }} size="small">
          <Row gutter={16}>
            {Object.entries(stats.strategy_usage).map(([strategy, count]) => (
              <Col span={4} key={strategy}>
                <Statistic
                  title={strategyConfig[strategy]?.label || strategy}
                  value={count}
                  suffix="次"
                />
              </Col>
            ))}
          </Row>
        </Card>
      )}

      {/* 任务列表 */}
      <Card title="任务列表">
        <Table
          columns={columns}
          dataSource={tasks}
          rowKey="id"
          loading={loading}
          pagination={{ pageSize: 10 }}
          scroll={{ x: 1000 }}
        />
      </Card>

      {/* 分发弹窗 */}
      <Modal
        title={`分发任务 - ${selectedTask?.task_code}`}
        open={distributeModalVisible}
        onCancel={() => setDistributeModalVisible(false)}
        footer={null}
        width={600}
      >
        {selectedTask && (
          <>
            <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="标题">{selectedTask.title}</Descriptions.Item>
              <Descriptions.Item label="优先级">
                <Tag color={selectedTask.priority === 'urgent' ? 'red' : 'blue'}>
                  {selectedTask.priority}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="所需技能">
                {selectedTask.required_skills?.join(', ') || '无'}
              </Descriptions.Item>
              <Descriptions.Item label="积分">+{selectedTask.points}</Descriptions.Item>
            </Descriptions>

            {/* AI 推荐 */}
            {recommendations.length > 0 && (
              <Card title="AI 推荐候选人" size="small" style={{ marginBottom: 16 }}>
                <List
                  size="small"
                  dataSource={recommendations.slice(0, 3)}
                  renderItem={(item: any, index) => (
                    <List.Item>
                      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                        <Space>
                          <Tag color={index === 0 ? 'gold' : 'default'}>推荐 #{index + 1}</Tag>
                          <Text>{item.full_name}</Text>
                        </Space>
                        <Progress percent={Math.round(item.score * 100)} size="small" style={{ width: 100 }} />
                      </Space>
                    </List.Item>
                  )}
                />
              </Card>
            )}

            <Form form={form} layout="vertical" onFinish={handleDistribute}>
              <Form.Item
                name="strategy"
                label="分发策略"
                rules={[{ required: true, message: '请选择分发策略' }]}
                initialValue="skill_match"
              >
                <Select>
                  {Object.entries(strategyConfig).map(([key, config]) => (
                    <Option key={key} value={key}>
                      {config.label} - {config.description}
                    </Option>
                  ))}
                </Select>
              </Form.Item>

              <Form.Item
                name="mode"
                label="分发模式"
                initialValue="direct"
              >
                <Select>
                  <Option value="direct">直接分配 - 引擎直接指定执行人</Option>
                  <Option value="pool">候选池抢单 - 推送给多个候选人</Option>
                  <Option value="agent">Agent 决策 - 由 AI Agent 决定</Option>
                </Select>
              </Form.Item>

              <Form.Item
                name="target_user_id"
                label="指定分配对象（可选）"
              >
                <Input placeholder="留空则按策略自动分配" />
              </Form.Item>

              <Form.Item>
                <Space>
                  <Button type="primary" htmlType="submit" icon={<ThunderboltOutlined />}>
                    执行分发
                  </Button>
                  <Button onClick={() => setDistributeModalVisible(false)}>
                    取消
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </>
        )}
      </Modal>
    </div>
  );
};

export default TaskDistribution;
