/**
 * HR 人力档案 - 花名册 + 部门/工序人力分布统计
 */
import { useState, useEffect } from 'react'
import { Card, Table, Tag, Statistic, Row, Col, Select, Input, Space, Progress, Tabs } from 'antd'
import { TeamOutlined, UserOutlined, CheckCircleOutlined, ApartmentOutlined } from '@ant-design/icons'
import api from '../../services/api'

interface Employee {
  id: string
  employee_code: string
  name: string
  gender: string
  department: string
  station: string
  position: string
  shift: string
  hire_date: string
  status: string
  skill_level: string
}

interface DeptStat {
  department: string
  total: number
  stations: { station: string; total: number; active: number }[]
}

interface HrStats {
  factory_id: string
  total: number
  active: number
  departments: DeptStat[]
  shifts: { shift: string; count: number }[]
  skill_levels: { level: string; count: number }[]
  genders: { gender: string; count: number }[]
}

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  active: { color: 'green', text: '在职' },
  leave: { color: 'orange', text: '休假' },
  resigned: { color: 'red', text: '离职' },
}

const SKILL_COLORS: Record<string, string> = { L1: 'default', L2: 'blue', L3: 'cyan', L4: 'purple', L5: 'gold' }

export default function HrRoster() {
  const [stats, setStats] = useState<HrStats | null>(null)
  const [employees, setEmployees] = useState<Employee[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [loading, setLoading] = useState(false)
  const [dept, setDept] = useState<string | undefined>()
  const [station, setStation] = useState<string | undefined>()
  const [status, setStatus] = useState<string | undefined>()
  const [keyword, setKeyword] = useState('')

  // 加载统计
  useEffect(() => {
    api.get('/api/v1/hr/stats').then((res: any) => setStats(res)).catch(() => {})
  }, [])

  // 加载花名册
  const loadEmployees = () => {
    setLoading(true)
    const params: any = { page, page_size: pageSize }
    if (dept) params.department = dept
    if (station) params.station = station
    if (status) params.status = status
    if (keyword) params.keyword = keyword
    api.get('/api/v1/hr/employees', { params })
      .then((res: any) => { setEmployees(res.items || []); setTotal(res.total || 0) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadEmployees() }, [page, pageSize, dept, station, status])

  const columns = [
    { title: '工号', dataIndex: 'employee_code', width: 100 },
    { title: '姓名', dataIndex: 'name', width: 90 },
    { title: '性别', dataIndex: 'gender', width: 60 },
    { title: '部门', dataIndex: 'department', width: 120 },
    { title: '工序/岗位', dataIndex: 'station', width: 100 },
    { title: '职位', dataIndex: 'position', width: 80 },
    { title: '班次', dataIndex: 'shift', width: 80, render: (v: string) => <Tag>{v}</Tag> },
    { title: '技能', dataIndex: 'skill_level', width: 70, render: (v: string) => <Tag color={SKILL_COLORS[v]}>{v}</Tag> },
    { title: '入职日期', dataIndex: 'hire_date', width: 110 },
    { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => <Tag color={STATUS_MAP[v]?.color}>{STATUS_MAP[v]?.text || v}</Tag> },
  ]

  // 部门人力分布柱状
  const maxDept = stats ? Math.max(...stats.departments.map(d => d.total)) : 1

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 16 }}><TeamOutlined /> 人力档案</h2>

      {/* 概览统计 */}
      {stats && (
        <Row gutter={16} style={{ marginBottom: 20 }}>
          <Col span={4}>
            <Card size="small"><Statistic title="总人数" value={stats.total} prefix={<TeamOutlined />} /></Card>
          </Col>
          <Col span={4}>
            <Card size="small"><Statistic title="在职" value={stats.active} prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} /></Card>
          </Col>
          <Col span={4}>
            <Card size="small"><Statistic title="部门数" value={stats.departments.length} prefix={<ApartmentOutlined />} /></Card>
          </Col>
          <Col span={12}>
            <Card size="small" title="技能等级分布">
              <Space>
                {stats.skill_levels.map(s => (
                  <Tag key={s.level} color={SKILL_COLORS[s.level]}>{s.level}: {s.count}人</Tag>
                ))}
              </Space>
            </Card>
          </Col>
        </Row>
      )}

      <Tabs defaultActiveKey="roster" items={[
        {
          key: 'roster',
          label: '花名册',
          children: (
            <Card size="small">
              {/* 筛选栏 */}
              <Space wrap style={{ marginBottom: 12 }}>
                <Select allowClear placeholder="部门" style={{ width: 140 }} value={dept} onChange={v => { setDept(v); setStation(undefined); setPage(1) }}
                  options={stats?.departments.map(d => ({ value: d.department, label: d.department }))} />
                <Select allowClear placeholder="工序/岗位" style={{ width: 120 }} value={station} onChange={v => { setStation(v); setPage(1) }}
                  options={stats?.departments.find(d => d.department === dept)?.stations.map(s => ({ value: s.station, label: s.station }))
                    || stats?.departments.flatMap(d => d.stations).map(s => ({ value: s.station, label: s.station }))} />
                <Select allowClear placeholder="状态" style={{ width: 100 }} value={status} onChange={v => { setStatus(v); setPage(1) }}
                  options={[{ value: 'active', label: '在职' }, { value: 'leave', label: '休假' }, { value: 'resigned', label: '离职' }]} />
                <Input.Search placeholder="姓名/工号" style={{ width: 180 }} allowClear
                  onSearch={v => { setKeyword(v); setPage(1); setTimeout(loadEmployees, 0) }} />
              </Space>
              <Table
                dataSource={employees}
                columns={columns}
                rowKey="id"
                size="small"
                loading={loading}
                pagination={{
                  current: page, pageSize, total, showSizeChanger: true, showTotal: t => `共 ${t} 人`,
                  onChange: (p, ps) => { setPage(p); setPageSize(ps) },
                }}
                scroll={{ x: 900 }}
              />
            </Card>
          ),
        },
        {
          key: 'distribution',
          label: '人力分布',
          children: stats && (
            <Row gutter={16}>
              <Col span={14}>
                <Card size="small" title="部门 → 工序人力配置">
                  {stats.departments.map(d => (
                    <div key={d.department} style={{ marginBottom: 16 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>
                        {d.department} <Tag color="blue">{d.total}人</Tag>
                      </div>
                      {d.stations.map(s => (
                        <div key={s.station} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                          <span style={{ width: 80, fontSize: 12, textAlign: 'right' }}>{s.station}</span>
                          <Progress
                            percent={Math.round(s.total / maxDept * 100)}
                            format={() => `${s.total}`}
                            strokeColor={s.total > 200 ? '#f5222d' : s.total > 80 ? '#fa8c16' : '#1890ff'}
                            style={{ flex: 1, margin: 0 }}
                            size="small"
                          />
                        </div>
                      ))}
                    </div>
                  ))}
                </Card>
              </Col>
              <Col span={10}>
                <Card size="small" title="班次分布" style={{ marginBottom: 16 }}>
                  {stats.shifts.map(s => (
                    <div key={s.shift} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                      <span>{s.shift}</span>
                      <Tag>{s.count}人 ({Math.round(s.count / stats.total * 100)}%)</Tag>
                    </div>
                  ))}
                </Card>
                <Card size="small" title="性别比例">
                  {stats.genders.map(g => (
                    <div key={g.gender} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                      <span>{g.gender === '男' ? '♂ 男' : '♀ 女'}</span>
                      <Tag color={g.gender === '男' ? 'blue' : 'pink'}>{g.count}人 ({Math.round(g.count / stats.total * 100)}%)</Tag>
                    </div>
                  ))}
                </Card>
              </Col>
            </Row>
          ),
        },
      ]} />
    </div>
  )
}
