import React, { useState, useEffect } from 'react';
import {
  Card, Row, Col, Select, Button, Table, Spin, Empty, Message, Tabs, Space, Tag, Input,
} from 'antd';
import {
  SyncOutlined, LoadingOutlined, DeleteOutlined, EditOutlined, CopyOutlined,
  VerticalAlignRightOutlined, SearchOutlined, } from '@ant-design/icons';
import BOMTree from './BOMTree';
import api from '../../services/api';

const FACTORY = 'factory-sh-01';

interface BOMModel {
  id: string;
  name: string;
  version: string;
  updated_at: string;
}

interface BOMWorkOrderData {
  version: string;
  work_order_id: string;
  product_name: string;
  tree: any[];
}

const BOMManager: React.FC = () => {
  const [models, setModels] = useState<BOMModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [bomData, setBomData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [syncLoading, setSyncLoading] = useState(false);
  const [workOrder, setWorkOrder] = useState<string>('');
  const [workOrderBOMData, setWorkOrderBOMData] = useState<BOMWorkOrderData | null>(null);
  const [workOrderBOMLoading, setWorkOrderBOMLoading] = useState(false);

  // 加载产品型号列表
  useEffect(() => {
    loadModels();
  }, []);

  const loadModels = async () => {
    setLoading(true);
    try {
      const res = await api.get('/api/v1/bom/models', { params: { factory_id: FACTORY } });
      setModels(res.data || []);
      if (res.data && res.data.length > 0) {
        setSelectedModel(res.data[0].id);
        loadBOM(res.data[0].id);
      }
    } catch (error) {
      console.error('Load models failed:', error);
      Message.error('加载产品型号失败');
    } finally {
      setLoading(false);
    }
  };

  // 加载BOM树形数据
  const loadBOM = async (modelName: string) => {
    setLoading(true);
    try {
      const res = await api.get(`/api/v1/bom/tree/${modelName}`, { params: { factory_id: FACTORY } });
      setBomData(res.data);
    } catch (error) {
      console.error('Load BOM failed:', error);
      Message.error('加载BOM失败');
    } finally {
      setLoading(false);
    }
  };

  // 触发同步
  const triggerSync = async (type: string) => {
    setSyncLoading(true);
    try {
      await api.post('/api/v1/bom/sync', { sync_type: type });
      Message.success(`${type === 'full' ? '全量' : '增量'}同步已触发`);
      loadModels();
      if (selectedModel) {
        loadBOM(selectedModel);
      }
    } catch (error) {
      console.error('Sync failed:', error);
      Message.error('同步失败');
    } finally {
      setSyncLoading(false);
    }
  };

  // 加载工单关联BOM
  const loadWorkOrderBOM = async () => {
    if (!workOrder) return;
    setWorkOrderBOMLoading(true);
    try {
      const res = await api.get(`/api/v1/bom/work-order/${workOrder}`);
      setWorkOrderBOMData({
        version: res.data.version || 'N/A',
        work_order_id: workOrder,
        product_name: res.data.product_name || '',
        tree: res.data.tree || [],
      });
    } catch (error) {
      console.error('Load WO BOM failed:', error);
      Message.error('查询工单BOM失败');
    } finally {
      setWorkOrderBOMLoading(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Card title="BOM 管理中心" bordered={false}>
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Select
              value={selectedModel}
              placeholder="选择产品型号"
              style={{ width: 100 }}
              onChange={setSelectedModel}
              disabled={models.length === 0 || loading}
            >
              {models.map((model) => (
                <Option key={model.id} value={model.id}>
                  {model.name} ({model.version})
                </Option>
              ))}
            </Select>
          </Col>
          <Col span={8}>
            <Button
              type="primary"
              icon={<SyncOutlined />}
              loading={syncLoading}
              onClick={() => triggerSync('incremental')}
              disabled={!selectedModel || loading}
            >
              增量同步
            </Button>
          </Col>
          <Col span={8}>
            <Button
              danger
              icon={<SyncOutlined />}
              loading={syncLoading}
              onClick={() => triggerSync('full')}
              disabled={!selectedModel || loading}
            >
              全量同步
            </Button>
          </Col>
        </Row>

        <Row>
          <Col span={8}>
            <Card size="small" title="同步状态">
              {bomData?.sync_status ? (
                <>
                  <p>最后同步: {bomData.sync_last_update}</p>
                  <p>状态: <Tag color={bomData.sync_status === 'success' ? 'green' : 'orange'}>{bomData.sync_status}</Tag></p>
                  <p>版本号: {bomData.current_version}</p>
                </>
              ) : (
                <Spin />
              )}
            </Card>
          </Col>
          <Col span={16}>
            <Card size="small" title="BOM 概览">
              {bomData ? (
                <div>
                  <p>总项数: {bomData.total_items}</p>
                  <p>层数: {bomData.max_level}</p>
                  <p>产品: {bomData.product_name}</p>
                </div>
              ) : (
                <Select placeholder="请选择产品型号" disabled />
              )}
            </Card>
          </Col>
        </Row>
      </Card>

      <div style={{ marginTop: 16 }}>
        <Tabs defaultActiveKey="1">
          <TabPane tab="产品结构BOM" key="1">
            <Card title="BOM 结构树">
              {loading ? (
                <Spin centerTip="正在加载BOM..." />
              ) : bomData ? (
                <BOMTree data={bomData.bom_tree} />
              ) : (
                <Empty description="请先选择产品型号" />
              )}
            </Card>
          </TabPane>
          <TabPane tab="工单关联BOM" key="2">
            <Card title="工单BOM查询">
              <Row gutter={[8, 8]} style={{ marginBottom: 16 }}>
                <Col span={16}>
                  <Input
                    placeholder="输入工单号 (e.g. WO-2026-xxxx)"
                    value={workOrder}
                    onChange={(e) => setWorkOrder(e.target.value)}
                    onPressEnter={loadWorkOrderBOM}
                  />
                </Col>
                <Col span={8}>
                  <Button type="primary" icon={<SearchOutlined />} onClick={loadWorkOrderBOM} loading={workOrderBOMLoading}>
                    查询
                  </Button>
                </Col>
              </Row>
              {workOrderBOMData && (
                <div>
                  <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                    <Col span={8}>
                      <Card size="small" bordered={false}>
                        <p>工单号</p>
                        <p style={{ fontSize: 18, fontWeight: 'bold' }}>{workOrderBOMData.work_order_id}</p>
                      </Card>
                    </Col>
                    <Col span={8}>
                      <Card size="small" bordered={false}>
                        <p>产品名称</p>
                        <p style={{ fontSize: 14 }}>{workOrderBOMData.product_name}</p>
                      </Card>
                    </Col>
                    <Col span={8}>
                      <Card size="small" bordered={false}>
                        <p>BOM版本</p>
                        <p style={{ fontSize: 14 }}>{workOrderBOMData.version}</p>
                      </Card>
                    </Col>
                  </Row>
                  <BOMTree data={workOrderBOMData.tree} />
                </div>
              )}
              {!workOrderBOMData && !workOrderBOMLoading && !workOrder && (
                <Empty description="请输入工单号后点击查询" />
              )}
            </Card>
          </TabPane>
        </Tabs>
      </div>

      <div style={{ marginTop: 16 }}>
        <Tabs defaultActiveKey="1">
          <TabPane tab="版本对比" key="1">
            <Button type="primary" icon={<CopyOutlined />} onClick={() => window.location.href = '/bom/compare'}>
              进入对比页面
            </Button>
          </TabPane>
          <TabPane tab="物料搜索" key="2">
            <Button type="primary" icon={<VerticalAlignRightOutlined />} onClick={() => window.location.href = '/bom/search'}>
              搜索物料
            </Button>
          </TabPane>
        </Tabs>
      </div>
    </div>
  );
};

export default BOMManager;