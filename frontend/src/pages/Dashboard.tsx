import { Card, Row, Col, Statistic } from 'antd'
import {
  FileTextOutlined,
  CheckCircleOutlined,
  ScheduleOutlined,
  WarningOutlined,
} from '@ant-design/icons'

export default function Dashboard() {
  return (
    <div>
      <h1 style={{ marginBottom: 24 }}>工作台</h1>
      
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="进行中工单"
              value={12}
              prefix={<FileTextOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="今日完工"
              value={28}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="计划完成率"
              value={94.5}
              suffix="%"
              prefix={<ScheduleOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card>
            <Statistic
              title="质量异常"
              value={3}
              prefix={<WarningOutlined />}
              valueStyle={{ color: '#ff4d4f' }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="生产趋势" style={{ height: 400 }}>
            <div style={{ textAlign: 'center', color: '#999', paddingTop: 150 }}>
              图表区域 - 集成 ECharts
            </div>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="待办事项" style={{ height: 400 }}>
            <div style={{ padding: 16 }}>
              <p>• 工单 WO-2024-001 待审核</p>
              <p>• 检验任务 IQC-2024-005 待执行</p>
              <p>• MRP 运算结果待确认</p>
              <p>• 设备维护计划待审批</p>
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
