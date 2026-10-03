import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Typography, Statistic, Row, Col, Progress, Descriptions } from 'antd';
import { PlusOutlined, EyeOutlined, EditOutlined, DeleteOutlined, SafetyOutlined, CheckCircleOutlined, ClockCircleOutlined, WarningOutlined, ExclamationCircleOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

interface SafetyRecord {
  id: string;
  hazard_type: string;
  location: string;
  description: string;
  severity: string;
  status: string;
  reported_by: string;
  reported_date: string;
  resolved_by: string;
  resolved_date: string;
  resolution_notes: string;
  photos: string[];
}

interface SafetyStats {
  total_hazards: number;
  open_hazards: number;
  closed_hazards: number;
  accident_rate: number;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
}

const SafetyEnvironment: React.FC = () => {
  const [records, setRecords] = useState<SafetyRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [severityFilter, setSeverityFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [stats, setStats] = useState<SafetyStats | null>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedRecord, setSelectedRecord] = useState<SafetyRecord | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  
  // Form
  const [createForm] = Form.useForm();

  // Fetch safety records
  const fetchRecords = async () => {
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
        params.hazard_type = typeFilter;
      }
      if (severityFilter) {
        params.severity = severityFilter;
      }
      if (statusFilter) {
        params.status = statusFilter;
      }
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/tpm/safety/`, { params });
      setRecords(response.data.records || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch safety records:', error);
      message.error('Failed to load safety records');
    } finally {
      setLoading(false);
    }
  };

  // Fetch statistics
  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/tpm/safety/stats/`);
      setStats(response.data);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  };

  useEffect(() => {
    fetchRecords();
    fetchStats();
  }, [pagination, typeFilter, severityFilter, statusFilter, dateRange]);

  // Handle table change
  const handleTableChange = (pagination: any) => {
    setPagination({ current: pagination.current, pageSize: pagination.pageSize });
  };

  // Handle search
  const handleSearch = () => {
    setPagination({ ...pagination, current: 1 });
    fetchRecords();
  };

  // Handle create
  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/tpm/safety/`, values);
      message.success('Safety hazard reported successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchRecords();
      fetchStats();
    } catch (error) {
      console.error('Failed to create safety record:', error);
      message.error('Failed to report safety hazard');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Handle resolve
  const handleResolve = async (id: string, resolutionNotes: string) => {
    try {
      await axios.post(`${API_BASE_URL}/tpm/safety/${id}/resolve`, {
        resolution_notes: resolutionNotes
      });
      message.success('Hazard resolved');
      fetchRecords();
      fetchStats();
    } catch (error) {
      console.error('Failed to resolve hazard:', error);
      message.error('Failed to resolve hazard');
    }
  };

  // Column definitions
  const columns = [
    {
      title: 'Hazard Type',
      dataIndex: 'hazard_type',
      key: 'hazard_type',
      width: 120,
      render: (type: string) => {
        const typeMap: Record<string, { label: string; color: string }> = {
          'MECHANICAL': { label: 'Mechanical', color: 'orange' },
          'ELECTRICAL': { label: 'Electrical', color: 'red' },
          'CHEMICAL': { label: 'Chemical', color: 'purple' },
          'FALL': { label: 'Fall', color: 'blue' },
          'ERGONOMIC': { label: 'Ergonomic', color: 'cyan' },
          'FIRE': { label: 'Fire', color: 'red' },
          'OTHER': { label: 'Other', color: 'default' }
        };
        const config = typeMap[type] || { label: type, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Location',
      dataIndex: 'location',
      key: 'location',
      width: 150,
    },
    {
      title: 'Description',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: 'Severity',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
      render: (severity: string) => {
        const severityMap: Record<string, { label: string; color: string }> = {
          'CRITICAL': { label: 'Critical', color: 'red' },
          'HIGH': { label: 'High', color: 'orange' },
          'MEDIUM': { label: 'Medium', color: 'yellow' },
          'LOW': { label: 'Low', color: 'green' }
        };
        const config = severityMap[severity] || { label: severity, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const statusMap: Record<string, { label: string; color: string }> = {
          'OPEN': { label: 'Open', color: 'red' },
          'IN_PROGRESS': { label: 'In Progress', color: 'orange' },
          'RESOLVED': { label: 'Resolved', color: 'green' },
          'CLOSED': { label: 'Closed', color: 'default' }
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Reported By',
      dataIndex: 'reported_by',
      key: 'reported_by',
      width: 120,
    },
    {
      title: 'Reported Date',
      dataIndex: 'reported_date',
      key: 'reported_date',
      width: 120,
      render: (date: string) => date ? new Date(date).toLocaleDateString() : '-',
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 150,
      render: (_: any, record: SafetyRecord) => (
        <Space>
          <Button 
            type="link" 
            icon={<EyeOutlined />} 
            onClick={() => {
              setSelectedRecord(record);
              setDetailModalVisible(true);
            }}
          >
            View
          </Button>
          {record.status === 'OPEN' && (
            <Button 
              type="link" 
              icon={<CheckCircleOutlined />}
              onClick={() => {
                const notes = prompt('Enter resolution notes:');
                if (notes) handleResolve(record.id, notes);
              }}
            >
              Resolve
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={3}>Safety, Health & Environment (安全健康环境)</Title>
      <Text type="secondary">TPM 7th Pillar - Zero accidents and safe workplace</Text>

      {/* Statistics */}
      {stats && (
        <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="Total Hazards"
                value={stats.total_hazards || 0}
                prefix={<ExclamationCircleOutlined />}
                valueStyle={{ color: '#ff4d4f' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Open Hazards"
                value={stats.open_hazards || 0}
                prefix={<WarningOutlined />}
                valueStyle={{ color: '#faad14' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Closed Hazards"
                value={stats.closed_hazards || 0}
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Accident Rate"
                value={stats.accident_rate || 0}
                suffix="/1M hrs"
                prefix={<SafetyOutlined />}
                valueStyle={{ color: (stats.accident_rate || 0) < 1 ? '#52c41a' : '#ff4d4f' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* Safety Categories */}
      <Card title="Safety Categories" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          {[
            { name: 'Mechanical', icon: '⚙️', color: 'orange' },
            { name: 'Electrical', icon: '⚡', color: 'red' },
            { name: 'Chemical', icon: '🧪', color: 'purple' },
            { name: 'Fall', icon: '⚠️', color: 'blue' },
            { name: 'Ergonomic', icon: '🪑', color: 'cyan' },
            { name: 'Fire', icon: '🔥', color: 'red' }
          ].map((category, index) => (
            <Col span={4} key={index}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 24 }}>{category.icon}</div>
                <div style={{ fontSize: 11, fontWeight: 'bold', marginTop: 4 }}>{category.name}</div>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      {/* Filters */}
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Input
          placeholder="Search hazards..."
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
          <Select.Option value="MECHANICAL">Mechanical</Select.Option>
          <Select.Option value="ELECTRICAL">Electrical</Select.Option>
          <Select.Option value="CHEMICAL">Chemical</Select.Option>
          <Select.Option value="FALL">Fall</Select.Option>
          <Select.Option value="ERGONOMIC">Ergonomic</Select.Option>
          <Select.Option value="FIRE">Fire</Select.Option>
          <Select.Option value="OTHER">Other</Select.Option>
        </Select>
        <Select
          placeholder="Severity"
          value={severityFilter}
          onChange={setSeverityFilter}
          style={{ width: 120 }}
          allowClear
        >
          <Select.Option value="CRITICAL">Critical</Select.Option>
          <Select.Option value="HIGH">High</Select.Option>
          <Select.Option value="MEDIUM">Medium</Select.Option>
          <Select.Option value="LOW">Low</Select.Option>
        </Select>
        <Select
          placeholder="Status"
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 120 }}
          allowClear
        >
          <Select.Option value="OPEN">Open</Select.Option>
          <Select.Option value="IN_PROGRESS">In Progress</Select.Option>
          <Select.Option value="RESOLVED">Resolved</Select.Option>
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
          Report Hazard
        </Button>
      </div>

      {/* Table */}
      <Table
        columns={columns}
        dataSource={records}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          total,
          showSizeChanger: true,
          showTotal: (total) => `Total ${total} hazards`,
        }}
        onChange={handleTableChange}
      />

      {/* Create Modal */}
      <Modal
        title="Report Safety Hazard"
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
            name="hazard_type"
            label="Hazard Type"
            rules={[{ required: true, message: 'Please select type' }]}
          >
            <Select>
              <Select.Option value="MECHANICAL">Mechanical</Select.Option>
              <Select.Option value="ELECTRICAL">Electrical</Select.Option>
              <Select.Option value="CHEMICAL">Chemical</Select.Option>
              <Select.Option value="FALL">Fall</Select.Option>
              <Select.Option value="ERGONOMIC">Ergonomic</Select.Option>
              <Select.Option value="FIRE">Fire</Select.Option>
              <Select.Option value="OTHER">Other</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="location"
            label="Location"
            rules={[{ required: true, message: 'Please enter location' }]}
          >
            <Input placeholder="e.g., Workshop A - Line 2" />
          </Form.Item>
          <Form.Item
            name="severity"
            label="Severity"
            rules={[{ required: true, message: 'Please select severity' }]}
          >
            <Select>
              <Select.Option value="CRITICAL">Critical</Select.Option>
              <Select.Option value="HIGH">High</Select.Option>
              <Select.Option value="MEDIUM">Medium</Select.Option>
              <Select.Option value="LOW">Low</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="description"
            label="Description"
            rules={[{ required: true, message: 'Please describe the hazard' }]}
          >
            <TextArea rows={4} placeholder="Describe the safety hazard in detail..." />
          </Form.Item>
          <Form.Item
            name="reported_by"
            label="Reported By"
            rules={[{ required: true, message: 'Please enter reporter name' }]}
          >
            <Input placeholder="Your name" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="Safety Hazard Detail"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            Close
          </Button>
        ]}
        width={600}
      >
        {selectedRecord && (
          <div>
            <Descriptions column={1} bordered>
              <Descriptions.Item label="Hazard Type">
                <Tag color={
                  selectedRecord.hazard_type === 'MECHANICAL' ? 'orange' :
                  selectedRecord.hazard_type === 'ELECTRICAL' ? 'red' :
                  selectedRecord.hazard_type === 'CHEMICAL' ? 'purple' : 'blue'
                }>
                  {selectedRecord.hazard_type}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Location">{selectedRecord.location}</Descriptions.Item>
              <Descriptions.Item label="Severity">
                <Tag color={
                  selectedRecord.severity === 'CRITICAL' ? 'red' :
                  selectedRecord.severity === 'HIGH' ? 'orange' :
                  selectedRecord.severity === 'MEDIUM' ? 'yellow' : 'green'
                }>
                  {selectedRecord.severity}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Description">{selectedRecord.description}</Descriptions.Item>
              <Descriptions.Item label="Status">
                <Tag color={
                  selectedRecord.status === 'RESOLVED' ? 'green' :
                  selectedRecord.status === 'IN_PROGRESS' ? 'orange' : 'red'
                }>
                  {selectedRecord.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Reported By">{selectedRecord.reported_by}</Descriptions.Item>
              <Descriptions.Item label="Reported Date">
                {selectedRecord.reported_date ? new Date(selectedRecord.reported_date).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Resolved By">{selectedRecord.resolved_by || '-'}</Descriptions.Item>
              <Descriptions.Item label="Resolved Date">
                {selectedRecord.resolved_date ? new Date(selectedRecord.resolved_date).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Resolution Notes">
                {selectedRecord.resolution_notes || '-'}
              </Descriptions.Item>
            </Descriptions>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default SafetyEnvironment;
