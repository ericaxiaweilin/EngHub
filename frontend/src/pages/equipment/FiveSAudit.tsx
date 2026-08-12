import React, { useState, useEffect } from 'react';
import { Card, Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Typography, Statistic, Row, Col, Progress, Steps } from 'antd';
import { PlusOutlined, CheckCircleOutlined, ClockCircleOutlined, ExclamationCircleOutlined, TrophyOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';

const { Title, Text } = Typography;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

interface FiveSAudit {
  id: string;
  audit_name: string;
  area: string;
  auditor: string;
  audit_date: string;
  score: number;
  status: string;
  items: Array<{
    category: string;
    item: string;
    score: number;
    notes: string;
  }>;
}

interface FiveSStats {
  total_audits: number;
  average_score: number;
  completed: number;
  pending: number;
  by_category: Record<string, number>;
}

const FiveSAudit: React.FC = () => {
  const [audits, setAudits] = useState<FiveSAudit[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [stats, setStats] = useState<FiveSStats | null>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedAudit, setSelectedAudit] = useState<FiveSAudit | null>(null);
  const [submitLoading, setSubmitLoading] = useState(false);
  
  // Form
  const [createForm] = Form.useForm();
  const [auditItems, setAuditItems] = useState(Array(20).fill({ category: 'Sort', item: '', score: 0, notes: '' }));

  // Fetch audits
  const fetchAudits = async () => {
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
      
      const response = await axios.get(`${API_BASE_URL}/ie/five-s-audits/`, { params });
      setAudits(response.data.audits || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch 5S audits:', error);
      message.error('Failed to load audits');
    } finally {
      setLoading(false);
    }
  };

  // Fetch statistics
  const fetchStats = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/ie/five-s-audits/stats/`);
      setStats(response.data);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  };

  useEffect(() => {
    fetchAudits();
    fetchStats();
  }, [pagination, statusFilter, dateRange]);

  // Handle table change
  const handleTableChange = (pagination: any) => {
    setPagination({ current: pagination.current, pageSize: pagination.pageSize });
  };

  // Handle search
  const handleSearch = () => {
    setPagination({ ...pagination, current: 1 });
    fetchAudits();
  };

  // Handle create
  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      const payload = {
        ...values,
        items: auditItems.filter(item => item.item.trim())
      };
      await axios.post(`${API_BASE_URL}/ie/five-s-audits/`, payload);
      message.success('5S audit created successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      setAuditItems(Array(20).fill({ category: 'Sort', item: '', score: 0, notes: '' }));
      fetchAudits();
      fetchStats();
    } catch (error) {
      console.error('Failed to create audit:', error);
      message.error('Failed to create audit');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Update audit item
  const updateAuditItem = (index: number, field: string, value: any) => {
    const newItems = [...auditItems];
    newItems[index] = { ...newItems[index], [field]: value };
    setAuditItems(newItems);
  };

  // Column definitions
  const columns = [
    {
      title: 'Audit Name',
      dataIndex: 'audit_name',
      key: 'audit_name',
    },
    {
      title: 'Area',
      dataIndex: 'area',
      key: 'area',
      width: 150,
    },
    {
      title: 'Auditor',
      dataIndex: 'auditor',
      key: 'auditor',
      width: 120,
    },
    {
      title: 'Date',
      dataIndex: 'audit_date',
      key: 'audit_date',
      width: 120,
      render: (date: string) => date ? new Date(date).toLocaleDateString() : '-',
    },
    {
      title: 'Score',
      dataIndex: 'score',
      key: 'score',
      width: 100,
      render: (score: number) => (
        <span style={{ color: score >= 80 ? '#52c41a' : score >= 60 ? '#faad14' : '#ff4d4f', fontWeight: 'bold' }}>
          {score}%
        </span>
      ),
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
          'NEEDS_IMPROVEMENT': { label: 'Needs Improvement', color: 'orange' }
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 100,
      render: (_: any, record: FiveSAudit) => (
        <Button 
          type="link" 
          onClick={() => {
            setSelectedAudit(record);
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
      <Title level={3}>5S Audit (5S 审核)</Title>
      <Text type="secondary">Sort, Set in Order, Shine, Standardize, Sustain - Workplace organization audit</Text>

      {/* Statistics */}
      {stats && (
        <Row gutter={16} style={{ marginTop: 16, marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="Total Audits"
                value={stats.total_audits || 0}
                prefix={<ClockCircleOutlined />}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Average Score"
                value={stats.average_score || 0}
                suffix="%"
                prefix={<TrophyOutlined />}
                valueStyle={{ color: (stats.average_score || 0) >= 80 ? '#52c41a' : (stats.average_score || 0) >= 60 ? '#faad14' : '#ff4d4f' }}
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
                title="Pending"
                value={stats.pending || 0}
                prefix={<ExclamationCircleOutlined />}
                valueStyle={{ color: '#faad14' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 5S Categories */}
      <Card title="5S Categories" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          {[
            { name: 'Sort (整理)', desc: 'Remove unnecessary items', color: 'red' },
            { name: 'Set in Order (整顿)', desc: 'Organize necessary items', color: 'orange' },
            { name: 'Shine (清扫)', desc: 'Clean and inspect', color: 'blue' },
            { name: 'Standardize (清洁)', desc: 'Maintain high standards', color: 'green' },
            { name: 'Sustain (素养)', desc: 'Discipline and habit', color: 'purple' }
          ].map((s, index) => (
            <Col span={4} key={index}>
              <Card size="small" style={{ textAlign: 'center' }}>
                <Tag color={s.color} style={{ fontSize: 16, padding: '4px 12px' }}>{s.name}</Tag>
                <div style={{ fontSize: 12, color: '#666', marginTop: 8 }}>{s.desc}</div>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      {/* Filters */}
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Input
          placeholder="Search audits..."
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
          <Select.Option value="NEEDS_IMPROVEMENT">Needs Improvement</Select.Option>
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
          Create Audit
        </Button>
      </div>

      {/* Table */}
      <Table
        columns={columns}
        dataSource={audits}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          total,
          showSizeChanger: true,
          showTotal: (total) => `Total ${total} audits`,
        }}
        onChange={handleTableChange}
      />

      {/* Create Modal */}
      <Modal
        title="Create 5S Audit"
        open={createModalVisible}
        onOk={() => createForm.submit()}
        onCancel={() => {
          setCreateModalVisible(false);
          createForm.resetFields();
        }}
        confirmLoading={submitLoading}
        width={800}
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={handleCreate}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="audit_name"
                label="Audit Name"
                rules={[{ required: true, message: 'Please enter audit name' }]}
              >
                <Input placeholder="e.g., Workshop A Daily 5S" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="area"
                label="Area"
                rules={[{ required: true, message: 'Please select area' }]}
              >
                <Select placeholder="Select area" options={[]} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="auditor"
                label="Auditor"
                rules={[{ required: true, message: 'Please enter auditor name' }]}
              >
                <Input placeholder="Auditor name" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="audit_date"
                label="Audit Date"
                rules={[{ required: true, message: 'Please select date' }]}
              >
                <DatePicker style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item label="Audit Items">
            <Table
              dataSource={auditItems.map((item, index) => ({ ...item, key: index }))}
              pagination={false}
              size="small"
              columns={[
                { title: '#', dataIndex: 'key', width: 50, render: ( _: any, __: any, index: number) => index + 1 },
                { 
                  title: '5S Category', 
                  dataIndex: 'category',
                  width: 120,
                  render: (_: any, __: any, index: number) => (
                    <Select
                      value={auditItems[index].category}
                      onChange={(v) => updateAuditItem(index, 'category', v)}
                      size="small"
                      options={[
                        { label: 'Sort', value: 'Sort' },
                        { label: 'Set in Order', value: 'Set in Order' },
                        { label: 'Shine', value: 'Shine' },
                        { label: 'Standardize', value: 'Standardize' },
                        { label: 'Sustain', value: 'Sustain' }
                      ]}
                    />
                  )
                },
                { 
                  title: 'Item Description', 
                  dataIndex: 'item',
                  render: (_: any, __: any, index: number) => (
                    <Input
                      placeholder="Enter item to check"
                      value={auditItems[index].item}
                      onChange={(e) => updateAuditItem(index, 'item', e.target.value)}
                      size="small"
                    />
                  )
                },
                { 
                  title: 'Score (0-10)', 
                  dataIndex: 'score',
                  width: 100,
                  render: (_: any, __: any, index: number) => (
                    <Input
                      type="number"
                      min="0"
                      max="10"
                      value={auditItems[index].score}
                      onChange={(e) => updateAuditItem(index, 'score', parseInt(e.target.value) || 0)}
                      size="small"
                    />
                  )
                },
                { 
                  title: 'Notes', 
                  dataIndex: 'notes',
                  render: (_: any, __: any, index: number) => (
                    <Input
                      placeholder="Notes"
                      value={auditItems[index].notes}
                      onChange={(e) => updateAuditItem(index, 'notes', e.target.value)}
                      size="small"
                    />
                  )
                }
              ]}
            />
          </Form.Item>

          <Form.Item
            name="overall_notes"
            label="Overall Notes"
          >
            <TextArea rows={3} placeholder="Overall assessment and improvement suggestions..." />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="5S Audit Detail"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            Close
          </Button>
        ]}
        width={800}
      >
        {selectedAudit && (
          <div>
            <Descriptions column={2} bordered>
              <Descriptions.Item label="Audit Name">{selectedAudit.audit_name}</Descriptions.Item>
              <Descriptions.Item label="Area">{selectedAudit.area}</Descriptions.Item>
              <Descriptions.Item label="Auditor">{selectedAudit.auditor}</Descriptions.Item>
              <Descriptions.Item label="Date">
                {selectedAudit.audit_date ? new Date(selectedAudit.audit_date).toLocaleDateString() : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="Overall Score">
                <span style={{ 
                  color: selectedAudit.score >= 80 ? '#52c41a' : selectedAudit.score >= 60 ? '#faad14' : '#ff4d4f',
                  fontWeight: 'bold',
                  fontSize: 18
                }}>
                  {selectedAudit.score}%
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="Status">
                <Tag color={
                  selectedAudit.status === 'COMPLETED' ? 'green' :
                  selectedAudit.status === 'NEEDS_IMPROVEMENT' ? 'orange' :
                  selectedAudit.status === 'IN_PROGRESS' ? 'blue' : 'default'
                }>
                  {selectedAudit.status}
                </Tag>
              </Descriptions.Item>
            </Descriptions>

            <Divider />
            
            <Title level={5}>Audit Items</Title>
            {selectedAudit.items && selectedAudit.items.length > 0 ? (
              <Table
                dataSource={selectedAudit.items}
                rowKey={(record, index) => index}
                pagination={false}
                size="small"
                columns={[
                  { title: 'Category', dataIndex: 'category', key: 'category', width: 120 },
                  { title: 'Item', dataIndex: 'item', key: 'item' },
                  { 
                    title: 'Score', 
                    dataIndex: 'score', 
                    key: 'score',
                    width: 80,
                    render: (score: number) => (
                      <Progress 
                        percent={score * 10} 
                        size="small" 
                        strokeColor={score >= 8 ? '#52c41a' : score >= 5 ? '#faad14' : '#ff4d4f'}
                      />
                    )
                  },
                  { title: 'Notes', dataIndex: 'notes', key: 'notes', render: (v: string) => v || '-' }
                ]}
              />
            ) : (
              <Text type="secondary">No audit items recorded</Text>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
};

export default FiveSAudit;
