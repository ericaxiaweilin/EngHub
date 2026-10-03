import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, Modal, Form, message, Typography, Statistic, Row, Col, Progress } from 'antd';
import { PlusOutlined, EyeOutlined, EditOutlined, DeleteOutlined, ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined, WarningOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import { getActiveFactoryId } from '../../utils/factory';

const { Title, Text } = Typography;
const { TextArea } = Input;

interface Equipment {
  id: string;
  factory_id: string;
  equipment_name: string;
  equipment_type: string;
  model: string;
  serial_number: string;
  location: string;
  status: string;
  oee: number;
  last_maintenance: string;
  next_maintenance: string;
  created_at: string;
}

const EquipmentCenter: React.FC = () => {
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedEquipment, setSelectedEquipment] = useState<Equipment | null>(null);
  
  // Form
  const [statusCounts, setStatusCounts] = useState<Record<string, number>>({});
  const [createForm] = Form.useForm();
  const [submitLoading, setSubmitLoading] = useState(false);

  // Fetch equipment
  const fetchEquipment = async () => {
    setLoading(true);
    try {
      const params: any = {
        factory_id: getActiveFactoryId(),
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
      
      const response = await axios.get(`${API_BASE_URL}/api/v1/equipment/`, { params });
      setEquipment(response.data.equipment || []);
      setTotal(response.data.total || 0);
      setStatusCounts(response.data.status_counts || {});
    } catch (error) {
      console.error('Failed to fetch equipment:', error);
      message.error('Failed to load equipment');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEquipment();
  }, [pagination]);

  // Handle table change
  const handleTableChange = (pagination: any) => {
    setPagination({ current: pagination.current, pageSize: pagination.pageSize });
  };

  // Handle search
  const handleSearch = () => {
    setPagination({ ...pagination, current: 1 });
    fetchEquipment();
  };

  // Handle create
  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/api/v1/equipment/`, { ...values, factory_id: getActiveFactoryId() });
      message.success('Equipment created successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchEquipment();
    } catch (error) {
      console.error('Failed to create equipment:', error);
      message.error('Failed to create equipment');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Column definitions
  const columns = [
    {
      title: 'Equipment Name',
      dataIndex: 'equipment_name',
      key: 'equipment_name',
      width: 150,
    },
    {
      title: 'Type',
      dataIndex: 'equipment_type',
      key: 'equipment_type',
      width: 120,
      render: (type: string) => <Tag>{type}</Tag>
    },
    {
      title: 'Model',
      dataIndex: 'model',
      key: 'model',
      width: 120,
    },
    {
      title: 'Location',
      dataIndex: 'station_id',
      key: 'location',
      width: 120,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        // 状态字典与 equipment 表实际取值一致（running/maintenance/idle/broken）；
        // 原来这里按 OPERATIONAL/DOWN 匹配，页面 KPI 与标签全部落到 default，看着像"0 台在运行"
        const statusMap: Record<string, { label: string; color: string }> = {
          running: { label: '运行中', color: 'green' },
          available: { label: '可开机', color: 'cyan' },
          idle: { label: '待机', color: 'blue' },
          maintenance: { label: '保养中', color: 'orange' },
          broken: { label: '故障', color: 'red' },
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'OEE',
      dataIndex: 'oee',
      key: 'oee',
      width: 100,
      render: (oee: number | null) => (oee == null ? (
        <span style={{ color: '#bfbfbf' }}>-</span>
      ) : (
        <span style={{ color: oee >= 85 ? '#52c41a' : oee >= 70 ? '#faad14' : '#ff4d4f', fontWeight: 'bold' }}>
          {oee}%
        </span>
      )),
    },
    {
      title: 'Next Maintenance',
      dataIndex: 'next_maintenance',
      key: 'next_maintenance',
      width: 120,
      render: (date: string) => date ? new Date(date).toLocaleDateString() : '-',
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 150,
      render: (_: any, record: Equipment) => (
        <Space>
          <Button 
            type="link" 
            icon={<EyeOutlined />} 
            onClick={() => {
              setSelectedEquipment(record);
              setDetailModalVisible(true);
            }}
          >
            View
          </Button>
          <Button type="link" icon={<EditOutlined />}>Edit</Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={3}>Equipment Center</Title>
      <Text type="secondary">Manage all factory equipment and their status</Text>

      {/* Statistics */}
      <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="Total Equipment"
              value={total}
              prefix={<ThunderboltOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Operational"
              value={Object.keys(statusCounts).length
                ? ['running', 'available', 'idle'].reduce((sum, key) => sum + (statusCounts[key] || 0), 0)
                : equipment.filter(e => ['running', 'available', 'idle'].includes(e.status)).length}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Under Maintenance"
              value={statusCounts.maintenance ?? equipment.filter(e => e.status === 'maintenance').length}
              prefix={<WarningOutlined />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Down"
              value={statusCounts.broken ?? equipment.filter(e => e.status === 'broken').length}
              prefix={<CloseCircleOutlined />}
              valueStyle={{ color: '#ff4d4f' }}
            />
          </Card>
        </Col>
      </Row>

      {/* Filters */}
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Input
          placeholder="Search equipment..."
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
          <Select.Option value="machining">机加工</Select.Option>
          <Select.Option value="welding">焊接</Select.Option>
          <Select.Option value="molding">注塑</Select.Option>
          <Select.Option value="assembly">装配</Select.Option>
          <Select.Option value="coating">涂装</Select.Option>
          <Select.Option value="testing">检测</Select.Option>
          <Select.Option value="utility">公用动力</Select.Option>
        </Select>
        <Select
          placeholder="Status"
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="running">运行中</Select.Option>
          <Select.Option value="idle">待机</Select.Option>
          <Select.Option value="maintenance">保养中</Select.Option>
          <Select.Option value="broken">故障</Select.Option>
        </Select>
        <Button type="primary" onClick={handleSearch}>
          Search
        </Button>
        <Button onClick={handleSearch}>Reset</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalVisible(true)}>
          Add Equipment
        </Button>
      </div>

      {/* Table */}
      <Table
        columns={columns}
        dataSource={equipment}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          total,
          showSizeChanger: true,
          showTotal: (total) => `Total ${total} equipment`,
        }}
        onChange={handleTableChange}
      />

      {/* Create Modal */}
      <Modal
        title="Add Equipment"
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
            name="equipment_name"
            label="Equipment Name"
            rules={[{ required: true, message: 'Please enter equipment name' }]}
          >
            <Input placeholder="Enter equipment name" />
          </Form.Item>
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
          <Form.Item
            name="model"
            label="Model"
          >
            <Input placeholder="Enter model" />
          </Form.Item>
          <Form.Item
            name="serial_number"
            label="Serial Number"
          >
            <Input placeholder="Enter serial number" />
          </Form.Item>
          <Form.Item
            name="location"
            label="Location"
          >
            <Input placeholder="Enter location" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="Equipment Detail"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            Close
          </Button>
        ]}
        width={600}
      >
        {selectedEquipment && (
          <div>
            <Descriptions column={2} bordered>
              <Descriptions.Item label="Equipment Name">{selectedEquipment.equipment_name}</Descriptions.Item>
              <Descriptions.Item label="Type">{selectedEquipment.equipment_type}</Descriptions.Item>
              <Descriptions.Item label="Model">{selectedEquipment.model}</Descriptions.Item>
              <Descriptions.Item label="Serial Number">{selectedEquipment.serial_number}</Descriptions.Item>
              <Descriptions.Item label="Location">{selectedEquipment.location}</Descriptions.Item>
              <Descriptions.Item label="Status">
                <Tag color={
                  ['running', 'available'].includes(selectedEquipment.status) ? 'green' :
                  selectedEquipment.status === 'maintenance' ? 'orange' :
                  selectedEquipment.status === 'broken' ? 'red' : 'blue'
                }>
                  {selectedEquipment.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="OEE">
                <span style={{ 
                  color: selectedEquipment.oee >= 85 ? '#52c41a' : selectedEquipment.oee >= 70 ? '#faad14' : '#ff4d4f',
                  fontWeight: 'bold'
                }}>
                  {selectedEquipment.oee}%
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="Last Maintenance">
                {selectedEquipment.last_maintenance ? new Date(selectedEquipment.last_maintenance).toLocaleDateString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Next Maintenance">
                {selectedEquipment.next_maintenance ? new Date(selectedEquipment.next_maintenance).toLocaleDateString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Created At">
                {selectedEquipment.created_at ? new Date(selectedEquipment.created_at).toLocaleString() : '-'}
              </Descriptions.Item>
            </Descriptions>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default EquipmentCenter;
