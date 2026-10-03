import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Typography, Statistic, Row, Col } from 'antd';
import { PlusOutlined, CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

interface MaintenanceTask {
  id: string;
  equipment_id: string;
  equipment_name: string;
  task_type: string;
  task_name: string;
  description: string;
  frequency: string;
  last_performed: string;
  next_due: string;
  status: string;
  performed_by: string;
  duration_minutes: number;
}

interface MaintenanceStats {
  total_tasks: number;
  completed: number;
  pending: number;
  overdue: number;
  completion_rate: number;
}

const PreventiveMaintenance: React.FC = () => {
  const [tasks, setTasks] = useState<MaintenanceTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [stats, setStats] = useState<MaintenanceStats | null>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedTask, setSelectedTask] = useState<MaintenanceTask | null>(null);
  
  // Form
  const [createForm] = Form.useForm();
  const [submitLoading, setSubmitLoading] = useState(false);

  // Fetch maintenance tasks
  const fetchTasks = async () => {
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
      if (typeFilter) {
        params.task_type = typeFilter;
      }
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/api/v1/equipment/maintenance/`, { params });
      setTasks(response.data.tasks || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch maintenance tasks:', error);
      message.error('Failed to load maintenance tasks');
    } finally {
      setLoading(false);
    }
  };

  // Fetch statistics
  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/v1/equipment/maintenance/stats/`);
      setStats(response.data);
    } catch (error) {
      console.error('Failed to fetch maintenance stats:', error);
    }
  };

  useEffect(() => {
    fetchTasks();
    fetchStats();
  }, [pagination, statusFilter, typeFilter, dateRange]);

  // Handle table change
  const handleTableChange = (pagination: any) => {
    setPagination({ current: pagination.current, pageSize: pagination.pageSize });
  };

  // Handle search
  const handleSearch = () => {
    setPagination({ ...pagination, current: 1 });
    fetchTasks();
  };

  // Handle create
  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/api/v1/equipment/maintenance/`, values);
      message.success('Maintenance task created successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchTasks();
      fetchStats();
    } catch (error) {
      console.error('Failed to create maintenance task:', error);
      message.error('Failed to create maintenance task');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Handle complete task
  const handleComplete = async (id: string) => {
    try {
      await axios.post(`${API_BASE_URL}/api/v1/equipment/maintenance/${id}/complete`);
      message.success('Task marked as completed');
      fetchTasks();
      fetchStats();
    } catch (error) {
      console.error('Failed to complete task:', error);
      message.error('Failed to complete task');
    }
  };

  // Column definitions
  const columns = [
    {
      title: 'Equipment',
      dataIndex: 'equipment_name',
      key: 'equipment_name',
      width: 150,
    },
    {
      title: 'Task Name',
      dataIndex: 'task_name',
      key: 'task_name',
      ellipsis: true,
    },
    {
      title: 'Type',
      dataIndex: 'task_type',
      key: 'task_type',
      width: 100,
      render: (type: string) => {
        const typeMap: Record<string, { label: string; color: string }> = {
          'INSPECTION': { label: 'Inspection', color: 'blue' },
          'LUBRICATION': { label: 'Lubrication', color: 'green' },
          'CALIBRATION': { label: 'Calibration', color: 'purple' },
          'REPLACEMENT': { label: 'Replacement', color: 'orange' },
          'ADJUSTMENT': { label: 'Adjustment', color: 'cyan' }
        };
        const config = typeMap[type] || { label: type, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Frequency',
      dataIndex: 'frequency',
      key: 'frequency',
      width: 100,
    },
    {
      title: 'Next Due',
      dataIndex: 'next_due',
      key: 'next_due',
      width: 120,
      render: (date: string) => date ? new Date(date).toLocaleDateString() : '-',
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const statusMap: Record<string, { label: string; color: string }> = {
          'PENDING': { label: 'Pending', color: 'default' },
          'IN_PROGRESS': { label: 'In Progress', color: 'blue' },
          'COMPLETED': { label: 'Completed', color: 'green' },
          'OVERDUE': { label: 'Overdue', color: 'red' }
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Duration',
      dataIndex: 'duration_minutes',
      key: 'duration_minutes',
      width: 80,
      render: (mins: number) => `${mins} min`,
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 150,
      render: (_: any, record: MaintenanceTask) => (
        <Space>
          <Button 
            type="link" 
            onClick={() => {
              setSelectedTask(record);
              setDetailModalVisible(true);
            }}
          >
            View
          </Button>
          {record.status !== 'COMPLETED' && (
            <Button 
              type="link" 
              icon={<CheckCircleOutlined />}
              onClick={() => handleComplete(record.id)}
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
      <Title level={3}>Preventive Maintenance</Title>
      <Text type="secondary">Schedule and track preventive maintenance tasks for equipment</Text>

      {/* Statistics */}
      {stats && (
        <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="Total Tasks"
                value={stats.total_tasks}
                prefix={<ClockCircleOutlined />}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Completed"
                value={stats.completed}
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Pending"
                value={stats.pending}
                prefix={<ClockCircleOutlined />}
                valueStyle={{ color: '#faad14' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Overdue"
                value={stats.overdue}
                prefix={<ExclamationCircleOutlined />}
                valueStyle={{ color: '#ff4d4f' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* Filters */}
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Input
          placeholder="Search tasks..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          onPressEnter={handleSearch}
          style={{ width: 200 }}
        />
        <Select
          placeholder="Status"
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="PENDING">Pending</Select.Option>
          <Select.Option value="IN_PROGRESS">In Progress</Select.Option>
          <Select.Option value="COMPLETED">Completed</Select.Option>
          <Select.Option value="OVERDUE">Overdue</Select.Option>
        </Select>
        <Select
          placeholder="Type"
          value={typeFilter}
          onChange={setTypeFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="INSPECTION">Inspection</Select.Option>
          <Select.Option value="LUBRICATION">Lubrication</Select.Option>
          <Select.Option value="CALIBRATION">Calibration</Select.Option>
          <Select.Option value="REPLACEMENT">Replacement</Select.Option>
          <Select.Option value="ADJUSTMENT">Adjustment</Select.Option>
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
          Create Task
        </Button>
      </div>

      {/* Table */}
      <Table
        columns={columns}
        dataSource={tasks}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          total,
          showSizeChanger: true,
          showTotal: (total) => `Total ${total} tasks`,
        }}
        onChange={handleTableChange}
      />

      {/* Create Modal */}
      <Modal
        title="Create Maintenance Task"
        open={createModalVisible}
        onOk={() => createForm.submit()}
        onCancel={() => {
          setCreateModalVisible(false);
          createForm.resetFields();
        }}
        confirmLoading={submitLoading}
        width={600}
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={handleCreate}
        >
          <Form.Item
            name="equipment_id"
            label="Equipment"
            rules={[{ required: true, message: 'Please select equipment' }]}
          >
            <Select placeholder="Select equipment" options={[]} />
          </Form.Item>
          <Form.Item
            name="task_type"
            label="Task Type"
            rules={[{ required: true, message: 'Please select type' }]}
          >
            <Select>
              <Select.Option value="INSPECTION">Inspection</Select.Option>
              <Select.Option value="LUBRICATION">Lubrication</Select.Option>
              <Select.Option value="CALIBRATION">Calibration</Select.Option>
              <Select.Option value="REPLACEMENT">Replacement</Select.Option>
              <Select.Option value="ADJUSTMENT">Adjustment</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="task_name"
            label="Task Name"
            rules={[{ required: true, message: 'Please enter task name' }]}
          >
            <Input placeholder="Enter task name" />
          </Form.Item>
          <Form.Item
            name="description"
            label="Description"
          >
            <TextArea rows={3} placeholder="Enter task description..." />
          </Form.Item>
          <Form.Item
            name="frequency"
            label="Frequency"
            rules={[{ required: true, message: 'Please enter frequency' }]}
          >
            <Input placeholder="e.g., Daily, Weekly, Monthly" />
          </Form.Item>
          <Form.Item
            name="duration_minutes"
            label="Estimated Duration (minutes)"
            rules={[{ required: true, message: 'Please enter duration' }]}
          >
            <Input type="number" min="1" placeholder="30" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="Maintenance Task Detail"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            Close
          </Button>
        ]}
        width={600}
      >
        {selectedTask && (
          <div>
            <p><strong>Equipment:</strong> {selectedTask.equipment_name}</p>
            <p><strong>Task Name:</strong> {selectedTask.task_name}</p>
            <p><strong>Type:</strong> {selectedTask.task_type}</p>
            <p><strong>Description:</strong> {selectedTask.description || '-'}</p>
            <p><strong>Frequency:</strong> {selectedTask.frequency}</p>
            <p><strong>Status:</strong> {selectedTask.status}</p>
            <p><strong>Next Due:</strong> {selectedTask.next_due ? new Date(selectedTask.next_due).toLocaleDateString() : '-'}</p>
            <p><strong>Last Performed:</strong> {selectedTask.last_performed ? new Date(selectedTask.last_performed).toLocaleDateString() : '-'}</p>
            <p><strong>Duration:</strong> {selectedTask.duration_minutes} minutes</p>
            <p><strong>Performed By:</strong> {selectedTask.performed_by || '-'}</p>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default PreventiveMaintenance;
