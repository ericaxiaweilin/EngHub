import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Typography, Statistic, Row, Col, Progress, Avatar, Descriptions } from 'antd';
import { PlusOutlined, EyeOutlined, EditOutlined, DeleteOutlined, TeamOutlined, CheckCircleOutlined, ClockCircleOutlined, StarOutlined, TrophyOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

interface TrainingRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  department: string;
  training_type: string;
  training_name: string;
  description: string;
  trainer: string;
  scheduled_date: string;
  completed_date: string;
  duration_hours: number;
  score: number;
  status: string;
  certificate_issued: boolean;
  created_at: string;
}

interface TrainingStats {
  total_trainings: number;
  completed: number;
  in_progress: number;
  avg_score: number;
  completion_rate: number;
  by_type: Record<string, number>;
  by_department: Record<string, number>;
}

const TrainingEducation: React.FC = () => {
  const [trainings, setTrainings] = useState<TrainingRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [stats, setStats] = useState<TrainingStats | null>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedTraining, setSelectedTraining] = useState<TrainingRecord | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  
  // Form
  const [createForm] = Form.useForm();

  // Fetch training records
  const fetchTrainings = async () => {
    setLoading(true);
    try {
      const params: any = {
        limit: pagination.pageSize,
        offset: (pagination.current - 1) * pagination.pageSize
      };
      
      if (searchText) {
        params.search = searchText;
      }
      if (typeFilter) {
        params.training_type = typeFilter;
      }
      if (statusFilter) {
        params.status = statusFilter;
      }
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/tpm/training/`, { params });
      setTrainings(response.data.trainings || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch training records:', error);
      message.error('Failed to load training records');
    } finally {
      setLoading(false);
    }
  };

  // Fetch statistics
  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/tpm/training/stats/`);
      setStats(response.data);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  };

  useEffect(() => {
    fetchTrainings();
    fetchStats();
  }, [pagination, typeFilter, statusFilter, dateRange]);

  // Handle table change
  const handleTableChange = (pagination: any) => {
    setPagination({ current: pagination.current, pageSize: pagination.pageSize });
  };

  // Handle search
  const handleSearch = () => {
    setPagination({ ...pagination, current: 1 });
    fetchTrainings();
  };

  // Handle create
  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/tpm/training/`, values);
      message.success('Training record created successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchTrainings();
      fetchStats();
    } catch (error) {
      console.error('Failed to create training:', error);
      message.error('Failed to create training');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Handle complete
  const handleComplete = async (id: string, score: number) => {
    try {
      await axios.post(`${API_BASE_URL}/tpm/training/${id}/complete`, { score });
      message.success('Training completed');
      fetchTrainings();
      fetchStats();
    } catch (error) {
      console.error('Failed to complete training:', error);
      message.error('Failed to complete training');
    }
  };

  // Column definitions
  const columns = [
    {
      title: 'Employee',
      dataIndex: 'employee_name',
      key: 'employee_name',
      width: 120,
      render: (name: string, record: TrainingRecord) => (
        <Space>
          <Avatar size="small">{name.charAt(0)}</Avatar>
          <span>{name}</span>
        </Space>
      )
    },
    {
      title: 'Training Name',
      dataIndex: 'training_name',
      key: 'training_name',
      ellipsis: true,
    },
    {
      title: 'Type',
      dataIndex: 'training_type',
      key: 'training_type',
      width: 120,
      render: (type: string) => {
        const typeMap: Record<string, { label: string; color: string }> = {
          'TPM_BASIC': { label: 'TPM Basic', color: 'blue' },
          'AUTONOMOUS_MAINTENANCE': { label: 'Autonomous Maint.', color: 'green' },
          'PLANNED_MAINTENANCE': { label: 'Planned Maint.', color: 'orange' },
          'SAFETY': { label: 'Safety', color: 'red' },
          'QUALITY': { label: 'Quality', color: 'purple' },
          'SKILL_UPGRADE': { label: 'Skill Upgrade', color: 'cyan' }
        };
        const config = typeMap[type] || { label: type, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Department',
      dataIndex: 'department',
      key: 'department',
      width: 100,
    },
    {
      title: 'Trainer',
      dataIndex: 'trainer',
      key: 'trainer',
      width: 100,
    },
    {
      title: 'Scheduled',
      dataIndex: 'scheduled_date',
      key: 'scheduled_date',
      width: 120,
      render: (date: string) => date ? new Date(date).toLocaleDateString() : '-',
    },
    {
      title: 'Duration',
      dataIndex: 'duration_hours',
      key: 'duration_hours',
      width: 80,
      render: (hours: number) => `${hours}h`,
    },
    {
      title: 'Score',
      dataIndex: 'score',
      key: 'score',
      width: 80,
      render: (score: number) => score ? <StarOutlined style={{ color: '#faad14' }} /> : '-',
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const statusMap: Record<string, { label: string; color: string }> = {
          'SCHEDULED': { label: 'Scheduled', color: 'default' },
          'IN_PROGRESS': { label: 'In Progress', color: 'blue' },
          'COMPLETED': { label: 'Completed', color: 'green' },
          'FAILED': { label: 'Failed', color: 'red' },
          'CANCELLED': { label: 'Cancelled', color: 'orange' }
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 150,
      render: (_: any, record: TrainingRecord) => (
        <Space>
          <Button 
            type="link" 
            icon={<EyeOutlined />} 
            onClick={() => {
              setSelectedTraining(record);
              setDetailModalVisible(true);
            }}
          >
            View
          </Button>
          {record.status === 'IN_PROGRESS' && (
            <Button 
              type="link" 
              icon={<CheckCircleOutlined />}
              onClick={() => {
                const score = prompt('Enter score (0-100):');
                if (score) handleComplete(record.id, parseInt(score));
              }}
            >
              Complete
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={3}>Training & Education (教育训练)</Title>
      <Text type="secondary">TPM 6th Pillar - Develop skills for all employees</Text>

      {/* Statistics */}
      {stats && (
        <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="Total Trainings"
                value={stats.total_trainings || 0}
                prefix={<TeamOutlined />}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Completed"
                value={stats.completed || 0}
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Avg Score"
                value={stats.avg_score || 0}
                suffix="/100"
                prefix={<TrophyOutlined />}
                valueStyle={{ color: '#faad14' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Completion Rate"
                value={stats.completion_rate || 0}
                suffix="%"
                prefix={<ClockCircleOutlined />}
                valueStyle={{ color: '#1890ff' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* Training Types */}
      <Card title="Training Categories" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          {[
            { name: 'TPM Basics', icon: '📚', color: 'blue', desc: 'TPM principles & 8 pillars' },
            { name: 'Autonomous Maint.', icon: '🔧', color: 'green', desc: 'Operator self-maintenance' },
            { name: 'Planned Maint.', icon: '⚙️', color: 'orange', desc: 'Professional maintenance skills' },
            { name: 'Safety', icon: '🛡️', color: 'red', desc: 'Workplace safety & hygiene' },
            { name: 'Quality', icon: '✅', color: 'purple', desc: 'Quality control & SPC' },
            { name: 'Skill Upgrade', icon: '📈', color: 'cyan', desc: 'Advanced technical skills' }
          ].map((type, index) => (
            <Col span={4} key={index}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 24 }}>{type.icon}</div>
                <div style={{ fontSize: 11, fontWeight: 'bold', marginTop: 4 }}>{type.name}</div>
                <div style={{ fontSize: 10, color: '#666' }}>{type.desc}</div>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      {/* Filters */}
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Input
          placeholder="Search..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          onPressEnter={handleSearch}
          style={{ width: 200 }}
        />
        <Select
          placeholder="Type"
          value={typeFilter}
          onChange={setTypeFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="TPM_BASIC">TPM Basic</Select.Option>
          <Select.Option value="AUTONOMOUS_MAINTENANCE">Autonomous Maint.</Select.Option>
          <Select.Option value="PLANNED_MAINTENANCE">Planned Maint.</Select.Option>
          <Select.Option value="SAFETY">Safety</Select.Option>
          <Select.Option value="QUALITY">Quality</Select.Option>
          <Select.Option value="SKILL_UPGRADE">Skill Upgrade</Select.Option>
        </Select>
        <Select
          placeholder="Status"
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="SCHEDULED">Scheduled</Select.Option>
          <Select.Option value="IN_PROGRESS">In Progress</Select.Option>
          <Select.Option value="COMPLETED">Completed</Select.Option>
          <Select.Option value="FAILED">Failed</Select.Option>
        </Select>
        <RangePicker
          value={dateRange}
          onChange={(dates) => setDateRange(dates as any)}
          placeholder={['Start Date', 'End Date']}
        />
        <Button type="primary" onClick={handleSearch}>
          Search
        </Button>
        <Button onClick={handleSearch}>Reset</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalVisible(true)}>
          Add Training
        </Button>
      </div>

      {/* Table */}
      <Table
        columns={columns}
        dataSource={trainings}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          total,
          showSizeChanger: true,
          showTotal: (total) => `Total ${total} trainings`,
        }}
        onChange={handleTableChange}
      />

      {/* Create Modal */}
      <Modal
        title="Add Training Record"
        open={createModalVisible}
        onOk={() => createForm.submit()}
        onCancel={() => {
          setCreateModalVisible(false);
          createForm.resetFields();
        }}
        confirmLoading={submitLoading}
        width={700}
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={handleCreate}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="employee_id"
                label="Employee"
                rules={[{ required: true, message: 'Please select employee' }]}
              >
                <Select placeholder="Select employee" options={[]} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="department"
                label="Department"
                rules={[{ required: true, message: 'Please select department' }]}
              >
                <Select>
                  <Select.Option value="Production">Production</Select.Option>
                  <Select.Option value="Maintenance">Maintenance</Select.Option>
                  <Select.Option value="Quality">Quality</Select.Option>
                  <Select.Option value="Engineering">Engineering</Select.Option>
                  <Select.Option value="HR">HR</Select.Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="training_name"
            label="Training Name"
            rules={[{ required: true, message: 'Please enter training name' }]}
          >
            <Input placeholder="e.g., TPM Basics for Operators" />
          </Form.Item>
          <Form.Item
            name="training_type"
            label="Training Type"
            rules={[{ required: true, message: 'Please select type' }]}
          >
            <Select>
              <Select.Option value="TPM_BASIC">TPM Basic</Select.Option>
              <Select.Option value="AUTONOMOUS_MAINTENANCE">Autonomous Maintenance</Select.Option>
              <Select.Option value="PLANNED_MAINTENANCE">Planned Maintenance</Select.Option>
              <Select.Option value="SAFETY">Safety</Select.Option>
              <Select.Option value="QUALITY">Quality</Select.Option>
              <Select.Option value="SKILL_UPGRADE">Skill Upgrade</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="trainer"
            label="Trainer"
            rules={[{ required: true, message: 'Please enter trainer' }]}
          >
            <Input placeholder="Trainer name" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="scheduled_date"
                label="Scheduled Date"
                rules={[{ required: true, message: 'Please select date' }]}
              >
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="duration_hours"
                label="Duration (hours)"
                rules={[{ required: true, message: 'Please enter duration' }]}
              >
                <Input type="number" min="1" placeholder="4" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="description"
            label="Description"
          >
            <TextArea rows={3} placeholder="Training content description..." />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="Training Detail"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            Close
          </Button>
        ]}
        width={600}
      >
        {selectedTraining && (
          <div>
            <Descriptions column={2} bordered>
              <Descriptions.Item label="Employee">
                <Space>
                  <Avatar size="small">{selectedTraining.employee_name.charAt(0)}</Avatar>
                  {selectedTraining.employee_name}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="Department">{selectedTraining.department}</Descriptions.Item>
              <Descriptions.Item label="Training">{selectedTraining.training_name}</Descriptions.Item>
              <Descriptions.Item label="Type">
                <Tag color={
                  selectedTraining.training_type === 'TPM_BASIC' ? 'blue' :
                  selectedTraining.training_type === 'SAFETY' ? 'red' : 'green'
                }>
                  {selectedTraining.training_type}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Trainer">{selectedTraining.trainer}</Descriptions.Item>
              <Descriptions.Item label="Duration">{selectedTraining.duration_hours} hours</Descriptions.Item>
              <Descriptions.Item label="Scheduled">
                {selectedTraining.scheduled_date ? new Date(selectedTraining.scheduled_date).toLocaleDateString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Completed">
                {selectedTraining.completed_date ? new Date(selectedTraining.completed_date).toLocaleDateString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Score">
                {selectedTraining.score ? (
                  <Space>
                    <StarOutlined style={{ color: '#faad14' }} />
                    <span>{selectedTraining.score}/100</span>
                  </Space>
                ) : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Certificate">
                {selectedTraining.certificate_issued ? (
                  <Tag color="green">Issued</Tag>
                ) : (
                  <Tag color="default">Not Issued</Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="Status" span={2}>
                <Tag color={
                  selectedTraining.status === 'COMPLETED' ? 'green' :
                  selectedTraining.status === 'IN_PROGRESS' ? 'blue' :
                  selectedTraining.status === 'FAILED' ? 'red' : 'default'
                }>
                  {selectedTraining.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Description" span={2}>
                {selectedTraining.description || '-'}
              </Descriptions.Item>
            </Descriptions>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default TrainingEducation;
