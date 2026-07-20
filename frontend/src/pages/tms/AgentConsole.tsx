/**
 * TMS Agent 控制台 - Agent Console
 * 
 * Agent/Chatbot 调试与监控界面：
 * - 命令执行测试
 * - 操作日志查看
 * - Webhook 订阅管理
 * - 权限配置
 */
import React, { useState } from 'react';
import {
  Card,
  Row,
  Col,
  Form,
  Input,
  Select,
  Button,
  Space,
  Typography,
  Tag,
  Table,
  Tabs,
  Alert,
  Descriptions,
  message,
  Switch,
  List,
  Divider,
} from 'antd';
import {
  RobotOutlined,
  SendOutlined,
  ApiOutlined,
  SafetyOutlined,
  CodeOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import tmsApi from '../../services/tms';

const { Title, Text, Paragraph } = Typography;
const { Option } = Select;
const { TextArea } = Input;
const { TabPane } = Tabs;

// 命令定义
const COMMANDS = [
  { value: 'query_tasks', label: 'query_tasks - 查询任务', level: 1 },
  { value: 'get_recommendation', label: 'get_recommendation - 获取分发建议', level: 1 },
  { value: 'get_task_context', label: 'get_task_context - 获取任务上下文', level: 1 },
  { value: 'get_stats', label: 'get_stats - 获取统计', level: 1 },
  { value: 'assign_task', label: 'assign_task - 分配任务', level: 2 },
  { value: 'create_task', label: 'create_task - 创建任务', level: 2 },
  { value: 'set_deadline', label: 'set_deadline - 设置截止日期', level: 2 },
  { value: 'claim_task', label: 'claim_task - 认领任务', level: 2 },
  { value: 'reassign_task', label: 'reassign_task - 重新分配 (需确认)', level: 3 },
  { value: 'approve_task', label: 'approve_task - 代审批 (需确认)', level: 3 },
  { value: 'reject_task', label: 'reject_task - 驳回 (需确认)', level: 3 },
  { value: 'escalate_task', label: 'escalate_task - 升级审批', level: 3 },
  { value: 'batch_distribute', label: 'batch_distribute - 批量分发 (需确认)', level: 3 },
];

const EVENT_TYPES = [
  'task.created',
  'task.distributed',
  'task.claimed',
  'task.completed',
  'task.overdue',
  'approval.initiated',
  'approval.pending',
  'approval.approved',
  'approval.rejected',
  'approval.completed',
];

interface CommandLog {
  id: string;
  command: string;
  params: string;
  response: any;
  success: boolean;
  timestamp: string;
}

const AgentConsole: React.FC = () => {
  const [commandForm] = Form.useForm();
  const [webhookForm] = Form.useForm();
  const [agentForm] = Form.useForm();
  const [commandLogs, setCommandLogs] = useState<CommandLog[]>([]);
  const [executing, setExecuting] = useState(false);
  const [lastResponse, setLastResponse] = useState<any>(null);

  // 执行命令
  const handleExecuteCommand = async (values: any) => {
    setExecuting(true);
    try {
      let params = {};
      try {
        params = values.params ? JSON.parse(values.params) : {};
      } catch (e) {
        message.error('参数格式错误，请输入有效的 JSON');
        setExecuting(false);
        return;
      }

      const result = await tmsApi.agentCommand({
        agent_id: values.agent_id,
        command: values.command,
        params,
        idempotency_key: values.idempotency_key || undefined,
      });

      const log: CommandLog = {
        id: Date.now().toString(),
        command: values.command,
        params: values.params || '{}',
        response: result.data,
        success: result.data?.success,
        timestamp: new Date().toISOString(),
      };

      setCommandLogs(prev => [log, ...prev]);
      setLastResponse(result.data);

      if (result.data?.success) {
        message.success(result.data.message || '命令执行成功');
      } else {
        message.warning(result.data?.message || '命令执行完成');
      }
    } catch (error: any) {
      message.error(error.response?.data?.detail || '命令执行失败');
      setLastResponse({ error: error.message });
    } finally {
      setExecuting(false);
    }
  };

  // 注册 Agent
  const handleRegisterAgent = async (values: any) => {
    try {
      const result = await tmsApi.registerAgent({
        agent_id: values.agent_id,
        permission_level: values.permission_level,
        whitelisted: values.whitelisted,
      });
      message.success(result.data?.message || 'Agent 注册成功');
    } catch (error) {
      message.error('Agent 注册失败');
    }
  };

  // 注册 Webhook
  const handleRegisterWebhook = async (values: any) => {
    try {
      const result = await tmsApi.registerWebhook({
        agent_id: values.agent_id,
        event_types: values.event_types,
        webhook_url: values.webhook_url,
        secret: values.secret,
      });
      message.success(result.data?.message || 'Webhook 注册成功');
    } catch (error) {
      message.error('Webhook 注册失败');
    }
  };

  // 命令日志表格列
  const logColumns: ColumnsType<CommandLog> = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 180,
      render: (ts: string) => new Date(ts).toLocaleString(),
    },
    {
      title: '命令',
      dataIndex: 'command',
      key: 'command',
      width: 150,
      render: (cmd: string) => <Tag icon={<CodeOutlined />}>{cmd}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'success',
      key: 'success',
      width: 80,
      render: (success: boolean) => (
        <Tag color={success ? 'success' : 'error'}>{success ? '成功' : '失败'}</Tag>
      ),
    },
    {
      title: '响应',
      dataIndex: 'response',
      key: 'response',
      ellipsis: true,
      render: (res: any) => (
        <Text code style={{ fontSize: 11 }}>
          {JSON.stringify(res?.message || res).slice(0, 100)}
        </Text>
      ),
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      {/* 页面标题 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Title level={3} style={{ marginBottom: 0 }}>
            <RobotOutlined style={{ color: '#722ed1', marginRight: 8 }} />
            Agent 控制台
          </Title>
          <Text type="secondary">Chatbot/Agent 接入调试与监控</Text>
        </Col>
      </Row>

      {/* 权限说明 */}
      <Alert
        message="Agent 权限分级"
        description={
          <Space direction="vertical" size={4}>
            <Text>
              <Tag color="green">LEVEL 1</Tag> 只读 - query_tasks, get_recommendation, get_stats
            </Text>
            <Text>
              <Tag color="blue">LEVEL 2</Tag> 写入 - assign_task, create_task, set_deadline
            </Text>
            <Text>
              <Tag color="red">LEVEL 3</Tag> 高危 - approve_task, reject_task, batch_distribute (需人工确认)
            </Text>
          </Space>
        }
        type="info"
        showIcon
        style={{ marginBottom: 24 }}
      />

      <Tabs defaultActiveKey="command">
        {/* 命令执行 */}
        <TabPane
          tab={
            <span>
              <ThunderboltOutlined />
              命令执行
            </span>
          }
          key="command"
        >
          <Row gutter={24}>
            <Col span={12}>
              <Card title="执行 Agent 命令">
                <Form
                  form={commandForm}
                  layout="vertical"
                  onFinish={handleExecuteCommand}
                  initialValues={{
                    agent_id: 'test-agent',
                    command: 'query_tasks',
                    params: '{"limit": 5}',
                  }}
                >
                  <Form.Item
                    name="agent_id"
                    label="Agent ID"
                    rules={[{ required: true, message: '请输入 Agent ID' }]}
                  >
                    <Input prefix={<RobotOutlined />} placeholder="例如: chatbot-01" />
                  </Form.Item>

                  <Form.Item
                    name="command"
                    label="命令"
                    rules={[{ required: true, message: '请选择命令' }]}
                  >
                    <Select>
                      {COMMANDS.map(cmd => (
                        <Option key={cmd.value} value={cmd.value}>
                          <Space>
                            {cmd.label}
                            <Tag color={cmd.level === 1 ? 'green' : cmd.level === 2 ? 'blue' : 'red'}>
                              L{cmd.level}
                            </Tag>
                          </Space>
                        </Option>
                      ))}
                    </Select>
                  </Form.Item>

                  <Form.Item
                    name="params"
                    label="参数 (JSON)"
                  >
                    <TextArea
                      rows={4}
                      placeholder='{"task_id": "xxx", "limit": 10}'
                      style={{ fontFamily: 'monospace' }}
                    />
                  </Form.Item>

                  <Form.Item
                    name="idempotency_key"
                    label="幂等键 (可选)"
                  >
                    <Input placeholder="防止重复执行的唯一标识" />
                  </Form.Item>

                  <Form.Item>
                    <Button
                      type="primary"
                      htmlType="submit"
                      loading={executing}
                      icon={<SendOutlined />}
                      block
                    >
                      执行命令
                    </Button>
                  </Form.Item>
                </Form>
              </Card>
            </Col>

            <Col span={12}>
              <Card title="响应结果">
                {lastResponse ? (
                  <pre
                    style={{
                      background: '#f5f5f5',
                      padding: 16,
                      borderRadius: 8,
                      maxHeight: 400,
                      overflow: 'auto',
                      fontSize: 12,
                    }}
                  >
                    {JSON.stringify(lastResponse, null, 2)}
                  </pre>
                ) : (
                  <Text type="secondary">执行命令后查看响应</Text>
                )}
              </Card>

              <Card title="命令历史" style={{ marginTop: 16 }}>
                <Table
                  columns={logColumns}
                  dataSource={commandLogs}
                  rowKey="id"
                  size="small"
                  pagination={{ pageSize: 5 }}
                />
              </Card>
            </Col>
          </Row>
        </TabPane>

        {/* Agent 注册 */}
        <TabPane
          tab={
            <span>
              <SafetyOutlined />
              Agent 注册
            </span>
          }
          key="register"
        >
          <Row gutter={24}>
            <Col span={12}>
              <Card title="注册 Agent">
                <Form
                  form={agentForm}
                  layout="vertical"
                  onFinish={handleRegisterAgent}
                  initialValues={{ permission_level: 1, whitelisted: false }}
                >
                  <Form.Item
                    name="agent_id"
                    label="Agent ID"
                    rules={[{ required: true, message: '请输入 Agent ID' }]}
                  >
                    <Input placeholder="例如: chatbot-01, slack-bot" />
                  </Form.Item>

                  <Form.Item
                    name="permission_level"
                    label="权限等级"
                  >
                    <Select>
                      <Option value={1}>LEVEL 1 - 只读</Option>
                      <Option value={2}>LEVEL 2 - 写入</Option>
                      <Option value={3}>LEVEL 3 - 高危操作</Option>
                    </Select>
                  </Form.Item>

                  <Form.Item
                    name="whitelisted"
                    label="白名单 (高危操作无需确认)"
                    valuePropName="checked"
                  >
                    <Switch />
                  </Form.Item>

                  <Form.Item>
                    <Button type="primary" htmlType="submit" icon={<SafetyOutlined />}>
                      注册 Agent
                    </Button>
                  </Form.Item>
                </Form>
              </Card>
            </Col>

            <Col span={12}>
              <Card title="权限说明">
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="LEVEL 1 (只读)">
                    query_tasks, get_recommendation, get_task_context, get_stats
                  </Descriptions.Item>
                  <Descriptions.Item label="LEVEL 2 (写入)">
                    assign_task, create_task, set_deadline, claim_task
                  </Descriptions.Item>
                  <Descriptions.Item label="LEVEL 3 (高危)">
                    reassign_task, approve_task, reject_task, escalate_task, batch_distribute
                  </Descriptions.Item>
                  <Descriptions.Item label="白名单">
                    白名单 Agent 执行高危操作无需人工确认
                  </Descriptions.Item>
                  <Descriptions.Item label="幂等性">
                    使用 idempotency_key 防止重复执行
                  </Descriptions.Item>
                </Descriptions>
              </Card>
            </Col>
          </Row>
        </TabPane>

        {/* Webhook 管理 */}
        <TabPane
          tab={
            <span>
              <ApiOutlined />
              Webhook 订阅
            </span>
          }
          key="webhook"
        >
          <Row gutter={24}>
            <Col span={12}>
              <Card title="注册 Webhook">
                <Form
                  form={webhookForm}
                  layout="vertical"
                  onFinish={handleRegisterWebhook}
                >
                  <Form.Item
                    name="agent_id"
                    label="Agent ID"
                    rules={[{ required: true, message: '请输入 Agent ID' }]}
                  >
                    <Input placeholder="例如: chatbot-01" />
                  </Form.Item>

                  <Form.Item
                    name="webhook_url"
                    label="Webhook URL"
                    rules={[
                      { required: true, message: '请输入 Webhook URL' },
                      { type: 'url', message: '请输入有效的 URL' },
                    ]}
                  >
                    <Input placeholder="https://your-bot.com/webhook/tms" />
                  </Form.Item>

                  <Form.Item
                    name="event_types"
                    label="订阅事件"
                    rules={[{ required: true, message: '请选择事件类型' }]}
                  >
                    <Select mode="multiple" placeholder="选择要订阅的事件">
                      {EVENT_TYPES.map(event => (
                        <Option key={event} value={event}>
                          {event}
                        </Option>
                      ))}
                    </Select>
                  </Form.Item>

                  <Form.Item
                    name="secret"
                    label="签名密钥 (可选)"
                  >
                    <Input.Password placeholder="用于验证 Webhook 来源" />
                  </Form.Item>

                  <Form.Item>
                    <Button type="primary" htmlType="submit" icon={<ApiOutlined />}>
                      注册 Webhook
                    </Button>
                  </Form.Item>
                </Form>
              </Card>
            </Col>

            <Col span={12}>
              <Card title="事件类型说明">
                <List
                  size="small"
                  dataSource={[
                    { event: 'task.created', desc: '任务创建时触发' },
                    { event: 'task.distributed', desc: '任务分发后触发' },
                    { event: 'task.claimed', desc: '任务被认领时触发' },
                    { event: 'task.completed', desc: '任务完成时触发' },
                    { event: 'task.overdue', desc: '任务超期时触发' },
                    { event: 'approval.initiated', desc: '审批流发起时触发' },
                    { event: 'approval.pending', desc: '等待审批时触发' },
                    { event: 'approval.approved', desc: '审批通过时触发' },
                    { event: 'approval.rejected', desc: '审批驳回时触发' },
                    { event: 'approval.completed', desc: '审批流完成时触发' },
                  ]}
                  renderItem={item => (
                    <List.Item>
                      <Space>
                        <Tag color="purple">{item.event}</Tag>
                        <Text type="secondary">{item.desc}</Text>
                      </Space>
                    </List.Item>
                  )}
                />
              </Card>

              <Card title="Webhook 安全" style={{ marginTop: 16 }}>
                <Paragraph>
                  <Text strong>签名验证：</Text>
                  <br />
                  如果设置了 secret，每个 Webhook 请求会包含 X-TMS-Signature 头：
                  <br />
                  <Text code>X-TMS-Signature: sha256=HMAC_SHA256(secret, body)</Text>
                </Paragraph>
              </Card>
            </Col>
          </Row>
        </TabPane>

        {/* API 文档 */}
        <TabPane
          tab={
            <span>
              <CodeOutlined />
              API 文档
            </span>
          }
          key="docs"
        >
          <Card title="Agent 命令 API">
            <Paragraph>
              <Title level={5}>命令入口</Title>
              <Text code>POST /api/v1/tms/agent/command</Text>
            </Paragraph>

            <Paragraph>
              <Title level={5}>请求格式</Title>
              <pre style={{ background: '#f5f5f5', padding: 16, borderRadius: 8 }}>
{`{
  "agent_id": "chatbot-01",
  "command": "assign_task",
  "params": {
    "task_code": "TASK-2026-00001",
    "assign_to": "user:zhangwei",
    "reason": "技能匹配度 98%"
  },
  "idempotency_key": "uuid-xxx"
}`}
              </pre>
            </Paragraph>

            <Paragraph>
              <Title level={5}>响应格式</Title>
              <pre style={{ background: '#f5f5f5', padding: 16, borderRadius: 8 }}>
{`{
  "success": true,
  "command": "assign_task",
  "data": {
    "task_code": "TASK-2026-00001",
    "assigned_to": "user:zhangwei",
    "message": "任务已分配给 张伟"
  },
  "message": "任务已分配给 张伟",
  "requires_confirmation": false,
  "action_id": "uuid-xxx"
}`}
              </pre>
            </Paragraph>

            <Divider />

            <Paragraph>
              <Title level={5}>确认高危操作</Title>
              <Text code>POST /api/v1/tms/agent/confirm</Text>
              <pre style={{ background: '#f5f5f5', padding: 16, borderRadius: 8, marginTop: 8 }}>
{`{
  "action_id": "uuid-xxx",
  "confirmed_by": "manager-001",
  "approved": true
}`}
              </pre>
            </Paragraph>
          </Card>
        </TabPane>
      </Tabs>
    </div>
  );
};

export default AgentConsole;
