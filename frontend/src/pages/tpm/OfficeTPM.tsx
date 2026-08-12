import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Typography, Statistic, Row, Col, Timeline, Progress } from 'antd';
import { PlusOutlined, EyeOutlined, EditOutlined, DeleteOutlined, ToolOutlined, CalendarOutlined, CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined, TrophyOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

interface OfficeTPMItem {
  id: string;
  department: string;
  process_name: string;
  current_time: number;
  target_time: number;
  waste_type: string;
  improvement_action: string;
  status: string;
  owner: string;
  created_at: string;
}

interface OfficeTPMStats {
  total_processes: number;
  avg_improvement: number;
  completed: number;
  in_progress: number;
  by_department: Record<string, number>;
  by_waste_type: Record<string, number>;
}

const OfficeTPM: React.FC = () => {
  const [items, setItems] = useState<OfficeTPMItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [departmentFilter, setDepartmentFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [stats, setStats] = useState<OfficeTPMStats | null>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedItem, setSelectedItem] = useState<OfficeTPMItem | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  
  // Form
  const [createForm] = Form.useForm();

  // Fetch office TPM items
  const fetchItems = async () => {
    setLoading(true);
    try {
      const params: any = {
        limit: pagination.pageSize,
        offset: (pagination.current - 1) * pagination.pageSize
      };
      
      if (searchText) {
        params.search = searchText;
      }
      if (departmentFilter) {
        params.department = departmentFilter;
      }
      if (statusFilter) {
        params.status = statusFilter;
      }
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/tpm/office/`, { params });
      setItems(response.data.items || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch office TPM items:', error);
      message.error('Failed to load office TPM data');
    } finally {
      setLoading(false);
    }
  };

  // Fetch statistics
  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/tpm/office/stats/`);
      setStats(response.data);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  };

  useEffect(() => {
    fetchItems();
    fetchStats();
  }, [pagination, departmentFilter, statusFilter, dateRange]);

  // Handle table change
  const handleTableChange = (pagination: any) => {
    setPagination({ current: pagination.current, pageSize: pagination.pageSize });
  };

  // Handle search
  const handleSearch = () => {
    setPagination({ ...pagination, current: 1 });
    fetchItems();
  };

  // Handle create
  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/tpm/office/`, values);
      message.success('Office TPM improvement item created successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchItems();
      fetchStats();
    } catch (error) {
      console.error('Failed to create office TPM item:', error);
      message.error('Failed to create office TPM item');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Handle complete
  const handleComplete = async (id: string) => {
    try {
      await axios.post(`${API_BASE_URL}/tpm/office/${id}/complete`);
      message.success('Improvement completed');
      fetchItems();
      fetchStats();
    } catch (error) {
      console.error('Failed to complete improvement:', error);
      message.error('Failed to complete improvement');
    }
  };

  // Column definitions
  const columns = [
    {
      title: 'Process',
      dataIndex: 'process_name',
      key: 'process_name',
      width: 200,
    },
    {
      title: 'Department',
      dataIndex: 'department',
      key: 'department',
      width: 120,
      render: (dept: string) => <Tag>{dept}</Tag>
    },
    {
      title: 'Current Time',
      dataIndex: 'current_time',
      key: 'current_time',
      width: 100,
      render: (mins: number) => `${mins} min`,
    },
    {
      title: 'Target Time',
      dataIndex: 'target_time',
      key: 'target_time',
      width: 100,
      render: (mins: number) => `${mins} min`,
    },
    {
      title: 'Improvement',
      key: 'improvement',
      width: 100,
      render: (_: any, record: OfficeTPMItem) => {
        const improvement = ((record.current_time - record.target_time) / record.current_time * 100).toFixed(1);
        return <span style={{ color: '#52c41a', fontWeight: 'bold' }}>{improvement}%</span>;
      }
    },
    {
      title: 'Waste Type',
      dataIndex: 'waste_type',
      key: 'waste_type',
      width: 120,
      render: (type: string) => {
        const wasteMap: Record<string, { label: string; color: string }> = {
          'WAITING': { label: 'Waiting', color: 'orange' },
          'MOVEMENT': { label: 'Movement', color: 'blue' },
          'OVERPROCESSING': { label: 'Overprocessing', color: 'purple' },
          'DEFECTS': { label: 'Defects', color: 'red' },
          'INVENTORY': { label: 'Inventory', color: 'cyan' },
          'TRANSPORT': { label: 'Transport', color: 'green' }
        };
        const config = wasteMap[type] || { label: type, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => {
        const statusMap: Record<string, { label: string; color: string }> = {
          'PENDING': { label: 'Pending', color: 'default' },
          'IN_PROGRESS': { label: 'In Progress', color: 'blue' },
          'COMPLETED': { label: 'Completed', color: 'green' },
          'FAILED': { label: 'Failed', color: 'red' }
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Owner',
      dataIndex: 'owner',
      key: 'owner',
      width: 120,
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 150,
      render: (_: any, record: OfficeTPMItem) => (
        <Space>
          <Button 
            type="link" 
            icon={<EyeOutlined />} 
            onClick={() => {
              setSelectedItem(record);
              setDetailModalVisible(true);
            }}
          >
            View
          </Button>
          {record.status === 'IN_PROGRESS' && (
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
      <Title level={3}>Office TPM - Administrative TPM (事务 TPM)</Title>
      <Text type="secondary">Improve efficiency in administrative and support functions - TPM 8th Pillar</Text>

      {/* Statistics */}
      {stats && (
        <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="Total Processes"
                value={stats.total_processes || 0}
                prefix={<ToolOutlined />}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Avg Improvement"
                value={stats.avg_improvement || 0}
                suffix="%"
                prefix={<TrophyOutlined />}
                valueStyle={{ color: '#52c41a' }}
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
        </Row>
      )}

      {/* 7 Wastes Overview */}
      <Card title="7 Wastes in Office (办公室七大浪费)" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          {[
            { name: 'Waiting (等待)', icon: '⏰', color: 'orange' },
            { name: 'Movement (移动)', icon: '🚶', color: 'blue' },
            { name: 'Overprocessing (过度加工)', icon: '⚙️', color: 'purple' },
            { name: 'Defects (缺陷)', icon: '❌', color: 'red' },
            { name: 'Inventory (库存)', icon: '📦', color: 'cyan' },
            { name: 'Transport (运输)', icon: '🚚', color: 'green' },
            { name: 'Skills (技能浪费)', icon: '👤', color: 'gold' }
          ].map((waste, index) => (
            <Col span={3} key={index}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 24 }}>{waste.icon}</div>
                <div style={{ fontSize: 11, fontWeight: 'bold', marginTop: 4 }}>{waste.name}</div>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      {/* Filters */}
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Input
          placeholder="Search processes..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          onPressEnter={handleSearch}
          style={{ width: 200 }}
        />
        <Select
          placeholder="Department"
          value={departmentFilter}
          onChange={setDepartmentFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="Procurement">Procurement</Select.Option>
          <Select.Option value="HR">HR</Select.Option>
          <Select.Option value="Finance">Finance</Select.Option>
          <Select.Option value="Quality">Quality</Select.Option>
          <Select.Option value="Planning">Planning</Select.Option>
          <Select.Option value="IT">IT</Select.Option>
        </Select>
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
          Add Improvement
        </Button>
      </div>

      {/* Table */}
      <Table
        columns={columns}
        dataSource={items}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          total,
          showSizeChanger: true,
          showTotal: (total) => `Total ${total} items`,
        }}
        onChange={handleTableChange}
      />

      {/* Create Modal */}
      <Modal
        title="Add Office TPM Improvement"
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
                name="department"
                label="Department"
                rules={[{ required: true, message: 'Please select department' }]}
              >
                <Select>
                  <Select.Option value="Procurement">Procurement</Select.Option>
                  <Select.Option value="HR">HR</Select.Option>
                  <Select.Option value="Finance">Finance</Select.Option>
                  <Select.Option value="Quality">Quality</Select.Option>
                  <Select.Option value="Planning">Planning</Select.Option>
                  <Select.Option value="IT">IT</Select.Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="owner"
                label="Owner"
                rules={[{ required: true, message: 'Please enter owner' }]}
              >
                <Input placeholder="Process owner name" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="process_name"
            label="Process Name"
            rules={[{ required: true, message: 'Please enter process name' }]}
          >
            <Input placeholder="e.g., Purchase Order Approval" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="current_time"
                label="Current Processing Time (minutes)"
                rules={[{ required: true, message: 'Please enter current time' }]}
              >
                <Input type="number" min="1" placeholder="60" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="target_time"
                label="Target Processing Time (minutes)"
                rules={[{ required: true, message: 'Please enter target time' }]}
              >
                <Input type="number" min="1" placeholder="30" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name="waste_type"
            label="Waste Type"
            rules={[{ required: true, message: 'Please select waste type' }]}
          >
            <Select>
              <Select.Option value="WAITING">Waiting (等待)</Select.Option>
              <Select.Option value="MOVEMENT">Movement (移动)</Select.Option>
              <Select.Option value="OVERPROCESSING">Overprocessing (过度加工)</Select.Option>
              <Select.Option value="DEFECTS">Defects (缺陷)</Select.Option>
              <Select.Option value="INVENTORY">Inventory (库存)</Select.Option>
              <Select.Option value="TRANSPORT">Transport (运输)</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="improvement_action"
            label="Improvement Action"
            rules={[{ required: true, message: 'Please enter improvement action' }]}
          >
            <TextArea rows={3} placeholder="Describe the improvement action..." />
          </Form.Item>
          <Form.Item
            name="notes"
            label="Notes"
          >
            <TextArea rows={2} placeholder="Additional notes..." />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="Office TPM Improvement Detail"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            Close
          </Button>
        ]}
        width={700}
      >
        {selectedItem && (
          <div>
            <Descriptions column={2} bordered>
              <Descriptions.Item label="Process">{selectedItem.process_name}</Descriptions.Item>
              <Descriptions.Item label="Department">{selectedItem.department}</Descriptions.Item>
              <Descriptions.Item label="Owner">{selectedItem.owner}</Descriptions.Item>
              <Descriptions.Item label="Status">
                <Tag color={
                  selectedItem.status === 'COMPLETED' ? 'green' :
                  selectedItem.status === 'IN_PROGRESS' ? 'blue' :
                  selectedItem.status === 'FAILED' ? 'red' : 'default'
                }>
                  {selectedItem.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Current Time">
                <Space>
                  <span>{selectedItem.current_time} min</span>
                  <Progress 
                    percent={Math.min(100, (selectedItem.current_time / (selectedItem.current_time + 1)) * 100)} 
                    size="small" 
                    status="normal"
                  />
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="Target Time">
                <Space>
                  <span>{selectedItem.target_time} min</span>
                  <Progress 
                    percent={Math.min(100, (selectedItem.target_time / (selectedItem.current_time + 1)) * 100)} 
                    size="small" 
                    status="success"
                  />
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="Improvement">
                <span style={{ color: '#52c41a', fontWeight: 'bold', fontSize: 16 }}>
                  {((selectedItem.current_time - selectedItem.target_time) / selectedItem.current_time * 100).toFixed(1)}%
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="Waste Type">
                <Tag color={
                  selectedItem.waste_type === 'WAITING' ? 'orange' :
                  selectedItem.waste_type === 'DEFECTS' ? 'red' : 'blue'
                }>
                  {selectedItem.waste_type}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Created At">
                {selectedItem.created_at ? new Date(selectedItem.created_at).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Improvement Action" colspan={2}>
                {selectedItem.improvement_action}
              </Descriptions.Item>
              <Descriptions.Item label="Notes" colspan={2}>
                {selectedItem.notes || '-'}
              </Descriptions.Item>
            </Descriptions>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default OfficeTPM;
