import React, { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  DatePicker,
  Descriptions,
  Drawer,
  Input,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
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

const { Text } = Typography

const statusColorMap: Record<string, string> = {
  accepted: 'success',
  rejected: 'error',
}

const AuditRecords: React.FC = () => {
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
              {selectedAudit.blocking_rules.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <Text strong style={{ color: '#f5222d' }}>阻断规则:</Text>
                  <div style={{ marginTop: 4 }}>
                    {selectedAudit.blocking_rules.map((r) => (
                      <Tag color="error" key={r} style={{ margin: '2px' }}>{r}</Tag>
                    ))}
                  </div>
                </div>
              )}
              {selectedAudit.warnings.length > 0 && (
                <div>
                  <Text strong style={{ color: '#faad14' }}>预警规则:</Text>
                  <div style={{ marginTop: 4 }}>
                    {selectedAudit.warnings.map((r) => (
                      <Tag color="warning" key={r} style={{ margin: '2px' }}>{r}</Tag>
                    ))}
                  </div>
                </div>
              )}
              {selectedAudit.blocking_rules.length === 0 && selectedAudit.warnings.length === 0 && (
                <Tag color="success">无阻断、无预警</Tag>
              )}
            </Card>

            {/* 物理快照 - 结构化 */}
            <Collapse size="small" defaultActiveKey={['snapshot']} items={[{
              key: 'snapshot',
              label: '物理快照',
              children: selectedAudit.snapshot_payload ? (
                <Descriptions column={2} size="small" bordered>
                  <Descriptions.Item label="工人">{selectedAudit.snapshot_payload.worker_ref ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="班次">{selectedAudit.snapshot_payload.shift_id ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="任务">{selectedAudit.snapshot_payload.task_type ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="区域">{selectedAudit.snapshot_payload.zone_id ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="动作">{selectedAudit.snapshot_payload.action_type ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="地形">{selectedAudit.snapshot_payload.terrain ?? selectedAudit.snapshot_payload.environment?.terrain ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="温度">{selectedAudit.snapshot_payload.temperature_c ?? selectedAudit.snapshot_payload.environment?.temperature_c ?? '-'} °C</Descriptions.Item>
                  <Descriptions.Item label="湿度">{selectedAudit.snapshot_payload.humidity_percent ?? selectedAudit.snapshot_payload.environment?.humidity_percent ?? '-'} %</Descriptions.Item>
                  <Descriptions.Item label="噪声">{selectedAudit.snapshot_payload.noise_db ?? selectedAudit.snapshot_payload.environment?.noise_db ?? '-'} dB</Descriptions.Item>
                  <Descriptions.Item label="步数">{selectedAudit.snapshot_payload.step_count ?? '-'}</Descriptions.Item>
                  <Descriptions.Item label="距离">{selectedAudit.snapshot_payload.distance_meters ?? '-'} m</Descriptions.Item>
                  <Descriptions.Item label="负重">{selectedAudit.snapshot_payload.load_weight_kg ?? '-'} kg</Descriptions.Item>
                  <Descriptions.Item label="姿态角">{selectedAudit.snapshot_payload.posture_angle_deg ?? '-'} °</Descriptions.Item>
                  <Descriptions.Item label="连续作业">{selectedAudit.snapshot_payload.continuous_work_minutes ?? '-'} min</Descriptions.Item>
                  <Descriptions.Item label="疲劳评分">
                    <Space>
                      <Progress
                        percent={Math.min(100, selectedAudit.snapshot_payload.fatigue_score ?? 0)}
                        size="small"
                        style={{ width: 80 }}
                        strokeColor={(selectedAudit.snapshot_payload.fatigue_score ?? 0) > 70 ? '#f5222d' : (selectedAudit.snapshot_payload.fatigue_score ?? 0) > 40 ? '#faad14' : '#52c41a'}
                      />
                      <Text>{(selectedAudit.snapshot_payload.fatigue_score ?? 0).toFixed(1)}</Text>
                    </Space>
                  </Descriptions.Item>
                  <Descriptions.Item label="能耗">{selectedAudit.snapshot_payload.energy_kcal ?? '-'} kcal</Descriptions.Item>
                </Descriptions>
              ) : <Text type="secondary">无快照数据</Text>,
            }]} />

            {/* 插件执行记录 - 结构化 */}
            <Collapse size="small" items={[{
              key: 'plugins',
              label: `插件执行记录 (${Array.isArray(selectedAudit.plugin_records_payload) ? selectedAudit.plugin_records_payload.length : 0})`,
              children: Array.isArray(selectedAudit.plugin_records_payload) && selectedAudit.plugin_records_payload.length > 0 ? (
                <Table
                  size="small"
                  rowKey={(_, i) => String(i)}
                  dataSource={selectedAudit.plugin_records_payload}
                  pagination={false}
                  columns={[
                    {
                      title: '插件', key: 'name', width: 180,
                      render: (_: any, r: any) => (
                        <Tooltip title={`v${r.manifest?.plugin_version ?? r.plugin_version ?? '?'} | 规则 v${r.manifest?.rule_version ?? r.rule_version ?? '?'}`}>
                          <Text code style={{ fontSize: 11 }}>{r.manifest?.plugin_name ?? r.plugin_name ?? '-'}</Text>
                        </Tooltip>
                      ),
                    },
                    {
                      title: '优先级', key: 'priority', width: 70,
                      render: (_: any, r: any) => {
                        const p = r.manifest?.priority ?? r.priority ?? '-'
                        const colorMap: Record<string, string> = { P0: 'red', P1: 'orange', P2: 'blue', P3: 'default' }
                        return <Tag color={colorMap[p] || 'default'}>{p}</Tag>
                      },
                    },
                    {
                      title: '耗时', key: 'duration', width: 80, align: 'right',
                      render: (_: any, r: any) => `${(r.duration_ms ?? 0).toFixed(1)} ms`,
                    },
                    {
                      title: '状态', key: 'status', width: 70,
                      render: (_: any, r: any) => r.status === 'ok'
                        ? <Tag color="success">OK</Tag>
                        : <Tag color="error">{r.error || r.status}</Tag>,
                    },
                    {
                      title: '裁决', key: 'decisions', ellipsis: true,
                      render: (_: any, r: any) => {
                        const decisions = r.decisions || []
                        if (!decisions.length) return <Text type="secondary">无</Text>
                        return (
                          <Space wrap size={2}>
                            {decisions.map((d: any, di: number) => (
                              <Tooltip key={di} title={d.message}>
                                <Tag
                                  color={d.blocking ? 'error' : d.decision_type === 'WARNING' ? 'warning' : 'processing'}
                                  style={{ fontSize: 10, margin: 0 }}
                                >
                                  {d.rule_code}
                                </Tag>
                              </Tooltip>
                            ))}
                          </Space>
                        )
                      },
                    },
                  ]}
                />
              ) : <Text type="secondary">无插件记录</Text>,
            }]} />

            {/* 仲裁结果 - 结构化 */}
            <Collapse size="small" items={[{
              key: 'arbiter',
              label: '仲裁结果',
              children: selectedAudit.arbiter_result_payload ? (
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  <Descriptions column={2} size="small" bordered>
                    <Descriptions.Item label="最终状态">
                      <Tag color={selectedAudit.arbiter_result_payload.final_status === 'accepted' ? 'success' : 'error'}>
                        {selectedAudit.arbiter_result_payload.final_status}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="法律阻断">
                      <Tag color={selectedAudit.arbiter_result_payload.legal_blocked ? 'error' : 'success'}>
                        {selectedAudit.arbiter_result_payload.legal_blocked ? '是' : '否'}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="胜出优先级">
                      {selectedAudit.arbiter_result_payload.winning_priority || '-'}
                    </Descriptions.Item>
                    <Descriptions.Item label="总罚分">
                      <Text type={selectedAudit.arbiter_result_payload.total_penalty_score > 0 ? 'danger' : undefined}>
                        {selectedAudit.arbiter_result_payload.total_penalty_score ?? 0}
                      </Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="成本变动">
                      VND {(selectedAudit.arbiter_result_payload.total_cost_delta ?? 0).toLocaleString()}
                    </Descriptions.Item>
                    <Descriptions.Item label="强制休息">
                      {selectedAudit.arbiter_result_payload.max_required_break_minutes ?? 0} 分钟
                    </Descriptions.Item>
                  </Descriptions>

                  {/* 强制措施 */}
                  {Array.isArray(selectedAudit.arbiter_result_payload.applied_actions) &&
                    selectedAudit.arbiter_result_payload.applied_actions.length > 0 && (
                    <Card size="small" title="强制措施">
                      {selectedAudit.arbiter_result_payload.applied_actions.map((a: any, i: number) => (
                        <div key={i} style={{ marginBottom: 6, padding: '4px 8px', background: '#f0f5ff', borderRadius: 4 }}>
                          <Text strong style={{ fontSize: 12 }}>{a.action_code}</Text>
                          <Text style={{ fontSize: 12, marginLeft: 8 }}>{a.description}</Text>
                          {a.break_minutes > 0 && <Tag color="blue" style={{ marginLeft: 8 }}>休息 {a.break_minutes} min</Tag>}
                        </div>
                      ))}
                    </Card>
                  )}

                  {/* 全部裁决 */}
                  {Array.isArray(selectedAudit.arbiter_result_payload.decisions) &&
                    selectedAudit.arbiter_result_payload.decisions.length > 0 && (
                    <Card size="small" title={`全部裁决 (${selectedAudit.arbiter_result_payload.decisions.length})`}>
                      <Table
                        size="small"
                        rowKey={(_: any, i) => String(i)}
                        dataSource={selectedAudit.arbiter_result_payload.decisions}
                        pagination={false}
                        columns={[
                          { title: '规则', dataIndex: 'rule_code', width: 140, render: (v: string) => <Text code style={{ fontSize: 11 }}>{v}</Text> },
                          {
                            title: '类型', dataIndex: 'decision_type', width: 110,
                            render: (v: string) => {
                              const c: Record<string, string> = { VIOLATION: 'error', WARNING: 'warning', REQUIRED_ACTION: 'processing', COST_MODIFIER: 'gold', ADVISORY: 'default' }
                              return <Tag color={c[v] || 'default'}>{v}</Tag>
                            },
                          },
                          { title: '信息', dataIndex: 'message', ellipsis: true },
                          {
                            title: '阻断', dataIndex: 'blocking', width: 60, align: 'center',
                            render: (v: boolean) => v ? <Tag color="error">是</Tag> : <Tag color="success">否</Tag>,
                          },
                          {
                            title: '成本Δ', dataIndex: 'cost_delta', width: 80, align: 'right',
                            render: (v: number) => v ? <Text type={v > 0 ? 'danger' : 'success'}>{v > 0 ? '+' : ''}{v.toLocaleString()}</Text> : '-',
                          },
                        ]}
                      />
                    </Card>
                  )}
                </Space>
              ) : <Text type="secondary">无仲裁数据</Text>,
            }]} />
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}

export default AuditRecords
