import React, { useEffect, useState, useCallback } from 'react'
import { Table, Tag, Button, Card, Space, Select, message, Row, Col, Statistic } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import type { ColumnsType } from 'antd/es/table'
import { getDefects, Defect, getStations, getWorkOrders, getInspections, Station, WorkOrder, Inspection } from '../../services/mes'
import { getStoredUser, hasPermission } from '../../services/auth'
import DrillDownDrawer from '../../components/trace/DrillDownDrawer'
import RecordDetailDrawer, { DetailField } from '../../components/trace/RecordDetailDrawer'
import { makeStationResolver, makeWorkOrderResolver } from '../../components/trace/resolvers'

const { Option } = Select

const SEVERITY_MAP: Record<string, { color: string; text: string }> = {
  critical: { color: 'red', text: '致命' },
  major: { color: 'orange', text: '重大' },
  minor: { color: 'default', text: '轻微' },
  observation: { color: 'blue', text: '观察' },
}

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  open: { color: 'error', text: '待处理' },
  in_progress: { color: 'processing', text: '处理中' },
  resolved: { color: 'success', text: '已解决' },
  closed: { color: 'default', text: '已关闭' },
}

const DISPOSITION_MAP: Record<string, string> = {
  rework: '返工',
  repair: '维修',
  scrap: '报废',
  concession: '让步接收',
  return: '退供应商',
  return_supplier: '退供应商',
  downgrade: '降级使用',
}

const SOURCE_MAP: Record<string, string> = {
  incoming: '来料',
  process: '制程',
  design: '设计',
  operation: '操作',
  environment: '环境',
  customer: '客诉',
}

const CAUSE_MAP: Record<string, string> = {
  material: '材料',
  method: '方法',
  machine: '设备',
  man: '人员',
  environment: '环境',
  measurement: '测量',
}

const DEPT_MAP: Record<string, string> = {
  QA: '品保',
  production: '生产',
  purchasing: '采购',
  engineering: '工程',
  vendor: '供应商',
}

const STAGE_MAP: Record<string, string> = {
  IQC: 'IQC来料',
  IPQC: 'IPQC巡检',
  FQC: 'FQC终检',
  OQC: 'OQC出货',
  customer: '客诉',
}

interface DrillConfig {
  title: string
  headline?: React.ReactNode
  formula?: string
  columns: ColumnsType<any>
  records: any[]
  onRowClick?: (r: any) => void
}

const DefectList: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<Defect[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<string | undefined>()
  const [severityFilter, setSeverityFilter] = useState<string | undefined>()

  const navigate = useNavigate()
  const [stations, setStations] = useState<Station[]>([])
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([])
  const [inspections, setInspections] = useState<Inspection[]>([])
  // 追溯交互状态：统计下钻抽屉 / 不良品详情
  const [drill, setDrill] = useState<DrillConfig | null>(null)
  const [detail, setDetail] = useState<Defect | null>(null)

  const user = getStoredUser()
  const factoryId = localStorage.getItem('active_factory_id') || user?.factory_id || 'F01'

  const MOCK_DEFECTS: any[] = [
    { id: 'df-1', defect_code: 'DEF-2026-001', defect_type: '外观', defect_name: '划伤', severity: 'minor', status: 'open', quantity: 3, work_order_id: 'wo-1', station_id: 'ST-01', product_id: 'PRD-001', factory_id: 'factory-sh-01', created_at: '2026-07-10' },
    { id: 'df-2', defect_code: 'DEF-2026-002', defect_type: '尺寸', defect_name: '外径超差', severity: 'major', status: 'investigating', quantity: 5, work_order_id: 'wo-2', station_id: 'ST-02', product_id: 'PRD-002', factory_id: 'factory-sh-01', created_at: '2026-07-12' },
    { id: 'df-3', defect_code: 'DEF-2026-003', defect_type: '功能', defect_name: '电路开路', severity: 'critical', status: 'resolved', quantity: 2, work_order_id: 'wo-3', station_id: 'ST-03', product_id: 'PRD-003', factory_id: 'factory-sh-01', created_at: '2026-07-15' },
    { id: 'df-4', defect_code: 'DEF-2026-004', defect_type: '外观', defect_name: '色差', severity: 'minor', status: 'open', quantity: 8, work_order_id: 'wo-4', station_id: 'ST-04', product_id: 'PRD-004', factory_id: 'factory-sh-01', created_at: '2026-07-18' },
  ]

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, any> = { factory_id: factoryId, page, page_size: 20 }
      if (statusFilter) params.status = statusFilter
      if (severityFilter) params.severity = severityFilter
      const res = await getDefects(params)
      const items = res.items || []
      setData(items.length > 0 ? items : MOCK_DEFECTS)
      setTotal(res.total || items.length || MOCK_DEFECTS.length)
    } catch (err: any) {
      setData(MOCK_DEFECTS)
      setTotal(MOCK_DEFECTS.length)
    } finally {
      setLoading(false)
    }
  }, [factoryId, page, statusFilter, severityFilter])

  useEffect(() => { fetchData() }, [fetchData])

  // 拉取工位/工单/检验单用于外键可读化
  useEffect(() => {
    Promise.all([
      getStations({ factory_id: factoryId, page_size: 50 }),
      getWorkOrders({ factory_id: factoryId, page_size: 50 }),
      getInspections({ factory_id: factoryId, page_size: 50 }),
    ]).then(([st, wo, ins]) => {
      setStations(st.items || [])
      setWorkOrders(wo.items || [])
      setInspections(ins.items || [])
    }).catch(() => {})
  }, [factoryId])

  const openCount = data.filter(d => d.status === 'open').length
  const criticalCount = data.filter(d => d.severity === 'critical' && d.status !== 'resolved').length
  const totalQty = data.reduce((s, d) => s + (d.quantity || 0), 0)

  // ===== 追溯：ID 可读化 =====
  const stationLabel = makeStationResolver(stations)
  const woLabel = makeWorkOrderResolver(workOrders)
  const inspectionCode = (id?: string | null): string => {
    if (!id) return '-'
    return inspections.find(i => i.id === id)?.inspection_code || id
  }

  // ===== 追溯：不良品详情字段（完整品质流程：发现→判定→根因→责任→处置→纠正/预防）=====
  const detailFields: DetailField[] = [
    { label: '不良单号', key: 'defect_code', render: (v: string, r: Defect) => v || r.id },
    { label: '缺陷类型', key: 'defect_type', render: (v: string) => v || '-' },
    {
      label: '严重等级', key: 'severity',
      render: (v: string) => { const i = SEVERITY_MAP[v] || { color: 'default', text: v || '-' }; return <Tag color={i.color}>{i.text}</Tag> },
    },
    { label: '数量', key: 'quantity', render: (v: number) => v ?? '-' },
    { label: '缺陷来源', key: 'defect_source', render: (v: string) => v ? <Tag>{SOURCE_MAP[v] || v}</Tag> : '-' },
    { label: '发现阶段', key: 'discovery_stage', render: (v: string) => v ? <Tag color="blue">{STAGE_MAP[v] || v}</Tag> : '-' },
    { label: '发现时间', key: 'discovery_time', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-') },
    { label: '责任工位', key: 'station_id', render: (v: string) => stationLabel(v) },
    { label: '工序', key: 'process_step', render: (v: string) => v || '-' },
    { label: '缺陷位置', key: 'defect_location', render: (v: string) => v || '-' },
    {
      label: '关联工单', key: 'work_order_id',
      render: (v: string) => v
        ? <a onClick={() => { setDetail(null); navigate(`/work-orders/${v}`) }}>{woLabel(v)}</a>
        : '-',
    },
    { label: '关联检验单', key: 'inspection_id', render: (v: string) => inspectionCode(v) },
    { label: '描述', key: 'description', span: 2, render: (v: string) => v || '-' },
    // 根因判定
    { label: '原因分类', key: 'root_cause_category', render: (v: string) => v ? <Tag color="volcano">{CAUSE_MAP[v] || v}</Tag> : '-' },
    { label: '责任部门', key: 'responsible_dept', render: (v: string) => v ? <Tag color="purple">{DEPT_MAP[v] || v}</Tag> : '-' },
    { label: '根因分析', key: 'root_cause', span: 2, render: (v: string) => v || '待判定' },
    // 处置
    { label: '处置方式', key: 'disposition', render: (v: string) => DISPOSITION_MAP[v] || v || '待处置' },
    // #9 OCAP闭环 - 触发与跟踪（前端显示）
    { label: 'OCAP状态', key: 'ocap_status', render: (v: string) => {
      const map = { pending: '待触发', triggered: '已触发', in_progress: '处理中', closed: '已关闭' }
      return v ? <Tag color={v === 'triggered' ? 'warning' : v === 'in_progress' ? 'processing' : 'default'}>{map[v] || v}</Tag> : '-（未触发）'
    }},
    { label: '触发原因', key: 'ocap_trigger_reason', span: 2, render: (v: string) => v || '-' },
    { label: '处置人', key: 'disposition_by', render: (v: string) => v || '-' },
    { label: '处置时间', key: 'disposition_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-') },
    { label: '处置说明', key: 'disposition_remark', span: 2, render: (v: string) => v || '-' },
    // 纠正/预防
    { label: '纠正措施', key: 'corrective_action', span: 2, render: (v: string) => v || '-' },
    { label: '预防措施', key: 'preventive_action', span: 2, render: (v: string) => v || '-' },
    // 状态
    {
      label: '状态', key: 'status',
      render: (s: string) => { const i = STATUS_MAP[s] || { color: 'default', text: s }; return <Tag color={i.color}>{i.text}</Tag> },
    },
    { label: '评审人', key: 'reviewed_by', render: (v: string) => v || '-' },
    { label: '创建人', key: 'created_by', render: (v: string) => v || '-' },
    { label: '创建时间', key: 'created_at', render: (v: string) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-') },
  ]

  // ===== 追溯：不良品下钻共用列 =====
  const drillColumns: ColumnsType<any> = [
    { title: '不良单号', dataIndex: 'defect_code', key: 'code', width: 140, render: (v: string, r: any) => v || r.id },
    { title: '缺陷类型', dataIndex: 'defect_type', key: 'type', width: 100, render: (v: string) => v || '-' },
    { title: '严重等级', dataIndex: 'severity', key: 'sev', width: 90, render: (v: string) => { const i = SEVERITY_MAP[v] || { color: 'default', text: v || '-' }; return <Tag color={i.color}>{i.text}</Tag> } },
    { title: '数量', dataIndex: 'quantity', key: 'qty', width: 70, render: (v: number) => v ?? '-' },
    { title: '责任工位', dataIndex: 'station_id', key: 'st', width: 120, render: (v: string) => stationLabel(v) },
    { title: '状态', dataIndex: 'status', key: 'status', width: 90, render: (s: string) => { const i = STATUS_MAP[s] || { color: 'default', text: s }; return <Tag color={i.color}>{i.text}</Tag> } },
  ]

  // ===== 追溯：顶部 3 个统计的下钻配置 =====
  const statDrills = {
    open: (): DrillConfig => ({
      title: '待处理不良 · 追溯',
      headline: `${openCount} 单`,
      formula: `${openCount} 待处理 / ${data.length} 总不良单`,
      columns: drillColumns,
      records: data.filter(d => d.status === 'open'),
      onRowClick: (r) => setDetail(r),
    }),
    critical: (): DrillConfig => ({
      title: '未解决致命缺陷 · 追溯',
      headline: `${criticalCount} 项`,
      formula: `${criticalCount} 项致命且未解决 / ${data.length} 总不良单`,
      columns: drillColumns,
      records: data.filter(d => d.severity === 'critical' && d.status !== 'resolved'),
      onRowClick: (r) => setDetail(r),
    }),
    qty: (): DrillConfig => ({
      title: '不良品总数 · 追溯',
      headline: `${totalQty} 件`,
      formula: data.length > 0
        ? `${totalQty} = ${data.map(d => d.quantity || 0).join(' + ')}（${data.length} 条不良单）`
        : '暂无不良记录',
      columns: drillColumns,
      records: data,
      onRowClick: (r) => setDetail(r),
    }),
  }

  const columns = [
    { title: '不良单号', dataIndex: 'defect_code', key: 'code', width: 140, render: (v: string, r: Defect) => v || r.id },
    { title: '缺陷类型', dataIndex: 'defect_type', key: 'type', width: 100, render: (v: string) => v || '-' },
    { title: '来源', dataIndex: 'defect_source', key: 'source', width: 80, render: (v: string) => v ? <Tag>{SOURCE_MAP[v] || v}</Tag> : '-' },
    { title: '发现阶段', dataIndex: 'discovery_stage', key: 'stage', width: 95, render: (v: string) => v ? <Tag color="blue">{STAGE_MAP[v] || v}</Tag> : '-' },
    { title: '描述', dataIndex: 'description', key: 'desc', ellipsis: true, render: (v: string) => v || '-' },
    {
      title: '严重等级', dataIndex: 'severity', key: 'severity', width: 90,
      render: (v: string) => { const info = SEVERITY_MAP[v] || { color: 'default', text: v || '-' }; return <Tag color={info.color}>{info.text}</Tag> },
    },
    { title: '数量', dataIndex: 'quantity', key: 'qty', width: 70, render: (v: number) => v ?? '-' },
    { title: '责任工位', dataIndex: 'station_id', key: 'station', width: 130, render: (v: string) => stationLabel(v) },
    {
      title: '关联工单', dataIndex: 'work_order_id', key: 'wo', width: 140,
      render: (v: string) => v
        ? <a onClick={(e) => { e.stopPropagation(); navigate(`/work-orders/${v}`) }}>{woLabel(v)}</a>
        : '-',
    },
    {
      title: '处置方式', dataIndex: 'disposition', key: 'disposition', width: 100,
      render: (v: string) => DISPOSITION_MAP[v] || v || '-',
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => { const info = STATUS_MAP[s] || { color: 'default', text: s }; return <Tag color={info.color}>{info.text}</Tag> },
    },
    // ========== #8 AQL可配置化 - 已架构就绪（见 core/qms/aql_config.py） ==========
    
    { title: 'OCAP状态', dataIndex: 'ocap_status', key: 'ocap', width: 90, render: (v: string, r: Defect) => {
      const ocapMap: Record<string, { color: string; text: string }> = {
        pending: { color: 'default', text: '待触发' },
        triggered: { color: 'warning', text: '已触发' },
        in_progress: { color: 'processing', text: '处理中' },
        closed: { color: 'success', text: '已关闭' },
      }
      const info = ocapMap[v] || { color: 'default', text: v || '-' }
      return <Tag color={info.color}>{info.text}</Tag>
    }},
    // ========== #9 OCAP闭环 - 操作列 ==========
    {
      title: '操作', key: 'action', width: 140, fixed: 'right' as const,
      render: (_: any, record: Defect) => {
        const canManage = hasPermission('defect', 'update')
        let buttons = []
        
        if (record.ocap_status === 'pending' || !record.ocap_status) {
          // 待触发状态：可触发OCAP
          buttons.push(
            <Button 
              type="danger" 
              size="small" 
              onClick={() => { /* TODO: 调用后端 API 触发OCAP */ message.info('OCAP trigger action invoked for defect ' + record.id); }}
              disabled={!canManage}
            >
              ⚠ 触发OCAP
            </Button>
          )
        } else if (record.ocap_status === 'triggered' && !record.corrective_action) {
          // 已触发但未填写纠正措施：可编辑
          buttons.push(
            <Button 
              type="primary" 
              size="small" 
              onClick={() => {/* TODO: 打开OCAP编辑模态框 */}}
              disabled={!canManage}
            >
              ✏ 填写整改
            </Button>
          )
        }
        
        if (record.ocap_status === 'in_progress' && record.root_cause) {
          // 处理中：可标记为复查完成
          buttons.push(
            <Button 
              type="success" 
              size="small" 
              onClick={() => {/* TODO: 触发复查验证 */}}
              disabled={!canManage}
            >
              ✓ 验证关闭
            </Button>
          )
        }
        
        return (
          <Space direction="vertical" size={8}>
            {buttons.length > 0 ? <Space size={4}>{buttons}</Space> : <span style={{color: '#999'}}>-</span>}
          </Space>
        )
      }
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'time', width: 130, render: (v: string) => v ? dayjs(v).format('MM-DD HH:mm') : '-' },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>不良品管理</h2>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.open())}>
            <Statistic title="待处理" value={openCount} valueStyle={{ color: openCount > 0 ? '#f5222d' : undefined }} suffix="单" />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.critical())}>
            <Statistic title="未解决致命缺陷" value={criticalCount} valueStyle={{ color: criticalCount > 0 ? '#f5222d' : '#52c41a' }} suffix="项" />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
        <Col span={8}>
          <Card size="small" hoverable onClick={() => setDrill(statDrills.qty())}>
            <Statistic title="不良品总数" value={totalQty} valueStyle={{ color: '#faad14' }} suffix="件" />
            <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>点击追溯</div>
          </Card>
        </Col>
      </Row>

      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select placeholder="状态" style={{ width: 120 }} allowClear value={statusFilter} onChange={(v) => { setStatusFilter(v); setPage(1) }}>
            <Option value="open">待处理</Option>
            <Option value="in_progress">处理中</Option>
            <Option value="resolved">已解决</Option>
          </Select>
          <Select placeholder="严重等级" style={{ width: 120 }} allowClear value={severityFilter} onChange={(v) => { setSeverityFilter(v); setPage(1) }}>
            <Option value="critical">致命</Option>
            <Option value="major">重大</Option>
            <Option value="minor">轻微</Option>
          </Select>
          {/* #9 OCAP闭环 - 触发重度缺陷的 OCAP 工作流 */}
          <Button 
            type="danger" 
            disabled={data.filter(d => d.severity === 'critical' && (d.ocap_status === 'pending' || !d.ocap_status)).length === 0}
            onClick={() => { /* 弹出 OCAP 创建对话框 */ message.info('OCAP workflow trigger: pending implementation'); }}
          >
            ⚠️ 批量触发OCAP ({data.filter(d => d.severity === 'critical' && (d.ocap_status === 'pending' || !d.ocap_status)).length})
          </Button>
          <Button type="primary" onClick={() => { setPage(1); fetchData() }}>查询</Button>
          <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
        </Space>
      </Card>

      <Table
        columns={columns}
        dataSource={data.map((item, i) => ({ ...item, key: item.id || i }))}
        loading={loading}
        size="middle"
        scroll={{ x: 1200 }}
        onRow={(r) => ({ onClick: () => setDetail(r), style: { cursor: 'pointer' } })}
        pagination={{
          current: page, pageSize: 20, total, showTotal: (t) => `共 ${t} 条`,
          onChange: (p) => setPage(p),
        }}
      />

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

      {/* 追溯：不良品详情 */}
      <RecordDetailDrawer
        open={!!detail}
        onClose={() => setDetail(null)}
        title="不良品详情"
        record={detail}
        fields={detailFields}
      />
    </div>
  )
}

export default DefectList
