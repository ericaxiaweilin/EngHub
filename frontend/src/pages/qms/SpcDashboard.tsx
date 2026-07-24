import React, { useState, useEffect } from 'react'
import {
  Card, Select, Space, Tag, Typography, Row, Col, Statistic, Table,
  Button, message, Empty, InputNumber,
} from 'antd'
import {
  LineChartOutlined, AimOutlined, WarningOutlined, PlusOutlined,
} from '@ant-design/icons'
import api from '../../services/api'

const { Title, Text } = Typography
const FACTORY = 'F001'

const SpcDashboard: React.FC = () => {
  const [characteristics, setCharacteristics] = useState<any[]>([])
  const [selected, setSelected] = useState<string>('')
  const [chartData, setChartData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [measureValue, setMeasureValue] = useState<number | null>(null)

  const loadCharacteristics = async () => {
    try {
      const res: any = await api.get('/api/v1/qms/spc/characteristics', { params: { factory_id: FACTORY } })
      setCharacteristics(res?.items || [])
      if (res?.items?.length && !selected) setSelected(res.items[0].characteristic_code)
    } catch { /* ignore */ }
  }

  const loadChart = async (code: string) => {
    if (!code) return
    setLoading(true)
    try {
      const res: any = await api.get('/api/v1/qms/spc/chart', { params: { factory_id: FACTORY, characteristic_code: code } })
      setChartData(res)
    } catch { setChartData(null) } finally { setLoading(false) }
  }

  useEffect(() => { loadCharacteristics() }, [])
  useEffect(() => { if (selected) loadChart(selected) }, [selected])

  const handleMeasure = async () => {
    if (measureValue === null || !selected) return
    try {
      const res: any = await api.post('/api/v1/qms/spc/measure', {
        factory_id: FACTORY, characteristic_code: selected, measured_value: measureValue,
      })
      if (res.is_out_of_control) {
        message.warning('⚠️ 超出控制限！过程失控')
      } else {
        message.success('记录成功，过程受控')
      }
      setMeasureValue(null)
      loadChart(selected)
    } catch (e: any) {
      message.error('记录失败')
    }
  }

  const points = chartData?.points || []
  const cpk = chartData?.cpk
  const cpkColor = cpk === null ? '#999' : cpk >= 1.33 ? '#52c41a' : cpk >= 1.0 ? '#faad14' : '#f5222d'

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <Space>
            <LineChartOutlined style={{ fontSize: 22, color: '#1890ff' }} />
            <Title level={4} style={{ margin: 0 }}>SPC 控制图</Title>
          </Space>
        </Col>
        <Col>
          <Space>
            <Select
              value={selected || undefined}
              onChange={setSelected}
              placeholder="选择质量特性"
              style={{ width: 220 }}
              options={characteristics.map(c => ({ value: c.characteristic_code, label: `${c.characteristic_code} ${c.characteristic_name || ''}` }))}
            />
            <InputNumber
              value={measureValue}
              onChange={v => setMeasureValue(v)}
              placeholder="测量值"
              style={{ width: 120 }}
            />
            <Button type="primary" icon={<PlusOutlined />} onClick={handleMeasure} disabled={!selected}>
              记录
            </Button>
          </Space>
        </Col>
      </Row>

      {/* KPI 卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="Cpk 过程能力" value={cpk ?? '—'} valueStyle={{ color: cpkColor }} prefix={<AimOutlined />} />
            <Text type="secondary" style={{ fontSize: 12 }}>{cpk >= 1.33 ? '能力充足' : cpk >= 1.0 ? '能力一般' : '能力不足'}</Text>
          </Card>
        </Col>
        <Col span={6}><Card size="small"><Statistic title="数据点" value={chartData?.total_points || 0} /></Card></Col>
        <Col span={6}><Card size="small"><Statistic title="失控点" value={chartData?.ooc_count || 0} valueStyle={{ color: (chartData?.ooc_count || 0) > 0 ? '#f5222d' : '#52c41a' }} prefix={<WarningOutlined />} /></Card></Col>
        <Col span={6}>
          <Card size="small">
            <Space direction="vertical" size={0}>
              <Text type="secondary">控制限</Text>
              <Text>UCL: {chartData?.ucl ?? '—'} | CL: {chartData?.cl ?? '—'} | LCL: {chartData?.lcl ?? '—'}</Text>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 控制图（简化表格展示） */}
      <Card title={<Space><LineChartOutlined /> {chartData?.characteristic_name || selected} 控制图</Space>} loading={loading}>
        {points.length === 0 ? (
          <Empty description="暂无数据，请录入测量值" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div>
            {/* 简易控制图可视化 */}
            <div style={{ position: 'relative', height: 200, border: '1px solid #f0f0f0', borderRadius: 8, marginBottom: 16, overflow: 'hidden', padding: '10px 20px' }}>
              {/* UCL / CL / LCL 线 */}
              {chartData?.ucl && <div style={{ position: 'absolute', top: '20%', left: 0, right: 0, borderTop: '2px dashed #f5222d', opacity: 0.6 }}><Text style={{ position: 'absolute', right: 4, top: -18, fontSize: 11, color: '#f5222d' }}>UCL {chartData.ucl}</Text></div>}
              {chartData?.cl && <div style={{ position: 'absolute', top: '50%', left: 0, right: 0, borderTop: '2px solid #1890ff', opacity: 0.6 }}><Text style={{ position: 'absolute', right: 4, top: -18, fontSize: 11, color: '#1890ff' }}>CL {chartData.cl}</Text></div>}
              {chartData?.lcl && <div style={{ position: 'absolute', top: '80%', left: 0, right: 0, borderTop: '2px dashed #f5222d', opacity: 0.6 }}><Text style={{ position: 'absolute', right: 4, top: -18, fontSize: 11, color: '#f5222d' }}>LCL {chartData.lcl}</Text></div>}
              {/* 数据点 */}
              <div style={{ display: 'flex', alignItems: 'center', height: '100%', gap: 2 }}>
                {points.slice(-30).map((p: any, i: number) => {
                  const range = (chartData?.ucl || 1) - (chartData?.lcl || 0)
                  const pct = range > 0 ? Math.max(5, Math.min(95, ((chartData?.ucl || 1) - p.measured_value) / range * 100)) : 50
                  return (
                    <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', height: '100%', justifyContent: 'flex-start', paddingTop: `${pct}%` }}>
                      <div style={{
                        width: 8, height: 8, borderRadius: '50%',
                        backgroundColor: p.is_out_of_control ? '#f5222d' : '#1890ff',
                        boxShadow: p.is_out_of_control ? '0 0 6px #f5222d' : 'none',
                      }} title={`${p.measured_value}`} />
                    </div>
                  )
                })}
              </div>
            </div>

            {/* 数据表 */}
            <Table
              dataSource={points.slice(-20).reverse()}
              rowKey={(_, i) => String(i)}
              size="small"
              pagination={false}
              columns={[
                { title: '时间', dataIndex: 'measured_at', width: 150, render: (v) => v?.slice(5, 16).replace('T', ' ') },
                { title: '测量值', dataIndex: 'measured_value', width: 100, render: (v, r: any) => <Text style={{ color: r.is_out_of_control ? '#f5222d' : undefined, fontWeight: r.is_out_of_control ? 'bold' : undefined }}>{v}</Text> },
                { title: '状态', dataIndex: 'is_out_of_control', width: 80, render: (v) => v ? <Tag color="red">失控</Tag> : <Tag color="green">受控</Tag> },
                { title: '工位', dataIndex: 'station_id', width: 80 },
              ]}
            />
          </div>
        )}
      </Card>
    </div>
  )
}

export default SpcDashboard
