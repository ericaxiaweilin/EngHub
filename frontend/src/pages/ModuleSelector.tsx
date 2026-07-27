import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Row, Col, Typography, Space, Tag } from 'antd'
import {
  AppstoreOutlined,
  InboxOutlined,
  SafetyOutlined,
  FieldTimeOutlined,
  ToolOutlined,
  ThunderboltOutlined,
  TeamOutlined,
  DashboardOutlined,
  LineChartOutlined,
} from '@ant-design/icons'

const { Title, Text, Paragraph } = Typography

interface ModuleDef {
  key: string
  title: string
  desc: string
  icon: React.ReactNode
  color: string
  path: string
  tag?: string
}

const MODULES: ModuleDef[] = [
  {
    key: 'mes',
    title: 'MES',
    desc: '工单管理 · 报工终端 · 产线看板 · 生产报表',
    icon: <AppstoreOutlined style={{ fontSize: 36 }} />,
    color: '#1890ff',
    path: '/dashboard',
  },
  {
    key: 'wms',
    title: 'WMS',
    desc: '出入库操作 · 库存查询 · 库存预警 · 循环盘点',
    icon: <InboxOutlined style={{ fontSize: 36 }} />,
    color: '#52c41a',
    path: '/wms-terminal',
  },
  {
    key: 'qms',
    title: 'QMS',
    desc: '检验终端 · SPC 控制图 · 不良分析 · 质量目标',
    icon: <SafetyOutlined style={{ fontSize: 36 }} />,
    color: '#faad14',
    path: '/inspection-terminal',
  },
  {
    key: 'pp',
    title: 'PP',
    desc: '销售订单 · APS 排程 · 甘特图 · 产能负荷',
    icon: <FieldTimeOutlined style={{ fontSize: 36 }} />,
    color: '#722ed1',
    path: '/scheduling',
  },
  {
    key: 'equipment',
    title: 'TPM',
    desc: '维保工单 · 点检保养 · OEE 看板 · 故障预测',
    icon: <ToolOutlined style={{ fontSize: 36 }} />,
    color: '#fa8c16',
    path: '/equipment/maintenance',
  },
  {
    key: 'sim',
    title: 'SIM',
    desc: '工厂仿真 · 产能负荷 · 人因合规 · 审计追踪',
    icon: <ThunderboltOutlined style={{ fontSize: 36 }} />,
    color: '#eb2f96',
    path: '/simulation',
  },
  {
    key: 'hr',
    title: 'HR',
    desc: '技能矩阵 · 人员资质 · 培训管理',
    icon: <TeamOutlined style={{ fontSize: 36 }} />,
    color: '#13c2c2',
    path: '/hr-roster',
  },
  {
    key: 'collab',
    title: 'RCC',
    desc: '安灯呼叫 · 作战室 · 任务分发 · 审批',
    icon: <DashboardOutlined style={{ fontSize: 36 }} />,
    color: '#2f54eb',
    path: '/andon',
  },
  {
    key: 'ie',
    title: 'IE',
    desc: '标准工时 · 时间研究 · 线平衡 · 精益指标 · 5S审核',
    icon: <LineChartOutlined style={{ fontSize: 36 }} />,
    color: '#a0d911',
    path: '/ie/standard-times',
  },
]

const ModuleSelector: React.FC = () => {
  const navigate = useNavigate()

  return (
    <div style={{ padding: '40px 24px', maxWidth: 1200, margin: '0 auto' }}>
      <div style={{ textAlign: 'center', marginBottom: 40 }}>
        <Title level={2} style={{ marginBottom: 8 }}>选择业务模块</Title>
        <Paragraph type="secondary" style={{ fontSize: 15 }}>
          EngHub 智能制造执行系统 — 选择要进入的业务域
        </Paragraph>
      </div>

      <Row gutter={[24, 24]}>
        {MODULES.map((mod) => (
          <Col xs={24} sm={12} lg={6} key={mod.key}>
            <Card
              hoverable
              onClick={() => navigate(mod.path)}
              style={{ height: '100%', borderRadius: 8, borderTop: `3px solid ${mod.color}` }}
              bodyStyle={{ padding: 24, textAlign: 'center' }}
            >
              <div style={{ color: mod.color, marginBottom: 16 }}>{mod.icon}</div>
              <Space direction="vertical" size={4}>
                <Space>
                  <Text strong style={{ fontSize: 16 }}>{mod.title}</Text>
                  {mod.tag && <Tag color={mod.color}>{mod.tag}</Tag>}
                </Space>
                <Text type="secondary" style={{ fontSize: 13 }}>{mod.desc}</Text>
              </Space>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}

export default ModuleSelector
