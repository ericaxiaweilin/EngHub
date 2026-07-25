/**
 * HR 人力档案 - 花名册 + 部门/工序人力分布 + 员工技能档案 + 人力调配
 */
import { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Statistic, Row, Col, Select, Input, Space, Progress, Tabs,
  Drawer, Descriptions, Button, Modal, message, Popconfirm, Empty,
} from 'antd'
import {
  TeamOutlined, CheckCircleOutlined, ApartmentOutlined, PlusOutlined,
  DeleteOutlined, SwapOutlined, SafetyCertificateOutlined, UserOutlined,
} from '@ant-design/icons'
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
  height_cm?: number | null
  weight_kg?: number | null
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

interface SkillItem { id: number; code: string; name: string }
interface SkillGroup { category: string; skills: SkillItem[] }
interface EmpSkill {
  skill_id: number
  code: string
  name: string
  category: string
  level: string
  certified_date?: string | null
  expiry_date?: string | null
  is_valid: boolean
}
interface Candidate {
  id: string
  employee_code: string
  name: string
  gender: string
  height_cm?: number | null
  weight_kg?: number | null
  department: string
  station: string
  shift: string
  skill_level: string
  matched_skill: { id: number; code: string; name: string; category: string; level: string }
}

const STATUS_MAP: Record<string, { color: string; text: string }> = {
  active: { color: 'green', text: '在职' },
  leave: { color: 'orange', text: '休假' },
  resigned: { color: 'red', text: '离职' },
}

const SKILL_COLORS: Record<string, string> = { L1: 'default', L2: 'blue', L3: 'cyan', L4: 'purple', L5: 'gold' }
const LEVEL_OPTIONS = ['L1', 'L2', 'L3', 'L4', 'L5'].map(l => ({ value: l, label: l }))

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

  // 技能库
  const [skillLibrary, setSkillLibrary] = useState<SkillGroup[]>([])

  // 员工详情抽屉
  const [detailVisible, setDetailVisible] = useState(false)
  const [currentEmp, setCurrentEmp] = useState<Employee | null>(null)
  const [empSkills, setEmpSkills] = useState<EmpSkill[]>([])
  const [empSkillsLoading, setEmpSkillsLoading] = useState(false)

  // 添加技能弹窗
  const [addSkillVisible, setAddSkillVisible] = useState(false)
  const [newSkillId, setNewSkillId] = useState<number | undefined>()
  const [newSkillLevel, setNewSkillLevel] = useState<string>('L1')

  // 人力调配
  const [dispatchCategory, setDispatchCategory] = useState<string | undefined>()
  const [dispatchSkillId, setDispatchSkillId] = useState<number | undefined>()
  const [dispatchMinLevel, setDispatchMinLevel] = useState<string>('L2')
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [candidatesLoading, setCandidatesLoading] = useState(false)

  // 加载统计 + 技能库
  useEffect(() => {
    api.get('/api/v1/hr/stats').then((res: any) => setStats(res)).catch(() => {})
    api.get('/api/v1/hr/skill-library').then((res: any) => setSkillLibrary(res || [])).catch(() => {})
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

  // ── 员工详情抽屉 ──
  const loadEmpSkills = (empId: string) => {
    setEmpSkillsLoading(true)
    api.get(`/api/v1/hr/employees/${empId}/skills`)
      .then((res: any) => setEmpSkills(res || []))
      .catch(() => setEmpSkills([]))
      .finally(() => setEmpSkillsLoading(false))
  }

  const openDetail = (emp: Employee) => {
    setCurrentEmp(emp)
    setDetailVisible(true)
    loadEmpSkills(emp.id)
  }

  const handleAddSkill = () => {
    if (!currentEmp || !newSkillId) { message.warning('请选择技能'); return }
    api.post(`/api/v1/hr/employees/${currentEmp.id}/skills`, { skill_id: newSkillId, level: newSkillLevel })
      .then(() => {
        message.success('技能已分配')
        setAddSkillVisible(false)
        setNewSkillId(undefined)
        setNewSkillLevel('L1')
        loadEmpSkills(currentEmp.id)
      })
      .catch(() => {})
  }

  const handleRemoveSkill = (skillId: number) => {
    if (!currentEmp) return
    api.delete(`/api/v1/hr/employees/${currentEmp.id}/skills/${skillId}`)
      .then(() => { message.success('已移除'); loadEmpSkills(currentEmp.id) })
      .catch(() => {})
  }

  // ── 人力调配查询 ──
  const queryDispatch = () => {
    if (!dispatchCategory && !dispatchSkillId) { message.warning('请选择工序大类或具体技能'); return }
    setCandidatesLoading(true)
    const params: any = { min_level: dispatchMinLevel, limit: 200 }
    if (dispatchCategory) params.category = dispatchCategory
    if (dispatchSkillId) params.skill_id = dispatchSkillId
    api.get('/api/v1/hr/dispatch-candidates', { params })
      .then((res: any) => setCandidates(res.items || []))
      .catch(() => setCandidates([]))
      .finally(() => setCandidatesLoading(false))
  }

  const columns = [
    { title: '工号', dataIndex: 'employee_code', width: 100 },
    { title: '姓名', dataIndex: 'name', width: 90 },
    { title: '性别', dataIndex: 'gender', width: 60 },
    {
      title: '身高(cm)', dataIndex: 'height_cm', width: 85,
      render: (v: number | null) => (v != null ? v : '-'),
    },
    {
      title: '体重(kg)', dataIndex: 'weight_kg', width: 85,
      render: (v: number | null) => (v != null ? v : '-'),
    },
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

  // 调配候选技能选项（按所选大类过滤）
  const dispatchSkillOptions = dispatchCategory
    ? (skillLibrary.find(g => g.category === dispatchCategory)?.skills || [])
    : skillLibrary.flatMap(g => g.skills)

  // 添加技能弹窗的分组选项
  const groupedSkillOptions = skillLibrary.map(g => ({
    label: g.category,
    options: g.skills.map(s => ({ value: s.id, label: `${s.name}（${s.code}）` })),
  }))

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
                onRow={(record) => ({ onClick: () => openDetail(record), style: { cursor: 'pointer' } })}
                pagination={{
                  current: page, pageSize, total, showSizeChanger: true, showTotal: t => `共 ${t} 人`,
                  onChange: (p, ps) => { setPage(p); setPageSize(ps) },
                }}
                scroll={{ x: 1100 }}
              />
            </Card>
          ),
        },
        {
          key: 'dispatch',
          label: <span><SwapOutlined /> 人力调配</span>,
          children: (
            <Card size="small" title="按工序技能查找可顶岗员工">
              <Space wrap style={{ marginBottom: 16 }}>
                <Select allowClear placeholder="工序大类" style={{ width: 140 }} value={dispatchCategory}
                  onChange={v => { setDispatchCategory(v); setDispatchSkillId(undefined) }}
                  options={skillLibrary.map(g => ({ value: g.category, label: g.category }))} />
                <Select allowClear showSearch placeholder="具体技能（可选）" style={{ width: 180 }} value={dispatchSkillId}
                  onChange={v => setDispatchSkillId(v)}
                  optionFilterProp="label"
                  options={dispatchSkillOptions.map(s => ({ value: s.id, label: `${s.name}（${s.code}）` }))} />
                <Select placeholder="最低等级" style={{ width: 110 }} value={dispatchMinLevel}
                  onChange={v => setDispatchMinLevel(v)} options={LEVEL_OPTIONS} />
                <Button type="primary" icon={<SwapOutlined />} onClick={queryDispatch} loading={candidatesLoading}>查询候选人</Button>
              </Space>
              {candidates.length > 0 ? (
                <Table
                  dataSource={candidates}
                  rowKey={(r) => r.id + '-' + r.matched_skill.id}
                  size="small"
                  loading={candidatesLoading}
                  pagination={{ pageSize: 20, showTotal: t => `共 ${t} 名候选人` }}
                  scroll={{ x: 1000 }}
                  columns={[
                    { title: '工号', dataIndex: 'employee_code', width: 100 },
                    { title: '姓名', dataIndex: 'name', width: 90 },
                    { title: '性别', dataIndex: 'gender', width: 60 },
                    { title: '身高(cm)', dataIndex: 'height_cm', width: 85, render: (v: number | null) => (v != null ? v : '-') },
                    { title: '体重(kg)', dataIndex: 'weight_kg', width: 85, render: (v: number | null) => (v != null ? v : '-') },
                    { title: '部门', dataIndex: 'department', width: 120 },
                    { title: '原工序', dataIndex: 'station', width: 90 },
                    { title: '班次', dataIndex: 'shift', width: 80, render: (v: string) => <Tag>{v}</Tag> },
                    {
                      title: '匹配技能', key: 'matched', width: 180,
                      render: (_: any, r: Candidate) => (
                        <Space size={4}>
                          <Tag color="blue">{r.matched_skill.category}·{r.matched_skill.name}</Tag>
                          <Tag color={SKILL_COLORS[r.matched_skill.level]}>{r.matched_skill.level}</Tag>
                        </Space>
                      ),
                    },
                  ]}
                />
              ) : (
                <Empty description={candidatesLoading ? '查询中...' : '请选择条件后点击查询'} />
              )}
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

      {/* 员工详情抽屉 */}
      <Drawer
        title={<span><UserOutlined /> 员工档案 {currentEmp ? `- ${currentEmp.name}` : ''}</span>}
        width={520}
        open={detailVisible}
        onClose={() => setDetailVisible(false)}
      >
        {currentEmp && (
          <>
            <Descriptions column={2} size="small" bordered style={{ marginBottom: 20 }}>
              <Descriptions.Item label="工号">{currentEmp.employee_code}</Descriptions.Item>
              <Descriptions.Item label="姓名">{currentEmp.name}</Descriptions.Item>
              <Descriptions.Item label="性别">{currentEmp.gender}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={STATUS_MAP[currentEmp.status]?.color}>{STATUS_MAP[currentEmp.status]?.text || currentEmp.status}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="身高">{currentEmp.height_cm != null ? `${currentEmp.height_cm} cm` : '-'}</Descriptions.Item>
              <Descriptions.Item label="体重">{currentEmp.weight_kg != null ? `${currentEmp.weight_kg} kg` : '-'}</Descriptions.Item>
              <Descriptions.Item label="部门">{currentEmp.department}</Descriptions.Item>
              <Descriptions.Item label="工序/岗位">{currentEmp.station}</Descriptions.Item>
              <Descriptions.Item label="职位">{currentEmp.position}</Descriptions.Item>
              <Descriptions.Item label="班次">{currentEmp.shift}</Descriptions.Item>
              <Descriptions.Item label="综合技能等级">
                <Tag color={SKILL_COLORS[currentEmp.skill_level]}>{currentEmp.skill_level}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="入职日期">{currentEmp.hire_date || '-'}</Descriptions.Item>
            </Descriptions>

            <Card
              size="small"
              title={<span><SafetyCertificateOutlined /> 内部工序技能</span>}
              extra={<Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddSkillVisible(true)}>添加技能</Button>}
            >
              {empSkillsLoading ? (
                <div style={{ textAlign: 'center', padding: 16 }}>加载中...</div>
              ) : empSkills.length === 0 ? (
                <Empty description="暂无技能记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                <Space direction="vertical" style={{ width: '100%' }} size={8}>
                  {empSkills.map(s => (
                    <div key={s.skill_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 10px', background: '#fafafa', borderRadius: 6 }}>
                      <Space>
                        <Tag color="blue">{s.category}</Tag>
                        <span style={{ fontWeight: 500 }}>{s.name}</span>
                        <Tag color={SKILL_COLORS[s.level]}>{s.level}</Tag>
                        {!s.is_valid && <Tag color="error">已过期</Tag>}
                      </Space>
                      <Popconfirm title="确认移除该技能？" onConfirm={() => handleRemoveSkill(s.skill_id)} okText="移除" cancelText="取消">
                        <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                      </Popconfirm>
                    </div>
                  ))}
                </Space>
              )}
            </Card>
          </>
        )}
      </Drawer>

      {/* 添加技能弹窗 */}
      <Modal
        title="添加内部工序技能"
        open={addSkillVisible}
        onOk={handleAddSkill}
        onCancel={() => setAddSkillVisible(false)}
        okText="分配"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size={12}>
          <div>
            <div style={{ marginBottom: 6 }}>技能（按工序大类分组）</div>
            <Select showSearch placeholder="选择技能" style={{ width: '100%' }} value={newSkillId}
              onChange={v => setNewSkillId(v)} optionFilterProp="label" options={groupedSkillOptions} />
          </div>
          <div>
            <div style={{ marginBottom: 6 }}>技能等级</div>
            <Select style={{ width: '100%' }} value={newSkillLevel} onChange={v => setNewSkillLevel(v)} options={LEVEL_OPTIONS} />
          </div>
        </Space>
      </Modal>
    </div>
  )
}
