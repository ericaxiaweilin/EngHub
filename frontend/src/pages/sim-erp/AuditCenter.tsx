import React, { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Drawer,
  Input,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import {
  getLatestSimErpAudit,
  getSimErpAuditDetail,
  getSimErpAudits,
  SimERPAuditDetail,
  SimERPAuditSummary,
} from '../../services/simErp'

const { Paragraph, Text } = Typography

const statusColorMap: Record<string, string> = {
  accepted: 'success',
  rejected: 'error',
}

const AuditCenter: React.FC = () => {
  const [loading, setLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [audits, setAudits] = useState<SimERPAuditSummary[]>([])
  const [latestAudit, setLatestAudit] = useState<SimERPAuditSummary | null>(null)
  const [selectedAudit, setSelectedAudit] = useState<SimERPAuditDetail | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [workerRef, setWorkerRef] = useState('')
  const [finalStatus, setFinalStatus] = useState<string | undefined>(undefined)
  const [createdRange, setCreatedRange] = useState<[Dayjs | null, Dayjs | null] | null>(null)
  const [pageSize, setPageSize] = useState(10)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)

  useEffect(() => {
    void fetchAudits(page, pageSize)
  }, [page, pageSize])

  const fetchAudits = async (nextPage = page, nextPageSize = pageSize) => {
    setLoading(true)
    try {
      const [auditList, latest] = await Promise.all([
        getSimErpAudits({
          page: nextPage,
          page_size: nextPageSize,
          worker_ref: workerRef || undefined,
          final_status: finalStatus,
          created_from: createdRange?.[0]?.startOf('day').toISOString(),
          created_to: createdRange?.[1]?.endOf('day').toISOString(),
        }),
        getLatestSimErpAudit().catch(() => null),
      ])
      setAudits(auditList.items)
      setTotal(auditList.total)
      setPage(auditList.page)
      setPageSize(auditList.page_size)
      setLatestAudit(latest)
    } finally {
      setLoading(false)
    }
  }

  const exportCurrentAudits = () => {
    const rows = [
      ['simulation_id', 'final_status', 'legal_blocked', 'created_at', 'total_cost_delta', 'max_required_break_minutes', 'blocking_rules', 'warnings'],
      ...audits.map((audit) => [
        audit.simulation_id,
        audit.final_status,
        String(audit.legal_blocked),
        audit.created_at,
        String(audit.total_cost_delta),
        String(audit.max_required_break_minutes),
        audit.blocking_rules.join('|'),
        audit.warnings.join('|'),
      ]),
    ]
    const csv = rows
      .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = window.URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `sim-erp-audits-${dayjs().format('YYYYMMDD-HHmmss')}.csv`
    anchor.click()
    window.URL.revokeObjectURL(url)
  }

  const openAuditDetail = async (simulationId: string) => {
    setDrawerOpen(true)
    setDetailLoading(true)
    try {
      const detail = await getSimErpAuditDetail(simulationId)
      setSelectedAudit(detail)
    } finally {
      setDetailLoading(false)
    }
  }

  const columns: ColumnsType<SimERPAuditSummary> = [
    {
      title: '仿真ID',
      dataIndex: 'simulation_id',
      key: 'simulation_id',
      render: (value: string) => <Text code>{value.slice(0, 8)}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'final_status',
      key: 'final_status',
      render: (value: string) => <Tag color={statusColorMap[value] || 'default'}>{value}</Tag>,
    },
    {
      title: '法律阻断',
      dataIndex: 'legal_blocked',
      key: 'legal_blocked',
      render: (value: boolean) => (
        <Tag color={value ? 'error' : 'success'}>{value ? '是' : '否'}</Tag>
      ),
    },
    {
      title: '成本变动',
      dataIndex: 'total_cost_delta',
      key: 'total_cost_delta',
      render: (value: number) => `VND ${value.toLocaleString()}`,
    },
    {
      title: '强制休息',
      dataIndex: 'max_required_break_minutes',
      key: 'max_required_break_minutes',
      render: (value: number) => `${value} 分钟`,
    },
    {
      title: '阻断规则',
      dataIndex: 'blocking_rules',
      key: 'blocking_rules',
      render: (rules: string[]) => rules.length ? rules.join(', ') : '-',
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作',
      key: 'action',
      render: (_, record) => (
        <Button type="link" size="small" onClick={() => void openAuditDetail(record.simulation_id)}>
          查看详情
        </Button>
      ),
    },
  ]

  return (
    <div>
      <h2 style={{ marginBottom: '24px' }}>Sim-ERP 审计中心</h2>

      {latestAudit?.legal_blocked ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: '24px' }}
          message="最近一次仿真被法律规则阻断"
          description={`阻断规则: ${latestAudit.blocking_rules.join(', ') || '无'}。仿真 ID: ${latestAudit.simulation_id}`}
        />
      ) : null}

      <Row gutter={16} style={{ marginBottom: '24px' }}>
        <Col span={6}>
          <Card>
            <Statistic title="最近状态" value={latestAudit?.final_status || '-'} valueStyle={{ color: latestAudit?.final_status === 'rejected' ? '#f5222d' : '#52c41a' }} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="最近成本变动" value={latestAudit?.total_cost_delta || 0} prefix="VND" />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="最近强制休息" value={latestAudit?.max_required_break_minutes || 0} suffix="分钟" />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="当前列表记录数" value={audits.length} suffix="条" />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="筛选后总记录" value={total} suffix="条" />
          </Card>
        </Col>
      </Row>

      <Card style={{ marginBottom: '24px' }}>
        <Space wrap>
          <Input
            placeholder="员工标识"
            style={{ width: 200 }}
            value={workerRef}
            onChange={(event) => setWorkerRef(event.target.value)}
          />
          <DatePicker.RangePicker
            value={createdRange}
            onChange={(value) => setCreatedRange(value)}
          />
          <Select
            placeholder="状态"
            allowClear
            style={{ width: 160 }}
            value={finalStatus}
            onChange={(value) => setFinalStatus(value)}
            options={[
              { value: 'accepted', label: 'accepted' },
              { value: 'rejected', label: 'rejected' },
            ]}
          />
          <Select
            style={{ width: 140 }}
            value={pageSize}
            onChange={(value) => setPageSize(value)}
            options={[
              { value: 10, label: '10 / 页' },
              { value: 20, label: '20 / 页' },
              { value: 50, label: '50 / 页' },
            ]}
          />
          <Button
            type="primary"
            onClick={() => {
              setPage(1)
              void fetchAudits(1, pageSize)
            }}
          >
            查询
          </Button>
          <Button onClick={exportCurrentAudits}>
            导出 CSV
          </Button>
          <Button
            onClick={() => {
              setWorkerRef('')
              setFinalStatus(undefined)
              setCreatedRange(null)
              setPage(1)
              setPageSize(10)
              void fetchAudits(1, 10)
            }}
          >
            重置
          </Button>
        </Space>
      </Card>

      <Card title="审计记录">
        <Table
          rowKey="simulation_id"
          columns={columns}
          dataSource={audits}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: false,
            onChange: (nextPage) => setPage(nextPage),
          }}
        />
      </Card>

      <Drawer
        title="审计详情"
        width={720}
        open={drawerOpen}
        onClose={() => {
          setDrawerOpen(false)
          setSelectedAudit(null)
        }}
        loading={detailLoading}
      >
        {selectedAudit ? (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Descriptions bordered column={2} size="small">
              <Descriptions.Item label="仿真ID">{selectedAudit.simulation_id}</Descriptions.Item>
              <Descriptions.Item label="状态">{selectedAudit.final_status}</Descriptions.Item>
              <Descriptions.Item label="员工">{selectedAudit.worker_ref}</Descriptions.Item>
              <Descriptions.Item label="班次">{selectedAudit.shift_id}</Descriptions.Item>
              <Descriptions.Item label="任务">{selectedAudit.task_type}</Descriptions.Item>
              <Descriptions.Item label="区域">{selectedAudit.zone_id}</Descriptions.Item>
              <Descriptions.Item label="成本变动">{`VND ${selectedAudit.total_cost_delta.toLocaleString()}`}</Descriptions.Item>
              <Descriptions.Item label="处罚分">{selectedAudit.total_penalty_score}</Descriptions.Item>
            </Descriptions>

            <Card title="阻断与预警" size="small">
              <Paragraph>
                <Text strong>阻断规则:</Text> {selectedAudit.blocking_rules.join(', ') || '-'}
              </Paragraph>
              <Paragraph style={{ marginBottom: 0 }}>
                <Text strong>预警规则:</Text> {selectedAudit.warnings.join(', ') || '-'}
              </Paragraph>
            </Card>

            <Card title="物理快照" size="small">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(selectedAudit.snapshot_payload, null, 2)}
              </pre>
            </Card>

            <Card title="插件执行记录" size="small">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(selectedAudit.plugin_records_payload, null, 2)}
              </pre>
            </Card>

            <Card title="仲裁结果" size="small">
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(selectedAudit.arbiter_result_payload, null, 2)}
              </pre>
            </Card>
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}

export default AuditCenter
