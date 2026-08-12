import React from 'react';
import { Tabs, Card, Typography, Row, Col, Statistic, Progress } from 'antd';
import { 
  ThunderboltOutlined, 
  CheckCircleOutlined, 
  ClockCircleOutlined, 
  WarningOutlined,
  ToolOutlined,
  TrophyOutlined,
  BarChartOutlined,
  SettingOutlined
} from '@ant-design/icons';
import OeeDashboard from './OeeDashboard';
import PreventiveMaintenance from './PreventiveMaintenance';
import AutonomousMaintenance from './AutonomousMaintenance';
import FiveSAudit from './FiveSAudit';
import DowntimeAnalysis from './DowntimeAnalysis';

const { Title, Text } = Typography;

interface TPMStats {
  oee: number;
  availability: number;
  performance: number;
  quality: number;
  total_downtime: number;
  pm_compliance: number;
  autonomous_tasks_completed: number;
  five_s_score: number;
}

const TPMDashboard: React.FC = () => {
  const [stats, setStats] = React.useState<TPMStats | null>(null);

  // Mock data for demo
  React.useEffect(() => {
    setStats({
      oee: 78.5,
      availability: 87.5,
      performance: 92.3,
      quality: 97.2,
      total_downtime: 245,
      pm_compliance: 85,
      autonomous_tasks_completed: 156,
      five_s_score: 82
    });
  }, []);

  return (
    <div>
      <Title level={2}>TPM - Total Productive Maintenance</Title>
      <Text type="secondary">Maximize equipment effectiveness through the 8 pillars of TPM</Text>

      {/* TPM 8 Pillars Overview */}
      <Card style={{ marginTop: 16, marginBottom: 16 }}>
        <Title level={4}>TPM 8 Pillars</Title>
        <Row gutter={16}>
          {[
            { name: 'Autonomous Maintenance', icon: <ToolOutlined />, color: '#1890ff', desc: 'Operators perform routine maintenance' },
            { name: 'Planned Maintenance', icon: <ClockCircleOutlined />, color: '#52c41a', desc: 'Schedule preventive maintenance' },
            { name: 'Quality Maintenance', icon: <CheckCircleOutlined />, color: '#722ed1', desc: 'Prevent defects at source' },
            { name: 'Focused Improvement', icon: <TrophyOutlined />, color: '#fa8c16', desc: 'Continuous improvement (Kaizen)' },
            { name: 'Early Equipment Mgmt', icon: <SettingOutlined />, color: '#13c2c2', desc: 'Design for maintainability' },
            { name: 'Training & Education', icon: <BarChartOutlined />, color: '#eb2f96', desc: 'Skill development' },
            { name: 'Safety & Environment', icon: <WarningOutlined />, color: '#ff4d4f', desc: 'Zero accidents' },
            { name: 'Office TPM', icon: <ThunderboltOutlined />, color: '#2f4554', desc: 'Admin efficiency' }
          ].map((pillar, index) => (
            <Col span={3} key={index}>
              <Card size="small" style={{ textAlign: 'center', height: 120 }}>
                <div style={{ fontSize: 24, color: pillar.color }}>{pillar.icon}</div>
                <div style={{ fontSize: 11, fontWeight: 'bold', marginTop: 4 }}>{pillar.name}</div>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>

      {/* Key Metrics */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic
                title="Overall OEE"
                value={stats.oee}
                suffix="%"
                prefix={<ThunderboltOutlined />}
                valueStyle={{ color: stats.oee >= 85 ? '#52c41a' : stats.oee >= 70 ? '#faad14' : '#ff4d4f' }}
              />
              <Progress 
                percent={stats.oee} 
                size="small" 
                status={stats.oee >= 85 ? 'success' : stats.oee >= 70 ? 'normal' : 'exception'}
                style={{ marginTop: 8 }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="Availability"
                value={stats.availability}
                suffix="%"
                prefix={<ClockCircleOutlined />}
                valueStyle={{ color: stats.availability >= 90 ? '#52c41a' : stats.availability >= 80 ? '#faad14' : '#ff4d4f' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="PM Compliance"
                value={stats.pm_compliance}
                suffix="%"
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="5S Score"
                value={stats.five_s_score}
                suffix="%"
                prefix={<TrophyOutlined />}
                valueStyle={{ color: stats.five_s_score >= 80 ? '#52c41a' : '#faad14' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* TPM Sub-modules */}
      <Tabs defaultActiveKey="oee" items={[
        {
          key: 'oee',
          label: 'OEE Dashboard',
          icon: <ThunderboltOutlined />,
          children: <OeeDashboard />
        },
        {
          key: 'preventive',
          label: 'Preventive Maintenance',
          icon: <ClockCircleOutlined />,
          children: <PreventiveMaintenance />
        },
        {
          key: 'autonomous',
          label: 'Autonomous Maintenance',
          icon: <ToolOutlined />,
          children: <AutonomousMaintenance />
        },
        {
          key: 'downtime',
          label: 'Downtime Analysis',
          icon: <WarningOutlined />,
          children: <DowntimeAnalysis />
        },
        {
          key: 'fives',
          label: '5S Audit',
          icon: <TrophyOutlined />,
          children: <FiveSAudit />
        }
      ]} />
    </div>
  );
};

export default TPMDashboard;
