import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  BarChartOutlined,
  CalendarOutlined,
  CalculatorOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  LineChartOutlined,
  PlusOutlined,
  ReloadOutlined,
  RocketOutlined,
  ScheduleOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { apsApi, type CapacityLoadData } from '../../services/aps'
import {
  calculateMrp,
  createPlan,
  getProducts,
  listInventory,
  listPlans,
  type Product,
} from '../../services/mes'
import { getActiveFactoryId } from '../../utils/factory'
import PmcWorkbookPanel from './PmcWorkbookPanel'

const { Text, Title, Paragraph } = Typography

type PlanRow = Record<string, any>
type MrpResult = Record<string, any>
type InventoryRow = Record<string, any>
type DohRow = InventoryRow & { doh: number | null; dohStatus: 'empty' | 'low' | 'watch' | 'healthy' }

const dateValue = (value: any) => (value ? dayjs(value).format('YYYY-MM-DD') : '')

const productLabel = (product: Product) => `${product.product_code || product.id} · ${product.product_name || '未命名产品'}`

const errorText = (error: any, fallback: string) => error?.response?.data?.detail || error?.message || fallback

export default function PmcForms() {
  const navigate = useNavigate()
  const factoryId = getActiveFactoryId()
  const [planForm] = Form.useForm()
  const [mrpForm] = Form.useForm()
  const [scheduleForm] = Form.useForm()
  const [capacityForm] = Form.useForm()
  const [dohForm] = Form.useForm()
  const [calendarForm] = Form.useForm()

  const [products, setProducts] = useState<Product[]>([])
  const [plans, setPlans] = useState<PlanRow[]>([])
  const [plansLoading, setPlansLoading] = useState(false)
  const [planSaving, setPlanSaving] = useState(false)
  const [mrpResult, setMrpResult] = useState<MrpResult | null>(null)
  const [mrpLoading, setMrpLoading] = useState(false)
  const [scheduleResult, setScheduleResult] = useState<any>(null)
  const [scheduleLoading, setScheduleLoading] = useState(false)
  const [schedules, setSchedules] = useState<any[]>([])
  const [capacityData, setCapacityData] = useState<CapacityLoadData | null>(null)
  const [capacityLoading, setCapacityLoading] = useState(false)
  const [dohRows, setDohRows] = useState<DohRow[]>([])
  const [dohLoading, setDohLoading] = useState(false)
  const [calendars, setCalendars] = useState<any[]>([])
  const [calendarLoading, setCalendarLoading] = useState(false)
  const [calendarSaving, setCalendarSaving] = useState(false)

  const productOptions = useMemo(
    () => products.map((product) => ({ value: product.id, label: productLabel(product) })),
    [products],
  )

  const productById = useMemo(() => {
    const map = new Map<string, Product>()
    products.forEach((product) => {
      map.set(product.id, product)
      if (product.product_code) map.set(product.product_code, product)
    })
    return map
  }, [products])

  const loadPlans = useCallback(async () => {
    setPlansLoading(true)
    try {
      const response: any = await listPlans(factoryId, { page: 1, page_size: 100 })
      setPlans(response?.items || [])
    } catch (error) {
      message.error(errorText(error, 'MPS 订单池加载失败'))
    } finally {
      setPlansLoading(false)
    }
  }, [factoryId])

  const loadProducts = useCallback(async () => {
    try {
      const response: any = await getProducts({ factory_id: factoryId, page: 1, page_size: 200 })
      setProducts(response?.items || [])
    } catch {
      // 产品可手工输入编码，主流程不依赖产品下拉接口。
      setProducts([])
    }
  }, [factoryId])

  const loadSchedules = useCallback(async () => {
    try {
      const response: any = await apsApi.listSchedules({ factory_id: factoryId, page: 1, page_size: 20 })
      setSchedules(response?.items || [])
    } catch {
      setSchedules([])
    }
  }, [factoryId])

  const loadCalendars = useCallback(async () => {
    setCalendarLoading(true)
    try {
      const response: any = await apsApi.listCalendars({ factory_id: factoryId })
      setCalendars(response?.items || [])
    } catch (error) {
      message.error(errorText(error, '工作日历加载失败'))
    } finally {
      setCalendarLoading(false)
    }
  }, [factoryId])

  useEffect(() => {
    loadProducts()
    loadPlans()
    loadSchedules()
    loadCalendars()
  }, [loadProducts, loadPlans, loadSchedules, loadCalendars])

  const submitPlan = async (values: any) => {
    setPlanSaving(true)
    try {
      const response: any = await createPlan({
        factory_id: factoryId,
        product_id: values.product_id,
        quantity: Number(values.quantity),
        required_date: dateValue(values.required_date),
        customer_level: values.customer_level,
        priority: Number(values.priority),
        sales_order_id: values.sales_order_id || undefined,
      })
      message.success(`MPS 计划 ${response?.plan_code || ''} 已创建`)
      await loadPlans()
      if (response?.id) mrpForm.setFieldsValue({ plan_id: response.id })
      planForm.resetFields()
      planForm.setFieldsValue({
        quantity: 1000,
        required_date: dayjs().add(14, 'day'),
        customer_level: 'b',
        priority: 50,
      })
    } catch (error) {
      message.error(errorText(error, 'MPS 计划创建失败'))
    } finally {
      setPlanSaving(false)
    }
  }

  const calculatePlanMrp = async (values: any) => {
    setMrpLoading(true)
    try {
      const response: any = await calculateMrp(values.plan_id, values.bom_version || undefined)
      setMrpResult(response)
      message.success(`MRP 已完成：${response?.summary?.total_materials || 0} 种物料`)
      await loadPlans()
    } catch (error) {
      setMrpResult(null)
      message.error(errorText(error, 'MRP 计算失败，请先确认产品已维护 BOM'))
    } finally {
      setMrpLoading(false)
    }
  }

  const generateSchedule = async (values: any) => {
    setScheduleLoading(true)
    try {
      const response: any = await apsApi.generate({
        factory_id: factoryId,
        mode: values.mode,
        horizon_days: Number(values.horizon_days),
        optimize_for: values.optimize_for,
        reason: values.reason || 'PMC 表单中心手工生成',
      })
      setScheduleResult(response)
      await loadSchedules()
      message.success(`排程完成：${response?.total_tasks ?? response?.schedule?.total_tasks ?? 0} 个任务`)
    } catch (error) {
      message.error(errorText(error, '排程生成失败'))
    } finally {
      setScheduleLoading(false)
    }
  }

  const loadCapacity = async (values: any) => {
    setCapacityLoading(true)
    try {
      const response = await apsApi.getCapacityLoad({ factory_id: factoryId, days: Number(values.days) })
      setCapacityData(response)
    } catch (error) {
      message.error(errorText(error, '产能负荷加载失败'))
    } finally {
      setCapacityLoading(false)
    }
  }

  const calculateDoh = async (values: any) => {
    setDohLoading(true)
    try {
      const response: any = await listInventory({ factory_id: factoryId })
      const keyword = String(values.material_code || '').trim().toLowerCase()
      const grouped = new Map<string, InventoryRow>()
      ;(response?.items || [])
        .filter((item: InventoryRow) => !keyword || String(item.material_code || item.material_id || '').toLowerCase().includes(keyword))
        .forEach((item: InventoryRow) => {
          const key = String(item.material_code || item.material_id || '未编码物料')
          const current = grouped.get(key) || {
            material_code: key,
            total_qty: 0,
            available_qty: 0,
            reserved_qty: 0,
            warehouse_count: 0,
          }
          current.total_qty += Number(item.total_qty || 0)
          current.available_qty += Number(item.available_qty || 0)
          current.reserved_qty += Number(item.reserved_qty || 0)
          current.warehouse_count += 1
          grouped.set(key, current)
        })
      const dailyDemand = Number(values.daily_demand)
      const rows: DohRow[] = Array.from(grouped.values()).map((item) => {
        const doh = dailyDemand > 0 ? Number((item.available_qty / dailyDemand).toFixed(1)) : null
        return {
          ...item,
          doh,
          dohStatus: doh === null ? 'empty' : doh < 7 ? 'low' : doh < 30 ? 'watch' : 'healthy',
        }
      })
      setDohRows(rows)
      if (!rows.length) message.info('没有匹配到库存记录')
    } catch (error) {
      message.error(errorText(error, '库存数据加载失败'))
    } finally {
      setDohLoading(false)
    }
  }

  const submitCalendar = async (values: any) => {
    setCalendarSaving(true)
    try {
      await apsApi.createCalendar({
        factory_id: factoryId,
        resource_id: values.resource_id,
        resource_type: values.resource_type,
        shift_name: values.shift_name,
        day_of_week: Number(values.day_of_week),
        start_time: values.start_time,
        end_time: values.end_time,
        is_active: true,
        effective_from: values.effective_from || undefined,
        effective_to: values.effective_to || undefined,
      })
      message.success('工作日历已保存')
      await loadCalendars()
    } catch (error) {
      message.error(errorText(error, '工作日历保存失败'))
    } finally {
      setCalendarSaving(false)
    }
  }

  const planColumns = [
    { title: '计划号', dataIndex: 'plan_code', key: 'plan_code', width: 150, render: (value: string) => <Text code>{value || '-'}</Text> },
    {
      title: '产品', dataIndex: 'product_id', key: 'product_id', width: 220,
      render: (value: string) => productById.get(value)?.product_name ? `${value} · ${productById.get(value)?.product_name}` : value,
    },
    { title: '数量', dataIndex: 'quantity', key: 'quantity', align: 'right' as const },
    { title: '需求日期', dataIndex: 'required_date', key: 'required_date', render: (value: string) => value?.slice(0, 10) || '-' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (value: string) => <Tag color={value === 'released' ? 'green' : value === 'cancelled' ? 'red' : 'blue'}>{value || '-'}</Tag> },
    { title: 'MRP', dataIndex: 'mrp_status', key: 'mrp_status', render: (value: string) => <Tag color={value === 'calculated' ? 'success' : 'default'}>{value === 'calculated' ? '已计算' : '未计算'}</Tag> },
  ]

  const mrpColumns = [
    { title: '物料编码', dataIndex: 'material_code', key: 'material_code', width: 150, render: (value: string) => <Text code>{value}</Text> },
    { title: '物料名称', dataIndex: 'material_name', key: 'material_name', width: 180 },
    { title: '单位用量', dataIndex: 'qty_per_unit', key: 'qty_per_unit', align: 'right' as const },
    { title: '毛需求', dataIndex: 'required_qty', key: 'required_qty', align: 'right' as const },
    { title: '可用库存', dataIndex: 'on_hand_qty', key: 'on_hand_qty', align: 'right' as const },
    {
      title: '净需求 / 欠料', dataIndex: 'net_qty', key: 'net_qty', align: 'right' as const,
      render: (value: number) => <Text type={value > 0 ? 'danger' : 'success'} strong>{value || 0}</Text>,
    },
    { title: '建议采购', dataIndex: 'suggested_order_qty', key: 'suggested_order_qty', align: 'right' as const, render: (value: number) => value > 0 ? <Tag color="orange">{value}</Tag> : '-' },
    { title: '供应商', dataIndex: 'supplier', key: 'supplier', render: (value: string) => value || '-' },
  ]

  const capacityRows = useMemo(
    () => (capacityData?.resources || []).flatMap((resource: any) => (resource.daily_load || []).map((day: any) => ({ ...day, station_id: resource.station_id, avg_utilization: resource.avg_utilization }))),
    [capacityData],
  )

  const capacityColumns = [
    { title: '工位', dataIndex: 'station_id', key: 'station_id', render: (value: string) => <Text code>{value}</Text> },
    { title: '日期', dataIndex: 'date', key: 'date' },
    { title: '计划负荷(h)', dataIndex: 'load_hours', key: 'load_hours', align: 'right' as const },
    { title: '可用产能(h)', dataIndex: 'capacity_hours', key: 'capacity_hours', align: 'right' as const },
    {
      title: '利用率', dataIndex: 'utilization', key: 'utilization', width: 180,
      render: (value: number) => <Progress percent={Math.min(Number(value || 0), 100)} size="small" status={value > 100 ? 'exception' : value > 85 ? 'active' : 'normal'} format={() => `${value || 0}%`} />,
    },
    { title: '结论', dataIndex: 'overloaded', key: 'overloaded', render: (value: boolean) => <Tag color={value ? 'error' : 'success'}>{value ? '超负荷' : '可承载'}</Tag> },
  ]

  const dohColumns = [
    { title: '物料编码', dataIndex: 'material_code', key: 'material_code', render: (value: string) => <Text code>{value}</Text> },
    { title: '库存总量', dataIndex: 'total_qty', key: 'total_qty', align: 'right' as const },
    { title: '可用库存', dataIndex: 'available_qty', key: 'available_qty', align: 'right' as const },
    { title: '已预留', dataIndex: 'reserved_qty', key: 'reserved_qty', align: 'right' as const },
    { title: '库位记录', dataIndex: 'warehouse_count', key: 'warehouse_count', align: 'right' as const },
    {
      title: 'DOH', dataIndex: 'doh', key: 'doh', align: 'right' as const,
      render: (value: number | null, row: DohRow) => value === null ? '-' : <Tag color={row.dohStatus === 'low' ? 'error' : row.dohStatus === 'watch' ? 'warning' : 'success'}>{value} 天</Tag>,
    },
  ]

  const calendarColumns = [
    { title: '资源', dataIndex: 'resource_id', key: 'resource_id', render: (value: string) => <Text code>{value}</Text> },
    { title: '班次', dataIndex: 'shift_name', key: 'shift_name' },
    { title: '星期', dataIndex: 'day_of_week', key: 'day_of_week', render: (value: number) => ['一', '二', '三', '四', '五', '六', '日'][value] || value },
    { title: '工作时段', key: 'time', render: (_: any, row: any) => `${row.start_time || '-'} - ${row.end_time || '-'}` },
    { title: '有效期', key: 'effective', render: (_: any, row: any) => `${row.effective_from || '长期'}${row.effective_to ? ` 至 ${row.effective_to}` : ''}` },
    { title: '状态', dataIndex: 'is_active', key: 'is_active', render: (value: boolean) => <Tag color={value ? 'success' : 'default'}>{value ? '启用' : '停用'}</Tag> },
  ]

  const formItemLayout = { labelCol: { span: 7 }, wrapperCol: { span: 17 } }

  const mpsAndMrp = (
    <>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={10}>
          <Card size="small" title={<Space><PlusOutlined /> 新建 MPS 计划</Space>}>
            <Paragraph type="secondary">先建立订单池，再以计划号作为 MRP 计算入口。产品编码可直接手工输入，也可从基础资料建议中选择。</Paragraph>
            <Form form={planForm} layout="vertical" initialValues={{ quantity: 1000, required_date: dayjs().add(14, 'day'), customer_level: 'b', priority: 50 }} onFinish={submitPlan}>
              <Form.Item label="产品编码" name="product_id" rules={[{ required: true, message: '请输入产品编码' }]}>
                <AutoComplete options={productOptions} filterOption={(input, option) => String(option?.label || option?.value).toLowerCase().includes(input.toLowerCase())} placeholder="输入产品编码或从建议中选择" />
              </Form.Item>
              <Row gutter={12}>
                <Col span={12}><Form.Item label="计划数量" name="quantity" rules={[{ required: true, message: '请输入数量' }]}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item></Col>
                <Col span={12}><Form.Item label="需求日期" name="required_date" rules={[{ required: true, message: '请选择需求日期' }]}><DatePicker style={{ width: '100%' }} /></Form.Item></Col>
              </Row>
              <Row gutter={12}>
                <Col span={12}><Form.Item label="客户等级" name="customer_level"><Select options={[{ value: 'a', label: 'A · 战略客户' }, { value: 'b', label: 'B · 重要客户' }, { value: 'c', label: 'C · 普通客户' }]} /></Form.Item></Col>
                <Col span={12}><Form.Item label="优先级" name="priority"><InputNumber min={1} max={100} style={{ width: '100%' }} /></Form.Item></Col>
              </Row>
              <Form.Item label="销售订单" name="sales_order_id"><Input placeholder="可选，如 SO-2026-001" /></Form.Item>
              <Button type="primary" htmlType="submit" icon={<PlusOutlined />} loading={planSaving} block>写入订单池</Button>
            </Form>
          </Card>
        </Col>
        <Col xs={24} lg={14}>
          <Card size="small" title={<Space><DatabaseOutlined /> 订单池 / MPS 计划</Space>} extra={<Button size="small" icon={<ReloadOutlined />} onClick={loadPlans} loading={plansLoading}>刷新</Button>}>
            <Table rowKey="id" size="small" scroll={{ x: 850 }} loading={plansLoading} dataSource={plans} columns={planColumns} pagination={{ pageSize: 6, showSizeChanger: false }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 MPS 计划" /> }} />
          </Card>
        </Col>
      </Row>

      <Card size="small" title={<Space><CalculatorOutlined /> 物料动态计算 / 齐套欠料</Space>} style={{ marginTop: 16 }}>
        <Paragraph type="secondary">计算链路：MPS 计划 → BOM → 可用库存 → 毛需求、净需求、建议采购量。只有实际维护了 BOM 和库存的物料会进入结果。</Paragraph>
        <Form form={mrpForm} layout="inline" onFinish={calculatePlanMrp} style={{ marginBottom: 16 }}>
          <Form.Item name="plan_id" label="选择计划" rules={[{ required: true, message: '请选择计划' }]} style={{ minWidth: 360 }}>
            <Select showSearch optionFilterProp="label" placeholder="选择订单池中的计划" options={plans.map((plan) => ({ value: plan.id, label: `${plan.plan_code || plan.id} · ${plan.product_id} · ${plan.quantity} · 交期 ${String(plan.required_date || '').slice(0, 10)}` }))} />
          </Form.Item>
          <Form.Item name="bom_version" label="BOM版本"><Input placeholder="CURRENT" style={{ width: 140 }} /></Form.Item>
          <Button type="primary" htmlType="submit" icon={<CalculatorOutlined />} loading={mrpLoading}>计算 MRP</Button>
        </Form>
        {mrpResult ? <>
          <Row gutter={12} style={{ marginBottom: 16 }}>
            <Col xs={12} md={6}><Statistic title="物料种类" value={mrpResult.summary?.total_materials || 0} suffix="种" /></Col>
            <Col xs={12} md={6}><Statistic title="毛需求合计" value={(mrpResult.items || []).reduce((sum: number, item: any) => sum + Number(item.required_qty || 0), 0)} /></Col>
            <Col xs={12} md={6}><Statistic title="欠料种类" value={mrpResult.summary?.shortage_count || 0} suffix="种" valueStyle={{ color: (mrpResult.summary?.shortage_count || 0) > 0 ? '#cf1322' : '#389e0d' }} /></Col>
            <Col xs={12} md={6}><Statistic title="欠料合计" value={mrpResult.summary?.total_shortage_qty || 0} valueStyle={{ color: (mrpResult.summary?.total_shortage_qty || 0) > 0 ? '#cf1322' : '#389e0d' }} /></Col>
          </Row>
          {(mrpResult.summary?.shortage_count || 0) > 0 && <Alert type="warning" showIcon icon={<WarningOutlined />} message="存在欠料，当前计划不建议直接放行" description="请根据物料编码核实库存、在途、采购 ETA 或替代料，再回到计划/排程环节处理。" style={{ marginBottom: 12 }} />}
          <Table rowKey={(row: any) => `${row.material_code}-${row.material_id || ''}`} size="small" scroll={{ x: 1050 }} dataSource={mrpResult.items || []} columns={mrpColumns} pagination={{ pageSize: 10, showSizeChanger: false }} rowClassName={(row: any) => Number(row.net_qty || 0) > 0 ? 'pmc-shortage-row' : ''} />
        </> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一张 MPS 计划后计算物料需求" />}
      </Card>
    </>
  )

  const scheduleFormPanel = (
    <>
      <Card size="small" title={<Space><RocketOutlined /> 生产排程计划</Space>}>
        <Paragraph type="secondary">以当前工厂已下达/可排程工单为输入生成 APS 方案；方案生成后可到排程中心查看甘特图、确认和下达。</Paragraph>
        <Form form={scheduleForm} {...formItemLayout} onFinish={generateSchedule} initialValues={{ mode: 'hybrid', horizon_days: 7, optimize_for: 'delivery' }} style={{ maxWidth: 720 }}>
          <Form.Item label="排程模式" name="mode"><Select options={[{ value: 'forward', label: '正排 · 尽快完成' }, { value: 'backward', label: '倒排 · 交期优先' }, { value: 'hybrid', label: '混合 · PMC 默认' }]} /></Form.Item>
          <Form.Item label="计划窗口" name="horizon_days"><Select options={[{ value: 3, label: '未来 3 天' }, { value: 7, label: '未来 7 天' }, { value: 14, label: '未来 14 天' }, { value: 30, label: '未来 30 天' }]} /></Form.Item>
          <Form.Item label="优化目标" name="optimize_for"><Select options={[{ value: 'delivery', label: '交期达成' }, { value: 'efficiency', label: '产能效率' }, { value: 'cost', label: '换线/成本' }]} /></Form.Item>
          <Form.Item label="变更说明" name="reason"><Input.TextArea rows={2} placeholder="例如：早会后重排，优先保障 A 客户交期" /></Form.Item>
          <Form.Item wrapperCol={{ offset: 7 }}><Space><Button type="primary" htmlType="submit" icon={<RocketOutlined />} loading={scheduleLoading}>生成排程方案</Button><Button onClick={() => navigate('/scheduling')} icon={<ScheduleOutlined />}>打开排程中心</Button></Space></Form.Item>
        </Form>
      </Card>
      {scheduleResult && <Card size="small" title="本次生成结果" style={{ marginTop: 16 }}>
        <Row gutter={16}><Col xs={12} md={6}><Statistic title="方案号" value={scheduleResult.schedule_code || scheduleResult.schedule?.schedule_code || '-'} /></Col><Col xs={12} md={6}><Statistic title="任务数" value={scheduleResult.total_tasks ?? scheduleResult.schedule?.total_tasks ?? 0} /></Col><Col xs={12} md={6}><Statistic title="未排任务" value={scheduleResult.unscheduled_count ?? scheduleResult.schedule?.unscheduled_count ?? 0} /></Col><Col xs={12} md={6}><Statistic title="状态" value={scheduleResult.status || scheduleResult.schedule?.status || '-'} /></Col></Row>
      </Card>}
      <Card size="small" title={<Space><FileTextOutlined /> 最近排程方案</Space>} style={{ marginTop: 16 }}>
        <Table rowKey="id" size="small" dataSource={schedules} pagination={{ pageSize: 8, showSizeChanger: false }} columns={[
          { title: '方案号', dataIndex: 'schedule_code', key: 'schedule_code', render: (value: string) => <Text code>{value}</Text> },
          { title: '模式', dataIndex: 'mode', key: 'mode' },
          { title: '窗口', key: 'horizon', render: (_: any, row: any) => `${String(row.horizon_start || '').slice(0, 10)} ~ ${String(row.horizon_end || '').slice(0, 10)}` },
          { title: '任务', dataIndex: 'total_tasks', key: 'total_tasks' },
          { title: '未排', dataIndex: 'unscheduled_count', key: 'unscheduled_count', render: (value: number) => <Text type={value > 0 ? 'danger' : 'success'}>{value || 0}</Text> },
          { title: '状态', dataIndex: 'status', key: 'status', render: (value: string) => <Tag>{value}</Tag> },
        ]} locale={{ emptyText: '暂无排程方案' }} />
      </Card>
    </>
  )

  const capacityPanel = (
    <>
      <Card size="small" title={<Space><BarChartOutlined /> 产能与负荷分析</Space>}>
        <Paragraph type="secondary">按当前有效 APS 方案汇总工位每日负荷；利用率超过 100% 自动标记超负荷，超过 85% 进入瓶颈关注区。</Paragraph>
        <Form form={capacityForm} layout="inline" onFinish={loadCapacity} initialValues={{ days: 7 }}>
          <Form.Item label="分析窗口" name="days"><Select style={{ width: 150 }} options={[{ value: 3, label: '未来 3 天' }, { value: 7, label: '未来 7 天' }, { value: 14, label: '未来 14 天' }, { value: 30, label: '未来 30 天' }]} /></Form.Item>
          <Button type="primary" htmlType="submit" icon={<LineChartOutlined />} loading={capacityLoading}>刷新负荷</Button>
        </Form>
      </Card>
      {capacityData ? <>
        <Row gutter={12} style={{ margin: '16px 0' }}>
          <Col xs={12} md={6}><Card size="small"><Statistic title="分析天数" value={capacityData.horizon_days} suffix="天" /></Card></Col>
          <Col xs={12} md={6}><Card size="small"><Statistic title="工位数" value={capacityData.resources?.length || 0} /></Card></Col>
          <Col xs={12} md={6}><Card size="small"><Statistic title="瓶颈工位" value={capacityData.bottleneck_count || 0} valueStyle={{ color: (capacityData.bottleneck_count || 0) > 0 ? '#cf1322' : '#389e0d' }} /></Card></Col>
          <Col xs={12} md={6}><Card size="small"><Statistic title="标准日产能" value={capacityData.daily_capacity_hours || 0} suffix="h" /></Card></Col>
        </Row>
        {(capacityData.bottleneck_count || 0) > 0 && <Alert type="warning" showIcon message={`发现 ${capacityData.bottleneck_count} 个瓶颈工位`} description="建议回到排程计划调整优先级、拆分批次或核实加班/外协能力。" style={{ marginBottom: 16 }} />}
        <Card size="small" title="日产能负荷明细"><Table rowKey={(row) => `${row.station_id}-${row.date}`} size="small" scroll={{ x: 800 }} dataSource={capacityRows} columns={capacityColumns} pagination={{ pageSize: 12, showSizeChanger: false }} locale={{ emptyText: '当前时间窗没有有效排程任务' }} /></Card>
      </> : <Card style={{ marginTop: 16 }}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="提交分析窗口后查看产能负荷" /></Card>}
    </>
  )

  const dohPanel = (
    <>
      <Card size="small" title={<Space><DatabaseOutlined /> 库存周转天数 DOH</Space>}>
        <Paragraph type="secondary">DOH = 可用库存 ÷ 日均需求。库存按物料编码跨仓库汇总；当前日均需求是 PMC 录入的分析口径，便于先用历史小批量数据跑通。</Paragraph>
        <Form form={dohForm} layout="inline" onFinish={calculateDoh} initialValues={{ daily_demand: 1 }}>
          <Form.Item label="物料编码" name="material_code"><Input allowClear placeholder="留空查看全部物料" style={{ width: 220 }} /></Form.Item>
          <Form.Item label="日均需求" name="daily_demand" rules={[{ required: true, message: '请输入日均需求' }]}><InputNumber min={0.01} precision={2} style={{ width: 150 }} /></Form.Item>
          <Button type="primary" htmlType="submit" icon={<LineChartOutlined />} loading={dohLoading}>计算 DOH</Button>
        </Form>
      </Card>
      {dohRows.length ? <Card size="small" title="库存周转分析结果" style={{ marginTop: 16 }}><Table rowKey="material_code" size="small" dataSource={dohRows} columns={dohColumns} pagination={{ pageSize: 12, showSizeChanger: false }} /></Card> : <Card style={{ marginTop: 16 }}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="提交物料和日均需求后查看 DOH" /></Card>}
    </>
  )

  const calendarPanel = (
    <>
      <Card size="small" title={<Space><CalendarOutlined /> 工作日历与班次</Space>}>
        <Paragraph type="secondary">工作日历以资源、星期和班次维护，是智能排程的时间基准。日期级法定假期可在 APS 日历接口中继续批量导入。</Paragraph>
        <Form form={calendarForm} layout="vertical" onFinish={submitCalendar} initialValues={{ resource_type: 'station', shift_name: '标准班', day_of_week: 0, start_time: '08:00', end_time: '20:00' }}>
          <Row gutter={12}>
            <Col xs={24} md={8}><Form.Item label="资源 / 工位编码" name="resource_id" rules={[{ required: true, message: '请输入资源编码' }]}><Input placeholder="如 ST-001" /></Form.Item></Col>
            <Col xs={12} md={5}><Form.Item label="资源类型" name="resource_type"><Select options={[{ value: 'station', label: '工位' }, { value: 'workshop', label: '车间' }, { value: 'line', label: '产线' }]} /></Form.Item></Col>
            <Col xs={12} md={5}><Form.Item label="班次名称" name="shift_name"><Input /></Form.Item></Col>
            <Col xs={12} md={6}><Form.Item label="星期" name="day_of_week"><Select options={['一', '二', '三', '四', '五', '六', '日'].map((label, value) => ({ value, label: `星期${label}` }))} /></Form.Item></Col>
          </Row>
          <Row gutter={12}>
            <Col xs={12} md={6}><Form.Item label="开始时间" name="start_time" rules={[{ required: true }]}><Input placeholder="08:00" /></Form.Item></Col>
            <Col xs={12} md={6}><Form.Item label="结束时间" name="end_time" rules={[{ required: true }]}><Input placeholder="20:00" /></Form.Item></Col>
            <Col xs={12} md={6}><Form.Item label="生效日期" name="effective_from"><Input placeholder="YYYY-MM-DD，可留空" /></Form.Item></Col>
            <Col xs={12} md={6}><Form.Item label="结束日期" name="effective_to"><Input placeholder="YYYY-MM-DD，可留空" /></Form.Item></Col>
          </Row>
          <Button type="primary" htmlType="submit" icon={<CalendarOutlined />} loading={calendarSaving}>保存班次日历</Button>
        </Form>
      </Card>
      <Card size="small" title={<Space><ScheduleOutlined /> 已配置日历</Space>} extra={<Button size="small" icon={<ReloadOutlined />} onClick={loadCalendars} loading={calendarLoading}>刷新</Button>} style={{ marginTop: 16 }}>
        <Table rowKey="id" size="small" dataSource={calendars} loading={calendarLoading} columns={calendarColumns} pagination={{ pageSize: 12, showSizeChanger: false }} locale={{ emptyText: '当前工厂尚未配置工作日历' }} />
      </Card>
    </>
  )

  return (
    <div style={{ minHeight: '100%', background: '#f5f7fb', padding: 24 }}>
      <div style={{ maxWidth: 1480, margin: '0 auto' }}>
        <Card bordered={false} style={{ marginBottom: 16, background: 'linear-gradient(135deg, #102a43 0%, #176b87 65%, #1677ff 130%)', color: '#fff' }}>
          <Space direction="vertical" size={4} style={{ width: '100%' }}>
            <Space wrap><Tag color="cyan">PMC FORMS</Tag><Tag>工厂 {factoryId}</Tag></Space>
            <Title level={2} style={{ color: '#fff', margin: '6px 0 0' }}>PMC 表单中心</Title>
            <Text style={{ color: 'rgba(255,255,255,.76)' }}>把 MPS、BOM、库存、MRP、排程、产能和 DOH 串成可执行的日常表单。</Text>
          </Space>
        </Card>

        <Alert type="info" showIcon message="推荐使用顺序：先建 MPS 计划 → 计算物料动态需求 → 查看欠料 → 生成排程 → 校核产能与库存周转" style={{ marginBottom: 16 }} />
        <Tabs
          defaultActiveKey="mrp"
          items={[
            { key: 'mrp', label: <span><CalculatorOutlined /> 物料动态计算</span>, children: mpsAndMrp },
            { key: 'schedule', label: <span><RocketOutlined /> 生产排程</span>, children: scheduleFormPanel },
            { key: 'capacity', label: <span><BarChartOutlined /> 产能负荷</span>, children: capacityPanel },
            { key: 'doh', label: <span><LineChartOutlined /> 库存 DOH</span>, children: dohPanel },
            { key: 'calendar', label: <span><CalendarOutlined /> 工作日历</span>, children: calendarPanel },
            { key: 'workbook', label: <span><FileTextOutlined /> 在线工作簿</span>, children: <PmcWorkbookPanel /> },
          ]}
        />
      </div>
    </div>
  )
}
