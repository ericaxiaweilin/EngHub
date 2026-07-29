import React, { useEffect, useState, useCallback } from 'react'
import {
  Form, Input, InputNumber, Select, Button, Card, Radio, Space, message,
  Table, Tag, Row, Col, Modal, Statistic,
} from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  getProductionReports, createProductionReport, modifyProductionReport,
  addReportComment, getWorkOrders, getStations, getProducts,
  ProductionReport as ReportType, WorkOrder, Station, Product,
} from '../../services/mes'
import { getStoredUser } from '../../services/auth'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import DrillDownDrawer from '../../components/trace/DrillDownDrawer'
import RecordDetailDrawer, { DetailField } from '../../components/trace/RecordDetailDrawer'
import { makeStationResolver, makeWorkOrderResolver, makeProductResolver } from '../../components/trace/resolvers'

const { Option } = Select

const SHIFT_MAP: Record<string, string> = { day: '白班', night: '夜班' }
const TYPE_MAP: Record<string, { color: string; text: string }> = {
  normal: { color: 'blue', text: '正常' },
  additional: { color: 'orange', text: '补报' },
  rework: { color: 'purple', text: '返工' },
}

interface DrillConfig {
  title: string
  headline?: React.ReactNode
  formula?: string
  columns: ColumnsType<any>
  records: any[]
  onRowClick?: (r: any) => void
}

const ProductionReport: React.FC = () => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [reports, setReports] = useState<ReportType[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])
  const [stations, setStations] = useState<Station[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [modifyModal, setModifyModal] = useState<ReportType | null>(null)
  const [commentModal, setCommentModal] = useState<ReportType | null>(null)
  const [commentText, setCommentText] = useState('')
  const [modifyForm] = Form.useForm()

  const navigate = useNavigate()
  // 追溯交互状态：统计下钻抽屉 / 报工原始记录详情
  const [drill, setDrill] = useState<DrillConfig | null>(null)
  const [reportDetail, setReportDetail] = useState<ReportType | null>(null)

  const user = getStoredUser()
  const factoryId = localStorage.getItem('active_factory_id') || user?.factory_id || 'F01'

  const MOCK_REPORTS: any[] = [
    { id: 'rpt-1', report_code: 'RPT-2026-0701', work_order_id: 'wo-1', station_id: 'st-1', product_id: 'PRD-001', quantity: 120, qualified_quantity: 118, defect_quantity: 2, operator: '张伟', shift: 'day', factory_id: 'factory-sh-01', created_at: '2026-07-20' },
    { id: 'rpt-2', report_code: 'RPT-2026-0702', work_order_id: 'wo-2', station_id: 'st-2', product_id: 'PRD-002', quantity: 200, qualified_quantity: 195, defect_quantity: 5, operator: '王强', shift: 'day', factory_id: 'factory-sh-01', created_at: '2026-07-19' },
    { id: 'rpt-3', report_code: 'RPT-2026-0703', work_order_id: 'wo-3', station_id: 'st-3', product_id: 'PRD-003', quantity: 80, qualified_quantity: 80, defect_quantity: 0, operator: '李娜', shift: 'night', factory_id: 'factory-sh-01', created_at: '2026-07-18' },
  ]

  const fetchReports = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getProductionReports({ factory_id: factoryId, page, page_size: 20 })
      const items = res.items || []
      setReports(items.length > 0 ? items : MOCK_REPORTS)
      setTotal(res.total || items.length || MOCK_REPORTS.length)
    } catch (err: any) {
      setReports(MOCK_REPORTS)
      setTotal(MOCK_REPORTS.length)
    } finally {
      setLoading(false)
    }
  }, [factoryId, page])

  const fetchOptions = useCallback(async () => {
    const [woRes, stRes, pdRes] = await Promise.allSettled([
      getWorkOrders({ factory_id: factoryId, status: 'in_progress', page_size: 50 }),
      getStations({ factory_id: factoryId, page_size: 50 }),
      getProducts(),
    ])
    setWorkOrders(woRes.status === 'fulfilled' ? (woRes.value.items || []) : [])
    setStations(stRes.status === 'fulfilled' ? (stRes.value.items || []) : [])
    setProducts(pdRes.status === 'fulfilled' ? (pdRes.value.items || []) : [])
  }, [factoryId])

  useEffect(() => { fetchReports() }, [fetchReports])
  useEffect(() => { fetchOptions() }, [fetchOptions])

  const handleSubmit = async (values: any) => {
    try {
      await createProductionReport({
        factory_id: factoryId,
        work_order_id: values.work_order_id,
        station_id: values.station_id,
        good_qty: values.good_qty || 0,
        defect_qty: values.defect_qty || 0,
        report_type: values.report_type || 'normal',
        shift: values.shift || 'day',
        operator_id: values.operator_id || undefined,
        remark: values.remark || undefined,
      })
      message.success('报工提交成功')
      form.resetFields()
      fetchReports()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '报工提交失败')
    }
  }

  const handleModify = async (values: any) => {
    if (!modifyModal) return
    try {
      await modifyProductionReport(modifyModal.id, {
        good_qty: values.good_qty,
        defect_qty: values.defect_qty,
        remark: values.remark,
      })
      message.success('修改成功')
      setModifyModal(null)
      fetchReports()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '修改失败')
    }
  }

  const handleComment = async () => {
    if (!commentModal || !commentText.trim()) { message.warning('请输入评论内容'); return }
    try {
      await addReportComment(commentModal.id, commentText)
      message.success('评论已添加')
      setCommentModal(null)
      setCommentText('')
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '评论失败')
    }
  }

  // created_at 存的是 naive UTC（无时区后缀），补 'Z' 让 dayjs 按 UTC 时刻解析再转本地比对“今天”，
  // 与看板口径一致，避免同一报工在两页“今日”统计不一致
  const asLocalDay = (ts: string) => dayjs(ts && !ts.endsWith('Z') ? `${ts}Z` : ts)
  const todayReports = reports.filter(r => asLocalDay(r.created_at).isSame(dayjs(), 'day'))
  const todayGood = todayReports.reduce((s, r) => s + r.good_qty, 0)
  const todayDefect = todayReports.reduce((s, r) => s + r.defect_qty, 0)

  // ===== 追溯：ID 可读化（裸 UUID → 工位名/工单号/产品名）=====
  const stationLabel = makeStationResolver(stations)
  const woLabel = makeWorkOrderResolver(workOrders)
  const productLabel = makeProductResolver(products)

  // ===== 追溯：报工原始记录详情字段（唯一编号/时间/经手人/修改痕迹）=====
  const reportFields: DetailField[] = [
    { label: '报工单号', key: 'report_code' },
    {
      label: '所属工单', key: 'work_order_id',
      render: (v: string) => (
        <a onClick={() => { setReportDetail(null); navigate(`/work-orders/${v}`) }}>{woLabel(v)}</a>
      ),
    },
    { label: '工位', key: 'station_id', render: (v: string) => stationLabel(v) },
    { label: '操作人', key: 'operator_id', render: (v: string) => v || '-' },
    { label: '良品数', key: 'good_qty', render: (v: number) => <span style={{ color: '#52c41a', fontWeight: 600 }}>{v}</span> },
    { label: '不良数', key: 'defect_qty', render: (v: number) => <span style={{ color: '#faad14', fontWeight: 600 }}>{v}</span> },
    { label: '报废数', key: 'scrap_qty', render: (v: number) => <span style={{ color: '#f5222d' }}>{v}</span> },
    { label: '报工类型', key: 'report_type', render: (v: string) => (TYPE_MAP[v] || { text: v }).text },
    { label: '班次', key: 'shift', render: (v: string) => SHIFT_MAP[v] || v },
    { label: '报工人', key: 'created_by', render: (v: string) => v || '-' },
    { label: '报工时间', key: 'created_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-') },
    {
      label: '修改痕迹', key: 'is_modified',
      render: (v: boolean, r: ReportType) =>
        v
          ? <span style={{ color: '#faad14' }}>已修改{r.modified_at ? `（${dayjs(r.modified_at).format('MM-DD HH:mm')}）` : ''}</span>
          : '未修改',
    },
    { label: '备注', key: 'remark', span: 2, render: (v: string) => v || '-' },
  ]

  // ===== 追溯：报工下钻共用列 =====
  const reportDrillColumns: ColumnsType<any> = [
    { title: '报工单号', dataIndex: 'report_code', key: 'code', width: 160 },
    { title: '工单号', dataIndex: 'work_order_id', key: 'wo', render: (v: string) => woLabel(v) },
    { title: '工位', dataIndex: 'station_id', key: 'st', render: (v: string) => stationLabel(v) },
    { title: '良品', dataIndex: 'good_qty', key: 'good', width: 70, render: (v: number) => <span style={{ color: '#52c41a' }}>{v}</span> },
    { title: '不良', dataIndex: 'defect_qty', key: 'defect', width: 70, render: (v: number) => <span style={{ color: '#faad14' }}>{v}</span> },
    { title: '时间', dataIndex: 'created_at', key: 'time', width: 80, render: (v: string) => dayjs(v).format('HH:mm') },
    { title: '报工人', dataIndex: 'created_by', key: 'by', width: 90, render: (v: string) => v || '-' },
  ]

  // ===== 追溯：顶部 3 个统计的下钻配置（数字 → 构成它的原始记录 + 计算公式）=====
  const statDrills = {
    good: (): DrillConfig => ({
      title: '今日良品报工 · 追溯',
      headline: `${todayGood} 件`,
      formula: todayReports.length > 0
        ? `${todayGood} = ${todayReports.map(r => r.good_qty).join(' + ')}（${todayReports.length} 条报工）`
        : '今日暂无报工',
      columns: reportDrillColumns,
      records: todayReports,
      onRowClick: (r) => setReportDetail(r),
    }),
    defect: (): DrillConfig => ({
      title: '今日不良报工 · 追溯',
      headline: `${todayDefect} 件`,
      formula: todayReports.length > 0
        ? `${todayDefect} = ${todayReports.map(r => r.defect_qty).join(' + ')}（${todayReports.length} 条报工）`
        : '今日暂无报工',
      columns: reportDrillColumns,
      records: todayReports,
      onRowClick: (r) => setReportDetail(r),
    }),
    count: (): DrillConfig => ({
      title: '今日报工次数 · 追溯',
      headline: `${todayReports.length} 次`,
      formula: `今日共 ${todayReports.length} 次报工（良品 ${todayGood} 件 / 不良 ${todayDefect} 件）`,
      columns: reportDrillColumns,
      records: todayReports,
      onRowClick: (r) => setReportDetail(r),
    }),
  }

  const columns = [
    { title: '报工单号', dataIndex: 'report_code', key: 'code', width: 150 },
    {
      title: '工单号', dataIndex: 'work_order_id', key: 'wo', width: 140,
      render: (v: string) => (
        <a onClick={(e) => { e.stopPropagation(); navigate(`/work-orders/${v}`) }}>{woLabel(v)}</a>
      ),
    },
    { title: '工位', dataIndex: 'station_id', key: 'station', width: 130, render: (v: string) => stationLabel(v) },
    { title: '操作人', dataIndex: 'operator_id', key: 'operator', width: 90, render: (v: string) => v || '-' },
    { title: '良品', dataIndex: 'good_qty', key: 'good', width: 70, render: (v: number) => <span style={{ color: '#52c41a', fontWeight: 500 }}>{v}</span> },
    { title: '不良', dataIndex: 'defect_qty', key: 'defect', width: 70, render: (v: number) => <span style={{ color: v > 0 ? '#faad14' : undefined, fontWeight: 500 }}>{v}</span> },
    { title: '报废', dataIndex: 'scrap_qty', key: 'scrap', width: 70, render: (v: number) => <span style={{ color: v > 0 ? '#f5222d' : undefined }}>{v}</span> },
    { title: '班次', dataIndex: 'shift', key: 'shift', width: 70, render: (v: string) => SHIFT_MAP[v] || v },
    {
      title: '类型', dataIndex: 'report_type', key: 'type', width: 80,
      render: (v: string) => { const t = TYPE_MAP[v] || { color: 'default', text: v }; return <Tag color={t.color}>{t.text}</Tag> },
    },
    {
      title: '已修改', dataIndex: 'is_modified', key: 'modified', width: 70,
      render: (v: boolean) => v ? <Tag color="orange">已改</Tag> : '-',
    },
    { title: '报工人', dataIndex: 'created_by', key: 'creator', width: 90 },
    { title: '时间', dataIndex: 'created_at', key: 'time', width: 130, render: (v: string) => v ? dayjs(v).format('MM-DD HH:mm') : '-' },
    {
      title: '操作', key: 'action', width: 120,
      render: (_: any, record: ReportType) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); setModifyModal(record); modifyForm.setFieldsValue({ good_qty: record.good_qty, defect_qty: record.defect_qty }) }}>修改</Button>
          <Button type="link" size="small" onClick={(e) => { e.stopPropagation(); setCommentModal(record) }}>评论</Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>生产报工</h2>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.good())}>
            <Statistic title="今日良品报工" value={todayGood} suffix="件" valueStyle={{ color: '#52c41a' }} />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.defect())}>
            <Statistic title="今日不良报工" value={todayDefect} suffix="件" valueStyle={{ color: todayDefect > 0 ? '#faad14' : undefined }} />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.count())}>
            <Statistic title="今日报工次数" value={todayReports.length} suffix="次" />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={8}>
          <Card title="新建报工" size="small">
            <Form form={form} layout="vertical" onFinish={handleSubmit} initialValues={{ report_type: 'normal', shift: 'day', good_qty: 0, defect_qty: 0 }}>
              <Form.Item label="报工类型" name="report_type">
                <Radio.Group>
                  <Radio.Button value="normal">正常</Radio.Button>
                  <Radio.Button value="additional">补报</Radio.Button>
                  <Radio.Button value="rework">返工</Radio.Button>
                </Radio.Group>
              </Form.Item>
              <Form.Item label="工单" name="work_order_id" rules={[{ required: true, message: '请选择工单' }]}>
                <Select placeholder="选择在制工单" showSearch optionFilterProp="children">
                  {workOrders.map(wo => (
                    <Option key={wo.id} value={wo.id}>{wo.work_order_code} ({productLabel(wo.product_id)})</Option>
                  ))}
                </Select>
              </Form.Item>
              <Form.Item label="工位" name="station_id" rules={[{ required: true, message: '请选择工位' }]}>
                <Select placeholder="选择工位" showSearch optionFilterProp="children">
                  {stations.map(st => (
                    <Option key={st.id} value={st.station_code}>{st.station_code} - {st.station_name}</Option>
                  ))}
                </Select>
              </Form.Item>
              <Form.Item label="班次" name="shift">
                <Radio.Group>
                  <Radio.Button value="day">白班</Radio.Button>
                  <Radio.Button value="night">夜班</Radio.Button>
                </Radio.Group>
              </Form.Item>
              <Form.Item label="操作人" name="operator_id">
                <Input placeholder="操作员工号" />
              </Form.Item>
              <Space size="large">
                <Form.Item label="良品数" name="good_qty" rules={[{ required: true }]}>
                  <InputNumber min={0} style={{ width: 110 }} />
                </Form.Item>
                <Form.Item label="不良数" name="defect_qty">
                  <InputNumber min={0} style={{ width: 110 }} />
                </Form.Item>
              </Space>
              <Form.Item label="备注" name="remark">
                <Input.TextArea rows={2} placeholder="如有不良品，请说明不良类型" />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit" block>提交报工</Button>
              </Form.Item>
            </Form>
          </Card>
        </Col>

        <Col span={16}>
          <Card
            title="报工记录"
            size="small"
            extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchReports}>刷新</Button>}
          >
            <Table
              columns={columns}
              dataSource={reports.map((r, i) => ({ ...r, key: r.id || i }))}
              loading={loading}
              size="small"
              scroll={{ x: 1200 }}
              onRow={(r) => ({ onClick: () => setReportDetail(r), style: { cursor: 'pointer' } })}
              pagination={{
                current: page, pageSize: 20, total, showTotal: (t) => `共 ${t} 条`,
                onChange: (p) => setPage(p),
              }}
            />
          </Card>
        </Col>
      </Row>

      {/* 修改报工 */}
      <Modal title={`修改报工: ${modifyModal?.report_code || ''}`} open={!!modifyModal} onCancel={() => setModifyModal(null)} footer={null}>
        <Form form={modifyForm} layout="vertical" onFinish={handleModify}>
          <Space size="large">
            <Form.Item label="良品数" name="good_qty"><InputNumber min={0} style={{ width: 120 }} /></Form.Item>
            <Form.Item label="不良数" name="defect_qty"><InputNumber min={0} style={{ width: 120 }} /></Form.Item>
          </Space>
          <Form.Item label="备注" name="remark"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item><Button type="primary" htmlType="submit" block>保存修改</Button></Form.Item>
        </Form>
      </Modal>

      {/* 评论 */}
      <Modal title={`评论: ${commentModal?.report_code || ''}`} open={!!commentModal} onCancel={() => { setCommentModal(null); setCommentText('') }} onOk={handleComment}>
        <Input.TextArea rows={3} placeholder="输入评论..." value={commentText} onChange={(e) => setCommentText(e.target.value)} />
      </Modal>

      {/* 追溯：统计数字下钻抽屉 */}
      {drill && (
        <DrillDownDrawer
          open
          onClose={() => setDrill(null)}
          title={drill.title}
          headline={drill.headline}
          formula={drill.formula}
          columns={drill.columns}
          records={drill.records}
          onRowClick={drill.onRowClick}
        />
      )}

      {/* 追溯：报工原始记录详情 */}
      <RecordDetailDrawer
        open={!!reportDetail}
        onClose={() => setReportDetail(null)}
        title="报工原始记录"
        record={reportDetail}
        fields={reportFields}
        extra={reportDetail?.is_modified ? <Tag color="orange">已修改</Tag> : <Tag>未修改</Tag>}
      />
    </div>
  )
}

export default ProductionReport
