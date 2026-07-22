

import { useState, useEffect } from 'react'
import { Card, Select, Button, Row, Col, Statistic, Table, Tag, Progress, Tabs, Timeline, Alert } from 'antd'
import { ThunderboltOutlined, WarningOutlined, CheckCircleOutlined, ClockCircleOutlined } from '@ant-design/icons'
import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE || '/api/v1/sim-factory'

export default function WarRoom() {
  const [scenarios, setScenarios] = useState<any[]>([])
  const [selectedScenario, setSelectedScenario] = useState('enghub-precision-plant')
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    axios.get(`${API_BASE}/scenarios`).then(res => setScenarios(res.data)).catch(console.error)
  }, [])

  const handleRunSimulation = async () => {
    try {
      setLoading(true)
      // 获取场景配置
      const scenarioRes = await axios.get(`${API_BASE}/scenario?scenario_id=${selectedScenario}`)
      const config = scenarioRes.data.config

      // 构造仿真请求
      const requestPayload = {
        horizon_days: 14,
        demand_variability_pct: 0.1,
        overtime_allowed: true,
        seed: 42,
        workshops: config.workshops,
        sections: config.sections,
        routings: config.routings,
        orders: config.orders?.map((o: any) => ({
          order_id: o.order_id,
          product_id: o.product_id,
          quantity: o.quantity,
          release_day: o.release_day,
          due_day: o.due_day,
          priority: o.priority || 'medium',
        })) || [],
      }

      const res = await axios.post(`${API_BASE}/run`, requestPayload)
      setResult(res.data)
    } catch (err: any) {
      console.error('仿真运行失败:', err)
    } finally {
      setLoading(false)
    }
  }

  if (!result) {
    return (
      <Card title="🏭 EngHub v2.5 — 仿真引擎战情室" style={{ minHeight: 400 }}>
        <Row justify="center" align="middle" style={{ height: 300 }}>
          <Col span={12} style={{ textAlign: 'center' }}>
            <ThunderboltOutlined style={{ fontSize: 64, color: '#1890ff' }} />
            <h2 style={{ marginTop: 16 }}>选择工厂场景并运行仿真</h2>
            <Select
              value={selectedScenario}
              onChange={setSelectedScenario}
              style={{ width: 300, marginBottom: 16 }}
              options={scenarios.map(s => ({ label: s.scenario_name, value: s.scenario_id }))}
              placeholder="选择工厂场景..."
            />
            <br />
            <Button type="primary" size="large" icon={<ThunderboltOutlined />} onClick={handleRunSimulation} loading={loading}>
              启动仿真推演
            </Button>
          </Col>
        </Row>
      </Card>
    )
  }

  const { kpis, sections, alerts, orders } = result

  return (
    <div>
      <Card title="🏭 EngHub v2.5 — 仿真引擎战情室">
        {/* KPI 概览 */}
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic title="平均负荷率" value={kpis.avg_load_rate} suffix="%" precision={1} prefix={<ClockCircleOutlined />} />
              <Progress percent={Math.round(kpis.avg_load_rate * 100)} size="small" status={kpis.max_load_rate > 1 ? 'exception' : 'active'} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="最大峰值负荷" value={kpis.max_load_rate} suffix="x" precision={2} prefix={<WarningOutlined />} />
              <Tag color={kpis.max_load_rate > 1 ? 'red' : 'green'}>{kpis.max_load_rate > 1 ? '⚠️ 过载' : '✅ 正常'}</Tag>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="延期订单数" value={kpis.delayed_orders} prefix={<WarningOutlined />} />
              <Tag color={kpis.delayed_orders > 0 ? 'red' : 'green'}>{kpis.delayed_orders > 0 ? '有风险' : '全部按时'}</Tag>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="瓶颈工段数" value={kpis.bottleneck_sections} prefix={<WarningOutlined />} />
              <Tag color={kpis.bottleneck_sections > 0 ? 'orange' : 'green'}>
                {kpis.bottleneck_sections > 0 ? '存在瓶颈' : '无瓶颈'}
              </Tag>
            </Card>
          </Col>
        </Row>

        {/* 工段负荷矩阵 + 告警 */}
        <Tabs defaultActiveKey="sections">
          <Tabs.TabPane tab="工段负荷矩阵" key="sections">
            <Table
              dataSource={sections}
              rowKey="section_id"
              pagination={false}
              size="small"
              scroll={{ x: 1000 }}
              columns={[
                { title: '工段ID', dataIndex: 'section_id', width: 120, fixed: 'left' },
                { title: '名称', dataIndex: 'name', width: 150 },
                { title: '车间', dataIndex: 'workshop_name', width: 120 },
                { title: '策略', dataIndex: 'strategy', width: 80, render: (s: string) => <Tag>{s}</Tag> },
                { title: '人数', dataIndex: 'workers', width: 60 },
                { title: '设备', dataIndex: 'machines', width: 60 },
                { title: '平均负荷率', dataIndex: 'avg_load_rate', width: 100, render: (v: number) => `${(v * 100).toFixed(1)}%` },
                { title: '峰值负荷率', dataIndex: 'peak_load_rate', width: 100, render: (v: number) => <span style={{ color: v > 1 ? 'red' : 'inherit', fontWeight: v > 1 ? 'bold' : 'normal' }}>{(v * 100).toFixed(1)}%</span> },
                { title: '是否瓶颈', dataIndex: 'is_bottleneck', width: 80, render: (v: boolean) => <Tag color={v ? 'red' : 'green'}>{v ? '是' : '否'}</Tag> },
                { title: '计划产出', dataIndex: 'planned_output', width: 80 },
                { title: '实际产出', dataIndex: 'actual_output', width: 80 },
                { title: '在制积压', dataIndex: 'wip_peak', width: 80, render: (v: number) => v > 0 ? <Tag color="orange">{v}</Tag> : '-' },
              ]}
            />
          </Tabs.TabPane>

          <Tabs.TabPane tab="订单甘特图数据" key="orders">
            <Table
              dataSource={orders}
              rowKey="order_id"
              pagination={false}
              size="small"
              columns={[
                { title: '订单ID', dataIndex: 'order_id', width: 180 },
                { title: '产品', dataIndex: 'product_code', width: 120 },
                { title: '数量', dataIndex: 'quantity', width: 80 },
                { title: '优先级', dataIndex: 'priority', width: 80, render: (p: string) => <Tag color={p === 'urgent' ? 'red' : p === 'high' ? 'orange' : 'default'}>{p}</Tag> },
                { title: '预计完工', dataIndex: 'estimated_complete', width: 150 },
                { title: '交期', dataIndex: 'due_date', width: 150 },
                { title: '延迟天数', dataIndex: 'delay_days', width: 80, render: (d: number) => d > 0 ? <Tag color="red">{d}天</Tag> : <CheckCircleOutlined style={{ color: '#52c41a' }} /> },
                { title: '状态', dataIndex: 'status', width: 100 },
              ]}
            />
          </Tabs.TabPane>

          <Tabs.TabPane tab="告警与风险" key="alerts">
            <Alert
              message={`${alerts.length} 条仿真告警`}
              type={kpis.max_load_rate > 1 || kpis.delayed_orders > 0 ? 'error' : 'success'}
              showIcon
              style={{ marginBottom: 16 }}
            />
            <Timeline
              items={(alerts || []).map((a: any) => ({
                key: a.section_id,
                color: a.level === 'critical' ? 'red' : a.level === 'warning' ? 'orange' : 'blue',
                children: (
                  <div>
                    <b>{a.category.toUpperCase()}</b>: {a.message}
                    <br />
                    <small>工段: {a.section_id} | 车间: {a.workshop_id} | 峰值: {(a.peak_load_rate * 100 || 0).toFixed(1)}%</small>
                  </div>
                ),
              }))}
            />
          </Tabs.TabPane>
        </Tabs>
      </Card>
    </div>
  )
}


