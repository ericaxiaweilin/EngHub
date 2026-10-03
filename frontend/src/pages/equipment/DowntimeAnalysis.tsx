import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Typography, Statistic, Row, Col, Progress, Divider, Timeline, Descriptions } from 'antd';
import { PlusOutlined, ThunderboltOutlined, ClockCircleOutlined, WarningOutlined, CheckCircleOutlined, BarChartOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

interface DowntimeRecord {
  id: string;
  equipment_id: string;
  equipment_name: string;
  downtime_start: string;
  downtime_end: string;
  duration_minutes: number;
  reason: string;
  category: string;
  reported_by: string;
  resolved_by: string;
  resolution_notes: string;
  status: string;
}

interface DowntimeStats {
  total_downtime_minutes: number;
  total_records: number;
  by_category: Record<string, number>;
  by_equipment: Array<{ equipment_id: string; equipment_name: string; minutes: number }>;
  top_reasons: Array<{ reason: string; count: number }>;
}

const DowntimeAnalysis: React.FC = () => {
  const [records, setRecords] = useState<DowntimeRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [stats, setStats] = useState<DowntimeStats | null>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedRecord, setSelectedRecord] = useState<DowntimeRecord | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  
  // Form
  const [createForm] = Form.useForm();

  // Fetch downtime records
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
      if (categoryFilter) {
        params.category = categoryFilter;
      }
      if (statusFilter) {
        params.status = statusFilter;
      }
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/api/v1/equipment/downtime/`, { params });
      setRecords(response.data.records || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch downtime records:', error);
      message.error('Failed to load downtime records');
    } finally {
      setLoading(false);
    }
  };

  // Fetch statistics
  const fetchStats = async () => {
    try {
      const params: any = {};
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/api/v1/equipment/downtime/stats/`, { params });
      setStats(response.data);
    } catch (error) {
      console.error('Failed to fetch downtime stats:', error);
    }
  };

  useEffect(() => {
    fetchRecords();
    fetchStats();
  }, [pagination, categoryFilter, statusFilter, dateRange]);

  // Handle table change
  const handleTableChange = (pagination: any) => {
    setPagination({ current: pagination.current, pageSize: pagination.pageSize });
  };

  // Handle search
  const handleSearch = () => {
    setPagination({ ...pagination, current: 1 });
    fetchRecords();
    fetchStats();
  };

  // Handle create
  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/api/v1/equipment/downtime/`, values);
      message.success('Downtime record created successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchRecords();
      fetchStats();
    } catch (error) {
      console.error('Failed to create downtime record:', error);
      message.error('Failed to create downtime record');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Handle resolve
  const handleResolve = async (id: string, resolutionNotes: string) => {
    try {
      await axios.post(`${API_BASE_URL}/api/v1/equipment/downtime/${id}/resolve`, {
        resolution_notes: resolutionNotes
      });
      message.success('Downtime record resolved');
      fetchRecords();
      fetchStats();
    } catch (error) {
      console.error('Failed to resolve downtime:', error);
      message.error('Failed to resolve downtime');
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
      title: 'Start Time',
      dataIndex: 'downtime_start',
      key: 'downtime_start',
      width: 150,
      render: (date: string) => new Date(date).toLocaleString(),
    },
    {
      title: 'End Time',
      dataIndex: 'downtime_end',
      key: 'downtime_end',
      width: 150,
      render: (date: string) => date ? new Date(date).toLocaleString() : '-',
    },
    {
      title: 'Duration',
      dataIndex: 'duration_minutes',
      key: 'duration_minutes',
      width: 100,
      render: (mins: number) => `${mins} min`,
    },
    {
      title: 'Reason',
      dataIndex: 'reason',
      key: 'reason',
      ellipsis: true,
    },
    {
      title: 'Category',
      dataIndex: 'category',
      key: 'category',
      width: 120,
      render: (category: string) => {
        const categoryMap: Record<string, { label: string; color: string }> = {
          'BREAKDOWN': { label: 'Breakdown', color: 'red' },
          'SETUP': { label: 'Setup', color: 'orange' },
          'MAINTENANCE': { label: 'Maintenance', color: 'blue' },
          'MATERIAL': { label: 'Material', color: 'purple' },
          'QUALITY': { label: 'Quality', color: 'cyan' },
          'OTHER': { label: 'Other', color: 'default' }
        };
        const config = categoryMap[category] || { label: category, color: 'default' };
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
          'ACTIVE': { label: 'Active', color: 'red' },
          'RESOLVED': { label: 'Resolved', color: 'green' },
          'SUSPENDED': { label: 'Suspended', color: 'orange' }
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
      title: 'Actions',
      key: 'actions',
      width: 150,
      render: (_: any, record: DowntimeRecord) => (
        <Space>
          <Button 
            type="link" 
            onClick={() => {
              setSelectedRecord(record);
              setDetailModalVisible(true);
            }}
          >
            View
          </Button>
          {record.status === 'ACTIVE' && (
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
      <Title level={3}>Downtime Analysis</Title>
      <Text type="secondary">Track and analyze equipment downtime to improve availability</Text>

      {/* Statistics */}
      {stats && (
        <>
          <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
            <Col span={6}>
              <Card>
                <Statistic
                  title="Total Downtime"
                  value={stats.total_downtime_minutes || 0}
                  suffix="min"
                  prefix={<ClockCircleOutlined />}
                  valueStyle={{ color: '#ff4d4f' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="Total Records"
                  value={stats.total_records || 0}
                  prefix={<ThunderboltOutlined />}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="Breakdowns"
                  value={stats.by_category?.BREAKDOWN || 0}
                  prefix={<WarningOutlined />}
                  valueStyle={{ color: '#ff4d4f' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="Resolved"
                  value={Object.values(stats.by_category || {}).reduce((a: number, b: number) => a + b, 0) - (stats.by_category?.BREAKDOWN || 0)}
                  prefix={<CheckCircleOutlined />}
                  valueStyle={{ color: '#52c41a' }}
                />
              </Card>
            </Col>
          </Row>

          {/* Downtime by Category */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            {Object.entries(stats.by_category || {}).map(([category, minutes]) => (
              <Col span={4} key={category}>
                <Card size="small">
                  <Text strong>{category}</Text>
                  <div style={{ marginTop: 8 }}>
                    <Progress 
                      percent={Math.min(100, (minutes / (stats.total_downtime_minutes || 1)) * 100)} 
                      size="small"
                      strokeColor="#ff4d4f"
                    />
                    <Text type="secondary">{minutes} min</Text>
                  </div>
                </Card>
              </Col>
            ))}
          </Row>

          {/* Top Downtime Equipment */}
          <Card title="Top Downtime Equipment" style={{ marginBottom: 16 }}>
            <Table
              dataSource={(stats.by_equipment || []).slice(0, 5)}
              rowKey="equipment_id"
              pagination={false}
              size="small"
              columns={[
                { title: 'Equipment', dataIndex: 'equipment_name', key: 'equipment_name' },
                { 
                  title: 'Downtime', 
                  dataIndex: 'minutes', 
                  key: 'minutes',
                  render: (mins: number) => `${mins} min`
                }
              ]}
            />
          </Card>
        </>
      )}

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
          placeholder="Category"
          value={categoryFilter}
          onChange={setCategoryFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="BREAKDOWN">Breakdown</Select.Option>
          <Select.Option value="SETUP">Setup</Select.Option>
          <Select.Option value="MAINTENANCE">Maintenance</Select.Option>
          <Select.Option value="MATERIAL">Material</Select.Option>
          <Select.Option value="QUALITY">Quality</Select.Option>
          <Select.Option value="OTHER">Other</Select.Option>
        </Select>
        <Select
          placeholder="Status"
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="ACTIVE">Active</Select.Option>
          <Select.Option value="RESOLVED">Resolved</Select.Option>
          <Select.Option value="SUSPENDED">Suspended</Select.Option>
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
          Report Downtime
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
          showTotal: (total) => `Total ${total} records`,
        }}
        onChange={handleTableChange}
      />

      {/* Create Modal */}
      <Modal
        title="Report Downtime"
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
            name="category"
            label="Category"
            rules={[{ required: true, message: 'Please select category' }]}
          >
            <Select>
              <Select.Option value="BREAKDOWN">Breakdown</Select.Option>
              <Select.Option value="SETUP">Setup</Select.Option>
              <Select.Option value="MAINTENANCE">Maintenance</Select.Option>
              <Select.Option value="MATERIAL">Material</Select.Option>
              <Select.Option value="QUALITY">Quality</Select.Option>
              <Select.Option value="OTHER">Other</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="reason"
            label="Reason"
            rules={[{ required: true, message: 'Please enter reason' }]}
          >
            <TextArea rows={3} placeholder="Describe the downtime reason..." />
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
        title="Downtime Record Detail"
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
              <Descriptions.Item label="Equipment">{selectedRecord.equipment_name}</Descriptions.Item>
              <Descriptions.Item label="Category">
                <Tag color={
                  selectedRecord.category === 'BREAKDOWN' ? 'red' :
                  selectedRecord.category === 'SETUP' ? 'orange' :
                  selectedRecord.category === 'MAINTENANCE' ? 'blue' :
                  selectedRecord.category === 'MATERIAL' ? 'purple' :
                  selectedRecord.category === 'QUALITY' ? 'cyan' : 'default'
                }>
                  {selectedRecord.category}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Reason">{selectedRecord.reason}</Descriptions.Item>
              <Descriptions.Item label="Start Time">
                {new Date(selectedRecord.downtime_start).toLocaleString()}
              </Descriptions.Item>
              <Descriptions.Item label="End Time">
                {selectedRecord.downtime_end ? new Date(selectedRecord.downtime_end).toLocaleString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Duration">
                <Text strong style={{ color: '#ff4d4f' }}>{selectedRecord.duration_minutes} minutes</Text>
              </Descriptions.Item>
              <Descriptions.Item label="Status">
                <Tag color={
                  selectedRecord.status === 'ACTIVE' ? 'red' :
                  selectedRecord.status === 'RESOLVED' ? 'green' : 'orange'
                }>
                  {selectedRecord.status}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="Reported By">{selectedRecord.reported_by}</Descriptions.Item>
              <Descriptions.Item label="Resolved By">{selectedRecord.resolved_by || '-'}</Descriptions.Item>
              <Descriptions.Item label="Resolution Notes">{selectedRecord.resolution_notes || '-'}</Descriptions.Item>
            </Descriptions>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default DowntimeAnalysis;
