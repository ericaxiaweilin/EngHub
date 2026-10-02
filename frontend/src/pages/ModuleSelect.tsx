import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Row, Col } from 'antd'
import {
  ToolOutlined,
  DatabaseOutlined,
  SafetyCertificateOutlined,
  ScheduleOutlined,
  TeamOutlined,
  ExperimentOutlined,
  RobotOutlined,
  CarOutlined,
} from '@ant-design/icons'

const MODULES = [
  { key: 'MES', title: 'MES', desc: '制造执行', icon: <ToolOutlined style={{ fontSize: 36, color: '#1890ff' }} />, path: '/dashboard' },
  { key: 'WMS', title: 'WMS', desc: '仓储管理', icon: <DatabaseOutlined style={{ fontSize: 36, color: '#52c41a' }} />, path: '/inventory' },
  { key: 'QMS', title: 'QMS', desc: '质量管理', icon: <SafetyCertificateOutlined style={{ fontSize: 36, color: '#faad14' }} />, path: '/inspections' },
  { key: 'PP', title: 'PP', desc: '生产计划', icon: <ScheduleOutlined style={{ fontSize: 36, color: '#722ed1' }} />, path: '/plans' },
  { key: 'TPM', title: 'TPM', desc: '设备管理', icon: <ToolOutlined style={{ fontSize: 36, color: '#13c2c2' }} />, path: '/base-data' },
  { key: 'SIM', title: 'SIM', desc: '系统仿真', icon: <ExperimentOutlined style={{ fontSize: 36, color: '#eb2f96' }} />, path: '/simulation' },
  { key: 'HR', title: 'HR', desc: '人员技能', icon: <TeamOutlined style={{ fontSize: 36, color: '#2f54eb' }} />, path: '/skill-matrix' },
  { key: 'TMS', title: 'TMS', desc: '任务管理', icon: <CarOutlined style={{ fontSize: 36, color: '#fa541c' }} />, path: '/tms/approval' },
]

const ModuleSelect: React.FC = () => {
  const navigate = useNavigate()

  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 40,
    }}>
      <h1 style={{ color: '#fff', fontSize: 32, fontWeight: 700, marginBottom: 8 }}>
        EngHub
      </h1>
      <p style={{ color: 'rgba(255,255,255,0.7)', fontSize: 16, marginBottom: 48 }}>
        智能制造执行系统
      </p>
      <Row gutter={[24, 24]} style={{ maxWidth: 900 }}>
        {MODULES.map(m => (
          <Col xs={12} sm={8} md={6} key={m.key}>
            <Card
              hoverable
              onClick={() => navigate(m.path)}
              style={{ borderRadius: 12, textAlign: 'center', height: '100%' }}
              bodyStyle={{ padding: '32px 16px' }}
            >
              <div style={{ marginBottom: 12 }}>{m.icon}</div>
              <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>{m.title}</div>
              <div style={{ fontSize: 13, color: '#888' }}>{m.desc}</div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}

export default ModuleSelect
