import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Typography, Statistic, Row, Col, Steps, Upload, Image } from 'antd';
import { PlusOutlined, CheckCircleOutlined, ClockCircleOutlined, CameraOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

interface AutonomousTask {
  id: string;
  equipment_id: string;
  equipment_name: string;
  task_name: string;
  checklist_items: Array<{
    id: string;
    item: string;
    status: string;
    notes?: string;
  }>;
  performed_by: string;
  performed_at: string;
  status: string;
  issues_found: number;
  photos: Array<{
    id: string;
    url: string;
    notes?: string;
  }>;
}

interface CheckItem {
  id: string;
  item: string;
  status: string;
  notes?: string;
}

const AutonomousMaintenance: React.FC = () => {
  const [tasks, setTasks] = useState<AutonomousTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [stats, setStats] = useState<any>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedTask, setSelectedTask] = useState<AutonomousTask | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  
  // Form
  const [createForm] = Form.useForm();
  const [checklist, setChecklist] = useState<CheckItem[]>([
    { id: '1', item: '', status: 'PENDING' },
    { id: '2', item: '', status: 'PENDING' },
    { id: '3', item: '', status: 'PENDING' }
  ]);

  // Fetch autonomous maintenance tasks
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
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/api/v1/equipment/autonomous-maintenance/`, { params });
      setTasks(response.data.tasks || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch autonomous maintenance tasks:', error);
      message.error('Failed to load tasks');
    } finally {
      setLoading(false);
    }
  };

  // Fetch statistics
  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/v1/equipment/autonomous-maintenance/stats/`);
      setStats(response.data);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  };

  useEffect(() => {
    fetchTasks();
    fetchStats();
  }, [pagination, statusFilter, dateRange]);

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
      const payload = {
        ...values,
        checklist_items: checklist.filter(item => item.item.trim()),
        performed_by: values.performed_by
      };
      await axios.post(`${API_BASE_URL}/api/v1/equipment/autonomous-maintenance/`, payload);
      message.success('Autonomous maintenance task created successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      setChecklist([
        { id: '1', item: '', status: 'PENDING' },
        { id: '2', item: '', status: 'PENDING' },
        { id: '3', item: '', status: 'PENDING' }
      ]);
      fetchTasks();
      fetchStats();
    } catch (error) {
      console.error('Failed to create task:', error);
      message.error('Failed to create task');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Add checklist item
  const addChecklistItem = () => {
    const newId = String(Date.now());
    setChecklist([...checklist, { id: newId, item: '', status: 'PENDING' }]);
  };

  // Remove checklist item
  const removeChecklistItem = (id: string) => {
    setChecklist(checklist.filter(item => item.id !== id));
  };

  // Update checklist item
  const updateChecklistItem = (id: string, field: string, value: string) => {
    setChecklist(checklist.map(item => 
      item.id === id ? { ...item, [field]: value } : item
    ));
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
      title: 'Performed By',
      dataIndex: 'performed_by',
      key: 'performed_by',
      width: 120,
    },
    {
      title: 'Date',
      dataIndex: 'performed_at',
      key: 'performed_at',
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
          'ISSUES_FOUND': { label: 'Issues Found', color: 'orange' }
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Issues',
      dataIndex: 'issues_found',
      key: 'issues_found',
      width: 80,
      render: (count: number) => count > 0 ? <Tag color="red">{count}</Tag> : '-',
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 100,
      render: (_: any, record: AutonomousTask) => (
        <Button 
          type="link" 
          onClick={() => {
            setSelectedTask(record);
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
      <Title level={3}>Autonomous Maintenance (自主保全)</Title>
      <Text type="secondary">Operators perform routine cleaning, lubrication, and inspection tasks</Text>

      {/* Statistics */}
      {stats && (
        <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="Total Tasks"
                value={stats.total_tasks || 0}
                prefix={<ClockCircleOutlined />}
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
                title="Issues Found"
                value={stats.issues_found || 0}
                prefix={<ExclamationCircleOutlined />}
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
                valueStyle={{ color: '#1890ff' }}
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
          <Select.Option value="ISSUES_FOUND">Issues Found</Select.Option>
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
        title="Create Autonomous Maintenance Task"
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
            name="equipment_id"
            label="Equipment"
            rules={[{ required: true, message: 'Please select equipment' }]}
          >
            <Select placeholder="Select equipment" options={[]} />
          </Form.Item>
          <Form.Item
            name="task_name"
            label="Task Name"
            rules={[{ required: true, message: 'Please enter task name' }]}
          >
            <Input placeholder="e.g., Daily Inspection" />
          </Form.Item>
          <Form.Item
            name="performed_by"
            label="Performed By"
            rules={[{ required: true, message: 'Please enter operator name' }]}
          >
            <Input placeholder="Operator name" />
          </Form.Item>

          <Form.Item label="Checklist Items">
            {checklist.map((item, index) => (
              <Space key={item.id} style={{ display: 'flex', marginBottom: 8, width: '100%' }}>
                <Input
                  placeholder={`Check item ${index + 1}`}
                  value={item.item}
                  onChange={(e) => updateChecklistItem(item.id, 'item', e.target.value)}
                  style={{ flex: 1 }}
                />
                <Button 
                  type="link" 
                  danger 
                  onClick={() => removeChecklistItem(item.id)}
                  disabled={checklist.length <= 1}
                >
                  Remove
                </Button>
              </Space>
            ))}
            <Button 
              type="dashed" 
              onClick={addChecklistItem}
              style={{ width: '100%', marginTop: 8 }}
            >
              <PlusOutlined /> Add Check Item
            </Button>
          </Form.Item>

          <Form.Item
            name="notes"
            label="Additional Notes"
          >
            <TextArea rows={3} placeholder="Any additional notes..." />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="Autonomous Maintenance Task Detail"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            Close
          </Button>
        ]}
        width={700}
      >
        {selectedTask && (
          <div>
            <Descriptions column={2} bordered>
              <Descriptions.Item label="Equipment">{selectedTask.equipment_name}</Descriptions.Item>
              <Descriptions.Item label="Task">{selectedTask.task_name}</Descriptions.Item>
              <Descriptions.Item label="Performed By">{selectedTask.performed_by}</Descriptions.Item>
              <Descriptions.Item label="Date">
                {selectedTask.performed_at ? new Date(selectedTask.performed_at).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Status">
                <Tag color={
                  selectedTask.status === 'COMPLETED' ? 'green' :
                  selectedTask.status === 'ISSUES_FOUND' ? 'orange' :
                  selectedTask.status === 'IN_PROGRESS' ? 'blue' : 'default'
                }>
                  {selectedTask.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Issues Found">{selectedTask.issues_found}</Descriptions.Item>
            </Descriptions>

            <Divider />
            
            <Title level={5}>Checklist Results</Title>
            {selectedTask.checklist_items && selectedTask.checklist_items.length > 0 ? (
              <Table
                dataSource={selectedTask.checklist_items}
                rowKey="id"
                pagination={false}
                size="small"
                columns={[
                  { title: 'Item', dataIndex: 'item', key: 'item' },
                  { 
                    title: 'Status', 
                    dataIndex: 'status', 
                    key: 'status',
                    render: (status: string) => (
                      <Tag color={status === 'PASS' ? 'green' : status === 'FAIL' ? 'red' : 'default'}>
                        {status}
                      </Tag>
                    )
                  },
                  { title: 'Notes', dataIndex: 'notes', key: 'notes', render: (v: string) => v || '-' }
                ]}
              />
            ) : (
              <Text type="secondary">No checklist items recorded</Text>
            )}

            {selectedTask.photos && selectedTask.photos.length > 0 && (
              <>
                <Divider />
                <Title level={5}>Photos</Title>
                <Space wrap>
                  {selectedTask.photos.map((photo) => (
                    <Image
                      key={photo.id}
                      src={photo.url}
                      alt="Maintenance photo"
                      width={150}
                      style={{ marginBottom: 8 }}
                    />
                  ))}
                </Space>
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
};

export default AutonomousMaintenance;
