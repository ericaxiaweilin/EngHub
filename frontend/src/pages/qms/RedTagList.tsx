import React, { useState, useEffect } from 'react';
import { 
  Table, 
  Button, 
  Tag, 
  Space, 
  Input, 
  Select, 
  DatePicker, 
  Modal, 
  Form, 
  message,
  Popconfirm,
  Descriptions,
  Drawer,
  Upload,
  Image
} from 'antd';
import { 
  PlusOutlined, 
  SearchOutlined, 
  EyeOutlined, 
  EditOutlined, 
  DeleteOutlined,
  ThunderboltOutlined,
  FileImageOutlined
} from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';

const { RangePicker } = DatePicker;
const { TextArea } = Input;

interface RedTag {
  id: string;
  red_tag_no: string;
  defect_id: string;
  red_tag_type: string;
  defect_description: string;
  nonconforming_qty: number;
  severity: string;
  quarantine_status: string;
  disposition: string;
  created_at: string;
  defect?: {
    id: string;
    defect_type: string;
    severity: string;
    description: string;
    status: string;
  };
}

interface RedTagListProps {
  factoryId: string;
  defectId?: string;
}

const RedTagList: React.FC<RedTagListProps> = ({ factoryId, defectId }) => {
  const [redTags, setRedTags] = useState<RedTag[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [searchText, setSearchText] = useState('');
  const [typeFilter, setTypeFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  
  // Modal states
  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailDrawerVisible, setDetailDrawerVisible] = useState(false);
  const [selectedRedTag, setSelectedRedTag] = useState<RedTag | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  
  // Form
  const [createForm] = Form.useForm();
  const [submitLoading, setSubmitLoading] = useState(false);

  // Fetch red tags
  const fetchRedTags = async () => {
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
        params.red_tag_type = typeFilter;
      }
      if (statusFilter) {
        params.quarantine_status = statusFilter;
      }
      if (defectId) {
        params.defect_id = defectId;
      }
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }
      
      const response = await axios.get(`${API_BASE_URL}/qms/red-tags/`, { params });
      setRedTags(response.data.red_tags || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Failed to fetch red tags:', error);
      message.error('Failed to load red tags');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRedTags();
  }, [pagination, factoryId, defectId]);

  // Handle table change
  const handleTableChange = (pagination: any) => {
    setPagination({ current: pagination.current, pageSize: pagination.pageSize });
  };

  // Handle search
  const handleSearch = () => {
    setPagination({ ...pagination, current: 1 });
    fetchRedTags();
  };

  // Handle create
  const handleCreate = async (values: any) => {
    setSubmitLoading(true);
    try {
      await axios.post(`${API_BASE_URL}/qms/red-tags/`, {
        ...values,
        factory_id: factoryId
      });
      message.success('Red tag created successfully');
      setCreateModalVisible(false);
      createForm.resetFields();
      fetchRedTags();
    } catch (error) {
      console.error('Failed to create red tag:', error);
      message.error('Failed to create red tag');
    } finally {
      setSubmitLoading(false);
    }
  };

  // Handle delete
  const handleDelete = async (id: string) => {
    try {
      await axios.delete(`${API_BASE_URL}/qms/red-tags/${id}`);
      message.success('Red tag deleted successfully');
      fetchRedTags();
    } catch (error) {
      console.error('Failed to delete red tag:', error);
      message.error('Failed to delete red tag');
    }
  };

  // Handle view detail
  const handleViewDetail = async (record: RedTag) => {
    setSelectedRedTag(record);
    setDetailDrawerVisible(true);
    setDetailLoading(true);
    
    try {
      const response = await axios.get(`${API_BASE_URL}/qms/red-tags/${record.id}`);
      setSelectedRedTag(response.data);
    } catch (error) {
      console.error('Failed to fetch red tag detail:', error);
      message.error('Failed to load red tag detail');
    } finally {
      setDetailLoading(false);
    }
  };

  // Column definitions
  const columns = [
    {
      title: 'Red Tag No',
      dataIndex: 'red_tag_no',
      key: 'red_tag_no',
      width: 150,
    },
    {
      title: 'Type',
      dataIndex: 'red_tag_type',
      key: 'red_tag_type',
      width: 120,
      render: (type: string) => {
        const typeMap: Record<string, { label: string; color: string }> = {
          'INCOMING': { label: 'Incoming', color: 'blue' },
          'IN_PROCESS': { label: 'In-Process', color: 'orange' },
          'FINAL': { label: 'Final', color: 'green' },
          'CUSTOMER_RETURN': { label: 'Customer Return', color: 'red' }
        };
        const config = typeMap[type] || { label: type, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Description',
      dataIndex: 'defect_description',
      key: 'defect_description',
      ellipsis: true,
    },
    {
      title: 'Qty',
      dataIndex: 'nonconforming_qty',
      key: 'nonconforming_qty',
      width: 80,
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
      title: 'Status',
      dataIndex: 'quarantine_status',
      key: 'quarantine_status',
      width: 120,
      render: (status: string) => {
        const statusMap: Record<string, { label: string; color: string }> = {
          'SEATED': { label: 'Seated', color: 'default' },
          'QUARANTINED': { label: 'Quarantined', color: 'orange' },
          'RELEASED': { label: 'Released', color: 'green' }
        };
        const config = statusMap[status] || { label: status, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
    {
      title: 'Disposition',
      dataIndex: 'disposition',
      key: 'disposition',
      width: 120,
      render: (disposition: string) => {
        if (!disposition) return <span>-</span>;
        const dispositionMap: Record<string, { label: string; color: string }> = {
          'SCRAP': { label: 'Scrap', color: 'red' },
          'REWORK': { label: 'Rework', color: 'orange' },
          'USE_AS_IS': { label: 'Use As Is', color: 'blue' },
          'RTV': { label: 'RTV', color: 'purple' },
          'NO_DEFECT': { label: 'No Defect', color: 'green' }
        };
        const config = dispositionMap[disposition] || { label: disposition, color: 'default' };
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
      width: 150,
      render: (_: any, record: RedTag) => (
        <Space>
          <Button 
            type="link" 
            icon={<EyeOutlined />} 
            onClick={() => handleViewDetail(record)}
          >
            View
          </Button>
          <Popconfirm
            title="Delete this red tag?"
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
          placeholder="Search red tag..."
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
          <Select.Option value="INCOMING">Incoming</Select.Option>
          <Select.Option value="IN_PROCESS">In-Process</Select.Option>
          <Select.Option value="FINAL">Final</Select.Option>
          <Select.Option value="CUSTOMER_RETURN">Customer Return</Select.Option>
        </Select>
        <Select
          placeholder="Status"
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 150 }}
          allowClear
        >
          <Select.Option value="SEATED">Seated</Select.Option>
          <Select.Option value="QUARANTINED">Quarantined</Select.Option>
          <Select.Option value="RELEASED">Released</Select.Option>
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
      </div>

      {/* Table */}
      <Table
        columns={columns}
        dataSource={redTags}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          total,
          showSizeChanger: true,
          showTotal: (total) => `Total ${total} red tags`,
        }}
        onChange={handleTableChange}
      />

      {/* Create Modal */}
      <Modal
        title="Create Quality Red Tag"
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
            name="defect_id"
            label="Defect ID"
            rules={[{ required: true, message: 'Please select a defect' }]}
          >
            <Select
              placeholder="Select defect"
              options={[]} // Would be populated from defects list
            />
          </Form.Item>
          <Form.Item
            name="red_tag_type"
            label="Red Tag Type"
            rules={[{ required: true, message: 'Please select type' }]}
          >
            <Select>
              <Select.Option value="INCOMING">Incoming</Select.Option>
              <Select.Option value="IN_PROCESS">In-Process</Select.Option>
              <Select.Option value="FINAL">Final</Select.Option>
              <Select.Option value="CUSTOMER_RETURN">Customer Return</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item
            name="defect_description"
            label="Defect Description"
            rules={[{ required: true, message: 'Please enter description' }]}
          >
            <TextArea rows={4} placeholder="Enter defect description..." />
          </Form.Item>
          <Form.Item
            name="nonconforming_qty"
            label="Non-conforming Quantity"
            rules={[{ required: true, message: 'Please enter quantity' }]}
          >
            <Input type="number" min="0" step="0.01" placeholder="0.00" />
          </Form.Item>
          <Form.Item
            name="batch_no"
            label="Batch Number"
          >
            <Input placeholder="Enter batch number" />
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
        </Form>
      </Modal>

      {/* Detail Drawer */}
      <Drawer
        title="Red Tag Detail"
        open={detailDrawerVisible}
        onClose={() => setDetailDrawerVisible(false)}
        width={600}
        loading={detailLoading}
      >
        {selectedRedTag && (
          <Descriptions column={1} bordered>
            <Descriptions.Item label="Red Tag No">{selectedRedTag.red_tag_no}</Descriptions.Item>
            <Descriptions.Item label="Type">
              <Tag color={selectedRedTag.red_tag_type === 'INCOMING' ? 'blue' : selectedRedTag.red_tag_type === 'IN_PROCESS' ? 'orange' : selectedRedTag.red_tag_type === 'FINAL' ? 'green' : 'red'}>
                {selectedRedTag.red_tag_type}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Defect ID">{selectedRedTag.defect_id}</Descriptions.Item>
            <Descriptions.Item label="Description">{selectedRedTag.defect_description}</Descriptions.Item>
            <Descriptions.Item label="Quantity">{selectedRedTag.nonconforming_qty}</Descriptions.Item>
            <Descriptions.Item label="Severity">
              <Tag color={selectedRedTag.severity === 'CRITICAL' ? 'red' : selectedRedTag.severity === 'MAJOR' ? 'orange' : 'blue'}>
                {selectedRedTag.severity}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Status">
              <Tag color={selectedRedTag.quarantine_status === 'QUARANTINED' ? 'orange' : selectedRedTag.quarantine_status === 'RELEASED' ? 'green' : 'default'}>
                {selectedRedTag.quarantine_status}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Disposition">
              {selectedRedTag.disposition ? (
                <Tag color={
                  selectedRedTag.disposition === 'SCRAP' ? 'red' :
                  selectedRedTag.disposition === 'REWORK' ? 'orange' :
                  selectedRedTag.disposition === 'USE_AS_IS' ? 'blue' :
                  selectedRedTag.disposition === 'RTV' ? 'purple' : 'green'
                }>
                  {selectedRedTag.disposition}
                </Tag>
              ) : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="Created At">
              {selectedRedTag.created_at ? new Date(selectedRedTag.created_at).toLocaleString() : '-'}
            </Descriptions.Item>
            {selectedRedTag.defect && (
              <Descriptions.Item label="Defect Info">
                <div>
                  <div>Type: {selectedRedTag.defect.defect_type}</div>
                  <div>Severity: {selectedRedTag.defect.severity}</div>
                  <div>Description: {selectedRedTag.defect.description}</div>
                  <div>Status: {selectedRedTag.defect.status}</div>
                </div>
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Drawer>
    </div>
  );
};

export default RedTagList;
