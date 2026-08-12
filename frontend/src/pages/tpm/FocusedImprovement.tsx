import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Typography, Statistic, Row, Col, Progress, Timeline, Avatar } from 'antd';
import { PlusOutlined, EyeOutlined, EditOutlined, DeleteOutlined, TrophyOutlined, TeamOutlined, CheckCircleOutlined, ClockCircleOutlined, FireOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

interface KaizenProject {
  id: string;
  project_name: string;
  team_leader: string;
  team_members: string[];
  department: string;
  problem_statement: string;
  current_value: number;
  target_value: number;
  improvement: number;
  status: string;
  phase: string;
  start_date: string;
  end_date: string;
  created_at: string;
}

interface KaizenStats {
  total_projects: number;
  completed: number;
  in_progress: number;
  avg_improvement: number;
  total_savings: number;
  by_phase: Record<string, number>;
}

const FocusedImprovement: React.FC = () => {
  const [projects, setProjects] = useState<KaizenProject[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [phaseFilter, setPhaseFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [stats, setStats] = useState<KaizenStats | null>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedProject, setSelectedProject] = useState<KaizenProject | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  
  // Form
  const [createForm] = Form.useForm();

  // Kaizen phases
  const kaizenPhases = [
    { key: 'TOPIC_SELECTION', name: 'Topic Selection', desc: 'Select improvement topic' },
    { key: 'CURRENT_STATE', name: 'Current State', desc: 'Measure current performance' },
    { key: 'ANALYSIS', name: 'Analysis', desc: 'Analyze root causes' },
    { key: 'IMPROVEMENT', name: 'Improvement', desc: 'Implement countermeasures' },
    { key: 'VERIFICATION', name: 'Verification', desc: 'Verify results' },
    { key: 'STANDARDIZATION', name: 'Standardization', desc: 'Standardize new process' },
    { key: 'COMPLETED', name: 'Completed', desc: 'Project completed' }
  ];

  // Fetch projects
  const fetchProjects = async () => {
    setLoading(true);
    try {
      const params: any = {
        limit: pagination.pageSize,
        offset: (pagination.current - 1) * pagination.pageSize
      };
      
      if (searchText) {
        params.search = searchText;
      }
      if (statusFilter) {
        params.status = statusFilter;
      }
      if (phaseFilter) {
        params.phase = phaseFilter;
      }
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/tpm/kaizen/`, { params });
      setProjects(response.data.projects || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch kaizen projects:', error);
      message.error('Failed to load projects');
    } finally {
      setLoading(false);
    }
  };

  // Fetch statistics
  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/tpm/kaizen/stats/`);
      setStats(response.data);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  };

  useEffect(() => {
    fetchProjects();
    fetchStats();
  }, [pagination, statusFilter, phaseFilter, dateRange]);

  // Handle table change
  const handleTableChange = (pagination: any) => {
    setPagination({ current: pagination.current, pageSize: pagination.pageSize });
  };

  // Handle search
  const handleSearch = () => {
    setPagination({ ...pagination, current: 1 });
    fetchProjects();
  };

  // Handle create
  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/tpm/kaizen/`, values);
      message.success('Kaizen project created successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchProjects();
      fetchStats();
    } catch (error) {
      console.error('Failed to create project:', error);
      message.error('Failed to create project');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Handle phase advance
  const handlePhaseAdvance = async (id: string, newPhase: string) => {
    try {
      await axios.post(`${API_BASE_URL}/tpm/kaizen/${id}/phase`, { phase: newPhase });
      message.success('Project phase advanced');
      fetchProjects();
    } catch (error) {
      console.error('Failed to advance phase:', error);
      message.error('Failed to advance phase');
    }
  };

  // Column definitions
  const columns = [
    {
      title: 'Project Name',
      dataIndex: 'project_name',
      key: 'project_name',
      width: 200,
    },
    {
      title: 'Team Leader',
      dataIndex: 'team_leader',
      key: 'team_leader',
      width: 120,
      render: (name: string) => (
        <Space>
          <Avatar size="small">{name.charAt(0)}</Avatar>
          {name}
        </Space>
      )
    },
    {
      title: 'Department',
      dataIndex: 'department',
      key: 'department',
      width: 100,
    },
    {
      title: 'Improvement',
      key: 'improvement',
      width: 100,
      render: (_: any, record: KaizenProject) => (
        <span style={{ color: '#52c41a', fontWeight: 'bold' }}>
          {record.improvement > 0 ? `+${record.improvement}%` : `${record.improvement}%`}
        </span>
      ),
    },
    {
      title: 'Phase',
      dataIndex: 'phase',
      key: 'phase',
      width: 120,
      render: (phase: string) => {
        const phaseConfig = kaizenPhases.find(p => p.key === phase);
        return phaseConfig ? <Tag color="blue">{phaseConfig.name}</Tag> : <Tag>{phase}</Tag>;
      }
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const statusMap: Record<string, { label: string; color: string }> = {
          'ACTIVE': { label: 'Active', color: 'green' },
          'PAUSED': { label: 'Paused', color: 'orange' },
          'COMPLETED': { label: 'Completed', color: 'blue' },
          'CANCELLED': { label: 'Cancelled', color: 'red' }
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Start Date',
      dataIndex: 'start_date',
      key: 'start_date',
      width: 100,
      render: (date: string) => date ? new Date(date).toLocaleDateString() : '-',
    },
    {
      title: 'End Date',
      dataIndex: 'end_date',
      key: 'end_date',
      width: 100,
      render: (date: string) => date ? new Date(date).toLocaleDateString() : '-',
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 150,
      render: (_: any, record: KaizenProject) => (
        <Space>
          <Button 
            type="link" 
            icon={<EyeOutlined />} 
            onClick={() => {
              setSelectedProject(record);
              setDetailModalVisible(true);
            }}
          >
            View
          </Button>
          {record.status === 'ACTIVE' && (
            <Button 
              type="link" 
              icon={<FireOutlined />}
              onClick={() => {
                const nextPhase = kaizenPhases[kaizenPhases.findIndex(p => p.key === record.phase) + 1]?.key;
                if (nextPhase) handlePhaseAdvance(record.id, nextPhase);
              }}
            >
              Next Phase
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={3}>Focused Improvement (重点改善) - Kaizen</Title>
      <Text type="secondary">TPM 4th Pillar - Small-group continuous improvement activities</Text>

      {/* Statistics */}
      {stats && (
        <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="Total Projects"
                value={stats.total_projects || 0}
                prefix={<TrophyOutlined />}
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
                title="In Progress"
                value={stats.in_progress || 0}
                prefix={<ClockCircleOutlined />}
                valueStyle={{ color: '#1890ff' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Avg Improvement"
                value={stats.avg_improvement || 0}
                suffix="%"
                prefix={<FireOutlined />}
                valueStyle={{ color: '#faad14' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* Kaizen Cycle */}
      <Card title="Kaizen Improvement Cycle" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          {kaizenPhases.map((phase, index) => (
            <Col span={3.4} key={phase.key}>
              <Card size="small" style={{ textAlign: 'center', height: 80 }}>
                <div style={{ fontSize: 20 }}>{index + 1}</div>
                <div style={{ fontSize: 10, fontWeight: 'bold' }}>{phase.name}</div>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      {/* Filters */}
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Input
          placeholder="Search projects..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          onPressEnter={handleSearch}
          style={{ width: 200 }}
        />
        <Select
          placeholder="Status"
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 120 }}
          allowClear
        >
          <Select.Option value="ACTIVE">Active</Select.Option>
          <Select.Option value="PAUSED">Paused</Select.Option>
          <Select.Option value="COMPLETED">Completed</Select.Option>
          <Select.Option value="CANCELLED">Cancelled</Select.Option>
        </Select>
        <Select
          placeholder="Phase"
          value={phaseFilter}
          onChange={setPhaseFilter}
          style={{ width: 150 }}
          allowClear
        >
          {kaizenPhases.map(p => (
            <Select.Option key={p.key} value={p.key}>{p.name}</Select.Option>
          ))}
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
          New Kaizen
        </Button>
      </div>

      {/* Table */}
      <Table
        columns={columns}
        dataSource={projects}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          total,
          showSizeChanger: true,
          showTotal: (total) => `Total ${total} projects`,
        }}
        onChange={handleTableChange}
      />

      {/* Create Modal */}
      <Modal
        title="Create Kaizen Project"
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
          <Form.Item
            name="project_name"
            label="Project Name"
            rules={[{ required: true, message: 'Please enter project name' }]}
          >
            <Input placeholder="e.g., Reduce Changeover Time by 30%" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="team_leader"
                label="Team Leader"
                rules={[{ required: true, message: 'Please enter team leader' }]}
              >
                <Input placeholder="Team leader name" />
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
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="problem_statement"
            label="Problem Statement"
            rules={[{ required: true, message: 'Please describe the problem' }]}
          >
            <TextArea rows={3} placeholder="Describe the current problem and its impact..." />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="current_value"
                label="Current Value"
                rules={[{ required: true, message: 'Please enter current value' }]}
              >
                <Input type="number" min="0" placeholder="100" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="target_value"
                label="Target Value"
                rules={[{ required: true, message: 'Please enter target value' }]}
              >
                <Input type="number" min="0" placeholder="70" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="start_date"
            label="Start Date"
            rules={[{ required: true, message: 'Please select start date' }]}
          >
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="end_date"
            label="Target End Date"
          >
            <DatePicker style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="Kaizen Project Detail"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            Close
          </Button>
        ]}
        width={800}
      >
        {selectedProject && (
          <div>
            <Descriptions column={2} bordered>
              <Descriptions.Item label="Project">{selectedProject.project_name}</Descriptions.Item>
              <Descriptions.Item label="Team Leader">
                <Space>
                  <Avatar size="small">{selectedProject.team_leader.charAt(0)}</Avatar>
                  {selectedProject.team_leader}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="Department">{selectedProject.department}</Descriptions.Item>
              <Descriptions.Item label="Status">
                <Tag color={
                  selectedProject.status === 'COMPLETED' ? 'green' :
                  selectedProject.status === 'PAUSED' ? 'orange' : 'blue'
                }>
                  {selectedProject.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Current Value">
                <span style={{ color: '#ff4d4f' }}>{selectedProject.current_value}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Target Value">
                <span style={{ color: '#52c41a' }}>{selectedProject.target_value}</span>
              </Descriptions.Item>
              <Descriptions.Item label="Improvement">
                <span style={{ color: '#52c41a', fontWeight: 'bold' }}>
                  {selectedProject.improvement > 0 ? `+${selectedProject.improvement}%` : `${selectedProject.improvement}%`}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="Phase">
                <Tag color="blue">
                  {kaizenPhases.find(p => p.key === selectedProject.phase)?.name || selectedProject.phase}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Start Date">
                {selectedProject.start_date ? new Date(selectedProject.start_date).toLocaleDateString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="End Date">
                {selectedProject.end_date ? new Date(selectedProject.end_date).toLocaleDateString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Problem Statement" colspan={2}>
                {selectedProject.problem_statement}
              </Descriptions.Item>
            </Descriptions>

            <Divider />
            
            <Title level={5}>Kaizen Cycle Progress</Title>
            <Progress 
              percent={(kaizenPhases.findIndex(p => p.key === selectedProject.phase) + 1) / kaizenPhases.length * 100}
              status="active"
            />
            <Timeline
              items={kaizenPhases.map((phase, index) => ({
                color: index < kaizenPhases.findIndex(p => p.key === selectedProject.phase) ? 'green' : 
                       index === kaizenPhases.findIndex(p => p.key === selectedProject.phase) ? 'blue' : 'gray',
                children: (
                  <div>
                    <div style={{ fontWeight: 'bold' }}>{phase.name}</div>
                    <div style={{ fontSize: 12, color: '#666' }}>{phase.desc}</div>
                  </div>
                )
              }))}
            />
          </div>
        )}
      </Modal>
    </div>
  );
};

export default FocusedImprovement;
