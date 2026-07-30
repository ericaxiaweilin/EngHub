import React, { useState } from 'react';
import {
  Card, Row, Col, Select, Button, Table, Spin, Empty, message, Input, Form,
} from 'antd';
import { RightOutlined } from '@ant-design/icons';
import api from '../../services/api';

const { Option } = Select;

interface BOMItem {
  part_number: string;
  name: string;
  quantity: string;
  level: number;
  diff: 'added' | 'removed' | 'changed' | 'same';
}

const BOMCompare: React.FC = () => {
  const [form] = Form.useForm();
  const [models, setModels] = useState<any[]>([]);
  const [compareData, setCompareData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    loadModels();
  }, []);

  const loadModels = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/v1/bom/models');
      setModels(res.data || []);
      if (res.data && res.data.length > 0) {
        form.setFieldsValue({ model: res.data[0].id });
      }
    } catch (error) {
      console.error('Load models failed:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCompare = async () => {
    const values = form.getFieldsValue();
    if (!values.model || !values.a || !values.b) {
      message.error('请填写完整参数');
      return;
    }
    setLoading(true);
    try {
      const res = await api.get('/api/v1/bom/compare', {
        params: {
          model: values.model,
          a: values.a,
          b: values.b,
        },
      });
      setCompareData(res.data);
    } catch (error) {
      console.error('Compare failed:', error);
      message.error('对比失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Card title="BOM 版本对比" bordered={false}>
        <Form form={form} layout="inline" style={{ marginBottom: 16 }}>
          <Form.Item label="产品型号" name="model" rules={[{ required: true }]}>
            <Select
              loading={loading && models.length === 0}
              style={{ width: 200 }}
              onChange={(v) => form.getFieldValue().model = v}
            >
              {models.map((m) => (
                <Option key={m.id} value={m.id}>{m.name}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item label="版本A" name="a" rules={[{ required: true }]}>
            <Input.TextArea placeholder="输入ISO日期时间或版本号" style={{ width: 200 }} />
          </Form.Item>
          <Form.Item label="版本B" name="b" rules={[{ required: true }]}>
            <Input.TextArea placeholder="输入ISO日期时间或版本号" style={{ width: 200 }} />
          </Form.Item>
          <Form.Item>
            <Button type="primary" onClick={handleCompare} loading={loading}>
              开始对比
            </Button>
          </Form.Item>
        </Form>

        {compareData && (
          <Table
            dataSource={compareData.differences?.map((d: any) => ({
              ...d,
              key: d.part_number,
            }))}
            columns={[
              { title: '物料号', dataIndex: 'part_number', key: 'part_number' },
              { title: '名称', dataIndex: 'name', key: 'name' },
              { title: '数量(A)', dataIndex: 'qty_a', key: 'qty_a' },
              { title: '数量(B)', dataIndex: 'qty_b', key: 'qty_b' },
              {
                title: '差异',
                render: (_, record) => (
                  <Tag color={
                    record.diff === 'added' ? 'green' :
                    record.diff === 'removed' ? 'red' :
                    record.diff === 'changed' ? 'orange' : 'gray'
                  }>
                    {record.diff === 'added' ? '新增' :
                     record.diff === 'removed' ? '删除' :
                     record.diff === 'changed' ? '修改' : '相同'}
                  </Tag>
                ),
              },
            ]}
            pagination={{ pageSize: 10 }}
            loading={loading}
          />
        )}

        {!compareData && !loading && models.length > 0 && (
          <Empty description="请选择对比参数后点击开始对比" />
        )}
        {!loading && models.length === 0 && (
          <Spin centerTip="加载中..." />
        )}
      </Card>
    </div>
  );
};

export default BOMCompare;
