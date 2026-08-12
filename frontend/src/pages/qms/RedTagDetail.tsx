import React, { useState, useEffect } from 'react';
import { 
  Descriptions, 
  Button, 
  Space, 
  Tag, 
  message,
  Modal,
  Form,
  Input,
  Select,
  Card,
  Typography,
  Divider,
  Alert,
  Steps
} from 'antd';
import { 
  ArrowLeftOutlined, 
  SaveOutlined, 
  ThunderboltOutlined,
  CheckOutlined,
  CloseOutlined
} from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import { redTagApi, RedTag } from '../../services/modules/qms';

const { Title, Text } = Typography;
const { TextArea } = Input;

interface RedTagDetailProps {
  redTagId: string;
  factoryId: string;
  onBack?: () => void;
}

const RedTagDetail: React.FC<RedTagDetailProps> = ({ redTagId, factoryId, onBack }) => {
  const [redTag, setRedTag] = useState<RedTag | null>(null);
  const [loading, setLoading] = useState(false);
  const [dispositionModalVisible, setDispositionModalVisible] = useState(false);
  const [dispositionLoading, setDispositionLoading] = useState(false);
  const [form] = Form.useForm();

  // Fetch red tag details
  useEffect(() => {
    fetchRedTag();
  }, [redTagId]);

  const fetchRedTag = async () => {
    setLoading(true);
    try {
      const response = await redTagApi.get(redTagId);
      setRedTag(response.data);
    } catch (error) {
      console.error('Failed to fetch red tag:', error);
      message.error('Failed to load red tag details');
    } finally {
      setLoading(false);
    }
  };

  // Handle disposition submit
  const handleSubmitDisposition = async (values: any) => {
    setDispositionLoading(true);
    try {
      await redTagApi.submitDisposition(redTagId, {
        disposition: values.disposition,
        disposition_by: values.disposition_by,
        disposition_notes: values.disposition_notes
      });
      message.success('Disposition submitted successfully');
      setDispositionModalVisible(false);
      form.resetFields();
      fetchRedTag();
    } catch (error: any) {
      console.error('Failed to submit disposition:', error);
      message.error(error.response?.data?.detail || 'Failed to submit disposition');
    } finally {
      setDispositionLoading(false);
    }
  };

  // Handle quarantine
  const handleQuarantine = async () => {
    try {
      await redTagApi.update(redTagId, {
        quarantine_status: 'QUARANTINED'
      });
      message.success('Red tag quarantined');
      fetchRedTag();
    } catch (error) {
      console.error('Failed to quarantine:', error);
      message.error('Failed to quarantine red tag');
    }
  };

  // Handle release
  const handleRelease = async () => {
    try {
      await redTagApi.update(redTagId, {
        quarantine_status: 'RELEASED'
      });
      message.success('Red tag released');
      fetchRedTag();
    } catch (error) {
      console.error('Failed to release:', error);
      message.error('Failed to release red tag');
    }
  };

  if (!redTag) {
    return <div>Loading...</div>;
  }

  // Disposition steps
  const dispositionSteps = [
    {
      title: 'Scrap',
      value: 'SCRAP',
      color: 'red',
      description: 'Parts cannot be salvaged and must be discarded'
    },
    {
      title: 'Rework',
      value: 'REWORK',
      color: 'orange',
      description: 'Parts can be repaired using internal resources'
    },
    {
      title: 'Use As Is',
      value: 'USE_AS_IS',
      color: 'blue',
      description: 'Parts are functionally acceptable despite minor defects'
    },
    {
      title: 'RTV',
      value: 'RTV',
      color: 'purple',
      description: 'Parts are returned to supplier for credit or replacement'
    },
    {
      title: 'No Defect',
      value: 'NO_DEFECT',
      color: 'green',
      description: 'Parts actually meet specifications after review'
    }
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={onBack}>
          Back
        </Button>
        <Title level={4}>Red Tag Detail: {redTag.red_tag_no}</Title>
      </Space>

      <Card loading={loading}>
        <Descriptions column={2} bordered>
          <Descriptions.Item label="Red Tag No">
            <Text strong>{redTag.red_tag_no}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="Type">
            <Tag color={
              redTag.red_tag_type === 'INCOMING' ? 'blue' :
              redTag.red_tag_type === 'IN_PROCESS' ? 'orange' :
              redTag.red_tag_type === 'FINAL' ? 'green' : 'red'
            }>
              {redTag.red_tag_type}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Defect ID">
            <Text copyable>{redTag.defect_id}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="Severity">
            <Tag color={
              redTag.severity === 'CRITICAL' ? 'red' :
              redTag.severity === 'MAJOR' ? 'orange' : 'blue'
            }>
              {redTag.severity}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Description">
            {redTag.defect_description || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="Quantity">
            <Text strong>{redTag.nonconforming_qty}</Text>
          </Descriptions.Item>
          <Descriptions.Item label="Batch No">
            {redTag.batch_no || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="Status">
            <Tag color={
              redTag.quarantine_status === 'QUARANTINED' ? 'orange' :
              redTag.quarantine_status === 'RELEASED' ? 'green' : 'default'
            }>
              {redTag.quarantine_status}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Disposition">
            {redTag.disposition ? (
              <Tag color={
                redTag.disposition === 'SCRAP' ? 'red' :
                redTag.disposition === 'REWORK' ? 'orange' :
                redTag.disposition === 'USE_AS_IS' ? 'blue' :
                redTag.disposition === 'RTV' ? 'purple' : 'green'
              }>
                {redTag.disposition}
              </Tag>
            ) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="Disposition By">
            {redTag.disposition_by || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="Created At">
            {redTag.created_at ? new Date(redTag.created_at).toLocaleString() : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="Updated At">
            {redTag.updated_at ? new Date(redTag.updated_at).toLocaleString() : '-'}
          </Descriptions.Item>
        </Descriptions>

        <Divider />

        <Space style={{ marginBottom: 16 }}>
          {redTag.quarantine_status !== 'QUARANTINED' && (
            <Button 
              type="primary" 
              danger 
              icon={<ThunderboltOutlined />}
              onClick={handleQuarantine}
              disabled={redTag.quarantine_status === 'RELEASED'}
            >
              Quarantine
            </Button>
          )}
          {redTag.quarantine_status === 'QUARANTINED' && (
            <Button 
              type="primary" 
              icon={<CheckOutlined />}
              onClick={handleRelease}
            >
              Release
            </Button>
          )}
          <Button 
            type="primary"
            onClick={() => setDispositionModalVisible(true)}
            disabled={redTag.quarantine_status !== 'QUARANTINED'}
          >
            Submit Disposition
          </Button>
        </Space>

        {redTag.disposition && (
          <Alert
            message={`Disposition: ${redTag.disposition}`}
            description={redTag.disposition_notes || 'No notes provided'}
            type="info"
            icon={<CheckOutlined />}
            showIcon
          />
        )}
      </Card>

      {/* Disposition Modal */}
      <Modal
        title="Submit Disposition"
        open={dispositionModalVisible}
        onOk={() => form.submit()}
        onCancel={() => {
          setDispositionModalVisible(false);
          form.resetFields();
        }}
        confirmLoading={dispositionLoading}
        width={600}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSubmitDisposition}
        >
          <Form.Item
            name="disposition"
            label="Disposition Type"
            rules={[{ required: true, message: 'Please select disposition' }]}
          >
            <Select>
              {dispositionSteps.map((step) => (
                <Select.Option key={step.value} value={step.value}>
                  <Space>
                    <Tag color={step.color}>{step.title}</Tag>
                    <Text type="secondary">{step.description}</Text>
                  </Space>
                </Select.Option>
              ))}
            </Select>
          </Form.Item>

          <Form.Item
            name="disposition_by"
            label="Approved By"
            rules={[{ required: true, message: 'Please enter approver name' }]}
          >
            <Input placeholder="Enter approver name" />
          </Form.Item>

          <Form.Item
            name="disposition_notes"
            label="Notes"
          >
            <TextArea rows={4} placeholder="Enter disposition notes..." />
          </Form.Item>
        </Form>

        <Divider />
        
        <Title level={5}>Disposition Process</Title>
        <Steps
          current={dispositionSteps.findIndex(s => s.value === form.getFieldValue('disposition'))}
          items={dispositionSteps.map(step => ({
            title: step.title,
            description: step.description,
            icon: step.value === form.getFieldValue('disposition') ? <CheckOutlined /> : undefined
          }))}
        />
      </Modal>
    </div>
  );
};

export default RedTagDetail;
