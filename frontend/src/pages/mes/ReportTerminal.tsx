import React, { useEffect, useState } from 'react'
import {
  Card, Row, Col, Button, InputNumber, Select, Tag, Space, Statistic,
  message, Result, Typography, Modal,
} from 'antd'
import {
  CheckCircleOutlined, ThunderboltOutlined, WarningOutlined,
  ToolOutlined, InboxOutlined, ClockCircleOutlined,
  UndoOutlined, SendOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import api from '../../services/api'

const { Text } = Typography
const FACTORY = 'F001'

// 班次配置
const shiftConfig: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  day: { label: '早班', color: '#52c41a', icon: <ClockCircleOutlined /> },
  middle: { label: '中班', color: '#1890ff', icon: <ClockCircleOutlined /> },
  night: { label: '晚班', color: '#722ed1', icon: <ClockCircleOutlined /> },
}

function detectShift(): string {
  const h = dayjs().hour()
  if (h >= 6 && h < 14) return 'day'
  if (h >= 14 && h < 22) return 'middle'
  return 'night'
}

interface WorkOrderItem {
  id: string
  work_order_code: string
  product_id: string
  planned_qty: number
  completed_qty: number
  status: string
  priority: string
}

interface ReportRecord {
  id: string
  report_code: string
  good_qty: number
  defect_qty: number
  scrap_qty: number
  station_id?: string
  created_at: string
}

const ReportTerminal: React.FC = () => {
  const [shift, setShift] = useState(detectShift())
  const [stations, setStations] = useState<any[]>([])
  const [selectedStation, setSelectedStation] = useState<string>('')
  const [workOrders, setWorkOrders] = useState<WorkOrderItem[]>([])
  const [selectedWO, setSelectedWO] = useState<string>('')
  const [goodQty, setGoodQty] = useState<number>(0)
  const [defectQty, setDefectQty] = useState<number>(0)
  const [scrapQty, setScrapQty] = useState<number>(0)
  const [submitting, setSubmitting] = useState(false)
  const [lastReport, setLastReport] = useState<ReportRecord | null>(null)
  const [todayOutput, setTodayOutput] = useState(0)
  const [todayGood, setTodayGood] = useState(0)
  const [recentReports, setRecentReports] = useState<ReportRecord[]>([])
  const [successVisible, setSuccessVisible] = useState(false)

  // 加载工位列表
  useEffect(() => {
    loadStations()
    loadTodayStats()
    loadRecentReports()
  }, [])

  // 选择工位后加载工单
  useEffect(() => {
    if (selectedStation) loadWorkOrders()
  }, [selectedStation])

  const loadStations = async () => {
    try {
      const res: any = await api.get('/api/v1/stations', { params: { factory_id: FACTORY } })
      setStations(res?.items || res || [])
    } catch { /* ignore */ }
  }

  const loadWorkOrders = async () => {
    try {
      const res: any = await api.get('/api/v1/work-orders', {
        params: { factory_id: FACTORY, status: 'in_progress', limit: 50 }
      })
      const items = res?.items || res || []
      setWorkOrders(items)
    } catch { /* ignore */ }
  }

  const loadTodayStats = async () => {
    try {
      const res: any = await api.get('/api/v1/reports/shift-summary', {
        params: { factory_id: FACTORY }
      })
      setTodayOutput(res?.total_output || 0)
      setTodayGood(res?.good_qty || 0)
    } catch { /* ignore */ }
  }

  const loadRecentReports = async () => {
    try {
      const res: any = await api.get('/api/v1/reports/realtime', {
        params: { factory_id: FACTORY, limit: 10 }
      })
      setRecentReports(res?.items || [])
    } catch { /* ignore */ }
  }

  const handleSubmit = async () => {
    if (!selectedStation) { message.warning('请选择工位'); return }
    if (!selectedWO) { message.warning('请选择工单'); return }
    if (goodQty + defectQty + scrapQty === 0) { message.warning('请输入数量'); return }

    setSubmitting(true)
    try {
      const res: any = await api.post('/api/v1/reports/quick', {
        factory_id: FACTORY,
        work_order_id: selectedWO,
        station_id: selectedStation,
        good_qty: goodQty,
        defect_qty: defectQty,
        scrap_qty: scrapQty,
        shift,
      })
      setLastReport(res)
      setSuccessVisible(true)
      // 重置数量
      setGoodQty(0)
      setDefectQty(0)
      setScrapQty(0)
      // 刷新统计
      loadTodayStats()
      loadRecentReports()
      loadWorkOrders()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '报工失败')
    } finally {
      setSubmitting(false)
    }
  }

  const handleUndo = async () => {
    if (!lastReport) return
    try {
      await api.post(`/api/v1/reports/${lastReport.id}/undo`)
      message.success('已撤回')
      setLastReport(null)
      loadTodayStats()
      loadRecentReports()
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '撤回失败')
    }
  }

  const shiftInfo = shiftConfig[shift] || shiftConfig.day
  const totalQty = goodQty + defectQty + scrapQty
  const yieldRate = totalQty > 0 ? ((goodQty / totalQty) * 100).toFixed(1) : '—'

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto' }}>
      {/* 顶部状态栏 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="当班产出"
              value={todayOutput}
              valueStyle={{ color: '#1890ff', fontSize: 28 }}
              suffix="件"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="良品数"
              value={todayGood}
              valueStyle={{ color: '#52c41a', fontSize: 28 }}
              suffix="件"
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="当前班次"
              value={shiftInfo.label}
              valueStyle={{ color: shiftInfo.color, fontSize: 28 }}
              prefix={shiftInfo.icon}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <div style={{ marginBottom: 8 }}>
              <Text type="secondary">切换班次</Text>
            </div>
            <Space>
              {Object.entries(shiftConfig).map(([key, cfg]) => (
                <Button
                  key={key}
                  size="small"
                  type={shift === key ? 'primary' : 'default'}
                  onClick={() => setShift(key)}
                  style={shift === key ? { background: cfg.color, borderColor: cfg.color } : {}}
                >
                  {cfg.label}
                </Button>
              ))}
            </Space>
          </Card>
        </Col>
      </Row>

      <Row gutter={24}>
        {/* 左侧：报工操作区 */}
        <Col span={14}>
          <Card
            title={<Space><SendOutlined /> 快速报工</Space>}
            styles={{ body: { padding: 24 } }}
          >
            {/* 工位选择 */}
            <div style={{ marginBottom: 20 }}>
              <Text strong style={{ fontSize: 15, display: 'block', marginBottom: 8 }}>
                1. 选择工位
              </Text>
              <Select
                placeholder="选择当前工位"
                style={{ width: '100%', height: 48, fontSize: 16 }}
                value={selectedStation || undefined}
                onChange={setSelectedStation}
                options={stations.map(s => ({
                  value: s.id,
                  label: `${s.name || s.id} (${s.id})`,
                }))}
                showSearch
                optionFilterProp="label"
              />
            </div>

            {/* 工单选择 */}
            <div style={{ marginBottom: 20 }}>
              <Text strong style={{ fontSize: 15, display: 'block', marginBottom: 8 }}>
                2. 选择工单
              </Text>
              <Select
                placeholder="选择加工工单"
                style={{ width: '100%', height: 48, fontSize: 16 }}
                value={selectedWO || undefined}
                onChange={setSelectedWO}
                options={workOrders.map(wo => ({
                  value: wo.id,
                  label: `${wo.work_order_code} | ${wo.product_id} | ${wo.completed_qty}/${wo.planned_qty}`,
                }))}
                showSearch
                optionFilterProp="label"
                notFoundContent="无在制工单"
              />
            </div>

            {/* 数量输入 */}
            <div style={{ marginBottom: 20 }}>
              <Text strong style={{ fontSize: 15, display: 'block', marginBottom: 12 }}>
                3. 输入数量
              </Text>
              <Row gutter={16}>
                <Col span={8}>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ marginBottom: 4 }}>
                      <Tag color="green" style={{ fontSize: 14, padding: '2px 12px' }}>良品</Tag>
                    </div>
                    <InputNumber
                      min={0}
                      value={goodQty}
                      onChange={v => setGoodQty(v || 0)}
                      style={{ width: '100%', height: 56, fontSize: 24, textAlign: 'center' }}
                      controls={true}
                    />
                  </div>
                </Col>
                <Col span={8}>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ marginBottom: 4 }}>
                      <Tag color="orange" style={{ fontSize: 14, padding: '2px 12px' }}>不良</Tag>
                    </div>
                    <InputNumber
                      min={0}
                      value={defectQty}
                      onChange={v => setDefectQty(v || 0)}
                      style={{ width: '100%', height: 56, fontSize: 24, textAlign: 'center' }}
                      controls={true}
                    />
                  </div>
                </Col>
                <Col span={8}>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ marginBottom: 4 }}>
                      <Tag color="red" style={{ fontSize: 14, padding: '2px 12px' }}>报废</Tag>
                    </div>
                    <InputNumber
                      min={0}
                      value={scrapQty}
                      onChange={v => setScrapQty(v || 0)}
                      style={{ width: '100%', height: 56, fontSize: 24, textAlign: 'center' }}
                      controls={true}
                    />
                  </div>
                </Col>
              </Row>
              {/* 实时良品率 */}
              {totalQty > 0 && (
                <div style={{ textAlign: 'center', marginTop: 12 }}>
                  <Text type="secondary">
                    本次: {totalQty} 件 | 良品率: <Text strong style={{ color: Number(yieldRate) >= 95 ? '#52c41a' : '#faad14' }}>{yieldRate}%</Text>
                  </Text>
                </div>
              )}
            </div>

            {/* 提交按钮 */}
            <Button
              type="primary"
              size="large"
              block
              loading={submitting}
              onClick={handleSubmit}
              icon={<CheckCircleOutlined />}
              style={{ height: 56, fontSize: 18, borderRadius: 8 }}
            >
              提交报工 ({totalQty} 件)
            </Button>

            {/* 撤回按钮 */}
            {lastReport && (
              <Button
                block
                style={{ marginTop: 12, height: 40 }}
                icon={<UndoOutlined />}
                onClick={handleUndo}
              >
                撤回上次报工 ({lastReport.report_code})
              </Button>
            )}
          </Card>
        </Col>

        {/* 右侧：最近报工记录 */}
        <Col span={10}>
          <Card
            title={<Space><ThunderboltOutlined /> 最近报工</Space>}
            styles={{ body: { padding: '12px 16px', maxHeight: 520, overflow: 'auto' } }}
          >
            {recentReports.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
                暂无报工记录
              </div>
            ) : (
              recentReports.map((r, i) => (
                <div
                  key={r.id}
                  style={{
                    padding: '10px 12px',
                    marginBottom: 8,
                    borderRadius: 8,
                    background: i === 0 ? '#f6ffed' : '#fafafa',
                    border: i === 0 ? '1px solid #b7eb8f' : '1px solid #f0f0f0',
                  }}
                >
                  <Row justify="space-between" align="middle">
                    <Col>
                      <Text strong>{r.report_code}</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {r.station_id} | {dayjs(r.created_at).format('HH:mm:ss')}
                      </Text>
                    </Col>
                    <Col>
                      <Space>
                        <Tag color="green">良 {r.good_qty}</Tag>
                        {r.defect_qty > 0 && <Tag color="orange">不良 {r.defect_qty}</Tag>}
                        {r.scrap_qty > 0 && <Tag color="red">废 {r.scrap_qty}</Tag>}
                      </Space>
                    </Col>
                  </Row>
                </div>
              ))
            )}
          </Card>

          {/* 异常快报 */}
          <Card
            title={<Space><WarningOutlined style={{ color: '#faad14' }} /> 异常快报</Space>}
            size="small"
            style={{ marginTop: 16 }}
          >
            <Space wrap>
              <Button icon={<ToolOutlined />} danger>设备故障</Button>
              <Button icon={<InboxOutlined />} style={{ borderColor: '#faad14', color: '#faad14' }}>缺料</Button>
              <Button icon={<WarningOutlined />} style={{ borderColor: '#722ed1', color: '#722ed1' }}>质量问题</Button>
            </Space>
          </Card>
        </Col>
      </Row>

      {/* 成功弹窗 */}
      <Modal
        open={successVisible}
        footer={null}
        onCancel={() => setSuccessVisible(false)}
        centered
        width={360}
      >
        <Result
          status="success"
          title="报工成功"
          subTitle={lastReport ? `${lastReport.report_code} | 良品 ${lastReport.good_qty} 件` : ''}
          extra={[
            <Button key="ok" type="primary" onClick={() => setSuccessVisible(false)}>
              继续报工
            </Button>,
          ]}
        />
      </Modal>
    </div>
  )
}

export default ReportTerminal
