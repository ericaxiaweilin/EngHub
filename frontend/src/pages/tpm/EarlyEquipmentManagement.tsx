import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Typography, Statistic, Row, Col, Steps, Progress, Descriptions, Divider, Timeline } from 'antd';
import { PlusOutlined, EyeOutlined, EditOutlined, DeleteOutlined, SettingOutlined, CheckCircleOutlined, ClockCircleOutlined, WarningOutlined, TrophyOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

interface EarlyEquipmentProject {
  id: string;
  project_name: string;
  equipment_type: string;
  department: string;
  status: string;
  current_phase: number;
  phases: Array<{
    phase: number;
    name: string;
    status: string;
    completed_at?: string;
    notes?: string;
  }>;
  expected_cost?: number;
  reliability_target: number;
  maintainability_target: number;
  cost_target: number;
  actual_cost: number;
  expected_lifespan: number;
  actual_lifespan: number;
  lessons_learned: string;
  created_by: string;
  created_at: string;
}

interface EarlyEquipmentStats {
  total_projects: number;
  in_progress: number;
  completed: number;
  avg_reliability: number;
  avg_maintainability: number;
  by_status: Record<string, number>;
}

const EarlyEquipmentManagement: React.FC = () => {
  const [projects, setProjects] = useState<EarlyEquipmentProject[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [stats, setStats] = useState<EarlyEquipmentStats | null>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedProject, setSelectedProject] = useState<EarlyEquipmentProject | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  
  // Form
  const [createForm] = Form.useForm();

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
      if (typeFilter) {
        params.equipment_type = typeFilter;
      }
      if (statusFilter) {
        params.status = statusFilter;
      }
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/tpm/early-equipment/`, { params });
      setProjects(response.data.projects || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch early equipment projects:', error);
      message.error('Failed to load projects');
    } finally {
      setLoading(false);
    }
  };

  // Fetch statistics
  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/tpm/early-equipment/stats/`);
      setStats(response.data);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  };

  useEffect(() => {
    fetchProjects();
    fetchStats();
  }, [pagination, typeFilter, statusFilter, dateRange]);

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
      await axios.post(`${API_BASE_URL}/tpm/early-equipment/`, values);
      message.success('Early equipment project created successfully');
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

  // Handle phase completion
  const handlePhaseComplete = async (projectId: string, phase: number) => {
    try {
      await axios.post(`${API_BASE_URL}/tpm/early-equipment/${projectId}/phase`, {
        phase: phase
      });
      message.success('Phase completed');
      fetchProjects();
    } catch (error) {
      console.error('Failed to complete phase:', error);
      message.error('Failed to complete phase');
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
      title: 'Equipment Type',
      dataIndex: 'equipment_type',
      key: 'equipment_type',
      width: 120,
      render: (type: string) => <Tag>{type}</Tag>
    },
    {
      title: 'Department',
      dataIndex: 'department',
      key: 'department',
      width: 100,
    },
    {
      title: 'Reliability Target',
      dataIndex: 'reliability_target',
      key: 'reliability_target',
      width: 120,
      render: (target: number) => `${target}%`,
    },
    {
      title: 'Maintainability',
      dataIndex: 'maintainability_target',
      key: 'maintainability_target',
      width: 120,
      render: (target: number) => `${target}%`,
    },
    {
      title: 'Cost',
      key: 'cost',
      width: 100,
      render: (_: any, record: EarlyEquipmentProject) => {
        const expected = record.expected_cost ?? 0
        const actual = record.actual_cost ?? 0
        const variance = expected > 0
          ? ((actual - expected) / expected * 100).toFixed(1)
          : '0';
        return (
          <span style={{ color: parseFloat(variance) > 0 ? '#ff4d4f' : '#52c41a' }}>
            {variance}%
          </span>
        );
      }
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => {
        const statusMap: Record<string, { label: string; color: string }> = {
          'PLANNING': { label: 'Planning', color: 'default' },
          'DESIGN': { label: 'Design', color: 'blue' },
          'PROCUREMENT': { label: 'Procurement', color: 'orange' },
          'INSTALLATION': { label: 'Installation', color: 'purple' },
          'COMMISSIONING': { label: 'Commissioning', color: 'cyan' },
          'COMPLETED': { label: 'Completed', color: 'green' }
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (date: string) => date ? new Date(date).toLocaleDateString() : '-',
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 100,
      render: (_: any, record: EarlyEquipmentProject) => (
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
      ),
    },
  ];

  return (
    <div>
      <Title level={3}>Early Equipment Management (初期管理)</Title>
      <Text type="secondary">TPM 5th Pillar - Design for maintainability and reliability from the start</Text>

      {/* Statistics */}
      {stats && (
        <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="Total Projects"
                value={stats.total_projects || 0}
                prefix={<SettingOutlined />}
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
                title="Avg Reliability"
                value={stats.avg_reliability || 0}
                suffix="%"
                prefix={<TrophyOutlined />}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* Project Lifecycle */}
      <Card title="Equipment Lifecycle" style={{ marginBottom: 16 }}>
        <Steps
          current={1}
          items={[
            { title: 'Planning', description: 'Requirements & feasibility' },
            { title: 'Design', description: 'Maintainability design' },
            { title: 'Procurement', description: 'Vendor selection' },
            { title: 'Installation', description: 'Setup & integration' },
            { title: 'Commissioning', description: 'Testing & validation' },
            { title: 'Operation', description: 'Full production' }
          ]}
        />
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
          placeholder="Equipment Type"
          value={typeFilter}
          onChange={setTypeFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="CNC">CNC Machine</Select.Option>
          <Select.Option value="INJECTION">Injection Molder</Select.Option>
          <Select.Option value="CONVEYOR">Conveyor</Select.Option>
          <Select.Option value="ROBOT">Robot</Select.Option>
          <Select.Option value="PACKAGING">Packaging</Select.Option>
        </Select>
        <Select
          placeholder="Status"
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="PLANNING">Planning</Select.Option>
          <Select.Option value="DESIGN">Design</Select.Option>
          <Select.Option value="PROCUREMENT">Procurement</Select.Option>
          <Select.Option value="INSTALLATION">Installation</Select.Option>
          <Select.Option value="COMMISSIONING">Commissioning</Select.Option>
          <Select.Option value="COMPLETED">Completed</Select.Option>
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
          New Project
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
        title="Create Early Equipment Project"
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
            <Input placeholder="e.g., New CNC Line Installation" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="equipment_type"
                label="Equipment Type"
                rules={[{ required: true, message: 'Please select type' }]}
              >
                <Select>
                  <Select.Option value="CNC">CNC Machine</Select.Option>
                  <Select.Option value="INJECTION">Injection Molder</Select.Option>
                  <Select.Option value="CONVEYOR">Conveyor</Select.Option>
                  <Select.Option value="ROBOT">Robot</Select.Option>
                  <Select.Option value="PACKAGING">Packaging</Select.Option>
                </Select>
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
                  <Select.Option value="Engineering">Engineering</Select.Option>
                  <Select.Option value="Quality">Quality</Select.Option>
                  <Select.Option value="Maintenance">Maintenance</Select.Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item
                name="reliability_target"
                label="Reliability Target (%)"
                rules={[{ required: true, message: 'Please enter target' }]}
              >
                <Input type="number" min="0" max="100" placeholder="95" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="maintainability_target"
                label="Maintainability Target (%)"
                rules={[{ required: true, message: 'Please enter target' }]}
              >
                <Input type="number" min="0" max="100" placeholder="90" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="expected_lifespan"
                label="Expected Lifespan (years)"
              >
                <Input type="number" min="1" placeholder="10" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="design_notes"
            label="Design for Maintainability Notes"
          >
            <TextArea rows={3} placeholder="Describe maintainability features: easy access, modular design, standard parts..." />
          </Form.Item>
          <Form.Item
            name="expected_cost"
            label="Expected Cost"
          >
            <Input type="number" min="0" placeholder="100000" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="Early Equipment Project Detail"
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
              <Descriptions.Item label="Equipment Type">{selectedProject.equipment_type}</Descriptions.Item>
              <Descriptions.Item label="Department">{selectedProject.department}</Descriptions.Item>
              <Descriptions.Item label="Status">
                <Tag color={
                  selectedProject.status === 'COMPLETED' ? 'green' :
                  selectedProject.status === 'COMMISSIONING' ? 'cyan' :
                  selectedProject.status === 'INSTALLATION' ? 'purple' :
                  selectedProject.status === 'PROCUREMENT' ? 'orange' :
                  selectedProject.status === 'DESIGN' ? 'blue' : 'default'
                }>
                  {selectedProject.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Reliability Target">
                <Progress percent={selectedProject.reliability_target} size="small" />
                <span>{selectedProject.reliability_target}%</span>
              </Descriptions.Item>
              <Descriptions.Item label="Maintainability Target">
                <Progress percent={selectedProject.maintainability_target} size="small" />
                <span>{selectedProject.maintainability_target}%</span>
              </Descriptions.Item>
              <Descriptions.Item label="Expected Lifespan">
                {selectedProject.expected_lifespan ? `${selectedProject.expected_lifespan} years` : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Created By">{selectedProject.created_by}</Descriptions.Item>
              <Descriptions.Item label="Created At">
                {selectedProject.created_at ? new Date(selectedProject.created_at).toLocaleString() : '-'}
              </Descriptions.Item>
            </Descriptions>

            <Divider />
            
            <Title level={5}>Project Phases</Title>
            <Timeline
              items={selectedProject.phases.map((p, index) => ({
                color: p.status === 'COMPLETED' ? 'green' : p.status === 'IN_PROGRESS' ? 'blue' : 'gray',
                children: (
                  <div>
                    <div style={{ fontWeight: 'bold' }}>{p.name}</div>
                    <div style={{ fontSize: 12, color: '#666' }}>
                      {p.status} {p.completed_at ? `- Completed: ${new Date(p.completed_at).toLocaleDateString()}` : ''}
                    </div>
                    {p.notes && <div style={{ fontSize: 12, marginTop: 4 }}>{p.notes}</div>}
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

export default EarlyEquipmentManagement;
