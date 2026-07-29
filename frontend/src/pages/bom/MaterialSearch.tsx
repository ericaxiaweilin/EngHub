import React, { useState, useEffect } from 'react';
import {
  Card, Table, Button, Spin, Empty, Input, Select, message, Tag,
} from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import api from '../../services/api';

interface MaterialItem {
  part_number: string;
  name: string;
  category: string;
  type: string;
  inventory?: number;
  safety_stock?: number;
}

const MaterialSearch: React.FC = () => {
  const [results, setResults] = useState<MaterialItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modelOptions, setModelOptions] = useState<any[]>([]);
  const [searchParams, setSearchParams] = useState({
    q: '',
    model: '',
    category: '',
    type: '',
  });

  useEffect(() => {
    loadModels();
  }, []);

  const loadModels = async () => {
    try {
      const res = await api.get('/api/v1/bom/models');
      setModelOptions(res.data || []);
    } catch (error) {
      console.error('Load models failed:', error);
    }
  };

  const handleSearch = async () => {
    if (!searchParams.q) {
      message.warn('请输入搜索关键词');
      return;
    }
    setLoading(true);
    try {
      const res = await api.get('/api/v1/bom/search', {
        params: {
          q: searchParams.q,
          model: searchParams.model || undefined,
          category_l1: searchParams.category || undefined,
          component_type: searchParams.type || undefined,
        },
      });
      setResults(res.data?.items || res.data || []);
    } catch (error) {
      console.error('Search failed:', error);
      message.error('搜索失败');
    } finally {
      setLoading(false);
    }
  };

  const handleEnter = (e: any) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Card title="BOM 物料搜索" bordered={false}>
        <div style={{ marginBottom: 16, display: 'flex', gap: 8, alignItems: 'end' }}>
          <Input.Search
            placeholder="输入物料号或名称搜索"
            value={searchParams.q}
            onChange={(e) => setSearchParams((prev) => ({ ...prev, q: e.target.value }))}
            onEnterPressKey={handleEnter}
            onPressButton
            style={{ flex: 1 }}
            allowClear
          />
          <Select
            placeholder="产品型号"
            value={searchParams.model}
            onChange={(v) => setSearchParams((prev) => ({ ...prev, model: v }))}
            style={{ width: 200 }}
          >
            {modelOptions.map((m) => (
              <Option key={m.id} value={m.id}>{m.name}</Option>
            ))}
          </Select>
          <Button type="primary" icon={<SearchOutlined />} onClick={handleSearch}>
            搜索
          </button>
        </div>

        {loading ? (
          <Spin centerTip="正在查询..." />
        ) : results.length > 0 ? (
          <Table
            dataSource={results.map((r) => ({ ...r, key: r.part_number }))}
            columns={[
              { title: '物料号', dataIndex: 'part_number', key: 'part_number' },
              { title: '名称', dataIndex: 'name', key: 'name' },
              { title: '分类', dataIndex: 'category', key: 'category' },
              { title: '类型', dataIndex: 'type', key: 'type' },
              { title: '库存', dataIndex: 'inventory', key: 'inventory' },
              { title: '安全库存', dataIndex: 'safety_stock', key: 'safety_stock' },
            ]}
            pagination={{ pageSize: 10 }}
          />
        ) : !loading && modelOptions.length > 0 ? (
          <Empty description="请输入搜索关键词后点击搜索" />
        ) : (
          <Spin centerTip="加载中..." />
        )}
      </Card>
    </div>
  );
};

export default MaterialSearch;