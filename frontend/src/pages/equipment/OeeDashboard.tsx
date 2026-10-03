import React, { useState, useEffect } from 'react';
import { Card, Row, Col, Statistic, Progress, Typography, Table, Tag, DatePicker, Space, Button } from 'antd';
import { ThunderboltOutlined, CheckCircleOutlined, WarningOutlined, ClockCircleOutlined } from '@ant-design/icons';
import axios from 'axios';
import { API_BASE_URL } from '../../config/api';
import dayjs from 'dayjs';
import { getActiveFactoryId } from '../../utils/factory';

const { Title, Text } = Typography;
const { RangePicker } = DatePicker;

interface OEEData {
  overall_oee: number;
  availability: number;
  performance: number;
  quality: number;
  downtime_loss: number;
  speed_loss: number;
  quality_loss: number;
}

interface DowntimeRecord {
  id: string;
  equipment_id: string;
  equipment_name: string;
  downtime_start: string;
  downtime_end: string;
  duration_minutes: number;
  reason: string;
  category: string;
}

const OeeDashboard: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [oeeData, setOeeData] = useState<OEEData | null>(null);
  const [downtimeRecords, setDowntimeRecords] = useState<DowntimeRecord[]>([]);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [factoryId] = useState(getActiveFactoryId());

  // Fetch OEE data
  const fetchOEE = async () => {
    setLoading(true);
    try {
      const params: any = { factory_id: factoryId };
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }

      const response = await axios.get(`${API_BASE_URL}/api/v1/equipment/oee/`, { params });
      setOeeData(response.data);
    } catch (error) {
      console.error('Failed to fetch OEE data:', error);
    } finally {
      setLoading(false);
    }
  };

  // Fetch downtime records
  const fetchDowntime = async () => {
    try {
      const params: any = { factory_id: factoryId, limit: 50 };
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.date_from = dateRange[0].format('YYYY-MM-DD');
        params.date_to = dateRange[1].format('YYYY-MM-DD');
      }

      const response = await axios.get(`${API_BASE_URL}/api/v1/equipment/downtime/`, { params });
      setDowntimeRecords(response.data.records || []);
    } catch (error) {
      console.error('Failed to fetch downtime data:', error);
    }
  };

  useEffect(() => {
    fetchOEE();
    fetchDowntime();
  }, [dateRange, factoryId]);

  // Column definitions for downtime table
  const downtimeColumns = [
    {
      title: 'Equipment',
      dataIndex: 'equipment_name',
      key: 'equipment_name',
    },
    {
      title: 'Start Time',
      dataIndex: 'downtime_start',
      key: 'downtime_start',
      render: (date: string) => new Date(date).toLocaleString(),
    },
    {
      title: 'End Time',
      dataIndex: 'downtime_end',
      key: 'downtime_end',
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
          'OTHER': { label: 'Other', color: 'default' }
        };
        const config = categoryMap[category] || { label: category, color: 'default' };
        return <Tag color={config.color}>{config.label}</Tag>;
      }
    },
  ];

  return (
    <div>
      <Title level={3}>OEE Dashboard - Overall Equipment Effectiveness</Title>
      <Text type="secondary">Track equipment performance through Availability, Performance, and Quality metrics</Text>

      <div style={{ marginBottom: 16, marginTop: 16 }}>
        <Space>
          <RangePicker
            value={dateRange}
            onChange={(dates) => setDateRange(dates as any)}
            placeholder={['Start Date', 'End Date']}
          />
          <Button type="primary" onClick={() => {
            fetchOEE();
            fetchDowntime();
          }}>
            Refresh
          </Button>
        </Space>
      </div>

      {/* OEE Overview Cards */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="Overall OEE"
              value={oeeData?.overall_oee || 0}
              suffix="%"
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: oeeData?.overall_oee && oeeData.overall_oee >= 85 ? '#52c41a' : oeeData?.overall_oee && oeeData.overall_oee >= 70 ? '#faad14' : '#ff4d4f' }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {oeeData?.overall_oee && oeeData.overall_oee >= 85 ? 'World Class' : oeeData?.overall_oee && oeeData.overall_oee >= 70 ? 'Good' : 'Needs Improvement'}
            </Text>
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Availability"
              value={oeeData?.availability || 0}
              suffix="%"
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: (oeeData?.availability || 0) >= 90 ? '#52c41a' : (oeeData?.availability || 0) >= 80 ? '#faad14' : '#ff4d4f' }}
            />
            <Progress
              percent={oeeData?.availability || 0}
              strokeColor={(oeeData?.availability || 0) >= 90 ? '#52c41a' : (oeeData?.availability || 0) >= 80 ? '#faad14' : '#ff4d4f'}
              size="small"
              style={{ marginTop: 8 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Performance"
              value={oeeData?.performance || 0}
              suffix="%"
              prefix={<ClockCircleOutlined />}
              valueStyle={{ color: (oeeData?.performance || 0) >= 90 ? '#52c41a' : (oeeData?.performance || 0) >= 80 ? '#faad14' : '#ff4d4f' }}
            />
            <Progress
              percent={oeeData?.performance || 0}
              strokeColor={(oeeData?.performance || 0) >= 90 ? '#52c41a' : (oeeData?.performance || 0) >= 80 ? '#faad14' : '#ff4d4f'}
              size="small"
              style={{ marginTop: 8 }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="Quality"
              value={oeeData?.quality || 0}
              suffix="%"
              prefix={<WarningOutlined />}
              valueStyle={{ color: (oeeData?.quality || 0) >= 99 ? '#52c41a' : (oeeData?.quality || 0) >= 95 ? '#faad14' : '#ff4d4f' }}
            />
            <Progress
              percent={oeeData?.quality || 0}
              strokeColor={(oeeData?.quality || 0) >= 99 ? '#52c41a' : (oeeData?.quality || 0) >= 95 ? '#faad14' : '#ff4d4f'}
              size="small"
              style={{ marginTop: 8 }}
            />
          </Card>
        </Col>
      </Row>

      {/* Loss Breakdown */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card title="Downtime Loss">
            <Statistic
              value={oeeData?.downtime_loss || 0}
              suffix="%"
              valueStyle={{ color: '#ff4d4f' }}
            />
            <Text type="secondary">Availability loss from breakdowns and setup</Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="Speed Loss">
            <Statistic
              value={oeeData?.speed_loss || 0}
              suffix="%"
              valueStyle={{ color: '#faad14' }}
            />
            <Text type="secondary">Performance loss from idling and minor stops</Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="Quality Loss">
            <Statistic
              value={oeeData?.quality_loss || 0}
              suffix="%"
              valueStyle={{ color: '#1890ff' }}
            />
            <Text type="secondary">Quality loss from defects and scrap</Text>
          </Card>
        </Col>
      </Row>

      {/* Downtime Records */}
      <Card title="Recent Downtime Records" loading={loading}>
        <Table
          columns={downtimeColumns}
          dataSource={downtimeRecords}
          rowKey="id"
          pagination={{ pageSize: 10 }}
        />
      </Card>
    </div>
  );
};

export default OeeDashboard;
