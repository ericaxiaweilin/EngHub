import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Typography, Statistic, Row, Col, Timeline, Progress } from 'antd';
import { PlusOutlined, EyeOutlined, EditOutlined, DeleteOutlined, ToolOutlined, CalendarOutlined, CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

interface MaintenanceOrder {
  id: string;
  equipment_id: string;
  equipment_name: string;
  order_type: string;
  priority: string;
  description: string;
  status: string;
  assigned_to: string;
  created_at: string;
  scheduled_start: string;
  scheduled_end: string;
  actual_start: string;
  actual_end: string;
  duration_hours: number;
  parts_used: Array<{
    part_id: string;
    part_name: string;
    quantity: number;
  }>;
  notes: string;
}

const MaintenanceCenter: React.FC = () => {
  const [orders, setOrders] = useState<MaintenanceOrder[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [stats, setStats] = useState<any>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedOrder, setSelectedOrder] = useState<MaintenanceOrder | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  
  // Form
  const [createForm] = Form.useForm();

  // Fetch maintenance orders
  const fetchOrders = async () => {
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
        params.order_type = typeFilter;
      }
      if (statusFilter) {
        params.status = statusFilter;
      }
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/api/v1/equipment/maintenance-orders/`, { params });
      setOrders(response.data.orders || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch maintenance orders:', error);
      message.error('Failed to load maintenance orders');
    } finally {
      setLoading(false);
    }
  };

  // Fetch statistics
  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/api/v1/equipment/maintenance-orders/stats/`);
      setStats(response.data);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  };

  useEffect(() => {
    fetchOrders();
    fetchStats();
  }, [pagination, typeFilter, statusFilter, dateRange]);

  // Handle table change
  const handleTableChange = (pagination: any) => {
    setPagination({ current: pagination.current, pageSize: pagination.pageSize });
  };

  // Handle search
  const handleSearch = () => {
    setPagination({ ...pagination, current: 1 });
    fetchOrders();
  };

  // Handle create
  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/api/v1/equipment/maintenance-orders/`, values);
      message.success('Maintenance order created successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchOrders();
      fetchStats();
    } catch (error) {
      console.error('Failed to create maintenance order:', error);
      message.error('Failed to create maintenance order');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Handle assign
  const handleAssign = async (id: string, assignedTo: string) => {
    try {
      await axios.post(`${API_BASE_URL}/api/v1/equipment/maintenance-orders/${id}/assign`, {
        assigned_to: assignedTo
      });
      message.success('Order assigned successfully');
      fetchOrders();
    } catch (error) {
      console.error('Failed to assign order:', error);
      message.error('Failed to assign order');
    }
  };

  // Handle start
  const handleStart = async (id: string) => {
    try {
      await axios.post(`${API_BASE_URL}/api/v1/equipment/maintenance-orders/${id}/start`);
      message.success('Maintenance started');
      fetchOrders();
    } catch (error) {
      console.error('Failed to start maintenance:', error);
      message.error('Failed to start maintenance');
    }
  };

  // Handle complete
  const handleComplete = async (id: string) => {
    try {
      await axios.post(`${API_BASE_URL}/api/v1/equipment/maintenance-orders/${id}/complete`);
      message.success('Maintenance completed');
      fetchOrders();
      fetchStats();
    } catch (error) {
      console.error('Failed to complete maintenance:', error);
      message.error('Failed to complete maintenance');
    }
  };

  // Column definitions
  const columns = [
    {
      title: 'Order No',
      dataIndex: 'id',
      key: 'id',
      width: 120,
    },
    {
      title: 'Equipment',
      dataIndex: 'equipment_name',
      key: 'equipment_name',
      width: 150,
    },
    {
      title: 'Type',
      dataIndex: 'order_type',
      key: 'order_type',
      width: 120,
      render: (type: string) => {
        const typeMap: Record<string, { label: string; color: string }> = {
          'PREVENTIVE': { label: 'Preventive', color: 'blue' },
          'CORRECTIVE': { label: 'Corrective', color: 'orange' },
          'EMERGENCY': { label: 'Emergency', color: 'red' },
          'PREDICTIVE': { label: 'Predictive', color: 'purple' }
        };
        const config = typeMap[type] || { label: type, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Priority',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (priority: string) => {
        const priorityMap: Record<string, { label: string; color: string }> = {
          'HIGH': { label: 'High', color: 'red' },
          'MEDIUM': { label: 'Medium', color: 'orange' },
          'LOW': { label: 'Low', color: 'green' }
        };
        const config = priorityMap[priority] || { label: priority, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Description',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => {
        const statusMap: Record<string, { label: string; color: string }> = {
          'PENDING': { label: 'Pending', color: 'default' },
          'ASSIGNED': { label: 'Assigned', color: 'blue' },
          'IN_PROGRESS': { label: 'In Progress', color: 'orange' },
          'COMPLETED': { label: 'Completed', color: 'green' },
          'CLOSED': { label: 'Closed', color: 'success' }
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Assigned To',
      dataIndex: 'assigned_to',
      key: 'assigned_to',
      width: 120,
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
      width: 200,
      render: (_: any, record: MaintenanceOrder) => (
        <Space>
          <Button 
            type="link" 
            icon={<EyeOutlined />} 
            onClick={() => {
              setSelectedOrder(record);
              setDetailModalVisible(true);
            }}
          >
            View
          </Button>
          {record.status === 'PENDING' && (
            <Button 
              type="link" 
              icon={<ToolOutlined />}
              onClick={() => handleAssign(record.id, 'tech-001')}
            >
              Assign
            </Button>
          )}
          {record.status === 'ASSIGNED' && (
            <Button 
              type="link" 
              icon={<CheckCircleOutlined />}
              onClick={() => handleStart(record.id)}
            >
              Start
            </Button>
          )}
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
      <Title level={3}>Maintenance Center</Title>
      <Text type="secondary">Manage equipment maintenance orders and repairs</Text>

      {/* Statistics */}
      {stats && (
        <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="Total Orders"
                value={stats.total_orders || 0}
                prefix={<ToolOutlined />}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="In Progress"
                value={stats.in_progress || 0}
                prefix={<ClockCircleOutlined />}
                valueStyle={{ color: '#faad14' }}
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
                title="MTTR (hours)"
                value={stats.mttr || 0}
                prefix={<CalendarOutlined />}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* Filters */}
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Input
          placeholder="Search orders..."
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
          <Select.Option value="PREVENTIVE">Preventive</Select.Option>
          <Select.Option value="CORRECTIVE">Corrective</Select.Option>
          <Select.Option value="EMERGENCY">Emergency</Select.Option>
          <Select.Option value="PREDICTIVE">Predictive</Select.Option>
        </Select>
        <Select
          placeholder="Status"
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="PENDING">Pending</Select.Option>
          <Select.Option value="ASSIGNED">Assigned</Select.Option>
          <Select.Option value="IN_PROGRESS">In Progress</Select.Option>
          <Select.Option value="COMPLETED">Completed</Select.Option>
          <Select.Option value="CLOSED">Closed</Select.Option>
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
          Create Order
        </Button>
      </div>

      {/* Table */}
      <Table
        columns={columns}
        dataSource={orders}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          total,
          showSizeChanger: true,
          showTotal: (total) => `Total ${total} orders`,
        }}
        onChange={handleTableChange}
      />

      {/* Create Modal */}
      <Modal
        title="Create Maintenance Order"
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
            name="order_type"
            label="Order Type"
            rules={[{ required: true, message: 'Please select type' }]}
          >
            <Select>
              <Select.Option value="PREVENTIVE">Preventive</Select.Option>
              <Select.Option value="CORRECTIVE">Corrective</Select.Option>
              <Select.Option value="EMERGENCY">Emergency</Select.Option>
              <Select.Option value="PREDICTIVE">Predictive</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="priority"
            label="Priority"
            rules={[{ required: true, message: 'Please select priority' }]}
          >
            <Select>
              <Select.Option value="HIGH">High</Select.Option>
              <Select.Option value="MEDIUM">Medium</Select.Option>
              <Select.Option value="LOW">Low</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="description"
            label="Description"
            rules={[{ required: true, message: 'Please enter description' }]}
          >
            <TextArea rows={4} placeholder="Describe the maintenance work..." />
          </Form.Item>
          <Form.Item
            name="scheduled_start"
            label="Scheduled Start"
          >
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="scheduled_end"
            label="Scheduled End"
          >
            <DatePicker showTime style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="Maintenance Order Detail"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            Close
          </Button>
        ]}
        width={700}
      >
        {selectedOrder && (
          <div>
            <Descriptions column={2} bordered>
              <Descriptions.Item label="Order No">{selectedOrder.id}</Descriptions.Item>
              <Descriptions.Item label="Type">
                <Tag color={
                  selectedOrder.order_type === 'PREVENTIVE' ? 'blue' :
                  selectedOrder.order_type === 'CORRECTIVE' ? 'orange' :
                  selectedOrder.order_type === 'EMERGENCY' ? 'red' : 'purple'
                }>
                  {selectedOrder.order_type}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Equipment">{selectedOrder.equipment_name}</Descriptions.Item>
              <Descriptions.Item label="Priority">
                <Tag color={
                  selectedOrder.priority === 'HIGH' ? 'red' :
                  selectedOrder.priority === 'MEDIUM' ? 'orange' : 'green'
                }>
                  {selectedOrder.priority}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Status" colspan={2}>
                <Tag color={
                  selectedOrder.status === 'COMPLETED' ? 'green' :
                  selectedOrder.status === 'IN_PROGRESS' ? 'orange' :
                  selectedOrder.status === 'ASSIGNED' ? 'blue' : 'default'
                }>
                  {selectedOrder.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Assigned To">{selectedOrder.assigned_to || '-'}</Descriptions.Item>
              <Descriptions.Item label="Created At">
                {selectedOrder.created_at ? new Date(selectedOrder.created_at).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Scheduled Start">
                {selectedOrder.scheduled_start ? new Date(selectedOrder.scheduled_start).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Scheduled End">
                {selectedOrder.scheduled_end ? new Date(selectedOrder.scheduled_end).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Actual Start">
                {selectedOrder.actual_start ? new Date(selectedOrder.actual_start).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Actual End">
                {selectedOrder.actual_end ? new Date(selectedOrder.actual_end).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Duration">{selectedOrder.duration_hours ? `${selectedOrder.duration_hours} hours` : '-'}</Descriptions.Item>
              <Descriptions.Item label="Description" colspan={2}>
                {selectedOrder.description}
              </Descriptions.Item>
              <Descriptions.Item label="Notes" colspan={2}>
                {selectedOrder.notes || '-'}
              </Descriptions.Item>
            </Descriptions>

            {selectedOrder.parts_used && selectedOrder.parts_used.length > 0 && (
              <>
                <Divider />
                <Title level={5}>Parts Used</Title>
                <Table
                  dataSource={selectedOrder.parts_used}
                  rowKey="part_id"
                  pagination={false}
                  size="small"
                  columns={[
                    { title: 'Part Name', dataIndex: 'part_name', key: 'part_name' },
                    { title: 'Quantity', dataIndex: 'quantity', key: 'quantity', width: 80 }
                  ]}
                />
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
};

export default MaintenanceCenter;
