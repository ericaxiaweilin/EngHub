import React, { useState, useEffect } from 'react';
import { 
  Form, 
  Input, 
  Select, 
  Button, 
  InputNumber, 
  Space, 
  message,
  Card,
  Typography
} from 'antd';
import { 
  SaveOutlined, 
  ArrowLeftOutlined 
} from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import { redTagApi } from '../../services/modules/qms';
import type { RedTagCreate as RedTagCreatePayload } from '../../services/modules/qms';

const { Title } = Typography;
const { TextArea } = Input;

interface RedTagCreateProps {
  factoryId: string;
  defectId?: string;
  onCreated?: (redTagId: string) => void;
  onCancel?: () => void;
}

const RedTagCreate: React.FC<RedTagCreateProps> = ({ factoryId, defectId, onCreated, onCancel }) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [defects, setDefects] = useState<any[]>([]);

  // Fetch defects for dropdown
  useEffect(() => {
    if (factoryId) {
      fetchDefects();
    }
  }, [factoryId]);

  const fetchDefects = async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/qms/defects/`, {
        params: { factory_id: factoryId, limit: 100, status: 'OPEN' }
      });
      setDefects(response.data.defects || []);
    } catch (error) {
      console.error('Failed to fetch defects:', error);
    }
  };

  const handleSubmit = async (values: any) => {
    setLoading(true);
    try {
      const payload: RedTagCreatePayload = {
        factory_id: factoryId,
        defect_id: values.defect_id || defectId,
        red_tag_type: values.red_tag_type,
        defect_description: values.defect_description,
        nonconforming_qty: values.nonconforming_qty,
        batch_no: values.batch_no,
        severity: values.severity || 'MINOR'
      };

      const response = await redTagApi.create(payload);
      message.success('Red tag created successfully');
      
      if (onCreated) {
        onCreated(response.data.id);
      }
    } catch (error: any) {
      console.error('Failed to create red tag:', error);
      message.error(error.response?.data?.detail || 'Failed to create red tag');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={onCancel}>
          Back
        </Button>
        <Title level={4}>Create Quality Red Tag</Title>
      </Space>

      <Card>
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmit}
          initialValues={{
            severity: 'MINOR',
            nonconforming_qty: 1
          }}
        >
          <Form.Item
            name="defect_id"
            label="Defect"
            rules={[{ required: true, message: 'Please select a defect' }]}
          >
            <Select
              placeholder="Select defect"
              options={defects.map(d => ({
                value: d.id,
                label: `${d.id} - ${d.description?.substring(0, 50)}...`
              }))}
              showSearch
              filterOption={(input, option) =>
                (option?.label ?? '').toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>

          <Form.Item
            name="red_tag_type"
            label="Red Tag Type"
            rules={[{ required: true, message: 'Please select type' }]}
          >
            <Select>
              <Select.Option value="INCOMING">Incoming (IQC)</Select.Option>
              <Select.Option value="IN_PROCESS">In-Process (IPC)</Select.Option>
              <Select.Option value="FINAL">Final (OQC)</Select.Option>
              <Select.Option value="CUSTOMER_RETURN">Customer Return</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="defect_description"
            label="Defect Description"
            rules={[{ required: true, message: 'Please enter description' }]}
          >
            <TextArea rows={4} placeholder="Describe the defect..." />
          </Form.Item>

          <Form.Item
            name="nonconforming_qty"
            label="Non-conforming Quantity"
            rules={[{ required: true, message: 'Please enter quantity' }]}
          >
            <InputNumber min={0} step={0.01} style={{ width: '100%' }} placeholder="0.00" />
          </Form.Item>

          <Form.Item name="batch_no" label="Batch Number">
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

          <Form.Item style={{ marginBottom: 0 }}>
            <Space>
              <Button type="primary" htmlType="submit" loading={loading} icon={<SaveOutlined />}>
                Create Red Tag
              </Button>
              <Button onClick={onCancel}>Cancel</Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
};

export default RedTagCreate;
