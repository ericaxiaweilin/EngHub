import React, { useState, useEffect } from 'react';
import { Table, Button, Tag, Space, Input, Select, DatePicker, Modal, Form, message, Popconfirm, Typography } from 'antd';
import { PlusOutlined, SearchOutlined, EyeOutlined, DeleteOutlined, FileTextOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';
import RedTagList from './RedTagList';

const { RangePicker } = DatePicker;
const { TextArea } = Input;

interface Defect {
  id: string;
  factory_id: string;
  inspection_id?: string;
  defect_type: string;
  severity: string;
  description: string;
  quantity: number;
  status: string;
  created_at: string;
}

interface DefectListProps {
  factoryId?: string;
}

const DefectList: React.FC<DefectListProps> = ({ factoryId: propFactoryId }) => {
  const factoryId = propFactoryId ?? localStorage.getItem('active_factory_id') ?? '';
  const [defects, setDefects] = useState<Defect[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedDefect, setSelectedDefect] = useState<Defect | null>(null);
  const [redTagModalVisible, setRedTagModalVisible] = useState(false);
  
  // Form
  const [createForm] = Form.useForm();
  const [submitLoading, setSubmitLoading] = useState(false);

  // Fetch defects
  const fetchDefects = async () => {
    setLoading(true);
    try {
      const params: any = {
        factory_id: factoryId,
        limit: pagination.pageSize,
        offset: (pagination.current - 1) * pagination.pageSize
      };
      
      if (searchText) {
        params.search = searchText;
      }
      if (typeFilter) {
        params.defect_type = typeFilter;
      }
      if (statusFilter) {
        params.status = statusFilter;
      }
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/qms/defects/`, { params });
      setDefects(response.data.defects || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch defects:', error);
      message.error('Failed to load defects');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDefects();
  }, [pagination, factoryId]);

  // Handle table change
  const handleTableChange = (pagination: any) => {
    setPagination({ current: pagination.current, pageSize: pagination.pageSize });
  };

  // Handle search
  const handleSearch = () => {
    setPagination({ ...pagination, current: 1 });
    fetchDefects();
  };

  // Handle create
  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/qms/defects/`, {
        ...values,
        factory_id: factoryId
      });
      message.success('Defect created successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchDefects();
    } catch (error) {
      console.error('Failed to create defect:', error);
      message.error('Failed to create defect');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Handle delete
  const handleDelete = async (id: string) => {
    try {
      await axios.delete(`${API_BASE_URL}/qms/defects/${id}`);
      message.success('Defect deleted successfully');
      fetchDefects();
    } catch (error) {
      console.error('Failed to delete defect:', error);
      message.error('Failed to delete defect');
    }
  };

  // Handle view detail
  const handleViewDetail = (record: Defect) => {
    setSelectedDefect(record);
    setDetailModalVisible(true);
  };

  // Handle view red tags
  const handleViewRedTags = (defectId: string) => {
    setSelectedDefect(defects.find(d => d.id === defectId) || null);
    setRedTagModalVisible(true);
  };

  // Column definitions
  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 100,
      render: (id: string) => <Typography.Text copyable>{id}</Typography.Text>
    },
    {
      title: 'Type',
      dataIndex: 'defect_type',
      key: 'defect_type',
      width: 120,
      render: (type: string) => {
        const typeMap: Record<string, { label: string; color: string }> = {
          'CRITICAL': { label: 'Critical', color: 'red' },
          'MAJOR': { label: 'Major', color: 'orange' },
          'MINOR': { label: 'Minor', color: 'blue' }
        };
        const config = typeMap[type] || { label: type, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Severity',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
      render: (severity: string) => {
        const severityMap: Record<string, { label: string; color: string }> = {
          'CRITICAL': { label: 'Critical', color: 'red' },
          'MAJOR': { label: 'Major', color: 'orange' },
          'MINOR': { label: 'Minor', color: 'blue' }
        };
        const config = severityMap[severity] || { label: severity, color: 'default' };
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
      title: 'Qty',
      dataIndex: 'quantity',
      key: 'quantity',
      width: 80,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: string) => {
        const statusMap: Record<string, { label: string; color: string }> = {
          'OPEN': { label: 'Open', color: 'blue' },
          'HOLD': { label: 'Hold', color: 'orange' },
          'QUARANTINE': { label: 'Quarantine', color: 'red' },
          'RESOLVED': { label: 'Resolved', color: 'green' },
          'CLOSED': { label: 'Closed', color: 'default' }
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Created At',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (date: string) => date ? new Date(date).toLocaleDateString() : '-',
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 200,
      render: (_: any, record: Defect) => (
        <Space>
          <Button 
            type="link" 
            icon={<EyeOutlined />} 
            onClick={() => handleViewDetail(record)}
          >
            View
          </Button>
          <Button 
            type="link" 
            icon={<FileTextOutlined />} 
            onClick={() => handleViewRedTags(record.id)}
          >
            Red Tags
          </Button>
          <Popconfirm
            title="Delete this defect?"
            onConfirm={() => handleDelete(record.id)}
            okText="Yes"
            cancelText="No"
          >
            <Button type="link" danger icon={<DeleteOutlined />}>
              Delete
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      {/* Filters */}
      <div style={{ marginBottom: 16, display: 'flex', gap: 16, alignItems: 'center' }}>
        <Input
          placeholder="Search defects..."
          prefix={<SearchOutlined />}
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
          <Select.Option value="CRITICAL">Critical</Select.Option>
          <Select.Option value="MAJOR">Major</Select.Option>
          <Select.Option value="MINOR">Minor</Select.Option>
        </Select>
        <Select
          placeholder="Status"
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="OPEN">Open</Select.Option>
          <Select.Option value="HOLD">Hold</Select.Option>
          <Select.Option value="QUARANTINE">Quarantine</Select.Option>
          <Select.Option value="RESOLVED">Resolved</Select.Option>
          <Select.Option value="CLOSED">Closed</Select.Option>
        </Select>
        <RangePicker
          value={dateRange}
          onChange={(dates) => setDateRange(dates as any)}
          placeholder={['Start Date', 'End Date']}
        />
        <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
          Search
        </Button>
        <Button onClick={handleSearch}>Reset</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateModalVisible(true)}>
          Create Defect
        </Button>
      </div>

      {/* Table */}
      <Table
        columns={columns}
        dataSource={defects}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          total,
          showSizeChanger: true,
          showTotal: (total) => `Total ${total} defects`,
        }}
        onChange={handleTableChange}
      />

      {/* Create Modal */}
      <Modal
        title="Create Defect"
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
            name="defect_type"
            label="Defect Type"
            rules={[{ required: true, message: 'Please select type' }]}
          >
            <Select>
              <Select.Option value="CRITICAL">Critical</Select.Option>
              <Select.Option value="MAJOR">Major</Select.Option>
              <Select.Option value="MINOR">Minor</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="severity"
            label="Severity"
            rules={[{ required: true, message: 'Please select severity' }]}
          >
            <Select>
              <Select.Option value="CRITICAL">Critical</Select.Option>
              <Select.Option value="MAJOR">Major</Select.Option>
              <Select.Option value="MINOR">Minor</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="description"
            label="Description"
            rules={[{ required: true, message: 'Please enter description' }]}
          >
            <TextArea rows={4} placeholder="Enter defect description..." />
          </Form.Item>
          <Form.Item
            name="quantity"
            label="Quantity"
            rules={[{ required: true, message: 'Please enter quantity' }]}
          >
            <Input type="number" min="0" step="0.01" placeholder="0.00" />
          </Form.Item>
          <Form.Item name="batch_no" label="Batch Number">
            <Input placeholder="Enter batch number" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Detail Modal */}
      <Modal
        title="Defect Detail"
        open={detailModalVisible}
        onCancel={() => setDetailModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailModalVisible(false)}>
            Close
          </Button>
        ]}
        width={600}
      >
        {selectedDefect && (
          <div>
            <p><strong>ID:</strong> {selectedDefect.id}</p>
            <p><strong>Type:</strong> {selectedDefect.defect_type}</p>
            <p><strong>Severity:</strong> {selectedDefect.severity}</p>
            <p><strong>Description:</strong> {selectedDefect.description}</p>
            <p><strong>Quantity:</strong> {selectedDefect.quantity}</p>
            <p><strong>Status:</strong> {selectedDefect.status}</p>
            <p><strong>Created At:</strong> {new Date(selectedDefect.created_at).toLocaleString()}</p>
          </div>
        )}
      </Modal>

      {/* Red Tag Modal */}
      <Modal
        title={`Red Tags for Defect: ${selectedDefect?.id}`}
        open={redTagModalVisible}
        onCancel={() => setRedTagModalVisible(false)}
        footer={null}
        width={1200}
      >
        {selectedDefect && (
          <RedTagList 
            factoryId={factoryId} 
            defectId={selectedDefect.id}
          />
        )}
      </Modal>
    </div>
  );
};

export default DefectList;
